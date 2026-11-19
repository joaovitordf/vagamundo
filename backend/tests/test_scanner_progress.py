"""Unit tests for Scanner progress tracking and region routing."""

import unittest
from backend.core.scanner import ScannerService
from backend.tools import scrape_run


class ScannerProgressTests(unittest.TestCase):
    def test_region_portals_configuration(self):
        self.assertIn("brasil", scrape_run.REGION_PORTALS)
        self.assertIn("estados-unidos", scrape_run.REGION_PORTALS)
        self.assertIn("europa", scrape_run.REGION_PORTALS)
        self.assertIn("global", scrape_run.REGION_PORTALS)

        self.assertIn("gupy-search", scrape_run.REGION_PORTALS["brasil"])
        self.assertIn("solides-search", scrape_run.REGION_PORTALS["brasil"])
        self.assertIn("greenhouse-search", scrape_run.REGION_PORTALS["estados-unidos"])
        self.assertIn("freehire-search", scrape_run.REGION_PORTALS["europa"])
        self.assertIn("jobicy-search", scrape_run.REGION_PORTALS["europa"])

    def test_scanner_initial_status(self):
        scanner = ScannerService()
        st = scanner.status()
        self.assertFalse(st["running"])
        self.assertIn("progress", st)
        self.assertEqual(st["progress"]["percent"], 0.0)
        self.assertEqual(st["progress"]["completed"], 0)
        self.assertEqual(st["progress"]["jobs_found"], 0)
        self.assertIsInstance(st["progress"]["portals"], dict)


class ScannerAppliedFilterTests(unittest.TestCase):
    def test_load_results_hides_jobs_already_applied_via_ledger(self):
        import json
        import tempfile
        from pathlib import Path
        from backend.db.repository import Repository

        repo = Repository(":memory:")
        self.addCleanup(repo.close)
        repo.record_application_ledger(
            company="Empresa A",
            role="Cargo A",
            job_url="https://portal.example/vaga/1/",
        )
        repo.upsert_job({
            "id": "job-b",
            "company": "Empresa B",
            "title": "Cargo B",
            "url": "https://portal.example/vaga/b-orig",
            "status": "applied",
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "res.json"
            out.write_text(json.dumps({"new": [
                {"url": "https://portal.example/vaga/1?utm=x", "company": "Outra", "title": "Outro", "date": None},
                {"url": "https://portal.example/vaga/2", "company": " empresa b ", "title": "CARGO  B", "date": None},
                {"url": "https://portal.example/vaga/3", "company": "Livre", "title": "Livre", "date": None},
            ]}), encoding="utf-8")
            scanner = ScannerService(out_path=out, repo=repo)
            urls = [j["url"] for j in scanner.load_results()["new"]]
        self.assertEqual(urls, ["https://portal.example/vaga/3"])


if __name__ == "__main__":
    unittest.main()

