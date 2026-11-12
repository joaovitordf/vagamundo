"""Document generation service for CVs, cover letters, and interview prep."""

from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.db.repository import Repository
from backend.tools import painel, painel_ia


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
        job_data: Optional[Dict[str, Any]] = None,
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
        job_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate tailored cover letter in LaTeX and compile to PDF."""
        def _run() -> Dict[str, Any]:
            avaliacao = self._ensure_evaluation(url, evaluation_md)
            res = painel_ia.redigir_carta(url, avaliacao)
            return {"output": res, "ok": True}

        return await asyncio.to_thread(_run)

    async def prepare_interview(
        self,
        url: str,
        job_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate interview dossier and questions."""
        def _run() -> Dict[str, Any]:
            res = painel_ia.preparar_entrevista(url)
            return res

        return await asyncio.to_thread(_run)

    def list_documents(self) -> List[Dict[str, Any]]:
        """List all generated PDFs (CV, cover letter, prep)."""
        return painel.list_generated_documents()

    def delete_document(self, rel_path: str) -> Dict[str, Any]:
        """Safely delete a single generated document and its LaTeX/Markdown build artifacts."""
        rel = str(rel_path or "").replace("\\", "/").strip("/.")
        if not rel:
            return {"deleted": False, "error": "Caminho ausente"}

        allowed_dirs = [
            (painel.ROOT / "cover_letters").resolve(),
            (painel.ROOT / "documents" / "interview").resolve(),
            (painel.ROOT / "cv").resolve(),
            (painel.ROOT / "documents" / "applications" / "_painel").resolve(),
        ]
        if painel.ROOT.name == "backend":
            allowed_dirs.extend([
                (painel.ROOT.parent / "cover_letters").resolve(),
                (painel.ROOT.parent / "documents" / "interview").resolve(),
                (painel.ROOT.parent / "cv").resolve(),
            ])

        target = None
        for base in [painel.ROOT, painel.ROOT.parent]:
            cand = (base / rel).resolve()
            if cand.is_file() and any(cand == ad or ad in cand.parents for ad in allowed_dirs):
                target = cand
                break

        if not target or not target.is_file():
            return {"deleted": False, "error": "Arquivo não encontrado ou acesso não permitido"}

        protected_stems = {"main_example", "reference_template", "cover_example", "cover"}
        if target.stem in protected_stems or target.name == "cover.cls":
            return {"deleted": False, "error": "Modelos base e templates do sistema não podem ser excluídos"}

        parent_dir = target.parent
        removed = []
        for suffix in (".pdf", ".tex", ".aux", ".log", ".out", ".fls", ".fdb_latexmk", ".synctex.gz", ".md"):
            cand = parent_dir / f"{target.stem}{suffix}"
            if cand.is_file():
                try:
                    cand.unlink()
                    removed.append(cand.name)
                except Exception:
                    pass

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

        protected_stems = {"main_example", "reference_template", "cover_example", "cover"}
        protected_names = {"cover.cls", "reference_template.tex", "main_example.tex", "cover_example.tex"}

        for d in dirs_to_clean:
            if not d.exists() or not d.is_dir():
                continue
            for item in d.glob("*"):
                if item.is_dir():
                    continue
                if item.stem in protected_stems or item.name in protected_names:
                    continue
                if item.suffix.lower() in (".pdf", ".tex", ".md", ".aux", ".log", ".out", ".fls", ".fdb_latexmk", ".synctex.gz", ".txt"):
                    try:
                        item.unlink()
                        removed.append(str(item.name))
                    except Exception:
                        pass

        return {"ok": True, "removed": removed, "count": len(removed), "kept_cv": keep_cv}
