"""API routes for command execution"""

from typing import Optional, Dict, Any, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db, AsyncSessionLocal  # noqa: F401
from app.core.tenant import tenant_session
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.db.models import Command, Asset, User
from app.api.auth import get_current_active_user
from app.middleware.rbac import require_admin, require_operator_or_admin
from app.services.command_executor import command_executor, CommandStatus
from app.services.websocket_manager import websocket_manager

router = APIRouter()


class CommandSubmitRequest(BaseModel):
    """Request to submit a new command"""

    #: TYPED, not `str`. `assets.id` is a UUID column, so `WHERE id = ''` is an asyncpg
    #: type error and this endpoint answered 500 to `{"asset_id": ""}` — a malformed id
    #: is the caller's mistake and 422 is what the schema already promised. Found by the
    #: contract gate (FS-259). `command_executor._uuid` already accepts a UUID object, so
    #: nothing downstream changes, and pydantic still accepts the canonical string form
    #: every existing client sends.
    asset_id: UUID = Field(..., description="Target asset ID")
    command_type: str = Field(default="operator", description="Type: tactical, operator, system")
    action_id: str = Field(..., description="Action identifier: set_speed, pause_job, etc.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Command parameters")
    timeout_seconds: Optional[int] = Field(
        default=None,
        ge=1,
        description="Custom timeout",
    )


class CommandResponse(BaseModel):
    """Command response"""
    command_id: str
    status: str
    asset_id: str
    action: str
    issued_at: Optional[str]
    executed_at: Optional[str]
    result: Optional[Dict]


class CommandSubmitResponse(BaseModel):
    """Command submission response"""
    command_id: str
    status: str
    message: str


class CommandCancelled(BaseModel):
    """`command_id` is typed `UUID`, not `str`.

    The handler returns the PATH PARAMETER, which FastAPI has already parsed into a
    `uuid.UUID` — pydantic v2 does not coerce that to `str`, so a `str` field here would
    have made every successful cancellation a 500. The identical mistake on
    `DELETE /notifications/subscriptions/{id}` is the first defect this burn-down found.
    `UUID` serialises to the same JSON string.
    """

    message: str
    command_id: UUID


class CommandQueueStatus(BaseModel):
    """`pending_count` is the CALLER'S organisation; the other two are executor config."""

    pending_count: int
    max_retries: int
    default_timeout: int


class EmergencyStopAccepted(BaseModel):
    """`command_id` is a `str` here and a `UUID` on cancel, because the sources differ:
    `submit_command` returns `str(uuid4())`, while cancel echoes a parsed path param.
    Naming them after their actual types rather than after each other."""

    command_id: str
    status: str
    message: str
    priority: str


@router.post("/submit", response_model=CommandSubmitResponse, summary="Submit command to asset", description="Submit a new command for execution on an industrial asset. Commands are queued and executed asynchronously with automatic retries.\n\n**Common actions:**\n- `set_speed`: Adjust print/processing speed (params: speed_percent)\n- `pause_job`: Pause current operation\n- `resume_job`: Resume paused operation\n- `emergency_stop`: Immediate stop (safety critical, admin only)\n- `set_temperature`: Adjust nozzle/bed temp (params: target_temp, component)", dependencies=[Depends(require_operator_or_admin)])
async def submit_command(
    request: CommandSubmitRequest,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
):
    """
    Submit a new command for execution on an asset.
    
    Common actions:
    - `set_speed`: Adjust print/processing speed (params: speed_percent)
    - `pause_job`: Pause current operation
    - `resume_job`: Resume paused operation
    - `emergency_stop`: Immediate stop (safety critical)
    - `set_temperature`: Adjust nozzle/bed temp (params: target_temp, component)
    """
    if request.action_id == "emergency_stop" and current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Emergency stop requires admin role"
        )
    
    # Verify asset exists and user has access
    # tenant_session, NOT AsyncSessionLocal. `assets` is FORCE ROW LEVEL SECURITY;
    # a plain session sets no app.current_org_id, so the policy matched nothing, the
    # lookup below returned None and this endpoint answered 404 for EVERY asset —
    # including the caller's own. Verified against a real database.
    async with tenant_session(org_id) as session:
        result = await session.execute(
            select(Asset).where(Asset.id == request.asset_id)
        )
        asset = result.scalar_one_or_none()
        
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        # Verify user has access to this asset (same organization)
        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied: asset belongs to different organization")
    
    # Submit command
    command_id = await command_executor.submit_command(
        asset_id=request.asset_id,
        command_type=request.command_type,
        action_id=request.action_id,
        parameters=request.parameters,
        issued_by=str(current_user.id),
        organization_id=str(asset.organization_id),
        timeout_seconds=request.timeout_seconds
    )
    
    return {
        "command_id": command_id,
        "status": CommandStatus.PENDING.value,
        "message": f"Command {request.action_id} queued for asset"
    }


@router.get("/status/{command_id}", response_model=CommandResponse)
async def get_command_status(
    command_id: UUID,
    current_user = Depends(get_current_active_user)
):
    """Get status of a specific command"""
    status = await command_executor.get_command_status(
        command_id,
        organization_id=str(current_user.organization_id),
    )
    
    if not status:
        raise HTTPException(status_code=404, detail="Command not found")
    
    return status


@router.post("/cancel/{command_id}", response_model=CommandCancelled, dependencies=[Depends(require_operator_or_admin)])
async def cancel_command(
    command_id: UUID,
    current_user: User = Depends(get_current_active_user)
):
    """Cancel a pending or executing command"""
    success = await command_executor.cancel_command(
        command_id,
        cancelled_by=str(current_user.id),
        organization_id=str(current_user.organization_id),
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Command not found or cannot be cancelled"
        )
    
    return {"message": "Command cancelled", "command_id": command_id}


@router.get("/asset/{asset_id}", response_model=List[CommandResponse])
async def get_asset_commands(
    asset_id: UUID,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, description="Maximum rows to return."),
    current_user = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
    org_id: UUID = Depends(get_tenant_org_id),
):
    """Get command history for an asset"""
    # Verify asset access
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset or asset.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Build query
    query = select(Command).where(Command.asset_id == asset_id)
    
    if status:
        query = query.where(Command.status == status)
    
    query = query.order_by(Command.issued_at.desc()).limit(limit)
    
    result = await db.execute(query)
    commands = result.scalars().all()
    
    return [
        {
            "command_id": cmd.id,
            "status": cmd.status,
            "asset_id": str(cmd.asset_id),
            "action": cmd.action_id,
            "issued_at": cmd.issued_at.isoformat() if cmd.issued_at else None,
            "executed_at": cmd.executed_at.isoformat() if cmd.executed_at else None,
            "result": cmd.result
        }
        for cmd in commands
    ]


@router.get("/queue/status", response_model=CommandQueueStatus)
async def get_queue_status(
    current_user = Depends(get_current_active_user)
):
    """Get current command queue status"""
    return {
        "pending_count": await command_executor.get_pending_count(
            organization_id=str(current_user.organization_id)
        ),
        "max_retries": command_executor._max_retries,
        "default_timeout": command_executor._timeout_seconds
    }


@router.post("/asset/{asset_id}/emergency-stop", response_model=EmergencyStopAccepted, dependencies=[Depends(require_admin)])
async def emergency_stop(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
):
    """
    Emergency stop - immediately halt asset operation.
    High priority command that bypasses normal queue.
    Requires admin role.
    """
    # tenant_session, NOT AsyncSessionLocal. `assets` is FORCE ROW LEVEL SECURITY;
    # a plain session sets no app.current_org_id, so the policy matched nothing, the
    # lookup below returned None and this endpoint answered 404 for EVERY asset —
    # including the caller's own. Verified against a real database.
    async with tenant_session(org_id) as session:
        result = await session.execute(
            select(Asset).where(Asset.id == asset_id)
        )
        asset = result.scalar_one_or_none()
        
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        # Verify user has access to this asset (same organization)
        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied: asset belongs to different organization")
    
    # Submit with high priority (short timeout)
    command_id = await command_executor.submit_command(
        asset_id=asset_id,
        command_type="system",
        action_id="emergency_stop",
        parameters={"triggered_by": str(current_user.id), "reason": "operator_initiated"},
        issued_by=str(current_user.id),
        organization_id=str(asset.organization_id),
        timeout_seconds=5  # Emergency commands get 5 second timeout
    )
    
    return {
        "command_id": command_id,
        "status": CommandStatus.PENDING.value,
        "message": "Emergency stop initiated",
        "priority": "critical"
    }
