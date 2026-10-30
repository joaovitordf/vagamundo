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
        mock_resp.text = "<html><body><h1>Desenvolvedor Angular Pleno</h1></body></html>"
        client.head.return_value = mock_resp

        res = await self.liveness.probe_url(client, "https://gupy.io/jobs/123")
        self.assertTrue(res["alive"])
        self.assertEqual(res["reason"], "OK")

    async def test_probe_200_closed_text(self):
        client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Esta vaga foi encerrada pela empresa.</body></html>"
        client.head.return_value = mock_resp

        res = await self.liveness.probe_url(client, "https://gupy.io/jobs/456")
        self.assertFalse(res["alive"])
        self.assertEqual(res["reason"], "posting_closed_text")


if __name__ == "__main__":
    unittest.main()

