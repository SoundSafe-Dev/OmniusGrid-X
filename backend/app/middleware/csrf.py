"""CSRF Protection Middleware"""

import secrets
from typing import Optional
from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Headers
import structlog

logger = structlog.get_logger()


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection middleware for state-changing requests"""
    
    def __init__(self, app, secret_key: Optional[str] = None):
        super().__init__(app)
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.csrf_token_length = 32
        self.cookie_name = "csrf_token"
        self.header_name = "X-CSRF-Token"
    
    async def dispatch(self, request: Request, call_next):
        # Skip CSRF for safe methods
        if request.method in ["GET", "HEAD", "OPTIONS", "TRACE"]:
            response = await call_next(request)
            # Add CSRF token to response for GET requests
            if request.method == "GET":
                csrf_token = self._generate_token()
                response.set_cookie(
                    key=self.cookie_name,
                    value=csrf_token,
                    httponly=True,
                    secure=True,
                    samesite="strict"
                )
                response.headers[self.header_name] = csrf_token
            return response
        
        # Check CSRF for state-changing methods
        csrf_token = request.cookies.get(self.cookie_name)
        csrf_header = request.headers.get(self.header_name)
        
        if not csrf_token:
            logger.warning("csrf_token_missing", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token missing. Please refresh the page and try again."
            )
        
        if not csrf_header:
            logger.warning("csrf_header_missing", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token header missing. Please include X-CSRF-Token header."
            )
        
        if not self._verify_token(csrf_token, csrf_header):
            logger.warning("csrf_token_invalid", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token invalid. Please refresh the page and try again."
            )
        
        # Token is valid, proceed with request
        response = await call_next(request)
        
        # Rotate CSRF token after successful state change
        new_token = self._generate_token()
        response.set_cookie(
            key=self.cookie_name,
            value=new_token,
            httponly=True,
            secure=True,
            samesite="strict"
        )
        response.headers[self.header_name] = new_token
        
        return response
    
    def _generate_token(self) -> str:
        """Generate a new CSRF token"""
        return secrets.token_urlsafe(self.csrf_token_length)
    
    def _verify_token(self, cookie_token: str, header_token: str) -> bool:
        """Verify CSRF token"""
        # In production, use HMAC for verification
        # For now, simple comparison
        return secrets.compare_digest(cookie_token, header_token)
