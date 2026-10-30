"""Settings and CSRF token endpoints."""

from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, Request

from backend.api.deps import get_ai_mux
from backend.api.models import TokenResponse
from backend.api.security import get_token, verify_csrf_token
from backend.core.ai_mux import AIMux

router = APIRouter(tags=["Settings"])


@router.get("/token", response_model=TokenResponse)
async def fetch_token() -> Dict[str, str]:
    """Get the current session security CSRF token."""
    return {"token": get_token()}


@router.get("/settings")
async def get_settings(
    ai_mux: AIMux = Depends(get_ai_mux),
) -> Dict[str, Any]:
    """Get active AI provider configurations (with redacted keys)."""
    return ai_mux.get_settings()


@router.post("/settings")
async def save_settings(
    request: Request,
    ai_mux: AIMux = Depends(get_ai_mux),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Save AI provider settings into .env."""
    body = await request.json()
    return ai_mux.save_settings(body)

