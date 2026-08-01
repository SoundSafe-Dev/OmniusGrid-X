"""
User Context API Endpoints

API endpoints for managing user context, priorities, and goals.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict, Field
import structlog

from app.db.database import get_db
from app.api.auth import get_current_active_user
from app.db.models import User

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/user", tags=["User Context"])


# ==================== Request/Response Schemas ====================

class UserContextResponse(BaseModel):
    """Response for user context"""
    id: str
    email: str
    full_name: Optional[str]
    role: str
    department: Optional[str]
    priorities: List[str]
    user_context: Dict[str, Any]
    user_goals: List[Dict[str, Any]]


class UpdateUserContextRequest(BaseModel):
    """Request for updating user context"""
    model_config = ConfigDict(extra="forbid")

    department: Optional[str] = Field(None, description="User department")
    priorities: Optional[List[str]] = Field(None, description="User priorities")


class UserGoalRequest(BaseModel):
    """Request for creating/updating a user goal"""
    title: str = Field(..., description="Goal title")
    progress: int = Field(default=0, ge=0, le=100, description="Goal progress percentage")
    deadline: Optional[str] = Field(None, description="Goal deadline (ISO format)")


class UserGoalResponse(BaseModel):
    """Response for a user goal"""
    id: str
    title: str
    progress: int
    deadline: Optional[str]


# ==================== User Context Endpoints ====================

@router.get("/context", response_model=UserContextResponse)
async def get_user_context(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current user's context and goals.
    """
    logger.info("get_user_context", user_id=str(current_user.id))
    
    # Refresh user from database to get latest data
    query = select(User).where(User.id == current_user.id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return UserContextResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role or "operator",
        department=user.department,
        priorities=user.priorities or [],
        user_context=user.user_context or {},
        user_goals=user.user_goals or []
    )


@router.put("/context", response_model=UserContextResponse)
async def update_user_context(
    request: UpdateUserContextRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update user context (department and priorities).
    """
    logger.info("update_user_context", user_id=str(current_user.id))
    
    # Get user
    query = select(User).where(User.id == current_user.id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update fields
    if request.department is not None:
        user.department = request.department
    if request.priorities is not None:
        user.priorities = request.priorities
    
    user.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(user)
    
    return UserContextResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        priorities=user.priorities or [],
        user_context=user.user_context or {},
        user_goals=user.user_goals or []
    )


# ==================== User Goals Endpoints ====================

@router.post("/goals", response_model=UserContextResponse)
async def add_user_goal(
    request: UserGoalRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Add a new goal to the user's goals.
    """
    logger.info("add_user_goal", user_id=str(current_user.id), title=request.title)
    
    # Get user
    query = select(User).where(User.id == current_user.id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # THIS ENDPOINT HAD NEVER ONCE CREATED A GOAL. The id was `str(UUID())`, and
    # `uuid.UUID` takes no zero-argument form — it raises
    #
    #     TypeError: one of the hex, bytes, bytes_le, fields, or int arguments must be given
    #
    # on every call, whatever the request said. So `POST /api/v1/user/goals` answered 500
    # to every caller since it was written, `userContext.ts:69` calls it from the UI, and
    # because nothing could ever be created the PUT and DELETE below could only ever
    # answer 404. The whole goals feature was dead, and the only `UUID()` in the codebase
    # is what killed it. Found by the contract gate (FS-259).
    new_goal = {
        "id": str(uuid4()),
        "title": request.title,
        "progress": request.progress,
        "deadline": request.deadline,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # REASSIGNED, NOT APPENDED TO, and that is load-bearing. `users.user_goals` is a plain
    # `Column(JSON)` with no `MutableList`, so SQLAlchemy does not see an in-place
    # `.append()` — the attribute is never marked dirty, no UPDATE is emitted, and the
    # `refresh()` below then reloads the row without the goal. The caller gets a 200 and
    # their goal is gone.
    #
    # The old code guarded `if user.user_goals is None: user.user_goals = []` first, which
    # looks like it rescues the case — an assignment DOES flag the attribute, and the
    # append then lands on that same list. But `users.user_goals` is
    # `Column(JSON, default=[])`, so every user created through the ORM already holds `[]`
    # rather than NULL and that branch never runs. Measured, not reasoned: reverting to
    # `.append()` loses the FIRST goal too, not merely the second.
    #
    # `delete_user_goal` two functions down already builds a new list and assigns it. It
    # was correct all along, in the same file, which is what makes these two readable as
    # slips rather than as a misunderstanding.
    user.user_goals = list(user.user_goals or []) + [new_goal]

    user.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(user)
    
    return UserContextResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        priorities=user.priorities or [],
        user_context=user.user_context or {},
        user_goals=user.user_goals or []
    )


@router.put("/goals/{goal_id}", response_model=UserContextResponse)
async def update_user_goal(
    goal_id: str,
    request: UserGoalRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing user goal.
    """
    logger.info("update_user_goal", user_id=str(current_user.id), goal_id=goal_id)
    
    # Get user
    query = select(User).where(User.id == current_user.id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Find and update goal
    if user.user_goals is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    # A NEW LIST, for the same reason as the create above: `users.user_goals` is a plain
    # `Column(JSON)`, so mutating `goal["title"]` in place leaves the attribute clean and
    # `commit()` writes nothing. The old code then called `refresh()`, which reloaded the
    # unmodified row — so the endpoint returned 200 carrying the operator's PREVIOUS
    # values, which reads as an edit that was accepted and then reverted itself.
    updated = []
    goal_found = False
    for goal in user.user_goals:
        if goal.get("id") == goal_id:
            goal = {
                **goal,
                "title": request.title,
                "progress": request.progress,
                "deadline": request.deadline,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            goal_found = True
        updated.append(goal)

    if not goal_found:
        raise HTTPException(status_code=404, detail="Goal not found")

    user.user_goals = updated

    user.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(user)
    
    return UserContextResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        priorities=user.priorities or [],
        user_context=user.user_context or {},
        user_goals=user.user_goals or []
    )


@router.delete("/goals/{goal_id}", response_model=UserContextResponse)
async def delete_user_goal(
    goal_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a user goal.
    """
    logger.info("delete_user_goal", user_id=str(current_user.id), goal_id=goal_id)
    
    # Get user
    query = select(User).where(User.id == current_user.id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Find and remove goal
    if user.user_goals is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    original_length = len(user.user_goals)
    user.user_goals = [g for g in user.user_goals if g.get("id") != goal_id]
    
    if len(user.user_goals) == original_length:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    user.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(user)
    
    return UserContextResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        priorities=user.priorities or [],
        user_context=user.user_context or {},
        user_goals=user.user_goals or []
    )
