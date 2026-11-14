from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_linkedin_worker, get_recruiter_service, get_repository
from backend.api.security import get_token
from backend.core.constants import ROOT
from backend.core.linkedin_browser import (
    DEFAULT_LINKEDIN_COOLDOWN_MINUTES,
    DEFAULT_LINKEDIN_MAX_DAILY,
    DEFAULT_LINKEDIN_MAX_SCROLLS,
    LINKEDIN_FEED_URL,
    LinkedInBrowserWorker,
    build_linkedin_content_search_url,
    find_chromium_executable,
)
from backend.core.recruiter_service import RecruiterService
from backend.db.repository import Repository


class _FakeWebSocket:
    """In-memory CDP WebSocket mock answering Runtime.evaluate / Target commands."""

    def __init__(self, eval_responder):
        self._responder = eval_responder
        self._responses: list[str] = []
        self.commands: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def send(self, payload: str) -> None:
        cmd = json.loads(payload)
        self.commands.append(cmd)
        method = cmd.get("method")
        req_id = cmd.get("id")
        if method == "Runtime.evaluate":
            expr = (cmd.get("params") or {}).get("expression", "")
            val = self._responder(expr)
            result = {"result": {"value": val}}
        elif method == "Target.createTarget":
            result = {"targetId": "TARGET-1"}
        else:
            result = {}
        self._responses.append(json.dumps({"id": req_id, "result": result}))

    def recv(self, timeout=None) -> str:
        return self._responses.pop(0)


class _FakeProc:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if (self.terminated or self.killed) else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class LinkedInBrowserWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profile_dir = self.root / "browser_profile"
        self.state_dir = self.root / "state"
        self.fake_chrome = self.root / "chrome.exe"
        self.fake_chrome.write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _make_worker(self) -> LinkedInBrowserWorker:
        return LinkedInBrowserWorker(
            profile_dir=self.profile_dir,
            state_dir=self.state_dir,
            executable_finder=lambda: str(self.fake_chrome),
        )

    def _seed_session_files(self) -> None:
        net_dir = self.profile_dir / "Default" / "Network"
        net_dir.mkdir(parents=True, exist_ok=True)
        (net_dir / "Cookies").write_text("cookie-blob", encoding="utf-8")

    def test_gitignore_ignores_isolated_browser_profile(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/browser_profile/", gitignore)

    def test_find_chromium_executable_respects_env_override(self):
        with patch.dict(os.environ, {"VAGAMUNDO_CHROME_PATH": str(self.fake_chrome)}):
            self.assertEqual(find_chromium_executable(), str(self.fake_chrome))

    def test_build_linkedin_content_search_url_encodes_terms_and_date_sort(self):
        from urllib.parse import unquote

        url = build_linkedin_content_search_url("Python, Angular, TypeScript")
        self.assertTrue(url.startswith("https://www.linkedin.com/search/results/content/?keywords="))
        decoded = unquote(url)
        self.assertIn("keywords=Python vaga", decoded)
        self.assertNotIn("OR", decoded)
        self.assertNotIn("TypeScript", decoded)
        self.assertIn('sortBy="date_posted"', decoded)
        self.assertIn('datePosted="past-week"', decoded)

    def test_default_state_uses_visible_browser_and_safe_limits(self):
        worker = self._make_worker()
        status = worker.get_status()
        self.assertEqual(status["status"], "not_connected")
        self.assertFalse(status["headless"])
        self.assertEqual(status["cooldown_minutes"], DEFAULT_LINKEDIN_COOLDOWN_MINUTES)
        self.assertEqual(status["max_daily_searches"], DEFAULT_LINKEDIN_MAX_DAILY)
        self.assertEqual(status["max_scrolls"], DEFAULT_LINKEDIN_MAX_SCROLLS)
        self.assertTrue(status["enabled"])

    def test_update_config_persists_and_clamps_bounds(self):
        worker = self._make_worker()
        updated = worker.update_config(
            {
                "enabled": False,
                "cooldown_minutes": -5,  # clamped to >= 0
                "max_daily_searches": 999,  # clamped to <= 500
                "max_scrolls": 20,  # clamped to <= 8
            }
        )
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["cooldown_minutes"], 0)
        self.assertEqual(updated["max_daily_searches"], 500)
        self.assertEqual(updated["max_scrolls"], 8)

        reloaded = self._make_worker().get_status()
        self.assertFalse(reloaded["enabled"])
        self.assertEqual(reloaded["cooldown_minutes"], 0)

    def test_legacy_cooldown_and_daily_cap_state_migrates_to_unlimited(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "linkedin_worker_state.json").write_text(
            json.dumps({"cooldown_minutes": 20, "max_daily_searches": 15, "last_status": "connected"}),
            encoding="utf-8",
        )
        migrated = self._make_worker().get_status()
        self.assertEqual(migrated["cooldown_minutes"], 0)
        self.assertEqual(migrated["max_daily_searches"], 0)
        self.assertEqual(migrated["cooldown_remaining_seconds"], 0)

    def test_open_connect_window_launches_visible_browser_and_detects_login(self):
        worker = self._make_worker()
        launched_cmds: list[list[str]] = []
        connect_proc = _FakeProc()
        verify_proc = _FakeProc()
        procs = [connect_proc, verify_proc]

        def fake_popen(cmd, **_kwargs):
            launched_cmds.append(list(cmd))
            proc = procs.pop(0) if procs else _FakeProc()
            if any("--remote-debugging-port" in str(a) for a in cmd):
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                (self.profile_dir / "DevToolsActivePort").write_text("9222\n/devtools/browser/1\n", encoding="utf-8")
            return proc

        page_tabs = json.dumps(
            [{"type": "page", "id": "T1", "url": "https://www.linkedin.com/feed/", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/T1"}]
        ).encode("utf-8")

        class _Resp:
            def __init__(self, data: bytes):
                self._data = data

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def read(self):
                return self._data

        with (
            patch("backend.core.linkedin_browser.subprocess.Popen", side_effect=fake_popen),
            patch("backend.core.linkedin_browser.time.sleep"),
        ):
            status = worker.open_connect_window()

        self.assertEqual(status["status"], "awaiting_login")
        self.assertTrue(status["login_window_open"])
        self.assertEqual(len(launched_cmds), 1)
        # Clean manual login must NOT attach --remote-debugging-port so Google Sign-In works
        self.assertFalse(any("--remote-debugging-port" in arg for arg in launched_cmds[0]))
        self.assertNotIn("--headless=new", launched_cmds[0])
        self.assertIn("--new-window", launched_cmds[0])
        self.assertIn(LINKEDIN_FEED_URL, launched_cmds[0])

        # While the manual login window is open, verify_connection asks cleanly to close it first
        pending_verify = worker.verify_connection()
        self.assertFalse(pending_verify["ok"])
        self.assertIn("Feche a janela", pending_verify["message"])

        # Once user finishes login and closes the window, cookies exist and verify_connection confirms via CDP
        connect_proc.terminate()
        self._seed_session_files()

        def responder(expr: str):
            if "document.readyState" in expr:
                return {"href": "https://www.linkedin.com/feed/", "ready": "complete", "isLogin": False, "isCheckpoint": False, "hasFeedUi": True}
            return {}

        with (
            patch("backend.core.linkedin_browser.subprocess.Popen", side_effect=fake_popen),
            patch("backend.core.linkedin_browser.urllib.request.urlopen", return_value=_Resp(page_tabs)),
            patch("websockets.sync.client.connect", return_value=_FakeWebSocket(responder)),
            patch("backend.core.linkedin_browser.time.sleep"),
        ):
            verified = worker.verify_connection()

        self.assertTrue(verified["ok"])
        self.assertEqual(verified["status"], "connected")
        self.assertFalse(verified["login_window_open"])
        self.assertTrue(any("--remote-debugging-port=0" in arg for arg in launched_cmds[1]))
        self.assertTrue(verify_proc.terminated)

    def test_search_content_posts_collects_scrolls_and_enforces_cooldown_and_daily_cap(self):
        worker = self._make_worker()
        self._seed_session_files()
        launched_cmds: list[list[str]] = []
        procs: list[_FakeProc] = []
        scroll_calls = 0

        def fake_popen(cmd, **_kwargs):
            launched_cmds.append(list(cmd))
            p = _FakeProc()
            procs.append(p)
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            (self.profile_dir / "DevToolsActivePort").write_text("9333\n/devtools/browser/2\n", encoding="utf-8")
            return p

        def responder(expr: str):
            nonlocal scroll_calls
            if "document.readyState" in expr:
                return {"href": "https://www.linkedin.com/search/results/content/", "ready": "complete", "isLogin": False, "isCheckpoint": False, "hasFeedUi": True}
            if "window.scrollBy" in expr:
                scroll_calls += 1
                return None
            if "see-more" in expr:
                return 1
            return {
                "cards_total": 1,
                "posts": [
                    {
                        "raw_text": "Vaga Desenvolvedor Python Remoto! Envie seu CV para jobs@techbr.dev",
                        "company": "TechBR",
                        "url": "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000000/",
                    }
                ],
            }

        page_tabs = json.dumps(
            [{"type": "page", "id": "TAB-1", "url": "https://www.linkedin.com/search/results/content/?keywords=python", "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/page/TAB-1"}]
        ).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def read(self):
                return page_tabs

        # On first _read_live_cdp() before spawn we want None so it exercises _spawn_browser visibly
        urlopen_calls = {"n": 0}

        def fake_urlopen(url, timeout=1.0):
            urlopen_calls["n"] += 1
            if not any(p.poll() is None for p in procs):
                raise OSError("not running yet")
            return _Resp()

        with (
            patch("backend.core.linkedin_browser.subprocess.Popen", side_effect=fake_popen),
            patch("backend.core.linkedin_browser.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("websockets.sync.client.connect", side_effect=lambda *_a, **_kw: _FakeWebSocket(responder)),
            patch("backend.core.linkedin_browser.time.sleep"),
            patch("backend.core.linkedin_browser.random.uniform", return_value=0.01),
        ):
            res = worker.search_content_posts("Python")

        self.assertTrue(res["ok"])
        self.assertEqual(len(res["posts"]), 1)
        self.assertEqual(scroll_calls, DEFAULT_LINKEDIN_MAX_SCROLLS)
        self.assertTrue(procs[0].terminated)
        self.assertNotIn("--headless=new", launched_cmds[0])

        status = worker.get_status()
        self.assertEqual(status["daily_count"], 1)
        self.assertEqual(status["cooldown_remaining_seconds"], 0)

        # Consecutive search runs immediately without hidden 20-minute cooldown block (default 0)
        second = None
        with (
            patch("backend.core.linkedin_browser.subprocess.Popen", side_effect=fake_popen),
            patch("backend.core.linkedin_browser.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("websockets.sync.client.connect", side_effect=lambda *_a, **_kw: _FakeWebSocket(responder)),
            patch("backend.core.linkedin_browser.time.sleep"),
            patch("backend.core.linkedin_browser.random.uniform", return_value=0.01),
        ):
            second = worker.search_content_posts("Angular")
        self.assertTrue(second["ok"])
        self.assertEqual(worker.get_status()["daily_count"], 2)

        # Explicit optional cooldown and daily cap still enforce when caller sets custom_limits > 0
        worker.update_config({"cooldown_minutes": 15, "max_daily_searches": 10})
        throttled = worker.search_content_posts("Java")
        self.assertFalse(throttled["ok"])
        self.assertEqual(throttled["skipped_reason"], "cooldown")

        with worker._state_lock:
            worker._state["last_run_ts"] = 0.0
            worker._state["daily_count"] = 10
            worker._save_state_locked()
        capped = worker.search_content_posts("Java")
        self.assertFalse(capped["ok"])
        self.assertEqual(capped["skipped_reason"], "daily_limit")

        # Day rollover resets daily_count back to 0
        with worker._state_lock:
            worker._state["daily_date"] = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
            worker._save_state_locked()
        rolled = worker.get_status()
        self.assertEqual(rolled["daily_count"], 0)

    def test_search_fails_closed_on_checkpoint_or_login(self):
        for idx, (marker_key, expected_reason) in enumerate((
            ("isCheckpoint", "checkpoint_required"),
            ("isLogin", "login_required"),
        )):
            with self.subTest(marker_key=marker_key):
                sub_root = self.root / f"sub_{idx}"
                sub_profile = sub_root / "profile"
                sub_state = sub_root / "state"
                net_dir = sub_profile / "Default" / "Network"
                net_dir.mkdir(parents=True, exist_ok=True)
                (net_dir / "Cookies").write_text("cookie-blob", encoding="utf-8")

                worker = LinkedInBrowserWorker(
                    profile_dir=sub_profile,
                    state_dir=sub_state,
                    executable_finder=lambda: str(self.fake_chrome),
                )
                proc = _FakeProc()

                def fake_popen(_cmd, _p=sub_profile, _proc=proc, **_kwargs):
                    _p.mkdir(parents=True, exist_ok=True)
                    (_p / "DevToolsActivePort").write_text("9444\n/devtools/browser/3\n", encoding="utf-8")
                    return _proc

                def responder(expr: str, _mk=marker_key):
                    if "document.readyState" in expr:
                        return {
                            "href": "https://www.linkedin.com/checkpoint/challenge/" if _mk == "isCheckpoint" else "https://www.linkedin.com/login",
                            "ready": "complete",
                            "isLogin": _mk == "isLogin",
                            "isCheckpoint": _mk == "isCheckpoint",
                            "hasFeedUi": False,
                        }
                    raise AssertionError(f"Should stop before scrolling/extracting when {_mk} is True")

                tab_url = (
                    "https://www.linkedin.com/checkpoint/"
                    if marker_key == "isCheckpoint"
                    else "https://www.linkedin.com/login"
                )
                page_tabs = json.dumps(
                    [{"type": "page", "id": "TAB-BLK", "url": tab_url, "webSocketDebuggerUrl": "ws://127.0.0.1:9444/devtools/page/TAB-BLK"}]
                ).encode("utf-8")

                class _Resp:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_a):
                        return False

                    def read(self):
                        return page_tabs

                spawned = {"yes": False}

                def fake_urlopen(_url, timeout=1.0, _sp=spawned):
                    if not _sp["yes"]:
                        raise OSError("not running yet")
                    return _Resp()

                def popen_wrapper(*a, _sp=spawned, **kw):
                    _sp["yes"] = True
                    return fake_popen(*a, **kw)

                with (
                    patch("backend.core.linkedin_browser.subprocess.Popen", side_effect=popen_wrapper),
                    patch("backend.core.linkedin_browser.urllib.request.urlopen", side_effect=fake_urlopen),
                    patch("websockets.sync.client.connect", return_value=_FakeWebSocket(responder)),
                    patch("backend.core.linkedin_browser.time.sleep"),
                ):
                    res = worker.search_content_posts("Python")

                self.assertFalse(res["ok"])
                self.assertEqual(res["skipped_reason"], expected_reason)
                self.assertEqual(worker.get_status()["status"], expected_reason)
                self.assertTrue(proc.terminated)

    def test_disconnect_wipes_profile_and_resets_state(self):
        worker = self._make_worker()
        self._seed_session_files()
        with worker._state_lock:
            worker._state["daily_count"] = 5
            worker._state["last_status"] = "connected"
            worker._save_state_locked()

        after = worker.disconnect()
        self.assertEqual(after["status"], "not_connected")
        self.assertFalse(self.profile_dir.exists())
        self.assertEqual(after["daily_count"], 0)


class RecruiterLinkedInIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.repo = Repository(db_path=self.tmp_db.name)

    def tearDown(self):
        self.repo.close()
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)

    def test_sync_all_imports_linkedin_hiring_post_without_email_when_has_url_and_forwards_days(self):
        captured: dict[str, object] = {}
        email_url = "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000010/"
        no_email_url = "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000011/"

        def fake_search(q, force=False, should_stop=None, days=None):
            captured["query"] = q
            captured["days"] = days
            return {
                "ok": True,
                "posts": [
                    {
                        "raw_text": "Estamos contratando Dev Angular Sênior! Envie CV para rh@angular-br.dev",
                        "company": "Angular BR",
                        "url": email_url,
                    },
                    {
                        "raw_text": "Estamos contratando Desenvolvedor Angular Pleno 100% remoto. Candidate-se pelo link da publicação.",
                        "company": "RemotoTech",
                        "url": no_email_url,
                    },
                ],
            }

        svc = RecruiterService(
            self.repo,
            enable_live_feeds=False,
            linkedin_worker=SimpleNamespace(search_content_posts=fake_search),
        )
        with patch.object(svc, "sync_from_hn", return_value=0):
            res = svc.sync_all(query="Angular", days=1)

        self.assertEqual(captured["days"], 1)
        self.assertEqual(res["linkedin_synced"], 2)
        self.assertEqual(res["portal_breakdown"]["linkedin_post"]["matched"], 2)
        self.assertIn(no_email_url, res["collected_urls"])

        with self.assertRaises(ValueError):
            svc.add_pasted_posts_batch(
                [
                    {
                        "raw_text": "Estamos contratando Dev Angular Pleno sem email na colagem manual.",
                        "company": "ManualCo",
                        "url": "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000012/",
                    }
                ]
            )

    def test_sync_all_imports_linkedin_posts_without_setting_rate_limit_on_alerts(self):
        act_id = str(int(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc).timestamp() * 1000) << 22)
        post_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{act_id}/"
        fake_worker = SimpleNamespace(
            search_content_posts=lambda q, force=False, should_stop=None: {
                "ok": True,
                "posts": [
                    {
                        "raw_text": "Estamos contratando Dev Python Pleno! Envie CV para talent@li-corp.dev",
                        "company": "LI Corp",
                        "url": post_url,
                    },
                    {
                        "raw_text": "Bom dia rede!",
                        "company": "Noise",
                        "url": "",
                    },
                ],
            }
        )
        svc = RecruiterService(self.repo, enable_live_feeds=False, linkedin_worker=fake_worker)
        with patch.object(svc, "sync_from_hn", return_value=0):
            res = svc.sync_all(query="Python")
        self.assertEqual(res["linkedin_synced"], 1)
        self.assertEqual(res["synced"], 1)
        self.assertIn(post_url, res["collected_urls"])
        self.assertEqual(res["portal_breakdown"]["linkedin_post"]["fetched"], 2)
        self.assertEqual(res["portal_breakdown"]["linkedin_post"]["matched"], 1)
        self.assertFalse(res["rate_limited"])
        self.assertEqual(res["errors"], 0)

        # Checkpoint alert pauses only LinkedIn and emits warning, keeping rate_limited=False
        paused_worker = SimpleNamespace(
            search_content_posts=lambda q, force=False, should_stop=None: {
                "ok": False,
                "skipped_reason": "checkpoint_required",
                "posts": [],
                "error": "LinkedIn solicitou verificação.",
            }
        )
        svc_paused = RecruiterService(self.repo, enable_live_feeds=False, linkedin_worker=paused_worker)
        with patch.object(svc_paused, "sync_from_hn", return_value=0):
            paused_res = svc_paused.sync_all(query="Python")
        self.assertEqual(paused_res["linkedin_synced"], 0)
        self.assertEqual(paused_res["linkedin_skipped_reason"], "checkpoint_required")
        self.assertIn("LinkedIn solicitou verificação.", paused_res["warnings"])
        self.assertFalse(paused_res["rate_limited"])
        self.assertEqual(paused_res["errors"], 0)

    def test_sync_from_linkedin_handles_batch_without_any_emails(self):
        fake_worker = SimpleNamespace(
            search_content_posts=lambda q, force=False, should_stop=None: {
                "ok": True,
                "posts": [{"raw_text": "Post sem email no texto", "company": "X"}],
            }
        )
        svc = RecruiterService(self.repo, enable_live_feeds=False, linkedin_worker=fake_worker)
        res = svc.sync_all(query="React")
        self.assertEqual(res["linkedin_synced"], 0)
        self.assertEqual(res["errors"], 0)

    def test_sync_all_runs_linkedin_in_parallel_with_other_platforms(self):
        barrier = threading.Barrier(2, timeout=2.0)
        seen_threads: list[str] = []

        def fake_hn(_term, _collected_urls=None, _status_out=None):
            seen_threads.append(f"hn:{threading.get_ident()}")
            barrier.wait()
            return 0

        def fake_linkedin(_q, force=False, should_stop=None):
            seen_threads.append(f"li:{threading.get_ident()}")
            barrier.wait()
            return {"ok": True, "posts": []}

        svc = RecruiterService(
            self.repo,
            enable_live_feeds=False,
            linkedin_worker=SimpleNamespace(search_content_posts=fake_linkedin),
        )
        with patch.object(svc, "sync_from_hn", side_effect=fake_hn):
            res = svc.sync_all(query="Python")

        self.assertEqual(res["errors"], 0)
        self.assertEqual(len(seen_threads), 2)
        self.assertNotEqual(seen_threads[0].split(":")[1], seen_threads[1].split(":")[1])


class LinkedInWorkerApiRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.repo = Repository(db_path=self.tmp_db.name)
        self.worker = LinkedInBrowserWorker(
            profile_dir=Path(self.tmp.name) / "profile",
            state_dir=Path(self.tmp.name) / "state",
            executable_finder=lambda: "C:/fake/chrome.exe",
        )
        app.dependency_overrides[get_repository] = lambda: self.repo
        app.dependency_overrides[get_linkedin_worker] = lambda: self.worker
        app.dependency_overrides[get_recruiter_service] = lambda: RecruiterService(
            self.repo, enable_live_feeds=False, linkedin_worker=self.worker
        )
        self.client = TestClient(app)
        self.token = get_token()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.repo.close()
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)
        self.tmp.cleanup()

    def test_linkedin_routes_status_config_disconnect_and_csrf_protection(self):
        st = self.client.get("/api/recruiters/linkedin/status")
        self.assertEqual(st.status_code, 200)
        body = st.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "not_connected")
        self.assertFalse(body["headless"])

        # Mutating routes require X-Painel-Token
        for path in ("/api/recruiters/linkedin/connect", "/api/recruiters/linkedin/verify", "/api/recruiters/linkedin/config", "/api/recruiters/linkedin/disconnect"):
            payload = {"enabled": False} if path.endswith("/config") else {}
            r_unauth = self.client.post(path, json=payload)
            self.assertEqual(r_unauth.status_code, 403, f"Expected 403 without CSRF on {path}")

        cfg_resp = self.client.post(
            "/api/recruiters/linkedin/config",
            json={"enabled": False, "cooldown_minutes": 30},
            headers={"X-Painel-Token": self.token},
        )
        self.assertEqual(cfg_resp.status_code, 200)
        self.assertFalse(cfg_resp.json()["enabled"])
        self.assertEqual(cfg_resp.json()["cooldown_minutes"], 30)

        with patch.object(self.worker, "open_connect_window", return_value={"status": "awaiting_login", "browser_available": True}):
            conn_resp = self.client.post("/api/recruiters/linkedin/connect", headers={"X-Painel-Token": self.token})
            self.assertEqual(conn_resp.status_code, 200)
            self.assertEqual(conn_resp.json()["status"], "awaiting_login")

        with patch.object(self.worker, "open_connect_window", side_effect=RuntimeError("Chrome ausente")):
            err_resp = self.client.post("/api/recruiters/linkedin/connect", headers={"X-Painel-Token": self.token})
            self.assertEqual(err_resp.status_code, 503)

        disc_resp = self.client.post("/api/recruiters/linkedin/disconnect", headers={"X-Painel-Token": self.token})
        self.assertEqual(disc_resp.status_code, 200)
        self.assertEqual(disc_resp.json()["status"], "not_connected")


class LinkedInExtractionAndHydrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile_dir = Path(self.tmp.name) / "profile"
        self.state_dir = Path(self.tmp.name) / "state"
        self.fake_chrome = Path(self.tmp.name) / "chrome.exe"
        self.fake_chrome.write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_linkedin_content_search_url_uses_essential_keyword_and_date_filters(self):
        from urllib.parse import unquote
        from backend.core.linkedin_browser import days_to_linkedin_date_posted

        self.assertEqual(days_to_linkedin_date_posted(1), "past-24h")
        self.assertEqual(days_to_linkedin_date_posted(7), "past-week")
        self.assertEqual(days_to_linkedin_date_posted(30), "past-month")
        self.assertEqual(days_to_linkedin_date_posted(None), "past-week")

        decoded = unquote(
            build_linkedin_content_search_url(
                "Desenvolvedor Angular, TypeScript",
                date_posted="past-24h",
            )
        )
        self.assertIn("keywords=Angular vaga", decoded)
        self.assertIn('datePosted="past-24h"', decoded)
        for forbidden in ('"e-mail"', '"email"', '"currículo"', " OR ", "("):
            self.assertNotIn(forbidden, decoded)

        broad = unquote(
            build_linkedin_content_search_url(
                "vaga Angular",
                date_posted="past-month",
                include_vaga_suffix=False,
            )
        )
        self.assertIn("keywords=vaga Angular", broad)
        self.assertNotIn("vaga Angular vaga", broad)
        self.assertIn('datePosted="past-month"', broad)

    def test_wait_and_inspect_waits_for_results_and_collects_incrementally_across_scrolls(self):
        worker = LinkedInBrowserWorker(
            profile_dir=self.profile_dir,
            state_dir=self.state_dir,
            executable_finder=lambda: str(self.fake_chrome),
        )
        (self.profile_dir / "Default").mkdir(parents=True, exist_ok=True)
        (self.profile_dir / "Default" / "Cookies").write_bytes(b"cookie")
        with worker._state_lock:
            worker._state["status"] = "connected"
            worker._save_state_locked()

        scroll_index = 0
        check_calls = 0
        procs = []

        def fake_popen(_cmd, **_kwargs):
            p = _FakeProc()
            procs.append(p)
            (self.profile_dir / "DevToolsActivePort").write_text("9334\n/devtools/browser/9\n", encoding="utf-8")
            return p

        def responder(expr: str):
            nonlocal scroll_index, check_calls
            if "document.readyState" in expr:
                check_calls += 1
                return {
                    "href": "https://www.linkedin.com/search/results/content/",
                    "ready": "complete",
                    "isLogin": False,
                    "isCheckpoint": False,
                    "hasFeedUi": True,
                    "hasResultContent": check_calls >= 2,
                    "hasEmptyState": False,
                }
            if "window.scrollBy" in expr:
                scroll_index += 1
                return None
            if "see-more" in expr:
                return 1
            if scroll_index == 0:
                return {
                    "cards_total": 1,
                    "posts": [{
                        "raw_text": "Primeira vaga Java remoto. CV para primeiro@alpha.dev",
                        "company": "Alpha",
                        "url": "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000001/",
                        "posted_age_text": "2 h",
                    }],
                }
            if scroll_index == 1:
                # Virtualized feed removes post 1 and renders post 2
                return {
                    "cards_total": 1,
                    "posts": [{
                        "raw_text": "Segunda vaga Spring! Contato: segundo [arroba] beta (ponto) com",
                        "company": "Beta",
                        "url": "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000002/",
                        "posted_age_text": "1 d",
                    }],
                }
            return {"cards_total": 1, "posts": []}

        page_tabs = json.dumps([
            {"type": "page", "id": "TAB-1", "url": "https://www.linkedin.com/search/results/content/", "webSocketDebuggerUrl": "ws://127.0.0.1:9334/devtools/page/TAB-1"}
        ]).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self
            def __exit__(self, *_a):
                return False
            def read(self):
                return page_tabs

        def fake_urlopen(_url, timeout=1.0):
            if not procs:
                raise OSError("not running")
            return _Resp()

        with (
            patch("backend.core.linkedin_browser.subprocess.Popen", side_effect=fake_popen),
            patch("backend.core.linkedin_browser.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("websockets.sync.client.connect", return_value=_FakeWebSocket(responder)),
            patch("backend.core.linkedin_browser.time.sleep"),
            patch("backend.core.linkedin_browser.random.uniform", return_value=0.01),
        ):
            res = worker.search_content_posts("Java", force=True)

        self.assertTrue(res["ok"])
        self.assertGreaterEqual(check_calls, 2)
        self.assertEqual(len(res["posts"]), 2)
        self.assertGreaterEqual(res["cards_total"], 2)
        self.assertEqual(worker.get_status()["last_cards_total"], res["cards_total"])

    def test_search_content_posts_retries_fallback_url_when_initial_page_shows_empty_state(self):
        from urllib.parse import unquote

        worker = LinkedInBrowserWorker(
            profile_dir=self.profile_dir,
            state_dir=self.state_dir,
            executable_finder=lambda: str(self.fake_chrome),
        )
        (self.profile_dir / "Default").mkdir(parents=True, exist_ok=True)
        (self.profile_dir / "Default" / "Cookies").write_bytes(b"cookie")
        with worker._state_lock:
            worker._state["status"] = "connected"
            worker._save_state_locked()

        procs = []
        navigated_urls: list[str] = []
        launched_urls: list[str] = []
        inspect_calls = 0

        def fake_popen(cmd, **_kwargs):
            p = _FakeProc()
            procs.append(p)
            launched_urls.extend(a for a in cmd if "linkedin.com/search" in str(a))
            (self.profile_dir / "DevToolsActivePort").write_text("9335\n/devtools/browser/10\n", encoding="utf-8")
            return p

        class _NavFakeWebSocket:
            def __init__(self):
                self._responses: list[str] = []

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def send(self, raw: str):
                nonlocal inspect_calls
                msg = json.loads(raw)
                msg_id = msg["id"]
                method = msg["method"]
                params = msg.get("params") or {}
                if method == "Page.navigate":
                    navigated_urls.append(params.get("url", ""))
                    self._responses.append(json.dumps({"id": msg_id, "result": {}}))
                    return
                expr = params.get("expression", "")
                if "document.readyState" in expr:
                    inspect_calls += 1
                    is_initial_empty = len(navigated_urls) == 0
                    val = {
                        "href": "https://www.linkedin.com/search/results/content/",
                        "ready": "complete",
                        "isLogin": False,
                        "isCheckpoint": False,
                        "hasFeedUi": True,
                        "hasResultContent": not is_initial_empty,
                        "hasEmptyState": is_initial_empty,
                    }
                elif "see-more" in expr or "window.scrollBy" in expr:
                    val = None
                else:
                    val = {
                        "cards_total": 1,
                        "posts": [
                            {
                                "raw_text": "Vaga Angular Pleno remota com inscrição pelo link do post.",
                                "company": "DevStudio",
                                "url": "https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000099/",
                                "posted_age_text": "3 d",
                            }
                        ],
                    }
                self._responses.append(json.dumps({"id": msg_id, "result": {"result": {"value": val}}}))

            def recv(self, timeout: float | None = None) -> str:
                return self._responses.pop(0)

        page_tabs = json.dumps([
            {"type": "page", "id": "TAB-NAV", "url": "https://www.linkedin.com/search/results/content/", "webSocketDebuggerUrl": "ws://127.0.0.1:9335/devtools/page/TAB-NAV"}
        ]).encode("utf-8")

        class _Resp:
            def __enter__(self):
                return self
            def __exit__(self, *_a):
                return False
            def read(self):
                return page_tabs

        def fake_urlopen(_url, timeout=1.0):
            if not procs:
                raise OSError("not running yet")
            return _Resp()

        with (
            patch("backend.core.linkedin_browser.subprocess.Popen", side_effect=fake_popen),
            patch("backend.core.linkedin_browser.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("websockets.sync.client.connect", return_value=_NavFakeWebSocket()),
            patch("backend.core.linkedin_browser.time.sleep"),
            patch("backend.core.linkedin_browser.random.uniform", return_value=0.01),
        ):
            res = worker.search_content_posts("Angular", force=True, days=7)

        self.assertTrue(res["ok"])
        self.assertEqual(len(res["posts"]), 1)
        self.assertGreaterEqual(len(launched_urls), 1)
        self.assertIn("keywords=Angular vaga", unquote(launched_urls[0]))
        self.assertEqual(len(navigated_urls), 1)
        decoded_fallback = unquote(navigated_urls[0])
        self.assertIn("keywords=Angular", decoded_fallback)
        self.assertNotIn("keywords=Angular vaga", decoded_fallback)
        self.assertIn('datePosted="past-month"', decoded_fallback)

