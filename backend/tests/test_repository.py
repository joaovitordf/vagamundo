"""Unit tests for SQLite Repository and TrackerService."""

from __future__ import annotations
import unittest
from pathlib import Path

from backend.db.repository import Repository
from backend.core.tracker import TrackerService


class TestRepository(unittest.TestCase):
    def setUp(self):
        # In-memory database for fast, isolated tests
        self.repo = Repository(":memory:")
        self.tracker = TrackerService(self.repo)

    def tearDown(self):
        self.repo.close()

    def test_schema_initialized(self):
        cur = self.repo.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        expected = {"jobs", "applications", "status_log", "evaluations", "profile", "scan_runs"}
        self.assertTrue(expected.issubset(tables))

    def test_upsert_and_get_job(self):
        job_data = {
            "title": "Software Engineer",
            "company": "Acme Tech",
            "url": "https://example.com/jobs/123",
            "location": "Remote",
            "portal": "gupy-search",
            "strengths": ["Python", "Angular"],
            "signals": {"remote": True},
        }
        job_id = self.repo.upsert_job(job_data)
        self.assertIsNotNone(job_id)

        fetched = self.repo.get_job(job_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "Software Engineer")
        self.assertEqual(fetched["company"], "Acme Tech")
        self.assertEqual(fetched["url"], "https://example.com/jobs/123")
        self.assertEqual(fetched["strengths"], ["Python", "Angular"])
        self.assertEqual(fetched["signals"], {"remote": True})

        # By URL
        by_url = self.repo.get_job_by_url("https://example.com/jobs/123")
        self.assertIsNotNone(by_url)
        self.assertEqual(by_url["id"], job_id)

    def test_upsert_update_existing_job(self):
        job_data = {
            "id": "acme-tech_dev",
            "title": "Dev Junior",
            "company": "Acme Tech",
            "url": "https://example.com/jobs/dev",
            "status": "new",
        }
        self.repo.upsert_job(job_data)

        # Update title and status
        update_data = {
            "id": "acme-tech_dev",
            "title": "Dev Pleno",
            "status": "interested",
        }
        self.repo.upsert_job(update_data)

        updated = self.repo.get_job("acme-tech_dev")
        self.assertEqual(updated["title"], "Dev Pleno")
        self.assertEqual(updated["status"], "interested")

    def test_list_and_count_jobs(self):
        self.repo.upsert_job({"id": "j1", "title": "Backend Python", "company": "Co1", "url": "https://u1", "status": "new", "portal": "gupy"})
        self.repo.upsert_job({"id": "j2", "title": "Frontend Angular", "company": "Co2", "url": "https://u2", "status": "interested", "portal": "linkedin"})
        self.repo.upsert_job({"id": "j3", "title": "Fullstack Python Angular", "company": "Co3", "url": "https://u3", "status": "new", "portal": "gupy"})

        # List all
        all_jobs = self.repo.list_jobs(limit=10)
        self.assertEqual(len(all_jobs), 3)

        # Filter by status
        new_jobs = self.repo.list_jobs(status="new")
        self.assertEqual(len(new_jobs), 2)
        self.assertEqual(self.repo.count_jobs(status="new"), 2)

        # Filter by portal
        gupy_jobs = self.repo.list_jobs(portal="gupy")
        self.assertEqual(len(gupy_jobs), 2)

        # Search term q
        search_jobs = self.repo.list_jobs(q="Angular")
        self.assertEqual(len(search_jobs), 2)

    def test_mark_jobs_and_status_log(self):
        self.repo.upsert_job({"id": "j1", "title": "Engineer", "company": "C1", "url": "https://u1", "status": "new"})
        updated = self.repo.mark_jobs(["j1"], decision="interested", source="test", note="Looks good")
        self.assertEqual(updated, 1)

        job = self.repo.get_job("j1")
        self.assertEqual(job["status"], "interested")
        self.assertEqual(job["fit"], "medium")

        # Check status_log
        cur = self.repo.conn.execute("SELECT * FROM status_log WHERE job_id = 'j1'")
        logs = cur.fetchall()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["from_status"], "new")
        self.assertEqual(logs[0]["to_status"], "interested")
        self.assertEqual(logs[0]["note"], "Looks good")

    def test_evaluations(self):
        self.repo.upsert_job({"id": "j1", "title": "Engineer", "company": "C1", "url": "https://u1"})
        eval_id = self.repo.insert_evaluation({
            "job_id": "j1",
            "score_technical": 85,
            "score_experience": 80,
            "score_behavioral": 90,
            "score_location": "PASS",
            "score_career": 75,
            "score_global": 82,
            "verdict": "Strong Fit",
            "strengths": ["Clean Code"],
            "gaps": ["Kubernetes"],
            "report_md": "# Report",
            "ai_provider": "gemini",
        })
        self.assertGreater(eval_id, 0)

        ev = self.repo.get_evaluation("j1")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["score_global"], 82)
        self.assertEqual(ev["verdict"], "Strong Fit")
        self.assertEqual(ev["strengths"], ["Clean Code"])

        # Check job updated
        job = self.repo.get_job("j1")
        self.assertEqual(job["rank_score"], 82)
        self.assertEqual(job["rank_verdict"], "Strong Fit")

    def test_applications(self):
        self.repo.upsert_job({"id": "j1", "title": "Engineer", "company": "C1", "url": "https://u1"})
        app_id = self.repo.upsert_application({
            "job_id": "j1",
            "status": "enviada",
            "cv_path": "cv/cv.pdf",
            "notes": "Applied via form",
        })
        self.assertGreater(app_id, 0)

        apps = self.repo.list_applications()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["job_title"], "Engineer")
        self.assertEqual(apps[0]["status"], "enviada")

    def test_tracker_is_seen(self):
        self.repo.upsert_job({"id": "j1", "title": "Angular Dev", "company": "Tech Corp", "url": "https://example.com/job1"})

        # By URL
        self.assertTrue(self.tracker.is_seen(url="https://example.com/job1"))
        self.assertFalse(self.tracker.is_seen(url="https://example.com/job2"))

        # By company + title
        self.assertTrue(self.tracker.is_seen(company="Tech Corp", title="Angular Dev"))
        self.assertTrue(self.tracker.is_seen(company="tech corp", title="angular dev"))
        self.assertFalse(self.tracker.is_seen(company="Other Corp", title="Angular Dev"))

    def test_evaluation_language_columns_and_deterministic_id(self):
        jid = self.repo.upsert_job({"title": "", "company": "", "url": "", "portal": "recruiter_radar"})
        jid_repeat = self.repo.upsert_job({"title": "", "company": "", "url": "", "portal": "recruiter_radar"})
        self.assertEqual(jid, jid_repeat)
        self.assertTrue(jid.startswith("unknown-company_untitled-"))
        self.repo.insert_evaluation({
            "job_id": jid,
            "score_global": 72,
            "verdict": "Good Fit",
            "language_gate": "FLAG",
            "language_note": "Inglês intermediário",
            "strengths": ["Python"],
            "gaps": ["Docker"],
        })
        ev = self.repo.get_evaluation(jid)
        self.assertEqual(ev["language_gate"], "FLAG")
        self.assertEqual(ev["language_note"], "Inglês intermediário")
        details = self.repo.get_latest_evaluation_details([jid])
        self.assertEqual(details[jid]["language_gate"], "FLAG")
        self.assertEqual(details[jid]["language_note"], "Inglês intermediário")

    def test_dashboard_stats_is_read_only(self):
        self.repo.upsert_job({"id": "j-ro", "title": "Eng", "company": "RoCo", "url": "https://u-ro", "status": "applied"})
        self.repo.upsert_application({"job_id": "j-ro", "status": "applied", "applied_date": "2026-01-01"})
        # Removendo do ledger manualmente para garantir que get_dashboard_stats não re-escreve no banco
        with self.repo.conn:
            self.repo.conn.execute("DELETE FROM application_ledger")
        stats = self.repo.get_dashboard_stats(period_months=6)
        self.assertIn("kpis", stats)
        self.assertEqual(stats["kpis"]["active_applications"], 1)
        self.assertEqual(stats["kpis"]["lifetime_applications"], 0)
        count_after = self.repo.conn.execute("SELECT COUNT(*) FROM application_ledger").fetchone()[0]
        self.assertEqual(count_after, 0)


if __name__ == "__main__":
    unittest.main()

