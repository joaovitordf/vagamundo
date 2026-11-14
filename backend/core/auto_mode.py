"""Orchestrator service for Autonomous Search + AI Triage + Auto-Interest mode."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
import random
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.core.constants import (
    AUTO_SCORE_DEFAULT,
    AUTO_SCORE_MAX,
    AUTO_SCORE_MIN,
    LOW_SCORE_AUTO_DISCARD_THRESHOLD,
    atomic_write_json,
)
from backend.core.evaluator import EvaluatorService
from backend.core.recruiter_service import RecruiterService
from backend.core.scanner import ScannerService
from backend.db.repository import Repository
from backend.tools import ai_providers, painel, painel_ia

logger = logging.getLogger(__name__)


PROFILE_KEY_CONFIG = "auto_mode"
PROFILE_KEY_HISTORY = "auto_mode_history"
PROFILE_KEY_RECRUITER_CONFIG = "auto_mode_recruiters"
PROFILE_KEY_RECRUITER_HISTORY = "auto_mode_recruiters_history"

JOBS_COOLDOWN_DEFAULT = 300
JOBS_COOLDOWN_MIN = 120
JOBS_COOLDOWN_MAX = 1800

RECRUITER_COOLDOWN_DEFAULT = 30
RECRUITER_COOLDOWN_MIN = 15
RECRUITER_COOLDOWN_MAX = 300

MAX_HISTORY_ITEMS = 40
MAX_ROUND_HISTORY = 15
MAX_CONSECUTIVE_FATAL_ERRORS = 5

DEFAULT_AUTO_CONFIG: Dict[str, Any] = {
    "min_score": AUTO_SCORE_DEFAULT,
    "jobage": 7,
    "region": "all",
    "hide_undated": False,
    "portals": None,
    "continuous": True,
    "cooldown_seconds": JOBS_COOLDOWN_DEFAULT,
}

DEFAULT_RECRUITER_CONFIG: Dict[str, Any] = {
    "min_score": AUTO_SCORE_DEFAULT,
    "continuous": True,
    "cooldown_seconds": RECRUITER_COOLDOWN_DEFAULT,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clamp_int(val: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _norm_pair_key(keywords: List[str]) -> str:
    return "|".join(sorted(str(k).strip().lower() for k in keywords if str(k).strip()))


def _detect_rate_limit_in_portals(portals_map: Any) -> bool:
    if not isinstance(portals_map, dict) or not portals_map:
        return False
    total = 0
    errors = 0
    markers = ("429", "403", "rate limit", "too many", "blocked", "captcha", "cloudflare")
    for info in portals_map.values():
        if not isinstance(info, dict):
            continue
        total += 1
        err_text = str(info.get("error") or "").strip().lower()
        status_text = str(info.get("status") or "").strip().lower()
        if err_text or status_text in ("error", "failed"):
            errors += 1
            if any(m in err_text for m in markers):
                return True
    if total >= 3 and (errors / total) >= 0.3:
        return True
    return False


def _parse_date_prefix(raw_date: Any) -> Optional[date]:
    s = str(raw_date or "").strip()
    if len(s) < 10:
        return None
    head = s[:10]
    try:
        return date.fromisoformat(head)
    except ValueError:
        pass
    try:
        return datetime.strptime(head, "%d/%m/%Y").date()
    except ValueError:
        return None


def _within_jobage(raw_date: Any, max_days: int, hide_undated: bool, today_day: Optional[date] = None) -> bool:
    posted = _parse_date_prefix(raw_date)
    if posted is None:
        return not hide_undated
    ref = today_day or date.today()
    return (ref - posted).days <= max_days


class AutoModeService:
    """Runs end-to-end automated keyword picking, portal search (<=7d), and AI triage."""

    def __init__(
        self,
        repo: Optional[Repository] = None,
        scanner: Optional[ScannerService] = None,
        evaluator: Optional[EvaluatorService] = None,
        recruiter_service: Optional[RecruiterService] = None,
    ):
        self.repo = repo or Repository()
        self.scanner = scanner or ScannerService(repo=self.repo)
        self.evaluator = evaluator or EvaluatorService(repo=self.repo)
        self.recruiter_service = recruiter_service or RecruiterService(repo=self.repo)

        self._lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._out_file_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._skip_cooldown_event = threading.Event()
        self._wake_event = threading.Event()
        self._queued_recruiter_post_ids: Set[int] = set()
        self._recruiter_current_title = ""
        self._session_totals: Dict[str, int] = self._empty_counts()
        self._session_promoted_items: List[Dict[str, Any]] = []
        self.state: Dict[str, Any] = self._empty_state()

    @staticmethod
    def _empty_counts() -> Dict[str, int]:
        return {
            "found": 0,
            "to_screen": 0,
            "screened": 0,
            "promoted": 0,
            "discarded": 0,
            "talent_pools_discarded": 0,
            "not_a_job": 0,
            "kept_low_score": 0,
            "pending": 0,
            "errors": 0,
        }

    @classmethod
    def _empty_state(cls) -> Dict[str, Any]:
        return {
            "running": False,
            "mode": "jobs",
            "phase": "idle",
            "run_id": None,
            "continuous": True,
            "cooldown_seconds": JOBS_COOLDOWN_DEFAULT,
            "cooldown_remaining_s": 0,
            "next_run_at": None,
            "backoff_reason": None,
            "round": 0,
            "round_jobs_found": 0,
            "round_eligible_count": 0,
            "round_screened": 0,
            "round_promoted": 0,
            "round_discarded": 0,
            "round_errors": 0,
            "round_history": [],
            "keywords": [],
            "rationale": "",
            "keyword_source": "",
            "jobage": 7,
            "min_score": AUTO_SCORE_DEFAULT,
            "region": "all",
            "hide_undated": False,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "undone": False,
            "counts": cls._empty_counts(),
            "promoted_items": [],
        }

    # ------------------------------------------------------------------
    # Persistent user preferences & recent keyword history (whitelabel DB)
    # ------------------------------------------------------------------

    def _load_profile_json_config(self, profile_key: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
        cfg = dict(defaults)
        raw = self.repo.get_profile(profile_key)
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    cfg.update(loaded)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Failed to decode %s config JSON: %s", profile_key, exc)
        return cfg

    def get_config(self) -> Dict[str, Any]:
        cfg = self._load_profile_json_config(PROFILE_KEY_CONFIG, DEFAULT_AUTO_CONFIG)
        cfg["min_score"] = _clamp_int(cfg.get("min_score"), AUTO_SCORE_DEFAULT, AUTO_SCORE_MIN, AUTO_SCORE_MAX)
        cfg["jobage"] = _clamp_int(cfg.get("jobage"), 7, 1, 7)
        cfg["hide_undated"] = bool(cfg.get("hide_undated", False))
        cfg["region"] = str(cfg.get("region") or "all")
        cfg["continuous"] = bool(cfg.get("continuous", True))
        cfg["cooldown_seconds"] = _clamp_int(
            cfg.get("cooldown_seconds"),
            JOBS_COOLDOWN_DEFAULT,
            JOBS_COOLDOWN_MIN,
            JOBS_COOLDOWN_MAX,
        )
        return cfg

    def save_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        curr = self.get_config()
        if "min_score" in patch and patch["min_score"] is not None:
            curr["min_score"] = _clamp_int(patch["min_score"], curr["min_score"], AUTO_SCORE_MIN, AUTO_SCORE_MAX)
        if "jobage" in patch and patch["jobage"] is not None:
            curr["jobage"] = _clamp_int(patch["jobage"], 7, 1, 7)
        if "region" in patch and patch["region"] is not None:
            curr["region"] = str(patch["region"] or "all")
        if "hide_undated" in patch and patch["hide_undated"] is not None:
            curr["hide_undated"] = bool(patch["hide_undated"])
        if "portals" in patch:
            curr["portals"] = patch["portals"] if isinstance(patch["portals"], list) else None
        if "continuous" in patch and patch["continuous"] is not None:
            curr["continuous"] = bool(patch["continuous"])
        if "cooldown_seconds" in patch and patch["cooldown_seconds"] is not None:
            curr["cooldown_seconds"] = _clamp_int(
                patch["cooldown_seconds"],
                curr["cooldown_seconds"],
                JOBS_COOLDOWN_MIN,
                JOBS_COOLDOWN_MAX,
            )
        self.repo.set_profile(PROFILE_KEY_CONFIG, json.dumps(curr, ensure_ascii=False))
        return curr

    def get_recruiter_config(self) -> Dict[str, Any]:
        cfg = self._load_profile_json_config(PROFILE_KEY_RECRUITER_CONFIG, DEFAULT_RECRUITER_CONFIG)
        cfg["min_score"] = _clamp_int(cfg.get("min_score"), AUTO_SCORE_DEFAULT, AUTO_SCORE_MIN, AUTO_SCORE_MAX)
        cfg["continuous"] = bool(cfg.get("continuous", True))
        cfg["cooldown_seconds"] = _clamp_int(
            cfg.get("cooldown_seconds"),
            RECRUITER_COOLDOWN_DEFAULT,
            RECRUITER_COOLDOWN_MIN,
            RECRUITER_COOLDOWN_MAX,
        )
        return cfg

    def save_recruiter_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        curr = self.get_recruiter_config()
        if "min_score" in patch and patch["min_score"] is not None:
            curr["min_score"] = _clamp_int(patch["min_score"], curr["min_score"], AUTO_SCORE_MIN, AUTO_SCORE_MAX)
        if "continuous" in patch and patch["continuous"] is not None:
            curr["continuous"] = bool(patch["continuous"])
        if "cooldown_seconds" in patch and patch["cooldown_seconds"] is not None:
            curr["cooldown_seconds"] = _clamp_int(
                patch["cooldown_seconds"],
                curr["cooldown_seconds"],
                RECRUITER_COOLDOWN_MIN,
                RECRUITER_COOLDOWN_MAX,
            )
        self.repo.set_profile(PROFILE_KEY_RECRUITER_CONFIG, json.dumps(curr, ensure_ascii=False))
        return curr

    def _get_recent_history(self, profile_key: str = PROFILE_KEY_HISTORY) -> List[str]:
        raw = self.repo.get_profile(profile_key)
        if not raw:
            return []
        try:
            items = json.loads(raw)
            return [str(x) for x in items if str(x).strip()][-MAX_HISTORY_ITEMS:] if isinstance(items, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _append_history(self, keywords: List[str], profile_key: str = PROFILE_KEY_HISTORY) -> None:
        label = ", ".join(keywords)
        if not label:
            return
        hist = [h for h in self._get_recent_history(profile_key) if h.lower() != label.lower()]
        hist.append(label)
        self.repo.set_profile(profile_key, json.dumps(hist[-MAX_HISTORY_ITEMS:], ensure_ascii=False))

    # ------------------------------------------------------------------
    # Orchestration lifecycle & Anti-Ban Cooldown
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_cooldown(
        *,
        mode: str,
        base_cooldown: int,
        round_had_items: bool,
        rate_limited: bool,
        consecutive_empty: int,
        consecutive_rate_limits: int,
        jitter_fn: Optional[Any] = None,
    ) -> Tuple[int, Optional[str]]:
        rand = jitter_fn or random.randint
        if mode == "recruiters":
            base = _clamp_int(base_cooldown, RECRUITER_COOLDOWN_DEFAULT, RECRUITER_COOLDOWN_MIN, RECRUITER_COOLDOWN_MAX)
            if rate_limited:
                exp = min(900, base * (2 ** min(max(1, consecutive_rate_limits), 4)))
                total = min(900, exp + rand(5, 25))
                return total, f"Rate-limit/erro externo detectado — intervalo ampliado para {total}s (proteção anti-ban)"
            if consecutive_empty >= 4:
                factor = min(4.0, 1.0 + (consecutive_empty - 3) * 0.5)
                exp = min(300, int(base * factor))
                total = min(300, exp + rand(0, 15))
                return total, f"{consecutive_empty} rodadas sem novos candidatos — reduzindo frequência"
            if round_had_items:
                return min(300, base + rand(0, 15)), None
            return min(300, max(RECRUITER_COOLDOWN_MIN, base - 5) + rand(0, 10)), None

        base = _clamp_int(base_cooldown, JOBS_COOLDOWN_DEFAULT, JOBS_COOLDOWN_MIN, JOBS_COOLDOWN_MAX)
        if rate_limited:
            exp = min(1800, base * (2 ** min(max(1, consecutive_rate_limits), 3)))
            total = min(1800, exp + rand(15, 60))
            return total, f"Bloqueio/instabilidade em portais detectada — intervalo ampliado para {max(1, total // 60)} min"
        if consecutive_empty >= 3:
            exp = min(900, int(base * 1.5))
            total = min(900, exp + rand(10, 45))
            return total, f"{consecutive_empty} rodadas sem novas vagas elegíveis — intervalo ampliado"
        return min(1800, base + rand(5, 45)), None

    def _pick_keywords_for_round(
        self,
        *,
        profile_key: str,
        region: str,
        mode: str,
        session_tried: List[str],
    ) -> Tuple[List[str], str, str]:
        persisted = self._get_recent_history(profile_key)
        seen_lower: Set[str] = set()
        avoid_recent: List[str] = []
        for item in [*persisted, *session_tried]:
            norm = str(item).strip()
            if norm and norm.lower() not in seen_lower:
                seen_lower.add(norm.lower())
                avoid_recent.append(norm)

        try:
            picked = painel_ia.sortear_palavras_chave_busca(
                avoid_recent=avoid_recent, region=region, mode=mode, limit=1
            )
        except TypeError:
            try:
                picked = painel_ia.sortear_palavras_chave_busca(
                    avoid_recent=avoid_recent, region=region, mode=mode
                )
            except TypeError:
                picked = painel_ia.sortear_palavras_chave_busca(
                    avoid_recent=avoid_recent, region=region
                )

        keywords = list(picked.get("keywords") or [])[:1]
        rationale = picked.get("rationale") or ""
        source = picked.get("source") or "ai"

        # Garante rotação caso a sessão contínua já tenha testado o mesmo termo
        if keywords and session_tried:
            session_pair_keys = {
                _norm_pair_key([p.strip() for p in item.split(",") if p.strip()])
                for item in session_tried
            }
            if _norm_pair_key(keywords) in session_pair_keys:
                try:
                    fallback = painel_ia._fallback_cv_keywords(avoid_recent=avoid_recent, limit=1, mode=mode)
                except TypeError:
                    fallback = painel_ia._fallback_cv_keywords(avoid_recent=avoid_recent, limit=1)
                if fallback and _norm_pair_key(fallback) not in session_pair_keys:
                    keywords = fallback
                    rationale = "Rotação automática de competências do currículo."
                    source = "cv_fallback"

        if not keywords:
            raise ValueError("Nenhuma palavra-chave pôde ser sorteada do seu currículo.")

        label = ", ".join(keywords)
        if label not in session_tried:
            session_tried.append(label)
        self._append_history(keywords, profile_key)
        return keywords, rationale, source

    def _wait_cooldown(self, seconds: int, reason: Optional[str] = None) -> str:
        if self._should_stop():
            return "cancelled"

        wait_s = max(1, int(seconds))
        self._skip_cooldown_event.clear()
        self._wake_event.clear()
        if self._should_stop():
            return "cancelled"

        next_dt = datetime.now(timezone.utc) + timedelta(seconds=wait_s)
        with self._lock:
            self.state["phase"] = "cooldown"
            self.state["cooldown_seconds"] = wait_s
            self.state["cooldown_remaining_s"] = wait_s
            self.state["next_run_at"] = next_dt.isoformat(timespec="seconds")
            self.state["backoff_reason"] = reason

        while True:
            if self._should_stop():
                return "cancelled"
            if self._skip_cooldown_event.is_set():
                self._skip_cooldown_event.clear()
                self._wake_event.clear()
                return "skipped"

            remaining = (next_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                return "elapsed"

            self._wake_event.wait(timeout=min(0.5, remaining))

    def _clear_cooldown_fields(self) -> None:
        with self._lock:
            self.state["cooldown_seconds"] = 0
            self.state["cooldown_remaining_s"] = 0
            self.state["next_run_at"] = None
            self.state["backoff_reason"] = None

    def _record_round_summary(self, entry: Dict[str, Any]) -> None:
        with self._lock:
            hist = list(self.state.get("round_history") or [])
            hist.append(entry)
            self.state["round_history"] = hist[-MAX_ROUND_HISTORY:]

    def validate_ready(self) -> None:
        env = ai_providers.load_env_file()
        if not ai_providers.has_consent(env):
            raise ValueError(
                "Consentimento de IA necessário: acesse Configurações e confirme o envio do perfil antes de usar o Modo Automático."
            )
        if not painel_ia.is_available():
            raise ValueError(
                "Nenhum provedor de IA ativo/configurado. Verifique suas credenciais em Configurações."
            )

    def _ensure_idle_locked(self) -> None:
        if self.state["running"]:
            raise RuntimeError("O Modo Automático já está em execução.")
        if self.scanner.running:
            raise RuntimeError("Já existe uma busca de vagas em andamento.")
        if self.evaluator.batch_status().get("running"):
            raise RuntimeError("Já existe uma triagem em lote em andamento.")

    def start(
        self,
        region: Optional[str] = None,
        portals: Optional[List[str]] = None,
        jobage: Optional[int] = None,
        min_score: Optional[int] = None,
        hide_undated: Optional[bool] = None,
        continuous: Optional[bool] = None,
        cooldown_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.validate_ready()

        saved_cfg = self.save_config({
            k: v for k, v in {
                "region": region,
                "portals": portals,
                "jobage": jobage,
                "min_score": min_score,
                "hide_undated": hide_undated,
                "continuous": continuous,
                "cooldown_seconds": cooldown_seconds,
            }.items() if v is not None
        })

        with self._lock:
            self._ensure_idle_locked()

            run_id = uuid.uuid4().hex[:12]
            self._cancel_event.clear()
            self._skip_cooldown_event.clear()
            self._wake_event.clear()
            self._session_totals = self._empty_counts()
            self._session_promoted_items = []
            self.state = {
                **self._empty_state(),
                "running": True,
                "phase": "picking_keywords",
                "run_id": run_id,
                "continuous": bool(saved_cfg["continuous"]),
                "cooldown_seconds": int(saved_cfg["cooldown_seconds"]),
                "round": 1,
                "jobage": saved_cfg["jobage"],
                "min_score": saved_cfg["min_score"],
                "region": saved_cfg["region"],
                "hide_undated": saved_cfg["hide_undated"],
                "started_at": _now_iso(),
            }

        threading.Thread(
            target=self._run,
            args=(run_id, saved_cfg),
            daemon=True,
        ).start()
        return {"ok": True, "run_id": run_id, "config": saved_cfg}

    def _should_stop(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self) -> Dict[str, Any]:
        with self._lock:
            if not self.state["running"]:
                return {"ok": False, "running": False}
            self._cancel_event.set()
            self._wake_event.set()
        self.scanner.cancel()
        return {"ok": True, "cancelling": True}

    def skip_cooldown(self) -> Dict[str, Any]:
        with self._lock:
            if not self.state["running"] or self.state.get("phase") != "cooldown":
                return {"ok": False, "skipped": False}
            self._skip_cooldown_event.set()
            self._wake_event.set()
        return {"ok": True, "skipped": True}

    def enqueue_recruiter_posts(self, post_ids: List[int]) -> bool:
        """Queue freshly imported LinkedIn/paste post IDs for the next auto round and wake cooldown if running."""
        valid_ids = {int(pid) for pid in (post_ids or []) if pid is not None}
        with self._lock:
            if valid_ids:
                self._queued_recruiter_post_ids.update(valid_ids)
                # Keep queue bounded for safety
                if len(self._queued_recruiter_post_ids) > 100:
                    self._queued_recruiter_post_ids = set(sorted(self._queued_recruiter_post_ids)[-100:])
            return self._wake_if_recruiter_cooldown_locked()

    def _wake_if_recruiter_cooldown_locked(self) -> bool:
        if (
            not self.state.get("running")
            or self.state.get("mode") != "recruiters"
            or self.state.get("phase") != "cooldown"
        ):
            return False
        self._skip_cooldown_event.set()
        self._wake_event.set()
        return True

    def wake_if_recruiter_cooldown(self) -> bool:
        """Wake recruiter auto-mode immediately from cooldown when user imports new LinkedIn posts."""
        with self._lock:
            return self._wake_if_recruiter_cooldown_locked()

    def _finish_state(self, phase: str, error: Optional[str] = None) -> None:
        with self._lock:
            self.state["running"] = False
            self.state["phase"] = phase
            self.state["cooldown_remaining_s"] = 0
            self.state["next_run_at"] = None
            self.state["finished_at"] = _now_iso()
            if error:
                self.state["error"] = error

    def _sync_batch_counts(self, batch: Dict[str, Any], to_screen: int, found_in_round: int = 0) -> Tuple[int, int, int, int]:
        r_screened = int(batch.get("current") or 0)
        r_promoted = int(batch.get("auto_interested") or 0)
        r_errors = int(batch.get("errors") or 0)
        results_map = batch.get("results") or {}
        r_discarded = sum(1 for r in results_map.values() if isinstance(r, dict) and r.get("discarded"))
        r_pending = max(0, to_screen - r_promoted - r_discarded)
        r_items = list(batch.get("promoted_items") or [])

        with self._lock:
            self._session_totals["found"] += found_in_round
            self._session_totals["to_screen"] += to_screen
            self._session_totals["screened"] += r_screened
            self._session_totals["promoted"] += r_promoted
            self._session_totals["discarded"] += r_discarded
            self._session_totals["errors"] += r_errors
            self._session_totals["pending"] = r_pending
            self._session_promoted_items.extend(r_items)

            self.state["counts"] = dict(self._session_totals)
            self.state["promoted_items"] = list(self._session_promoted_items)
            self.state["round_screened"] = r_screened
            self.state["round_promoted"] = r_promoted
            self.state["round_discarded"] = r_discarded
            self.state["round_errors"] = r_errors

        return r_screened, r_promoted, r_discarded, r_errors

    def _read_raw_scanner_payload(self) -> Dict[str, Any]:
        with self._out_file_lock:
            if not self.scanner.out.exists():
                return {"meta": None, "new": []}
            try:
                data = json.loads(self.scanner.out.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {"meta": None, "new": []}
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read scanner payload %s: %s", self.scanner.out, exc)
                return {"meta": None, "new": []}

    def _merge_scanner_results(
        self,
        prior_jobs: List[Dict[str, Any]],
        fresh_payload: Dict[str, Any],
    ) -> None:
        """Preserve pending (unpromoted/undiscarded) jobs across continuous auto rounds."""
        if not prior_jobs:
            return
        fresh_jobs = [j for j in (fresh_payload.get("new") or []) if isinstance(j, dict) and j.get("url")]
        fresh_urls = {str(j["url"]).strip() for j in fresh_jobs}

        kept_prior: List[Dict[str, Any]] = []
        for pj in prior_jobs:
            url = str(pj.get("url") or "").strip()
            if not url or url in fresh_urls:
                continue
            row = self.repo.get_job_by_url(url)
            if row and row.get("status") in ("interested", "discarded", "applied", "skipped"):
                continue
            if row and row.get("rank_score") is not None and row["rank_score"] < LOW_SCORE_AUTO_DISCARD_THRESHOLD:
                continue
            kept_prior.append(pj)

        if not kept_prior:
            return

        merged = {**fresh_payload, "new": [*fresh_jobs, *kept_prior]}
        with self._out_file_lock:
            atomic_write_json(self.scanner.out, merged)

    def _is_fatal_non_retryable(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            isinstance(exc, painel_ia.ConsentRequired)
            or "consentimento" in msg
            or "preencha seu perfil" in msg
            or "nenhum provedor" in msg
        )

    def _run_mode_loop(
        self,
        *,
        mode: str,
        profile_key: str,
        region: str,
        continuous: bool,
        base_cooldown: int,
        execute_round: Callable[[int, List[str]], Optional[Tuple[int, int, int, int, int, bool]]],
    ) -> None:
        session_tried: List[str] = []
        round_num = 0
        consecutive_empty = 0
        consecutive_rate_limits = 0
        consecutive_fatal_errors = 0

        try:
            while not self._should_stop():
                round_num += 1
                self._clear_cooldown_fields()
                with self._lock:
                    self.state["round"] = round_num
                    self.state["phase"] = "picking_keywords"
                    self.state["round_jobs_found"] = 0
                    self.state["round_eligible_count"] = 0
                    self.state["round_screened"] = 0
                    self.state["round_promoted"] = 0
                    self.state["round_discarded"] = 0
                    self.state["round_errors"] = 0
                    self.state["counts"]["pending"] = 0
                    if mode == "recruiters":
                        self._recruiter_current_title = ""

                rate_limited = False
                round_found = 0
                round_eligible = 0
                round_promoted = 0
                round_discarded = 0
                round_errors = 0
                keywords: List[str] = []

                try:
                    keywords, rationale, source = self._pick_keywords_for_round(
                        profile_key=profile_key,
                        region=region,
                        mode=mode,
                        session_tried=session_tried,
                    )
                    with self._lock:
                        self.state["keywords"] = keywords
                        self.state["rationale"] = rationale
                        self.state["keyword_source"] = source
                        if self._should_stop():
                            self._finish_state("cancelled")
                            return
                        self.state["phase"] = "searching"

                    outcome = execute_round(round_num, keywords)
                    if outcome is None or self._should_stop():
                        self._finish_state("cancelled")
                        return

                    (
                        round_found,
                        round_eligible,
                        round_promoted,
                        round_discarded,
                        round_errors,
                        rate_limited,
                    ) = outcome

                    consecutive_fatal_errors = 0
                    consecutive_empty = 0 if round_eligible > 0 else (consecutive_empty + 1)
                    consecutive_rate_limits = (consecutive_rate_limits + 1) if rate_limited else 0

                    self._record_round_summary({
                        "round": round_num,
                        "keywords": list(keywords),
                        "found": round_found,
                        "eligible": round_eligible,
                        "promoted": round_promoted,
                        "discarded": round_discarded,
                        "errors": round_errors,
                        "rate_limited": rate_limited,
                        "finished_at": _now_iso(),
                    })

                    if not continuous:
                        self._finish_state("done")
                        return

                except Exception as exc:
                    if not continuous or self._is_fatal_non_retryable(exc):
                        self._finish_state("error", error=str(exc))
                        return
                    logger.warning("AutoMode %s round %d failed (retrying): %s", mode, round_num, exc)
                    consecutive_fatal_errors += 1
                    consecutive_rate_limits += 1
                    rate_limited = True
                    with self._lock:
                        err_found = round_found or int(self.state.get("round_jobs_found") or 0)
                        err_elig = round_eligible or int(self.state.get("round_eligible_count") or 0)
                        err_prom = round_promoted or int(self.state.get("round_promoted") or 0)
                        err_disc = round_discarded or int(self.state.get("round_discarded") or 0)
                        err_errs = (round_errors or int(self.state.get("round_errors") or 0)) + 1
                    self._record_round_summary({
                        "round": round_num,
                        "keywords": list(keywords),
                        "found": err_found,
                        "eligible": err_elig,
                        "promoted": err_prom,
                        "discarded": err_disc,
                        "errors": err_errs,
                        "error": str(exc),
                        "finished_at": _now_iso(),
                    })
                    if consecutive_fatal_errors >= MAX_CONSECUTIVE_FATAL_ERRORS:
                        self._finish_state(
                            "error",
                            error=f"Interrompido após {MAX_CONSECUTIVE_FATAL_ERRORS} erros consecutivos: {exc}",
                        )
                        return

                wait_s, reason = self._compute_cooldown(
                    mode=mode,
                    base_cooldown=base_cooldown,
                    round_had_items=(round_eligible > 0),
                    rate_limited=rate_limited,
                    consecutive_empty=consecutive_empty,
                    consecutive_rate_limits=consecutive_rate_limits,
                )
                wait_outcome = self._wait_cooldown(wait_s, reason=reason)
                if wait_outcome == "cancelled":
                    self._finish_state("cancelled")
                    return

            self._finish_state("cancelled")
        except Exception as exc:
            logger.exception("AutoMode %s loop crashed", mode)
            self._finish_state("error", error=str(exc))

    def _run(self, run_id: str, cfg: Dict[str, Any]) -> None:
        session_evaluated_urls: Set[str] = set()

        def _execute_jobs_round(
            round_num: int, keywords: List[str]
        ) -> Optional[Tuple[int, int, int, int, int, bool]]:
            prior_jobs = [
                j for j in (self._read_raw_scanner_payload().get("new") or [])
                if isinstance(j, dict) and j.get("url")
            ]

            started_scan = self.scanner.start(
                priorities=[],
                jobage=cfg["jobage"],
                focus="all",
                portals=cfg.get("portals"),
                region=cfg["region"],
                all_priorities=True,
                query=", ".join(keywords),
            )
            if not started_scan:
                raise RuntimeError("Não foi possível iniciar a busca nos portais.")

            while self.scanner.running:
                if self._should_stop():
                    self.scanner.cancel()
                time.sleep(0.25)

            if self._should_stop():
                return None
            if self.scanner.error:
                raise RuntimeError(self.scanner.error)

            fresh_payload = self._read_raw_scanner_payload()
            portals_map = (
                fresh_payload.get("portals")
                or (fresh_payload.get("meta") or {}).get("portals")
                or self.scanner.progress.get("portals")
            )
            rate_limited = _detect_rate_limit_in_portals(portals_map)
            self._merge_scanner_results(prior_jobs, fresh_payload)

            results = self.scanner.load_results()
            raw_new = results.get("new", []) if isinstance(results, dict) else []
            round_found = len(fresh_payload.get("new") or []) if round_num > 1 else len(raw_new)

            eligible = []
            for j in raw_new:
                if not isinstance(j, dict):
                    continue
                u = str(j.get("url") or "")
                if not u.startswith("http") or u in session_evaluated_urls:
                    continue
                if not _within_jobage(j.get("date") or j.get("posted_date"), cfg["jobage"], cfg["hide_undated"]):
                    continue
                if round_num > 1:
                    db_row = self.repo.get_job_by_url(u)
                    if db_row and db_row.get("rank_score") is not None:
                        continue
                eligible.append(j)

            urls = list(dict.fromkeys(j["url"] for j in eligible))
            round_eligible = len(urls)
            round_promoted = 0
            round_discarded = 0
            round_errors = 0

            with self._lock:
                self.state["round_jobs_found"] = round_found
                self.state["round_eligible_count"] = round_eligible
                if not urls:
                    self._session_totals["found"] += round_found
                    self.state["counts"] = dict(self._session_totals)

            if urls:
                with self._lock:
                    self.state["phase"] = "screening"

                session_evaluated_urls.update(urls)
                self.evaluator.start_batch(
                    urls=urls,
                    workers=2,
                    auto_interest_min=cfg["min_score"],
                    run_id=run_id,
                    should_stop=self._should_stop,
                    blocking=True,
                    extra_jobs={j["url"]: j for j in eligible if j.get("url")},
                )

                batch = self.evaluator.batch_status()
                _, round_promoted, round_discarded, round_errors = self._sync_batch_counts(
                    batch, len(urls), found_in_round=round_found
                )

            return round_found, round_eligible, round_promoted, round_discarded, round_errors, rate_limited

        self._run_mode_loop(
            mode="jobs",
            profile_key=PROFILE_KEY_HISTORY,
            region=cfg["region"],
            continuous=bool(cfg.get("continuous", True)),
            base_cooldown=int(cfg.get("cooldown_seconds") or JOBS_COOLDOWN_DEFAULT),
            execute_round=_execute_jobs_round,
        )

    def start_recruiters(
        self,
        min_score: Optional[int] = None,
        continuous: Optional[bool] = None,
        cooldown_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Start autonomous AI triage + promotion for Recrutadores -> Me Interessam."""
        self.validate_ready()

        saved_cfg = self.save_recruiter_config({
            k: v for k, v in {
                "min_score": min_score,
                "continuous": continuous,
                "cooldown_seconds": cooldown_seconds,
            }.items() if v is not None
        })

        with self._lock:
            self._ensure_idle_locked()

            run_id = uuid.uuid4().hex[:12]
            self._cancel_event.clear()
            self._skip_cooldown_event.clear()
            self._wake_event.clear()
            self._recruiter_current_title = ""
            self._session_totals = self._empty_counts()
            self._session_promoted_items = []
            self.state = {
                **self._empty_state(),
                "running": True,
                "mode": "recruiters",
                "phase": "picking_keywords",
                "run_id": run_id,
                "continuous": bool(saved_cfg["continuous"]),
                "cooldown_seconds": int(saved_cfg["cooldown_seconds"]),
                "round": 1,
                "min_score": saved_cfg["min_score"],
                "started_at": _now_iso(),
            }

        threading.Thread(
            target=self._run_recruiters,
            args=(run_id, saved_cfg),
            daemon=True,
        ).start()
        return {"ok": True, "mode": "recruiters", "run_id": run_id, "config": saved_cfg}

    def _screen_one_recruiter(
        self,
        post: Dict[str, Any],
        run_id: str,
        min_score: int,
    ) -> None:
        if self._should_stop():
            return

        title = str(post.get("title") or "Publicação")
        company = str(post.get("company") or "")
        disp = f"{title} ({company})" if company else title
        with self._lock:
            self._recruiter_current_title = disp[:80]

        try:
            res = painel_ia.triar_post_recrutador(post)
            cls = res["classification"]
            score = int(res["score"])
            verdict = res["verdict"]
            summary = res["summary"]
            best_email = res["best_email"]
            ai_model = res.get("ai_model")

            promoted_jid = None
            with self._db_lock:
                if cls == "banco_talentos":
                    auto_dismiss = post.get("portal") != "linkedin_post"
                    self.repo.update_recruiter_post_ai(
                        post["id"], cls, score, verdict, summary, best_email, auto_dismissed=auto_dismiss, ai_model=ai_model
                    )
                elif cls == "nao_e_vaga":
                    self.repo.update_recruiter_post_ai(
                        post["id"], cls, score, verdict, summary, best_email, auto_dismissed=False, ai_model=ai_model
                    )
                else:
                    self.repo.update_recruiter_post_ai(
                        post["id"], cls, score, verdict, summary, best_email, auto_dismissed=False, ai_model=ai_model
                    )
                    if score >= min_score:
                        promoted_jid = self.recruiter_service.promote_post_to_interested(
                            post,
                            run_id,
                            score,
                            verdict,
                            summary,
                            best_email,
                            ai_model=ai_model,
                            subscores=res.get("subscores"),
                            strengths=res.get("strengths"),
                            gaps=res.get("gaps"),
                            location_verdict=res.get("location_verdict"),
                            language_gate=res.get("language_gate"),
                            language_note=res.get("language_note"),
                            guard_alert=res.get("guard_alert"),
                        )

            with self._lock:
                counts = self.state["counts"]
                counts["screened"] += 1
                self.state["round_screened"] += 1
                counts["pending"] = max(0, self.state["round_eligible_count"] - self.state["round_screened"])
                if cls == "banco_talentos":
                    counts["talent_pools_discarded"] += 1
                    counts["discarded"] += 1
                    self.state["round_discarded"] += 1
                elif cls == "nao_e_vaga":
                    counts["not_a_job"] += 1
                elif promoted_jid:
                    counts["promoted"] += 1
                    self.state["round_promoted"] += 1
                    self.state["promoted_items"].append({
                        "url": post.get("url") or f"recruiter://post/{post['id']}",
                        "job_id": promoted_jid,
                        "title": title,
                        "company": company,
                        "score": score,
                        "best_email": best_email,
                    })
                else:
                    counts["kept_low_score"] += 1
        except Exception as exc:
            logger.warning("Failed to screen recruiter post %s: %s", post.get("id"), exc)
            with self._lock:
                counts = self.state["counts"]
                counts["screened"] += 1
                counts["errors"] += 1
                self.state["round_screened"] += 1
                self.state["round_errors"] += 1
                counts["pending"] = max(0, self.state["round_eligible_count"] - self.state["round_screened"])

    def _run_recruiters(self, run_id: str, cfg: Dict[str, Any]) -> None:
        def _execute_recruiters_round(
            _round_num: int, keywords: List[str]
        ) -> Optional[Tuple[int, int, int, int, int, bool]]:
            linkedin_only = getattr(self.recruiter_service, "linkedin_worker", None) is not None
            try:
                sync_res = self.recruiter_service.sync_all(
                    query=", ".join(keywords),
                    days=1,
                    linkedin_only=linkedin_only,
                    should_stop=self._should_stop,
                )
            except TypeError:
                try:
                    sync_res = self.recruiter_service.sync_all(
                        query=", ".join(keywords),
                        days=1,
                        should_stop=self._should_stop,
                    )
                except TypeError:
                    try:
                        sync_res = self.recruiter_service.sync_all(
                            query=", ".join(keywords),
                            should_stop=self._should_stop,
                        )
                    except TypeError:
                        sync_res = self.recruiter_service.sync_all(query=", ".join(keywords))
            if self._should_stop():
                return None

            collected_urls = set(sync_res.get("collected_urls") or sync_res.get("hn_urls") or [])
            collected_post_ids = {
                int(pid) for pid in (sync_res.get("collected_post_ids") or []) if pid is not None
            }
            rate_limited = bool(sync_res.get("rate_limited")) or int(sync_res.get("errors") or 0) > 0
            with self._lock:
                queued_post_ids = set(self._queued_recruiter_post_ids)
                self._queued_recruiter_post_ids.clear()

            with self._db_lock:
                candidates = self.recruiter_service.find_untriaged_candidates(
                    keywords=keywords,
                    include_urls=collected_urls,
                    include_post_ids=collected_post_ids | queued_post_ids,
                )
            if linkedin_only:
                candidates = [p for p in candidates if p.get("portal") == "linkedin_post"]

            if self._should_stop():
                return None

            external_synced = (
                int(sync_res.get("hn_synced", 0))
                + int(sync_res.get("github_synced", 0))
                + int(sync_res.get("remotive_synced", 0))
                + int(sync_res.get("scrapes_synced", 0))
                + int(sync_res.get("portal_synced", 0))
                + int(sync_res.get("linkedin_synced", 0))
            )
            round_found = int(sync_res.get("posts_with_email", 0)) + external_synced
            round_eligible = len(candidates)

            with self._lock:
                self.state["round_jobs_found"] = round_found
                self.state["round_eligible_count"] = round_eligible
                self.state["counts"]["found"] += round_found
                self.state["counts"]["to_screen"] += round_eligible
                self.state["counts"]["pending"] = round_eligible

            if candidates:
                with self._lock:
                    self.state["phase"] = "screening"

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(self._screen_one_recruiter, post, run_id, cfg["min_score"])
                        for post in candidates
                    ]
                    for fut in futures:
                        fut.result()

            with self._lock:
                r_promoted = int(self.state["round_promoted"])
                r_discarded = int(self.state["round_discarded"])
                r_errors = int(self.state["round_errors"])

            return round_found, round_eligible, r_promoted, r_discarded, r_errors, rate_limited

        self._run_mode_loop(
            mode="recruiters",
            profile_key=PROFILE_KEY_RECRUITER_HISTORY,
            region="all",
            continuous=bool(cfg.get("continuous", True)),
            base_cooldown=int(cfg.get("cooldown_seconds") or RECRUITER_COOLDOWN_DEFAULT),
            execute_round=_execute_recruiters_round,
        )

    def status(self) -> Dict[str, Any]:
        with self._lock:
            snap = {
                **self.state,
                "keywords": list(self.state.get("keywords") or []),
                "counts": dict(self.state.get("counts") or {}),
                "promoted_items": list(self.state.get("promoted_items") or []),
                "round_history": list(self.state.get("round_history") or []),
                "recruiter_current_title": self._recruiter_current_title,
            }
            base_totals = dict(self._session_totals)
            base_items = list(self._session_promoted_items)

        mode = snap.get("mode") or "jobs"
        rec_title = snap.pop("recruiter_current_title", "")
        if snap.get("phase") == "cooldown" and snap.get("next_run_at"):
            try:
                next_dt = datetime.fromisoformat(str(snap["next_run_at"]))
                rem = (next_dt - datetime.now(timezone.utc)).total_seconds()
                snap["cooldown_remaining_s"] = max(0, math.ceil(rem))
            except (ValueError, TypeError) as exc:
                logger.debug("Invalid next_run_at timestamp %r: %s", snap.get("next_run_at"), exc)

        snap["search_progress"] = (
            self.scanner.status().get("progress")
            if (mode == "jobs" and snap["phase"] == "searching")
            else None
        )
        if snap["phase"] == "screening" and mode == "jobs":
            batch = self.evaluator.batch_status()
            snap["batch_progress"] = {
                "current": batch.get("current", 0),
                "total": batch.get("total", 0),
                "percent": batch.get("percent", 0.0),
                "current_title": batch.get("current_title", ""),
                "errors": batch.get("errors", 0),
                "auto_interested": batch.get("auto_interested", 0),
                "provider": batch.get("provider", ""),
            }
            r_screened = int(batch.get("current") or 0)
            r_promoted = int(batch.get("auto_interested") or 0)
            r_errors = int(batch.get("errors") or 0)
            r_eligible = int(snap.get("round_eligible_count") or 0)
            results_map = batch.get("results") or {}
            r_discarded = sum(1 for r in results_map.values() if isinstance(r, dict) and r.get("discarded"))
            r_found = int(snap.get("round_jobs_found") or 0)

            snap["round_screened"] = r_screened
            snap["round_promoted"] = r_promoted
            snap["round_discarded"] = r_discarded
            snap["round_errors"] = r_errors
            snap["counts"].update({
                "found": base_totals["found"] + r_found,
                "to_screen": base_totals["to_screen"] + r_eligible,
                "screened": base_totals["screened"] + r_screened,
                "promoted": base_totals["promoted"] + r_promoted,
                "discarded": base_totals["discarded"] + r_discarded,
                "pending": max(0, r_eligible - r_promoted - r_discarded),
                "errors": base_totals["errors"] + r_errors,
            })
            snap["promoted_items"] = [*base_items, *(batch.get("promoted_items") or [])]
        elif snap["phase"] == "screening" and mode == "recruiters":
            cur = int(snap.get("round_screened") or 0)
            tot = int(snap.get("round_eligible_count") or 0)
            snap["batch_progress"] = {
                "current": cur,
                "total": tot,
                "percent": round((cur / max(1, tot)) * 100, 1),
                "current_title": rec_title,
                "errors": int(snap.get("round_errors") or 0),
                "auto_interested": int(snap.get("round_promoted") or 0),
                "provider": "",
            }
        else:
            snap["batch_progress"] = None

        return snap

    # ------------------------------------------------------------------
    # Undo (full run or single auto-promoted job)
    # ------------------------------------------------------------------

    def _restore_to_pending_json(self, job_row: Dict[str, Any]) -> None:
        """Ensure an undone job is visible again in Buscar Vagas results if out file exists."""
        try:
            url = job_row.get("url")
            if not url:
                return
            out = self.scanner.out
            with self._out_file_lock:
                data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"meta": None, "new": []}
                new_list = data.get("new")
                if not isinstance(new_list, list):
                    new_list = []
                if not any(isinstance(x, dict) and x.get("url") == url for x in new_list):
                    item = {
                        "id": job_row.get("id"),
                        "title": job_row.get("title"),
                        "company": job_row.get("company"),
                        "url": url,
                        "location": job_row.get("location"),
                        "portal": job_row.get("portal"),
                        "workplace_type": job_row.get("work_model"),
                        "contract": job_row.get("contract_type"),
                        "seniority": job_row.get("seniority"),
                        "date": job_row.get("posted_date") or job_row.get("first_seen"),
                        "posted_date": job_row.get("posted_date"),
                        "description": job_row.get("description") or "",
                    }
                    if job_row.get("rank_score") is not None:
                        item["screening"] = {
                            "score": job_row.get("rank_score"),
                            "verdict": job_row.get("rank_verdict") or "Avaliada",
                        }
                    new_list.insert(0, item)
                    data["new"] = new_list
                    atomic_write_json(out, data)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to restore undone job to %s: %s", self.scanner.out, exc)

    def _revert_job(self, job: Dict[str, Any], source: str, note: str) -> bool:
        if not job or job.get("status") != "interested":
            return False
        jid = job["id"]
        now = _now_iso()
        with self.repo.conn:
            self.repo.conn.execute(
                "UPDATE jobs SET status = 'new', fit = NULL, updated_at = ? WHERE id = ?",
                (now, jid),
            )
            self.repo.conn.execute(
                """
                INSERT INTO status_log (job_id, from_status, to_status, source, note, created_at)
                VALUES (?, 'interested', 'new', ?, ?, ?)
                """,
                (jid, source, note, now),
            )
        self.repo.clear_recruiter_post_promotion(job_id=jid)
        if job.get("url"):
            painel.unmark_interested(job["url"])
        if job.get("source") != "recruiter_radar":
            self._restore_to_pending_json(job)
        return True

    def undo_run(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if self.state["running"]:
                raise RuntimeError("Pare o Modo Automático antes de desfazer a rodada.")
            target_id = run_id or self.state.get("run_id")

        if not target_id:
            return {"ok": False, "reverted": 0, "error": "Nenhuma rodada identificada para desfazer."}

        cur = self.repo.conn.execute(
            """
            SELECT DISTINCT job_id
            FROM status_log
            WHERE to_status = 'interested'
              AND source IN ('auto_triage', 'auto_triage_recruiter')
              AND note LIKE ?
            """,
            (f"%[auto:{target_id}]%",),
        )
        job_ids = [r["job_id"] for r in cur.fetchall()]

        reverted = 0
        for jid in job_ids:
            job = self.repo.get_job(jid)
            if self._revert_job(job, "auto_undo", f"[auto:{target_id}] Desfeito em lote pelo usuário"):
                reverted += 1

        self.repo.clear_recruiter_post_promotion(run_id=target_id)
        with self._lock:
            if self.state.get("run_id") == target_id:
                self.state["undone"] = True
        return {"ok": True, "run_id": target_id, "reverted": reverted}

    def undo_job(self, url: Optional[str] = None, job_id: Optional[str] = None) -> Dict[str, Any]:
        job = self.repo.get_job(job_id) if job_id else (self.repo.get_job_by_url(url) if url else None)
        if not job:
            return {"ok": False, "reverted": 0, "error": "Vaga não encontrada."}

        ok = self._revert_job(job, "auto_undo", "Desfeito individualmente a partir de Me Interessam")
        if ok and job.get("url"):
            with self._lock:
                items = [x for x in (self.state.get("promoted_items") or []) if x.get("url") != job["url"]]
                self.state["promoted_items"] = items
        return {"ok": ok, "reverted": 1 if ok else 0, "url": job.get("url"), "job_id": job.get("id")}
