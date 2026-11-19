"""Document generation and management endpoints."""

from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from backend.api.deps import get_docgen, get_evaluator, get_profile
from backend.api.models import ClaudeStepRequest
from backend.api.security import verify_csrf_token
from backend.core.constants import ALLOWED_DOC_EXTS
from backend.core.docgen import DocGenService
from backend.core.evaluator import EvaluatorService
from backend.core.profile import ProfileService

router = APIRouter(tags=["Documents"])


@router.get("/documents")
def list_documents(
    docgen: DocGenService = Depends(get_docgen),
) -> Dict[str, Any]:
    """List all generated documents."""
    docs = docgen.list_documents()
    return {"documents": docs}


@router.get("/cv-areas")
def cv_areas(
    profile_svc: ProfileService = Depends(get_profile),
) -> Dict[str, Any]:
    """List available CV specialization keywords/areas."""
    return profile_svc.get_cv_areas()


@router.get("/file")
def serve_document_file(
    path: str = Query(..., description="Caminho relativo do arquivo (PDF, MD ou TXT)"),
    docgen: DocGenService = Depends(get_docgen),
) -> FileResponse:
    """Serve a generated PDF or Markdown document securely."""
    if not str(path or "").replace("\\", "/").strip("/."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Caminho ausente.")

    target = docgen.resolve_document_file(path)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo não encontrado.")

    ext = target.suffix.lower()
    media_type = ALLOWED_DOC_EXTS.get(ext)
    if not media_type:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tipo de arquivo não permitido.")

    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=target.name,
    )


@router.post("/claude")
async def trigger_ai_task(
    req: ClaudeStepRequest,
    evaluator: EvaluatorService = Depends(get_evaluator),
    docgen: DocGenService = Depends(get_docgen),
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Execute AI action requested by the panel buttons."""
    step = req.step
    url = (req.url or "").strip()

    if step != "perfil" and not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL da vaga é obrigatória para o passo '{step}'.",
        )

    try:
        if step == "avaliar":
            res = await evaluator.evaluate_job(url)
            return {"ok": True, "result": res}
        if step == "curriculo":
            res = await docgen.generate_cv(url)
            return {"ok": True, "result": res}
        if step == "carta":
            res = await docgen.generate_cover_letter(url)
            return {"ok": True, "result": res}
        if step == "entrevista":
            res = await docgen.prepare_interview(url)
            return {"ok": True, "result": res}
        if step == "redigir":
            cv_res = await docgen.generate_cv(url)
            letter_res = await docgen.generate_cover_letter(url)
            return {"ok": True, "cv": cv_res, "carta": letter_res}
        if step == "perfil":
            res = await asyncio.to_thread(profile_svc.build_ai_profile)
            return {"ok": True, "result": res}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Passo desconhecido: '{step}'",
    )


@router.post("/documents/delete")
def delete_document(
    path: str = Query(...),
    docgen: DocGenService = Depends(get_docgen),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Delete a generated PDF and its associated build artifacts."""
    res = docgen.delete_document(path)
    if not res.get("deleted"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error") or "Não foi possível excluir o documento.",
        )
    return res


@router.post("/documents/clear")
def clear_documents(
    keep_cv: bool = Query(True, description="Se True, preserva todos os currículos e apaga apenas cartas e dossiês"),
    docgen: DocGenService = Depends(get_docgen),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Batch clear generated documents while protecting the user's CVs."""
    return docgen.clear_generated_documents(keep_cv=keep_cv)
