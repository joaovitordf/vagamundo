"""Candidate profile, uploaded files, and evolution endpoints."""

from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request

from backend.api.deps import get_profile
from backend.api.models import RemoveUploadRequest, UploadFileRequest
from backend.api.security import verify_csrf_token
from backend.core.profile import ProfileService

router = APIRouter(tags=["Profile"])


@router.get("/profile")
async def get_profile_data(
    refresh: bool = Query(False),
    profile_svc: ProfileService = Depends(get_profile),
) -> Dict[str, Any]:
    """Get candidate profile data and questionnaire answers."""
    return profile_svc.get_profile_data(refresh=refresh)


@router.post("/profile")
async def save_profile_answers(
    request: Request,
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Save answers from the candidate profile form."""
    body = await request.json()
    answers = body.get("answers", body)
    return profile_svc.save_profile_answers(answers)


@router.get("/evolucao")
async def get_evolution(
    profile_svc: ProfileService = Depends(get_profile),
) -> Dict[str, Any]:
    """Get metrics and roadmap evolution data."""
    return profile_svc.get_evolution()


@router.get("/geo")
async def get_geo_data(
    profile_svc: ProfileService = Depends(get_profile),
) -> Dict[str, Any]:
    """Get geojson map data."""
    return profile_svc.get_geo()


@router.post("/upload")
async def upload_document(
    req: UploadFileRequest,
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Upload candidate source documents (CV or LinkedIn PDF)."""
    return profile_svc.save_upload(req.kind, req.name, req.data)


@router.post("/upload-remove")
async def remove_upload(
    req: RemoveUploadRequest,
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Remove an uploaded document."""
    return profile_svc.remove_upload(req.kind, req.name)

