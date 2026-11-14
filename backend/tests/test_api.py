"""Integration tests for FastAPI gateway endpoints."""

from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_docgen, get_profile, get_tracker
from backend.api.security import get_token
from backend.core.docgen import DocGenService
from backend.core.profile import ProfileService
from backend.db.repository import Repository
from backend.core.tracker import TrackerService
from backend.tools import ai_providers, painel, painel_ia, painel_perfil, scrape_run


class TestFastAPI(unittest.TestCase):
    def setUp(self):
        import os
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        tmp_dir = Path(self.tmp.name)
        fake_root = tmp_dir / "workspace" / "backend"
        (fake_root / "documents").mkdir(parents=True, exist_ok=True)
        (fake_root / "job_scraper").mkdir(parents=True, exist_ok=True)
        fake_claude = fake_root / "documents" / "applications" / "_painel"
        fake_seen = fake_root / "job_scraper" / "seen_jobs.json"
        fake_tracker = fake_root / "documents" / "job_search_tracker.csv"

        for target, value in (
            (painel, ("ROOT", fake_root)),
            (painel, ("CLAUDE_DIR", fake_claude)),
            (painel, ("EVOLUTION_PATH", fake_root / "documents" / "evolucao.json")),
            (painel, ("WORK_CONTEXT_DIR", tmp_dir / "work")),
            (painel_ia, ("PAINEL_DIR", fake_claude)),
            (painel_perfil, ("ROOT", fake_root)),
            (painel_perfil, ("REPO_ROOT", fake_root.parent)),
            (painel_perfil, ("DOCUMENTS", fake_root / "documents")),
            (painel_perfil, ("ANSWERS", fake_root / "documents" / "perfil" / "respostas.json")),
            (scrape_run, ("SEEN", fake_seen)),
            (scrape_run, ("TRACKER", fake_tracker)),
            (painel.scrape_run, ("SEEN", fake_seen)),
            (painel.scrape_run, ("TRACKER", fake_tracker)),
            (ai_providers, ("ENV_PATH", tmp_dir / ".env")),
        ):
            attr, new_val = value
            p = patch.object(target, attr, new_val)
            p.start()
            self.addCleanup(p.stop)

        self.db_path = tmp_dir / "test_api.db"
        os.environ["VAGAMUNDO_DB_PATH"] = str(self.db_path)
        self.repo = Repository(self.db_path)
        self.tracker = TrackerService(self.repo)
        self.docgen = DocGenService(self.repo)
        self.profile_svc = ProfileService()
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        app.dependency_overrides[get_docgen] = lambda: self.docgen
        app.dependency_overrides[get_profile] = lambda: self.profile_svc
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
        self.assertIn(data.get("source"), ("profile", "fallback"))

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

    def test_saved_batch_reevaluate_discard_and_applied_endpoints(self):
        from backend.api.deps import get_evaluator
        from backend.core.evaluator import EvaluatorService
        from backend.tools import painel, painel_ia

        tmp_dir = Path(self.tmp.name)
        seen_file = tmp_dir / "seen_jobs.json"
        tracker_csv = tmp_dir / "job_search_tracker.csv"
        evo_json = tmp_dir / "evolution.json"
        claude_dir = tmp_dir / "painel_cache"
        claude_dir.mkdir(parents=True, exist_ok=True)

        evaluator = EvaluatorService(repo=self.repo)
        app.dependency_overrides[get_evaluator] = lambda: evaluator

        url_http = "https://example.com/vaga-saved-1"
        url_rec = "recruiter://post/999"
        self.repo.upsert_job({
            "title": "Dev Java Junior",
            "company": "Acme",
            "url": url_http,
            "portal": "gupy-search",
            "status": "interested",
            "description": "Desenvolvimento backend em Java com Spring Boot e SQL.",
        })
        self.repo.upsert_job({
            "title": "Backend Recruiter",
            "company": "Beta",
            "url": url_rec,
            "portal": "github-vagas",
            "status": "interested",
            "description": "Vaga Java Júnior via recrutador direto.",
        })

        fake_report = (
            "> Modelo: gemini-4-hydrogen-high\n\n"
            "## Avaliação de encaixe: Dev\n\n"
            "**Nota geral: 35/100**\n\n"
            "### Veredito: Weak Fit\n\n"
            "### Recomendação\n"
            "Reavaliada com novo modelo.\n"
        )

        with patch("backend.tools.painel.CLAUDE_DIR", claude_dir), \
             patch("backend.tools.painel_ia.PAINEL_DIR", claude_dir), \
             patch("backend.tools.painel.scrape_run.SEEN", seen_file), \
             patch("backend.tools.painel.scrape_run.TRACKER", tracker_csv), \
             patch("backend.tools.painel.EVOLUTION_PATH", evo_json), \
             patch("backend.tools.painel.record_applied", return_value={"ok": True}), \
             patch("backend.tools.painel.discard_job", return_value={"discarded": True}), \
             patch("backend.tools.painel_ia.avaliar_vaga", return_value=fake_report):

            # 1. Batch re-evaluation via EvaluatorService (must never auto-discard < 40 and must persist report + ai_model)
            started = evaluator.start_reevaluate_batch([url_http, url_rec], workers=1, blocking=True)
            self.assertTrue(started)
            st = self.client.get("/api/saved/batch-status").json()
            self.assertFalse(st["running"])
            self.assertEqual(st["current"], 2)
            self.assertEqual(st["total"], 2)
            self.assertEqual(st["errors"], 0)

            for u in (url_http, url_rec):
                j = self.repo.get_job_by_url(u)
                self.assertEqual(j["status"], "interested")
                self.assertEqual(j["rank_score"], 35)
                cached = painel.get_cached_score(u)
                self.assertIsNotNone(cached)
                self.assertEqual(cached["ai_model"], "gemini-4-hydrogen-high")
                self.assertEqual(cached["summary"], "Reavaliada com novo modelo.")

            # 2. HTTP batch-reevaluate validation
            bad_reeval = self.client.post(
                "/api/saved/batch-reevaluate",
                json={"urls": ["ftp://invalid"]},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(bad_reeval.status_code, 400)

            # 3. Batch discard
            disc_resp = self.client.post(
                "/api/saved/batch-discard",
                json={"urls": [url_http]},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(disc_resp.status_code, 200)
            self.assertEqual(disc_resp.json()["discarded"], 1)
            self.assertEqual(self.repo.get_job_by_url(url_http)["status"], "discarded")

            # 4. Batch mark applied
            app_resp = self.client.post(
                "/api/applied/batch",
                json={"items": [{"url": url_rec, "company": "Beta", "role": "Backend Recruiter", "portal": "github-vagas"}]},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(app_resp.status_code, 200)
            self.assertEqual(app_resp.json()["applied"], 1)
            self.assertEqual(self.repo.get_job_by_url(url_rec)["status"], "applied")

    def test_claude_perfil_step_passes_answers_and_maps_value_error(self):
        from backend.tools import painel

        tmp_dir = Path(self.tmp.name)
        claude_dir = tmp_dir / "claude_cache"
        answers_file = tmp_dir / "respostas.json"
        answers_file.write_text('{"cargos": ["Desenvolvedor Python"]}', encoding="utf-8")

        with patch("backend.tools.painel_perfil.ANSWERS", answers_file), \
             patch("backend.tools.painel.CLAUDE_DIR", claude_dir), \
             patch("backend.tools.painel_ia.montar_perfil", return_value="> Modelo: gemini-test\n\n## Perfil consolidado") as mock_perfil:
            resp = self.client.post(
                "/api/claude",
                json={"step": "perfil", "confirm": True},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json().get("ok"))
            self.assertIn("## Perfil consolidado", resp.json().get("result", ""))
            mock_perfil.assert_called_once()
            arg_text = mock_perfil.call_args[0][0]
            self.assertIn("Desenvolvedor Python", arg_text)
            saved_md = painel.claude_answer(painel.PERFIL_KEY, "perfil", base=claude_dir)
            self.assertIsNotNone(saved_md)
            self.assertIn("## Perfil consolidado", saved_md)

        with patch("backend.tools.painel_ia.montar_perfil", side_effect=ValueError("nenhum documento legível")):
            err_resp = self.client.post(
                "/api/claude",
                json={"step": "perfil", "confirm": True},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(err_resp.status_code, 400)
            self.assertIn("nenhum documento", err_resp.json().get("detail", ""))

    def test_settings_and_profile_validation_endpoints(self):
        import os

        tmp_dir = Path(self.tmp.name)
        env_path = tmp_dir / ".env"
        answers_file = tmp_dir / "respostas.json"
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith(("GEMINI_", "OPENAI_", "ANTHROPIC_", "AI_"))}

        with patch.dict(os.environ, clean_env, clear=True), \
             patch("backend.tools.ai_providers.ENV_PATH", env_path), \
             patch("backend.tools.ai_providers.shutil.which", return_value=None):
            ok_resp = self.client.post(
                "/api/settings",
                json={"provider": "gemini", "consent": True, "gemini_key": "AIza" + "Z" * 35},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(ok_resp.status_code, 200)
            self.assertEqual(ok_resp.json().get("provider"), "gemini")
            gem = next(p for p in ok_resp.json()["providers"] if p["id"] == "gemini")
            self.assertTrue(gem["has_key"])

            bad_resp = self.client.post(
                "/api/settings",
                json={"provider": "provedor_inexistente"},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(bad_resp.status_code, 400)

        with patch("backend.tools.painel_perfil.ANSWERS", answers_file):
            # ProfileSaveRequest accepts both flat payloads and nested {"answers": ...}
            flat_resp = self.client.post(
                "/api/profile",
                json={"cargos": ["Engenheiro Backend"]},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(flat_resp.status_code, 200)
            self.assertEqual(flat_resp.json()["answers"]["cargos"], ["Engenheiro Backend"])

            nested_resp = self.client.post(
                "/api/profile",
                json={"answers": {"cargos": ["Arquiteto Python"]}},
                headers={"X-Painel-Token": self.token},
            )
            self.assertEqual(nested_resp.status_code, 200)
            self.assertEqual(nested_resp.json()["answers"]["cargos"], ["Arquiteto Python"])

    def test_clear_discarded_via_tracker_keeps_interested_jobs(self):
        self.repo.upsert_job({
            "title": "Vaga Boa",
            "company": "Emp A",
            "url": "https://example.com/keep-me",
            "status": "interested",
        })
        self.repo.upsert_job({
            "title": "Vaga Ruim",
            "company": "Emp B",
            "url": "https://example.com/drop-me",
            "status": "discarded",
            "fit": "low",
        })
        resp = self.client.post("/api/discarded/clear", headers={"X-Painel-Token": self.token})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("deleted_db"), 1)
        self.assertIsNotNone(self.repo.get_job_by_url("https://example.com/keep-me"))
        self.assertIsNone(self.repo.get_job_by_url("https://example.com/drop-me"))

    def test_delete_discarded_by_url_and_clear_also_removes_linked_recruiter_posts(self):
        keep_url = "https://example.com/keep-interested"
        self.repo.upsert_job({
            "title": "Vaga Interessante",
            "company": "Emp Keep",
            "url": keep_url,
            "status": "interested",
        })
        p1_id = self.repo.upsert_recruiter_post({
            "portal": "linkedin_post",
            "company": "Disc Tech 1",
            "title": "Dev Python Disc 1",
            "description": "Envie CV para rh1@disctech.dev",
            "emails": ["rh1@disctech.dev"],
            "matched_keywords": ["Python"],
            "match_score": 80,
            "url": "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000901/",
        })
        p2_id = self.repo.upsert_recruiter_post({
            "portal": "linkedin_post",
            "company": "Disc Tech 2",
            "title": "Dev Java Disc 2",
            "description": "Envie CV para rh2@disctech.dev",
            "emails": ["rh2@disctech.dev"],
            "matched_keywords": ["Java"],
            "match_score": 82,
            "url": "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000902/",
        })

        dismiss_resp = self.client.post(
            "/api/recruiters/dismiss-batch",
            json={"post_ids": [p1_id, p2_id]},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(dismiss_resp.status_code, 200)

        discarded_before = self.client.get("/api/discarded").json()["discarded"]
        self.assertEqual(len(discarded_before), 2)

        url_1 = "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000901/"
        url_2 = "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000902/"

        # CSRF obrigatório em /api/discarded/delete
        forbidden = self.client.post("/api/discarded/delete", json={"urls": [url_1]})
        self.assertEqual(forbidden.status_code, 403)

        # Exclui apenas url_1 do BD (incluindo vínculo recruiter_posts, sem ressuscitar em /api/recruiters)
        del_resp = self.client.post(
            "/api/discarded/delete",
            json={"urls": [url_1, keep_url]},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(del_resp.status_code, 200)
        body = del_resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["deleted_db"], 1)
        self.assertEqual(body["deleted_recruiter_posts"], 1)

        self.assertIsNone(self.repo.get_job_by_url(url_1))
        self.assertIsNotNone(self.repo.get_job_by_url(url_2))
        self.assertIsNotNone(self.repo.get_job_by_url(keep_url))

        rp_1 = self.repo.conn.execute("SELECT id FROM recruiter_posts WHERE id = ?", (p1_id,)).fetchone()
        rp_2 = self.repo.conn.execute("SELECT id FROM recruiter_posts WHERE id = ?", (p2_id,)).fetchone()
        self.assertIsNone(rp_1)
        self.assertIsNotNone(rp_2)
        self.assertEqual(self.client.get("/api/recruiters").json()["posts"], [])

        # Limpar lista restante também remove recruiter_posts vinculado a p2, mantendo interessadas
        clear_resp = self.client.post("/api/discarded/clear", headers={"X-Painel-Token": self.token})
        self.assertEqual(clear_resp.status_code, 200)
        self.assertEqual(clear_resp.json().get("deleted_db"), 1)
        self.assertIsNone(self.repo.get_job_by_url(url_2))
        self.assertIsNotNone(self.repo.get_job_by_url(keep_url))
        rp_2_after = self.repo.conn.execute("SELECT id FROM recruiter_posts WHERE id = ?", (p2_id,)).fetchone()
        self.assertIsNone(rp_2_after)
        self.assertEqual(self.client.get("/api/recruiters").json()["posts"], [])

    def test_claude_non_profile_step_requires_url(self):
        resp = self.client.post(
            "/api/claude",
            json={"url": "", "step": "avaliar"},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
