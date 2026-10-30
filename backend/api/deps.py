"""Dependency injection providers for FastAPI."""

from __future__ import annotations
from backend.db.repository import Repository
from backend.core.tracker import TrackerService
from backend.core.scanner import ScannerService
from backend.core.evaluator import EvaluatorService
from backend.core.docgen import DocGenService
from backend.core.profile import ProfileService
from backend.core.ai_mux import AIMux
from backend.core.liveness import LivenessService

_repo: Repository | None = None
_tracker: TrackerService | None = None
_scanner: ScannerService | None = None
_evaluator: EvaluatorService | None = None
_docgen: DocGenService | None = None
_profile: ProfileService | None = None
_ai_mux: AIMux | None = None
_liveness: LivenessService | None = None


def get_repository() -> Repository:
    global _repo
    if _repo is None:
        _repo = Repository()
    return _repo


def get_tracker() -> TrackerService:
    global _tracker
    if _tracker is None:
        _tracker = TrackerService(repo=get_repository())
    return _tracker


def get_scanner() -> ScannerService:
    global _scanner
    if _scanner is None:
        _scanner = ScannerService(repo=get_repository())
    return _scanner


def get_evaluator() -> EvaluatorService:
    global _evaluator
    if _evaluator is None:
        _evaluator = EvaluatorService(repo=get_repository())
    return _evaluator


def get_docgen() -> DocGenService:
    global _docgen
    if _docgen is None:
        _docgen = DocGenService(repo=get_repository())
    return _docgen


def get_profile() -> ProfileService:
    global _profile
    if _profile is None:
        _profile = ProfileService()
    return _profile


def get_ai_mux() -> AIMux:
    global _ai_mux
    if _ai_mux is None:
        _ai_mux = AIMux()
    return _ai_mux


def get_liveness() -> LivenessService:
    global _liveness
    if _liveness is None:
        _liveness = LivenessService(repo=get_repository())
    return _liveness
