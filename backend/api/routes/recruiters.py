"""Recruiter posts and direct email radar endpoints."""

from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import get_auto_mode, get_linkedin_worker, get_recruiter_service
from backend.api.models import (
    LinkedInWorkerConfigRequest,
    PasteRecruiterBatchRequest,
    PasteRecruiterPostRequest,
    RecruiterAutoConfigRequest,
    RecruiterAutoStartRequest,
    RecruiterContactedRequest,
    RecruiterDismissBatchRequest,
    RecruiterTriageRequest,
)
from backend.api.security import verify_csrf_token
from backend.core.auto_mode import AutoModeService
from backend.core.linkedin_browser import LinkedInBrowserWorker
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
    include_linkedin: bool = Query(True, description="Incluir coleta automática do LinkedIn quando conectado"),
    force_linkedin: bool = Query(False, description="Ignorar cooldown do LinkedIn nesta execução manual"),
    days: Optional[int] = Query(None, ge=1, le=365, description="Janela em dias para filtro de data de publicação no LinkedIn"),
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Scan collected jobs and extract postings containing recruiter emails, optionally searching public feeds."""
    if not include_linkedin or force_linkedin or days is not None:
        sync_kwargs: Dict[str, Any] = {
            "include_linkedin": include_linkedin,
            "force_linkedin": force_linkedin,
        }
        if days is not None:
            sync_kwargs["days"] = days
        try:
            res = service.sync_all(query=q, **sync_kwargs)
        except TypeError:
            res = service.sync_all(query=q)
    else:
        res = service.sync_all(query=q)
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


@router.get("/linkedin/status")
def get_linkedin_worker_status(
    worker: LinkedInBrowserWorker = Depends(get_linkedin_worker),
) -> Dict[str, Any]:
    """Return isolated LinkedIn browser worker state, quotas, cooldown timer, and browser availability."""
    return {"ok": True, **worker.get_status()}


@router.post("/linkedin/connect")
def connect_linkedin_worker(
    worker: LinkedInBrowserWorker = Depends(get_linkedin_worker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Open the isolated visible browser window so the user can sign in once to LinkedIn."""
    try:
        return {"ok": True, **worker.open_connect_window()}
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/linkedin/verify")
def verify_linkedin_worker(
    worker: LinkedInBrowserWorker = Depends(get_linkedin_worker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Verify live LinkedIn session status in the isolated browser profile."""
    try:
        return worker.verify_connection()
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/linkedin/config")
def update_linkedin_worker_config(
    req: LinkedInWorkerConfigRequest,
    worker: LinkedInBrowserWorker = Depends(get_linkedin_worker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Persist LinkedIn worker configuration (enabled, headless, cooldown, daily cap, scrolls)."""
    return {"ok": True, **worker.update_config(req.model_dump(exclude_none=True))}


@router.post("/linkedin/disconnect")
def disconnect_linkedin_worker(
    worker: LinkedInBrowserWorker = Depends(get_linkedin_worker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Close the isolated browser and wipe its local LinkedIn session profile."""
    return {"ok": True, **worker.disconnect()}


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
        )
        saved_ids = [p["id"] for p in (res.get("posts") or []) if p.get("id")]
        woken = auto_mode.enqueue_recruiter_posts(saved_ids) if saved_ids else False
        return {"ok": True, **res, "auto_mode_woken": woken}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/dismiss-batch")
def dismiss_recruiter_posts_batch(
    req: RecruiterDismissBatchRequest,
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Dismiss multiple recruiter publications to Limbo in one batch."""
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
    """Dismiss a publication from the radar."""
    ok = service.dismiss_post(post_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publicação não encontrada ou já removida.",
        )
    return {"ok": True, "id": post_id}
