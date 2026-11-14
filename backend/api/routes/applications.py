"""Application tracker endpoints."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import get_profile, get_tracker
from backend.api.models import (
    ApplicationEventCreateRequest,
    ApplicationRemoveRequest,
    ApplicationSaveRequest,
    AppliedRequest,
    BatchAppliedRequest,
    ReopenRecruiterRequest,
)
from backend.api.security import verify_csrf_token
from backend.core.profile import ProfileService
from backend.core.tracker import TrackerService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Applications"])


@router.get("/applications")
def list_applications(
    status: Optional[str] = Query(None),
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """List applications with complete metadata, materials, and aliases."""
    normalized = tracker.list_enriched_applications(status=status)
    return {"applications": normalized, "total": len(normalized)}


@router.post("/applications")
def save_application(
    req: ApplicationSaveRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Create or update an application record."""
    try:
        return tracker.save_application_with_legacy(req.model_dump(exclude_none=True))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post("/applied")
def mark_applied(
    req: AppliedRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Mark a job as applied from Me Interessam / Cards."""
    return tracker.apply_single_job(
        url=req.url,
        company=req.company,
        role=req.role,
        portal=req.portal,
        contact_channel=req.contact_channel,
        contacted_email=req.contacted_email,
    )


@router.post("/applied/batch")
def mark_applied_batch(
    req: BatchAppliedRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Mark multiple selected jobs as applied sequentially without CSV/JSON write races."""
    seen_urls: set[str] = set()
    deduped: List[AppliedRequest] = []
    for item in req.items or []:
        url = (item.url or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(item)
    if not deduped:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhuma vaga selecionada para marcar candidatura.",
        )
    results = [
        tracker.apply_single_job(
            url=item.url,
            company=item.company,
            role=item.role,
            portal=item.portal,
            contact_channel=item.contact_channel,
            contacted_email=item.contacted_email,
        )
        for item in deduped
    ]
    return {"ok": True, "applied": len(results), "results": results}


@router.post("/applications/remove")
def remove_application(
    req: ApplicationRemoveRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Remove application record from SQLite and tracker.csv while preserving ledger history."""
    url_to_clean = tracker.remove_application_with_legacy(
        app_id=req.id,
        job_id=req.job_id,
        url=req.url,
    )
    return {"ok": True, "removed": True, "url": url_to_clean}


@router.post("/applications/reopen-recruiter")
def reopen_recruiter_application(
    req: ReopenRecruiterRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Undo a direct recruiter outreach application and restore the post to Recrutadores."""
    reopened = tracker.reopen_recruiter_with_legacy(
        app_id=req.id,
        job_id=req.job_id,
        url=req.url,
        recruiter_post_id=req.recruiter_post_id,
    )
    if not reopened:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidatura de recrutador não encontrada para reabrir.",
        )
    return {"ok": True, "reopened": True, **reopened}


@router.get("/applications/{app_id}/events")
def list_application_events(
    app_id: int,
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """List timeline events (stages, feedbacks, questions) for an application."""
    events = tracker.list_application_events(application_id=app_id)
    return {"events": events, "total": len(events)}


@router.post("/applications/event")
def add_application_event(
    req: ApplicationEventCreateRequest,
    tracker: TrackerService = Depends(get_tracker),
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Record an interview stage event with feedback and Q&A."""
    event_id = tracker.add_application_event_with_status(
        application_id=req.application_id,
        job_id=req.job_id,
        url=req.url,
        stage=req.stage,
        event_date=req.event_date,
        feedback=req.feedback,
        questions_and_answers=req.questions_and_answers,
        status_update=req.status,
    )
    if not event_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidatura não encontrada para registrar evento.",
        )

    try:
        profile_svc.update_evolution()
    except (OSError, sqlite3.Error, ValueError) as exc:
        logger.warning("Failed to update evolution after adding event %s: %s", event_id, exc)

    return {"ok": True, "event_id": event_id}


@router.delete("/applications/event/{event_id}")
def delete_application_event(
    event_id: int,
    tracker: TrackerService = Depends(get_tracker),
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Delete an interview stage event."""
    deleted = tracker.delete_application_event(event_id=event_id)
    try:
        profile_svc.update_evolution()
    except (OSError, sqlite3.Error, ValueError) as exc:
        logger.warning("Failed to update evolution after deleting event %s: %s", event_id, exc)
    return {"ok": True, "deleted": deleted > 0}
