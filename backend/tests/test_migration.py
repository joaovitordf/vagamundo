"""Unit tests for data migration (migrate_data.py)."""

from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from backend.db.repository import Repository
from backend.tools.migrate_data import migrate


class TestDataMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.db_path = self.tmp_dir / "test.db"
        self.seen_path = self.tmp_dir / "seen_jobs.json"
        self.tracker_path = self.tmp_dir / "tracker.csv"

        # Create dummy seen_jobs.json
        seen_data = {
            "seen": {
                "empresa-a_angular-dev": {
                    "title": "Angular Dev",
                    "company": "Empresa A",
                    "url": "https://empresa-a.com/job/1",
                    "status": "new",
                    "fit": "high",
                    "portal": "gupy-search",
                }
            }
        }
        self.seen_path.write_text(json.dumps(seen_data), encoding="utf-8")

        # Create dummy tracker.csv
        tracker_content = (
            "date,company,role,channel,status,notes,source,cv_file,cover_letter_file\n"
            "2026-10-25,Empresa B,Fullstack,linkedin-search,applied,Enviado,https://empresa-b.com/job/2,cv.pdf,carta.pdf\n"
        )
        self.tracker_path.write_text(tracker_content, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_is_idempotent(self):
        # 1st run
        res1 = migrate(self.seen_path, self.tracker_path, self.db_path)
        self.assertEqual(res1["jobs"], 1)
        self.assertEqual(res1["applications"], 1)

        repo = Repository(self.db_path)
        jobs = repo.list_jobs()
        apps = repo.list_applications()
        self.assertEqual(len(jobs), 2)  # 1 from seen + 1 from tracker
        self.assertEqual(len(apps), 1)
        repo.close()

        # 2nd run: should not duplicate
        res2 = migrate(self.seen_path, self.tracker_path, self.db_path)
        repo2 = Repository(self.db_path)
        jobs2 = repo2.list_jobs()
        apps2 = repo2.list_applications()
        self.assertEqual(len(jobs2), 2)
        self.assertEqual(len(apps2), 1)
        repo2.close()


if __name__ == "__main__":
    unittest.main()

