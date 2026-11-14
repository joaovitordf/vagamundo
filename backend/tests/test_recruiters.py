"""Unit tests for recruiter service and API endpoints."""

import json
import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
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
from backend.tools import painel, painel_ia
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

    def test_api_dismiss_batch_requires_csrf_and_moves_only_target_ids_to_limbo(self):
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

        # Apenas p3 permanece listado no radar
        remaining = self.client.get("/api/recruiters").json()["posts"]
        self.assertEqual([p["id"] for p in remaining], [p3["id"]])

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

    def test_dismiss_to_limbo_blocks_same_vacancy_without_blocking_other_jobs_same_email(self):
        vaga_java = self.service.add_pasted_post(
            raw_text="Vaga Desenvolvedor Java Sênior com Spring Boot e Kafka. Envie CV para rh@consultoria.dev",
            title="Desenvolvedor Java Sênior",
            company="Consultoria Dev",
            url="https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000101/",
        )
        self.assertTrue(self.service.dismiss_post(vaga_java["id"]))

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

        # Reimportar a mesma vaga já descartada em lote continua bloqueado no Limbo
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


if __name__ == "__main__":
    unittest.main()
