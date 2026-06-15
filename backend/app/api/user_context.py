"""
User Context API Endpoints

API endpoints for managing user context, priorities, and goals.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
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
    
    user.updated_at = datetime.utcnow()
    
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
    
    # Create new goal
    new_goal = {
        "id": str(UUID()),
        "title": request.title,
        "progress": request.progress,
        "deadline": request.deadline,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Add to user goals
    if user.user_goals is None:
        user.user_goals = []
    user.user_goals.append(new_goal)
    
    user.updated_at = datetime.utcnow()
    
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
    
    goal_found = False
    for goal in user.user_goals:
        if goal.get("id") == goal_id:
            goal["title"] = request.title
            goal["progress"] = request.progress
            goal["deadline"] = request.deadline
            goal["updated_at"] = datetime.utcnow().isoformat()
            goal_found = True
            break
    
    if not goal_found:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    user.updated_at = datetime.utcnow()
    
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
    
    user.updated_at = datetime.utcnow()
    
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
