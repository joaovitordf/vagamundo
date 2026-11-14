"""Unit tests for LivenessService."""

from __future__ import annotations
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.liveness import LivenessService
from backend.db.repository import Repository


class TestLivenessService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = Repository(":memory:")
        self.liveness = LivenessService(repo=self.repo)

    async def asyncTearDown(self):
        self.repo.close()

    async def test_probe_404_dead(self):
        client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        client.head.return_value = mock_resp

        res = await self.liveness.probe_url(client, "https://gupy.io/jobs/999")
        self.assertFalse(res["alive"])
        self.assertIn("404", res["reason"])

    async def test_probe_200_alive(self):
        client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        client.head.return_value = mock_resp

        res = await self.liveness.probe_url(client, "https://gupy.io/jobs/123")
        self.assertTrue(res["alive"])
        self.assertEqual(res["reason"], "OK")

    async def test_probe_405_get_fallback_closed_text(self):
        client = AsyncMock()
        head_resp = MagicMock()
        head_resp.status_code = 405
        head_resp.text = ""
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = "<html><body>Esta vaga foi encerrada pela empresa.</body></html>"
        client.head.return_value = head_resp
        client.get.return_value = get_resp

        res = await self.liveness.probe_url(client, "https://gupy.io/jobs/456")
        self.assertFalse(res["alive"])
        self.assertEqual(res["reason"], "posting_closed_text")

    async def test_probe_blocks_ssrf_and_non_http_urls(self):
        client = AsyncMock()
        for bad_url in (
            "file:///etc/passwd",
            "http://127.0.0.1:8765/api/settings",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8765/api/profile",
            "http://10.0.0.1/admin",
        ):
            res = await self.liveness.probe_url(client, bad_url)
            self.assertIsNone(res["alive"], bad_url)
            self.assertIn(res["reason"], ("invalid_scheme", "blocked_internal_host", "blocked_private_ip"))
        client.head.assert_not_called()
        client.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()

