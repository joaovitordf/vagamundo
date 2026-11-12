"""Integration tests for FastAPI gateway endpoints."""

from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_tracker
from backend.api.security import get_token
from backend.db.repository import Repository
from backend.core.tracker import TrackerService


class TestFastAPI(unittest.TestCase):
    def setUp(self):
        import os
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "test_api.db"
        os.environ["VAGAMUNDO_DB_PATH"] = str(self.db_path)
        self.repo = Repository(self.db_path)
        self.tracker = TrackerService(self.repo)
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        self.client = TestClient(app)
        self.token = get_token()

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
        with patch("backend.tools.painel.mark"):
            resp_ok = self.client.post(
                "/api/mark",
                json={"urls": [], "decision": "interesse"},
                headers={"X-Painel-Token": self.token},
            )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertTrue(resp_ok.json().get("ok"))

    def test_applied_endpoint(self):
        test_url = "https://example.com/test-applied-unit"
        resp = self.client.post(
            "/api/applied",
            json={
                "url": test_url,
                "company": "Empresa Teste",
                "role": "Frontend Angular",
                "portal": "linkedin-search"
            },
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("applied"))

        # Clean up test application and verify remove endpoint
        del_resp = self.client.post(
            "/api/applications/remove",
            json={"url": test_url},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json().get("ok"))

    def test_job_interest_and_apply_data_lifecycle(self):
        sample_url = "https://example.com/job-lifecycle-audit-123"
        job_payload = {
            "title": "Engenheiro de Software Pleno",
            "company": "Tech Inova",
            "url": sample_url,
            "location": "São Paulo, SP",
            "portal": "gupy-search",
            "workplace_type": "remote",
            "date": "2026-10-31",
            "contract": "CLT",
            "seniority": "Pleno",
            "screening": {
                "score": 88,
                "verdict": "Alta Afinidade",
                "summary": "Excelente aderência ao perfil."
            }
        }

        # 1. Mark as interest
        with patch("backend.tools.painel.mark"):
            mark_resp = self.client.post(
                "/api/mark",
                json={
                    "urls": [sample_url],
                    "decision": "interesse",
                    "job_data": job_payload
                },
                headers={"X-Painel-Token": self.token},
            )
        self.assertEqual(mark_resp.status_code, 200)

        # 2. Check /api/saved returns all normalized fields
        saved_resp = self.client.get("/api/saved")
        self.assertEqual(saved_resp.status_code, 200)
        saved_jobs = saved_resp.json().get("saved", [])
        matched = next((j for j in saved_jobs if j.get("url") == sample_url), None)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.get("company"), "Tech Inova")
        self.assertEqual(matched.get("title"), "Engenheiro de Software Pleno")
        self.assertEqual(matched.get("workplace_type"), "remote")
        self.assertEqual(matched.get("date"), "2026-10-31")
        self.assertEqual(matched.get("contract"), "CLT")
        self.assertIsNotNone(matched.get("screening"))
        self.assertEqual(matched["screening"].get("score"), 88)

        # 3. Mark applied from Me Interessam / Buscar Vagas
        app_resp = self.client.post(
            "/api/applied",
            json={
                "url": sample_url,
                "company": "Tech Inova",
                "role": "Engenheiro de Software Pleno",
                "portal": "gupy-search"
            },
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(app_resp.status_code, 200)

        # 4. Check /api/applications returns the application with full metadata and id
        list_resp = self.client.get("/api/applications")
        self.assertEqual(list_resp.status_code, 200)
        apps = list_resp.json().get("applications", [])
        app_match = next((a for a in apps if a.get("url") == sample_url), None)
        self.assertIsNotNone(app_match)
        self.assertEqual(app_match.get("company"), "Tech Inova")
        self.assertEqual(app_match.get("role"), "Engenheiro de Software Pleno")
        self.assertEqual(app_match.get("channel"), "gupy-search")
        self.assertEqual(app_match.get("status"), "applied")
        self.assertIsNotNone(app_match.get("id"))

        # 5. Delete application using the remove endpoint
        del_resp = self.client.post(
            "/api/applications/remove",
            json={"url": sample_url, "id": app_match.get("id")},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json().get("ok"))

        # 6. Verify it is removed from applications
        after_del = self.client.get("/api/applications").json().get("applications", [])
        self.assertIsNone(next((a for a in after_del if a.get("url") == sample_url), None))

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

        repo = self.repo
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

    def test_application_event_lifecycle_and_evolution_sync(self):
        # 1. Apply to a job
        test_url = "https://example.com/job-lifecycle-event-test"
        apply_resp = self.client.post("/api/applied", json={
            "url": test_url,
            "company": "Event Tech S/A",
            "role": "Senior Frontend Angular",
            "portal": "gupy-search"
        }, headers={"X-Painel-Token": self.token})
        self.assertEqual(apply_resp.status_code, 200)

        # 2. Retrieve application id
        apps_resp = self.client.get("/api/applications")
        self.assertEqual(apps_resp.status_code, 200)
        apps = apps_resp.json().get("applications", [])
        my_app = next((a for a in apps if a.get("url") == test_url), None)
        self.assertIsNotNone(my_app)
        app_id = my_app["id"]

        # 3. Add an interview event
        event_payload = {
            "application_id": app_id,
            "stage": "Entrevista Técnica",
            "event_date": "2026-10-31",
            "feedback": "Excelente domínio de Angular Signals e RxJS.",
            "questions_and_answers": "P: Como otimizar performance no Angular? R: Usar OnPush, signals e lazy loading.",
            "status": "interview"
        }
        event_resp = self.client.post("/api/applications/event", json=event_payload, headers={"X-Painel-Token": self.token})
        self.assertEqual(event_resp.status_code, 200)
        event_data = event_resp.json()
        self.assertTrue(event_data.get("ok"))
        event_id = event_data.get("event_id")
        self.assertIsNotNone(event_id)

        # 4. List events for this application
        events_list_resp = self.client.get(f"/api/applications/{app_id}/events")
        self.assertEqual(events_list_resp.status_code, 200)
        events_list = events_list_resp.json().get("events", [])
        self.assertGreaterEqual(len(events_list), 1)
        self.assertEqual(events_list[0]["stage"], "Entrevista Técnica")
        self.assertEqual(events_list[0]["feedback"], "Excelente domínio de Angular Signals e RxJS.")

        # 5. Call update evolution endpoint
        with patch("backend.tools.painel.save_evolution"):
            evo_resp = self.client.post("/api/evolucao/atualizar", headers={"X-Painel-Token": self.token})
            self.assertEqual(evo_resp.status_code, 200)
            evo_data = evo_resp.json()
            self.assertTrue(evo_data.get("ok"))
            metrics = evo_data["evolution"]["evolution"]["metrics"]
            self.assertGreaterEqual(metrics["applications"], 1)
            self.assertGreaterEqual(metrics["applications_with_feedback"], 1)
            self.assertGreaterEqual(metrics["applications_with_questions"], 1)

        # 6. Delete event and cleanup application
        del_ev_resp = self.client.delete(f"/api/applications/event/{event_id}", headers={"X-Painel-Token": self.token})
        self.assertEqual(del_ev_resp.status_code, 200)

        rem_resp = self.client.post("/api/applications/remove", json={"id": app_id, "url": test_url}, headers={"X-Painel-Token": self.token})
        self.assertEqual(rem_resp.status_code, 200)

    def test_host_check_blocks_localhost_spoof_and_allows_valid_hosts(self):
        bad_spoof = self.client.get("/api/token", headers={"Host": "localhost.attacker.com:8765"})
        self.assertEqual(bad_spoof.status_code, 400)

        bad_empty = self.client.get("/api/token", headers={"Host": ""})
        self.assertEqual(bad_empty.status_code, 400)

        ok_ipv6 = self.client.get("/api/token", headers={"Host": "[::1]:8765"})
        self.assertEqual(ok_ipv6.status_code, 200)

        ok_local = self.client.get("/api/token", headers={"Host": "localhost:4200"})
        self.assertEqual(ok_local.status_code, 200)


if __name__ == "__main__":
    unittest.main()
