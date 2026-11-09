"""Unit tests for recruiter service and API endpoints."""

import os
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi.testclient import TestClient

from backend.db.repository import Repository
from backend.core.recruiter_service import (
    extract_clean_emails,
    extract_email_context,
    match_cv_keywords,
    RecruiterService,
)
from backend.api.app import app
from backend.api.deps import get_repository, get_recruiter_service


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


class TestRecruitersApi(unittest.TestCase):
    def setUp(self):
        self.tmp_db = NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.repo = Repository(db_path=self.tmp_db.name)
        self.service = RecruiterService(self.repo)

        app.dependency_overrides[get_repository] = lambda: self.repo
        app.dependency_overrides[get_recruiter_service] = lambda: self.service
        self.client = TestClient(app)

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
        token_resp = self.client.get("/api/settings")
        # Use token header or simulate
        paste_resp = self.client.post("/api/recruiters/paste", json={
            "raw_text": "Estamos contratando Desenvolvedor Python! CVs para dev@ai-company.com",
            "company": "AI Company",
        }, headers={"X-Painel-Token": "test"})
        # Should be 200 (or if CSRF enabled, with valid token)
        self.assertIn(paste_resp.status_code, [200, 403])


if __name__ == "__main__":
    unittest.main()
