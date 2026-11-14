"""Unit and integration tests for Auto Mode (AI keyword pick, <=7d scan, triage, undo, and API)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_auto_mode, get_tracker
from backend.api.security import get_token
from backend.core.auto_mode import AutoModeService, _detect_rate_limit_in_portals, _within_jobage
from backend.core.evaluator import EvaluatorService
from backend.core.recruiter_service import RecruiterService
from backend.core.scanner import ScannerService
from backend.core.tracker import TrackerService
from backend.db.repository import Repository
from backend.tools import painel_ia


class AutoModeSafetyAndKeywordsTests(unittest.TestCase):
    def test_triar_vaga_rapida_never_defaults_invalid_score_to_50(self):
        with patch("backend.tools.painel_ia.fetch_posting", return_value={"text": "Vaga X", "portal": "gupy-search", "title": "Dev"}), \
             patch("backend.tools.painel_ia.candidate_profile", return_value="Perfil exemplo"), \
             patch("backend.tools.painel_ia.call_llm", return_value='{"verdict": "Moderate Fit", "summary": "Sem nota"}'):
            with self.assertRaises(ValueError):
                painel_ia.triar_vaga_rapida("https://example.com/vaga-sem-nota")

        with patch("backend.tools.painel_ia.fetch_posting", return_value={"text": "Vaga X", "portal": "gupy-search", "title": "Dev"}), \
             patch("backend.tools.painel_ia.candidate_profile", return_value="Perfil exemplo"), \
             patch("backend.tools.painel_ia.call_llm", return_value='{"score": "nao-numerico"}'):
            with self.assertRaises(ValueError):
                painel_ia.triar_vaga_rapida("https://example.com/vaga-nota-invalida")

    def test_sortear_palavras_chave_caps_at_two_and_propagates_consent(self):
        with patch("backend.tools.painel_ia.candidate_profile", return_value="Competencias: Python, Dados, Produto"), \
             patch("backend.tools.painel_ia.call_llm", return_value='{"keywords": ["Python", "Dados", "Extra"], "rationale": "Eixo"}'):
            out = painel_ia.sortear_palavras_chave_busca(avoid_recent=["Produto, SQL"], region="brasil")
        self.assertEqual(out["keywords"], ["Python", "Dados"])
        self.assertEqual(out["source"], "ai")

        with patch("backend.tools.painel_ia.candidate_profile", return_value="Competencias: Angular, Python"), \
             patch("backend.tools.painel_ia.call_llm", return_value='{"keywords": ["Angular", "Python"], "rationale": "Foco único"}'):
            out_rec = painel_ia.sortear_palavras_chave_busca(avoid_recent=["Java"], region="all", mode="recruiters")
        self.assertEqual(out_rec["keywords"], ["Angular"])

        with patch("backend.tools.painel_ia.candidate_profile", return_value="Competencias: Python"), \
             patch("backend.tools.painel_ia.call_llm", side_effect=painel_ia.ConsentRequired("Sem consentimento")):
            with self.assertRaises(painel_ia.ConsentRequired):
                painel_ia.sortear_palavras_chave_busca()

    def test_within_jobage_date_cutoff(self):
        today = date(2026, 11, 11)
        self.assertTrue(_within_jobage("2026-11-05", 7, hide_undated=True, today_day=today))
        self.assertTrue(_within_jobage("05/11/2026", 7, hide_undated=True, today_day=today))
        self.assertFalse(_within_jobage("2026-11-03", 7, hide_undated=True, today_day=today))
        self.assertFalse(_within_jobage("03/11/2026", 7, hide_undated=True, today_day=today))
        self.assertTrue(_within_jobage(None, 7, hide_undated=False, today_day=today))
        self.assertFalse(_within_jobage(None, 7, hide_undated=True, today_day=today))


class AutoModeOrchestrationAndUndoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self.tmp.name)
        self.db_path = self.dir / "auto_test.db"
        os.environ["VAGAMUNDO_DB_PATH"] = str(self.db_path)
        self.repo = Repository(self.db_path)
        self.scanner = ScannerService(out_path=self.dir / "results.json", repo=self.repo)
        self.evaluator = EvaluatorService(repo=self.repo)
        self.tracker = TrackerService(repo=self.repo)
        self.recruiter_service = RecruiterService(repo=self.repo, enable_live_feeds=False)
        self.auto = AutoModeService(
            repo=self.repo,
            scanner=self.scanner,
            evaluator=self.evaluator,
            recruiter_service=self.recruiter_service,
        )

    def tearDown(self):
        app.dependency_overrides.clear()
        os.environ.pop("VAGAMUNDO_DB_PATH", None)
        self.repo.close()
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def test_evaluator_auto_interest_promotion_thresholds(self):
        jobs = [
            {"id": "j-high", "title": "Engenheiro de Dados", "company": "Alfa", "url": "https://ex.com/high", "status": "new"},
            {"id": "j-mid", "title": "Analista Pleno", "company": "Beta", "url": "https://ex.com/mid", "status": "new"},
            {"id": "j-low", "title": "Diretor", "company": "Gama", "url": "https://ex.com/low", "status": "new"},
            {"id": "j-app", "title": "Dev Aplicado", "company": "Delta", "url": "https://ex.com/app", "status": "applied"},
        ]
        for j in jobs:
            self.repo.upsert_job(j)

        scores = {
            "https://ex.com/high": {"url": "https://ex.com/high", "score": 68, "verdict": "Good Fit", "summary": "Forte match"},
            "https://ex.com/mid": {"url": "https://ex.com/mid", "score": 54, "verdict": "Moderate Fit", "summary": "Falta stack"},
            "https://ex.com/low": {"url": "https://ex.com/low", "score": 30, "verdict": "Poor Fit", "summary": "Incompatível"},
            "https://ex.com/app": {"url": "https://ex.com/app", "score": 90, "verdict": "Strong Fit", "summary": "Ótima"},
        }

        with patch("backend.tools.painel_ia.triar_vaga_rapida", side_effect=lambda u, _jd=None: scores[u]), \
             patch("backend.tools.painel_ia.get_provider_info", return_value={"label": "Mock AI"}), \
             patch.object(EvaluatorService, "_sync_painel_mark"):
            ok = self.evaluator.start_batch(
                [j["url"] for j in jobs],
                workers=1,
                auto_interest_min=60,
                run_id="run123",
                blocking=True,
            )

        self.assertTrue(ok)
        st = self.evaluator.batch_status()
        self.assertEqual(st["auto_interested"], 1)
        self.assertEqual(len(st["promoted_items"]), 1)
        self.assertEqual(st["promoted_items"][0]["url"], "https://ex.com/high")

        self.assertEqual(self.repo.get_job("j-high")["status"], "interested")
        self.assertEqual(self.repo.get_job("j-mid")["status"], "new")
        self.assertEqual(self.repo.get_job("j-mid")["rank_score"], 54)
        self.assertEqual(self.repo.get_job("j-low")["status"], "discarded")
        self.assertEqual(self.repo.get_job("j-app")["status"], "applied")

    def test_end_to_end_run_api_saved_badge_and_dual_undo(self):
        today_str = date.today().isoformat()
        old_str = (date.today() - timedelta(days=12)).isoformat()
        scan_payload = {
            "meta": {"jobage": 7},
            "new": [
                {"url": "https://ex.com/v1", "title": "Cargo Um", "company": "Emp A", "date": today_str, "portal": "gupy-search"},
                {"url": "https://ex.com/v2", "title": "Cargo Dois", "company": "Emp B", "date": today_str, "portal": "gupy-search"},
                {"url": "https://ex.com/v3", "title": "Cargo Tres", "company": "Emp C", "date": today_str, "portal": "gupy-search"},
                {"url": "https://ex.com/old", "title": "Vaga Velha", "company": "Emp D", "date": old_str, "portal": "gupy-search"},
            ],
        }
        self.scanner.out.write_text(json.dumps(scan_payload), encoding="utf-8")

        def fake_scanner_start(**kwargs):
            # Verifica que jobage maximo de 7 dias foi respeitado mesmo pedindo 30
            self.assertEqual(kwargs.get("jobage"), 7)
            self.scanner.running = False
            self.scanner.error = None
            return True

        triage_scores = {
            "https://ex.com/v1": {"url": "https://ex.com/v1", "score": 78, "verdict": "Strong Fit", "summary": "Casa bem"},
            "https://ex.com/v2": {"url": "https://ex.com/v2", "score": 64, "verdict": "Good Fit", "summary": "Boa aderência"},
            "https://ex.com/v3": {"url": "https://ex.com/v3", "score": 48, "verdict": "Weak Fit", "summary": "Falta requisito"},
        }

        app.dependency_overrides[get_auto_mode] = lambda: self.auto
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        client = TestClient(app)
        token = get_token()

        with patch.object(self.auto, "validate_ready"), \
             patch("backend.tools.painel_ia.sortear_palavras_chave_busca", return_value={"keywords": ["Termo 1", "Termo 2"], "rationale": "Teste", "source": "ai"}), \
             patch.object(self.scanner, "start", side_effect=fake_scanner_start), \
             patch("backend.tools.painel_ia.triar_vaga_rapida", side_effect=lambda u, _jd=None: triage_scores[u]), \
             patch("backend.tools.painel_ia.get_provider_info", return_value={"label": "Mock AI"}), \
             patch.object(EvaluatorService, "_sync_painel_mark"), \
             patch("backend.tools.painel.unmark_interested", return_value=True):

            # Dispara passando jobage=30 para testar trava em 7 dias
            self.auto.save_config({"min_score": 60, "jobage": 30})
            cfg = self.auto.get_config()
            self.assertEqual(cfg["jobage"], 7)

            res_start = client.post(
                "/api/auto-mode/start",
                json={"region": "brasil", "jobage": 30, "min_score": 60, "continuous": False},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(res_start.status_code, 200)
            run_id = res_start.json()["run_id"]

            # Aguarda thread daemon concluir (rápido com mocks)
            import time
            for _ in range(50):
                st = client.get("/api/auto-mode/status").json()
                if not st["running"]:
                    break
                time.sleep(0.05)

            self.assertEqual(st["phase"], "done")
            self.assertEqual(st["counts"]["to_screen"], 3)  # vaga de 12d ficou de fora
            self.assertEqual(st["counts"]["promoted"], 2)   # v1 (78) e v2 (64)

            # Verifica /api/saved exibe badge auto_promoted=True e auto_run_id
            saved_resp = client.get("/api/saved")
            self.assertEqual(saved_resp.status_code, 200)
            saved_by_url = {s["url"]: s for s in saved_resp.json()["saved"]}
            self.assertIn("https://ex.com/v1", saved_by_url)
            self.assertIn("https://ex.com/v2", saved_by_url)
            self.assertTrue(saved_by_url["https://ex.com/v1"]["auto_promoted"])
            self.assertEqual(saved_by_url["https://ex.com/v1"]["auto_run_id"], run_id)

            # Vagas promovidas saem de load_results() em Buscar Vagas
            pending_urls = [j["url"] for j in self.scanner.load_results()["new"]]
            self.assertNotIn("https://ex.com/v1", pending_urls)
            self.assertNotIn("https://ex.com/v2", pending_urls)
            self.assertIn("https://ex.com/v3", pending_urls)

            # Desfazer vaga individual (v1) -> volta para Buscar Vagas mantendo nota 78
            undo_one = client.post(
                "/api/auto-mode/undo-job",
                json={"url": "https://ex.com/v1"},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(undo_one.status_code, 200)
            self.assertEqual(undo_one.json()["reverted"], 1)
            self.assertEqual(self.repo.get_job_by_url("https://ex.com/v1")["status"], "new")
            self.assertEqual(self.repo.get_job_by_url("https://ex.com/v1")["rank_score"], 78)
            self.assertEqual(self.repo.get_job_by_url("https://ex.com/v2")["status"], "interested")

            # Desfazer rodada inteira -> devolve apenas v2 (que ainda estava interested)
            undo_all = client.post(
                "/api/auto-mode/undo",
                json={"run_id": run_id},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(undo_all.status_code, 200)
            self.assertEqual(undo_all.json()["reverted"], 1)
            self.assertEqual(self.repo.get_job_by_url("https://ex.com/v2")["status"], "new")

    def test_start_requires_consent_and_csrf(self):
        app.dependency_overrides[get_auto_mode] = lambda: self.auto
        client = TestClient(app)

        no_csrf = client.post("/api/auto-mode/start", json={"min_score": 60})
        self.assertEqual(no_csrf.status_code, 403)

        token = get_token()
        with patch("backend.tools.ai_providers.load_env_file", return_value={}), \
             patch("backend.tools.ai_providers.has_consent", return_value=False):
            no_consent = client.post(
                "/api/auto-mode/start",
                json={"min_score": 60},
                headers={"X-Painel-Token": token},
            )
        self.assertEqual(no_consent.status_code, 400)
        self.assertIn("Consentimento", no_consent.json()["detail"])

    def test_recruiters_auto_mode_end_to_end_classify_promote_and_dual_undo(self):
        # 4 posts matching sorted keywords ("Python", "Backend"): 1 high active, 1 low active, 1 talent pool, 1 non-job
        # + 1 unrelated untriaged post that should NOT be evaluated in this keyword-focused round
        p_promote = self.recruiter_service.add_pasted_post(
            raw_text="Vaga Python Backend Pleno! Enviar CV para vagas@alfa.com ou dpo@alfa.com",
            url="https://news.ycombinator.com/item?id=9901",
            title="Python Backend Pleno",
            company="Alfa Tech",
        )
        p_low = self.recruiter_service.add_pasted_post(
            raw_text="Staff Python Backend Architect (10+ anos). Contato: jobs@beta.io",
            url="https://ex.com/rec/low",
            title="Staff Python Architect",
            company="Beta IO",
        )
        p_pool = self.recruiter_service.add_pasted_post(
            raw_text="Banco de talentos Python e Backend! Deixe seu currículo em talentos@gama.com",
            url="https://ex.com/rec/pool",
            title="Banco de Talentos Python",
            company="Gama",
        )
        p_non_job = self.recruiter_service.add_pasted_post(
            raw_text="Artigo: 5 dicas sobre Python e Backend. Fale conosco: contato@blog.dev",
            url="https://ex.com/rec/nonjob",
            title="Dicas Python Backend",
            company="Blog Dev",
        )
        p_unrelated = self.recruiter_service.add_pasted_post(
            raw_text="Designer Gráfico Júnior para agência. Enviar portfólio para design@agencia.com",
            url="https://ex.com/rec/unrelated",
            title="Designer Gráfico",
            company="Agência X",
        )

        # Normalize portal on first post as hn-search to verify non-Vagas source handling
        with self.repo.conn:
            self.repo.conn.execute("UPDATE recruiter_posts SET portal = 'hn-search' WHERE id = ?", (p_promote["id"],))

        triage_results = {
            p_promote["id"]: {
                "classification": "vaga_ativa",
                "best_email": "vagas@alfa.com",
                "score": 82,
                "verdict": "Strong Fit",
                "summary": "Vaga ativa alinhada com seu perfil.",
            },
            p_low["id"]: {
                "classification": "vaga_ativa",
                "best_email": "jobs@beta.io",
                "score": 45,
                "verdict": "Weak Fit",
                "summary": "Senioridade acima do alvo.",
            },
            p_pool["id"]: {
                "classification": "banco_talentos",
                "best_email": "",
                "score": 0,
                "verdict": "Poor Fit",
                "summary": "Captação para banco de talentos sem vaga aberta.",
            },
            p_non_job["id"]: {
                "classification": "nao_e_vaga",
                "best_email": "",
                "score": 0,
                "verdict": "Poor Fit",
                "summary": "Publicação informativa, não é vaga.",
            },
        }
        evaluated_ids = []

        def fake_triar_recrutador(post):
            evaluated_ids.append(post["id"])
            return triage_results[post["id"]]

        app.dependency_overrides[get_auto_mode] = lambda: self.auto
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        from backend.api.deps import get_recruiter_service, get_repository
        app.dependency_overrides[get_recruiter_service] = lambda: self.recruiter_service
        app.dependency_overrides[get_repository] = lambda: self.repo
        client = TestClient(app)
        token = get_token()

        # CSRF & config validation
        no_csrf = client.post("/api/recruiters/auto/start", json={"min_score": 60})
        self.assertEqual(no_csrf.status_code, 403)
        cfg_save = client.post(
            "/api/recruiters/auto/config",
            json={"min_score": 120},
            headers={"X-Painel-Token": token},
        )
        self.assertEqual(cfg_save.status_code, 200)
        self.assertEqual(cfg_save.json()["config"]["min_score"], 95)

        with patch.object(self.auto, "validate_ready"), \
             patch.object(painel_ia, "PAINEL_DIR", self.dir / "_painel"), \
             patch("backend.tools.painel_ia.sortear_palavras_chave_busca", return_value={"keywords": ["Python", "Backend"], "rationale": "Foco backend", "source": "ai"}), \
             patch.object(self.recruiter_service, "sync_from_hn", return_value=0), \
             patch("backend.tools.painel_ia.triar_post_recrutador", side_effect=fake_triar_recrutador), \
             patch("backend.tools.painel.unmark_interested", return_value=True):

            res = client.post(
                "/api/recruiters/auto/start",
                json={"min_score": 60, "continuous": False},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(res.status_code, 200)
            run_id = res.json()["run_id"]

            import time
            st = {}
            for _ in range(60):
                st = client.get("/api/auto-mode/status").json()
                if not st["running"]:
                    break
                time.sleep(0.05)

            self.assertEqual(st["mode"], "recruiters")
            self.assertEqual(st["phase"], "done")
            self.assertEqual(st["counts"]["to_screen"], 4)
            self.assertEqual(st["counts"]["promoted"], 1)
            self.assertEqual(st["counts"]["talent_pools_discarded"], 1)
            self.assertEqual(st["counts"]["not_a_job"], 1)
            self.assertEqual(st["counts"]["kept_low_score"], 1)
            self.assertNotIn(p_unrelated["id"], evaluated_ids)

            # Promoted post creates linked job in Me Interessam with recruiter_emails & auto_origin='recruiter'
            saved = client.get("/api/saved").json()["saved"]
            by_url = {s["url"]: s for s in saved}
            self.assertIn("https://news.ycombinator.com/item?id=9901", by_url)
            promoted_saved = by_url["https://news.ycombinator.com/item?id=9901"]
            self.assertTrue(promoted_saved["auto_promoted"])
            self.assertEqual(promoted_saved["auto_origin"], "recruiter")
            self.assertEqual(promoted_saved["auto_run_id"], run_id)
            self.assertEqual(promoted_saved["recruiter_emails"][0], "vagas@alfa.com")

            # Recrutadores listing: promoted & talent pool removed; low-score active + nao_e_vaga kept (nao_e_vaga last)
            rec_all = client.get("/api/recruiters").json()["posts"]
            rec_ids = [p["id"] for p in rec_all]
            self.assertNotIn(p_promote["id"], rec_ids)
            self.assertNotIn(p_pool["id"], rec_ids)
            self.assertIn(p_low["id"], rec_ids)
            self.assertIn(p_non_job["id"], rec_ids)
            self.assertGreater(rec_ids.index(p_non_job["id"]), rec_ids.index(p_low["id"]))
            self.assertEqual(self.repo.get_recruiter_post(p_pool["id"])["dismissed"], 1)

            # Optional hide non-jobs toggle
            rec_only_jobs = client.get("/api/recruiters?include_non_jobs=false").json()["posts"]
            self.assertNotIn(p_non_job["id"], [p["id"] for p in rec_only_jobs])

            # Undo run reverts promoted post out of Me Interessam & back to Recrutadores preserving AI score, without touching scanner.out
            undo_res = client.post(
                "/api/auto-mode/undo",
                json={"run_id": run_id},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(undo_res.status_code, 200)
            self.assertEqual(undo_res.json()["reverted"], 1)
            self.assertFalse(self.scanner.out.exists())
            saved_after = client.get("/api/saved").json()["saved"]
            self.assertNotIn("https://news.ycombinator.com/item?id=9901", [s["url"] for s in saved_after])

            rec_after_undo = client.get("/api/recruiters").json()["posts"]
            reverted_post = next((p for p in rec_after_undo if p["id"] == p_promote["id"]), None)
            self.assertIsNotNone(reverted_post)
            self.assertEqual(reverted_post["ai_score"], 82)
            self.assertEqual(reverted_post["auto_promoted"], 0)

    def test_config_defaults_and_clamping_for_continuous_mode(self):
        jobs_default = self.auto.get_config()
        self.assertTrue(jobs_default["continuous"])
        self.assertEqual(jobs_default["cooldown_seconds"], 300)

        jobs_low = self.auto.save_config({"cooldown_seconds": 10, "continuous": False})
        self.assertEqual(jobs_low["cooldown_seconds"], 120)
        self.assertFalse(jobs_low["continuous"])

        jobs_high = self.auto.save_config({"cooldown_seconds": 9999})
        self.assertEqual(jobs_high["cooldown_seconds"], 1800)

        rec_default = self.auto.get_recruiter_config()
        self.assertTrue(rec_default["continuous"])
        self.assertEqual(rec_default["cooldown_seconds"], 30)

        rec_low = self.auto.save_recruiter_config({"cooldown_seconds": 2, "continuous": False})
        self.assertEqual(rec_low["cooldown_seconds"], 15)
        self.assertFalse(rec_low["continuous"])

        rec_high = self.auto.save_recruiter_config({"cooldown_seconds": 999})
        self.assertEqual(rec_high["cooldown_seconds"], 300)

    def test_compute_cooldown_jitter_backoff_and_portal_rate_limit(self):
        det_min = lambda a, _b: a
        s_empty, reason_empty = AutoModeService._compute_cooldown(
            mode="recruiters",
            base_cooldown=30,
            round_had_items=False,
            rate_limited=False,
            consecutive_empty=1,
            consecutive_rate_limits=0,
            jitter_fn=det_min,
        )
        self.assertEqual(s_empty, 25)
        self.assertIsNone(reason_empty)

        s_active, reason_active = AutoModeService._compute_cooldown(
            mode="recruiters",
            base_cooldown=30,
            round_had_items=True,
            rate_limited=False,
            consecutive_empty=0,
            consecutive_rate_limits=0,
            jitter_fn=det_min,
        )
        self.assertEqual(s_active, 30)
        self.assertIsNone(reason_active)

        s_streak, reason_streak = AutoModeService._compute_cooldown(
            mode="recruiters",
            base_cooldown=30,
            round_had_items=False,
            rate_limited=False,
            consecutive_empty=5,
            consecutive_rate_limits=0,
            jitter_fn=det_min,
        )
        self.assertGreater(s_streak, 30)
        self.assertIn("rodadas", reason_streak)

        s_rl, reason_rl = AutoModeService._compute_cooldown(
            mode="recruiters",
            base_cooldown=30,
            round_had_items=False,
            rate_limited=True,
            consecutive_empty=1,
            consecutive_rate_limits=2,
            jitter_fn=det_min,
        )
        self.assertGreaterEqual(s_rl, 125)
        self.assertIn("Rate-limit", reason_rl)

        s_jobs_rl, reason_jobs_rl = AutoModeService._compute_cooldown(
            mode="jobs",
            base_cooldown=300,
            round_had_items=False,
            rate_limited=True,
            consecutive_empty=1,
            consecutive_rate_limits=2,
            jitter_fn=det_min,
        )
        self.assertGreaterEqual(s_jobs_rl, 1215)
        self.assertIn("portais", reason_jobs_rl)

        self.assertTrue(_detect_rate_limit_in_portals({"gupy": {"error": "HTTP 429 Too Many Requests"}}))
        self.assertTrue(
            _detect_rate_limit_in_portals({
                "p1": {"error": "timeout"},
                "p2": {"status": "ok"},
                "p3": {"status": "ok"},
            })
        )
        self.assertFalse(
            _detect_rate_limit_in_portals({
                "p1": {"error": "timeout"},
                "p2": {"status": "ok"},
                "p3": {"status": "ok"},
                "p4": {"status": "ok"},
            })
        )

    def test_recruiters_continuous_skip_cooldown_and_whole_session_undo(self):
        import time

        p_py = self.recruiter_service.add_pasted_post(
            raw_text="Vaga Python FastAPI Pleno. Envie CV para rh@pytech.com",
            url="https://ex.com/rec/py",
            title="Python FastAPI Dev",
            company="PyTech",
        )
        p_go = self.recruiter_service.add_pasted_post(
            raw_text="Senior Golang Backend Engineer. Email: jobs@gotech.io",
            url="https://ex.com/rec/go",
            title="Golang Backend",
            company="GoTech",
        )

        # Rodada 1 sorteia ["Angular"] -> 0 candidatos; entra em cooldown
        # Rodada 2 (via skip-cooldown) sorteia ["Python"] -> promove p_py
        # Rodada 3 (via skip-cooldown) sorteia ["Golang"] -> promove p_go; usuário cancela no cooldown
        keyword_sequence = [
            {"keywords": ["Angular"], "rationale": "R1", "source": "ai"},
            {"keywords": ["Python"], "rationale": "R2", "source": "ai"},
            {"keywords": ["Golang"], "rationale": "R3", "source": "ai"},
        ]

        def fake_triar(post):
            return {
                "classification": "vaga_ativa",
                "best_email": (post.get("emails") or ["rh@ex.com"])[0],
                "score": 85,
                "verdict": "Strong Fit",
                "summary": "Match excelente.",
            }

        app.dependency_overrides[get_auto_mode] = lambda: self.auto
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        client = TestClient(app)
        token = get_token()

        with patch.object(self.auto, "validate_ready"), \
             patch("backend.tools.painel_ia.sortear_palavras_chave_busca", side_effect=keyword_sequence), \
             patch.object(self.recruiter_service, "sync_from_hn", return_value=0), \
             patch("backend.tools.painel_ia.triar_post_recrutador", side_effect=fake_triar), \
             patch("backend.tools.painel.unmark_interested", return_value=True):

            start_res = client.post(
                "/api/recruiters/auto/start",
                json={"min_score": 60, "continuous": True, "cooldown_seconds": 30},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(start_res.status_code, 200)
            run_id = start_res.json()["run_id"]

            def wait_for_cooldown_round(expected_round: int):
                for _ in range(80):
                    st = client.get("/api/auto-mode/status").json()
                    if st.get("phase") == "cooldown" and st.get("round") == expected_round:
                        return st
                    time.sleep(0.03)
                self.fail(f"Nao entrou em cooldown na rodada {expected_round}: {st}")

            st1 = wait_for_cooldown_round(1)
            self.assertEqual(st1["keywords"], ["Angular"])
            self.assertEqual(st1["round_eligible_count"], 0)
            self.assertGreater(st1["cooldown_remaining_s"], 0)
            self.assertIsNotNone(st1["next_run_at"])

            # Pula cooldown para iniciar imediatamente a Rodada 2
            skip1 = client.post("/api/auto-mode/skip-cooldown", headers={"X-Painel-Token": token})
            self.assertTrue(skip1.json()["skipped"])

            st2 = wait_for_cooldown_round(2)
            self.assertEqual(st2["keywords"], ["Python"])
            self.assertEqual(st2["counts"]["promoted"], 1)

            skip2 = client.post("/api/auto-mode/skip-cooldown", headers={"X-Painel-Token": token})
            self.assertTrue(skip2.json()["skipped"])

            st3 = wait_for_cooldown_round(3)
            self.assertEqual(st3["keywords"], ["Golang"])
            self.assertEqual(st3["counts"]["promoted"], 2)
            self.assertEqual(len(st3["round_history"]), 3)

            # Cancela instantaneamente durante cooldown
            cancel_res = client.post("/api/auto-mode/cancel", headers={"X-Painel-Token": token})
            self.assertEqual(cancel_res.status_code, 200)
            for _ in range(50):
                final_st = client.get("/api/auto-mode/status").json()
                if not final_st["running"]:
                    break
                time.sleep(0.03)
            self.assertEqual(final_st["phase"], "cancelled")

            # Undo da sessão contínua inteira reverte ambos os posts promovidos nas rodadas 2 e 3
            undo_res = client.post(
                "/api/auto-mode/undo",
                json={"run_id": run_id},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(undo_res.status_code, 200)
            self.assertEqual(undo_res.json()["reverted"], 2)
            self.assertEqual(self.repo.get_recruiter_post(p_py["id"])["auto_promoted"], 0)
            self.assertEqual(self.repo.get_recruiter_post(p_go["id"])["auto_promoted"], 0)

    def test_jobs_continuous_merges_pending_and_skips_re_eval(self):
        import time

        today_str = date.today().isoformat()
        scan_round_counter = {"n": 0}

        def fake_scanner_start(**_kwargs):
            scan_round_counter["n"] += 1
            if scan_round_counter["n"] == 1:
                payload = {
                    "meta": {"jobage": 7},
                    "new": [
                        {"url": "https://ex.com/j1", "title": "Java Dev", "company": "A", "date": today_str, "portal": "gupy"},
                        {"url": "https://ex.com/j_mid", "title": "Pleno Dev", "company": "B", "date": today_str, "portal": "gupy"},
                    ],
                }
            else:
                # Simula overwrite completo do arquivo de saída pelo scrape_run.py
                payload = {
                    "meta": {"jobage": 7},
                    "new": [
                        {"url": "https://ex.com/j2", "title": "Angular Dev", "company": "C", "date": today_str, "portal": "remoteok"},
                    ],
                }
            self.scanner.out.write_text(json.dumps(payload), encoding="utf-8")
            self.scanner.running = False
            self.scanner.error = None
            return True

        evaluated_calls = []
        scores = {
            "https://ex.com/j1": {"url": "https://ex.com/j1", "score": 80, "verdict": "Strong Fit", "summary": "Boa"},
            "https://ex.com/j_mid": {"url": "https://ex.com/j_mid", "score": 50, "verdict": "Moderate Fit", "summary": "Media"},
            "https://ex.com/j2": {"url": "https://ex.com/j2", "score": 84, "verdict": "Strong Fit", "summary": "Otima"},
        }

        def fake_triage(url, _jd=None):
            evaluated_calls.append(url)
            return scores[url]

        app.dependency_overrides[get_auto_mode] = lambda: self.auto
        client = TestClient(app)
        token = get_token()

        with patch.object(self.auto, "validate_ready"), \
             patch("backend.tools.painel_ia.sortear_palavras_chave_busca", side_effect=[
                 {"keywords": ["Java", "Spring"], "rationale": "R1", "source": "ai"},
                 {"keywords": ["Angular", "TS"], "rationale": "R2", "source": "ai"},
             ]), \
             patch.object(self.scanner, "start", side_effect=fake_scanner_start), \
             patch("backend.tools.painel_ia.triar_vaga_rapida", side_effect=fake_triage), \
             patch("backend.tools.painel_ia.get_provider_info", return_value={"label": "Mock AI"}), \
             patch.object(EvaluatorService, "_sync_painel_mark"):

            res = client.post(
                "/api/auto-mode/start",
                json={"min_score": 60, "continuous": True, "cooldown_seconds": 120},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(res.status_code, 200)

            for _ in range(80):
                st = client.get("/api/auto-mode/status").json()
                if st.get("phase") == "cooldown" and st.get("round") == 1:
                    break
                time.sleep(0.03)
            self.assertEqual(st["counts"]["promoted"], 1)

            client.post("/api/auto-mode/skip-cooldown", headers={"X-Painel-Token": token})

            for _ in range(80):
                st2 = client.get("/api/auto-mode/status").json()
                if st2.get("phase") == "cooldown" and st2.get("round") == 2:
                    break
                time.sleep(0.03)

            client.post("/api/auto-mode/cancel", headers={"X-Painel-Token": token})
            for _ in range(50):
                if not client.get("/api/auto-mode/status").json()["running"]:
                    break
                time.sleep(0.03)

            self.assertEqual(st2["counts"]["promoted"], 2)
            # j_mid não foi re-avaliada na rodada 2 e continua visível na lista de pendentes
            self.assertEqual(evaluated_calls, ["https://ex.com/j1", "https://ex.com/j_mid", "https://ex.com/j2"])
            pending_urls = [j["url"] for j in self.scanner.load_results()["new"]]
            self.assertIn("https://ex.com/j_mid", pending_urls)
            self.assertNotIn("https://ex.com/j1", pending_urls)
            self.assertNotIn("https://ex.com/j2", pending_urls)

    def test_sortear_palavras_chave_rotates_on_duplicate_ai_reply(self):
        fake_areas = [
            {"id": "a1", "title": "Backend", "keywords": ["Java", "Spring", "Kafka"]},
            {"id": "a2", "title": "Frontend", "keywords": ["Angular", "TypeScript", "RxJS"]},
        ]
        with patch("backend.tools.painel_ia.candidate_profile", return_value="Java, Spring, Angular, TypeScript"), \
             patch("backend.tools.painel_ia.call_llm", return_value='{"keywords": ["Angular", "Spring"], "rationale": "Dup"}'), \
             patch("painel_perfil.extract_cv_areas", return_value=fake_areas):
            out = painel_ia.sortear_palavras_chave_busca(
                avoid_recent=["Angular, Spring"],
                region="all",
                mode="recruiters",
            )
        self.assertEqual(out["source"], "cv_fallback")
        self.assertNotEqual({k.lower() for k in out["keywords"]}, {"angular", "spring"})

    def test_recruiters_auto_mode_collects_github_and_portal_urls(self):
        import time

        live_recruiter = RecruiterService(repo=self.repo, enable_live_feeds=True)
        auto_live = AutoModeService(
            repo=self.repo,
            scanner=self.scanner,
            evaluator=self.evaluator,
            recruiter_service=live_recruiter,
        )

        def fake_github_sync(*args, **kwargs):
            live_recruiter.add_pasted_post(
                raw_text="Vaga Python FastAPI Junior! CV: vagas@mkdigital.ch",
                url="https://github.com/backend-br/vagas/issues/12493",
                title="[Remoto] Back-end Júnior Python/AI",
                company="backend-br/vagas",
            )
            with self.repo.conn:
                self.repo.conn.execute(
                    "UPDATE recruiter_posts SET portal = 'github-vagas' WHERE url = ?",
                    ("https://github.com/backend-br/vagas/issues/12493",),
                )
            kwargs["_collected_urls"].add("https://github.com/backend-br/vagas/issues/12493")
            return 1

        app.dependency_overrides[get_auto_mode] = lambda: auto_live
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        client = TestClient(app)
        token = get_token()

        with patch.object(auto_live, "validate_ready"), \
             patch("backend.tools.painel_ia.sortear_palavras_chave_busca", return_value={"keywords": ["Python", "FastAPI"], "rationale": "Stack BR", "source": "ai"}), \
             patch.object(live_recruiter, "sync_from_hn", return_value=0), \
             patch.object(live_recruiter, "sync_from_recent_scrapes", return_value=0), \
             patch.object(live_recruiter, "sync_from_github_repos", side_effect=fake_github_sync), \
             patch.object(live_recruiter, "sync_from_remotive", return_value=0), \
             patch.object(live_recruiter, "sync_from_live_portals", return_value=0), \
             patch("backend.tools.painel_ia.triar_post_recrutador", return_value={
                 "classification": "vaga_ativa",
                 "best_email": "vagas@mkdigital.ch",
                 "score": 88,
                 "verdict": "Strong Fit",
                 "summary": "Aderência total ao perfil.",
             }), \
             patch("backend.tools.painel.unmark_interested", return_value=True):
            res = client.post(
                "/api/recruiters/auto/start",
                json={"min_score": 60, "continuous": False},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(res.status_code, 200)
            st = {}
            for _ in range(60):
                st = client.get("/api/auto-mode/status").json()
                if not st["running"]:
                    break
                time.sleep(0.04)

        self.assertEqual(st["phase"], "done")
        self.assertEqual(st["counts"]["found"], 1)
        self.assertEqual(st["counts"]["promoted"], 1)

    def test_recruiters_wake_if_recruiter_cooldown_and_auto_round_triages_linkedin_post(self):
        import time

        live_recruiter = RecruiterService(repo=self.repo, enable_live_feeds=True)
        auto_live = AutoModeService(
            repo=self.repo,
            scanner=self.scanner,
            evaluator=self.evaluator,
            recruiter_service=live_recruiter,
        )

        # Testa wake_if_recruiter_cooldown apenas em mode='recruiters' e phase='cooldown'
        with auto_live._lock:
            auto_live.state.update({"running": True, "mode": "recruiters", "phase": "cooldown"})
        self.assertTrue(auto_live.wake_if_recruiter_cooldown())
        self.assertTrue(auto_live._skip_cooldown_event.is_set())

        auto_live._skip_cooldown_event.clear()
        auto_live._wake_event.clear()
        with auto_live._lock:
            auto_live.state.update({"running": True, "mode": "jobs", "phase": "cooldown"})
        self.assertFalse(auto_live.wake_if_recruiter_cooldown())
        with auto_live._lock:
            auto_live.state.update({"running": False, "mode": "jobs", "phase": "idle"})

        from backend.api.deps import get_recruiter_service

        app.dependency_overrides[get_auto_mode] = lambda: auto_live
        app.dependency_overrides[get_recruiter_service] = lambda: live_recruiter
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        client = TestClient(app)
        token = get_token()

        # Importa via rota real /paste-batch post do LinkedIn sobre stack diferente da palavra-chave da rodada
        paste_res = client.post(
            "/api/recruiters/paste-batch",
            json={
                "items": [{
                    "raw_text": "Vaga Python/Go Cloud Remote! Enviar CV para people@cloudli.dev",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:7525862923169132544/",
                    "title": "Cloud Python/Go Engineer",
                    "company": "CloudLI",
                }]
            },
            headers={"X-Painel-Token": token},
        )
        self.assertEqual(paste_res.status_code, 200)
        self.assertEqual(paste_res.json()["imported"], 1)

        with patch.object(auto_live, "validate_ready"), \
             patch("backend.tools.painel_ia.sortear_palavras_chave_busca", return_value={"keywords": ["Angular"], "rationale": "Front", "source": "ai"}), \
             patch.object(live_recruiter, "sync_from_jobs", return_value={"scanned": 0, "posts_with_email": 0, "synced": 0}), \
             patch.object(live_recruiter, "sync_from_hn", return_value=0), \
             patch.object(live_recruiter, "sync_from_recent_scrapes", return_value=0), \
             patch.object(live_recruiter, "sync_from_github_repos", return_value=0), \
             patch.object(live_recruiter, "sync_from_remotive", return_value=0), \
             patch.object(live_recruiter, "sync_from_live_portals", return_value=0), \
             patch("backend.tools.painel_ia.triar_post_recrutador", return_value={
                 "classification": "vaga_ativa",
                 "best_email": "people@cloudli.dev",
                 "score": 84,
                 "verdict": "Strong Fit",
                 "summary": "Vaga capturada no LinkedIn e compatível.",
             }), \
             patch("backend.tools.painel.unmark_interested", return_value=True):
            res = client.post(
                "/api/recruiters/auto/start",
                json={"min_score": 60, "continuous": False},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(res.status_code, 200)
            st = {}
            for _ in range(60):
                st = client.get("/api/auto-mode/status").json()
                if not st["running"]:
                    break
                time.sleep(0.04)

        self.assertEqual(st["phase"], "done")
        self.assertEqual(st["counts"]["to_screen"], 1)
        self.assertEqual(st["counts"]["promoted"], 1)

    def test_recruiters_auto_round_triages_urlless_linkedin_post_via_collected_post_ids(self):
        import time
        from types import SimpleNamespace

        fake_li_worker = SimpleNamespace(
            search_content_posts=lambda q, force=False, should_stop=None: {
                "ok": True,
                "cards_total": 1,
                "posts": [{
                    "raw_text": "Vaga Rust Backend sem permalink! Enviar CV para rustjobs@nouri.dev",
                    "company": "NouriSystems",
                    "title": "Rust Backend Dev",
                    "url": "",
                }],
            }
        )
        live_recruiter = RecruiterService(
            repo=self.repo,
            enable_live_feeds=True,
            linkedin_worker=fake_li_worker,
        )
        auto_live = AutoModeService(
            repo=self.repo,
            scanner=self.scanner,
            evaluator=self.evaluator,
            recruiter_service=live_recruiter,
        )
        app.dependency_overrides[get_auto_mode] = lambda: auto_live
        app.dependency_overrides[get_tracker] = lambda: self.tracker
        client = TestClient(app)
        token = get_token()

        with patch.object(auto_live, "validate_ready"), \
             patch("backend.tools.painel_ia.sortear_palavras_chave_busca", return_value={"keywords": ["Angular"], "rationale": "Front", "source": "ai"}), \
             patch.object(live_recruiter, "sync_from_jobs", return_value={"scanned": 0, "posts_with_email": 0, "synced": 0}), \
             patch.object(live_recruiter, "sync_from_hn", return_value=0), \
             patch.object(live_recruiter, "sync_from_recent_scrapes", return_value=0), \
             patch.object(live_recruiter, "sync_from_github_repos", return_value=0), \
             patch.object(live_recruiter, "sync_from_remotive", return_value=0), \
             patch.object(live_recruiter, "sync_from_live_portals", return_value=0), \
             patch("backend.tools.painel_ia.triar_post_recrutador", return_value={
                 "classification": "vaga_ativa",
                 "best_email": "rustjobs@nouri.dev",
                 "score": 81,
                 "verdict": "Strong Fit",
                 "summary": "Post do LinkedIn sem URL capturado por ID.",
             }), \
             patch("backend.tools.painel.unmark_interested", return_value=True):
            res = client.post(
                "/api/recruiters/auto/start",
                json={"min_score": 60, "continuous": False},
                headers={"X-Painel-Token": token},
            )
            self.assertEqual(res.status_code, 200)
            st = {}
            for _ in range(60):
                st = client.get("/api/auto-mode/status").json()
                if not st["running"]:
                    break
                time.sleep(0.04)

        self.assertEqual(st["phase"], "done")
        self.assertEqual(st["counts"]["to_screen"], 1)
        self.assertEqual(st["counts"]["promoted"], 1)
        interested = self.repo.list_jobs(status="interested")
        self.assertEqual(len(interested), 1)
        self.assertEqual(interested[0]["portal"], "linkedin_post")
        self.assertEqual(interested[0]["rank_score"], 81)


if __name__ == "__main__":
    unittest.main()
