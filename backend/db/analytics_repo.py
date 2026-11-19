"""Scan runs, profile key-value settings, and dashboard analytics repository mixin."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.db.utils import now_iso, serialize

_PORTAL_LABELS: dict[str, str] = {
    "gupy-search": "Gupy",
    "linkedin-search": "LinkedIn",
    "remotar-search": "Remotar",
    "greenhouse-search": "Greenhouse",
    "vagas-search": "Vagas.com",
    "solides-search": "Sólides",
    "programathor-search": "Programathor",
    "infojobs-search": "InfoJobs",
    "geekhunter-search": "GeekHunter",
    "trampos-search": "Trampos",
    "michaelpage-search": "Michael Page",
    "roberthalf-search": "Robert Half",
    "pcd-search": "PCD Online",
    "digai-search": "DigAÍ",
    "empregos-search": "Empregos.com.br",
    "freehire-search": "FreeHire",
    "agrobase-search": "Agrobase",
    "agrosearch-search": "AGROSearch",
    "ashby-search": "Ashby",
    "jobicy-search": "Jobicy",
    "remoteok-search": "RemoteOK",
    "hh-search": "HeadHunter (RU)",
    "habrcareer-search": "Habr Career",
    "linkedin_post": "LinkedIn (Post)",
    "hn-search": "Hacker News",
    "github-vagas": "GitHub Vagas",
    "remotive": "Remotive",
    "recruiter_radar": "Recrutadores",
}

_MONTH_NAMES: dict[int, str] = {
    1: "jan.",
    2: "fev.",
    3: "mar.",
    4: "abr.",
    5: "mai.",
    6: "jun.",
    7: "jul.",
    8: "ago.",
    9: "set.",
    10: "out.",
    11: "nov.",
    12: "dez.",
}


class AnalyticsRepositoryMixin:
    """SQLite operations for scan_runs, profile preferences, and analytics aggregations."""

    SCAN_JSON_FIELDS = ("portals_summary", "health_report")

    def insert_scan_run(self, run: dict) -> int:
        """Record statistics of a scan run."""
        now = now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO scan_runs (
                    date, total_found, total_new, total_seen,
                    portals_summary, health_report, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.get("date", now[:10]),
                    run.get("total_found", 0),
                    run.get("total_new", 0),
                    run.get("total_seen", 0),
                    serialize(run.get("portals_summary")),
                    serialize(run.get("health_report")),
                    now,
                ),
            )
            return cur.lastrowid

    def get_profile(self, key: str) -> str | None:
        """Read a serialized profile or settings value by key."""
        cur = self.conn.execute("SELECT value FROM profile WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_profile(self, key: str, value: str) -> None:
        """Persist a profile or settings value by key."""
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO profile (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def _query_dashboard_kpis(self) -> dict[str, Any]:
        saved_jobs = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'interested'").fetchone()[0]
        active_applications = self.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        lifetime_applications = self.conn.execute("SELECT COUNT(*) FROM application_ledger").fetchone()[0]
        active_processes = self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status IN ('applied', 'screening', 'interview', 'offer')"
        ).fetchone()[0]
        interviews = self.conn.execute("""
            SELECT COUNT(DISTINCT a.id) FROM applications a
            LEFT JOIN application_events ae ON a.id = ae.application_id
            WHERE a.status = 'interview'
               OR ae.stage LIKE '%entrevista%'
               OR ae.stage LIKE '%interview%'
               OR ae.stage LIKE '%coding%'
        """).fetchone()[0]
        offers = self.conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('offer', 'hired')").fetchone()[0]
        rejected = self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status IN ('rejected', 'no_response', 'offer_declined', 'withdrawn')"
        ).fetchone()[0]
        discarded_jobs = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'discarded'").fetchone()[0]
        conversion_rate = (
            f"{round((interviews / lifetime_applications) * 100, 1)}%"
            if lifetime_applications > 0
            else "0.0%"
        )
        return {
            "saved_jobs": saved_jobs,
            "active_applications": active_applications,
            "lifetime_applications": lifetime_applications,
            "active_processes": active_processes,
            "interviews": interviews,
            "offers": offers,
            "rejected": rejected,
            "discarded_jobs": discarded_jobs,
            "conversion_rate": conversion_rate,
        }

    def _query_dashboard_timelines(self, period_months: int) -> tuple[list[dict], list[dict]]:
        today = date.today()
        months_list: list[tuple[str, str]] = []
        year, month = today.year, today.month
        current_ym = f"{year:04d}-{month:02d}"
        for _ in range(period_months):
            key = f"{year:04d}-{month:02d}"
            label = f"{_MONTH_NAMES[month]}/{str(year)[2:]}"
            months_list.append((key, label))
            month -= 1
            if month == 0:
                month = 12
                year -= 1

        cur = self.conn.execute("""
            SELECT substr(applied_date, 1, 7) as ym,
                   COUNT(*) as total,
                   SUM(active_in_list) as active,
                   SUM(CASE WHEN active_in_list = 0 THEN 1 ELSE 0 END) as archived
            FROM application_ledger
            GROUP BY ym
        """)
        monthly_map = {row["ym"]: dict(row) for row in cur.fetchall()}
        monthly_timeline = [
            {
                "month_key": key,
                "label": label,
                "count": monthly_map.get(key, {}).get("total", 0),
                "active": monthly_map.get(key, {}).get("active", 0) or 0,
                "archived": monthly_map.get(key, {}).get("archived", 0) or 0,
                "is_current": key == current_ym,
            }
            for key, label in months_list
        ]

        start_date = today - timedelta(days=29)
        daily_list: list[str] = []
        cur_day = today
        while cur_day >= start_date:
            daily_list.append(cur_day.isoformat())
            cur_day -= timedelta(days=1)

        cur = self.conn.execute(
            """
            SELECT applied_date, COUNT(*) as total
            FROM application_ledger
            WHERE applied_date >= ?
            GROUP BY applied_date
            """,
            (start_date.isoformat(),),
        )
        daily_map = {row["applied_date"]: row["total"] for row in cur.fetchall()}
        today_str = today.isoformat()
        yesterday_str = (today - timedelta(days=1)).isoformat()
        daily_timeline = [
            {
                "date": d_str,
                "label": f"{d_str.split('-')[2]}/{d_str.split('-')[1]}",
                "count": daily_map.get(d_str, 0),
                "is_today": d_str == today_str,
                "is_yesterday": d_str == yesterday_str,
            }
            for d_str in daily_list
        ]
        return monthly_timeline, daily_timeline

    def _query_dashboard_distributions(self, saved_jobs: int, lifetime_applications: int) -> tuple[list[dict], list[dict]]:
        cur = self.conn.execute("SELECT status, COUNT(*) as count FROM applications GROUP BY status")
        app_status_counts = {row["status"]: row["count"] for row in cur.fetchall()}
        archived_count = self.conn.execute(
            "SELECT COUNT(*) FROM application_ledger WHERE active_in_list = 0"
        ).fetchone()[0]

        total_funnel = saved_jobs + lifetime_applications
        calc_pct = lambda c: round((c / total_funnel) * 100, 1) if total_funnel > 0 else 0.0

        offer_count = app_status_counts.get("offer", 0) + app_status_counts.get("hired", 0)
        closed_count = (
            app_status_counts.get("rejected", 0)
            + app_status_counts.get("no_response", 0)
            + app_status_counts.get("offer_declined", 0)
            + app_status_counts.get("withdrawn", 0)
        )
        status_distribution = [
            {"status": "saved", "label": "Salva (Interesse)", "count": saved_jobs, "percentage": calc_pct(saved_jobs), "color": "#38bdf8"},
            {"status": "applied", "label": "Candidatura enviada", "count": app_status_counts.get("applied", 0), "percentage": calc_pct(app_status_counts.get("applied", 0)), "color": "#60a5fa"},
            {"status": "screening", "label": "Triagem RH", "count": app_status_counts.get("screening", 0), "percentage": calc_pct(app_status_counts.get("screening", 0)), "color": "#818cf8"},
            {"status": "interview", "label": "Entrevista", "count": app_status_counts.get("interview", 0), "percentage": calc_pct(app_status_counts.get("interview", 0)), "color": "#a855f7"},
            {"status": "offer", "label": "Proposta / Contratação", "count": offer_count, "percentage": calc_pct(offer_count), "color": "#34d399"},
            {"status": "rejected", "label": "Encerrada / Não seguiu", "count": closed_count, "percentage": calc_pct(closed_count), "color": "#f87171"},
            {"status": "archived", "label": "Limpa da Lista (Histórico)", "count": archived_count, "percentage": calc_pct(archived_count), "color": "#94a3b8"},
        ]

        cur = self.conn.execute("""
            SELECT COALESCE(NULLIF(portal, ''), 'manual') as portal_code, COUNT(*) as count
            FROM application_ledger
            GROUP BY portal_code
            ORDER BY count DESC
            LIMIT 8
        """)
        portal_distribution = []
        for r in cur.fetchall():
            code = r["portal_code"]
            label = _PORTAL_LABELS.get(code, code.replace("-search", "").capitalize() if code else "Outro")
            portal_distribution.append({"portal": code, "label": label, "count": r["count"]})
        return status_distribution, portal_distribution

    def get_dashboard_stats(self, period_months: int = 6) -> dict:
        """Compile complete analytics dashboard metrics and timelines (read-only)."""
        kpis = self._query_dashboard_kpis()
        monthly_timeline, daily_timeline = self._query_dashboard_timelines(period_months)
        status_distribution, portal_distribution = self._query_dashboard_distributions(
            kpis["saved_jobs"],
            kpis["lifetime_applications"],
        )
        cur = self.conn.execute("""
            SELECT id, company, role, portal, job_url, applied_date, active_in_list
            FROM application_ledger
            ORDER BY applied_date DESC, id DESC
            LIMIT 5
        """)
        recent_activity = [dict(r) for r in cur.fetchall()]

        return {
            "kpis": kpis,
            "monthly_timeline": monthly_timeline,
            "daily_timeline": daily_timeline,
            "status_distribution": status_distribution,
            "portal_distribution": portal_distribution,
            "recent_activity": recent_activity,
        }
