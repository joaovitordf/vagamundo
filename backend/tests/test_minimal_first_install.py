"""End-to-end regressions for zero-tracked-edits first-time installation."""

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
REPO_ROOT = BACKEND_DIR.parent

for p in (str(REPO_ROOT), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.app import app, get_token  # noqa: E402
from backend.api.deps import get_profile  # noqa: E402
from backend.core.profile import ProfileService  # noqa: E402
from backend.db.repository import Repository  # noqa: E402
from backend.tools import (  # noqa: E402
    ai_providers,
    install_portal_clis,
    painel,
    painel_ia,
    painel_perfil,
    scrape_run,
)
from backend.tools.ia import context as ia_context  # noqa: E402


PLACEHOLDER_CLAUDE = """# CLAUDE.md
Nome: [YOUR_NAME]
Cargo-alvo: [YOUR_PRIMARY_JOB_TITLE_1]
"""

PLACEHOLDER_PROFILE = """# Perfil
**Nome:** [YOUR_NAME]
**E-mail:** [YOUR_EMAIL]
**Local:** [YOUR_CITY]
"""

PLACEHOLDER_QUERIES = """# Buscas

### Prioridade 1: Geral

```
gupy-search: -q "[YOUR_PRIMARY_JOB_TITLE_1]" --state [YOUR_REGION]
```
"""


def _seed_fresh_repo(root: Path) -> dict[str, Path]:
    """Create a clean fresh-clone directory tree with only placeholder tracked files."""
    backend_root = root / "backend"
    docs = backend_root / "documents"
    perfil_dir = docs / "perfil"
    claude_cache = docs / "applications" / "_painel"
    skills_dir = root / ".claude" / "skills"
    profile_md = skills_dir / "job-application-assistant" / "01-candidate-profile.md"
    queries_md = skills_dir / "job-scraper" / "search-queries.md"
    claude_md = root / "CLAUDE.md"

    for d in (perfil_dir, docs / "cv", docs / "linkedin", claude_cache, profile_md.parent, queries_md.parent):
        d.mkdir(parents=True, exist_ok=True)

    claude_md.write_text(PLACEHOLDER_CLAUDE, encoding="utf-8")
    profile_md.write_text(PLACEHOLDER_PROFILE, encoding="utf-8")
    queries_md.write_text(PLACEHOLDER_QUERIES, encoding="utf-8")
    return {
        "root": root,
        "backend": backend_root,
        "docs": docs,
        "perfil": perfil_dir,
        "answers": perfil_dir / "respostas.json",
        "claude_cache": claude_cache,
        "claude_md": claude_md,
        "profile_md": profile_md,
        "queries_md": queries_md,
    }


def _profile_patches(paths: dict[str, Path]) -> list:
    return [
        patch.object(painel, "ROOT", paths["backend"]),
        patch.object(painel, "CLAUDE_DIR", paths["claude_cache"]),
        patch.object(painel_ia, "ROOT", paths["backend"]),
        patch.object(painel_ia, "DOCUMENTS", paths["docs"]),
        patch.object(painel_ia, "PAINEL_DIR", paths["claude_cache"]),
        patch.object(painel_ia, "PROFILE_MD", paths["profile_md"]),
        patch.object(painel_ia, "CLAUDE_MD", paths["claude_md"]),
        patch.object(painel_perfil, "ROOT", paths["backend"]),
        patch.object(painel_perfil, "REPO_ROOT", paths["root"]),
        patch.object(painel_perfil, "DOCUMENTS", paths["docs"]),
        patch.object(painel_perfil, "ANSWERS", paths["answers"]),
    ]


class EnvLoadingTests(unittest.TestCase):
    def test_root_env_fallback_and_backend_env_override(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            t = Path(tmp)
            root_env = t / ".env"
            backend_env = t / "backend" / ".env"
            backend_env.parent.mkdir(parents=True, exist_ok=True)

            backend_env.write_text(
                "AI_PROVIDER=gemini\nGEMINI_API_KEY=legacy-key\nOPENAI_API_KEY=from-legacy\n",
                encoding="utf-8",
            )
            with patch.object(ai_providers, "LEGACY_ENV_PATH", backend_env), \
                 patch.object(ai_providers, "ENV_PATH", root_env), \
                 patch.object(ai_providers, "_DEFAULT_ENV_PATH", root_env):
                loaded_legacy_only = ai_providers.load_env_file()
                self.assertEqual(loaded_legacy_only["AI_PROVIDER"], "gemini")
                self.assertEqual(loaded_legacy_only["GEMINI_API_KEY"], "legacy-key")

                root_env.write_text("GEMINI_API_KEY=root-override\n", encoding="utf-8")
                loaded_merged = ai_providers.load_env_file()
                self.assertEqual(loaded_merged["GEMINI_API_KEY"], "root-override")
                self.assertEqual(loaded_merged["OPENAI_API_KEY"], "from-legacy")

    def test_patched_env_path_stays_isolated_from_repo_env(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            t = Path(tmp)
            legacy_env = t / ".env"
            isolated_env = t / "isolated.env"
            legacy_env.write_text("GEMINI_API_KEY=should-not-leak\n", encoding="utf-8")

            with patch.object(ai_providers, "LEGACY_ENV_PATH", legacy_env), \
                 patch.object(ai_providers, "ENV_PATH", isolated_env):
                self.assertEqual(ai_providers.load_env_file(), {})

    def test_save_settings_writes_root_env_and_mirrors_existing_legacy_env(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            t = Path(tmp)
            root_env = t / ".env"
            backend_env = t / "backend" / ".env"
            backend_env.parent.mkdir(parents=True, exist_ok=True)

            with patch.object(ai_providers, "ENV_PATH", root_env), \
                 patch.object(ai_providers, "_DEFAULT_ENV_PATH", root_env), \
                 patch.object(ai_providers, "LEGACY_ENV_PATH", backend_env):
                ai_providers.save_settings(
                    {
                        "provider": "gemini",
                        "consent": True,
                        "providers": {"gemini": {"api_key": "root-first"}},
                    }
                )
                self.assertTrue(root_env.exists())
                self.assertFalse(backend_env.exists())
                self.assertEqual(ai_providers.load_env_file().get("GEMINI_API_KEY"), "root-first")

                backend_env.write_text("AI_PROVIDER=openai\nGEMINI_API_KEY=stale-legacy\n", encoding="utf-8")
                ai_providers.save_settings(
                    {
                        "provider": "gemini",
                        "consent": True,
                        "providers": {"gemini": {"api_key": "updated-key"}},
                    }
                )
                self.assertIn("GEMINI_API_KEY=updated-key", root_env.read_text(encoding="utf-8"))
                self.assertIn("GEMINI_API_KEY=updated-key", backend_env.read_text(encoding="utf-8"))

                ai_providers.save_settings(
                    {
                        "providers": {"gemini": {"clear_key": True}},
                    }
                )
                self.assertEqual(ai_providers.load_env_file().get("GEMINI_API_KEY"), "")
                backend_text = backend_env.read_text(encoding="utf-8")
                self.assertNotIn("GEMINI_API_KEY=updated-key", backend_text)
                self.assertIn("GEMINI_API_KEY=", backend_text)


class LocalProfileWithoutTrackedEditsTests(unittest.TestCase):
    def test_profile_and_queries_live_under_gitignored_perfil_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            paths = _seed_fresh_repo(Path(tmp))
            for p in _profile_patches(paths):
                p.start()
                self.addCleanup(p.stop)

            self.assertFalse(painel_perfil.is_customized_md(PLACEHOLDER_PROFILE))
            self.assertFalse(painel_perfil.is_customized_md(PLACEHOLDER_CLAUDE))
            self.assertFalse(painel_perfil.profile_ready())
            self.assertIsNone(painel_perfil.profile_text())

            svc = ProfileService()
            answers_in = {
                "nome": "Joana Silva",
                "cargos": ["Engenheira de Software", "Desenvolvedora Backend"],
                "palavras_chave_sorteio": ["Python", "FastAPI"],
                "senioridade": ["pleno", "senior"],
                "cidades": ["Belo Horizonte"],
                "remoto": ["remoto", "hibrido"],
                "modelo": ["clt", "pj"],
            }
            svc.save_profile_answers(answers_in)

            # Tracked templates must remain completely untouched
            self.assertEqual(paths["profile_md"].read_text(encoding="utf-8"), PLACEHOLDER_PROFILE)
            self.assertEqual(paths["claude_md"].read_text(encoding="utf-8"), PLACEHOLDER_CLAUDE)
            self.assertEqual(paths["queries_md"].read_text(encoding="utf-8"), PLACEHOLDER_QUERIES)

            # Ready immediately from answers + auto-generated local search-queries.md
            self.assertTrue(painel_perfil.profile_ready())
            payload = painel_perfil.get_cv_areas_payload()
            self.assertEqual(payload["source"], "profile")
            labels = [a["label"] for a in payload["areas"]]
            self.assertEqual(labels, ["Python", "FastAPI"])
            self.assertTrue(any("Python" in a.get("keywords", []) for a in payload["areas"]))

            local_q = painel_perfil.local_queries_path()
            self.assertTrue(local_q.exists())
            parsed_calls = scrape_run.parse_queries(local_q.read_text(encoding="utf-8"))
            self.assertTrue(parsed_calls, "local search-queries.md should yield executable queries")

            # AI profile generation stores mirror in backend/documents/perfil/candidate-profile.md
            with patch.object(painel_ia, "montar_perfil", return_value="# Perfil IA\n\n## Resumo Executivo\nExperiente em Python.\n"):
                svc.build_ai_profile()

            self.assertIn("Perfil IA", painel_perfil.profile_text() or "")
            self.assertTrue(painel_perfil.local_profile_path().exists())
            self.assertEqual(paths["profile_md"].read_text(encoding="utf-8"), PLACEHOLDER_PROFILE)


class ContextFallbackWithoutCanonicalMdTests(unittest.TestCase):
    def test_ia_context_uses_local_profile_and_uploaded_txt_cv(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            paths = _seed_fresh_repo(Path(tmp))
            (paths["docs"] / "cv" / "Curriculo_PT.txt").write_text(
                "Ana Beatriz Costa\nEngenheira de Dados com 5 anos de Python, SQL e Spark.",
                encoding="utf-8",
            )
            (paths["perfil"] / "candidate-profile.md").write_text(
                "# Perfil Consolidado\nNome: Ana Beatriz Costa\nSenioridade: Pleno/Sênior\n",
                encoding="utf-8",
            )
            paths["answers"].write_text(
                json.dumps({
                    "cargos": ["Engenheira de Dados"],
                    "senioridade": ["pleno"],
                    "modelo": ["clt"],
                    "remoto": ["remoto"],
                    "cidades": ["São Paulo"],
                    "idiomas": ["Português (nativo)", "Inglês (avançado)"],
                }),
                encoding="utf-8",
            )

            for p in _profile_patches(paths):
                p.start()
                self.addCleanup(p.stop)

            full = ia_context.candidate_profile(include_claude_md=True, language="pt")
            self.assertIn("Ana Beatriz Costa", full)
            self.assertIn("Curriculo_PT", full)
            self.assertIn("Pleno", full)

            compact = ia_context._compact_candidate_profile(language="pt")
            self.assertIn("Ana Beatriz Costa", compact)
            self.assertEqual(ia_context.get_candidate_name(), "Ana Beatriz Costa")


class ScrapeRunFallbackTests(unittest.TestCase):
    def test_scrape_run_uses_answers_and_synthesizes_calls_without_queries_md(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            paths = _seed_fresh_repo(Path(tmp))
            answers_file = paths["answers"]
            answers_file.write_text(
                json.dumps({
                    "cargos": ["Engenheiro Backend"],
                    "senioridade": ["junior", "pleno"],
                }),
                encoding="utf-8",
            )
            fake_local_queries = paths["perfil"] / "search-queries.md"  # intentionally absent
            fake_seen = paths["backend"] / "seen_jobs.json"
            fake_tracker = paths["docs"] / "job_search_tracker.csv"
            out_file = Path(tmp) / "scrape_out.json"
            captured = []

            real_collect = scrape_run.collect

            def fake_collect(calls, portals, seen, accept, jobage, runner=None, workers=4):
                captured.append((calls, accept))
                return real_collect([], portals, seen, accept, jobage)

            with patch.object(scrape_run, "QUERIES", paths["queries_md"]), \
                 patch.object(scrape_run, "LOCAL_QUERIES", fake_local_queries), \
                 patch.object(scrape_run, "LOCAL_ANSWERS", answers_file), \
                 patch.object(scrape_run, "PROFILE", paths["profile_md"]), \
                 patch.object(scrape_run, "SEEN", fake_seen), \
                 patch.object(scrape_run, "TRACKER", fake_tracker), \
                 patch.object(scrape_run, "collect", side_effect=fake_collect):
                self.assertEqual(scrape_run.local_target_seniority(), ["junior", "pleno"])

                # 1. Explicit --query when QUERIES only has placeholders
                rc_explicit = scrape_run.main(["search", "--query", "python", "--out", str(out_file)])
                self.assertEqual(rc_explicit, 0)
                self.assertTrue(captured and captured[0][0], "expected synthesized portal calls")
                self.assertEqual(captured[0][1], ["junior", "pleno"])

                # 2. No --query and no search-queries.md -> falls back to answers.cargos[0]
                rc_auto = scrape_run.main(["search", "--out", str(out_file)])
                self.assertEqual(rc_auto, 0)
                self.assertEqual(len(captured), 2)
                self.assertTrue(any("Engenheiro Backend" in " ".join(c[2]) for c in captured[1][0]))


class PortalDiscoveryTests(unittest.TestCase):
    def test_all_24_portals_follow_standard_cli_layout(self):
        clis = install_portal_clis.discover()
        names = [p.parent.name for p in clis]
        self.assertGreaterEqual(len(names), 24)
        for normalized in ("ashby-search", "hn-search", "jobicy-search", "remoteok-search"):
            self.assertIn(normalized, names)
            base = REPO_ROOT / ".agents" / "skills" / normalized
            self.assertTrue((base / "cli" / "package.json").is_file())
            self.assertTrue((base / "cli" / "tsconfig.json").is_file())
            self.assertTrue((base / "cli" / "tests" / "cli.test.ts").is_file())
            self.assertFalse((base / "package.json").exists())
            self.assertFalse((base / "tsconfig.json").exists())
            self.assertFalse((base / "tests").exists())


class FreshCloneEndToEndApiTests(unittest.TestCase):
    def test_first_install_flow_via_api_needs_zero_tracked_edits(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            t = Path(tmp)
            paths = _seed_fresh_repo(t / "clone")
            env_path = t / ".env"
            db_path = t / "fresh.db"
            repo = Repository(db_path)
            os.environ["VAGAMUNDO_DB_PATH"] = str(db_path)
            self.addCleanup(lambda: os.environ.pop("VAGAMUNDO_DB_PATH", None))

            legacy_env = t / "legacy_backend.env"
            patches = _profile_patches(paths) + [
                patch.object(ai_providers, "LEGACY_ENV_PATH", legacy_env),
                patch.object(ai_providers, "ENV_PATH", env_path),
                patch.object(ai_providers, "_DEFAULT_ENV_PATH", env_path),
                patch.object(painel, "EVOLUTION_PATH", paths["docs"] / "evolucao.json"),
            ]
            for p in patches:
                p.start()
                self.addCleanup(p.stop)

            profile_svc = ProfileService()
            app.dependency_overrides[get_profile] = lambda: profile_svc
            self.addCleanup(lambda: app.dependency_overrides.clear())
            client = TestClient(app)
            token = get_token()
            headers = {"X-Painel-Token": token}

            # 1. Save AI provider via Web UI (writes only .env inside isolated tmp)
            s_resp = client.post(
                "/api/settings",
                json={"provider": "gemini", "consent": True, "gemini_key": "fake-key-for-test"},
                headers=headers,
            )
            self.assertEqual(s_resp.status_code, 200)

            # 2. Upload PDF CV via Web UI (/api/upload)
            pdf_b64 = base64.b64encode(b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n").decode()
            u_resp = client.post(
                "/api/upload",
                json={"kind": "cv", "name": "meu_cv.pdf", "data": pdf_b64},
                headers=headers,
            )
            self.assertEqual(u_resp.status_code, 200)

            # 3. Save profile answers via Web UI (/api/profile)
            p_save = client.post(
                "/api/profile",
                json={
                    "cargos": ["Desenvolvedor Full Stack"],
                    "palavras_chave_sorteio": ["TypeScript", "Python"],
                    "senioridade": ["pleno"],
                },
                headers=headers,
            )
            self.assertEqual(p_save.status_code, 200)

            # 4. Read profile back -> ready=True without touching tracked .claude files
            p_get = client.get("/api/profile")
            self.assertEqual(p_get.status_code, 200)
            body = p_get.json()
            self.assertTrue(body["ready"])
            self.assertEqual(body["answers"]["cargos"], ["Desenvolvedor Full Stack"])
            self.assertEqual(body["files"]["cv"][0]["name"], "meu_cv.pdf")
            self.assertEqual(body["privacy"]["status"], "local")
            self.assertEqual(paths["profile_md"].read_text(encoding="utf-8"), PLACEHOLDER_PROFILE)
            self.assertEqual(paths["claude_md"].read_text(encoding="utf-8"), PLACEHOLDER_CLAUDE)
            self.assertIsNotNone(repo)


class _FakePdfPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakePdfReader:
    def __init__(self, text: str) -> None:
        self.pages = [_FakePdfPage(text)]


class PdfAutoOrganizeProfileTests(unittest.TestCase):
    def test_extrair_respostas_normalizes_aliases_and_ignores_unknown_or_subjective_fields(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            paths = _seed_fresh_repo(Path(tmp))
            (paths["docs"] / "cv" / "cv.pdf").write_bytes(b"%PDF-1.4\nfake\n")

            long_cv_text = ("Experiencia em software. " * 300) + "\nIdiomas\nPortuguês: Nativo\nInglês: C1\n"
            self.assertGreater(len(long_cv_text), 6500)

            fake_llm_reply = json.dumps(
                {
                    "cidade": "Campinas - SP",
                    "cargos": "Engenheira de Software\nArquiteta Python",
                    "palavras_chave_sorteio": ["Python", "FastAPI", "python", "Docker"],
                    "senioridade": ["Sênior", "Pleno"],
                    "idiomas": ["Português - nativo", "Inglês - avançado"],
                    "genero": "Feminino",
                    # Campos subjetivos/removidos/fora do escopo que o LLM pode tentar inventar devem ser filtrados
                    "idioma_cv": "PT-BR",
                    "comportamental": "Analítica",
                    "modelo": ["híbrido", "remoto"],
                    "regimes": ["clt", "PJ"],
                    "locais": "Campinas - SP",
                    "setores": ["Crédito"],
                    "situacao": "Bacharel...",
                    "empresas": ["Antiga Empresa"],
                    "motivacao": "Genérica",
                    "pretensao_clt": "R$ 5.000",
                    "deal_breakers": "Inventado",
                    "desconhecido": "valor",
                }
            )
            captured_prompts = []

            def _capture_llm(prompt: str, **_kwargs):
                captured_prompts.append(prompt)
                return fake_llm_reply

            patches = _profile_patches(paths) + [
                patch("pypdf.PdfReader", return_value=_FakePdfReader(long_cv_text)),
                patch.object(painel_ia, "call_llm", side_effect=_capture_llm),
            ]
            for p in patches:
                p.start()
                self.addCleanup(p.stop)

            extracted = painel_ia.extrair_respostas_de_documentos(existing_answers={})
            self.assertTrue(captured_prompts)
            self.assertIn("Inglês: C1", captured_prompts[0])
            self.assertEqual(extracted["cidade"], "Campinas - SP")
            self.assertEqual(extracted["cargos"], ["Engenheira de Software", "Arquiteta Python"])
            self.assertEqual(extracted["palavras_chave_sorteio"], ["Python", "FastAPI", "Docker"])
            self.assertEqual(extracted["senioridade"], ["pleno", "senior"])
            self.assertEqual(extracted["idiomas"], ["Português - nativo", "Inglês - avançado"])
            self.assertEqual(extracted["genero"], "feminino")
            for disallowed in (
                "idioma_cv",
                "comportamental",
                "modelo",
                "regimes",
                "locais",
                "setores",
                "situacao",
                "empresas",
                "motivacao",
                "pretensao_clt",
                "deal_breakers",
                "desconhecido",
            ):
                self.assertNotIn(disallowed, extracted)

    def test_organize_profile_merges_safely_and_builds_local_profile(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            t = Path(tmp)
            paths = _seed_fresh_repo(t)
            (paths["docs"] / "cv" / "cv.pdf").write_bytes(b"%PDF-1.4\nfake\n")
            painel_perfil.save_answers(
                {
                    "cargos": ["Cargo Manual"],
                    "deal_breakers": "Sem presencial integral",
                    "regimes": ["CLT"],
                },
                path=paths["answers"],
            )

            extracted_json = json.dumps(
                {
                    "cidade": "Campinas - SP",
                    "cargos": ["Desenvolvedora Python"],
                    "palavras_chave_sorteio": ["Python", "FastAPI"],
                    "senioridade": ["senior"],
                    "deal_breakers": "Inventado pela IA",
                    "regimes": ["PJ"],
                }
            )

            def fake_call_llm(prompt: str, **_kwargs):
                if "ESQUEMA PERMITIDO" in prompt:
                    return extracted_json
                return "## Perfil consolidado\n\n### Identidade e objetivo\n- Joana Silva"

            legacy_env = paths["backend"] / ".env"
            root_env = paths["root"] / ".env"
            patches = _profile_patches(paths) + [
                patch.object(ai_providers, "LEGACY_ENV_PATH", legacy_env),
                patch.object(ai_providers, "ENV_PATH", root_env),
                patch.object(ai_providers, "_DEFAULT_ENV_PATH", root_env),
                patch("pypdf.PdfReader", return_value=_FakePdfReader("Joana Silva — Python / FastAPI")),
                patch.object(painel_ia, "is_available", return_value=True),
                patch.object(painel_ia, "call_llm", side_effect=fake_call_llm),
            ]
            for p in patches:
                p.start()
                self.addCleanup(p.stop)

            svc = ProfileService()
            res = svc.organize_profile_from_documents(overwrite=False)

            self.assertTrue(res["ok"])
            self.assertTrue(res["organized"])
            self.assertIn("cidade", res["updated_fields"])
            self.assertIn("palavras_chave_sorteio", res["updated_fields"])
            # Safe merge keeps pre-filled manual answers
            saved = painel_perfil.load_answers(path=paths["answers"])
            self.assertEqual(saved["cargos"], ["Cargo Manual"])
            self.assertEqual(saved["deal_breakers"], "Sem presencial integral")
            self.assertEqual(saved["regimes"], ["CLT"])
            self.assertEqual(saved["cidade"], "Campinas - SP")
            # Local artifacts created, tracked placeholders untouched
            self.assertTrue((paths["perfil"] / "search-queries.md").exists())
            self.assertTrue((paths["perfil"] / "candidate-profile.md").exists())
            self.assertEqual(paths["profile_md"].read_text(encoding="utf-8"), PLACEHOLDER_PROFILE)
            self.assertEqual(paths["claude_md"].read_text(encoding="utf-8"), PLACEHOLDER_CLAUDE)

            # With overwrite=True, objective extractable fields update while manual-only preferences stay intact
            res_over = svc.organize_profile_from_documents(overwrite=True)
            self.assertTrue(res_over["ok"])
            saved_over = painel_perfil.load_answers(path=paths["answers"])
            self.assertEqual(saved_over["cargos"], ["Desenvolvedora Python"])
            self.assertEqual(saved_over["deal_breakers"], "Sem presencial integral")
            self.assertEqual(saved_over["regimes"], ["CLT"])

    def test_organize_profile_falls_back_gracefully_without_ai_or_consent(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            t = Path(tmp)
            paths = _seed_fresh_repo(t)
            cv_file = paths["docs"] / "cv" / "cv.pdf"
            cv_file.write_bytes(b"%PDF-1.4\nfake\n")
            legacy_env = paths["backend"] / ".env"
            root_env = paths["root"] / ".env"

            patches = _profile_patches(paths) + [
                patch.object(ai_providers, "LEGACY_ENV_PATH", legacy_env),
                patch.object(ai_providers, "ENV_PATH", root_env),
                patch.object(ai_providers, "_DEFAULT_ENV_PATH", root_env),
                patch("pypdf.PdfReader", return_value=_FakePdfReader("Joana Silva — Python")),
            ]
            for p in patches:
                p.start()
                self.addCleanup(p.stop)

            svc = ProfileService()
            with patch.object(painel_ia, "is_available", return_value=False):
                no_ai = svc.organize_profile_from_documents()
            self.assertFalse(no_ai["ok"])
            self.assertFalse(no_ai["organized"])
            self.assertEqual(no_ai["reason"], "ai_unconfigured")
            self.assertTrue(cv_file.exists())

            with patch.object(painel_ia, "is_available", return_value=True), \
                 patch.object(painel_ia, "call_llm", side_effect=painel_ia.ConsentRequired("consentimento necessário")):
                no_consent = svc.organize_profile_from_documents()
            self.assertFalse(no_consent["ok"])
            self.assertFalse(no_consent["organized"])
            self.assertEqual(no_consent["reason"], "consent_required")
            self.assertTrue(cv_file.exists())

    def test_profile_organize_endpoint_http_roundtrip(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            t = Path(tmp)
            paths = _seed_fresh_repo(t)
            db_path = t / "vagamundo.db"
            legacy_env = paths["backend"] / ".env"
            root_env = paths["root"] / ".env"

            def fake_call_llm(prompt: str, **_kwargs):
                if "ESQUEMA PERMITIDO" in prompt:
                    return json.dumps(
                        {
                            "cidade": "São Paulo - SP",
                            "cargos": ["Cientista de Dados"],
                            "palavras_chave_sorteio": ["Python", "SQL"],
                            "senioridade": ["pleno"],
                        }
                    )
                return "## Perfil consolidado\n\n- Cientista de Dados"

            patches = _profile_patches(paths) + [
                patch.dict(os.environ, {"VAGAMUNDO_DB_PATH": str(db_path)}),
                patch.object(ai_providers, "LEGACY_ENV_PATH", legacy_env),
                patch.object(ai_providers, "ENV_PATH", root_env),
                patch.object(ai_providers, "_DEFAULT_ENV_PATH", root_env),
                patch("pypdf.PdfReader", return_value=_FakePdfReader("Joana Silva — Cientista de Dados")),
                patch.object(painel_ia, "is_available", return_value=True),
                patch.object(painel_ia, "call_llm", side_effect=fake_call_llm),
            ]
            for p in patches:
                p.start()
                self.addCleanup(p.stop)

            profile_svc = ProfileService()
            app.dependency_overrides[get_profile] = lambda: profile_svc
            self.addCleanup(lambda: app.dependency_overrides.clear())
            client = TestClient(app)
            headers = {"X-Painel-Token": get_token()}

            # Before uploading any PDF -> 400
            empty_resp = client.post("/api/profile/organize", json={"overwrite": False}, headers=headers)
            self.assertEqual(empty_resp.status_code, 400)

            # Upload PDF and run /api/profile/organize
            pdf_b64 = base64.b64encode(b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n").decode()
            up_resp = client.post(
                "/api/upload",
                json={"kind": "cv", "name": "joana.pdf", "data": pdf_b64},
                headers=headers,
            )
            self.assertEqual(up_resp.status_code, 200)

            org_resp = client.post("/api/profile/organize", json={"overwrite": False}, headers=headers)
            self.assertEqual(org_resp.status_code, 200)
            body = org_resp.json()
            self.assertTrue(body["ok"])
            self.assertTrue(body["organized"])
            self.assertTrue(body["profile"]["ready"])
            self.assertEqual(body["profile"]["answers"]["cargos"], ["Cientista de Dados"])


class WhitelabelAndPortalProfileTests(unittest.TestCase):
    def test_google_careers_respects_candidate_gender_on_affirmative_roles(self):
        from backend.tools import google_careers

        fem_res, fem_warn = google_careers.evaluate_google_job(
            "Software Engineer (For Women in Tech)",
            "Sao Paulo, Brazil",
            "1 year of Python experience.",
            "",
            "",
            "Women in Tech cohort",
            "",
            accept_sen={"junior", "pleno"},
            profile_ans={"genero": "feminino", "cargos": ["Software Engineer"]},
        )
        self.assertGreaterEqual(fem_res["score"], 80)
        self.assertEqual(fem_warn, [])

        masc_res, masc_warn = google_careers.evaluate_google_job(
            "Software Engineer (For Women in Tech)",
            "Sao Paulo, Brazil",
            "1 year of Python experience.",
            "",
            "",
            "Women in Tech cohort",
            "",
            accept_sen={"junior", "pleno"},
            profile_ans={"genero": "masculino", "cargos": ["Software Engineer"]},
        )
        self.assertEqual(masc_res["score"], 25)
        self.assertIn("vaga exclusiva afirmativa (Women in Tech)", masc_warn)

        unset_res, unset_warn = google_careers.evaluate_google_job(
            "Software Engineer (For Women in Tech)",
            "Sao Paulo, Brazil",
            "1 year of Python experience.",
            "",
            "",
            "Women in Tech cohort",
            "",
            accept_sen={"junior", "pleno"},
            profile_ans={"cargos": ["Software Engineer"]},
        )
        self.assertGreaterEqual(unset_res["score"], 80)
        self.assertTrue(any("confirme elegibilidade" in w for w in unset_warn))

    def test_eures_non_tech_profile_allows_non_tech_results(self):
        from unittest.mock import patch

        from backend.tools import eures, painel_perfil

        self.assertFalse(eures._queries_expect_tech(["Analista Financeiro", "Controller"]))
        self.assertTrue(eures._queries_expect_tech(["Software Engineer"]))

        non_tech_job = {
            "id": "eures-123",
            "title": "Analista Financeiro Sênior",
            "company": "Acme EU",
            "employer": "Acme EU",
            "location": "Lisbon, Portugal",
            "country_code": "PT",
            "date": "2026-11-10",
            "description": "IFRS, controladoria e fechamento contábil",
            "languages": ["pt", "en"],
            "portal": "eures",
            "workplace_type": "on-site",
            "url": "https://europa.eu/eures/portal/jv-se/jv-details/123?lang=en",
        }

        with (
            patch.object(
                painel_perfil,
                "load_answers",
                return_value={
                    "cargos": ["Analista Financeiro"],
                    "palavras_chave_sorteio": ["Controladoria", "IFRS"],
                },
            ),
            patch.object(
                eures,
                "search_eures",
                return_value={"total": 1, "jobs": [non_tech_job]},
            ),
        ):
            self.assertEqual(
                eures._profile_eures_keywords(),
                ["Analista Financeiro", "Controladoria", "IFRS"],
            )
            results = eures.fetch_eures_for_panel(focus="all", max_per_query=5)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["title"], "Analista Financeiro Sênior")

        with (
            patch.object(
                painel_perfil,
                "load_answers",
                return_value={"cargos": ["Software Engineer"]},
            ),
            patch.object(
                eures,
                "search_eures",
                return_value={"total": 1, "jobs": [non_tech_job]},
            ),
        ):
            self.assertEqual(eures.fetch_eures_for_panel(focus="all", max_per_query=5), [])


if __name__ == "__main__":
    unittest.main()
