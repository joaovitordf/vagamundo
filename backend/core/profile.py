"""Profile service managing candidate profile, documents, and evolution state."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

from backend.tools import painel, painel_perfil

_here = Path(__file__).resolve()
ROOT = _here.parent.parent.parent if _here.parent.parent.name == "backend" else _here.parent.parent
GEO_PATH = ROOT / "frontend" / "src" / "assets" / "geo_data.json"


class ProfileService:
    """Manages candidate profile, answers, uploaded documents, and evolution ledger."""

    def get_profile_data(self, refresh: bool = False) -> Dict[str, Any]:
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

    def save_evolution(self, data: Dict[str, Any]) -> None:
        painel.save_evolution(data)

    def get_geo(self) -> Dict[str, Any]:
        if GEO_PATH.exists():
            try:
                return json.loads(GEO_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

