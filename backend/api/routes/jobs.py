"""Job management, decision marking, and evaluation endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import get_evaluator, get_liveness, get_scanner, get_tracker
from backend.api.models import BatchScreenRequest, MarkRequest, SingleUrlRequest
from backend.api.security import verify_csrf_token
from backend.core.evaluator import EvaluatorService
from backend.core.liveness import LivenessService
from backend.core.scanner import ScannerService
from backend.core.tracker import TrackerService

router = APIRouter(tags=["Jobs"])

# Compatibilidade retroativa para testes unitários que importam _build_screening da rota.
_build_screening = TrackerService.build_screening


@router.get("/results")
def get_search_results(
    scanner: ScannerService = Depends(get_scanner),
) -> Dict[str, Any]:
    """Get the current scan results, omitting already marked jobs."""
    return scanner.load_results()


@router.get("/saved")
def get_saved_jobs(
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """Get jobs marked as 'Me interessam', enriched with AI evaluation scores and documents."""
    rows = tracker.list_enriched_saved_jobs()
    return {"saved": rows, "total": len(rows)}


@router.get("/discarded")
def get_discarded_jobs(
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """Get discarded jobs enriched with AI evaluation score and merged with painel."""
    return {"discarded": tracker.list_enriched_discarded_jobs()}


@router.get("/jobs")
def list_jobs(
    status: Optional[str] = Query(None),
    fit: Optional[str] = Query(None),
    portal: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """RESTful job listing with filters and pagination."""
    jobs = tracker.list_jobs(status=status, fit=fit, portal=portal, q=q, limit=limit, offset=offset)
    total = tracker.count_jobs(status=status, fit=fit, portal=portal, q=q)
    return {"jobs": jobs, "total": total, "limit": limit, "offset": offset}


@router.get("/jobs/{job_id}")
def get_job_detail(
    job_id: str,
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """Fetch a single job with its evaluation."""
    job = tracker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vaga não encontrada.")
    evaluation = tracker.get_evaluation(job_id)
    return {"job": job, "evaluation": evaluation}


@router.post("/mark")
def mark_jobs(
    req: MarkRequest,
    tracker: TrackerService = Depends(get_tracker),
    scanner: ScannerService = Depends(get_scanner),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Mark decision on jobs ('interesse' or 'descartar')."""
    marked = tracker.mark_decision(
        urls=req.urls or [],
        decision=req.decision,
        ids=req.ids,
        job_data=req.job_data,
        scanner_results=scanner.load_results(),
    )
    return {"ok": True, "marked": marked}


@router.post("/discard")
def discard_single_job(
    req: SingleUrlRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Move a job to discarded."""
    tracker.discard_by_url(req.url)
    return {"discarded": True, "url": req.url}


@router.post("/saved/batch-discard")
def batch_discard_saved_jobs(
    req: BatchScreenRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Move selected saved jobs to discarded sequentially without file race conditions."""
    urls = [u for u in dict.fromkeys(req.urls or []) if isinstance(u, str) and u.strip()]
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhuma vaga selecionada para descartar.",
        )
    count = sum(1 for u in urls if tracker.discard_by_url(u))
    return {"ok": True, "discarded": count, "total": len(urls)}


@router.post("/saved/batch-reevaluate")
def batch_reevaluate_saved_jobs(
    req: BatchScreenRequest,
    evaluator: EvaluatorService = Depends(get_evaluator),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Start background AI re-evaluation of selected saved jobs without altering status."""
    urls = [
        u
        for u in dict.fromkeys(req.urls or [])
        if isinstance(u, str) and u.startswith(("http://", "https://", "recruiter://"))
    ]
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhuma vaga válida selecionada para reavaliar.",
        )
    if evaluator.reeval_status().get("running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma reavaliação em lote em andamento. Aguarde a conclusão.",
        )
    started = evaluator.start_reevaluate_batch(urls)
    return {"ok": started, "started": started, "total": len(urls)}


@router.get("/saved/batch-status")
def saved_batch_reevaluate_status(
    evaluator: EvaluatorService = Depends(get_evaluator),
) -> Dict[str, Any]:
    """Get progress status of the Me Interessam batch AI re-evaluation."""
    return evaluator.reeval_status()


@router.post("/restore")
def restore_single_job(
    req: SingleUrlRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Restore a discarded job back to interested."""
    tracker.restore_by_url(req.url)
    return {"restored": True, "url": req.url}


@router.post("/batch-screen")
def batch_screen_jobs(
    req: BatchScreenRequest,
    evaluator: EvaluatorService = Depends(get_evaluator),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Batch screen jobs with AI evaluation."""
    started = evaluator.start_batch(req.urls)
    return {"ok": started, "started": started, "total": len(req.urls)}


@router.post("/jobs/liveness")
async def check_liveness(
    req: MarkRequest,
    liveness_svc: LivenessService = Depends(get_liveness),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Verify if URLs are alive or closed."""
    urls = req.urls or []
    results = await liveness_svc.check(urls)
    return {"results": results, "total": len(results)}


@router.post("/discarded/clear")
def clear_discarded_jobs(
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Permanently clear discarded jobs from SQLite and seen_jobs.json."""
    stats = tracker.clear_discarded_with_legacy()
    return {"ok": True, **stats}
