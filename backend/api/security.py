"""Security guards and CSRF token protection for Vagamundo API."""

from __future__ import annotations
import secrets
from typing import Optional
from fastapi import Header, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.core.constants import DEFAULT_ALLOWED_HOSTS, get_allowed_hosts

# Global session CSRF token
SESSION_TOKEN = secrets.token_hex(16)

ALLOWED_HOSTS = set(DEFAULT_ALLOWED_HOSTS)


def get_token() -> str:
    return SESSION_TOKEN


class HostCheckMiddleware(BaseHTTPMiddleware):
    """Enforce request host allowlist against DNS rebinding."""

    async def dispatch(self, request: Request, call_next):
        raw_host = (request.headers.get("host") or "").strip().lower()
        if not raw_host:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Cabeçalho Host ausente."},
            )
        if raw_host.startswith("["):
            end_bracket = raw_host.find("]")
            host_header = raw_host[1:end_bracket] if end_bracket != -1 else raw_host
        else:
            host_header = raw_host.partition(":")[0]

        allowed_hosts = ALLOWED_HOSTS | get_allowed_hosts()
        if not host_header or host_header not in allowed_hosts:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": f"Host '{host_header or raw_host}' não permitido."},
            )
        return await call_next(request)


async def verify_csrf_token(
    request: Request,
    x_painel_token: Optional[str] = Header(None, alias="X-Painel-Token"),
) -> str:
    """Validate CSRF protection token on state-changing requests."""
    # Allow reading GET / HEAD / OPTIONS without token
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return SESSION_TOKEN

    token = x_painel_token or request.query_params.get("token")
    if not token or not secrets.compare_digest(token, SESSION_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token de segurança inválido ou expirado. Atualize o painel.",
        )
    return SESSION_TOKEN
