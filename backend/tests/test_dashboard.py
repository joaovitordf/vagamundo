"""Unit tests for Application Ledger and Dashboard Analytics API."""

import unittest
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from backend.api.app import app
from backend.api.deps import get_tracker
from backend.db.repository import Repository
from backend.core.tracker import TrackerService


class TestDashboardAndLedger(unittest.TestCase):
    def setUp(self):
        import os
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "test_dash.db"
        os.environ["VAGAMUNDO_DB_PATH"] = str(self.db_path)
        self.repo = Repository(self.db_path)
        self.tracker = TrackerService(self.repo)
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        self.client = TestClient(app)

    def tearDown(self):
        import os
        import gc
        app.dependency_overrides.clear()
        os.environ.pop("VAGAMUNDO_DB_PATH", None)
        self.repo.close()
        gc.collect()
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def test_ledger_preserves_count_after_deletion(self):
        # 1. Create a job and application
        job_id = self.repo.upsert_job({
            "title": "Software Engineer",
            "company": "Acme Corp",
            "url": "https://acme.com/job/1",
            "portal": "gupy-search",
            "status": "applied",
        })
        app_id = self.repo.upsert_application({
            "job_id": job_id,
            "status": "applied",
            "applied_date": "2026-10-15",
        })
        self.repo.record_application_ledger(
            company="Acme Corp",
            role="Software Engineer",
            portal="gupy-search",
            job_url="https://acme.com/job/1",
            job_id=job_id,
            applied_date="2026-10-15",
        )

        stats_before = self.repo.get_dashboard_stats(period_months=6)
        self.assertEqual(stats_before["kpis"]["active_applications"], 1)
        self.assertEqual(stats_before["kpis"]["lifetime_applications"], 1)

        # 2. User clears / removes the application from the active list
        self.repo.delete_application(app_id=app_id)
        self.repo.archive_application_ledger(job_id=job_id, app_id=app_id)

        # 3. Active application count drops to 0, BUT lifetime application count REMAINS 1!
        stats_after = self.repo.get_dashboard_stats(period_months=6)
        self.assertEqual(stats_after["kpis"]["active_applications"], 0)
        self.assertEqual(stats_after["kpis"]["lifetime_applications"], 1)

        # 4. Check monthly timeline retained the application count for 2026-10
        oct_entry = next((m for m in stats_after["monthly_timeline"] if m["month_key"] == "2026-10"), None)
        if oct_entry:
            self.assertEqual(oct_entry["count"], 1)
            self.assertEqual(oct_entry["archived"], 1)

    def test_dashboard_api_endpoint(self):
        res = self.client.get("/api/dashboard/stats?period_months=6")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("kpis", data)
        self.assertIn("monthly_timeline", data)
        self.assertIn("daily_timeline", data)
        self.assertIn("status_distribution", data)
        self.assertIn("portal_distribution", data)
        self.assertIn("recent_activity", data)

        # Assert daily timeline is in descending order (most recent first)
        daily = data["daily_timeline"]
        self.assertTrue(len(daily) > 0)
        self.assertTrue(daily[0]["is_today"])
        self.assertGreaterEqual(daily[0]["date"], daily[-1]["date"])

        # Assert monthly timeline is in descending order (most recent first)
        monthly = data["monthly_timeline"]
        self.assertTrue(len(monthly) > 0)
        self.assertTrue(monthly[0]["is_current"])
        self.assertGreaterEqual(monthly[0]["month_key"], monthly[-1]["month_key"])


if __name__ == "__main__":
    unittest.main()
