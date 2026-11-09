"""Recruiter posts and direct email radar endpoints."""

from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import get_recruiter_service
from backend.api.models import PasteRecruiterPostRequest
from backend.api.security import verify_csrf_token
from backend.core.recruiter_service import RecruiterService

router = APIRouter(prefix="/recruiters", tags=["Recruiters"])


@router.get("")
async def list_recruiter_posts(
    q: Optional[str] = Query(None, description="Filtrar por palavras-chave ou texto"),
    only_cv: bool = Query(False, description="Filtrar apenas posts compatíveis com o CV"),
    portal: Optional[str] = Query(None, description="Filtrar por portal de origem"),
    service: RecruiterService = Depends(get_recruiter_service),
) -> Dict[str, Any]:
    """List all active recruiter publications matching criteria."""
    posts = service.list_posts(query=q, only_cv=only_cv, portal=portal)
    return {"total": len(posts), "posts": posts}


@router.post("/sync")
async def sync_recruiter_posts(
    q: Optional[str] = Query(None, description="Palavra-chave opcional para buscar também em threads públicas (ex: Hacker News)"),
    service: RecruiterService = Depends(get_recruiter_service),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Scan collected jobs and extract postings containing recruiter emails, optionally searching public feeds."""
    res = service.sync_all(query=q)
    return {"ok": True, **res}


@router.post("/paste")
async def paste_recruiter_post(
    req: PasteRecruiterPostRequest,
    service: RecruiterService = Depends(get_recruiter_service),
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
        )
        return {"ok": True, "post": post}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{post_id}")
async def dismiss_recruiter_post(
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
