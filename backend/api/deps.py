"""Dependency injection providers for FastAPI."""

from __future__ import annotations
import logging
import threading

from backend.db.repository import Repository
from backend.core.tracker import TrackerService
from backend.core.scanner import ScannerService
from backend.core.evaluator import EvaluatorService
from backend.core.docgen import DocGenService
from backend.core.profile import ProfileService
from backend.core.ai_mux import AIMux
from backend.core.liveness import LivenessService
from backend.core.constants import ROOT
from backend.core.recruiter_service import RecruiterService
from backend.core.linkedin_browser import LinkedInBrowserWorker
from backend.core.auto_mode import AutoModeService
from backend.tools import painel_ia

logger = logging.getLogger(__name__)
_lock = threading.RLock()

_repo: Repository | None = None
_tracker: TrackerService | None = None
_scanner: ScannerService | None = None
_evaluator: EvaluatorService | None = None
_docgen: DocGenService | None = None
_profile: ProfileService | None = None
_ai_mux: AIMux | None = None
_liveness: LivenessService | None = None
_linkedin_worker: LinkedInBrowserWorker | None = None
_recruiter: RecruiterService | None = None
_auto_mode: AutoModeService | None = None


def get_repository() -> Repository:
    global _repo
    if _repo is None:
        with _lock:
            if _repo is None:
                _repo = Repository()
    return _repo


def get_tracker() -> TrackerService:
    global _tracker
    if _tracker is None:
        with _lock:
            if _tracker is None:
                _tracker = TrackerService(repo=get_repository())
    return _tracker


def get_scanner() -> ScannerService:
    global _scanner
    if _scanner is None:
        with _lock:
            if _scanner is None:
                _scanner = ScannerService(repo=get_repository())
    return _scanner


def get_evaluator() -> EvaluatorService:
    global _evaluator
    if _evaluator is None:
        with _lock:
            if _evaluator is None:
                _evaluator = EvaluatorService(repo=get_repository())
    return _evaluator


def get_docgen() -> DocGenService:
    global _docgen
    if _docgen is None:
        with _lock:
            if _docgen is None:
                _docgen = DocGenService(repo=get_repository())
    return _docgen


def get_profile() -> ProfileService:
    global _profile
    if _profile is None:
        with _lock:
            if _profile is None:
                _profile = ProfileService()
    return _profile


def get_ai_mux() -> AIMux:
    global _ai_mux
    if _ai_mux is None:
        with _lock:
            if _ai_mux is None:
                _ai_mux = AIMux()
    return _ai_mux


def get_liveness() -> LivenessService:
    global _liveness
    if _liveness is None:
        with _lock:
            if _liveness is None:
                _liveness = LivenessService(repo=get_repository())
    return _liveness


def get_linkedin_worker() -> LinkedInBrowserWorker:
    global _linkedin_worker
    if _linkedin_worker is None:
        with _lock:
            if _linkedin_worker is None:
                _linkedin_worker = LinkedInBrowserWorker(
                    profile_dir=ROOT / "data" / "browser_profile",
                    state_dir=painel_ia.PAINEL_DIR,
                )
    return _linkedin_worker


def get_recruiter_service() -> RecruiterService:
    global _recruiter
    if _recruiter is None:
        with _lock:
            if _recruiter is None:
                _recruiter = RecruiterService(
                    repo=get_repository(),
                    cache_dir=painel_ia.PAINEL_DIR,
                    linkedin_worker=get_linkedin_worker(),
                )
    return _recruiter


def get_auto_mode() -> AutoModeService:
    global _auto_mode
    if _auto_mode is None:
        with _lock:
            if _auto_mode is None:
                _auto_mode = AutoModeService(
                    repo=get_repository(),
                    scanner=get_scanner(),
                    evaluator=get_evaluator(),
                    recruiter_service=get_recruiter_service(),
                )
    return _auto_mode


def shutdown_services() -> None:
    """Stop active background services and reset singletons so closed connections are never reused."""
    global _auto_mode, _repo, _tracker, _scanner, _evaluator, _docgen, _profile, _ai_mux, _liveness, _linkedin_worker, _recruiter
    with _lock:
        if _auto_mode is not None:
            try:
                _auto_mode.cancel()
            except Exception as exc:
                logger.warning("Failed to cancel AutoModeService on shutdown: %s", exc)
        if _linkedin_worker is not None:
            try:
                _linkedin_worker.shutdown()
            except Exception as exc:
                logger.warning("Failed to shutdown LinkedInBrowserWorker on shutdown: %s", exc)
        if _repo is not None:
            try:
                _repo.close()
            except Exception as exc:
                logger.warning("Failed to close Repository on shutdown: %s", exc)
        _auto_mode = None
        _recruiter = None
        _linkedin_worker = None
        _liveness = None
        _docgen = None
        _evaluator = None
        _scanner = None
        _tracker = None
        _profile = None
        _ai_mux = None
        _repo = None
