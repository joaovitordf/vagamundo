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
    match_cv_keywords,
    RecruiterService,
)
from backend.tools import painel, painel_ia
from backend.api.app import app
from backend.api.deps import get_repository, get_recruiter_service, get_tracker
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
            for col in ("ai_classification", "ai_score", "ai_verdict", "ai_summary", "ai_best_email", "ai_evaluated_at", "auto_promoted", "auto_run_id"):
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
             patch("backend.tools.painel_ia.call_llm", return_value='{"classification": "vaga_ativa", "best_email": "talentos@techco.com", "score": 82, "verdict": "Strong Fit", "summary": "Casa com stack e senioridade."}'):
            out = painel_ia.triar_post_recrutador(post)
        self.assertEqual(out["classification"], "vaga_ativa")
        self.assertEqual(out["best_email"], "talentos@techco.com")
        self.assertEqual(out["score"], 82)

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

        # Saiu da caixa de entrada de Recrutadores e foi para Me Interessam sem auto_promoted
        self.assertEqual(self.service.list_posts(), [])
        saved = self.repo.list_jobs(status="interested")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["url"], f"recruiter://post/{post['id']}")
        refreshed_post = self.repo.get_recruiter_post(post["id"])
        self.assertEqual(refreshed_post["auto_promoted"], 0)
        self.assertEqual(refreshed_post["job_id"], saved[0]["id"])

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


if __name__ == "__main__":
    unittest.main()
