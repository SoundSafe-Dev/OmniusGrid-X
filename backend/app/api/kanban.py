"""
Kanban Task Management API Endpoints
Actionable decision-making kanban system for OmniusGrid
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db, AsyncSessionLocal
from app.db.models import (
    TaskBoard, TaskColumn, Task, TaskComment, TaskTimer, 
    TaskRule, TaskEscalation, Asset, Alarm, User, Organization, Command
)
from app.models.schemas import (
    TaskBoardCreate, TaskBoardResponse, TaskColumnCreate, TaskColumnResponse,
    TaskCreate, TaskUpdate, TaskResponse, TaskMoveRequest, TaskApprovalRequest,
    TaskCommentBase, TaskCommentCreate, TaskCommentResponse, TaskTimerStart, TaskTimerStop, TaskTimerResponse,
    TaskRuleCreate, TaskRuleUpdate, TaskRuleResponse, TaskRuleTestRequest, TaskRuleTestResponse,
    KanbanViewFilter, KanbanBoardData, KanbanMetrics, KanbanWorkloadResponse,
    TaskEscalationResponse, TaskChecklistItem
)
from app.api.auth import get_current_active_user
from app.services.websocket_manager import websocket_manager

router = APIRouter()


# ==================== Helper Functions ====================

async def get_organization_board(session: AsyncSession, organization_id: str) -> TaskBoard:
    """Get or create the unified kanban board for an organization"""
    result = await session.execute(
        select(TaskBoard).where(
            and_(
                TaskBoard.organization_id == organization_id,
                TaskBoard.is_active == True
            )
        ).order_by(TaskBoard.created_at)
    )
    board = result.scalar_one_or_none()
    
    # If no active board exists, check for inactive boards and deactivate them, then create a new one
    if not board:
        # Check if there are any boards (active or inactive) for this org
        all_boards_result = await session.execute(
            select(TaskBoard).where(TaskBoard.organization_id == organization_id)
        )
        all_boards = all_boards_result.scalars().all()
        
        if all_boards:
            # Deactivate all existing boards
            for existing_board in all_boards:
                existing_board.is_active = False
            await session.commit()
        
        # Create default board
        board = TaskBoard(
            organization_id=organization_id,
            name="Operations Board",
            board_type="unified",
            default_view_config={
                "default_filter": "all",
                "default_group_by": None,
                "show_wip_limits": True,
                "show_completed": False
            }
        )
        session.add(board)
        await session.commit()
        await session.refresh(board)
        
        # Create standard 6 columns
        columns = [
            TaskColumn(board_id=board.id, name="Backlog", position=0, column_type="backlog", wip_limit=50, color="#6B7280"),
            TaskColumn(board_id=board.id, name="Triage", position=1, column_type="triage", wip_limit=20, color="#F59E0B"),
            TaskColumn(board_id=board.id, name="In Progress", position=2, column_type="in_progress", wip_limit=10, color="#3B82F6"),
            TaskColumn(board_id=board.id, name="Review", position=3, column_type="review", wip_limit=15, color="#8B5CF6"),
            TaskColumn(board_id=board.id, name="Rejected", position=4, column_type="rejected", wip_limit=10, color="#EF4444"),
            TaskColumn(board_id=board.id, name="Done", position=5, column_type="done", wip_limit=100, color="#10B981"),
        ]
        for col in columns:
            session.add(col)
        await session.commit()
    
    return board


async def get_column_by_type(session: AsyncSession, board_id: str, column_type: str) -> TaskColumn:
    """Get column by type for a board"""
    result = await session.execute(
        select(TaskColumn).where(
            and_(
                TaskColumn.board_id == board_id,
                TaskColumn.column_type == column_type
            )
        )
    )
    return result.scalar_one_or_none()


async def log_task_comment(
    session: AsyncSession,
    task_id: str,
    user_id: Optional[str],
    content: str,
    comment_type: str = "system",
    extra_data: Dict[str, Any] = None
):
    """Log a system comment for task activity"""
    comment = TaskComment(
        task_id=task_id,
        user_id=user_id,
        content=content,
        comment_type=comment_type,
        extra_data=extra_data or {}
    )
    session.add(comment)


async def broadcast_task_update(
    organization_id: str,
    event_type: str,
    task_data: Dict[str, Any]
):
    """Broadcast task update via WebSocket"""
    await websocket_manager.broadcast_to_org(
        organization_id=organization_id,
        message={
            "type": f"kanban_{event_type}",
            "data": task_data,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# ==================== Board Management ====================

@router.get("/board", response_model=KanbanBoardData)
async def get_kanban_board(
    filters: KanbanViewFilter = Depends(),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get the unified kanban board with columns and tasks.
    Supports filtering by asset, workcell, type, priority, assignee.
    """
    # Get or create board
    board = await get_organization_board(session, current_user.organization_id)
    
    # Get columns
    result = await session.execute(
        select(TaskColumn).where(TaskColumn.board_id == board.id).order_by(TaskColumn.position)
    )
    columns = result.scalars().all()
    
    # Build task query with filters
    query = select(Task).where(Task.board_id == board.id)
    
    if filters.asset_id:
        query = query.where(Task.asset_id == filters.asset_id)
    if filters.task_type:
        query = query.where(Task.task_type == filters.task_type)
    if filters.priority:
        query = query.where(Task.priority == filters.priority)
    if filters.assignee_id:
        query = query.where(Task.assigned_to == filters.assignee_id)
    if filters.status:
        query = query.where(Task.status == filters.status)
    if filters.date_from:
        query = query.where(Task.created_at >= filters.date_from)
    if filters.date_to:
        query = query.where(Task.created_at <= filters.date_to)
    
    # Role-based filtering
    if current_user.role == "operator":
        # Operators see tasks for their assigned assets or unassigned tasks
        query = query.where(
            or_(
                Task.assigned_to == current_user.id,
                Task.assigned_to.is_(None)
            )
        )
    
    query = query.order_by(Task.position)
    result = await session.execute(query)
    tasks = result.scalars().all()
    
    # Get task counts for columns
    column_ids = [col.id for col in columns]
    count_query = select(Task.column_id, func.count(Task.id)).where(
        Task.column_id.in_(column_ids)
    ).group_by(Task.column_id)
    count_result = await session.execute(count_query)
    task_counts = {col_id: count for col_id, count in count_result.all()}
    
    # Build response
    column_responses = []
    for col in columns:
        col_dict = {
            "id": col.id,
            "board_id": col.board_id,
            "name": col.name,
            "position": col.position,
            "wip_limit": col.wip_limit,
            "column_type": col.column_type,
            "color": col.color,
            "is_collapsed": col.is_collapsed,
            "auto_archive_days": col.auto_archive_days,
            "created_at": col.created_at,
            "updated_at": col.updated_at,
            "task_count": task_counts.get(col.id, 0)
        }
        column_responses.append(col_dict)
    
    return {
        "board": board,
        "columns": column_responses,
        "tasks": tasks,
        "view_config": filters.dict()
    }


@router.post("/board/view", response_model=KanbanBoardData)
async def update_board_view(
    filters: KanbanViewFilter,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update board view with new filters"""
    return await get_kanban_board(filters, session, current_user)


# ==================== Task CRUD ====================

@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(
    board_id: Optional[UUID] = None,
    column_id: Optional[UUID] = None,
    assignee_id: Optional[UUID] = None,
    task_type: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    approval_status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """List tasks with filtering"""
    query = select(Task).where(Task.board_id.isnot(None))
    
    if board_id:
        query = query.where(Task.board_id == board_id)
    else:
        # Default to user's org board
        board = await get_organization_board(session, current_user.organization_id)
        query = query.where(Task.board_id == board.id)
    
    if column_id:
        query = query.where(Task.column_id == column_id)
    if assignee_id:
        query = query.where(Task.assigned_to == assignee_id)
    if task_type:
        query = query.where(Task.task_type == task_type)
    if priority:
        query = query.where(Task.priority == priority)
    if status:
        query = query.where(Task.status == status)
    if approval_status:
        query = query.where(Task.approval_status == approval_status)
    
    query = query.order_by(Task.position).offset(offset).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    task_data: TaskCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create a new task"""
    # Validate board exists
    result = await session.execute(
        select(TaskBoard).where(TaskBoard.id == task_data.board_id)
    )
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    # Validate column exists and belongs to board
    result = await session.execute(
        select(TaskColumn).where(
            and_(
                TaskColumn.id == task_data.column_id,
                TaskColumn.board_id == task_data.board_id
            )
        )
    )
    column = result.scalar_one_or_none()
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")
    
    # Get max position for ordering
    result = await session.execute(
        select(func.max(Task.position)).where(Task.column_id == task_data.column_id)
    )
    max_position = result.scalar() or 0
    
    # Create task
    task = Task(
        board_id=task_data.board_id,
        column_id=task_data.column_id,
        position=max_position + 1,
        title=task_data.title,
        description=task_data.description,
        task_type=task_data.task_type,
        priority=task_data.priority,
        status="ready" if task_data.column_id != column.id else "draft",
        assigned_to=task_data.assigned_to,
        assigned_by=current_user.id if task_data.assigned_to else None,
        assigned_at=datetime.utcnow() if task_data.assigned_to else None,
        planned_start=task_data.planned_start,
        planned_duration=task_data.planned_duration,
        due_date=task_data.due_date,
        estimated_effort_minutes=task_data.estimated_effort_minutes,
        asset_id=task_data.asset_id,
        operation_id=task_data.operation_id,
        alarm_id=task_data.alarm_id,
        command_id=task_data.command_id,
        parent_task_id=task_data.parent_task_id,
        tags=task_data.tags,
        checklist_items=[item.dict() for item in task_data.checklist_items],
        custom_fields=task_data.custom_fields,
        color_code=task_data.color_code,
        completion_actions=task_data.completion_actions,
        approval_status="approved" if task_data.column_id != column.id else "pending",
        created_by=current_user.id
    )
    
    session.add(task)
    await session.commit()
    await session.refresh(task)
    
    # Log creation
    await log_task_comment(
        session, task.id, current_user.id,
        f"Task created by {current_user.full_name or current_user.email}",
        "system",
        {"created_by": str(current_user.id), "initial_column": column.column_type}
    )
    await session.commit()
    
    # Broadcast creation
    background_tasks.add_task(
        broadcast_task_update,
        str(current_user.organization_id),
        "task_created",
        {"task_id": str(task.id), "title": task.title, "column": column.column_type}
    )
    
    return task


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get task details"""
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task


@router.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    task_update: TaskUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update a task"""
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Track changes for activity log
    changes = []
    
    if task_update.title is not None and task_update.title != task.title:
        changes.append(f"Title changed from '{task.title}' to '{task_update.title}'")
        task.title = task_update.title
    
    if task_update.description is not None:
        changes.append("Description updated")
        task.description = task_update.description
    
    if task_update.priority is not None and task_update.priority != task.priority:
        changes.append(f"Priority changed from {task.priority} to {task_update.priority}")
        task.priority = task_update.priority
    
    if task_update.status is not None and task_update.status != task.status:
        changes.append(f"Status changed from {task.status} to {task_update.status}")
        task.status = task_update.status
    
    if task_update.assigned_to is not None and task_update.assigned_to != task.assigned_to:
        if task.assigned_to is None:
            changes.append(f"Assigned to user {task_update.assigned_to}")
        else:
            changes.append(f"Reassigned from {task.assigned_to} to {task_update.assigned_to}")
        task.assigned_to = task_update.assigned_to
        task.assigned_by = current_user.id
        task.assigned_at = datetime.utcnow()
    
    if task_update.column_id is not None and task_update.column_id != task.column_id:
        # Get old and new column names
        old_col_result = await session.execute(
            select(TaskColumn).where(TaskColumn.id == task.column_id)
        )
        old_col = old_col_result.scalar_one()
        
        new_col_result = await session.execute(
            select(TaskColumn).where(TaskColumn.id == task_update.column_id)
        )
        new_col = new_col_result.scalar_one()
        
        changes.append(f"Moved from '{old_col.name}' to '{new_col.name}'")
        task.column_id = task_update.column_id
        
        # Update position
        if task_update.position is not None:
            task.position = task_update.position
    
    if task_update.progress_percent is not None:
        task.progress_percent = task_update.progress_percent
    
    if task_update.checklist_items is not None:
        task.checklist_items = [item.dict() for item in task_update.checklist_items]
    
    if task_update.custom_fields is not None:
        task.custom_fields = task_update.custom_fields
    
    if task_update.due_date is not None:
        task.due_date = task_update.due_date
    
    if task_update.color_code is not None:
        task.color_code = task_update.color_code
    
    task.updated_at = datetime.utcnow()
    
    await session.commit()
    await session.refresh(task)
    
    # Log changes
    if changes:
        await log_task_comment(
            session, task.id, current_user.id,
            "; ".join(changes),
            "system"
        )
        await session.commit()
    
    # Broadcast update
    background_tasks.add_task(
        broadcast_task_update,
        str(current_user.organization_id),
        "task_updated",
        {"task_id": str(task.id), "changes": changes}
    )
    
    return task


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete/archive a task"""
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Soft delete - move to done column with deleted status
    done_column = await get_column_by_type(session, task.board_id, "done")
    if done_column:
        task.column_id = done_column.id
        task.status = "cancelled"
        task.updated_at = datetime.utcnow()
        
        await log_task_comment(
            session, task.id, current_user.id,
            "Task deleted/archived",
            "system"
        )
        await session.commit()
    
    return {"message": "Task archived"}


# ==================== Task Workflow Actions ====================

@router.post("/tasks/{task_id}/move", response_model=TaskResponse)
async def move_task(
    task_id: str,
    move_request: TaskMoveRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Move task to different column"""
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Validate target column
    result = await session.execute(
        select(TaskColumn).where(TaskColumn.id == move_request.target_column_id)
    )
    target_column = result.scalar_one_or_none()
    
    if not target_column:
        raise HTTPException(status_code=404, detail="Target column not found")
    
    if target_column.board_id != task.board_id:
        raise HTTPException(status_code=400, detail="Cannot move task to different board")
    
    # Get current column for logging
    result = await session.execute(
        select(TaskColumn).where(TaskColumn.id == task.column_id)
    )
    source_column = result.scalar_one()
    
    # Update position
    if move_request.position is not None:
        task.position = move_request.position
    else:
        # Get max position in target column
        result = await session.execute(
            select(func.max(Task.position)).where(Task.column_id == move_request.target_column_id)
        )
        max_pos = result.scalar() or 0
        task.position = max_pos + 1
    
    # Update column
    task.column_id = move_request.target_column_id
    task.updated_at = datetime.utcnow()
    
    # Update status based on column type
    if target_column.column_type == "in_progress" and task.status != "in_progress":
        task.status = "in_progress"
        task.actual_start = datetime.utcnow()
    elif target_column.column_type == "done":
        task.status = "completed"
        task.progress_percent = 100
        task.actual_end = datetime.utcnow()
        task.completed_at = datetime.utcnow()
        task.completed_by = current_user.id
    
    await session.commit()
    await session.refresh(task)
    
    # Log move
    await log_task_comment(
        session, task.id, current_user.id,
        f"Moved from '{source_column.name}' to '{target_column.name}'",
        "status_change",
        {"from_column": source_column.column_type, "to_column": target_column.column_type}
    )
    await session.commit()
    
    # Broadcast move
    background_tasks.add_task(
        broadcast_task_update,
        str(current_user.organization_id),
        "task_moved",
        {
            "task_id": str(task.id),
            "from_column": source_column.column_type,
            "to_column": target_column.column_type
        }
    )
    
    return task


@router.post("/tasks/{task_id}/approve", response_model=TaskResponse)
async def approve_task(
    task_id: str,
    approval: TaskApprovalRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Approve or reject a task from Backlog"""
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Get current column
    result = await session.execute(
        select(TaskColumn).where(TaskColumn.id == task.column_id)
    )
    current_column = result.scalar_one()
    
    if approval.action == "approve":
        # Move to Triage column
        triage_column = await get_column_by_type(session, task.board_id, "triage")
        if not triage_column:
            raise HTTPException(status_code=500, detail="Triage column not found")
        
        task.column_id = triage_column.id
        task.approval_status = "approved"
        task.approved_by = current_user.id
        task.approved_at = datetime.utcnow()
        task.status = "ready"
        
        # Get max position in triage
        result = await session.execute(
            select(func.max(Task.position)).where(Task.column_id == triage_column.id)
        )
        max_pos = result.scalar() or 0
        task.position = max_pos + 1
        
        log_message = f"Task approved by {current_user.full_name or current_user.email}"
        event_type = "task_approved"
        
    elif approval.action == "reject":
        if not approval.reason:
            raise HTTPException(status_code=400, detail="Rejection reason required")
        
        # Move to Rejected column
        rejected_column = await get_column_by_type(session, task.board_id, "rejected")
        if not rejected_column:
            raise HTTPException(status_code=500, detail="Rejected column not found")
        
        task.column_id = rejected_column.id
        task.approval_status = "rejected"
        task.rejection_reason = approval.reason
        task.status = "cancelled"
        
        # Get max position in rejected
        result = await session.execute(
            select(func.max(Task.position)).where(Task.column_id == rejected_column.id)
        )
        max_pos = result.scalar() or 0
        task.position = max_pos + 1
        
        log_message = f"Task rejected by {current_user.full_name or current_user.email}. Reason: {approval.reason}"
        event_type = "task_rejected"
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'approve' or 'reject'")
    
    task.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(task)
    
    # Log action
    await log_task_comment(
        session, task.id, current_user.id,
        log_message,
        "approval_action",
        {"action": approval.action, "reason": approval.reason}
    )
    await session.commit()
    
    # Broadcast
    background_tasks.add_task(
        broadcast_task_update,
        str(current_user.organization_id),
        event_type,
        {"task_id": str(task.id), "action": approval.action}
    )
    
    return task


@router.post("/tasks/{task_id}/start", response_model=TaskResponse)
async def start_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Start work on a task (Triage -> In Progress)"""
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Move to In Progress
    in_progress_column = await get_column_by_type(session, task.board_id, "in_progress")
    if not in_progress_column:
        raise HTTPException(status_code=500, detail="In Progress column not found")
    
    # Update task
    task.column_id = in_progress_column.id
    task.status = "in_progress"
    task.actual_start = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    
    # Get max position
    result = await session.execute(
        select(func.max(Task.position)).where(Task.column_id == in_progress_column.id)
    )
    max_pos = result.scalar() or 0
    task.position = max_pos + 1
    
    await session.commit()
    await session.refresh(task)
    
    # Start timer
    timer = TaskTimer(
        task_id=task.id,
        user_id=current_user.id,
        started_at=datetime.utcnow(),
        is_running=True,
        description="Work started"
    )
    session.add(timer)
    
    # Log
    await log_task_comment(
        session, task.id, current_user.id,
        f"Work started by {current_user.full_name or current_user.email}",
        "system"
    )
    await session.commit()
    
    # Broadcast
    background_tasks.add_task(
        broadcast_task_update,
        str(current_user.organization_id),
        "task_started",
        {"task_id": str(task.id), "started_by": str(current_user.id)}
    )
    
    return task


@router.post("/tasks/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Complete a task (In Progress/Review -> Done)"""
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Move to Done
    done_column = await get_column_by_type(session, task.board_id, "done")
    if not done_column:
        raise HTTPException(status_code=500, detail="Done column not found")
    
    # Stop any running timer
    result = await session.execute(
        select(TaskTimer).where(
            and_(
                TaskTimer.task_id == task_id,
                TaskTimer.is_running == True
            )
        )
    )
    running_timer = result.scalar_one_or_none()
    if running_timer:
        running_timer.is_running = False
        running_timer.ended_at = datetime.utcnow()
        duration = (running_timer.ended_at - running_timer.started_at).total_seconds() / 60
        running_timer.duration_minutes = int(duration)
        task.time_logged_minutes += int(duration)
    
    # Update task
    task.column_id = done_column.id
    task.status = "completed"
    task.progress_percent = 100
    task.actual_end = datetime.utcnow()
    task.completed_at = datetime.utcnow()
    task.completed_by = current_user.id
    task.updated_at = datetime.utcnow()
    
    # Get max position
    result = await session.execute(
        select(func.max(Task.position)).where(Task.column_id == done_column.id)
    )
    max_pos = result.scalar() or 0
    task.position = max_pos + 1
    
    await session.commit()
    await session.refresh(task)
    
    # Log
    await log_task_comment(
        session, task.id, current_user.id,
        f"Task completed by {current_user.full_name or current_user.email}",
        "system",
        {"completion_time": task.actual_end.isoformat() if task.actual_end else None}
    )
    await session.commit()
    
    # Execute completion actions (bidirectional integration)
    if task.completion_actions:
        background_tasks.add_task(
            execute_completion_actions,
            task_id,
            task.completion_actions,
            str(current_user.organization_id)
        )
    
    # Broadcast
    background_tasks.add_task(
        broadcast_task_update,
        str(current_user.organization_id),
        "task_completed",
        {"task_id": str(task.id), "completed_by": str(current_user.id)}
    )
    
    return task


async def execute_completion_actions(task_id: str, actions: Dict[str, Any], organization_id: str):
    """Execute actions when task is completed"""
    results = {}
    
    async with AsyncSessionLocal() as session:
        # Get task for related entities
        result = await session.execute(
            select(Task).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        
        if not task:
            return
        
        # Clear alarm if linked
        if actions.get("clear_alarm") and task.alarm_id:
            try:
                result = await session.execute(
                    select(Alarm).where(Alarm.id == task.alarm_id)
                )
                alarm = result.scalar_one_or_none()
                if alarm and alarm.is_active:
                    alarm.is_active = False
                    alarm.cleared_at = datetime.utcnow()
                    results["alarm_cleared"] = True
                    
                    # Log
                    await log_task_comment(
                        session, task.id, None,
                        f"Linked alarm {task.alarm_id} auto-cleared on task completion",
                        "system"
                    )
            except Exception as e:
                results["alarm_cleared"] = False
                results["alarm_error"] = str(e)
        
        # Execute command if configured
        if actions.get("execute_command"):
            cmd_action = actions["execute_command"]
            try:
                # Queue command via command executor
                from app.services.command_executor import command_executor
                
                command_id = await command_executor.submit_command(
                    asset_id=cmd_action.get("asset_id") or str(task.asset_id),
                    command_type=cmd_action.get("command_type", "system"),
                    action_id=cmd_action.get("action_id"),
                    parameters=cmd_action.get("parameters", {}),
                    organization_id=organization_id
                )
                results["command_executed"] = True
                results["command_id"] = command_id
                
                await log_task_comment(
                    session, task.id, None,
                    f"Auto-executed command: {cmd_action.get('action_id')}",
                    "system"
                )
            except Exception as e:
                results["command_executed"] = False
                results["command_error"] = str(e)
        
        # Update completion result
        task.completion_result = results
        await session.commit()


# ==================== Comments & Activity ====================

@router.get("/tasks/{task_id}/comments", response_model=List[TaskCommentResponse])
async def get_task_comments(
    task_id: str,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get activity feed for a task"""
    result = await session.execute(
        select(TaskComment)
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/tasks/{task_id}/comments", response_model=TaskCommentResponse)
async def add_task_comment(
    task_id: str,
    comment: TaskCommentBase,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Add comment to task"""
    # Validate task exists
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    new_comment = TaskComment(
        task_id=task_id,
        user_id=current_user.id,
        content=comment.content,
        comment_type=comment.comment_type
    )
    session.add(new_comment)
    await session.commit()
    await session.refresh(new_comment)
    
    # Broadcast
    background_tasks.add_task(
        broadcast_task_update,
        str(current_user.organization_id),
        "comment_added",
        {"task_id": str(task_id), "comment_id": str(new_comment.id)}
    )
    
    return new_comment


# ==================== Time Tracking ====================

@router.post("/tasks/{task_id}/timer/start", response_model=TaskTimerResponse)
async def start_task_timer(
    task_id: str,
    timer_data: TaskTimerStart,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Start time tracking for a task"""
    # Check for existing running timer
    result = await session.execute(
        select(TaskTimer).where(
            and_(
                TaskTimer.task_id == task_id,
                TaskTimer.user_id == current_user.id,
                TaskTimer.is_running == True
            )
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(status_code=400, detail="Timer already running for this task")
    
    timer = TaskTimer(
        task_id=task_id,
        user_id=current_user.id,
        started_at=datetime.utcnow(),
        is_running=True,
        description=timer_data.description
    )
    session.add(timer)
    await session.commit()
    await session.refresh(timer)
    
    # Log
    await log_task_comment(
        session, task_id, current_user.id,
        f"Timer started: {timer_data.description or 'Work session'}",
        "time_log"
    )
    await session.commit()
    
    return timer


@router.post("/tasks/{task_id}/timer/stop", response_model=TaskTimerResponse)
async def stop_task_timer(
    task_id: str,
    timer_data: TaskTimerStop,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Stop time tracking for a task"""
    result = await session.execute(
        select(TaskTimer).where(
            and_(
                TaskTimer.task_id == task_id,
                TaskTimer.user_id == current_user.id,
                TaskTimer.is_running == True
            )
        )
    )
    timer = result.scalar_one_or_none()
    
    if not timer:
        raise HTTPException(status_code=404, detail="No running timer found")
    
    timer.is_running = False
    timer.ended_at = datetime.utcnow()
    duration = (timer.ended_at - timer.started_at).total_seconds() / 60
    timer.duration_minutes = int(duration)
    
    if timer_data.description:
        timer.description = timer.description + " - " + timer_data.description if timer.description else timer_data.description
    
    # Update task time logged
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one()
    task.time_logged_minutes += int(duration)
    
    await session.commit()
    await session.refresh(timer)
    
    # Log
    await log_task_comment(
        session, task_id, current_user.id,
        f"Timer stopped. Duration: {int(duration)} minutes",
        "time_log",
        {"duration_minutes": int(duration)}
    )
    await session.commit()
    
    return timer


@router.get("/tasks/{task_id}/time-logs", response_model=List[TaskTimerResponse])
async def get_task_time_logs(
    task_id: str,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get all time logs for a task"""
    result = await session.execute(
        select(TaskTimer)
        .where(TaskTimer.task_id == task_id)
        .order_by(TaskTimer.started_at.desc())
    )
    return result.scalars().all()


# ==================== Metrics & Analytics ====================

@router.get("/metrics", response_model=KanbanMetrics)
async def get_kanban_metrics(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get kanban board metrics"""
    board = await get_organization_board(session, current_user.organization_id)
    
    # Total tasks
    result = await session.execute(
        select(func.count(Task.id)).where(Task.board_id == board.id)
    )
    total_tasks = result.scalar() or 0
    
    # Tasks by column
    result = await session.execute(
        select(TaskColumn.column_type, func.count(Task.id))
        .join(Task, Task.column_id == TaskColumn.id)
        .where(TaskColumn.board_id == board.id)
        .group_by(TaskColumn.column_type)
    )
    tasks_by_column = {col_type: count for col_type, count in result.all()}
    
    # Tasks by priority
    result = await session.execute(
        select(Task.priority, func.count(Task.id))
        .where(Task.board_id == board.id)
        .group_by(Task.priority)
    )
    tasks_by_priority = {priority: count for priority, count in result.all()}
    
    # Tasks awaiting approval (in Backlog)
    backlog_column = await get_column_by_type(session, board.id, "backlog")
    if backlog_column:
        result = await session.execute(
            select(func.count(Task.id)).where(
                and_(
                    Task.board_id == board.id,
                    Task.column_id == backlog_column.id,
                    Task.approval_status == "pending"
                )
            )
        )
        tasks_awaiting_approval = result.scalar() or 0
    else:
        tasks_awaiting_approval = 0
    
    # Overdue tasks
    result = await session.execute(
        select(func.count(Task.id)).where(
            and_(
                Task.board_id == board.id,
                Task.due_date < datetime.utcnow(),
                Task.status != "completed"
            )
        )
    )
    overdue_tasks = result.scalar() or 0
    
    # Tasks completed today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.count(Task.id)).where(
            and_(
                Task.board_id == board.id,
                Task.completed_at >= today_start
            )
        )
    )
    tasks_completed_today = result.scalar() or 0
    
    # Active escalations
    result = await session.execute(
        select(func.count(TaskEscalation.id)).where(
            and_(
                TaskEscalation.resolved_at.is_(None),
                TaskEscalation.triggered_at >= today_start - timedelta(days=7)
            )
        )
    )
    active_escalations = result.scalar() or 0
    
    # Average cycle time (Backlog -> Done)
    result = await session.execute(
        select(func.avg(
            func.extract('epoch', Task.completed_at - Task.created_at) / 60
        )).where(
            and_(
                Task.board_id == board.id,
                Task.status == "completed",
                Task.completed_at.isnot(None)
            )
        )
    )
    avg_cycle_time = result.scalar()
    
    return {
        "total_tasks": total_tasks,
        "tasks_by_column": tasks_by_column,
        "tasks_by_priority": tasks_by_priority,
        "tasks_awaiting_approval": tasks_awaiting_approval,
        "overdue_tasks": overdue_tasks,
        "avg_cycle_time_minutes": float(avg_cycle_time) if avg_cycle_time else None,
        "tasks_completed_today": tasks_completed_today,
        "active_escalations": active_escalations
    }


@router.get("/workload", response_model=KanbanWorkloadResponse)
async def get_workload_distribution(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get workload distribution by assignee"""
    board = await get_organization_board(session, current_user.organization_id)
    
    # Get all users in org with tasks
    result = await session.execute(
        select(User.id, User.full_name)
        .where(User.organization_id == current_user.organization_id)
    )
    users = result.all()
    
    workloads = []
    for user_id, user_name in users:
        # Assigned tasks
        result = await session.execute(
            select(func.count(Task.id)).where(
                and_(
                    Task.board_id == board.id,
                    Task.assigned_to == user_id
                )
            )
        )
        assigned = result.scalar() or 0
        
        # In progress
        result = await session.execute(
            select(func.count(Task.id)).where(
                and_(
                    Task.board_id == board.id,
                    Task.assigned_to == user_id,
                    Task.status == "in_progress"
                )
            )
        )
        in_progress = result.scalar() or 0
        
        # Overdue
        result = await session.execute(
            select(func.count(Task.id)).where(
                and_(
                    Task.board_id == board.id,
                    Task.assigned_to == user_id,
                    Task.due_date < datetime.utcnow(),
                    Task.status != "completed"
                )
            )
        )
        overdue = result.scalar() or 0
        
        # Average completion time
        result = await session.execute(
            select(func.avg(
                func.extract('epoch', Task.completed_at - Task.created_at) / 60
            )).where(
                and_(
                    Task.board_id == board.id,
                    Task.assigned_to == user_id,
                    Task.status == "completed"
                )
            )
        )
        avg_time = result.scalar()
        
        workloads.append({
            "user_id": user_id,
            "user_name": user_name or "Unknown",
            "assigned_tasks": assigned,
            "in_progress_tasks": in_progress,
            "overdue_tasks": overdue,
            "avg_completion_time": float(avg_time) if avg_time else None
        })
    
    return {"workloads": workloads}


# ==================== Rules Management ====================

@router.get("/rules", response_model=List[TaskRuleResponse])
async def list_task_rules(
    active_only: bool = False,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """List all task automation rules"""
    query = select(TaskRule).where(
        TaskRule.organization_id == current_user.organization_id
    )
    
    if active_only:
        query = query.where(TaskRule.is_active == True)
    
    query = query.order_by(TaskRule.created_at.desc())
    result = await session.execute(query)
    return result.scalars().all()


@router.post("/rules", response_model=TaskRuleResponse)
async def create_task_rule(
    rule_data: TaskRuleCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create a new automation rule"""
    rule = TaskRule(
        organization_id=current_user.organization_id,
        rule_name=rule_data.rule_name,
        description=rule_data.description,
        trigger_type=rule_data.trigger_type,
        trigger_conditions=rule_data.trigger_conditions,
        target_board_id=rule_data.target_board_id,
        target_column_id=rule_data.target_column_id,
        task_template=rule_data.task_template,
        auto_approve_emergency=rule_data.auto_approve_emergency,
        auto_approve_timeout_minutes=rule_data.auto_approve_timeout_minutes,
        assignee_rule=rule_data.assignee_rule,
        specific_assignee_id=rule_data.specific_assignee_id,
        notify_users=rule_data.notify_users,
        escalation_config=rule_data.escalation_config,
        completion_actions=rule_data.completion_actions,
        is_system_rule=False,
        created_by=current_user.id
    )
    
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    
    return rule


@router.put("/rules/{rule_id}", response_model=TaskRuleResponse)
async def update_task_rule(
    rule_id: str,
    rule_update: TaskRuleUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update an automation rule"""
    result = await session.execute(
        select(TaskRule).where(
            and_(
                TaskRule.id == rule_id,
                TaskRule.organization_id == current_user.organization_id
            )
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Prevent editing system rules
    if rule.is_system_rule and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Cannot edit system rules")
    
    if rule_update.rule_name is not None:
        rule.rule_name = rule_update.rule_name
    if rule_update.description is not None:
        rule.description = rule_update.description
    if rule_update.is_active is not None:
        rule.is_active = rule_update.is_active
    if rule_update.trigger_conditions is not None:
        rule.trigger_conditions = rule_update.trigger_conditions
    if rule_update.task_template is not None:
        rule.task_template = rule_update.task_template
    if rule_update.auto_approve_emergency is not None:
        rule.auto_approve_emergency = rule_update.auto_approve_emergency
    if rule_update.auto_approve_timeout_minutes is not None:
        rule.auto_approve_timeout_minutes = rule_update.auto_approve_timeout_minutes
    if rule_update.assignee_rule is not None:
        rule.assignee_rule = rule_update.assignee_rule
    if rule_update.escalation_config is not None:
        rule.escalation_config = rule_update.escalation_config
    
    rule.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(rule)
    
    return rule


@router.post("/rules/{rule_id}/test", response_model=TaskRuleTestResponse)
async def test_task_rule(
    rule_id: str,
    test_data: TaskRuleTestRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Test a rule against sample data"""
    result = await session.execute(
        select(TaskRule).where(
            and_(
                TaskRule.id == rule_id,
                TaskRule.organization_id == current_user.organization_id
            )
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Evaluate conditions against sample data
    matched_conditions = []
    would_trigger = True
    
    for key, expected_value in rule.trigger_conditions.items():
        actual_value = test_data.sample_data.get(key)
        if actual_value == expected_value:
            matched_conditions.append(f"{key} = {expected_value}")
        else:
            would_trigger = False
            matched_conditions.append(f"{key}: expected {expected_value}, got {actual_value}")
    
    # Generate preview
    preview = None
    if would_trigger:
        preview = {
            "title": rule.task_template.get("title", "Untitled Task"),
            "description": rule.task_template.get("description", ""),
            "priority": rule.task_template.get("priority", "medium"),
            "task_type": rule.task_template.get("task_type", "custom"),
            "assignee_rule": rule.assignee_rule,
            "auto_approve": rule.auto_approve_emergency
        }
    
    return {
        "would_trigger": would_trigger,
        "matched_conditions": matched_conditions,
        "generated_task_preview": preview
    }


@router.get("/rules/premade", response_model=List[TaskRuleResponse])
async def get_premade_rules(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get list of available premade system rules"""
    # Return system rule templates that can be activated
    premade_templates = [
        {
            "id": "template-001",
            "rule_name": "Critical Alarm Response",
            "description": "Auto-create high-priority task when critical alarms fire",
            "trigger_type": "alarm_created",
            "trigger_conditions": {"severity": "critical"},
            "task_template": {
                "title": "CRITICAL: {alarm_message}",
                "priority": "emergency",
                "task_type": "alarm_response"
            },
            "is_system_rule": True
        },
        {
            "id": "template-002",
            "rule_name": "OEE Degradation Alert",
            "description": "Create investigation task when OEE drops below threshold",
            "trigger_type": "oee_threshold",
            "trigger_conditions": {"availability": "<40%", "duration_minutes": 30},
            "task_template": {
                "title": "Investigate Low OEE on {asset_name}",
                "priority": "high",
                "task_type": "production_job"
            },
            "is_system_rule": True
        },
        {
            "id": "template-003",
            "rule_name": "Command Failure Follow-up",
            "description": "Create troubleshooting task when commands fail",
            "trigger_type": "command_failed",
            "trigger_conditions": {},
            "task_template": {
                "title": "Command Failed: {action_id} on {asset_name}",
                "priority": "high",
                "task_type": "command_execution"
            },
            "is_system_rule": True
        },
        {
            "id": "template-004",
            "rule_name": "PackML Abort Investigation",
            "description": "Create fault investigation task on PackML Aborted state",
            "trigger_type": "packml_state_change",
            "trigger_conditions": {"to_state": "Aborted"},
            "task_template": {
                "title": "Fault Investigation: {asset_name} Aborted",
                "priority": "critical",
                "task_type": "alarm_response"
            },
            "is_system_rule": True
        },
        {
            "id": "template-005",
            "rule_name": "Preventive Maintenance Due",
            "description": "Schedule PM tasks based on maintenance calendar",
            "trigger_type": "maintenance_due",
            "trigger_conditions": {},
            "task_template": {
                "title": "PM Due: {asset_name} - {maintenance_type}",
                "priority": "medium",
                "task_type": "maintenance_pm"
            },
            "is_system_rule": True
        }
    ]
    
    return premade_templates


@router.delete("/rules/{rule_id}")
async def delete_task_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete a custom rule (cannot delete system rules)"""
    result = await session.execute(
        select(TaskRule).where(
            and_(
                TaskRule.id == rule_id,
                TaskRule.organization_id == current_user.organization_id
            )
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    if rule.is_system_rule:
        raise HTTPException(status_code=403, detail="Cannot delete system rules")
    
    await session.delete(rule)
    await session.commit()
    
    return {"message": "Rule deleted"}
