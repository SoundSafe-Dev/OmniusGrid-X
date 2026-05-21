"""
Initialize Correlation AI Registries Script

This script initializes registries for all 47 operational domains
for existing organizations in the database.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import AsyncSessionLocal
from app.db.models import Organization, User
from app.services.correlation_registry_integration import correlation_registry_integration
import structlog

logger = structlog.get_logger()


async def initialize_for_organization(organization_id: str):
    """Initialize registries for a specific organization"""
    from uuid import UUID
    
    org_uuid = UUID(organization_id)
    
    async with AsyncSessionLocal() as db:
        # Get organization
        result = await db.execute(
            select(Organization).where(Organization.id == org_uuid)
        )
        org = result.scalar_one_or_none()
        
        if not org:
            logger.error("organization_not_found", organization_id=organization_id)
            return False
        
        # Get admin user (first user in org)
        result = await db.execute(
            select(User).where(User.organization_id == org_uuid).limit(1)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            logger.error("no_user_in_organization", organization_id=organization_id)
            return False
        
        logger.info("initializing_registries", organization=org.name, organization_id=str(org_uuid))
        
        # Initialize registries
        registry_ids = await correlation_registry_integration.initialize_registries_for_organization(
            org_uuid,
            db,
            user.id
        )
        
        logger.info("registries_initialized", count=len(registry_ids), organization=org.name)
        
        # Count registry items
        from app.db.models import ActionableRegistryItem
        from sqlalchemy import func
        
        result = await db.execute(
            select(func.count(ActionableRegistryItem.id)).where(
                ActionableRegistryItem.registry_id.in_(registry_ids.values())
            )
        )
        items_count = result.scalar() or 0
        
        logger.info("registry_items_created", count=items_count, organization=org.name)
        
        return True


async def initialize_all_organizations():
    """Initialize registries for all organizations in the database"""
    
    async with AsyncSessionLocal() as db:
        # Get all organizations
        result = await db.execute(select(Organization))
        organizations = result.scalars().all()
        
        logger.info("found_organizations", count=len(organizations))
        
        success_count = 0
        for org in organizations:
            try:
                success = await initialize_for_organization(str(org.id))
                if success:
                    success_count += 1
            except Exception as e:
                logger.error("initialization_failed", organization=str(org.id), error=str(e))
        
        logger.info("initialization_complete", success=success_count, total=len(organizations))


async def main():
    """Main entry point"""
    
    if len(sys.argv) > 1:
        # Initialize specific organization
        organization_id = sys.argv[1]
        await initialize_for_organization(organization_id)
    else:
        # Initialize all organizations
        await initialize_all_organizations()


if __name__ == "__main__":
    asyncio.run(main())
