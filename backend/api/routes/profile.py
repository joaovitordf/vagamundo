"""Candidate profile, uploaded files, and evolution endpoints."""

from __future__ import annotations
import asyncio
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import get_profile
from backend.api.models import ProfileOrganizeRequest, ProfileSaveRequest, RemoveUploadRequest, UploadFileRequest
from backend.api.security import verify_csrf_token
from backend.core.profile import ProfileService
from backend.tools import ai_providers

router = APIRouter(tags=["Profile"])


@router.get("/profile")
def get_profile_data(
    profile_svc: ProfileService = Depends(get_profile),
) -> Dict[str, Any]:
    """Get candidate profile data and questionnaire answers."""
    return profile_svc.get_profile_data()


@router.post("/profile")
def save_profile_answers(
    req: ProfileSaveRequest,
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Save answers from the candidate profile form."""
    return profile_svc.save_profile_answers(req.to_answers_dict())


@router.post("/profile/organize")
async def organize_profile_from_documents(
    req: ProfileOrganizeRequest,
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Extract questionnaire fields from uploaded PDFs and consolidate the AI profile."""
    try:
        return await asyncio.to_thread(
            profile_svc.organize_profile_from_documents,
            overwrite=req.overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ai_providers.ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/evolucao")
def get_evolution(
    profile_svc: ProfileService = Depends(get_profile),
) -> Dict[str, Any]:
    """Get metrics and roadmap evolution data."""
    return profile_svc.get_evolution()


@router.post("/evolucao/atualizar")
def update_evolution_endpoint(
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Recalculate evolution metrics, audit sources, and sync ledger."""
    data = profile_svc.update_evolution()
    return {"ok": True, "evolution": data}


@router.get("/geo")
def get_geo_data(
    profile_svc: ProfileService = Depends(get_profile),
) -> Dict[str, Any]:
    """Get geojson map data."""
    return profile_svc.get_geo()


@router.post("/upload")
def upload_document(
    req: UploadFileRequest,
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Upload candidate source documents (CV or LinkedIn PDF)."""
    return profile_svc.save_upload(req.kind, req.name, req.data)


@router.post("/upload-remove")
def remove_upload(
    req: RemoveUploadRequest,
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Remove an uploaded document."""
    return profile_svc.remove_upload(req.kind, req.name)

