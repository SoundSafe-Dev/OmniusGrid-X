"""Optional CSRF protection for cookie-authenticated requests."""

import secrets
from typing import Optional

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Apply double-submit CSRF checks to non-bearer writes."""

    def __init__(self, app, secret_key: Optional[str] = None):
        super().__init__(app)
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.csrf_token_length = 32
        self.cookie_name = "csrf_token"
        self.header_name = "X-CSRF-Token"

    async def dispatch(self, request: Request, call_next):
        # Bearer credentials are not ambient browser cookies and are therefore
        # outside the CSRF threat model.
        if request.headers.get("authorization", "").lower().startswith("bearer "):
            return await call_next(request)

        if request.method in SAFE_METHODS:
            response = await call_next(request)
            if request.method == "GET":
                self._set_token(response, self._generate_token())
            return response

        csrf_token = request.cookies.get(self.cookie_name)
        csrf_header = request.headers.get(self.header_name)

        if not csrf_token:
            logger.warning("csrf_token_missing", path=request.url.path)
            return self._forbidden(
                "CSRF token missing. Please refresh the page and try again."
            )
        if not csrf_header:
            logger.warning("csrf_header_missing", path=request.url.path)
            return self._forbidden(
                "CSRF token header missing. Please include X-CSRF-Token header."
            )
        if not self._verify_token(csrf_token, csrf_header):
            logger.warning("csrf_token_invalid", path=request.url.path)
            return self._forbidden(
                "CSRF token invalid. Please refresh the page and try again."
            )

        response = await call_next(request)
        if response.status_code < 400:
            self._set_token(response, self._generate_token())
        return response

    @staticmethod
    def _forbidden(detail: str) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": detail})

    def _set_token(self, response, token: str) -> None:
        response.set_cookie(
            key=self.cookie_name,
            value=token,
            httponly=True,
            secure=True,
            samesite="strict",
        )
        response.headers[self.header_name] = token

    def _generate_token(self) -> str:
        return secrets.token_urlsafe(self.csrf_token_length)

    @staticmethod
    def _verify_token(cookie_token: str, header_token: str) -> bool:
        return secrets.compare_digest(cookie_token, header_token)
