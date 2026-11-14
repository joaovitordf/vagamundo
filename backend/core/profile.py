"""Profile service managing candidate profile, documents, and evolution state."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict

from backend.core.constants import ROOT
from backend.tools import ai_providers, painel, painel_ia, painel_perfil

logger = logging.getLogger(__name__)

GEO_PATH = ROOT / "frontend" / "src" / "assets" / "geo_data.json"


class ProfileService:
    """Manages candidate profile, answers, uploaded documents, and evolution ledger."""

    def get_profile_data(self) -> Dict[str, Any]:
        return {
            "schema": [{"title": t, "fields": f} for t, f in painel_perfil.SCHEMA],
            "answers": painel_perfil.load_answers(),
            "files": painel_perfil.list_uploads(),
            "privacy": painel_perfil.privacy(),
            "ready": painel_perfil.profile_ready(),
            "profile": painel_perfil.profile_text(),
            "report": painel.claude_answer(painel.PERFIL_KEY, "perfil"),
        }

    def save_profile_answers(self, answers: Dict[str, Any]) -> Dict[str, Any]:
        clean = painel_perfil.clean_answers(answers)
        painel_perfil.save_answers(clean)
        painel_perfil.sync_local_queries_from_answers(clean, overwrite=False)
        return {"answers": clean}

    def list_uploads(self) -> Dict[str, Any]:
        return painel_perfil.list_uploads()

    def save_upload(self, kind: str, name: str, data_b64: str) -> Dict[str, Any]:
        dest = painel_perfil.save_upload(kind, name, data_b64)
        return {"saved": str(dest), "files": painel_perfil.list_uploads()}

    def remove_upload(self, kind: str, name: str) -> Dict[str, Any]:
        painel_perfil.remove_upload(kind, name)
        return {"files": painel_perfil.list_uploads()}

    def get_evolution(self) -> Dict[str, Any]:
        return painel.load_evolution()

    def update_evolution(self) -> Dict[str, Any]:
        return painel.update_evolution()

    def build_ai_profile(self) -> str:
        """Assemble the AI-consolidated candidate profile report and persist it locally."""
        answers = painel_perfil.load_answers()
        respostas_texto = painel_perfil.format_answers(answers)
        result = painel_ia.montar_perfil(respostas_texto)
        out = painel.claude_file(painel.PERFIL_KEY, "perfil", base=painel.CLAUDE_DIR)
        out.parent.mkdir(parents=True, exist_ok=True)
        clean_out = result.rstrip() + "\n"
        out.write_text(clean_out, encoding="utf-8")

        # Persiste espelho local .gitignored para leitura direta sem editar arquivos rastreados
        local_md = painel_perfil.local_profile_path()
        try:
            default_claude = painel.ROOT / "documents" / "applications" / "_painel"
            if painel.CLAUDE_DIR.resolve() == default_claude.resolve() or painel_perfil.DOCUMENTS in painel.CLAUDE_DIR.parents:
                local_md.parent.mkdir(parents=True, exist_ok=True)
                local_md.write_text(clean_out, encoding="utf-8")
        except OSError:
            pass
        painel_perfil.sync_local_queries_from_answers(answers, overwrite=False)
        return result

    def organize_profile_from_documents(self, overwrite: bool = False) -> Dict[str, Any]:
        """Extract questionnaire fields from uploaded PDFs, sync queries, and build AI profile."""
        if not painel_perfil.has_documents():
            raise ValueError("Envie ao menos um currículo ou perfil do LinkedIn em PDF antes de organizar.")

        if not painel_ia.is_available():
            return {
                "ok": False,
                "organized": False,
                "reason": "ai_unconfigured",
                "detail": "Nenhum provedor de IA configurado ainda. Configure em Configurações ou preencha o formulário manualmente.",
                "updated_fields": [],
                "profile": self.get_profile_data(),
            }

        existing = painel_perfil.load_answers()
        try:
            extracted = painel_ia.extrair_respostas_de_documentos(existing_answers=existing)
        except painel_ia.ConsentRequired as exc:
            return {
                "ok": False,
                "organized": False,
                "reason": "consent_required",
                "detail": str(exc),
                "updated_fields": [],
                "profile": self.get_profile_data(),
            }
        except ai_providers.ProviderError as exc:
            if not painel_ia.is_available() or isinstance(ai_providers.get_ai_provider(), ai_providers.UnconfiguredProvider):
                return {
                    "ok": False,
                    "organized": False,
                    "reason": "ai_unconfigured",
                    "detail": str(exc),
                    "updated_fields": [],
                    "profile": self.get_profile_data(),
                }
            raise

        merged = dict(existing)
        updated_fields: list[str] = []
        for key, value in extracted.items():
            if not value:
                continue
            if overwrite or not merged.get(key):
                if merged.get(key) != value:
                    updated_fields.append(key)
                merged[key] = value

        clean = painel_perfil.clean_answers(merged)
        painel_perfil.save_answers(clean)
        should_refresh_queries = (
            overwrite
            or not painel_perfil.local_queries_path().exists()
            or ("cargos" in updated_fields and not existing.get("cargos"))
        )
        painel_perfil.sync_local_queries_from_answers(clean, overwrite=should_refresh_queries)
        self.build_ai_profile()
        return {
            "ok": True,
            "organized": True,
            "updated_fields": updated_fields,
            "profile": self.get_profile_data(),
        }

    def save_evolution(self, data: Dict[str, Any]) -> None:
        painel.save_evolution(data)

    def get_geo(self) -> Dict[str, Any]:
        if GEO_PATH.exists():
            try:
                return json.loads(GEO_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load geo data from %s: %s", GEO_PATH, exc)
        return {}

