"""Dependency injection providers for FastAPI."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, TypeVar

from backend.core.ai_mux import AIMux
from backend.core.auto_mode import AutoModeService
from backend.core.docgen import DocGenService
from backend.core.evaluator import EvaluatorService
from backend.core.liveness import LivenessService
from backend.core.profile import ProfileService
from backend.core.recruiter_service import RecruiterService
from backend.core.scanner import ScannerService
from backend.core.tracker import TrackerService
from backend.db.repository import Repository

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class _ServiceRegistry:
    """Thread-safe lazy singleton container for FastAPI service dependencies."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._instances: dict[str, Any] = {}

    def get(self, key: str, factory: Callable[[], _T]) -> _T:
        inst = self._instances.get(key)
        if inst is None:
            with self._lock:
                inst = self._instances.get(key)
                if inst is None:
                    inst = factory()
                    self._instances[key] = inst
        return inst

    def shutdown(self) -> None:
        with self._lock:
            auto_mode = self._instances.get("auto_mode")
            if auto_mode is not None:
                try:
                    auto_mode.cancel()
                except Exception as exc:
                    logger.warning("Failed to cancel AutoModeService on shutdown: %s", exc)
            repo = self._instances.get("repo")
            if repo is not None:
                try:
                    repo.close()
                except Exception as exc:
                    logger.warning("Failed to close Repository on shutdown: %s", exc)
            self._instances.clear()


_registry = _ServiceRegistry()


def get_repository() -> Repository:
    return _registry.get("repo", Repository)


def get_tracker() -> TrackerService:
    return _registry.get("tracker", lambda: TrackerService(repo=get_repository()))


def get_scanner() -> ScannerService:
    return _registry.get("scanner", lambda: ScannerService(repo=get_repository()))


def get_evaluator() -> EvaluatorService:
    return _registry.get("evaluator", lambda: EvaluatorService(repo=get_repository()))


def get_docgen() -> DocGenService:
    return _registry.get("docgen", lambda: DocGenService(repo=get_repository()))


def get_profile() -> ProfileService:
    return _registry.get("profile", ProfileService)


def get_ai_mux() -> AIMux:
    return _registry.get("ai_mux", AIMux)


def get_liveness() -> LivenessService:
    return _registry.get("liveness", lambda: LivenessService(repo=get_repository()))


def get_recruiter_service() -> RecruiterService:
    return _registry.get(
        "recruiter",
        lambda: RecruiterService(
            repo=get_repository(),
            cache_dir=RecruiterService.default_cache_dir(),
        ),
    )


def get_auto_mode() -> AutoModeService:
    return _registry.get(
        "auto_mode",
        lambda: AutoModeService(
            repo=get_repository(),
            scanner=get_scanner(),
            evaluator=get_evaluator(),
            recruiter_service=get_recruiter_service(),
        ),
    )


def shutdown_services() -> None:
    """Stop active background services and reset singletons so closed connections are never reused."""
    _registry.shutdown()
