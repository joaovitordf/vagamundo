"""Helpers de compatibilidade do pacote tools/ia para resolução da fachada painel_ia e módulos irmãos."""

from __future__ import annotations

import sys
from typing import Any

_PKG = __package__ or ""
_TOOLS_PKG = _PKG.rsplit(".", 1)[0] if "." in _PKG else ""
_FACADE_NAME = f"{_TOOLS_PKG}.painel_ia" if _TOOLS_PKG else "painel_ia"

if _TOOLS_PKG:
    from .. import (
        ai_providers,
        painel_perfil,
        posting_guard,
        posting_signals,
        privacy_utils,
        rank_state,
    )
else:
    import ai_providers
    import painel_perfil
    import posting_guard
    import posting_signals
    import privacy_utils
    import rank_state


def facade() -> Any:
    """Retorna a instância ativa de painel_ia correspondente ao pacote de importação."""
    mod = sys.modules.get(_FACADE_NAME)
    if mod is not None:
        return mod
    return sys.modules.get("backend.tools.painel_ia") or sys.modules.get("painel_ia")
