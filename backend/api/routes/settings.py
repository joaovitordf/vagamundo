"""Settings and CSRF token endpoints."""

from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import get_ai_mux
from backend.api.models import SettingsSaveRequest, TokenResponse
from backend.api.security import get_token, verify_csrf_token
from backend.core.ai_mux import AIMux

router = APIRouter(tags=["Settings"])


@router.get("/token", response_model=TokenResponse)
def fetch_token() -> Dict[str, str]:
    """Get the current session security CSRF token."""
    return {"token": get_token()}


@router.get("/settings")
def get_settings(
    ai_mux: AIMux = Depends(get_ai_mux),
) -> Dict[str, Any]:
    """Get active AI provider configurations (with redacted keys)."""
    return ai_mux.get_settings()


@router.post("/settings")
def save_settings(
    req: SettingsSaveRequest,
    ai_mux: AIMux = Depends(get_ai_mux),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Save AI provider settings into .env."""
    body = req.model_dump(exclude_none=True)
    providers = dict(body.get("providers") or {})
    flat_key_map = {
        "gemini": ("gemini_key", "gemini_model", None),
        "openai": ("openai_key", "openai_model", "openai_base_url"),
        "claude": ("claude_key", "anthropic_model", None),
    }
    for pid, (key_field, model_field, base_field) in flat_key_map.items():
        cfg = dict(providers.get(pid) or {})
        if key_field in body and not cfg.get("api_key"):
            cfg["api_key"] = body.get(key_field)
        if pid == "claude" and "anthropic_key" in body and not cfg.get("api_key"):
            cfg["api_key"] = body.get("anthropic_key")
        if model_field in body and not cfg.get("model"):
            cfg["model"] = body.get(model_field)
        if base_field and base_field in body and not cfg.get("base_url"):
            cfg["base_url"] = body.get(base_field)
        if cfg:
            providers[pid] = cfg
    if providers:
        body["providers"] = providers
    try:
        return ai_mux.save_settings(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

