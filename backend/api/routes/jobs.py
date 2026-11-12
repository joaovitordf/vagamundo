"""Job management, decision marking, and evaluation endpoints."""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.deps import get_evaluator, get_liveness, get_scanner, get_tracker
from backend.api.models import BatchScreenRequest, MarkRequest, SingleUrlRequest
from backend.api.security import verify_csrf_token
from backend.core.evaluator import EvaluatorService
from backend.core.liveness import LivenessService
from backend.core.scanner import ScannerService
from backend.core.tracker import TrackerService
from backend.tools import painel

router = APIRouter(tags=["Jobs"])


@router.get("/results")
async def get_search_results(
    scanner: ScannerService = Depends(get_scanner),
) -> Dict[str, Any]:
    """Get the current scan results, omitting already marked jobs."""
    return scanner.load_results()


@router.get("/saved")
async def get_saved_jobs(
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """Get jobs marked as 'Me interessam', enriched with AI evaluation scores and documents."""
    try:
        raw_saved = tracker.list_jobs(status="interested", limit=500)
    except Exception:
        raw_saved = []

    if not raw_saved:
        try:
            raw_saved = painel.saved()
        except Exception:
            raw_saved = []
    else:
        try:
            existing_urls = {j.get("url") for j in raw_saved if j.get("url")}
            for ps in painel.saved():
                if ps.get("url") and ps["url"] not in existing_urls:
                    raw_saved.append(ps)
        except Exception:
            pass

    # Pre-fetch saved_at timestamps, auto-promotion provenance and linked recruiter direct emails
    job_ids = [s.get("id") for s in raw_saved if s.get("id")]
    job_urls = [s.get("url") for s in raw_saved if s.get("url")]
    saved_at_map = {}
    auto_meta_map = {}
    recruiter_email_map = {}
    if job_ids:
        try:
            placeholders = ",".join("?" for _ in job_ids)
            cur = tracker.repo.conn.execute(
                f"""
                SELECT job_id, created_at, source, note
                FROM status_log
                WHERE to_status = 'interested' AND job_id IN ({placeholders})
                ORDER BY id ASC
                """,
                job_ids,
            )
            for r in cur.fetchall():
                saved_at_map[r["job_id"]] = r["created_at"]
                src = r["source"] or ""
                note = r["note"] or ""
                is_auto = src in ("auto_triage", "auto_triage_recruiter")
                m_run = re.search(r"\[auto:([A-Za-z0-9_-]+)\]", note)
                auto_meta_map[r["job_id"]] = {
                    "auto_promoted": is_auto,
                    "auto_origin": "recruiter" if src == "auto_triage_recruiter" else ("jobs" if src == "auto_triage" else None),
                    "auto_run_id": m_run.group(1) if (is_auto and m_run) else None,
                }
        except Exception:
            pass

    try:
        recruiter_email_map = tracker.repo.get_recruiter_emails_for_jobs(job_ids, job_urls)
    except Exception:
        recruiter_email_map = {}

    rows = []
    for s in raw_saved:
        u = s.get("url")
        jid = s.get("id")
        auto_meta = auto_meta_map.get(jid, {})
        rec_emails = recruiter_email_map.get(f"id:{jid}") or recruiter_email_map.get(f"url:{u}") or []
        date_val = s.get("date") or s.get("posted_date") or s.get("first_seen")
        saved_at_val = (
            saved_at_map.get(jid)
            or s.get("saved_at")
            or s.get("updated_at")
            or s.get("created_at")
            or s.get("first_seen")
            or date_val
        )
        saved_at_str = str(saved_at_val) if saved_at_val else date_val
        saved_date = saved_at_str[:10] if len(saved_at_str) >= 10 else saved_at_str

        if u:
            try:
                answers = painel.claude_answers(u)
            except Exception:
                answers = {}
            try:
                pdfs = painel.job_pdfs(s.get("company") or "", s.get("title") or "")
            except Exception:
                pdfs = {}
            try:
                cached_score = painel.get_cached_score(u)
            except Exception:
                cached_score = None

            screening = cached_score or s.get("screening")
            if not screening and (s.get("rank_score") is not None or s.get("rank_verdict")):
                screening = {
                    "score": s.get("rank_score"),
                    "verdict": s.get("rank_verdict"),
                }

            workplace_type = s.get("workplace_type") or s.get("work_model")
            contract_val = s.get("contract") or s.get("contract_type")

            rows.append({
                **s,
                "workplace_type": workplace_type,
                "work_model": workplace_type,
                "date": date_val,
                "posted_date": date_val,
                "saved_at": saved_date,
                "saved_at_full": saved_at_str,
                "contract": contract_val,
                "contract_type": contract_val,
                "claude": answers,
                **pdfs,
                "screening": screening,
                "auto_promoted": bool(auto_meta.get("auto_promoted", False)),
                "auto_origin": auto_meta.get("auto_origin"),
                "auto_run_id": auto_meta.get("auto_run_id"),
                "recruiter_emails": rec_emails,
            })
        else:
            rows.append({
                **s,
                "date": date_val,
                "posted_date": date_val,
                "saved_at": saved_date,
                "saved_at_full": saved_at_str,
                "auto_promoted": bool(auto_meta.get("auto_promoted", False)),
                "auto_origin": auto_meta.get("auto_origin"),
                "auto_run_id": auto_meta.get("auto_run_id"),
                "recruiter_emails": rec_emails,
            })

    def sort_key(r):
        sc = r.get("screening")
        score = -1
        if isinstance(sc, dict) and sc.get("score") is not None:
            score = sc.get("score")
        return (score, r.get("first_seen") or r.get("date") or "")

    rows.sort(key=sort_key, reverse=True)
    return {"saved": rows, "total": len(rows)}


@router.get("/discarded")
async def get_discarded_jobs(
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """Get discarded jobs enriched with AI evaluation score and merged with painel."""
    try:
        raw_discarded = tracker.list_jobs(status="discarded", limit=500)
    except Exception:
        raw_discarded = []

    if not raw_discarded:
        try:
            raw_discarded = painel.discarded()
        except Exception:
            raw_discarded = []
    else:
        try:
            existing_urls = {j.get("url") for j in raw_discarded if j.get("url")}
            for pd in painel.discarded():
                if pd.get("url") and pd["url"] not in existing_urls:
                    raw_discarded.append(pd)
        except Exception:
            pass

    rows = []
    for d in raw_discarded:
        u = d.get("url")
        cached_score = None
        if u:
            try:
                cached_score = painel.get_cached_score(u)
            except Exception:
                cached_score = None

        screening = cached_score or d.get("screening")
        if not screening and (d.get("rank_score") is not None or d.get("rank_verdict")):
            screening = {
                "score": d.get("rank_score"),
                "verdict": d.get("rank_verdict"),
            }

        workplace_type = d.get("workplace_type") or d.get("work_model")
        date_val = d.get("date") or d.get("posted_date") or d.get("first_seen")
        contract_val = d.get("contract") or d.get("contract_type")

        rows.append({
            **d,
            "workplace_type": workplace_type,
            "work_model": workplace_type,
            "date": date_val,
            "posted_date": date_val,
            "contract": contract_val,
            "contract_type": contract_val,
            "screening": screening,
        })

    rows.sort(key=lambda r: r.get("first_seen") or "", reverse=True)
    return {"discarded": rows}


@router.get("/jobs")
async def list_jobs(
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
async def get_job_detail(
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
async def mark_jobs(
    req: MarkRequest,
    tracker: TrackerService = Depends(get_tracker),
    scanner: ScannerService = Depends(get_scanner),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Mark decision on jobs ('interesse' or 'descartar')."""
    urls = req.urls or []
    decision = req.decision

    if req.job_data:
        status = "interested" if decision in ("interesse", "interested") else ("discarded" if decision in ("descartar", "discarded") else decision)
        fit = "medium" if decision in ("interesse", "interested") else ("low" if decision in ("descartar", "discarded") else None)
        job_dict = {
            **req.job_data,
            "status": status,
            "fit": fit,
        }
        tracker.upsert_job(job_dict)

    ids_to_mark = list(req.ids or [])
    for u in urls:
        j = tracker.repo.get_job_by_url(u)
        if j:
            ids_to_mark.append(j["id"])

    tracker.mark_jobs(ids_to_mark, decision=decision, source="painel")

    try:
        results = scanner.load_results()
        painel.mark(results, urls, decision, job_data=req.job_data)
    except Exception:
        pass

    return {"ok": True, "marked": len(urls) or len(ids_to_mark)}


@router.post("/discard")
async def discard_single_job(
    req: SingleUrlRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Move a job to discarded."""
    job = tracker.repo.get_job_by_url(req.url)
    if job:
        tracker.mark_jobs([job["id"]], decision="discarded", source="painel")
    painel.discard_job(req.url)
    return {"discarded": True, "url": req.url}


@router.post("/restore")
async def restore_single_job(
    req: SingleUrlRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Restore a discarded job back to interested."""
    job = tracker.repo.get_job_by_url(req.url)
    if job:
        tracker.mark_jobs([job["id"]], decision="interested", source="painel")
    painel.restore_job(req.url)
    return {"restored": True, "url": req.url}


@router.post("/batch-screen")
async def batch_screen_jobs(
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
async def clear_discarded_jobs(
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Permanently clear discarded jobs from SQLite and seen_jobs.json."""
    import json
    with tracker.repo.conn:
        cur = tracker.repo.conn.execute("DELETE FROM jobs WHERE status = 'discarded' OR (status = 'skipped' AND fit = 'low')")
        deleted_count = cur.rowcount
        tracker.repo.conn.execute("DELETE FROM status_log WHERE to_status = 'discarded'")

    seen_path = painel.scrape_run.SEEN
    cleared_seen = 0
    if seen_path.exists():
        try:
            state = json.loads(seen_path.read_text(encoding="utf-8"))
            seen = state.get("seen", {})
            keys_to_remove = [
                k for k, v in seen.items()
                if isinstance(v, dict) and (v.get("status") in ("skipped", "discarded") or v.get("fit") == "low")
            ]
            for k in keys_to_remove:
                del seen[k]
                cleared_seen += 1
            seen_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return {"ok": True, "deleted_db": deleted_count, "cleared_seen": cleared_seen}
