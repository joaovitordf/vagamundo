"""Application tracker endpoints."""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.deps import get_profile, get_tracker
from backend.api.models import (
    ApplicationEventCreateRequest,
    ApplicationRemoveRequest,
    ApplicationSaveRequest,
    AppliedRequest,
    ReopenRecruiterRequest,
    SingleUrlRequest,
)
from backend.api.security import verify_csrf_token
from backend.core.profile import ProfileService
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
            painel_apps = painel.applications()
            painel_by_source = {p.get("source") or p.get("url"): p for p in painel_apps if p.get("source") or p.get("url")}
            existing_urls = set()
            for a in raw_apps:
                u = a.get("job_url") or a.get("url") or a.get("source")
                if u:
                    existing_urls.add(u)
                if u and u in painel_by_source:
                    p = painel_by_source[u]
                    for k in ("cv_file", "cover_letter_file", "channel", "notes", "date", "role", "sector"):
                        if p.get(k) and not a.get(k):
                            a[k] = p[k]
            # Include tracker.csv entries not in SQLite
            for p in painel_apps:
                u = p.get("source") or p.get("url")
                if u and u not in existing_urls:
                    raw_apps.append({
                        "job_company": p.get("company"),
                        "job_title": p.get("role"),
                        "job_url": u,
                        "job_portal": p.get("channel") or "portal",
                        "applied_date": p.get("date"),
                        "status": p.get("status") or "applied",
                        "notes": p.get("notes"),
                        "cv_file": p.get("cv_file"),
                        "cover_letter_file": p.get("cover_letter_file"),
                    })
                    existing_urls.add(u)
        except Exception:
            pass

    job_ids = [a.get("job_id") for a in raw_apps if a.get("job_id")]
    job_urls = [
        (a.get("job_url") or a.get("url") or a.get("source"))
        for a in raw_apps
        if (a.get("job_url") or a.get("url") or a.get("source"))
    ]
    try:
        recruiter_ctx_map = tracker.repo.get_recruiter_context_for_jobs(job_ids, job_urls)
    except Exception:
        recruiter_ctx_map = {}

    normalized = []
    for a in raw_apps:
        company = a.get("job_company") or a.get("company") or ""
        role = a.get("job_title") or a.get("role") or a.get("title") or ""
        url = a.get("job_url") or a.get("url") or a.get("source") or ""
        date_val = a.get("applied_date") or a.get("date") or ""
        channel_val = a.get("job_portal") or a.get("channel") or a.get("portal") or "portal"
        jid = a.get("job_id")
        ctx = recruiter_ctx_map.get(f"id:{jid}") or recruiter_ctx_map.get(f"url:{url}") or {}
        rec_emails = ctx.get("emails") or []
        contacted_email = (a.get("contacted_email") or ctx.get("contacted_email") or "").strip() or None
        contacted_at = a.get("contacted_at") or ctx.get("contacted_at")
        recruiter_post_id = a.get("recruiter_post_id") or ctx.get("post_id")
        is_direct = bool(
            contacted_email
            or a.get("contact_channel") == "recruiter_email"
            or str(url).startswith("recruiter://")
        )
        contact_channel = "recruiter_email" if is_direct else (a.get("contact_channel") or "portal")
        if is_direct and not contacted_email and rec_emails:
            contacted_email = rec_emails[0]
        job_description = a.get("job_description") or ctx.get("description") or ""

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
        pdf_entrevista = pdfs.get("pdf_entrevista")

        job_posted_date = a.get("job_posted_date") or a.get("posted_date") or a.get("job_date") or ""
        applied_date_clean = date_val or (a.get("created_at") or "")[:10]

        normalized.append({
            **a,
            "company": company,
            "job_company": company,
            "role": role,
            "title": role,
            "job_title": role,
            "date": applied_date_clean,
            "applied_date": applied_date_clean,
            "job_posted_date": job_posted_date,
            "created_at": a.get("created_at") or applied_date_clean,
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
            "pdf_entrevista": pdf_entrevista,
            "recruiter_emails": rec_emails,
            "recruiter_post_id": recruiter_post_id,
            "contacted_email": contacted_email,
            "contacted_at": contacted_at,
            "contact_channel": contact_channel,
            "job_description": job_description,
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
        tracker.record_application_ledger(
            company=req.company or (job.get("company") if job else "") or "Empresa",
            role=req.title or req.role or (job.get("title") if job else "") or "Cargo",
            portal=req.portal or (job.get("portal") if job else "") or "portal",
            job_url=req.url or "",
            job_id=job_id,
            applied_date=req.applied_date or req.date or painel.date.today().isoformat(),
        )

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
    if not job:
        # Upsert the job into SQLite first so it definitely exists
        job_id = tracker.upsert_job({
            "title": req.role or "Vaga sem título",
            "company": req.company or "Empresa não informada",
            "url": req.url,
            "portal": req.portal or "portal",
            "status": "applied",
        })
        job = tracker.repo.get_job(job_id)
    else:
        # If job existed but company/title was missing, update them
        updates = {}
        if req.company and not job.get("company"):
            updates["company"] = req.company
        if req.role and not job.get("title"):
            updates["title"] = req.role
        if req.portal and not job.get("portal"):
            updates["portal"] = req.portal
        if updates:
            updates["id"] = job["id"]
            updates["url"] = job.get("url") or req.url
            tracker.upsert_job(updates)

    if job:
        ctx_map = tracker.repo.get_recruiter_context_for_jobs([job["id"]], [req.url])
        ctx = ctx_map.get(f"id:{job['id']}") or ctx_map.get(f"url:{req.url}") or {}
        rec_emails = ctx.get("emails") or []
        recruiter_post_id = ctx.get("post_id")
        contacted_email = (req.contacted_email or "").strip().lower() or None
        is_direct = bool(
            req.contact_channel == "recruiter_email"
            or contacted_email
            or str(req.url).startswith("recruiter://")
        )
        contact_channel = "recruiter_email" if is_direct else (req.contact_channel or "portal")
        if is_direct and not contacted_email and rec_emails:
            contacted_email = rec_emails[0].strip().lower()

        notes_val = f"E-mail direto: {contacted_email}" if contacted_email else "Registrado pelo painel"
        tracker.mark_jobs([job["id"]], decision="applied", source="painel")
        tracker.record_application({
            "job_id": job["id"],
            "status": "applied",
            "applied_date": painel.date.today().isoformat(),
            "notes": notes_val,
            "contact_channel": contact_channel,
            "contacted_email": contacted_email,
            "recruiter_post_id": recruiter_post_id,
        })
        if recruiter_post_id and contacted_email and is_direct:
            tracker.repo.mark_recruiter_post_contacted(
                post_id=recruiter_post_id,
                job_id=job["id"],
                contacted_email=contacted_email,
                contacted_at=painel.date.today().isoformat(),
            )

    # Record in immutable ledger to preserve historical data even if removed from active list
    company_name = req.company or (job.get("company") if job else "") or ""
    role_title = req.role or (job.get("title") if job else "") or ""
    portal_name = req.portal or (job.get("portal") if job else "") or ""
    tracker.record_application_ledger(
        company=company_name or "Empresa",
        role=role_title or "Cargo",
        portal=portal_name or "portal",
        job_url=req.url,
        job_id=job["id"] if job else None,
        applied_date=painel.date.today().isoformat(),
    )

    res = painel.record_applied(
        url=req.url,
        company=company_name,
        role=role_title,
        portal=portal_name,
    )
    return res


@router.post("/applications/remove")
async def remove_application(
    req: ApplicationRemoveRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Remove application record from SQLite and tracker.csv while preserving ledger history."""
    target_job_id = req.job_id
    url_to_clean = (req.url or "").strip()

    if req.id:
        app_row = tracker.repo.get_application(req.id)
        if app_row:
            target_job_id = target_job_id or app_row.get("job_id")
        tracker.repo.delete_application(app_id=req.id)

    if not target_job_id and url_to_clean:
        job = tracker.repo.get_job_by_url(url_to_clean)
        if job:
            target_job_id = job["id"]

    if target_job_id:
        if not url_to_clean:
            job = tracker.repo.get_job(target_job_id)
            if job:
                url_to_clean = job.get("url") or ""
        tracker.repo.delete_application(job_id=target_job_id)
        tracker.mark_jobs([target_job_id], decision="discarded", source="painel")

    # Mark as archived in ledger (preserves date and historical count)
    tracker.archive_application_ledger(
        job_id=target_job_id,
        job_url=url_to_clean,
        app_id=req.id,
    )

    if url_to_clean:
        painel.remove_application(url_to_clean)

    return {"ok": True, "removed": True, "url": url_to_clean}


@router.post("/applications/reopen-recruiter")
async def reopen_recruiter_application(
    req: ReopenRecruiterRequest,
    tracker: TrackerService = Depends(get_tracker),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Undo a direct recruiter outreach application and restore the post to Recrutadores."""
    reopened = tracker.repo.reopen_recruiter_post_from_application(
        app_id=req.id,
        job_id=req.job_id,
        job_url=req.url,
        recruiter_post_id=req.recruiter_post_id,
    )
    if not reopened:
        raise HTTPException(
            status_code=404,
            detail="Candidatura de recrutador não encontrada para reabrir.",
        )

    url_to_clean = reopened.get("url") or (req.url or "").strip()
    if url_to_clean:
        try:
            painel.remove_application(url_to_clean)
        except Exception:
            pass

    return {"ok": True, "reopened": True, **reopened}


@router.get("/applications/{app_id}/events")
async def list_application_events(
    app_id: int,
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """List timeline events (stages, feedbacks, questions) for an application."""
    events = tracker.list_application_events(application_id=app_id)
    return {"events": events, "total": len(events)}


@router.post("/applications/event")
async def add_application_event(
    req: ApplicationEventCreateRequest,
    tracker: TrackerService = Depends(get_tracker),
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Record an interview stage event with feedback and Q&A."""
    app_id = req.application_id
    if not app_id:
        if req.job_id:
            apps = tracker.list_applications()
            for a in apps:
                if a.get("job_id") == req.job_id:
                    app_id = a.get("id")
                    break
        elif req.url:
            job = tracker.repo.get_job_by_url(req.url)
            if job:
                apps = tracker.list_applications()
                for a in apps:
                    if a.get("job_id") == job["id"]:
                        app_id = a.get("id")
                        break

    if not app_id:
        raise HTTPException(status_code=404, detail="Candidatura não encontrada para registrar evento.")

    event_id = tracker.insert_application_event({
        "application_id": app_id,
        "stage": req.stage,
        "event_date": req.event_date or painel.date.today().isoformat(),
        "feedback": req.feedback or "",
        "questions_and_answers": req.questions_and_answers or "",
    })

    if req.status and req.status in painel.APPLICATION_STATUSES:
        app_row = tracker.get_application(app_id)
        tracker.record_application({
            "id": app_id,
            "status": req.status,
        })
        if app_row and app_row.get("job_id"):
            tracker.mark_jobs([app_row["job_id"]], decision=req.status, source="painel")

    # Update evolution ledger in background
    try:
        profile_svc.update_evolution()
    except Exception:
        pass

    return {"ok": True, "event_id": event_id}


@router.delete("/applications/event/{event_id}")
async def delete_application_event(
    event_id: int,
    tracker: TrackerService = Depends(get_tracker),
    profile_svc: ProfileService = Depends(get_profile),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Delete an interview stage event."""
    deleted = tracker.delete_application_event(event_id=event_id)
    try:
        profile_svc.update_evolution()
    except Exception:
        pass
    return {"ok": True, "deleted": deleted > 0}
