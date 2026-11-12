"""API routes for Autonomous Search + AI Triage + Auto-Interest mode."""

from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import get_auto_mode
from backend.api.models import (
    AutoModeConfigRequest,
    AutoModeStartRequest,
    AutoModeUndoJobRequest,
    AutoModeUndoRequest,
)
from backend.api.security import verify_csrf_token
from backend.core.auto_mode import AutoModeService

router = APIRouter(tags=["AutoMode"])


@router.get("/auto-mode/status")
def auto_mode_status(
    svc: AutoModeService = Depends(get_auto_mode),
) -> Dict[str, Any]:
    """Return real-time state, counts, and active warning metadata of Auto Mode."""
    return svc.status()


@router.get("/auto-mode/config")
def auto_mode_get_config(
    svc: AutoModeService = Depends(get_auto_mode),
) -> Dict[str, Any]:
    """Return user's persisted Auto Mode preferences (whitelabel DB)."""
    return {"config": svc.get_config()}


@router.post("/auto-mode/config")
def auto_mode_save_config(
    req: AutoModeConfigRequest,
    svc: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Persist user's Auto Mode preferences into SQLite profile table."""
    cfg = svc.save_config(req.model_dump(exclude_none=True))
    return {"ok": True, "config": cfg}


@router.post("/auto-mode/start")
def auto_mode_start(
    req: AutoModeStartRequest,
    svc: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Start Auto Mode: AI keyword picking -> search (<=7d) -> unlimited screening -> auto interested."""
    try:
        return svc.start(
            region=req.region,
            portals=req.portals,
            jobage=req.jobage,
            min_score=req.min_score,
            hide_undated=req.hide_undated,
            continuous=req.continuous,
            cooldown_seconds=req.cooldown_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/auto-mode/cancel")
def auto_mode_cancel(
    svc: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Cancel an active Auto Mode run safely."""
    return svc.cancel()


@router.post("/auto-mode/skip-cooldown")
def auto_mode_skip_cooldown(
    svc: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Immediately skip active anti-ban cooldown and start the next round."""
    return svc.skip_cooldown()


@router.post("/auto-mode/undo")
def auto_mode_undo_run(
    req: AutoModeUndoRequest,
    svc: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Revert all still-interested jobs promoted during a given Auto Mode run."""
    try:
        return svc.undo_run(run_id=req.run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/auto-mode/undo-job")
def auto_mode_undo_single_job(
    req: AutoModeUndoJobRequest,
    svc: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Revert a single Auto-promoted job from Me Interessam back to Buscar Vagas pending list."""
    return svc.undo_job(url=req.url, job_id=req.job_id)
