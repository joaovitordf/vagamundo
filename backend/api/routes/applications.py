"""Application tracker endpoints."""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_tracker
from backend.api.models import ApplicationSaveRequest, AppliedRequest, SingleUrlRequest
from backend.api.security import verify_csrf_token
from backend.core.tracker import TrackerService
from backend.tools import painel

router = APIRouter(tags=["Applications"])


@router.get("/applications")
async def list_applications(
    status: Optional[str] = Query(None),
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """List applications with complete metadata, materials, and aliases."""
    raw_apps = []
    try:
        raw_apps = tracker.list_applications(status=status)
    except Exception:
        raw_apps = []

    if not raw_apps:
        try:
            raw_apps = painel.applications()
        except Exception:
            raw_apps = []
    else:
        # Merge with painel.applications() to get any tracker.csv metadata
        try:
            painel_by_source = {p.get("source") or p.get("url"): p for p in painel.applications() if p.get("source") or p.get("url")}
            for a in raw_apps:
                u = a.get("job_url") or a.get("url") or a.get("source")
                if u and u in painel_by_source:
                    p = painel_by_source[u]
                    for k in ("cv_file", "cover_letter_file", "channel", "notes", "date", "role", "sector"):
                        if p.get(k) and not a.get(k):
                            a[k] = p[k]
        except Exception:
            pass

    normalized = []
    for a in raw_apps:
        company = a.get("job_company") or a.get("company") or ""
        role = a.get("job_title") or a.get("role") or a.get("title") or ""
        url = a.get("job_url") or a.get("url") or a.get("source") or ""
        date_val = a.get("applied_date") or a.get("date") or ""
        channel_val = a.get("job_portal") or a.get("channel") or a.get("portal") or "portal"

        # Resolve PDF materials
        pdfs = {}
        if company or role:
            try:
                pdfs = painel.job_pdfs(company, role)
            except Exception:
                pdfs = {}

        cv_file = a.get("cv_file") or a.get("cv_path") or pdfs.get("pdf_cv") or ""
        if cv_file and cv_file.endswith(".tex"):
            pdf_cand = cv_file[:-4] + ".pdf"
            if (painel.ROOT / pdf_cand).exists():
                cv_file = pdf_cand
            elif pdfs.get("pdf_cv"):
                cv_file = pdfs["pdf_cv"]

        cover_file = a.get("cover_letter_file") or a.get("cover_letter_path") or pdfs.get("pdf_carta") or ""
        if cover_file and cover_file.endswith(".tex"):
            pdf_cand = cover_file[:-4] + ".pdf"
            if (painel.ROOT / pdf_cand).exists():
                cover_file = pdf_cand
            elif pdfs.get("pdf_carta"):
                cover_file = pdfs["pdf_carta"]

        pdf_cv = pdfs.get("pdf_cv") or (cv_file if cv_file.endswith(".pdf") else None)
        pdf_carta = pdfs.get("pdf_carta") or (cover_file if cover_file.endswith(".pdf") else None)

        normalized.append({
            **a,
            "company": company,
            "job_company": company,
            "role": role,
            "title": role,
            "job_title": role,
            "date": date_val,
            "applied_date": date_val,
            "channel": channel_val,
            "portal": channel_val,
            "job_portal": channel_val,
            "url": url,
            "source": url,
            "job_url": url,
            "cv_file": cv_file,
            "cv_path": cv_file,
            "cover_letter_file": cover_file,
            "cover_letter_path": cover_file,
            "pdf_cv": pdf_cv,
            "pdf_carta": pdf_carta,
        })

    return {"applications": normalized, "total": len(normalized)}


@router.post("/applications")
async def save_application(
    req: ApplicationSaveRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Create or update an application record."""
    # 1. Update in SQLite
    job_id = req.job_id
    if not job_id and req.url:
        job = tracker.repo.get_job_by_url(req.url)
        if job:
            job_id = job["id"]
        elif req.title and req.company:
            job_id = tracker.upsert_job({
                "title": req.title or req.role,
                "company": req.company,
                "url": req.url,
                "portal": req.portal,
            })

    if job_id:
        tracker.record_application({
            "job_id": job_id,
            "status": req.status,
            "cv_path": req.cv_file,
            "cover_letter_path": req.cover_letter_file,
            "applied_date": req.applied_date or req.date,
            "notes": req.notes,
        })
        tracker.mark_jobs([job_id], decision="applied", source="painel")

    # 2. Update legacy evolution and tracker.csv
    try:
        payload = req.model_dump(exclude_none=True)
        record = painel.save_application_record(payload)
        return {"ok": True, "record": record}
    except Exception as exc:
        return {"ok": True, "error": str(exc)}


@router.post("/applied")
async def mark_applied(
    req: AppliedRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Mark a job as applied from Me Interessam / Cards."""
    job = tracker.repo.get_job_by_url(req.url)
    if job:
        tracker.mark_jobs([job["id"]], decision="applied", source="painel")
        tracker.record_application({
            "job_id": job["id"],
            "status": "applied",
            "applied_date": painel.date.today().isoformat(),
            "notes": "Registrado pelo painel",
        })
    res = painel.record_applied(
        url=req.url,
        company=req.company or (job.get("company") if job else "") or "",
        role=req.role or (job.get("title") if job else "") or "",
        portal=req.portal or (job.get("portal") if job else "") or "",
    )
    return res


@router.post("/applications/remove")
async def remove_application(
    req: SingleUrlRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Remove application record."""
    job = tracker.repo.get_job_by_url(req.url)
    if job:
        tracker.mark_jobs([job["id"]], decision="discarded", source="painel")
    res = painel.remove_application(req.url)
    return res
