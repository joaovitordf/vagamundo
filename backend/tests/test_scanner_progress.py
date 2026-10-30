"""Unit tests for Scanner progress tracking and region routing."""

import unittest
from backend.core.scanner import ScannerService
from backend.tools import scrape_run


class ScannerProgressTests(unittest.TestCase):
    def test_region_portals_configuration(self):
        self.assertIn("brasil", scrape_run.REGION_PORTALS)
        self.assertIn("estados-unidos", scrape_run.REGION_PORTALS)
        self.assertIn("europa", scrape_run.REGION_PORTALS)
        self.assertIn("global", scrape_run.REGION_PORTALS)

        self.assertIn("gupy-search", scrape_run.REGION_PORTALS["brasil"])
        self.assertIn("solides-search", scrape_run.REGION_PORTALS["brasil"])
        self.assertIn("greenhouse-search", scrape_run.REGION_PORTALS["estados-unidos"])
        self.assertIn("eures", scrape_run.REGION_PORTALS["europa"])

    def test_scanner_initial_status(self):
        scanner = ScannerService()
        st = scanner.status()
        self.assertFalse(st["running"])
        self.assertIn("progress", st)
        self.assertEqual(st["progress"]["percent"], 0.0)
        self.assertEqual(st["progress"]["completed"], 0)
        self.assertEqual(st["progress"]["jobs_found"], 0)
        self.assertIsInstance(st["progress"]["portals"], dict)


if __name__ == "__main__":
    unittest.main()

