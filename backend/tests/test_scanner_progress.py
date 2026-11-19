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

    def test_load_results_keeps_interested_jobs_enriched_with_ai_screening(self):
        import json
        import tempfile
        from pathlib import Path
        from backend.db.repository import Repository

        repo = Repository(":memory:")
        self.addCleanup(repo.close)
        jid = repo.upsert_job({
            "id": "job-int",
            "company": "Acme Global",
            "title": "Computer Vision Engineer",
            "url": "https://portal.example/vaga/cv-1",
            "status": "new",
            "rank_score": 88,
            "rank_verdict": "Strong Fit",
        })
        repo.mark_jobs([jid], decision="interested", source="auto_triage", note="[auto:run99] Auto-interesse 88/100")
        repo.insert_evaluation({
            "job_id": jid,
            "score_technical": 90,
            "score_experience": 85,
            "score_behavioral": 88,
            "score_career": 88,
            "score_global": 88,
            "verdict": "Strong Fit",
            "strengths": ["OpenCV e PyTorch"],
            "gaps": ["Edge deploy"],
            "report_md": "Excelente encaixe técnico.",
            "ai_provider": "gemini-2.5-flash",
        })

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "res.json"
            out.write_text(json.dumps({"new": [
                {"url": "https://portal.example/vaga/cv-1", "company": "Acme Global", "title": "Computer Vision Engineer", "location": "Berlin, Germany"},
            ]}), encoding="utf-8")
            scanner = ScannerService(out_path=out, repo=repo)
            loaded = scanner.load_results()["new"]

        self.assertEqual(len(loaded), 1)
        item = loaded[0]
        self.assertEqual(item["status"], "interested")
        self.assertTrue(item["interested"])
        self.assertTrue(item["auto_promoted"])
        self.assertEqual(item["auto_run_id"], "run99")
        self.assertEqual(item["screening"]["score"], 88)
        self.assertEqual(item["screening"]["verdict"], "Strong Fit")
        self.assertEqual(item["screening"]["subscores"]["technical"], 90)
        self.assertEqual(item["screening"]["strengths"], ["OpenCV e PyTorch"])


if __name__ == "__main__":
    unittest.main()

