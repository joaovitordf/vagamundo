"""Integration tests for FastAPI gateway endpoints."""

from __future__ import annotations
import unittest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.security import get_token


class TestFastAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.token = get_token()

    def test_token_endpoint(self):
        resp = self.client.get("/api/token")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("token", data)
        self.assertEqual(data["token"], self.token)

    def test_settings_endpoint(self):
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("provider", data)
        self.assertIn("providers", data)

    def test_search_status_endpoint(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("running", data)

    def test_saved_jobs_endpoint(self):
        resp = self.client.get("/api/saved")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("saved", data)
        self.assertIn("total", data)
        if data["saved"]:
            first = data["saved"][0]
            self.assertIn("claude", first)

    def test_applications_endpoint(self):
        resp = self.client.get("/api/applications")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("applications", data)

    def test_jobs_rest_endpoint(self):
        resp = self.client.get("/api/jobs")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("jobs", data)
        self.assertIn("total", data)

    def test_cv_areas_endpoint(self):
        resp = self.client.get("/api/cv-areas")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("areas", data)

    def test_profile_endpoint(self):
        resp = self.client.get("/api/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("schema", data)
        self.assertIn("answers", data)
        self.assertIn("files", data)
        self.assertIn("privacy", data)
        self.assertIn("ready", data)

    def test_csrf_protection_on_post(self):
        # Without token -> 403 Forbidden
        resp_blocked = self.client.post("/api/mark", json={"urls": [], "decision": "interesse"})
        self.assertEqual(resp_blocked.status_code, 403)

        # With token in header -> 200 OK
        resp_ok = self.client.post(
            "/api/mark",
            json={"urls": [], "decision": "interesse"},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertTrue(resp_ok.json().get("ok"))

    def test_applied_endpoint(self):
        resp = self.client.post(
            "/api/applied",
            json={
                "url": "https://example.com/test-applied-unit",
                "company": "Empresa Teste",
                "role": "Frontend Angular",
                "portal": "linkedin-search"
            },
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("applied"))

    def test_file_endpoint_security(self):
        # Non-existing or illegal path -> 404/403
        bad_resp = self.client.get("/api/file?path=../../etc/passwd")
        self.assertIn(bad_resp.status_code, (403, 404))

    def test_clear_discarded_endpoint(self):
        resp = self.client.post("/api/discarded/clear", headers={"X-Painel-Token": self.token})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

    def test_clear_documents_endpoint_protects_cv(self):
        resp = self.client.post("/api/documents/clear?keep_cv=true", headers={"X-Painel-Token": self.token})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("kept_cv"))

    def test_auto_discard_low_score_jobs(self):
        from unittest.mock import patch
        from backend.core.evaluator import EvaluatorService
        from backend.db.repository import Repository

        repo = Repository()
        test_url = "https://example.com/job-auto-discard-test-low"
        test_job = {
            "title": "Low Score Job Test",
            "company": "Test Company Low",
            "url": test_url,
            "status": "new",
        }
        repo.upsert_job(test_job)

        evaluator = EvaluatorService(repo=repo)
        with patch("backend.tools.painel_ia.triar_vaga_rapida") as mock_triage:
            mock_triage.return_value = {
                "url": test_url,
                "score": 25,
                "verdict": "Poor Fit",
                "summary": "Tecnologias não batem",
                "title": test_job["title"],
                "company": test_job["company"],
            }
            res = evaluator._screen_one(test_url)
            self.assertTrue(res.get("discarded"))
            self.assertEqual(res.get("score"), 25)

        # Verifica se no banco o status agora é discarded e fit é low
        j = repo.get_job_by_url(test_url)
        self.assertIsNotNone(j)
        self.assertEqual(j["status"], "discarded")
        self.assertEqual(j["fit"], "low")
        self.assertEqual(j["rank_score"], 25)

        # Verifica se o endpoint /api/discarded retorna a vaga com screening
        resp = self.client.get("/api/discarded")
        self.assertEqual(resp.status_code, 200)
        disc_jobs = resp.json().get("discarded", [])
        found = next((x for x in disc_jobs if x.get("url") == test_url), None)
        self.assertIsNotNone(found)
        self.assertIn("screening", found)
        self.assertEqual(found["screening"]["score"], 25)
        self.assertEqual(found["screening"]["verdict"], "Poor Fit")


if __name__ == "__main__":
    unittest.main()
