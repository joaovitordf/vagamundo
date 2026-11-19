"""Recruiter posts and direct email radar endpoints."""

from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import get_auto_mode, get_recruiter_service
from backend.api.models import (
    PasteRecruiterBatchRequest,
    PasteRecruiterPostRequest,
    RecruiterAutoConfigRequest,
    RecruiterAutoStartRequest,
    RecruiterContactedRequest,
    RecruiterDismissBatchRequest,
    RecruiterExpandTermRequest,
    RecruiterTriageRequest,
)
from backend.api.security import verify_csrf_token
from backend.core.auto_mode import AutoModeService
from backend.core.recruiter_service import RecruiterService

router = APIRouter(prefix="/recruiters", tags=["Recruiters"])


@router.get("")
def list_recruiter_posts(
    q: Optional[str] = Query(None, description="Filtrar por palavras-chave ou texto"),
    only_cv: bool = Query(False, description="Filtrar apenas posts compatíveis com o CV"),
    portal: Optional[str] = Query(None, description="Filtrar por portal de origem"),
    include_non_jobs: bool = Query(True, description="Incluir publicações classificadas pela IA como 'Não é vaga'"),
    service: RecruiterService = Depends(get_recruiter_service),
) -> Dict[str, Any]:
    """List all active recruiter publications matching criteria."""
    posts = service.list_posts(query=q, only_cv=only_cv, portal=portal, include_non_jobs=include_non_jobs)
    return {"total": len(posts), "posts": posts}


@router.get("/auto/config")
def get_recruiter_auto_config(
    auto_mode: AutoModeService = Depends(get_auto_mode),
) -> Dict[str, Any]:
    """Return persisted Auto Mode preferences for Recrutadores."""
    return {"config": auto_mode.get_recruiter_config()}


@router.post("/auto/config")
def save_recruiter_auto_config(
    req: RecruiterAutoConfigRequest,
    auto_mode: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Persist Auto Mode preferences for Recrutadores in SQLite profile table."""
    cfg = auto_mode.save_recruiter_config(req.model_dump(exclude_none=True))
    return {"ok": True, "config": cfg}


@router.post("/auto/start")
def start_recruiter_auto_mode(
    req: RecruiterAutoStartRequest,
    auto_mode: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Start Autonomous AI triage + promotion for Recrutadores -> Me Interessam."""
    try:
        return auto_mode.start_recruiters(
            min_score=req.min_score,
            continuous=req.continuous,
            cooldown_seconds=req.cooldown_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/sync")
def sync_recruiter_posts(
    q: Optional[str] = Query(None, description="Palavra-chave opcional para buscar também em threads públicas (ex: Hacker News)"),
    days: Optional[int] = Query(None, ge=1, le=365, description="Idade máxima opcional das publicações em dias"),
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Scan collected jobs and extract postings containing recruiter emails, optionally searching public feeds."""
    res = service.sync_all(query=q) if days is None else service.sync_all(query=q, days=days)
    return {"ok": True, **res}


@router.post("/triage")
def triage_recruiter_posts(
    req: Optional[RecruiterTriageRequest] = None,
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Run on-demand AI triage on untriaged recruiter posts and return updated scores."""
    try:
        return service.triage_posts(
            post_ids=req.post_ids if req else None,
            query=req.q if req else None,
            portal=req.portal if req else None,
            limit=req.limit if req else 12,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/paste")
def paste_recruiter_post(
    req: PasteRecruiterPostRequest,
    service: RecruiterService = Depends(get_recruiter_service),
    auto_mode: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Parse and save a manually pasted post from LinkedIn or other channels."""
    try:
        post = service.add_pasted_post(
            raw_text=req.raw_text,
            url=req.url,
            title=req.title,
            company=req.company,
            location=req.location,
            work_model=req.work_model,
            published_date=req.published_date,
            allow_without_email=req.allow_without_email,
        )
        woken = auto_mode.enqueue_recruiter_posts([post["id"]] if post.get("id") else [])
        return {"ok": True, "post": post, "auto_mode_woken": woken}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/paste-batch")
def paste_recruiter_posts_batch(
    req: PasteRecruiterBatchRequest,
    service: RecruiterService = Depends(get_recruiter_service),
    auto_mode: AutoModeService = Depends(get_auto_mode),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Parse and import multiple LinkedIn/clipboard recruiter posts safely without bots or account login."""
    try:
        items_payload = [item.model_dump() for item in req.items] if req.items else None
        res = service.add_pasted_posts_batch(
            items_payload,
            raw_batch_text=req.raw_batch_text,
            allow_without_email=req.allow_without_email,
        )
        saved_ids = [p["id"] for p in (res.get("posts") or []) if p.get("id")]
        woken = auto_mode.enqueue_recruiter_posts(saved_ids) if saved_ids else False
        return {"ok": True, **res, "auto_mode_woken": woken}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/expand-search-term")
def expand_recruiter_search_term(
    req: RecruiterExpandTermRequest,
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Expand a job-search keyword into its PT/EN market equivalent via configured AI (cached, degrades silently)."""
    return service.expand_search_term(req.term)


@router.post("/dismiss-batch")
def dismiss_recruiter_posts_batch(
    req: RecruiterDismissBatchRequest,
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Move multiple recruiter publications to Descartadas in one batch."""
    dismissed_ids = service.dismiss_posts(req.post_ids)
    return {
        "ok": True,
        "dismissed_ids": dismissed_ids,
        "dismissed_count": len(dismissed_ids),
    }


@router.post("/{post_id}/interested")
def save_recruiter_post_as_interested(
    post_id: int,
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Manually move a recruiter publication to Me Interessam (without generating CV/Letter)."""
    try:
        return service.save_post_as_interested(post_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{post_id}/contacted")
def mark_recruiter_post_contacted(
    post_id: int,
    req: Optional[RecruiterContactedRequest] = None,
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Record direct recruiter email outreach into Minhas Candidaturas."""
    try:
        return service.mark_post_contacted(
            post_id=post_id,
            email=req.email if req else None,
            notes=req.notes if req else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{post_id}")
def dismiss_recruiter_post(
    post_id: int,
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Move a publication from the radar to Descartadas."""
    ok = service.dismiss_post(post_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publicação não encontrada ou já removida.",
        )
    return {"ok": True, "id": post_id}
