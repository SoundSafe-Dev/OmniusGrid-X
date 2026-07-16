"""Query Performance Monitoring API Routes"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
try:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db.database import get_db
except ImportError:
    text = None
    AsyncSession = None
    get_db = None
try:
    from app.middleware.security_headers import SecurityHeadersMiddleware
except ImportError:
    SecurityHeadersMiddleware = None

from app.api.auth import require_admin_user

# Currently unmounted. Admin-gated defensively so it is safe if ever wired up
# (exposes DB introspection + POST /reset-stats).
router = APIRouter(dependencies=[Depends(require_admin_user)])

@router.get("/slow-queries")
async def get_slow_queries(
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Get slow queries (>1 second execution time)."""
    try:
        query = text("""
            SELECT * FROM slow_queries
            ORDER BY mean_exec_time DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()
        
        return {
            "slow_queries": [
                {
                    "queryid": row.queryid,
                    "query": row.query,
                    "calls": row.calls,
                    "mean_exec_time_ms": row.mean_exec_time,
                    "max_exec_time_ms": row.max_exec_time,
                    "min_exec_time_ms": row.min_exec_time,
                    "stddev_exec_time_ms": row.stddev_exec_time,
                    "total_exec_time_ms": row.total_exec_time,
                    "rows": row.rows
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve slow queries: {str(e)}"
        )

@router.get("/table-performance")
async def get_table_performance(
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Get performance statistics by table."""
    try:
        query = text("""
            SELECT * FROM query_performance_by_table
            ORDER BY seq_tup_read + idx_tup_fetch DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()
        
        return {
            "tables": [
                {
                    "schemaname": row.schemaname,
                    "tablename": row.tablename,
                    "seq_scan": row.seq_scan,
                    "seq_tup_read": row.seq_tup_read,
                    "idx_scan": row.idx_scan,
                    "idx_tup_fetch": row.idx_tup_fetch,
                    "n_tup_ins": row.n_tup_ins,
                    "n_tup_upd": row.n_tup_upd,
                    "n_tup_del": row.n_tup_del,
                    "n_live_tup": row.n_live_tup,
                    "n_dead_tup": row.n_dead_tup,
                    "last_vacuum": row.last_vacuum.isoformat() if row.last_vacuum else None,
                    "last_analyze": row.last_analyze.isoformat() if row.last_analyze else None
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve table performance: {str(e)}"
        )

@router.get("/index-usage")
async def get_index_usage(
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Get index usage statistics."""
    try:
        query = text("""
            SELECT * FROM index_usage_stats
            ORDER BY idx_scan DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()
        
        return {
            "indexes": [
                {
                    "schemaname": row.schemaname,
                    "tablename": row.tablename,
                    "indexname": row.indexname,
                    "idx_scan": row.idx_scan,
                    "idx_tup_read": row.idx_tup_read,
                    "idx_tup_fetch": row.idx_tup_fetch,
                    "is_used": row.is_used
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve index usage: {str(e)}"
        )

@router.get("/missing-indexes")
async def get_missing_indexes(
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Get tables that may benefit from additional indexes."""
    try:
        query = text("""
            SELECT * FROM missing_index_candidates
            ORDER BY seq_tup_read DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()
        
        return {
            "candidates": [
                {
                    "schemaname": row.schemaname,
                    "tablename": row.tablename,
                    "seq_scan": row.seq_scan,
                    "seq_tup_read": row.seq_tup_read,
                    "idx_scan": row.idx_scan,
                    "idx_tup_fetch": row.idx_tup_fetch,
                    "seq_tup_read_ratio": row.seq_tup_read_ratio
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve missing index candidates: {str(e)}"
        )

@router.get("/query-analysis")
async def get_query_analysis(
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Get comprehensive query performance analysis."""
    try:
        query = text("""
            SELECT * FROM analyze_query_performance()
            ORDER BY mean_exec_time DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()
        
        return {
            "queries": [
                {
                    "queryid": row.queryid,
                    "query": row.query,
                    "calls": row.calls,
                    "mean_exec_time_ms": row.mean_exec_time,
                    "max_exec_time_ms": row.max_exec_time,
                    "stddev_exec_time_ms": row.stddev_exec_time,
                    "total_exec_time_ms": row.total_exec_time,
                    "rows": row.rows,
                    "hit_percent": row.hit_percent,
                    "performance_rating": row.performance_rating
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to analyze query performance: {str(e)}"
        )

@router.post("/record-snapshot")
async def record_performance_snapshot(
    db: AsyncSession = Depends(get_db)
):
    """Record current query performance to history table."""
    try:
        query = text("SELECT record_query_performance_snapshot()")
        await db.execute(query)
        await db.commit()
        
        return {"message": "Performance snapshot recorded successfully"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to record performance snapshot: {str(e)}"
        )

@router.get("/history")
async def get_performance_history(
    hours: int = 24,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Get query performance history."""
    try:
        query = text("""
            SELECT * FROM query_performance_history
            WHERE recorded_at > NOW() - INTERVAL '1 hour' * :hours
            ORDER BY recorded_at DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"hours": hours, "limit": limit})
        rows = result.fetchall()
        
        return {
            "history": [
                {
                    "id": row.id,
                    "queryid": row.queryid,
                    "query": row.query,
                    "calls": row.calls,
                    "mean_exec_time_ms": row.mean_exec_time,
                    "max_exec_time_ms": row.max_exec_time,
                    "performance_rating": row.performance_rating,
                    "recorded_at": row.recorded_at.isoformat()
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve performance history: {str(e)}"
        )

@router.get("/frequent-queries")
async def get_frequent_queries(
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Get most frequently executed queries."""
    try:
        query = text("""
            SELECT * FROM frequent_queries
            ORDER BY calls DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()
        
        return {
            "queries": [
                {
                    "queryid": row.queryid,
                    "query": row.query,
                    "calls": row.calls,
                    "total_exec_time_ms": row.total_exec_time,
                    "mean_exec_time_ms": row.mean_exec_time,
                    "rows": row.rows
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve frequent queries: {str(e)}"
        )

@router.post("/refresh-frequent-queries")
async def refresh_frequent_queries_view(
    db: AsyncSession = Depends(get_db)
):
    """Refresh the frequent queries materialized view."""
    try:
        query = text("SELECT refresh_frequent_queries()")
        await db.execute(query)
        await db.commit()
        
        return {"message": "Frequent queries view refreshed successfully"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to refresh frequent queries: {str(e)}"
        )

@router.get("/table-bloat")
async def get_table_bloat(
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Get table size and bloat statistics."""
    try:
        query = text("""
            SELECT * FROM table_bloat
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()
        
        return {
            "tables": [
                {
                    "schemaname": row.schemaname,
                    "tablename": row.tablename,
                    "total_size": row.total_size,
                    "table_size": row.table_size,
                    "index_size": row.index_size,
                    "n_live_tup": row.n_live_tup,
                    "n_dead_tup": row.n_dead_tup,
                    "dead_tup_ratio": row.dead_tup_ratio
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve table bloat: {str(e)}"
        )

@router.get("/cache-hit-ratio")
async def get_cache_hit_ratio(
    db: AsyncSession = Depends(get_db)
):
    """Get overall cache hit ratio."""
    try:
        query = text("SELECT * FROM cache_hit_ratio")
        result = await db.execute(query)
        row = result.fetchone()
        
        if not row:
            return {"ratio": 0.0}
        
        return {
            "heap_read": row.heap_read,
            "heap_hit": row.heap_hit,
            "ratio": row.ratio
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve cache hit ratio: {str(e)}"
        )

@router.post("/reset-stats")
async def reset_query_stats(
    db: AsyncSession = Depends(get_db)
):
    """Reset query statistics (use with caution)."""
    try:
        query = text("SELECT reset_query_stats()")
        await db.execute(query)
        await db.commit()
        
        return {"message": "Query statistics reset successfully"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to reset query statistics: {str(e)}"
        )
