"""Database connection and session management"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from app.core.config import settings

# Convert PostgreSQL URL to async version
def get_async_db_url():
    url = settings.DATABASE_URL
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

def _pool_kwargs() -> dict:
    """Pool settings, or nothing when the pool is not a QueuePool.

    Two engines here are not pooled and must not be handed pool arguments, because
    SQLAlchemy raises `TypeError` rather than ignoring them:

    * `NullPool` under DEBUG, which opens and closes per checkout on purpose.
    * SQLite, whose async driver uses `StaticPool`/`SingletonThreadPool` — and the whole
      test suite runs on SQLite, so getting this wrong breaks every test rather than
      only production.

    FS-839. The numbers themselves and why they are smaller than SQLAlchemy's defaults
    are in `config.py`; the short version is that the defaults were chosen by the library
    and the ceilings are ours.
    """
    if settings.DEBUG or get_async_db_url().startswith("sqlite"):
        return {}
    return {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        # Hand out a connection only after checking it is still alive. Without this a
        # database failover or an idle-timeout cut is discovered by the first query on a
        # dead connection, which surfaces as a request-level error rather than a
        # reconnect — one 500 per pooled connection, on the worst day.
        "pool_pre_ping": True,
    }


# Create async engine
engine = create_async_engine(
    get_async_db_url(),
    echo=settings.DEBUG,
    poolclass=NullPool if settings.DEBUG else None,
    future=True,
    **_pool_kwargs(),
)

# Create async session maker
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def get_db():
    """Dependency for getting database sessions"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database connection and create tables"""
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
