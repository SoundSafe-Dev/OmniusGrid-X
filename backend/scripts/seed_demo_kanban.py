"""
Seed demo Kanban tasks for development/demo purposes
"""

import asyncio
import sys
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add parent directory to path
sys.path.insert(0, "/Users/hamaddada/Downloads/OmniusGrid/backend")

from app.db.database import AsyncSessionLocal
from app.db.models import TaskBoard, TaskColumn, Task, User, Organization


DEMO_TASKS = [
    {
        "title": "Investigate conveyor belt jam in Line 3",
        "description": "Conveyor belt jammed at station 4 causing production halt. Need to inspect mechanical components and clear obstruction.",
        "task_type": "maintenance_cm",
        "priority": "critical",
        "column_type": "in_progress",
        "estimated_effort_minutes": 45,
        "tags": ["maintenance", "conveyor", "line-3"]
    },
    {
        "title": "Schedule preventive maintenance for CNC Machine A",
        "description": "Quarterly preventive maintenance due for CNC Machine A. Check lubrication, calibration, and replace worn parts.",
        "task_type": "maintenance_pm",
        "priority": "high",
        "column_type": "triage",
        "estimated_effort_minutes": 120,
        "due_date": datetime.utcnow() + timedelta(days=3),
        "tags": ["maintenance", "cnc", "preventive"]
    },
    {
        "title": "Quality inspection for Batch #4521",
        "description": "Perform quality inspection on completed Batch #4521. Verify dimensional accuracy and surface finish specifications.",
        "task_type": "quality_inspection",
        "priority": "medium",
        "column_type": "backlog",
        "estimated_effort_minutes": 30,
        "tags": ["quality", "inspection", "batch-4521"]
    },
    {
        "title": "Respond to high temperature alarm on Hydraulic Press",
        "description": "Temperature alarm triggered on Hydraulic Press Unit 2. Operating temperature exceeded safe threshold. Immediate investigation required.",
        "task_type": "alarm_response",
        "priority": "critical",
        "column_type": "in_progress",
        "estimated_effort_minutes": 60,
        "tags": ["alarm", "hydraulic", "temperature"]
    },
    {
        "title": "Execute safety check for robotic cell",
        "description": "Daily safety check for Robotic Welding Cell. Verify emergency stops, light curtains, and safety interlocks.",
        "task_type": "safety_check",
        "priority": "high",
        "column_type": "backlog",
        "estimated_effort_minutes": 15,
        "tags": ["safety", "robotic", "daily"]
    },
    {
        "title": "Material request: Steel sheets for Line 2",
        "description": "Order additional steel sheets for Line 2 production. Current inventory below minimum threshold.",
        "task_type": "material_request",
        "priority": "medium",
        "column_type": "triage",
        "estimated_effort_minutes": 20,
        "tags": ["material", "procurement", "line-2"]
    },
    {
        "title": "Changeover: Product A to Product B on Line 1",
        "description": "Scheduled changeover from Product A to Product B on Line 1. Update tooling, adjust settings, and perform first-piece inspection.",
        "task_type": "changeover",
        "priority": "high",
        "column_type": "review",
        "estimated_effort_minutes": 90,
        "due_date": datetime.utcnow() + timedelta(hours=4),
        "tags": ["changeover", "line-1", "product-b"]
    },
    {
        "title": "Review OEE metrics for Week 22",
        "description": "Analyze Overall Equipment Effectiveness metrics for Week 22. Identify bottlenecks and improvement opportunities.",
        "task_type": "custom",
        "priority": "low",
        "column_type": "backlog",
        "estimated_effort_minutes": 45,
        "tags": ["analysis", "oee", "metrics"]
    },
    {
        "title": "Update firmware on PLC controllers",
        "description": "Apply firmware update to all PLC controllers in Zone B. Update includes security patches and performance improvements.",
        "task_type": "custom",
        "priority": "medium",
        "column_type": "backlog",
        "estimated_effort_minutes": 60,
        "tags": ["firmware", "plc", "zone-b"]
    },
    {
        "title": "Train operators on new HMI interface",
        "description": "Conduct training session for operators on new HMI interface. Cover navigation, alarm handling, and data entry procedures.",
        "task_type": "custom",
        "priority": "low",
        "column_type": "backlog",
        "estimated_effort_minutes": 120,
        "tags": ["training", "hmi", "operators"]
    },
    {
        "title": "Calibrate load cells on packaging line",
        "description": "Annual calibration of load cells on packaging line. Verify accuracy against certified weights.",
        "task_type": "maintenance_pm",
        "priority": "medium",
        "column_type": "done",
        "estimated_effort_minutes": 30,
        "tags": ["calibration", "load-cells", "packaging"]
    },
    {
        "title": "Investigate excessive vibration on Motor 5",
        "description": "Vibration monitoring detected abnormal levels on Motor 5. Need to inspect bearings, alignment, and mounting.",
        "task_type": "maintenance_cm",
        "priority": "high",
        "column_type": "review",
        "estimated_effort_minutes": 60,
        "tags": ["maintenance", "vibration", "motor-5"]
    }
]


async def get_column_by_type(session: AsyncSession, board_id: str, column_type: str) -> TaskColumn:
    """Get column by type for a board"""
    result = await session.execute(
        select(TaskColumn).where(
            TaskColumn.board_id == board_id,
            TaskColumn.column_type == column_type
        )
    )
    return result.scalar_one_or_none()


async def seed_demo_tasks():
    """Seed demo kanban tasks"""
    async with AsyncSessionLocal() as session:
        # Get dev organization
        dev_org_id = "00000000-0000-0000-0000-000000000001"
        result = await session.execute(
            select(Organization).where(Organization.id == dev_org_id)
        )
        org = result.scalar_one_or_none()
        
        if not org:
            print("Dev organization not found. Please login first to create it.")
            return
        
        # Get or create board
        result = await session.execute(
            select(TaskBoard).where(
                TaskBoard.organization_id == dev_org_id,
                TaskBoard.is_active == True
            )
        )
        board = result.scalar_one_or_none()
        
        if not board:
            print("Creating demo board...")
            board = TaskBoard(
                organization_id=dev_org_id,
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
            
            # Create standard columns
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
        
        # Check if tasks already exist
        result = await session.execute(
            select(Task).where(Task.board_id == board.id)
        )
        existing_tasks = result.scalars().all()
        
        if existing_tasks:
            print(f"Board already has {len(existing_tasks)} tasks. Skipping seed.")
            return
        
        # Create demo tasks
        print(f"Creating {len(DEMO_TASKS)} demo tasks...")
        
        for i, task_data in enumerate(DEMO_TASKS):
            column_type = task_data.pop("column_type")
            column = await get_column_by_type(session, board.id, column_type)
            
            if not column:
                print(f"Warning: Column '{column_type}' not found, skipping task")
                continue
            
            # Get max position for column
            from sqlalchemy import func
            result = await session.execute(
                select(func.max(Task.position)).where(Task.column_id == column.id)
            )
            max_position = result.scalar() or 0
            
            task = Task(
                board_id=board.id,
                column_id=column.id,
                position=max_position + 1,
                title=task_data["title"],
                description=task_data.get("description"),
                task_type=task_data.get("task_type", "custom"),
                priority=task_data.get("priority", "medium"),
                status="completed" if column_type == "done" else "in_progress" if column_type == "in_progress" else "ready",
                estimated_effort_minutes=task_data.get("estimated_effort_minutes"),
                due_date=task_data.get("due_date"),
                tags=task_data.get("tags", []),
                checklist_items=[],
                custom_fields={},
                color_code=None,
                completion_actions={},
                approval_status="approved",
                created_by="00000000-0000-0000-0000-000000000001",
                created_at=datetime.utcnow() - timedelta(hours=i)  # Stagger creation times
            )
            
            # Set completion data for done tasks
            if column_type == "done":
                task.completed_at = datetime.utcnow() - timedelta(hours=i)
                task.completed_by = "00000000-0000-0000-0000-000000000001"
                task.progress_percent = 100
                task.actual_end = task.completed_at
            
            session.add(task)
        
        await session.commit()
        print(f"Successfully seeded {len(DEMO_TASKS)} demo tasks!")


if __name__ == "__main__":
    asyncio.run(seed_demo_tasks())
