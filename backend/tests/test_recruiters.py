"""Unit tests for recruiter service and API endpoints."""

import json
import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.db.repository import Repository
from backend.core.recruiter_service import (
    extract_clean_emails,
    extract_email_context,
    extract_linkedin_snowflake_date,
    match_cv_keywords,
    RecruiterService,
)
from backend.tools import painel, painel_ia, scrape_run
from backend.api.app import app
from backend.api.deps import get_auto_mode, get_repository, get_recruiter_service, get_tracker
from backend.api.security import get_token
from backend.core.tracker import TrackerService


class TestRecruiterService(unittest.TestCase):
    def setUp(self):
        self.tmp_db = NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.repo = Repository(db_path=self.tmp_db.name)
        self.service = RecruiterService(self.repo)

    def tearDown(self):
        self.repo.close()
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)

    def test_extract_clean_emails(self):
        text = """
        Entre em contato com nossa equipe em recrutamento@techcorp.com.br.
        Ou mande para josh@sigmawave.ai, com o assunto Dev.
        Descarte privacy@techcorp.com e suporte@example.com!
        Outro caso: rh@empresa.com.
        """
        emails = extract_clean_emails(text)
        self.assertIn("recrutamento@techcorp.com.br", emails)
        self.assertIn("josh@sigmawave.ai", emails)
        self.assertIn("rh@empresa.com", emails)
        self.assertNotIn("privacy@techcorp.com", emails)
        self.assertNotIn("suporte@example.com", emails)

    def test_extract_email_context(self):
        text = "Vaga aberta para desenvolvedor frontend. Envie seu curriculo para jobs@startup.io hoje mesmo."
        ctx = extract_email_context(text, "jobs@startup.io", window=30)
        self.assertIn("jobs@startup.io", ctx)
        self.assertIn("Envie seu curriculo", ctx)

    def test_match_cv_keywords(self):
        text = "Buscamos profissional com domínio de Angular, TypeScript e experiência com Python para IA."
        kws = ["Angular", "TypeScript", "Python", "Java", "Flutter"]
        matched, score = match_cv_keywords(text, kws)
        self.assertIn("Angular", matched)
        self.assertIn("TypeScript", matched)
        self.assertIn("Python", matched)
        self.assertNotIn("Java", matched)
        self.assertGreater(score, 50)

    def test_add_pasted_post_and_dismiss(self):
        post = self.service.add_pasted_post(
            raw_text="Vaga Angular Pleno! Enviar CV para talent@inovacao.com.br",
            url="https://linkedin.com/posts/123",
            company="Inovacao Tech",
        )
        self.assertEqual(post["company"], "Inovacao Tech")
        self.assertIn("talent@inovacao.com.br", post["emails"])

        posts = self.service.list_posts()
        self.assertEqual(len(posts), 1)

        # Dismiss
        dismissed = self.service.dismiss_post(post["id"])
        self.assertTrue(dismissed)
        self.assertEqual(len(self.service.list_posts()), 0)

    def test_add_pasted_post_no_email_raises_error(self):
        with self.assertRaises(ValueError):
            self.service.add_pasted_post(raw_text="Vaga sem e-mail nenhum de contato")

    def test_sync_from_jobs(self):
        # Insert a job with email
        self.repo.upsert_job({
            "id": "job-1",
            "title": "Computer Vision Developer",
            "company": "Vision AI",
            "url": "https://example.com/job-1",
            "description": "Desenvolvimento com OpenCV e Python. Envie CV para hiring@visionai.com",
            "portal": "linkedin-search",
        })
        # Insert another job without email
        self.repo.upsert_job({
            "id": "job-2",
            "title": "Backend Dev",
            "company": "No Email Corp",
            "url": "https://example.com/job-2",
            "description": "Apenas candidate-se pela nossa plataforma interna",
            "portal": "gupy-search",
        })

        res = self.service.sync_from_jobs()
        self.assertEqual(res["posts_with_email"], 1)

        posts = self.service.list_posts()
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["company"], "Vision AI")
        self.assertIn("hiring@visionai.com", posts[0]["emails"])

    def test_sync_excludes_discarded_jobs_and_preserves_ai_cache(self):
        self.repo.upsert_job({
            "id": "job-discarded",
            "title": "Vaga Descartada",
            "company": "Old Corp",
            "url": "https://example.com/old",
            "description": "Contato: rh@oldcorp.com",
            "status": "discarded",
        })
        self.repo.upsert_job({
            "id": "job-active",
            "title": "Dev Ativa",
            "company": "Nova Corp",
            "url": "https://example.com/active",
            "description": "Envie CV para rh@novacorp.com",
            "status": "new",
        })

        self.service.sync_from_jobs()
        posts = self.service.list_posts()
        self.assertEqual(len(posts), 1)
        pid = posts[0]["id"]

        self.repo.update_recruiter_post_ai(
            pid,
            classification="vaga_ativa",
            score=77,
            verdict="Good Fit",
            summary="Boa aderência",
            best_email="rh@novacorp.com",
        )
        # Re-sync must not wipe cached AI evaluation
        self.service.sync_from_jobs()
        refreshed = self.repo.get_recruiter_post(pid)
        self.assertEqual(refreshed["ai_score"], 77)
        self.assertEqual(refreshed["ai_classification"], "vaga_ativa")
        self.assertIsNotNone(refreshed["ai_evaluated_at"])

    def test_list_orders_non_jobs_last_and_filters_include_non_jobs(self):
        p1 = self.service.add_pasted_post(
            raw_text="Vaga Python Pleno. Envie para jobs@python.dev",
            url="https://example.com/p1",
            company="PyDev",
        )
        p2 = self.service.add_pasted_post(
            raw_text="Artigo com dicas de carreira! Dúvidas em blog@editorial.dev",
            url="https://example.com/p2",
            company="Blog",
        )
        self.repo.update_recruiter_post_ai(p1["id"], "vaga_ativa", 70, "Good Fit", "Vaga real", "jobs@python.dev")
        self.repo.update_recruiter_post_ai(p2["id"], "nao_e_vaga", 0, "Poor Fit", "É apenas um artigo", "")

        all_visible = self.service.list_posts(include_non_jobs=True)
        self.assertEqual([p["id"] for p in all_visible], [p1["id"], p2["id"]])
        self.assertEqual(all_visible[1]["ai_classification"], "nao_e_vaga")

        only_jobs = self.service.list_posts(include_non_jobs=False)
        self.assertEqual([p["id"] for p in only_jobs], [p1["id"]])

    def test_legacy_db_migration_adds_recruiter_ai_columns(self):
        legacy_file = NamedTemporaryFile(suffix=".db", delete=False)
        legacy_file.close()
        try:
            conn = sqlite3.connect(legacy_file.name)
            conn.execute("""
                CREATE TABLE recruiter_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emails TEXT NOT NULL,
                    email_context TEXT,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    portal TEXT NOT NULL,
                    url TEXT,
                    location TEXT,
                    work_model TEXT,
                    published_date TEXT,
                    description TEXT NOT NULL,
                    matched_keywords TEXT,
                    match_score INTEGER DEFAULT 0,
                    job_id TEXT,
                    dismissed INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
            conn.close()

            migrated_repo = Repository(db_path=legacy_file.name)
            cols = {r["name"] for r in migrated_repo.conn.execute("PRAGMA table_info(recruiter_posts)").fetchall()}
            for col in ("ai_classification", "ai_score", "ai_verdict", "ai_summary", "ai_best_email", "ai_model", "ai_evaluated_at", "auto_promoted", "auto_run_id"):
                self.assertIn(col, cols)
            migrated_repo.close()
        finally:
            if os.path.exists(legacy_file.name):
                os.remove(legacy_file.name)

    def test_triar_post_recrutador_classifications_and_safety(self):
        post = {
            "title": "Pessoa Desenvolvedora Python",
            "company": "TechCo",
            "location": "Remoto",
            "emails": ["dpo@techco.com", "talentos@techco.com"],
            "description": "Estamos contratando dev Python pleno. Enviar CV para talentos@techco.com.",
        }
        with patch("backend.tools.painel_ia.candidate_profile", return_value="Perfil Python Pleno"), \
             patch("backend.tools.painel_ia.call_llm", return_value='{"model": "gemini-4-hydrogen-high", "classification": "vaga_ativa", "best_email": "talentos@techco.com", "score": 82, "verdict": "Strong Fit", "summary": "Casa com stack e senioridade."}'):
            out = painel_ia.triar_post_recrutador(post)
        self.assertEqual(out["classification"], "vaga_ativa")
        self.assertEqual(out["best_email"], "talentos@techco.com")
        self.assertEqual(out["score"], 82)
        self.assertEqual(out["ai_model"], "gemini-4-hydrogen-high")

        with patch("backend.tools.painel_ia.candidate_profile", return_value="Perfil"), \
             patch("backend.tools.painel_ia.call_llm", return_value='{"classification": "banco_talentos", "best_email": "", "score": 65, "summary": "Captação genérica."}'):
            tp = painel_ia.triar_post_recrutador(post)
        self.assertEqual(tp["classification"], "banco_talentos")
        self.assertEqual(tp["score"], 0)

        with patch("backend.tools.painel_ia.candidate_profile", return_value="Perfil"), \
             patch("backend.tools.painel_ia.call_llm", return_value='{"classification": "vaga_ativa", "verdict": "Moderate Fit"}'):
            with self.assertRaises(ValueError):
                painel_ia.triar_post_recrutador(post)

        with patch("backend.tools.painel_ia.candidate_profile", return_value="Perfil"), \
             patch("backend.tools.painel_ia.call_llm", side_effect=painel_ia.ConsentRequired("Sem consentimento")):
            with self.assertRaises(painel_ia.ConsentRequired):
                painel_ia.triar_post_recrutador(post)

    def test_save_post_as_interested_is_manual_and_skips_cv_letter_ai(self):
        post = self.service.add_pasted_post(
            raw_text="Vaga Java Angular. Enviar CV para arturo.gutierrez@ibertech.org",
            title="Fullstack Angular / Java",
            company="Ibertech",
        )
        with patch("backend.tools.painel_ia.save_job_cache") as mock_cache, \
             patch("backend.tools.painel_ia.redigir_curriculo") as mock_cv, \
             patch("backend.tools.painel_ia.redigir_carta") as mock_carta, \
             patch("backend.tools.painel_ia.call_llm") as mock_llm:
            res = self.service.save_post_as_interested(post["id"])

        self.assertTrue(res["ok"])
        mock_cache.assert_called_once()
        mock_cv.assert_not_called()
        mock_carta.assert_not_called()
        mock_llm.assert_not_called()

        # Publicação do LinkedIn permanece em Recrutadores (com job_status='interested') até exclusão manual
        remaining = self.service.list_posts(portal="linkedin_post")
        self.assertEqual([p["id"] for p in remaining], [post["id"]])
        self.assertEqual(remaining[0]["job_status"], "interested")
        saved = self.repo.list_jobs(status="interested")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["url"], f"recruiter://post/{post['id']}")
        refreshed_post = self.repo.get_recruiter_post(post["id"])
        self.assertEqual(refreshed_post["auto_promoted"], 0)
        self.assertEqual(refreshed_post["job_id"], saved[0]["id"])
        self.assertTrue(self.service.dismiss_post(post["id"]))
        self.assertEqual(self.service.list_posts(), [])

    def test_mark_post_contacted_duplicate_warning_and_reopen_roundtrip(self):
        post_1 = self.service.add_pasted_post(
            raw_text="Vaga Java Microsservicos Brasil. Enviar CV para arturo.gutierrez@ibertech.org",
            title="Fullstack Angular / Java",
            company="Ibertech",
            url="https://freehire.me/jobs/ibertech-1",
        )
        post_2 = self.service.add_pasted_post(
            raw_text="Outra vaga anunciada pelo mesmo recrutador: arturo.gutierrez@ibertech.org",
            title="Backend Java Senior",
            company="Ibertech Latam",
        )
        # Simula que post_2 já tinha triagem IA em cache
        self.repo.update_recruiter_post_ai(post_2["id"], "vaga_ativa", 85, "Strong Fit", "Boa aderência", "arturo.gutierrez@ibertech.org")

        with patch("backend.tools.painel.record_applied") as mock_csv, \
             patch("backend.tools.painel_ia.save_job_cache"), \
             patch("backend.tools.painel_ia.redigir_curriculo") as mock_cv, \
             patch("backend.tools.painel_ia.redigir_carta") as mock_carta:
            res = self.service.mark_post_contacted(post_1["id"], email="Arturo.Gutierrez@ibertech.org")

        self.assertTrue(res["ok"])
        self.assertEqual(res["contacted_email"], "arturo.gutierrez@ibertech.org")
        mock_csv.assert_called_once()
        mock_cv.assert_not_called()
        mock_carta.assert_not_called()

        # Post 1 saiu da caixa de entrada; Post 2 continua visível porém alertando sobre o mesmo e-mail
        active_posts = self.service.list_posts()
        self.assertEqual([p["id"] for p in active_posts], [post_2["id"]])
        self.assertEqual(len(active_posts[0]["previously_contacted"]), 1)
        self.assertEqual(active_posts[0]["previously_contacted"][0]["email"], "arturo.gutierrez@ibertech.org")
        self.assertEqual(active_posts[0]["previously_contacted"][0]["company"], "Ibertech")

        # Minhas Candidaturas (DB) registra canal e email
        apps = self.repo.list_applications()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["contact_channel"], "recruiter_email")
        self.assertEqual(apps[0]["contacted_email"], "arturo.gutierrez@ibertech.org")
        self.assertEqual(apps[0]["recruiter_post_id"], post_1["id"])

        # Reabrir devolve post_1 para Recrutadores e limpa alerta do post_2
        reopened = self.repo.reopen_recruiter_post_from_application(app_id=apps[0]["id"])
        self.assertIsNotNone(reopened)
        self.assertEqual(self.repo.list_applications(), [])
        restored_posts = self.service.list_posts()
        self.assertEqual({p["id"] for p in restored_posts}, {post_1["id"], post_2["id"]})
        p2_after = next(p for p in restored_posts if p["id"] == post_2["id"])
        self.assertEqual(p2_after["previously_contacted"], [])

        # sync_from_jobs não deve duplicar post sem URL externa mesmo com job.status='new'
        p2_via_no_url = self.service.add_pasted_post(
            raw_text="Vaga sem link externo dev@unica.com",
            title="Vaga Unica",
            company="Unica Co",
        )
        with patch("backend.tools.painel.record_applied"), patch("backend.tools.painel_ia.save_job_cache"):
            self.service.mark_post_contacted(p2_via_no_url["id"])
            self.repo.reopen_recruiter_post_from_application(recruiter_post_id=p2_via_no_url["id"])
            self.service.sync_from_jobs()
        unica_matches = [p for p in self.service.list_posts() if "dev@unica.com" in p["emails"]]
        self.assertEqual(len(unica_matches), 1)


class TestRecruitersApi(unittest.TestCase):
    def setUp(self):
        self.tmp_dir_obj = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp_dir_obj.cleanup)
        tmp_dir = Path(self.tmp_dir_obj.name)
        fake_root = tmp_dir / "backend"
        fake_root.mkdir(parents=True, exist_ok=True)
        fake_claude = fake_root / "documents" / "applications" / "_painel"
        fake_seen = fake_root / "job_scraper" / "seen_jobs.json"
        fake_tracker = fake_root / "documents" / "job_search_tracker.csv"
        for target, attr, val in (
            (painel, "ROOT", fake_root),
            (painel, "CLAUDE_DIR", fake_claude),
            (painel, "EVOLUTION_PATH", fake_root / "documents" / "evolucao.json"),
            (painel_ia, "PAINEL_DIR", fake_claude),
            (scrape_run, "SEEN", fake_seen),
            (scrape_run, "TRACKER", fake_tracker),
            (painel.scrape_run, "SEEN", fake_seen),
            (painel.scrape_run, "TRACKER", fake_tracker),
        ):
            p = patch.object(target, attr, val)
            p.start()
            self.addCleanup(p.stop)

        self.tmp_db = NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.repo = Repository(db_path=self.tmp_db.name)
        self.service = RecruiterService(self.repo)
        self.tracker = TrackerService(self.repo)

        app.dependency_overrides[get_repository] = lambda: self.repo
        app.dependency_overrides[get_recruiter_service] = lambda: self.service
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        self.client = TestClient(app)
        self.token = get_token()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.repo.close()
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)

    def test_api_list_empty(self):
        resp = self.client.get("/api/recruiters")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["posts"], [])

    def test_api_paste_and_list(self):
        paste_resp = self.client.post("/api/recruiters/paste", json={
            "raw_text": "Estamos contratando Desenvolvedor Python! CVs para dev@ai-company.com",
            "company": "AI Company",
        }, headers={"X-Painel-Token": self.token})
        self.assertEqual(paste_resp.status_code, 200)

    def test_api_paste_batch_requires_csrf_imports_and_wakes_recruiter_cooldown(self):
        from datetime import datetime, timezone

        ts_ms = int(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        act_id = str(ts_ms << 22)

        class _FakeAutoMode:
            def __init__(self):
                self.woken = 0
                self.queued = []
            def enqueue_recruiter_posts(self, post_ids):
                self.queued.extend(post_ids)
                self.woken += 1
                return True

        fake_auto = _FakeAutoMode()
        app.dependency_overrides[get_auto_mode] = lambda: fake_auto

        # Sem CSRF -> 403
        forbidden = self.client.post("/api/recruiters/paste-batch", json={
            "items": [{"raw_text": "Dev Angular remoto CV: rh@teste.com"}]
        })
        self.assertEqual(forbidden.status_code, 403)

        batch_resp = self.client.post("/api/recruiters/paste-batch", json={
            "items": [
                {
                    "raw_text": "Vaga 100% remota Angular/TypeScript! Envie CV para talent@angularbr.dev",
                    "company": "AngularBR",
                    "url": f"https://www.linkedin.com/feed/update/urn:li:activity:{act_id}/",
                },
                {
                    "raw_text": "Post sem nenhum endereço de contato.",
                },
            ]
        }, headers={"X-Painel-Token": self.token})
        self.assertEqual(batch_resp.status_code, 200)
        body = batch_resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["imported"], 1)
        self.assertEqual(body["invalid"], 1)
        self.assertTrue(body["auto_mode_woken"])
        self.assertEqual(fake_auto.woken, 1)
        self.assertEqual(body["posts"][0]["published_date"], "2026-11-10")
        self.assertEqual(body["posts"][0]["work_model"], "remoto")

    def test_api_contacted_enriches_applications_and_reopens(self):
        post = self.service.add_pasted_post(
            raw_text="Engenheiro Java/Angular remoto. Contato: arturo@ibertech.org",
            title="Fullstack Java/Angular",
            company="Ibertech",
        )
        sibling = self.service.add_pasted_post(
            raw_text="Segunda vaga da Ibertech: arturo@ibertech.org",
            title="Tech Lead Java",
            company="Ibertech 2",
        )
        headers = {"X-Painel-Token": self.token}

        with patch("backend.tools.painel.record_applied"), \
             patch("backend.tools.painel.remove_application"), \
             patch("backend.tools.painel.applications", return_value=[]), \
             patch("backend.tools.painel.job_pdfs", return_value={}), \
             patch("backend.tools.painel_ia.save_job_cache"):
            contacted_resp = self.client.post(
                f"/api/recruiters/{post['id']}/contacted",
                json={"email": "arturo@ibertech.org"},
                headers=headers,
            )
            self.assertEqual(contacted_resp.status_code, 200)
            payload = contacted_resp.json()
            self.assertEqual(payload["contacted_email"], "arturo@ibertech.org")

            # Sibling tem previously_contacted no GET /api/recruiters
            rec_resp = self.client.get("/api/recruiters")
            self.assertEqual(rec_resp.status_code, 200)
            rec_posts = rec_resp.json()["posts"]
            self.assertEqual([p["id"] for p in rec_posts], [sibling["id"]])
            self.assertEqual(rec_posts[0]["previously_contacted"][0]["email"], "arturo@ibertech.org")

            # GET /api/applications traz canal direto e email contatado
            apps_resp = self.client.get("/api/applications")
            self.assertEqual(apps_resp.status_code, 200)
            apps = apps_resp.json()["applications"]
            self.assertEqual(len(apps), 1)
            self.assertEqual(apps[0]["contact_channel"], "recruiter_email")
            self.assertEqual(apps[0]["contacted_email"], "arturo@ibertech.org")
            self.assertEqual(apps[0]["recruiter_post_id"], post["id"])
            self.assertIn("arturo@ibertech.org", apps[0]["recruiter_emails"])

            # Reabrir volta para Recrutadores e sai de Minhas Candidaturas
            reopen_resp = self.client.post(
                "/api/applications/reopen-recruiter",
                json={"id": apps[0]["id"]},
                headers=headers,
            )
            self.assertEqual(reopen_resp.status_code, 200)
            self.assertTrue(reopen_resp.json()["reopened"])

            apps_after = self.client.get("/api/applications").json()["applications"]
            self.assertEqual(apps_after, [])
            rec_after = self.client.get("/api/recruiters").json()["posts"]
            self.assertEqual({p["id"] for p in rec_after}, {post["id"], sibling["id"]})

    def test_api_interested_then_applied_preserves_direct_channel(self):
        post = self.service.add_pasted_post(
            raw_text="Dev Angular Pleno. CV para vagas@studio.dev",
            title="Dev Angular",
            company="Studio Dev",
        )
        headers = {"X-Painel-Token": self.token}

        with patch("backend.tools.painel.record_applied", return_value={"applied": True}), \
             patch("backend.tools.painel.applications", return_value=[]), \
             patch("backend.tools.painel.job_pdfs", return_value={}), \
             patch("backend.tools.painel_ia.save_job_cache"):
            int_resp = self.client.post(f"/api/recruiters/{post['id']}/interested", headers=headers)
            self.assertEqual(int_resp.status_code, 200)
            job_url = int_resp.json()["url"]
            self.assertTrue(job_url.startswith("recruiter://post/"))

            applied_resp = self.client.post("/api/applied", json={
                "url": job_url,
                "company": "Studio Dev",
                "role": "Dev Angular",
                "portal": "linkedin_post",
                "contact_channel": "recruiter_email",
                "contacted_email": "vagas@studio.dev",
            }, headers=headers)
            self.assertEqual(applied_resp.status_code, 200)

            apps = self.client.get("/api/applications").json()["applications"]
            self.assertEqual(len(apps), 1)
            self.assertEqual(apps[0]["contact_channel"], "recruiter_email")
            self.assertEqual(apps[0]["contacted_email"], "vagas@studio.dev")

    def test_api_dismiss_batch_requires_csrf_and_moves_only_target_ids_to_discarded(self):
        p1 = self.service.add_pasted_post(
            raw_text="Dev Java Sênior remoto. CV para rh@alpha.dev",
            title="Dev Java Sênior",
            company="Alpha Tech",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000201/",
        )
        p2 = self.service.add_pasted_post(
            raw_text="Dev Python Júnior presencial. CV para rh@alpha.dev",
            title="Dev Python Júnior",
            company="Alpha Tech",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000202/",
        )
        p3 = self.service.add_pasted_post(
            raw_text="Dev Angular Pleno híbrido. CV para talento@beta.dev",
            title="Dev Angular Pleno",
            company="Beta Soft",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000203/",
        )

        # Sem CSRF -> 403
        forbidden = self.client.post(
            "/api/recruiters/dismiss-batch",
            json={"post_ids": [p1["id"], p2["id"]]},
        )
        self.assertEqual(forbidden.status_code, 403)

        # Com CSRF -> descarta em lote p1 e p2 (incluindo deduplicação/ID inexistente), preserva p3
        resp = self.client.post(
            "/api/recruiters/dismiss-batch",
            json={"post_ids": [p1["id"], p1["id"], p2["id"], 999999]},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["dismissed_count"], 2)
        self.assertEqual(body["dismissed_ids"], [p1["id"], p2["id"]])

        # Apenas p3 permanece listado no radar; p1 e p2 foram movidos para Descartadas
        remaining = self.client.get("/api/recruiters").json()["posts"]
        self.assertEqual([p["id"] for p in remaining], [p3["id"]])
        discarded_urls = {j["url"] for j in self.client.get("/api/discarded").json()["discarded"]}
        self.assertIn(p1["url"], discarded_urls)
        self.assertIn(p2["url"], discarded_urls)
        self.assertNotIn(p3["url"], discarded_urls)

        # Segunda chamada nos mesmos IDs é idempotente
        again = self.client.post(
            "/api/recruiters/dismiss-batch",
            json={"post_ids": [p1["id"], p2["id"]]},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["dismissed_count"], 0)
        self.assertEqual(again.json()["dismissed_ids"], [])

    def test_legacy_db_adds_application_and_recruiter_outreach_columns(self):
        legacy_file = NamedTemporaryFile(suffix=".db", delete=False)
        legacy_file.close()
        migrated_repo = None
        try:
            conn = sqlite3.connect(legacy_file.name)
            conn.execute("""
                CREATE TABLE applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'preparando',
                    cv_path TEXT,
                    cover_letter_path TEXT,
                    interview_notes_path TEXT,
                    applied_date TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE recruiter_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emails TEXT NOT NULL,
                    email_context TEXT,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    portal TEXT NOT NULL,
                    url TEXT,
                    location TEXT,
                    work_model TEXT,
                    published_date TEXT,
                    description TEXT NOT NULL,
                    matched_keywords TEXT,
                    match_score INTEGER DEFAULT 0,
                    job_id TEXT,
                    dismissed INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
            conn.close()

            migrated_repo = Repository(db_path=legacy_file.name)
            app_cols = {r["name"] for r in migrated_repo.conn.execute("PRAGMA table_info(applications)").fetchall()}
            for col in ("contact_channel", "contacted_email", "recruiter_post_id"):
                self.assertIn(col, app_cols)
            rec_cols = {r["name"] for r in migrated_repo.conn.execute("PRAGMA table_info(recruiter_posts)").fetchall()}
            for col in ("contacted_email", "contacted_at"):
                self.assertIn(col, rec_cols)
        finally:
            if migrated_repo is not None:
                migrated_repo.close()
            if os.path.exists(legacy_file.name):
                os.remove(legacy_file.name)

    def test_extract_clean_emails_blocks_portuguese_placeholders(self):
        txt = "Mande para seu-email@dominio.com ou nome@empresa.com.br ou real@empresa-tech.com.br"
        self.assertEqual(extract_clean_emails(txt), ["real@empresa-tech.com.br"])

    def test_sync_from_hn_filters_replies_and_candidate_bios(self):
        story_payload = json.dumps({
            "hits": [
                {"objectID": "900", "title": "Ask HN: Who wants to be hired?"},
                {"objectID": "901", "title": "Ask HN: Who is hiring? (November 2026)"},
            ]
        }).encode("utf-8")
        comments_payload = json.dumps({
            "hits": [
                {
                    "objectID": "1",
                    "parent_id": 999,
                    "author": "replyguy",
                    "comment_text": "Hi Kiran! I just applied: reply@test-real.io",
                },
                {
                    "objectID": "2",
                    "parent_id": 901,
                    "author": "seeker",
                    "comment_text": "Location: Bangalore, India<p>Remote: Yes<p>Willing to relocate: Yes<p>Email: dev@gmail.com",
                },
                {
                    "objectID": "3",
                    "parent_id": 901,
                    "author": "acmehr",
                    "comment_text": "Acme AI | REMOTE | Junior Python Engineer<p>We're hiring! Apply: jobs@acme-ai.dev",
                },
            ]
        }).encode("utf-8")

        class _FakeResp:
            def __init__(self, body: bytes):
                self.body = body
            def read(self):
                return self.body
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=5):
            if "tags=story" in req.full_url:
                return _FakeResp(story_payload)
            return _FakeResp(comments_payload)

        collected = set()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            n = self.service.sync_from_hn("Python", _collected_urls=collected)
        self.assertEqual(n, 1)
        self.assertEqual(collected, {"https://news.ycombinator.com/item?id=3"})

    def test_sync_from_github_repos_uses_age_filter_and_ttl_cache(self):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT12:00:00Z")
        old = "2024-01-10T12:00:00Z"
        issues_payload = json.dumps([
            {
                "html_url": "https://github.com/backend-br/vagas/issues/1",
                "title": "[Remoto] Desenvolvedor Python Júnior",
                "created_at": recent,
                "user": {"login": "mkdigital"},
                "labels": [{"name": "Júnior"}, {"name": "Remoto"}],
                "body": "Vaga Python FastAPI Docker. Enviar CV para info@mkdigital.ch",
            },
            {
                "html_url": "https://github.com/backend-br/vagas/issues/2",
                "title": "[Remoto] Vaga muito antiga",
                "created_at": old,
                "user": {"login": "oldco"},
                "labels": [],
                "body": "Email antigo@oldco.com.br",
            },
        ]).encode("utf-8")

        class _FakeResp:
            def read(self):
                return issues_payload
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        calls = {"n": 0}

        def fake_urlopen(req, timeout=7):
            calls["n"] += 1
            return _FakeResp()

        collected = set()
        with patch("backend.core.recruiter_service.RECRUITER_GITHUB_REPOS", ("backend-br/vagas",)), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            n1 = self.service.sync_from_github_repos(query="Python", _collected_urls=collected)
            n2 = self.service.sync_from_github_repos(query="Python", _collected_urls=collected)

        self.assertEqual(n1, 1)
        self.assertEqual(n2, 1)
        self.assertEqual(calls["n"], 1)  # TTL cache evita re-request HTTP
        self.assertIn("https://github.com/backend-br/vagas/issues/1", collected)
        posts = self.service.list_posts(portal="github-vagas")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["work_model"], "remoto")

    def test_sync_from_remotive_and_live_portals_and_email_diversity(self):
        remotive_json = json.dumps({
            "jobs": [{
                "url": "https://remotive.com/remote-jobs/software-dev/py-1",
                "title": "Junior Python Engineer",
                "company_name": "Globex",
                "candidate_required_location": "Worldwide",
                "publication_date": "2026-11-10T10:00:00",
                "tags": ["python", "fastapi"],
                "description": "<p>Send CV to jobs@globex-remote.com</p>",
            }]
        }).encode("utf-8")

        class _FakeRemotiveResp:
            def read(self):
                return remotive_json
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        collected = set()
        with patch("urllib.request.urlopen", return_value=_FakeRemotiveResp()):
            n_rem = self.service.sync_from_remotive(query="Python", _collected_urls=collected)
        self.assertEqual(n_rem, 1)
        self.assertIn("https://remotive.com/remote-jobs/software-dev/py-1", collected)

        fake_cli_results = ([{
            "url": "https://remotar.com.br/job/r1",
            "title": "Dev Angular Pleno",
            "company": "TechBR",
            "location": "Brasil",
            "work_model": "remoto",
            "description": "Envie seu CV para rh@techbr.com.br",
        }], None)
        with patch("backend.tools.scrape_run.installed_portals", return_value={"remotar-search": True}), \
             patch("backend.tools.scrape_run.run_cli", return_value=fake_cli_results) as mock_cli:
            n_p1 = self.service.sync_from_live_portals(["Desenvolvedor Angular"], _collected_urls=collected)
            n_p2 = self.service.sync_from_live_portals(["Desenvolvedor Angular"], _collected_urls=collected)
        self.assertEqual(n_p1, 1)
        self.assertEqual(n_p2, 1)
        self.assertEqual(mock_cli.call_count, 1)  # cache de sessão respeitado

        # Adiciona 3 posts com o mesmo e-mail para testar cap de diversidade (max_per_email=2)
        for i in range(3):
            self.service.add_pasted_post(
                raw_text=f"Java Spring Boot vaga {i} enviar CV para clone@consultoria.com.br",
                url=f"https://github.com/soujava/vagas-java/issues/{100 + i}",
                title=f"Java Junior {i}",
                company="Consultoria Clone",
            )
        candidates = self.service.find_untriaged_candidates(keywords=["Desenvolvedor Angular", "Java"], max_per_email=2)
        clone_hits = [c for c in candidates if (c.get("emails") or [""])[0] == "clone@consultoria.com.br"]
        self.assertEqual(len(clone_hits), 2)
        angular_hits = [c for c in candidates if "Angular" in c["title"]]
        self.assertEqual(len(angular_hits), 1)

    def test_extract_clean_emails_filters_compliance_and_keeps_hiring(self):
        text = (
            "How to apply: send your resume to jobs@acme.dev today.\n"
            "If you require a reasonable accommodation due to a disability, contact hr@acme.dev or accommodations@acme.dev.\n"
            "You can request access or deletion of your personal data by emailing careers@story.io.\n"
            "If someone is claiming to be from OurCo, email peopleteam@ourco.com before taking any further steps."
        )
        emails = extract_clean_emails(text)
        self.assertEqual(emails, ["jobs@acme.dev"])

        # E-mail mencionado primeiro para envio de CV e depois citado no rodapé continua válido
        mixed = "Apply by sending your CV to hiring@dual.io. If you need accommodation, contact hiring@dual.io."
        self.assertEqual(extract_clean_emails(mixed), ["hiring@dual.io"])

    def test_github_sync_uses_etag_304_and_handles_rate_limit(self):
        import io
        import urllib.error
        from datetime import datetime, timezone, timedelta

        recent = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT10:00:00Z")
        payload = json.dumps([{
            "html_url": "https://github.com/phpdevbr/vagas/issues/55",
            "title": "[Remoto] Dev PHP/Laravel",
            "created_at": recent,
            "user": {"login": "phpco"},
            "labels": [{"name": "Remoto"}],
            "body": "Enviar CV para vagas@phpco.com.br",
        }]).encode("utf-8")

        class _Headers:
            def get(self, k, d=None):
                return 'W/"etag-1"' if k.lower() == "etag" else d

        class _Resp:
            headers = _Headers()
            def read(self):
                return payload
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        seen_if_none_match = []

        def fake_urlopen(req, timeout=7):
            seen_if_none_match.append(req.headers.get("If-none-match"))
            if len(seen_if_none_match) == 1:
                return _Resp()
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, io.BytesIO(b""))

        with patch("backend.core.recruiter_service.RECRUITER_GITHUB_REPOS", ("phpdevbr/vagas",)), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            n1 = self.service.sync_from_github_repos(query="PHP", cache_ttl_seconds=0)
            n2 = self.service.sync_from_github_repos(query="PHP", cache_ttl_seconds=0)

        self.assertEqual(n1, 1)
        self.assertEqual(n2, 1)
        self.assertEqual(seen_if_none_match, [None, 'W/"etag-1"'])

        # Rate limit 403 interrompe loop sem disparar requisições extras nos repositórios seguintes
        rl_calls = []

        def fake_rate_limit(req, timeout=7):
            rl_calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 403, "rate limit exceeded", {}, io.BytesIO(b""))

        status_out = {"errors": 0, "rate_limited": False}
        with patch("backend.core.recruiter_service.RECRUITER_GITHUB_REPOS", ("backend-br/vagas", "soujava/vagas-java")), \
             patch("urllib.request.urlopen", side_effect=fake_rate_limit):
            self.service.sync_from_github_repos(query="Java", cache_ttl_seconds=0, _status_out=status_out)

        self.assertEqual(len(rl_calls), 1)
        self.assertTrue(status_out["rate_limited"])
        self.assertEqual(status_out["errors"], 1)

    def test_sync_all_reports_portal_breakdown_and_remotar_international_location(self):
        fake_remotar = ([{
            "url": "https://remotar.com.br/job/intl-1",
            "title": "Angular Engineer",
            "company": "IntlCo",
            "international": True,
            "work_model": "remoto",
            "description": "Send CV to careers@intlco.dev",
        }], None)
        with patch.object(self.service, "sync_from_hn", return_value=0), \
             patch.object(self.service, "sync_from_github_repos", return_value=0), \
             patch.object(self.service, "sync_from_remotive", return_value=0), \
             patch.object(self.service, "sync_from_recent_scrapes", return_value=0), \
             patch("backend.tools.scrape_run.installed_portals", return_value={"remotar-search": True}), \
             patch("backend.tools.scrape_run.run_cli", return_value=fake_remotar):
            res = self.service.sync_all(query="Angular")

        self.assertEqual(res["portal_breakdown"]["remotar-search"]["matched"], 1)
        posts = self.service.list_posts(portal="remotar-search")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["location"], "Remoto / Internacional")

    def test_extract_linkedin_snowflake_date_and_batch_dedup(self):
        from datetime import datetime, timezone

        ts_ms = int(datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc).timestamp() * 1000)
        act_id = str(ts_ms << 22)
        post_url = f"https://pt.linkedin.com/posts/alguem_vaga-dev-activity-{act_id}-xYz1"
        feed_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{act_id}/"

        self.assertEqual(extract_linkedin_snowflake_date(post_url), "2026-11-08")
        self.assertEqual(extract_linkedin_snowflake_date(feed_url), "2026-11-08")
        self.assertIsNone(extract_linkedin_snowflake_date("https://linkedin.com/jobs/view/123"))

        payload = "VAGAMUNDO_LI_BATCH_V1:" + json.dumps({
            "v": 1,
            "posts": [
                {
                    "text": "Hiring Python/FastAPI Dev! Email: careers@pyco.dev",
                    "author": "PyCo",
                    "url": post_url,
                },
                {
                    "text": "Post sem email",
                },
            ],
        })
        r1 = self.service.add_pasted_posts_batch(raw_batch_text=payload)
        self.assertEqual(r1["imported"], 1)
        self.assertEqual(r1["invalid"], 1)
        self.assertEqual(r1["posts"][0]["published_date"], "2026-11-08")

        # Mesmo post em formato URL diferente (/feed/update/urn:li:activity:...) deve ser deduplicado e não ressuscitado após dismiss
        self.service.dismiss_post(r1["posts"][0]["id"])
        r2 = self.service.add_pasted_posts_batch(items=[{
            "raw_text": "Hiring Python/FastAPI Dev! Email: careers@pyco.dev",
            "url": feed_url,
            "company": "PyCo",
        }])
        self.assertEqual(r2["imported"], 0)
        self.assertEqual(r2["skipped"], 1)
        self.assertEqual(self.service.list_posts(), [])

    def test_find_untriaged_candidates_includes_imported_linkedin_across_keywords(self):
        self.service.add_pasted_post(
            raw_text="Vaga Rust Systems Developer! Enviar CV para rust@core.dev",
            company="CoreRust",
            title="Rust Developer",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7525862923169132544/",
        )
        # Sem include_portals: rodada sorteou 'Angular', logo 'Rust' fica de fora
        without_portal = self.service.find_untriaged_candidates(keywords=["Angular"])
        self.assertEqual(without_portal, [])

        # Com include_portals=('linkedin_post',): entra imediatamente na rodada multiplataforma
        with_portal = self.service.find_untriaged_candidates(
            keywords=["Angular"],
            include_portals=("linkedin_post",),
        )
        self.assertEqual(len(with_portal), 1)
        self.assertEqual(with_portal[0]["portal"], "linkedin_post")
        self.assertEqual(with_portal[0]["company"], "CoreRust")

    def test_github_sync_persists_disk_cache_and_pauses_repeat_403_calls(self):
        import io
        import time
        import urllib.error
        from datetime import datetime, timezone, timedelta
        from tempfile import TemporaryDirectory

        recent = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT10:00:00Z")
        payload = json.dumps([{
            "html_url": "https://github.com/datascience-br/vagas/issues/99",
            "title": "[Remoto] Cientista de Dados",
            "created_at": recent,
            "user": {"login": "dsbr"},
            "labels": [{"name": "Remoto"}],
            "body": "Enviar currículo para talento@dsbr.org",
        }]).encode("utf-8")

        class _Headers:
            def get(self, k, d=None):
                lk = k.lower()
                if lk == "etag":
                    return 'W/"ds-1"'
                if lk == "x-ratelimit-remaining":
                    return "5"
                return d

        class _Resp:
            headers = _Headers()
            def read(self):
                return payload
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        with TemporaryDirectory() as tmpdir:
            svc1 = RecruiterService(self.repo, cache_dir=Path(tmpdir))
            with patch("backend.core.recruiter_service.RECRUITER_GITHUB_REPOS", ("datascience-br/vagas",)), \
                 patch("urllib.request.urlopen", return_value=_Resp()):
                n1 = svc1.sync_from_github_repos(query="Dados", cache_ttl_seconds=1200)
            self.assertEqual(n1, 1)
            self.assertTrue((Path(tmpdir) / "github_vagas_cache.json").is_file())

            # Nova instância carrega cache/ETag em disco sem gastar cota do GitHub
            svc2 = RecruiterService(self.repo, cache_dir=Path(tmpdir))
            with patch("backend.core.recruiter_service.RECRUITER_GITHUB_REPOS", ("datascience-br/vagas",)), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("Não deveria consultar API")):
                n2 = svc2.sync_from_github_repos(query="Dados", cache_ttl_seconds=1200)
            self.assertEqual(n2, 1)

            # Após 403 com X-RateLimit-Reset futuro, próximas chamadas não martelam a API
            reset_future = str(int(time.time() + 600))
            rl_calls = []

            def fake_403(req, timeout=7):
                rl_calls.append(req.full_url)
                raise urllib.error.HTTPError(
                    req.full_url, 403, "rate limit exceeded", {"X-RateLimit-Reset": reset_future}, io.BytesIO(b"")
                )

            svc3 = RecruiterService(self.repo, cache_dir=Path(tmpdir))
            status_1 = {"errors": 0, "rate_limited": False, "warnings": []}
            status_2 = {"errors": 0, "rate_limited": False, "warnings": []}
            with patch("backend.core.recruiter_service.RECRUITER_GITHUB_REPOS", ("pydevbr/vagas",)), \
                 patch("urllib.request.urlopen", side_effect=fake_403):
                svc3.sync_from_github_repos(query="Python", cache_ttl_seconds=1200, _status_out=status_1)
                svc3.sync_from_github_repos(query="Python", cache_ttl_seconds=1200, _status_out=status_2)

            self.assertEqual(len(rl_calls), 1)
            self.assertTrue(any("pausa temporária" in w for w in status_2["warnings"]))
            self.assertFalse(status_2["rate_limited"])

    def test_obfuscated_emails_and_relative_age_date_fallback(self):
        from datetime import date, timedelta

        extracted = extract_clean_emails(
            "Envie CV para talentos [arroba] nuvem (ponto) com (dot) br ou ana(at)corp[dot]io"
        )
        self.assertEqual(extracted, ["talentos@nuvem.com.br", "ana@corp.io"])

        batch = self.service.add_pasted_posts_batch([
            {
                "raw_text": "Vaga Java Sênior! Contato: hiring [arroba] cloudstack (ponto) dev",
                "company": "CloudStack",
                "posted_age_text": "3 d",
            },
            {
                "raw_text": "Dev Angular remoto! CV: rh(at)front[dot]io",
                "company": "FrontIO",
                "posted_age_text": "4 h",
            },
        ])
        self.assertEqual(batch["imported"], 2)
        posts_by_company = {p["company"]: p for p in self.service.list_posts()}
        self.assertEqual(posts_by_company["CloudStack"]["emails"], ["hiring@cloudstack.dev"])
        self.assertEqual(
            posts_by_company["CloudStack"]["published_date"],
            (date.today() - timedelta(days=3)).isoformat(),
        )
        self.assertEqual(posts_by_company["FrontIO"]["emails"], ["rh@front.io"])
        self.assertEqual(posts_by_company["FrontIO"]["published_date"], date.today().isoformat())

    def test_save_post_as_interested_never_fakes_rank_score_and_persists_ai_eval_when_triaged(self):
        from tempfile import TemporaryDirectory

        with patch("backend.core.recruiter_service.match_cv_keywords", return_value=(["Python", "SQL"], 74)):
            untriaged = self.service.add_pasted_post(
                raw_text="Vaga Python Pleno remoto! CV: jobs@untriaged.dev",
                title="Python Pleno",
                company="Untriaged Corp",
                url="https://www.linkedin.com/feed/update/urn:li:activity:7500000000000000001/",
            )
            triaged = self.service.add_pasted_post(
                raw_text="Vaga Java/Angular! CV: jobs@triaged.dev",
                title="Java/Angular Dev",
                company="Triaged Corp",
                url="https://www.linkedin.com/feed/update/urn:li:activity:7500000000000000002/",
            )

        self.repo.update_recruiter_post_ai(
            triaged["id"],
            "vaga_ativa",
            86,
            "Strong Fit",
            "Boa aderência técnica.",
            "jobs@triaged.dev",
            ai_model="gemini-test",
        )

        with TemporaryDirectory() as tmpdir, \
             patch("backend.tools.painel_ia.PAINEL_DIR", Path(tmpdir)), \
             patch("backend.tools.painel_ia.save_job_cache"):
            self.service.save_post_as_interested(untriaged["id"])
            self.service.save_post_as_interested(triaged["id"])

            saved_jobs = {j["company"]: j for j in self.repo.list_jobs(status="interested")}
            # Untriaged post must NOT copy keyword match_score (74) as rank_score
            u_job = saved_jobs["Untriaged Corp"]
            self.assertIsNone(u_job["rank_score"])
            self.assertIsNone(u_job["rank_verdict"])
            self.assertEqual(self.repo.get_latest_evaluation_details([u_job["id"]]), {})

            # AI-triaged post MUST copy real score/verdict + evaluation record + markdown
            t_job = saved_jobs["Triaged Corp"]
            self.assertEqual(t_job["rank_score"], 86)
            self.assertEqual(t_job["rank_verdict"], "Strong Fit")
            ev_row = self.repo.conn.execute(
                "SELECT score_global, verdict, ai_provider FROM evaluations WHERE job_id = ?",
                (t_job["id"],),
            ).fetchone()
            self.assertIsNotNone(ev_row)
            self.assertEqual(ev_row["score_global"], 86)
            self.assertEqual(ev_row["verdict"], "Strong Fit")
            self.assertEqual(ev_row["ai_provider"], "gemini-test")
            self.assertIn(t_job["id"], self.repo.get_latest_evaluation_details([t_job["id"]]))
            md_files = list(Path(tmpdir).glob("*_avaliacao.md"))
            self.assertEqual(len(md_files), 1)
            self.assertIn("86/100", md_files[0].read_text(encoding="utf-8"))

    def test_api_recruiters_triage_evaluates_linkedin_posts_and_handles_missing_consent(self):
        post = self.service.add_pasted_post(
            raw_text="Vaga Java & Angular! Enviar currículo para talento@linkedintech.dev",
            title="Engenheiro Java/Angular",
            company="LinkedInTech",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7500000000000000009/",
        )
        headers = {"X-Painel-Token": self.token}

        no_csrf = self.client.post("/api/recruiters/triage", json={"portal": "linkedin_post"})
        self.assertEqual(no_csrf.status_code, 403)

        with patch("backend.core.recruiter_service.ai_providers.load_env_file", return_value={}), \
             patch("backend.core.recruiter_service.ai_providers.has_consent", return_value=False):
            no_consent = self.client.post("/api/recruiters/triage", json={"portal": "linkedin_post"}, headers=headers)
            self.assertEqual(no_consent.status_code, 400)

        with patch("backend.core.recruiter_service.ai_providers.load_env_file", return_value={"AI_CONSENT": "1"}), \
             patch("backend.core.recruiter_service.ai_providers.has_consent", return_value=True), \
             patch("backend.tools.painel_ia.is_available", return_value=True), \
             patch("backend.tools.painel_ia.get_active_model_name", return_value="gemini-triage"), \
             patch("backend.tools.painel_ia.triar_post_recrutador", return_value={
                 "classification": "vaga_ativa",
                 "best_email": "talento@linkedintech.dev",
                 "score": 88,
                 "verdict": "Strong Fit",
                 "summary": "Stack Java e Angular compatível.",
                 "ai_model": "gemini-triage",
             }):
            ok_resp = self.client.post(
                "/api/recruiters/triage",
                json={"post_ids": [post["id"]], "portal": "linkedin_post"},
                headers=headers,
            )

        self.assertEqual(ok_resp.status_code, 200)
        body = ok_resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["triaged"], 1)
        self.assertEqual(body["active_jobs"], 1)
        self.assertEqual(len(body["posts"]), 1)
        self.assertEqual(body["posts"][0]["ai_score"], 88)
        self.assertEqual(body["posts"][0]["ai_verdict"], "Strong Fit")
        self.assertEqual(body["posts"][0]["portal"], "linkedin_post")

        refreshed = self.repo.get_recruiter_post(post["id"])
        self.assertEqual(refreshed["ai_score"], 88)
        self.assertIsNotNone(refreshed["ai_evaluated_at"])

    def test_linkedin_posts_remain_listed_until_manual_dismiss_and_only_cv_uses_local_ai_score(self):
        p_promoted = self.service.add_pasted_post(
            raw_text="Vaga Java Angular Pleno remota! Enviar CV para selecao@promovida.dev",
            title="Dev Java Angular Pleno",
            company="Promovida Tech",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000001/",
        )
        p_low = self.service.add_pasted_post(
            raw_text="Vaga Java Angular Sênior 15 anos. Contato: senior@outra.dev",
            title="Arquiteto Java Angular",
            company="Outra Tech",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000002/",
        )
        p_pool = self.service.add_pasted_post(
            raw_text="Banco de talentos Python/Angular. Envie currículo para talentos@pool.dev",
            title="Banco de Talentos TI",
            company="Pool Corp",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000003/",
        )

        # Auto-promoção de p_promoted para Me Interessam mantém registro na lista do LinkedIn
        with patch("backend.tools.painel_ia.save_job_cache"):
            self.service.promote_post_to_interested(
                p_promoted,
                run_id="run-1",
                score=85,
                verdict="Strong Fit",
                summary="Ótima aderência.",
                best_email="selecao@promovida.dev",
                ai_model="ollama-local",
            )
        self.repo.update_recruiter_post_ai(
            p_promoted["id"], "vaga_ativa", 85, "Strong Fit", "Ótima aderência.", "selecao@promovida.dev", ai_model="ollama-local"
        )
        self.repo.update_recruiter_post_ai(
            p_low["id"], "vaga_ativa", 40, "Weak Fit", "Score abaixo do mínimo.", "senior@outra.dev", ai_model="ollama-local"
        )

        def fake_triar(post):
            return {
                "classification": "banco_talentos",
                "best_email": "talentos@pool.dev",
                "score": 25,
                "verdict": "Banco de talentos",
                "summary": "Captação para banco sem vaga específica.",
                "ai_model": "ollama-local",
            }

        with patch("backend.core.recruiter_service.ai_providers.load_env_file", return_value={"AI_CONSENT": "1"}), \
             patch("backend.core.recruiter_service.ai_providers.has_consent", return_value=True), \
             patch("backend.tools.painel_ia.is_available", return_value=True), \
             patch("backend.tools.painel_ia.triar_post_recrutador", side_effect=fake_triar):
            triage_res = self.service.triage_posts(post_ids=[p_pool["id"]], portal="linkedin_post")

        self.assertEqual(triage_res["talent_pools_discarded"], 1)
        self.assertEqual([p["id"] for p in triage_res["posts"]], [p_pool["id"]])
        self.assertEqual(self.repo.get_recruiter_post(p_pool["id"])["dismissed"], 0)

        all_li = self.service.list_posts(portal="linkedin_post")
        by_id = {p["id"]: p for p in all_li}
        self.assertEqual(set(by_id.keys()), {p_promoted["id"], p_low["id"], p_pool["id"]})
        self.assertEqual(by_id[p_promoted["id"]]["auto_promoted"], 1)
        self.assertEqual(by_id[p_promoted["id"]]["job_status"], "interested")
        self.assertEqual(by_id[p_pool["id"]]["ai_classification"], "banco_talentos")
        self.assertEqual(by_id[p_pool["id"]]["ai_score"], 25)

        # only_cv=True respeita exclusivamente nota >= 60 da IA local após avaliação
        cv_only = self.service.list_posts(only_cv=True, portal="linkedin_post")
        self.assertEqual([p["id"] for p in cv_only], [p_promoted["id"]])

        # Exclusão manual remove definitivamente da lista
        self.service.dismiss_post(p_promoted["id"])
        self.service.dismiss_post(p_pool["id"])
        remaining_ids = [p["id"] for p in self.service.list_posts(portal="linkedin_post")]
        self.assertEqual(remaining_ids, [p_low["id"]])

    def test_dismiss_to_discarded_blocks_same_vacancy_without_blocking_other_jobs_same_email(self):
        vaga_java = self.service.add_pasted_post(
            raw_text="Vaga Desenvolvedor Java Sênior com Spring Boot e Kafka. Envie CV para rh@consultoria.dev",
            title="Desenvolvedor Java Sênior",
            company="Consultoria Dev",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000101/",
        )
        self.assertTrue(self.service.dismiss_post(vaga_java["id"]))
        discarded = self.client.get("/api/discarded").json()["discarded"]
        self.assertEqual([d["url"] for d in discarded], [vaga_java["url"]])
        self.assertEqual(discarded[0]["recruiter_emails"], ["rh@consultoria.dev"])

        batch_res = self.service.add_pasted_posts_batch(
            [
                {
                    "raw_text": "Vaga Desenvolvedor Java Sênior com Spring Boot e Kafka. Envie CV para rh@consultoria.dev",
                    "title": "Desenvolvedor Java Sênior",
                    "company": "Consultoria Dev",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000102/",
                },
                {
                    "raw_text": "Nova vaga Engenheiro de Dados Pleno com Spark, Airflow e SQL. Contato: rh@consultoria.dev",
                    "title": "Engenheiro de Dados Pleno",
                    "company": "Consultoria Dev",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000103/",
                },
            ],
            allow_without_email=False,
        )

        self.assertEqual(batch_res["skipped"], 1)
        self.assertEqual(batch_res["imported"], 1)
        listed = self.service.list_posts(portal="linkedin_post")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["title"], "Engenheiro de Dados Pleno")
        self.assertEqual(listed[0]["emails"], ["rh@consultoria.dev"])

    def test_dismiss_posts_batch_preserves_limbo_reimport_block(self):
        v1 = self.service.add_pasted_post(
            raw_text="Vaga Node.js Sênior com TypeScript e PostgreSQL. Envie CV para jobs@nodecorp.dev",
            title="Vaga Node.js Sênior",
            company="NodeCorp",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000301/",
        )
        v2 = self.service.add_pasted_post(
            raw_text="Vaga QA Automação Cypress/Playwright. Envie CV para qa@nodecorp.dev",
            title="QA Automação",
            company="NodeCorp",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000302/",
        )

        dismissed = self.service.dismiss_posts([v1["id"], v2["id"]])
        self.assertEqual(dismissed, [v1["id"], v2["id"]])
        self.assertEqual(self.service.list_posts(portal="linkedin_post"), [])

        # Reimportar a mesma vaga já descartada em lote continua bloqueado em Descartadas
        reimport = self.service.add_pasted_posts_batch(
            [
                {
                    "raw_text": "Vaga Node.js Sênior com TypeScript e PostgreSQL. Envie CV para jobs@nodecorp.dev",
                    "title": "Vaga Node.js Sênior",
                    "company": "NodeCorp",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000399/",
                }
            ],
            allow_without_email=False,
        )
        self.assertEqual(reimport["skipped"], 1)
        self.assertEqual(reimport["imported"], 0)

    def test_dismiss_moves_to_discarded_restore_returns_and_applied_stays_protected(self):
        p_norm = self.service.add_pasted_post(
            raw_text="Dev Spring Boot Sênior. Envie CV para vagas@disc-norm.dev",
            title="Dev Spring Boot Sênior",
            company="SpringCo",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000701/",
        )
        headers = {"X-Painel-Token": self.token}
        del_resp = self.client.delete(f"/api/recruiters/{p_norm['id']}", headers=headers)
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(self.service.list_posts(portal="linkedin_post"), [])

        discarded = self.client.get("/api/discarded").json()["discarded"]
        self.assertEqual(len(discarded), 1)
        self.assertEqual(discarded[0]["url"], p_norm["url"])
        self.assertEqual(discarded[0]["recruiter_emails"], ["vagas@disc-norm.dev"])

        # Restaurar em Descartadas devolve para Me Interessam e tira de Descartadas
        restore_resp = self.client.post("/api/restore", json={"url": p_norm["url"]}, headers=headers)
        self.assertEqual(restore_resp.status_code, 200)
        self.assertEqual(self.client.get("/api/discarded").json()["discarded"], [])
        restored_job = self.repo.get_job_by_url(p_norm["url"])
        self.assertIsNotNone(restored_job)
        self.assertEqual(restored_job["status"], "interested")

        # Post já aplicado/contacted não tem status rebaixado para discarded ao ser ocultado
        p_applied = self.service.add_pasted_post(
            raw_text="Dev Kotlin Pleno. Envie CV para jobs@kotlincorp.dev",
            title="Dev Kotlin Pleno",
            company="KotlinCorp",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000702/",
        )
        self.service.mark_post_contacted(p_applied["id"], email="jobs@kotlincorp.dev")
        self.assertTrue(self.service.dismiss_post(p_applied["id"]))
        self.assertEqual(self.client.get("/api/discarded").json()["discarded"], [])
        applied_job = self.repo.get_job_by_url(p_applied["url"])
        self.assertIsNotNone(applied_job)
        self.assertEqual(applied_job["status"], "applied")

    def test_api_sync_runs_all_platforms_simultaneously_and_tracks_round_matched_post_ids(self):
        unrelated = self.service.add_pasted_post(
            raw_text="Vaga PHP antiga em cache. Envie CV para php@old.dev",
            title="PHP Sênior",
            company="OldPHP",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000501/",
        )
        dismissed_job = {
            "id": "job-ang-dismissed",
            "title": "Angular Descartada",
            "company": "TrashCo",
            "url": "https://remotar.com.br/job/ang-trash",
            "portal": "remotar-search",
            "description": "Vaga descartada anteriormente Angular. CV para trash@li.dev",
            "status": "new",
        }
        evaluated_job = {
            "id": "job-ang-evaluated",
            "title": "Angular Já Avaliada",
            "company": "EvalCo",
            "url": "https://remotar.com.br/job/ang-evaluated",
            "portal": "remotar-search",
            "description": "Vaga Angular já avaliada! Envie CV para evaluated@li.dev",
            "status": "new",
        }
        self.repo.upsert_job(dismissed_job)
        self.repo.upsert_job(evaluated_job)
        self.service.sync_from_jobs(query="Angular")
        by_url_initial = {p.get("url"): p for p in self.service.list_posts()}
        dismissed_post = by_url_initial[dismissed_job["url"]]
        evaluated_post = by_url_initial[evaluated_job["url"]]
        self.service.dismiss_post(dismissed_post["id"])

        self.repo.update_recruiter_post_ai(
            evaluated_post["id"],
            "vaga_ativa",
            85,
            "Strong Fit",
            "Compatível.",
            "evaluated@li.dev",
        )

        # Post manual do LinkedIn importado via /paste continua disponível e aparece na lista
        headers = {"X-Painel-Token": self.token}
        paste_resp = self.client.post(
            "/api/recruiters/paste",
            json={
                "raw_text": "Vaga Angular Pleno no LinkedIn! CV para novo@li.dev",
                "company": "NewLICo",
                "title": "Angular Pleno",
                "url": "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000504/",
            },
            headers=headers,
        )
        self.assertEqual(paste_resp.status_code, 200)
        new_li_id = paste_resp.json()["post"]["id"]

        fake_remotar = ([
            {
                "url": "https://remotar.com.br/job/ang-sync-1",
                "title": "Dev Angular Remoto",
                "company": "RemotarCorp",
                "work_model": "remoto",
                "description": "Envie CV para jobs@remotarcorp.dev",
            },
            {
                "url": "https://remotar.com.br/job/java-other",
                "title": "Dev Java Sênior",
                "company": "JavaCorp",
                "work_model": "remoto",
                "description": "Envie CV para jobs@javacorp.dev",
            },
        ], None)

        with patch.object(self.service, "sync_from_hn", return_value=0) as hn_mock, \
             patch.object(self.service, "sync_from_github_repos", return_value=0) as gh_mock, \
             patch.object(self.service, "sync_from_remotive", return_value=0) as rem_mock, \
             patch.object(self.service, "sync_from_recent_scrapes", return_value=0), \
             patch("backend.tools.scrape_run.installed_portals", return_value={"remotar-search": True}), \
             patch("backend.tools.scrape_run.run_cli", return_value=fake_remotar):
            resp = self.client.post("/api/recruiters/sync?q=Angular", headers=headers)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(hn_mock.called)
        self.assertTrue(gh_mock.called)
        self.assertTrue(rem_mock.called)

        listed_by_url = {p.get("url"): p for p in self.service.list_posts()}
        rem_ang = listed_by_url["https://remotar.com.br/job/ang-sync-1"]
        rem_java = listed_by_url["https://remotar.com.br/job/java-other"]
        self.assertIn("https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000504/", listed_by_url)
        self.assertEqual(listed_by_url["https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000504/"]["id"], new_li_id)

        matched_ids = set(data["matched_post_ids"])
        self.assertIn(evaluated_post["id"], matched_ids)  # Reencontrada ativa sem re-triar
        self.assertIn(rem_ang["id"], matched_ids)
        self.assertNotIn(dismissed_post["id"], matched_ids)  # Descartada/oculta nunca vaza
        self.assertNotIn(unrelated["id"], matched_ids)       # Post antigo PHP fora da busca
        self.assertNotIn(rem_java["id"], matched_ids)        # Java do Remotar não casa 'Angular'
        self.assertNotIn(evaluated_post["id"], data["collected_post_ids"])

    def test_move_between_interested_and_discarded_preserves_triage_metadata_and_subscores(self):
        from tempfile import TemporaryDirectory
        from backend.core.tracker import TrackerService
        from backend.tools import painel

        post = self.service.add_pasted_post(
            raw_text="Vaga Python Pleno remota! Envie CV para rh@preserve-triage.dev",
            title="Dev Python Pleno",
            company="PreserveTech",
            location="São Paulo, SP",
            work_model="remoto",
            published_date="2026-11-12",
            url="https://freehire.me/jobs/preserve-triage-1",
        )
        self.repo.update_recruiter_post_ai(
            post["id"],
            "vaga_ativa",
            82,
            "Strong Fit",
            "Excelente encaixe com Python e APIs.",
            "rh@preserve-triage.dev",
            ai_model="gemini-3-flash-preview",
        )

        # Simula vaga que já tinha subnotas detalhadas antes de nova movimentação
        jid = self.repo.upsert_job({
            "title": post["title"],
            "company": post["company"],
            "url": post["url"],
            "status": "new",
            "source": "recruiter_radar",
        })
        self.repo.insert_evaluation({
            "job_id": jid,
            "score_technical": 88,
            "score_experience": 80,
            "score_behavioral": 78,
            "score_location": "PASS",
            "score_career": 82,
            "score_global": 82,
            "verdict": "Strong Fit",
            "language_gate": "PASS",
            "strengths": ["Python sólido"],
            "gaps": ["Ajustar stack auxiliar"],
            "report_md": "Excelente encaixe com Python e APIs.",
            "ai_provider": "gemini-3-flash-preview",
        })

        headers = {"X-Painel-Token": self.token}
        with TemporaryDirectory() as tmpdir, \
             patch("backend.tools.painel_ia.PAINEL_DIR", Path(tmpdir)), \
             patch("backend.tools.painel.CLAUDE_DIR", Path(tmpdir)), \
             patch("backend.tools.painel_ia.save_job_cache"), \
             patch("backend.tools.painel.saved", return_value=[]), \
             patch("backend.tools.painel.discarded", return_value=[]), \
             patch("backend.tools.painel.discard_job", return_value={"discarded": True}), \
             patch("backend.tools.painel.restore_job"):
            # 1) Mover para Me Interessam sem perder subnotas/localidade/modelo/resumo/e-mail
            res_int = self.client.post(f"/api/recruiters/{post['id']}/interested", headers=headers)
            self.assertEqual(res_int.status_code, 200)

            tracker = TrackerService(self.repo)
            saved_rows = tracker.list_enriched_saved_jobs()
            self.assertEqual(len(saved_rows), 1)
            saved = saved_rows[0]
            self.assertEqual(saved["url"], "https://freehire.me/jobs/preserve-triage-1")
            self.assertEqual(saved["location"], "São Paulo, SP")
            self.assertEqual(saved["work_model"], "remoto")
            self.assertEqual(saved["posted_date"], "2026-11-12")
            self.assertEqual(saved["recruiter_emails"], ["rh@preserve-triage.dev"])
            self.assertEqual(saved["screening"]["score"], 82)
            self.assertEqual(saved["screening"]["verdict"], "Strong Fit")
            self.assertEqual(saved["screening"]["ai_model"], "gemini-3-flash-preview")
            self.assertIn("Excelente encaixe", saved["screening"]["summary"])
            self.assertEqual(saved["screening"]["subscores"]["technical"], 88)
            self.assertEqual(saved["screening"]["strengths"], ["Python sólido"])

            # 2) Mover para Descartadas -> preserva triagem e subnotas em Descartadas
            res_del = self.client.delete(f"/api/recruiters/{post['id']}", headers=headers)
            self.assertEqual(res_del.status_code, 200)
            disc_rows = tracker.list_enriched_discarded_jobs()
            self.assertEqual(len(disc_rows), 1)
            disc = disc_rows[0]
            self.assertEqual(disc["url"], "https://freehire.me/jobs/preserve-triage-1")
            self.assertEqual(disc["recruiter_emails"], ["rh@preserve-triage.dev"])
            self.assertEqual(disc["screening"]["score"], 82)
            self.assertEqual(disc["screening"]["subscores"]["technical"], 88)
            self.assertEqual(disc["screening"]["ai_model"], "gemini-3-flash-preview")

            # 3) Restaurar de Descartadas -> retorna a Me Interessam com toda a referência de triagem íntegra
            tracker.restore_by_url(post["url"])
            restored_rows = tracker.list_enriched_saved_jobs()
            self.assertEqual(len(restored_rows), 1)
            self.assertEqual(restored_rows[0]["screening"]["score"], 82)
            self.assertEqual(restored_rows[0]["screening"]["subscores"]["technical"], 88)
            self.assertEqual(restored_rows[0]["recruiter_emails"], ["rh@preserve-triage.dev"])

    def test_non_linkedin_promoted_and_talent_pool_posts_stay_visible_and_in_matched_ids(self):
        from backend.core.recruiter_service import RecruiterService

        svc = RecruiterService(self.repo, enable_live_feeds=False)
        seed_jobs = [
            {
                "id": "ext-fh-1",
                "title": "Dev Python Backend",
                "company": "FreeHireCo",
                "url": "https://freehire.me/jobs/py-ext-1",
                "portal": "freehire-search",
                "description": "Vaga Python remota. Enviar CV para rh@freehireco.dev",
                "status": "new",
            },
            {
                "id": "ext-hn-1",
                "title": "Python Distributed Systems",
                "company": "HNStartup",
                "url": "https://news.ycombinator.com/item?id=88001122",
                "portal": "hn-search",
                "description": "Python and SQL backend role. Email hiring@hnstartup.dev",
                "status": "new",
            },
            {
                "id": "ext-solides-1",
                "title": "Engenheiro Python",
                "company": "SolidesTech",
                "url": "https://vagas.solides.com.br/vaga/8801",
                "portal": "solides-search",
                "description": "Vaga Python Brasil. CV para vagas@solidestech.com.br",
                "status": "new",
            },
            {
                "id": "ext-solides-pool",
                "title": "Banco de Talentos Python",
                "company": "SolidesPool",
                "url": "https://vagas.solides.com.br/vaga/8802",
                "portal": "solides-search",
                "description": "Banco de talentos Python contínuo. CV para talentos@solidespool.com.br",
                "status": "new",
            },
        ]
        for job in seed_jobs:
            self.repo.upsert_job(job)

        svc.sync_from_jobs(query="Python")
        by_url = {p["url"]: p for p in svc.list_posts()}
        fh_id = by_url["https://freehire.me/jobs/py-ext-1"]["id"]
        hn_id = by_url["https://news.ycombinator.com/item?id=88001122"]["id"]
        sol_id = by_url["https://vagas.solides.com.br/vaga/8801"]["id"]
        pool_id = by_url["https://vagas.solides.com.br/vaga/8802"]["id"]

        def fake_triar(post):
            if post["id"] == pool_id:
                return {
                    "classification": "banco_talentos",
                    "best_email": "talentos@solidespool.com.br",
                    "score": 0,
                    "verdict": "Poor Fit",
                    "summary": "Banco de talentos contínuo.",
                    "ai_model": "gemini-test",
                }
            return {
                "classification": "vaga_ativa",
                "best_email": post["emails"][0],
                "score": 87,
                "verdict": "Strong Fit",
                "summary": "Compatível com Python.",
                "ai_model": "gemini-test",
            }

        headers = {"X-Painel-Token": self.token}
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir, \
             patch("backend.tools.painel_ia.PAINEL_DIR", Path(tmpdir)), \
             patch("backend.tools.painel.CLAUDE_DIR", Path(tmpdir)), \
             patch("backend.tools.painel_ia.save_job_cache"), \
             patch("backend.tools.painel.saved", return_value=[]), \
             patch("backend.tools.painel.discarded", return_value=[]), \
             patch("backend.tools.painel.discard_job", return_value={"discarded": True}), \
             patch("backend.tools.painel.restore_job"), \
             patch("backend.core.recruiter_service.ai_providers.load_env_file", return_value={"AI_CONSENT": "1"}), \
             patch("backend.core.recruiter_service.ai_providers.has_consent", return_value=True), \
             patch("backend.tools.painel_ia.is_available", return_value=True), \
             patch("backend.tools.painel_ia.get_active_model_name", return_value="gemini-test"), \
             patch("backend.tools.painel_ia.triar_post_recrutador", side_effect=fake_triar):
            triage_res = svc.triage_posts(post_ids=[fh_id, hn_id, sol_id, pool_id])
            self.assertEqual(triage_res["triaged"], 4)
            self.assertEqual(triage_res["active_jobs"], 3)
            self.assertEqual(triage_res["talent_pools_discarded"], 1)
            pool_item = next(p for p in triage_res["posts"] if p["id"] == pool_id)
            self.assertFalse(pool_item.get("auto_dismissed", False))
            self.assertEqual(pool_item["dismissed"], 0)
            self.assertEqual(self.repo.get_recruiter_post(pool_id)["dismissed"], 0)

            # Promote/save non-LinkedIn active jobs (auto_promoted + manual interested)
            fh_row = self.repo.get_recruiter_post(fh_id)
            hn_row = self.repo.get_recruiter_post(hn_id)
            svc.promote_post_to_interested(
                fh_row, "auto-run-1", 87, "Strong Fit", "Compatível.", "rh@freehireco.dev", ai_model="gemini-test"
            )
            svc.promote_post_to_interested(
                hn_row, "auto-run-1", 87, "Strong Fit", "Compatível.", "hiring@hnstartup.dev", ai_model="gemini-test"
            )
            res_sol = self.client.post(f"/api/recruiters/{sol_id}/interested", headers=headers)
            self.assertEqual(res_sol.status_code, 200)

            visible = self.client.get("/api/recruiters").json()["posts"]
            vis_by_id = {p["id"]: p for p in visible}
            for pid in (fh_id, hn_id, sol_id, pool_id):
                self.assertIn(pid, vis_by_id)
            self.assertEqual(vis_by_id[fh_id]["auto_promoted"], 1)
            self.assertEqual(vis_by_id[hn_id]["auto_promoted"], 1)
            self.assertEqual(vis_by_id[fh_id]["job_status"], "interested")
            self.assertEqual(vis_by_id[hn_id]["job_status"], "interested")
            self.assertEqual(vis_by_id[sol_id]["job_status"], "interested")

            with patch.object(svc, "sync_from_live_portals", return_value=0), \
                 patch.object(svc, "sync_from_recent_scrapes", return_value=0):
                sync_res = svc.sync_all(query="Python")
            for pid in (fh_id, hn_id, sol_id, pool_id):
                self.assertIn(pid, sync_res["matched_post_ids"])

            # Manual dismiss removes explicitly dismissed external post without affecting others
            self.assertTrue(svc.dismiss_post(fh_id))
            after_dismiss_ids = [p["id"] for p in svc.list_posts()]
            self.assertNotIn(fh_id, after_dismiss_ids)
            self.assertIn(hn_id, after_dismiss_ids)
            self.assertIn(sol_id, after_dismiss_ids)
            self.assertIn(pool_id, after_dismiss_ids)

    def test_expanded_live_portals_calls_dedup_and_sync_all_portal_breakdown(self):
        from backend.core.recruiter_service import RECRUITER_LIVE_PORTALS, RecruiterService

        self.assertEqual(
            RECRUITER_LIVE_PORTALS,
            (
                "remotar-search",
                "freehire-search",
                "remoteok-search",
                "solides-search",
                "gupy-search",
                "greenhouse-search",
                "ashby-search",
                "jobicy-search",
                "empregos-search",
            ),
        )

        fh_calls = RecruiterService._build_live_portal_calls("freehire-search", "Python", "brazil")
        self.assertEqual(len(fh_calls), 3)
        self.assertIn(["-q", "Python", "--limit", "50", "--format", "json"], fh_calls)
        gh_calls = RecruiterService._build_live_portal_calls("greenhouse-search", "Python", "brazil")
        self.assertEqual(gh_calls, [["-q", "Python", "--with-description", "--format", "json"]])
        emp_calls = RecruiterService._build_live_portal_calls("empregos-search", "Python", "brazil")
        self.assertEqual(emp_calls, [["-q", "Python", "--with-description", "--format", "json"]])

        # Pre-existing job + recent scrape file verify _status_out aggregation in sync_all
        self.repo.upsert_job({
            "id": "local-hn-1",
            "title": "Backend Python",
            "company": "HNLocal",
            "url": "https://news.ycombinator.com/item?id=77001",
            "portal": "hn-search",
            "description": "Python FastAPI role. Email dev@hnlocal.dev",
            "status": "new",
        })

        seen_cli_calls = []

        def fake_run_cli(cli_portal, args, timeout=120):
            seen_cli_calls.append((cli_portal, list(args)))
            if cli_portal == "freehire-search":
                # Overlapping identical URL returned across --country, --remote, and --limit 50
                return [{
                    "url": "https://freehire.me/jobs/shared-dup-1",
                    "title": "Python Cloud Dev",
                    "company": "FreeDupCo",
                    "description": "Python cloud role. Contact jobs@freedup.dev",
                    "location": "Remote",
                }], None
            if cli_portal == "solides-search":
                return [{
                    "url": "https://vagas.solides.com.br/vaga/55123",
                    "title": "Dev Python Solides",
                    "company": "SolidesCo",
                    "description": "Python e Postgres. Envie CV para rh@solidesco.com.br",
                    "location": "São Paulo, SP",
                }], None
            if cli_portal == "greenhouse-search":
                self.assertIn("--with-description", args)
                return [{
                    "url": "https://boards.greenhouse.io/ghco/jobs/991",
                    "title": "Software Engineer Python",
                    "company": "GHCo",
                    "description": "Python services. Contact talent@ghco.io",
                    "location": "São Paulo, BR",
                }], None
            if cli_portal == "ashby-search":
                return None, "ashby temporary failure"
            return [], None

        installed_map = {p: True for p in RECRUITER_LIVE_PORTALS}
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp_scrape_dir:
            svc = RecruiterService(self.repo, enable_live_feeds=True, cache_dir=Path(tmp_scrape_dir))
            scan_file = Path(tmp_scrape_dir) / "painel_busca_2026-11-15.json"
            scan_file.write_text(json.dumps({
                "new": [{
                    "portal": "gupy-search",
                    "title": "Analista Python",
                    "company": "GupyScanCo",
                    "url": "https://gupyscan.gupy.io/jobs/777",
                    "description": "Python e dados. CV para rh@gupyscan.com.br",
                }]
            }), encoding="utf-8")

            with patch("tempfile.gettempdir", return_value=tmp_scrape_dir), \
                 patch("backend.tools.scrape_run.installed_portals", return_value=installed_map), \
                 patch("backend.tools.scrape_run.run_cli", side_effect=fake_run_cli), \
                 patch.object(svc, "sync_from_hn", return_value=0), \
                 patch.object(svc, "sync_from_github_repos", return_value=0), \
                 patch.object(svc, "sync_from_remotive", return_value=0):
                res = svc.sync_all(query="Python")

        breakdown = res["portal_breakdown"]
        # (portal, url) dedup counts overlapping freehire-search URL only once
        self.assertEqual(breakdown["freehire-search"]["fetched"], 1)
        self.assertEqual(breakdown["freehire-search"]["matched"], 1)
        self.assertEqual(breakdown["solides-search"]["fetched"], 1)
        self.assertEqual(breakdown["solides-search"]["matched"], 1)
        self.assertEqual(breakdown["greenhouse-search"]["fetched"], 1)
        self.assertEqual(breakdown["greenhouse-search"]["matched"], 1)
        self.assertGreaterEqual(breakdown["ashby-search"]["errors"], 1)
        # Local jobs & recent scrapes also report breakdown telemetry
        self.assertEqual(breakdown["hn-search"]["fetched"], 1)
        self.assertEqual(breakdown["hn-search"]["matched"], 1)
        self.assertEqual(breakdown["gupy-search"]["matched"], 1)

        all_posts = svc.list_posts()
        fh_rows = [p for p in all_posts if p["portal"] == "freehire-search"]
        self.assertEqual(len(fh_rows), 1)
        self.assertTrue(any("--limit" in args for portal, args in seen_cli_calls if portal == "freehire-search"))

    def test_linkedin_worker_routes_removed_and_sync_all_parallel_public_sources(self):
        import threading
        from backend.core.recruiter_service import RecruiterService

        headers = {"X-Painel-Token": self.token}
        self.assertIn(self.client.get("/api/recruiters/linkedin/status").status_code, (404, 405))
        for path in (
            "/api/recruiters/linkedin/connect",
            "/api/recruiters/linkedin/verify",
            "/api/recruiters/linkedin/config",
            "/api/recruiters/linkedin/disconnect",
        ):
            self.assertIn(self.client.post(path, json={}, headers=headers).status_code, (404, 405))

        # enable_live_feeds=False não dispara fontes externas
        offline_svc = RecruiterService(self.repo, enable_live_feeds=False)
        with patch.object(offline_svc, "sync_from_hn", side_effect=AssertionError("enable_live_feeds=False não deve chamar HN")):
            offline_res = offline_svc.sync_all(query="React")
        self.assertEqual(offline_res["errors"], 0)

        # add_pasted_posts_batch continua rejeitando lote sem e-mail válido
        with self.assertRaises(ValueError):
            offline_svc.add_pasted_posts_batch([
                {
                    "raw_text": "Estamos contratando Dev Angular Pleno sem email na colagem manual.",
                    "company": "ManualCo",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000012/",
                }
            ])

        # enable_live_feeds=True executa fontes públicas em threads paralelas
        barrier = threading.Barrier(2, timeout=2.0)
        seen_threads: list[str] = []

        def fake_hn(_term, _collected_urls=None, _status_out=None):
            seen_threads.append(f"hn:{threading.get_ident()}")
            barrier.wait()
            return 0

        def fake_gh(*_a, **_kw):
            seen_threads.append(f"gh:{threading.get_ident()}")
            barrier.wait()
            return 0

        online_svc = RecruiterService(self.repo, enable_live_feeds=True)
        with patch.object(online_svc, "sync_from_hn", side_effect=fake_hn), \
             patch.object(online_svc, "sync_from_github_repos", side_effect=fake_gh), \
             patch.object(online_svc, "sync_from_remotive", return_value=0), \
             patch.object(online_svc, "sync_from_live_portals", return_value=0), \
             patch.object(online_svc, "sync_from_recent_scrapes", return_value=0):
            online_res = online_svc.sync_all(query="Python")

        self.assertEqual(online_res["errors"], 0)
        self.assertEqual(len(seen_threads), 2)
        self.assertNotEqual(seen_threads[0].split(":")[1], seen_threads[1].split(":")[1])

    def test_expand_search_term_ai_cache_consent_and_sanitization(self):
        from backend.core.recruiters.search_terms import clear_search_term_cache

        clear_search_term_cache()
        headers = {"X-Painel-Token": self.token}

        class FakeProvider:
            def __init__(self, payload: str):
                self.payload = payload
                self.calls = 0

            def is_available(self) -> bool:
                return True

            def generate(self, *_args, **_kwargs) -> str:
                self.calls += 1
                return self.payload

        # 1) Sem consentimento -> degrada silenciosamente sem chamar IA
        provider_no_consent = FakeProvider('{"en": "Tax Law", "pt": "Direito Tributário"}')
        with patch("backend.core.recruiter_service.ai_providers.load_env_file", return_value={}), \
             patch("backend.core.recruiter_service.ai_providers.has_consent", return_value=False), \
             patch("backend.core.recruiter_service.ai_providers.get_ai_provider", return_value=provider_no_consent):
            res_nc = self.client.post(
                "/api/recruiters/expand-search-term",
                json={"term": "Direito Tributário"},
                headers=headers,
            )
        self.assertEqual(res_nc.status_code, 200)
        self.assertEqual(res_nc.json()["source"], "none")
        self.assertIsNone(res_nc.json()["en"])
        self.assertEqual(provider_no_consent.calls, 0)

        # 2) Com consentimento -> chama IA uma vez e cacheia variações sem acento
        provider_ok = FakeProvider('```json\n{"en": "Tax Law", "pt": "Direito Tributário"}\n```')
        with patch("backend.core.recruiter_service.ai_providers.load_env_file", return_value={"AI_DATA_CONSENT": "yes"}), \
             patch("backend.core.recruiter_service.ai_providers.has_consent", return_value=True), \
             patch("backend.core.recruiter_service.ai_providers.get_ai_provider", return_value=provider_ok):
            res_ai = self.client.post(
                "/api/recruiters/expand-search-term",
                json={"term": "Direito Tributário"},
                headers=headers,
            )
            res_cached = self.client.post(
                "/api/recruiters/expand-search-term",
                json={"term": "direito tributario"},
                headers=headers,
            )
        self.assertEqual(res_ai.status_code, 200)
        self.assertEqual(res_ai.json()["en"], "Tax Law")
        self.assertIsNone(res_ai.json()["pt"])  # Igual ao termo original -> omitido
        self.assertEqual(res_ai.json()["source"], "ai")
        self.assertEqual(res_cached.json()["source"], "cache")
        self.assertEqual(res_cached.json()["en"], "Tax Law")
        self.assertEqual(provider_ok.calls, 1)

        # 3) Sanitização rejeita operadores booleanos na resposta e ignora query booleana na entrada
        provider_dirty = FakeProvider('{"en": "Agronomy OR Farming", "pt": "Agronomia"}')
        with patch("backend.core.recruiter_service.ai_providers.load_env_file", return_value={"AI_DATA_CONSENT": "yes"}), \
             patch("backend.core.recruiter_service.ai_providers.has_consent", return_value=True), \
             patch("backend.core.recruiter_service.ai_providers.get_ai_provider", return_value=provider_dirty):
            res_dirty = self.client.post(
                "/api/recruiters/expand-search-term",
                json={"term": "Engenharia Agronômica"},
                headers=headers,
            )
            res_bool = self.client.post(
                "/api/recruiters/expand-search-term",
                json={"term": "(Python OR Go)"},
                headers=headers,
            )
        self.assertEqual(res_dirty.status_code, 200)
        self.assertIsNone(res_dirty.json()["en"])
        self.assertEqual(res_dirty.json()["pt"], "Agronomia")
        self.assertEqual(res_bool.json()["source"], "none")
        self.assertEqual(provider_dirty.calls, 1)
        clear_search_term_cache()

    def test_paste_without_email_inline_triage_details_and_interested_or_discard(self):
        from tempfile import TemporaryDirectory
        from backend.core.tracker import TrackerService
        from backend.tools import painel

        headers = {"X-Painel-Token": self.token}
        res_paste = self.client.post(
            "/api/recruiters/paste",
            json={
                "raw_text": "Estamos contratando Engenheiro de Visão Computacional / Computer Vision remoto com Python e OpenCV! Link nos comentários.",
                "url": "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000881/",
                "allow_without_email": True,
            },
            headers=headers,
        )
        self.assertEqual(res_paste.status_code, 200)
        pasted = res_paste.json()["post"]
        self.assertEqual(pasted["emails"], [])
        post_id = pasted["id"]

        fake_triage = {
            "classification": "vaga_ativa",
            "best_email": "",
            "score": 84,
            "verdict": "Strong Fit",
            "summary": "Forte aderência com Python, OpenCV e projetos de Visão Computacional.",
            "ai_model": "gemini-test",
            "subscores": {"technical": 88, "experience": 82, "behavioral": 80, "career": 84},
            "strengths": ["Experiência em Visão Computacional", "Python e OpenCV"],
            "gaps": ["Confirmar stack de deploy em edge"],
            "location_verdict": "PASS",
            "language_gate": "PASS",
            "language_note": "",
            "guard_alert": "",
        }
        with patch("backend.core.recruiter_service.ai_providers.load_env_file", return_value={"AI_DATA_CONSENT": "yes"}), \
             patch("backend.core.recruiter_service.ai_providers.has_consent", return_value=True), \
             patch("backend.tools.painel_ia.is_available", return_value=True), \
             patch("backend.tools.painel_ia.triar_post_recrutador", return_value=fake_triage):
            res_triage = self.client.post(
                "/api/recruiters/triage",
                json={"post_ids": [post_id], "limit": 5},
                headers=headers,
            )

        self.assertEqual(res_triage.status_code, 200)
        triaged_data = res_triage.json()
        self.assertEqual(triaged_data["triaged"], 1)
        self.assertEqual(triaged_data["active_jobs"], 1)
        triaged_post = triaged_data["posts"][0]
        self.assertEqual(triaged_post["id"], post_id)
        self.assertEqual(triaged_post["ai_score"], 84)
        self.assertEqual(triaged_post["ai_details"]["subscores"]["technical"], 88)
        self.assertEqual(triaged_post["ai_details"]["strengths"], ["Experiência em Visão Computacional", "Python e OpenCV"])
        self.assertEqual(triaged_post["ai_details"]["gaps"], ["Confirmar stack de deploy em edge"])

        # Enviar para Me Interessam preserva subscores, strengths e gaps em evaluations
        with TemporaryDirectory() as tmpdir, \
             patch("backend.tools.painel_ia.PAINEL_DIR", Path(tmpdir)), \
             patch("backend.tools.painel.CLAUDE_DIR", Path(tmpdir)), \
             patch("backend.tools.painel_ia.save_job_cache"), \
             patch("backend.tools.painel.saved", return_value=[]), \
             patch("backend.tools.painel.discarded", return_value=[]):
            res_int = self.client.post(f"/api/recruiters/{post_id}/interested", headers=headers)
            self.assertEqual(res_int.status_code, 200)

            tracker = TrackerService(self.repo)
            saved_rows = tracker.list_enriched_saved_jobs()
            self.assertEqual(len(saved_rows), 1)
            self.assertEqual(saved_rows[0]["screening"]["score"], 84)
            self.assertEqual(saved_rows[0]["screening"]["subscores"]["technical"], 88)
            self.assertEqual(saved_rows[0]["screening"]["strengths"], ["Experiência em Visão Computacional", "Python e OpenCV"])
            self.assertEqual(saved_rows[0]["screening"]["gaps"], ["Confirmar stack de deploy em edge"])

            # Segundo post colado sem e-mail descartado diretamente
            res_paste2 = self.client.post(
                "/api/recruiters/paste",
                json={
                    "raw_text": "Vaga presencial em outro país sem remoto para diretor de vendas corporativas.",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000882/",
                    "allow_without_email": True,
                },
                headers=headers,
            )
            self.assertEqual(res_paste2.status_code, 200)
            post2_id = res_paste2.json()["post"]["id"]
            res_del = self.client.delete(f"/api/recruiters/{post2_id}", headers=headers)
            self.assertEqual(res_del.status_code, 200)
            disc_rows = tracker.list_enriched_discarded_jobs()
            self.assertEqual(len(disc_rows), 1)
            self.assertEqual(disc_rows[0]["url"], "https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000882/")


if __name__ == "__main__":
    unittest.main()
