"""Document generation service for CVs, cover letters, and interview prep."""

from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.core.constants import PROTECTED_DOC_STEMS, resolve_safe_document_path
from backend.db.repository import Repository
from backend.tools import painel, painel_ia

logger = logging.getLogger(__name__)


class DocGenService:
    """Manages LaTeX compilation and document lifecycle."""

    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo or Repository()

    def _ensure_evaluation(self, url: str, evaluation_md: Optional[str] = None) -> str:
        if evaluation_md and evaluation_md.strip():
            return evaluation_md

        cached = painel.claude_answers(url).get("avaliar")
        if cached and cached.strip():
            return cached

        # Generate evaluation on demand
        eval_text = painel_ia.avaliar_vaga(url)
        eval_out = painel.claude_file(url, "avaliar")
        eval_out.parent.mkdir(parents=True, exist_ok=True)
        eval_out.write_text(eval_text + "\n", encoding="utf-8")
        return eval_text

    async def generate_cv(
        self,
        url: str,
        evaluation_md: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate tailored CV in LaTeX and compile to PDF."""
        def _run() -> Dict[str, Any]:
            avaliacao = self._ensure_evaluation(url, evaluation_md)
            res = painel_ia.redigir_curriculo(url, avaliacao)
            return {"output": res, "ok": True}

        return await asyncio.to_thread(_run)

    async def generate_cover_letter(
        self,
        url: str,
        evaluation_md: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate tailored cover letter in LaTeX and compile to PDF."""
        def _run() -> Dict[str, Any]:
            avaliacao = self._ensure_evaluation(url, evaluation_md)
            res = painel_ia.redigir_carta(url, avaliacao)
            return {"output": res, "ok": True}

        return await asyncio.to_thread(_run)

    async def prepare_interview(self, url: str) -> Dict[str, Any]:
        """Generate interview dossier and questions."""
        def _run() -> Dict[str, Any]:
            return painel_ia.preparar_entrevista(url)

        return await asyncio.to_thread(_run)

    def list_documents(self) -> List[Dict[str, Any]]:
        """List all generated PDFs (CV, cover letter, prep)."""
        return painel.list_generated_documents()

    def delete_document(self, rel_path: str) -> Dict[str, Any]:
        """Safely delete a single generated document and its LaTeX/Markdown build artifacts."""
        rel = str(rel_path or "").replace("\\", "/").strip("/.")
        if not rel:
            return {"deleted": False, "error": "Caminho ausente"}

        target = resolve_safe_document_path(rel, base_root=painel.ROOT, include_all_documents=False)
        if not target or not target.is_file():
            return {"deleted": False, "error": "Arquivo não encontrado ou acesso não permitido"}

        if target.stem in PROTECTED_DOC_STEMS or target.name == "cover.cls":
            return {"deleted": False, "error": "Modelos base e templates do sistema não podem ser excluídos"}

        parent_dir = target.parent
        removed = []
        for suffix in (".pdf", ".tex", ".aux", ".log", ".out", ".fls", ".fdb_latexmk", ".synctex.gz", ".md"):
            cand = parent_dir / f"{target.stem}{suffix}"
            if cand.is_file():
                try:
                    cand.unlink()
                    removed.append(cand.name)
                except OSError as exc:
                    logger.warning("Failed to remove document artifact %s: %s", cand, exc)

        return {"deleted": True, "path": rel, "removed": removed}

    def clear_generated_documents(self, keep_cv: bool = True) -> Dict[str, Any]:
        """Clear generated documents. If keep_cv=True, preserves all CVs and templates."""
        removed = []

        dirs_to_clean = []
        for base in [painel.ROOT, painel.ROOT.parent]:
            dirs_to_clean.append((base / "cover_letters").resolve())
            dirs_to_clean.append((base / "documents" / "interview").resolve())
            if not keep_cv:
                dirs_to_clean.append((base / "cv").resolve())

        protected_names = {"cover.cls", "reference_template.tex", "main_example.tex", "cover_example.tex"}

        for d in dirs_to_clean:
            if not d.exists() or not d.is_dir():
                continue
            for item in d.glob("*"):
                if item.is_dir():
                    continue
                if item.stem in PROTECTED_DOC_STEMS or item.name in protected_names:
                    continue
                if item.suffix.lower() in (".pdf", ".tex", ".md", ".aux", ".log", ".out", ".fls", ".fdb_latexmk", ".synctex.gz", ".txt"):
                    try:
                        item.unlink()
                        removed.append(str(item.name))
                    except OSError as exc:
                        logger.warning("Failed to clear generated artifact %s: %s", item, exc)

        return {"ok": True, "removed": removed, "count": len(removed), "kept_cv": keep_cv}
