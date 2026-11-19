"""Recruiter radar posts, deduplication, and outreach tracking repository mixin."""

from __future__ import annotations

import re
from typing import Any

from backend.core.constants import APPLIED_PIPELINE_STATUSES, EXCLUDED_RADAR_JOB_STATUSES
from backend.db.utils import deserialize, now_iso, serialize

_EXCLUDED_STATUS_SQL = ",".join(f"'{s}'" for s in EXCLUDED_RADAR_JOB_STATUSES)
_APPLIED_STATUS_SQL = ",".join(f"'{s}'" for s in APPLIED_PIPELINE_STATUSES)


class RecruitersRepositoryMixin:
    """SQLite operations for recruiter_posts, dedup lookup, promotion, and outreach state."""

    def upsert_recruiter_post(self, post: dict) -> int:
        """Insert or update a recruiter post identified with emails."""
        emails_json = serialize(post.get("emails", []))
        matched_kw_json = serialize(post.get("matched_keywords", []))
        now = now_iso()

        url = post.get("url")
        job_id = post.get("job_id")
        with self.conn:
            existing_row = None
            if url:
                cur = self.conn.execute("SELECT id FROM recruiter_posts WHERE url = ?", (url,))
                existing_row = cur.fetchone()
            if not existing_row and job_id:
                cur = self.conn.execute("SELECT id FROM recruiter_posts WHERE job_id = ?", (job_id,))
                existing_row = cur.fetchone()
            if existing_row:
                post_id = existing_row["id"]
                self.conn.execute(
                    """
                    UPDATE recruiter_posts
                    SET emails = ?, email_context = ?, title = ?, company = ?,
                        portal = ?, location = ?, work_model = ?, published_date = ?,
                        description = ?, matched_keywords = ?, match_score = ?,
                        job_id = COALESCE(?, job_id)
                    WHERE id = ?
                    """,
                    (
                        emails_json,
                        post.get("email_context"),
                        post.get("title", "Oportunidade"),
                        post.get("company", "Empresa"),
                        post.get("portal", "outros"),
                        post.get("location"),
                        post.get("work_model"),
                        post.get("published_date"),
                        post.get("description", ""),
                        matched_kw_json,
                        post.get("match_score", 0),
                        job_id,
                        post_id,
                    ),
                )
                return post_id

            cur = self.conn.execute(
                """
                INSERT INTO recruiter_posts (
                    emails, email_context, title, company, portal, url, location,
                    work_model, published_date, description, matched_keywords, match_score,
                    job_id, dismissed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    emails_json,
                    post.get("email_context"),
                    post.get("title", "Oportunidade"),
                    post.get("company", "Empresa"),
                    post.get("portal", "outros"),
                    url,
                    post.get("location"),
                    post.get("work_model"),
                    post.get("published_date"),
                    post.get("description", ""),
                    matched_kw_json,
                    post.get("match_score", 0),
                    post.get("job_id"),
                    now,
                ),
            )
            return cur.lastrowid

    def get_latest_recruiter_post_for_job(self, job_id: str | None, url: str) -> dict | None:
        """Fetch latest recruiter_post description/metadata matching a job_id or URL."""
        cur = self.conn.execute(
            """
            SELECT description, title, company, location, work_model
            FROM recruiter_posts
            WHERE (? IS NOT NULL AND job_id = ?) OR url = ?
            ORDER BY id DESC LIMIT 1
            """,
            (job_id, job_id, url),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _norm_dedup_text(value: str | None) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", (value or "").lower())).strip()

    def find_recruiter_post_for_dedup(
        self,
        *,
        url: str | None = None,
        linkedin_activity_id: str | None = None,
        primary_email: str | None = None,
        description: str = "",
        title: str | None = None,
    ) -> dict | None:
        """Find an existing recruiter_posts row by URL, LinkedIn activity ID, or email+vacancy signature."""
        base_select = """
            SELECT rp.*, j.status AS job_status
            FROM recruiter_posts rp
            LEFT JOIN jobs j ON rp.job_id = j.id
        """
        clean_url = (url or "").strip()
        if clean_url:
            cur = self.conn.execute(f"{base_select} WHERE rp.url = ? ORDER BY rp.id DESC LIMIT 1", (clean_url,))
            row = cur.fetchone()
            if row:
                return dict(row)

        if linkedin_activity_id and linkedin_activity_id.isdigit():
            cur = self.conn.execute(
                f"{base_select} WHERE rp.url LIKE ? ORDER BY rp.id DESC LIMIT 1",
                (f"%{linkedin_activity_id}%",),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        norm_email = (primary_email or "").strip().lower()
        norm_prefix = " ".join((description or "").split())[:160].lower()
        cand_desc = self._norm_dedup_text(description)
        cand_title = self._norm_dedup_text(title)
        generic_titles = {"", "oportunidade", "vaga"}
        meaningful_cand_title = cand_title if cand_title not in generic_titles else ""
        if not (norm_email and (norm_prefix or meaningful_cand_title)):
            return None

        cur = self.conn.execute(
            f"{base_select} WHERE LOWER(rp.emails) LIKE ? ORDER BY rp.id DESC LIMIT 50",
            (f"%{norm_email}%",),
        )
        for r in cur.fetchall():
            d = dict(r)
            row_emails = [
                str(e).strip().lower()
                for e in (deserialize(d.get("emails")) or [])
                if str(e).strip()
            ]
            if row_emails and norm_email not in row_emails:
                continue

            existing_prefix = " ".join((d.get("description") or "").split())[:160].lower()
            existing_desc = self._norm_dedup_text(d.get("description"))
            existing_title = self._norm_dedup_text(d.get("title"))
            meaningful_existing_title = existing_title if existing_title not in generic_titles else ""
            titles_conflict = bool(
                meaningful_cand_title
                and meaningful_existing_title
                and meaningful_cand_title not in meaningful_existing_title
                and meaningful_existing_title not in meaningful_cand_title
            )

            if norm_prefix and existing_prefix == norm_prefix and not titles_conflict:
                if (
                    not cand_desc
                    or not existing_desc
                    or cand_desc == existing_desc
                    or cand_desc.startswith(existing_desc)
                    or existing_desc.startswith(cand_desc)
                    or cand_desc[:240] == existing_desc[:240]
                ):
                    return d

            if cand_desc and existing_desc and not titles_conflict:
                if len(cand_desc) >= 40 and len(existing_desc) >= 40 and (
                    cand_desc == existing_desc
                    or cand_desc.startswith(existing_desc)
                    or existing_desc.startswith(cand_desc)
                ):
                    return d

            if (
                meaningful_cand_title
                and len(meaningful_cand_title) >= 12
                and meaningful_cand_title == meaningful_existing_title
            ):
                if (
                    not cand_desc
                    or not existing_desc
                    or cand_desc[:80] == existing_desc[:80]
                    or len(set(cand_desc.split()) & set(existing_desc.split())) >= 6
                ):
                    return d
        return None

    def list_recruiter_posts(
        self,
        query: str | None = None,
        only_cv: bool = False,
        portal: str | None = None,
        include_non_jobs: bool = True,
        only_untriaged: bool = False,
        include_without_email: bool = False,
    ) -> list[dict]:
        """List active recruiter posts with optional keyword, CV match, portal and AI filters."""
        sql = f"""
            SELECT rp.*, j.status AS job_status
            FROM recruiter_posts rp
            LEFT JOIN jobs j ON rp.job_id = j.id
            WHERE rp.dismissed = 0
              AND (rp.job_id IS NULL OR j.status IS NULL OR j.status NOT IN ({_EXCLUDED_STATUS_SQL}))
        """
        if not include_without_email:
            sql += " AND TRIM(COALESCE(rp.emails, '')) NOT IN ('', '[]', 'null')"
        params: list[Any] = []

        if only_cv:
            sql += """ AND (
                (rp.ai_evaluated_at IS NOT NULL AND rp.ai_classification = 'vaga_ativa' AND COALESCE(rp.ai_score, 0) >= 60)
                OR (rp.ai_evaluated_at IS NULL AND rp.ai_classification = 'vaga_ativa' AND COALESCE(rp.ai_score, 0) >= 60)
                OR (rp.ai_evaluated_at IS NULL AND rp.ai_classification IS NULL AND rp.match_score > 0)
            )"""

        if portal:
            sql += " AND rp.portal = ?"
            params.append(portal)

        if not include_non_jobs:
            sql += " AND COALESCE(rp.ai_classification, '') != 'nao_e_vaga'"

        if only_untriaged:
            sql += " AND rp.ai_evaluated_at IS NULL"

        if query and query.strip():
            terms = [t.strip() for t in query.split(",") if t.strip()]
            if terms:
                clauses = []
                for t in terms:
                    pattern = f"%{t}%"
                    clauses.append(
                        "(rp.title LIKE ? OR rp.company LIKE ? OR rp.description LIKE ? OR rp.emails LIKE ? OR rp.matched_keywords LIKE ?)"
                    )
                    params.extend([pattern, pattern, pattern, pattern, pattern])
                sql += " AND (" + " OR ".join(clauses) + ")"

        sql += """
            ORDER BY
                CASE WHEN rp.ai_classification = 'nao_e_vaga' THEN 1 ELSE 0 END ASC,
                COALESCE(rp.ai_score, rp.match_score) DESC,
                rp.published_date DESC,
                rp.id DESC
        """

        cur = self.conn.execute(sql, params)
        posts = []
        for r in cur.fetchall():
            d = dict(r)
            d["emails"] = deserialize(d.get("emails")) or []
            d["matched_keywords"] = deserialize(d.get("matched_keywords")) or []
            raw_details = deserialize(d.get("ai_details"))
            d["ai_details"] = raw_details if isinstance(raw_details, dict) else None
            posts.append(d)
        return posts

    def get_recruiter_post(self, post_id: int) -> dict | None:
        """Fetch a single recruiter post by ID."""
        cur = self.conn.execute(
            """
            SELECT rp.*, j.status AS job_status
            FROM recruiter_posts rp
            LEFT JOIN jobs j ON rp.job_id = j.id
            WHERE rp.id = ?
            """,
            (post_id,),
        )
        r = cur.fetchone()
        if not r:
            return None
        d = dict(r)
        d["emails"] = deserialize(d.get("emails")) or []
        d["matched_keywords"] = deserialize(d.get("matched_keywords")) or []
        raw_details = deserialize(d.get("ai_details"))
        d["ai_details"] = raw_details if isinstance(raw_details, dict) else None
        return d

    def get_recruiter_post_visibility(self, post_id: int) -> dict | None:
        """Fetch radar visibility flags and linked job status for a recruiter post."""
        cur = self.conn.execute(
            """
            SELECT rp.portal, rp.dismissed, rp.auto_promoted, j.status AS job_status
            FROM recruiter_posts rp
            LEFT JOIN jobs j ON rp.job_id = j.id
            WHERE rp.id = ?
            """,
            (post_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def link_recruiter_post_to_job(self, post_id: int, job_id: str) -> None:
        """Associate a recruiter post with a jobs row and keep it visible in radar tracking."""
        with self.conn:
            self.conn.execute(
                "UPDATE recruiter_posts SET job_id = ?, dismissed = 0 WHERE id = ?",
                (job_id, post_id),
            )

    def update_recruiter_post_ai(
        self,
        post_id: int,
        classification: str,
        score: int | None,
        verdict: str | None,
        summary: str | None,
        best_email: str | None = None,
        auto_dismissed: bool = False,
        evaluated_at: str | None = None,
        ai_model: str | None = None,
        ai_details: dict | None = None,
    ) -> bool:
        """Persist AI triage metadata for a recruiter post (and optionally auto-dismiss)."""
        ts = evaluated_at or now_iso()
        details_json = serialize(ai_details) if isinstance(ai_details, dict) and ai_details else None
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE recruiter_posts
                SET ai_classification = ?,
                    ai_score = ?,
                    ai_verdict = ?,
                    ai_summary = ?,
                    ai_best_email = ?,
                    ai_model = COALESCE(?, ai_model),
                    ai_details = COALESCE(?, ai_details),
                    ai_evaluated_at = ?,
                    dismissed = CASE WHEN ? THEN 1 ELSE dismissed END
                WHERE id = ?
                """,
                (
                    classification,
                    score,
                    verdict,
                    summary,
                    best_email or None,
                    ai_model or None,
                    details_json,
                    ts,
                    1 if auto_dismissed else 0,
                    post_id,
                ),
            )
        return cur.rowcount > 0

    def mark_recruiter_post_promoted(
        self,
        post_id: int,
        job_id: str,
        run_id: str | None = None,
    ) -> bool:
        """Link a recruiter post to its promoted job row and mark auto-promotion provenance."""
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE recruiter_posts
                SET job_id = ?,
                    auto_promoted = 1,
                    auto_run_id = ?,
                    dismissed = 0
                WHERE id = ?
                """,
                (job_id, run_id, post_id),
            )
        return cur.rowcount > 0

    def clear_recruiter_post_promotion(
        self,
        job_id: str | None = None,
        run_id: str | None = None,
    ) -> int:
        """Revert auto-promotion flag on recruiter_posts while preserving AI triage cache."""
        if not job_id and not run_id:
            return 0
        with self.conn:
            if job_id:
                cur = self.conn.execute(
                    "UPDATE recruiter_posts SET auto_promoted = 0, auto_run_id = NULL WHERE job_id = ?",
                    (job_id,),
                )
            else:
                cur = self.conn.execute(
                    "UPDATE recruiter_posts SET auto_promoted = 0, auto_run_id = NULL WHERE auto_run_id = ?",
                    (run_id,),
                )
        return cur.rowcount

    def get_recruiter_context_for_jobs(
        self,
        job_ids: list[str],
        urls: list[str] | None = None,
    ) -> dict[str, dict]:
        """Map job_id / url -> recruiter context (ordered emails, post_id, contacted_email, contacted_at, description)."""
        clean_ids = [jid for jid in job_ids if jid]
        clean_urls = [u for u in (urls or []) if u]
        if not clean_ids and not clean_urls:
            return {}

        clauses: list[str] = []
        params: list[Any] = []
        if clean_ids:
            ph = ",".join("?" for _ in clean_ids)
            clauses.append(f"job_id IN ({ph})")
            params.extend(clean_ids)
        if clean_urls:
            ph = ",".join("?" for _ in clean_urls)
            clauses.append(f"url IN ({ph})")
            params.extend(clean_urls)

        cur = self.conn.execute(
            f"""
            SELECT id, job_id, url, emails, ai_best_email, contacted_email, contacted_at, description
            FROM recruiter_posts
            WHERE {' OR '.join(clauses)}
            """,
            params,
        )
        mapping: dict[str, dict] = {}
        for r in cur.fetchall():
            emails = deserialize(r["emails"]) or []
            if not isinstance(emails, list):
                emails = []
            best = (r["ai_best_email"] or "").strip()
            ordered: list[str] = []
            if best:
                ordered.append(best)
            for em in emails:
                em_s = str(em).strip()
                if em_s and em_s not in ordered:
                    ordered.append(em_s)
            if not ordered and not r["contacted_email"]:
                continue
            ctx = {
                "post_id": r["id"],
                "emails": ordered,
                "contacted_email": (r["contacted_email"] or "").strip() or None,
                "contacted_at": r["contacted_at"],
                "description": r["description"] or "",
            }
            if r["job_id"]:
                mapping[f"id:{r['job_id']}"] = ctx
            if r["url"]:
                mapping[f"url:{r['url']}"] = ctx
        return mapping

    def get_recruiter_emails_for_jobs(
        self,
        job_ids: list[str],
        urls: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Map job_id / url -> ordered direct recruiter email list (best email first)."""
        contexts = self.get_recruiter_context_for_jobs(job_ids, urls)
        return {
            key: ctx["emails"]
            for key, ctx in contexts.items()
            if ctx.get("emails")
        }

    def get_contacted_recruiter_emails(self) -> dict[str, dict]:
        """Return active contacted recruiter emails keyed by lowercase address."""
        contacted: dict[str, dict] = {}

        def _store(email_val: str | None, info: dict) -> None:
            em = (email_val or "").strip().lower()
            if not em:
                return
            existing = contacted.get(em)
            if not existing or (info.get("contacted_at") or "") > (existing.get("contacted_at") or ""):
                contacted[em] = info

        cur = self.conn.execute(f"""
            SELECT rp.id as post_id, rp.contacted_email, rp.contacted_at,
                   COALESCE(NULLIF(rp.company, ''), j.company, '') as company,
                   COALESCE(NULLIF(rp.title, ''), j.title, '') as title,
                   rp.job_id,
                   a.id as application_id,
                   a.applied_date
            FROM recruiter_posts rp
            LEFT JOIN jobs j ON rp.job_id = j.id
            LEFT JOIN applications a ON a.job_id = rp.job_id
            WHERE rp.contacted_email IS NOT NULL AND TRIM(rp.contacted_email) != ''
              AND (a.id IS NOT NULL OR COALESCE(j.status, '') IN ({_APPLIED_STATUS_SQL}))
        """)
        for r in cur.fetchall():
            ts = r["contacted_at"] or r["applied_date"] or ""
            _store(
                r["contacted_email"],
                {
                    "email": (r["contacted_email"] or "").strip(),
                    "company": r["company"] or "",
                    "title": r["title"] or "",
                    "contacted_at": ts,
                    "job_id": r["job_id"],
                    "application_id": r["application_id"],
                },
            )

        cur2 = self.conn.execute("""
            SELECT a.id as application_id, a.contacted_email, a.applied_date, a.updated_at,
                   a.job_id, j.company, j.title
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.contacted_email IS NOT NULL AND TRIM(a.contacted_email) != ''
        """)
        for r in cur2.fetchall():
            ts = r["applied_date"] or (r["updated_at"] or "")[:10]
            _store(
                r["contacted_email"],
                {
                    "email": (r["contacted_email"] or "").strip(),
                    "company": r["company"] or "",
                    "title": r["title"] or "",
                    "contacted_at": ts,
                    "job_id": r["job_id"],
                    "application_id": r["application_id"],
                },
            )

        return contacted

    def mark_recruiter_post_contacted(
        self,
        post_id: int,
        job_id: str,
        contacted_email: str,
        contacted_at: str | None = None,
    ) -> bool:
        """Link a recruiter post to its applied job and record contacted email/timestamp."""
        ts = contacted_at or now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE recruiter_posts
                SET job_id = ?,
                    contacted_email = ?,
                    contacted_at = ?,
                    auto_promoted = 0,
                    dismissed = 0
                WHERE id = ?
                """,
                (job_id, contacted_email.strip().lower(), ts, post_id),
            )
        return cur.rowcount > 0

    def reopen_recruiter_post_from_application(
        self,
        app_id: int | None = None,
        job_id: str | None = None,
        job_url: str | None = None,
        recruiter_post_id: int | None = None,
    ) -> dict | None:
        """Delete application, archive ledger, reset job status to 'new' and restore recruiter post."""
        now = now_iso()
        target_job_id = job_id
        target_url = (job_url or "").strip()

        if app_id:
            app = self.get_application(app_id)
            if app:
                target_job_id = target_job_id or app.get("job_id")
                if not recruiter_post_id:
                    recruiter_post_id = app.get("recruiter_post_id")

        if not target_job_id and target_url:
            job = self.get_job_by_url(target_url)
            if job:
                target_job_id = job["id"]

        if target_job_id and not target_url:
            job = self.get_job(target_job_id)
            if job:
                target_url = job.get("url") or ""

        clauses: list[str] = []
        params: list[Any] = []
        if recruiter_post_id:
            clauses.append("id = ?")
            params.append(recruiter_post_id)
        if target_job_id:
            clauses.append("job_id = ?")
            params.append(target_job_id)
        if target_url:
            clauses.append("url = ?")
            params.append(target_url)

        matched_posts: list[dict] = []
        if clauses:
            cur = self.conn.execute(
                f"SELECT id, job_id, url FROM recruiter_posts WHERE {' OR '.join(clauses)}",
                params,
            )
            matched_posts = [dict(r) for r in cur.fetchall()]
            if matched_posts and not recruiter_post_id:
                recruiter_post_id = matched_posts[0]["id"]
            if matched_posts and not target_job_id:
                target_job_id = matched_posts[0].get("job_id")

        if not matched_posts and not recruiter_post_id and not target_url.startswith("recruiter://"):
            return None

        with self.conn:
            if app_id:
                self.conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            if target_job_id:
                self.conn.execute("DELETE FROM applications WHERE job_id = ?", (target_job_id,))

            if target_job_id or target_url:
                self.conn.execute(
                    """
                    UPDATE application_ledger
                    SET active_in_list = 0, archived_at = ?
                    WHERE (job_id IS NOT NULL AND job_id != '' AND job_id = ?)
                       OR (job_url IS NOT NULL AND job_url != '' AND job_url = ?)
                    """,
                    (now, target_job_id or "", target_url or ""),
                )

            if target_job_id:
                row = self.conn.execute(
                    "SELECT status FROM jobs WHERE id = ?", (target_job_id,)
                ).fetchone()
                old_status = row["status"] if row else None
                self.conn.execute(
                    "UPDATE jobs SET status = 'new', updated_at = ? WHERE id = ?",
                    (now, target_job_id),
                )
                self.conn.execute(
                    """
                    INSERT INTO status_log (job_id, from_status, to_status, source, note, created_at)
                    VALUES (?, ?, 'new', 'reopen_recruiter', 'Reaberto para Recrutadores', ?)
                    """,
                    (target_job_id, old_status, now),
                )

            if clauses:
                self.conn.execute(
                    f"""
                    UPDATE recruiter_posts
                    SET contacted_email = NULL,
                        contacted_at = NULL,
                        dismissed = 0,
                        auto_promoted = 0,
                        auto_run_id = NULL
                    WHERE {' OR '.join(clauses)}
                    """,
                    params,
                )

        return {
            "post_id": recruiter_post_id,
            "job_id": target_job_id,
            "url": target_url,
        }

    def dismiss_recruiter_post(self, post_id: int) -> bool:
        """Soft delete a recruiter post by setting dismissed = 1."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE recruiter_posts SET dismissed = 1 WHERE id = ?",
                (post_id,),
            )
        return cur.rowcount > 0

    def dismiss_recruiter_posts(self, post_ids: list[int]) -> list[int]:
        """Soft delete multiple recruiter posts by setting dismissed = 1 in safe chunks."""
        clean_ids: list[int] = []
        seen: set[int] = set()
        for raw_id in post_ids or []:
            try:
                pid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if pid > 0 and pid not in seen:
                seen.add(pid)
                clean_ids.append(pid)

        if not clean_ids:
            return []

        dismissed_ids: list[int] = []
        with self.conn:
            for idx in range(0, len(clean_ids), 500):
                chunk = clean_ids[idx:idx + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = self.conn.execute(
                    f"SELECT id FROM recruiter_posts WHERE id IN ({placeholders}) AND COALESCE(dismissed, 0) = 0",
                    chunk,
                ).fetchall()
                existing = {int(row["id"]) for row in rows}
                if not existing:
                    continue
                self.conn.execute(
                    f"UPDATE recruiter_posts SET dismissed = 1 WHERE id IN ({placeholders}) AND COALESCE(dismissed, 0) = 0",
                    chunk,
                )
                dismissed_ids.extend(pid for pid in chunk if pid in existing)
        return dismissed_ids

    def get_jobs_with_potential_emails(self) -> list[dict]:
        """Fetch active/pending jobs from DB whose description mentions an email symbol (@)."""
        cur = self.conn.execute(f"""
            SELECT id, title, company, portal, url, location, work_model, posted_date, description
            FROM jobs
            WHERE description IS NOT NULL
              AND description LIKE '%@%'
              AND COALESCE(url, '') NOT LIKE 'recruiter://%'
              AND COALESCE(status, 'new') NOT IN ({_EXCLUDED_STATUS_SQL})
        """)
        return [dict(r) for r in cur.fetchall()]

    def get_interested_status_metadata(
        self, job_ids: list[str]
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        """Fetch saved_at timestamps and auto-promotion provenance for interested jobs."""
        clean_ids = [jid for jid in job_ids if jid]
        if not clean_ids:
            return {}, {}
        placeholders = ",".join("?" for _ in clean_ids)
        cur = self.conn.execute(
            f"""
            SELECT job_id, created_at, source, note
            FROM status_log
            WHERE to_status = 'interested' AND job_id IN ({placeholders})
            ORDER BY id ASC
            """,
            clean_ids,
        )
        saved_at_map: dict[str, str] = {}
        auto_meta_map: dict[str, dict[str, Any]] = {}
        for r in cur.fetchall():
            jid = r["job_id"]
            saved_at_map[jid] = r["created_at"]
            src = r["source"] or ""
            note = r["note"] or ""
            is_auto = src in ("auto_triage", "auto_triage_recruiter")
            m_run = re.search(r"\[auto:([A-Za-z0-9_-]+)\]", note)
            auto_meta_map[jid] = {
                "auto_promoted": is_auto,
                "auto_origin": (
                    "recruiter"
                    if src == "auto_triage_recruiter"
                    else ("jobs" if src == "auto_triage" else None)
                ),
                "auto_run_id": m_run.group(1) if (is_auto and m_run) else None,
            }
        return saved_at_map, auto_meta_map

    def _delete_linked_recruiter_posts(
        self,
        job_ids: list[str],
        urls: list[str],
    ) -> int:
        """Delete recruiter_posts rows linked to permanently deleted discarded jobs."""
        clean_jids = [jid for jid in dict.fromkeys(job_ids) if jid]
        clean_urls = [u.strip() for u in dict.fromkeys(urls) if u and u.strip()]
        synthetic_ids: list[int] = []
        for u in clean_urls:
            if u.startswith("recruiter://post/"):
                tail = u.split("recruiter://post/", 1)[1].strip()
                if tail.isdigit():
                    synthetic_ids.append(int(tail))

        clauses: list[str] = []
        params: list[Any] = []
        for idx in range(0, len(clean_jids), 400):
            chunk = clean_jids[idx:idx + 400]
            ph = ",".join("?" for _ in chunk)
            clauses.append(f"job_id IN ({ph})")
            params.extend(chunk)
        for idx in range(0, len(clean_urls), 400):
            chunk = clean_urls[idx:idx + 400]
            ph = ",".join("?" for _ in chunk)
            clauses.append(f"url IN ({ph})")
            params.extend(chunk)
        for idx in range(0, len(synthetic_ids), 400):
            chunk = synthetic_ids[idx:idx + 400]
            ph = ",".join("?" for _ in chunk)
            clauses.append(f"id IN ({ph})")
            params.extend(chunk)

        if not clauses:
            return 0
        cur = self.conn.execute(
            f"DELETE FROM recruiter_posts WHERE {' OR '.join(clauses)}",
            params,
        )
        return cur.rowcount
