"""Document generation and management endpoints."""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from backend.api.deps import get_docgen, get_evaluator
from backend.api.models import ClaudeStepRequest
from backend.api.security import verify_csrf_token
from backend.core.docgen import DocGenService
from backend.core.evaluator import EvaluatorService
from backend.tools import painel, painel_ia, painel_perfil

router = APIRouter(tags=["Documents"])


@router.get("/documents")
async def list_documents(
    docgen: DocGenService = Depends(get_docgen),
) -> Dict[str, Any]:
    """List all generated documents."""
    docs = docgen.list_documents()
    return {"documents": docs}


@router.get("/cv-areas")
async def cv_areas() -> Dict[str, Any]:
    """List available CV specialization templates/areas."""
    return {"areas": painel_perfil.extract_cv_areas()}


@router.get("/file")
async def serve_document_file(
    path: str = Query(..., description="Caminho relativo do arquivo (PDF, MD ou TXT)"),
) -> FileResponse:
    """Serve a generated PDF or Markdown document securely."""
    rel_path = path.replace("\\", "/").strip("/.")
    if not rel_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Caminho ausente.")

    allowed_roots = [
        (painel.ROOT / "cv").resolve(),
        (painel.ROOT / "cover_letters").resolve(),
        (painel.ROOT / "documents" / "interview").resolve(),
        (painel.ROOT / "documents" / "applications" / "_painel").resolve(),
        (painel.ROOT / "documents").resolve(),
    ]
    if painel.ROOT.name == "backend":
        allowed_roots.extend([
            (painel.ROOT.parent / "cv").resolve(),
            (painel.ROOT.parent / "cover_letters").resolve(),
            (painel.ROOT.parent / "documents").resolve(),
        ])

    target: Optional[Path] = None
    for base in [painel.ROOT, painel.ROOT.parent]:
        cand = (base / rel_path).resolve()
        if cand.is_file() and any(cand == ar or ar in cand.parents for ar in allowed_roots):
            target = cand
            break

    if not target or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo não encontrado.")

    allowed_exts = {
        ".pdf": "application/pdf",
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".html": "text/html; charset=utf-8",
    }
    ext = target.suffix.lower()
    media_type = allowed_exts.get(ext)
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
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Execute AI action requested by the panel buttons."""
    step = req.step
    url = req.url or ""

    if step == "avaliar":
        res = await evaluator.evaluate_job(url)
        return {"ok": True, "result": res}
    elif step == "curriculo":
        res = await docgen.generate_cv(url)
        return {"ok": True, "result": res}
    elif step == "carta":
        res = await docgen.generate_cover_letter(url)
        return {"ok": True, "result": res}
    elif step == "entrevista":
        res = await docgen.prepare_interview(url)
        return {"ok": True, "result": res}
    elif step == "redigir":
        cv_res = await docgen.generate_cv(url)
        letter_res = await docgen.generate_cover_letter(url)
        return {"ok": True, "cv": cv_res, "carta": letter_res}
    elif step == "perfil":
        res = painel_ia.montar_perfil()
        return {"ok": True, "result": res}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Passo desconhecido: '{step}'",
        )


@router.post("/documents/delete")
async def delete_document(
    path: str = Query(...),
    docgen: DocGenService = Depends(get_docgen),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Delete a generated PDF and its associated build artifacts."""
    return docgen.delete_document(path)

@router.post("/documents/clear")
async def clear_documents(
    keep_cv: bool = Query(True, description="Se True, preserva todos os currículos e apaga apenas cartas e dossiês"),
    docgen: DocGenService = Depends(get_docgen),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Batch clear generated documents while protecting the user's CVs."""
    return docgen.clear_generated_documents(keep_cv=keep_cv)
