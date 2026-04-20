"""API routes for command execution"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db, AsyncSessionLocal
from app.db.models import Command, Asset
from app.api.auth import get_current_active_user
from app.services.command_executor import command_executor, CommandStatus
from app.services.websocket_manager import websocket_manager

router = APIRouter()


class CommandSubmitRequest(BaseModel):
    """Request to submit a new command"""
    asset_id: str = Field(..., description="Target asset ID")
    command_type: str = Field(default="operator", description="Type: tactical, operator, system")
    action_id: str = Field(..., description="Action identifier: set_speed, pause_job, etc.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Command parameters")
    timeout_seconds: Optional[int] = Field(default=None, description="Custom timeout")


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


@router.post("/submit", response_model=CommandSubmitResponse)
async def submit_command(
    request: CommandSubmitRequest,
    current_user = Depends(get_current_active_user)
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
    # Verify asset exists and user has access
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Asset).where(Asset.id == request.asset_id)
        )
        asset = result.scalar_one_or_none()
        
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        # TODO: Verify user has permission for this asset
        # For now, allow if same organization
        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")
    
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
    command_id: str,
    current_user = Depends(get_current_active_user)
):
    """Get status of a specific command"""
    status = await command_executor.get_command_status(command_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Command not found")
    
    return status


@router.post("/cancel/{command_id}")
async def cancel_command(
    command_id: str,
    current_user = Depends(get_current_active_user)
):
    """Cancel a pending or executing command"""
    success = await command_executor.cancel_command(
        command_id,
        cancelled_by=str(current_user.id)
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Command not found or cannot be cancelled"
        )
    
    return {"message": "Command cancelled", "command_id": command_id}


@router.get("/asset/{asset_id}", response_model=List[CommandResponse])
async def get_asset_commands(
    asset_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    current_user = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
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


@router.get("/queue/status")
async def get_queue_status(
    current_user = Depends(get_current_active_user)
):
    """Get current command queue status"""
    return {
        "pending_count": command_executor.get_pending_count(),
        "max_retries": command_executor._max_retries,
        "default_timeout": command_executor._timeout_seconds
    }


@router.post("/asset/{asset_id}/emergency-stop")
async def emergency_stop(
    asset_id: str,
    current_user = Depends(get_current_active_user)
):
    """
    Emergency stop - immediately halt asset operation.
    High priority command that bypasses normal queue.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Asset).where(Asset.id == asset_id)
        )
        asset = result.scalar_one_or_none()
        
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
    
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
        "status": "executing",
        "message": "Emergency stop initiated",
        "priority": "critical"
    }
