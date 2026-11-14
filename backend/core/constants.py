"""Shared constants, path resolution, security allowlists, and atomic I/O helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve()
ROOT: Path = _here.parent.parent.parent if _here.parent.parent.name == "backend" else _here.parent.parent

# Canonical screening & auto-mode thresholds
HIGH_FIT_MIN_SCORE = 75
MED_FIT_MIN_SCORE = 60
LOW_SCORE_AUTO_DISCARD_THRESHOLD = 40
AUTO_SCORE_MIN = 45
AUTO_SCORE_MAX = 95
AUTO_SCORE_DEFAULT = 60

DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
)

DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "[::1]",
    "::1",
    "testserver",
})

ALLOWED_DOC_EXTS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}

PROTECTED_DOC_STEMS: frozenset[str] = frozenset({
    "main_example",
    "reference_template",
    "cover_example",
    "cover",
})


def _parse_env_csv(var_name: str) -> list[str]:
    raw = os.environ.get(var_name) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def get_allowed_origins() -> list[str]:
    """Return allowed CORS origins, extensible via VAGAMUNDO_ALLOWED_ORIGINS."""
    extras = _parse_env_csv("VAGAMUNDO_ALLOWED_ORIGINS")
    return list(dict.fromkeys([*DEFAULT_ALLOWED_ORIGINS, *extras]))


def get_allowed_hosts() -> set[str]:
    """Return allowed Host headers, extensible via VAGAMUNDO_ALLOWED_HOSTS."""
    extras = [h.lower() for h in _parse_env_csv("VAGAMUNDO_ALLOWED_HOSTS")]
    return set(DEFAULT_ALLOWED_HOSTS) | set(extras)


def resolve_safe_document_path(
    rel_path: str,
    base_root: Path | None = None,
    *,
    include_all_documents: bool = False,
) -> Path | None:
    """Resolve a user-supplied relative path strictly within generated document directories."""
    rel = str(rel_path or "").replace("\\", "/").strip("/.")
    if not rel:
        return None

    anchor = (base_root or ROOT).resolve()
    bases = [anchor]
    if anchor.name == "backend":
        bases.append(anchor.parent)

    allowed_dirs: list[Path] = []
    subpaths = (
        ("cover_letters",),
        ("documents", "interview"),
        ("cv",),
        ("documents", "applications", "_painel"),
    )
    if include_all_documents:
        subpaths = (*subpaths, ("documents",))

    for base in bases:
        for parts in subpaths:
            allowed_dirs.append(base.joinpath(*parts).resolve())

    for base in bases:
        cand = (base / rel).resolve()
        if cand.is_file() and any(cand == ad or ad in cand.parents for ad in allowed_dirs):
            return cand
    return None


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    """Atomically write JSON to disk using a same-directory temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=indent)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
