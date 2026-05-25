"""Rate limiting middleware using slowapi with Redis backend"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, HTTPException, status
from typing import Callable
import redis.asyncio as redis
from app.core.config import settings
import structlog

logger = structlog.get_logger()

# Initialize Redis client for distributed rate limiting
redis_client = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)

# Initialize limiter
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    default_limits=["1000/hour"],  # Global limit
    headers_enabled=True
)


def get_user_id_from_request(request: Request) -> str:
    """Extract user ID from request for per-user rate limiting"""
    # Try to get user from token
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            # For dev-token, use a fixed ID
            if token == "dev-token":
                return "dev-user"
            # Extract user ID from JWT token (simplified)
            # In production, decode JWT properly
            return f"user:{token[:16]}"
    except Exception:
        pass
    
    # Fallback to IP address
    return get_remote_address(request)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded"""
    logger.warning(
        "rate_limit_exceeded",
        path=request.url.path,
        client_ip=get_remote_address(request),
        limit=exc.detail
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Rate limit exceeded: {exc.detail}. Please try again later.",
        headers={"X-RateLimit-Limit": str(exc.detail)}
    )


# Register custom error handler
limiter._rate_limit_exceeded_handler = rate_limit_exceeded_handler


def rate_limit(limit: str = "100/minute"):
    """Decorator for rate limiting specific endpoints"""
    def decorator(func: Callable):
        return limiter.limit(limit)(func)
    return decorator
