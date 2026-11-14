"""Camada de dados e persistência de compatibilidade em backend/tools/painel.py."""

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import painel  # noqa: E402

RESULTS = {
    "meta": {"date": "2026-10-22"},
    "new": [
        {"title": "Product Manager", "company": "Zeta", "url": "https://zeta.gupy.io/jobs/1", "date": "2026-10-20",
         "portal": "gupy-search", "signals": {"verdict": "posting_signals: none"}},
        {"title": "Product Owner", "company": "Omega", "url": "https://remotar.com.br/job/2", "date": "2026-10-19",
         "portal": "remotar-search", "signals": {"verdict": "posting_signals: none"}},
    ],
}

class Data(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.seen = self.dir / "seen_jobs.json"
        self.tracker = self.dir / "tracker.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def test_mark_uses_the_search_file_not_the_browser(self):
        out = painel.mark(RESULTS, ["https://zeta.gupy.io/jobs/1", "https://evil.example/x"], "interesse", self.seen)
        self.assertEqual((out["added"], out["missing"]), (1, ["https://evil.example/x"]))
        entry = next(iter(json.loads(self.seen.read_text(encoding="utf-8"))["seen"].values()))
        self.assertEqual((entry["title"], entry["fit"], entry["status"], entry["source"]),
                         ("Product Manager", "medium", "new", "painel"))

    def test_mark_with_job_data_for_external_source(self):
        job_data = {"url": "https://europa.eu/eures/portal/jv-se/jv-details/123", "title": "AI Engineer", "company": "Tech Corp", "portal": "eures"}
        out = painel.mark(None, [job_data["url"]], "interesse", self.seen, job_data=job_data)
        self.assertEqual((out["added"], out["missing"]), (1, []))
        entry = next(iter(json.loads(self.seen.read_text(encoding="utf-8"))["seen"].values()))
        self.assertEqual((entry["title"], entry["company"], entry["portal"]), ("AI Engineer", "Tech Corp", "eures"))

    def test_discard_is_low_and_skipped(self):
        painel.mark(RESULTS, ["https://remotar.com.br/job/2"], "descartar", self.seen)
        entry = next(iter(json.loads(self.seen.read_text(encoding="utf-8"))["seen"].values()))
        self.assertEqual((entry["fit"], entry["status"]), ("low", "skipped"))

    def test_unknown_decision(self):
        with self.assertRaises(ValueError):
            painel.mark(RESULTS, [], "candidatar", self.seen)

    def test_marked_jobs_leave_the_list_and_only_interest_is_saved(self):
        painel.mark(RESULTS, ["https://zeta.gupy.io/jobs/1"], "interesse", self.seen)
        painel.mark(RESULTS, ["https://remotar.com.br/job/2"], "descartar", self.seen)
        self.assertEqual([s["title"] for s in painel.saved(self.seen)], ["Product Manager"])
        self.assertEqual([d["title"] for d in painel.discarded(self.seen)], ["Product Owner"])
        painel.restore_job("https://remotar.com.br/job/2", self.seen)
        self.assertEqual(painel.discarded(self.seen), [])
        self.assertEqual(len(painel.saved(self.seen)), 2)
        painel.record_applied("https://zeta.gupy.io/jobs/1", "Zeta", "Product Manager", "gupy-search", self.tracker, self.seen)
        self.assertEqual([s["title"] for s in painel.saved(self.seen)], ["Product Owner"])
        self.assertEqual(len(painel.applications(self.tracker)), 1)
        painel.remove_application("https://zeta.gupy.io/jobs/1", "skipped", tracker_path=self.tracker, seen_path=self.seen)
        self.assertEqual(len(painel.applications(self.tracker)), 0)
        self.assertEqual([d["title"] for d in painel.discarded(self.seen)], ["Product Manager"])

    def test_visa_flag_survives_marking_for_interest_and_discard(self):
        visa_results = {
            "new": [
                {**RESULTS["new"][0], "visa_sponsorship": True},
                {**RESULTS["new"][1], "visa_sponsorship": True},
            ]
        }
        painel.mark(visa_results, [visa_results["new"][0]["url"]], "interesse", self.seen)
        painel.mark(visa_results, [visa_results["new"][1]["url"]], "descartar", self.seen)
        self.assertTrue(painel.saved(self.seen)[0]["visa_sponsorship"])
        self.assertTrue(painel.discarded(self.seen)[0]["visa_sponsorship"])

    def test_application_record_stores_job_details_and_manual_history(self):
        evolution = self.dir / "evolucao.json"
        record = painel.save_application_record({
            "url": "https://zeta.gupy.io/jobs/1",
            "company": "Zeta",
            "title": "Product Manager",
            "portal": "gupy-search",
            "location": "Brasil",
            "workplace_type": "remote",
            "description": "Descrição da vaga",
            "applied_date": "2026-10-27",
            "status": "interview",
            "cv_file": "cv/main_zeta_product_manager.pdf",
            "event_date": "2026-10-28",
            "event_stage": "Entrevista técnica",
            "event_feedback": "Boa base técnica",
            "event_questions": "Como você testa integrações?",
            "event_answers": "Expliquei o caso da Steam.",
        }, evolution, self.tracker, self.seen)
        self.assertEqual(record["application"]["status"], "interview")
        self.assertEqual(record["job"]["location"], "Brasil")
        self.assertEqual(record["history"][0]["stage"], "Entrevista técnica")
        stored = json.loads(evolution.read_text(encoding="utf-8"))
        self.assertIn("https://zeta.gupy.io/jobs/1", stored["applications"])

    def test_update_evolution_imports_tracker_and_counts_application_data(self):
        self.tracker.write_text("date,company,role,status,source,cv_file\n2026-10-01,Zeta,PM,applied,https://zeta.example/job,cv.pdf\n", encoding="utf-8")
        data = painel.update_evolution(self.dir / "evolucao.json", self.tracker, self.seen, self.dir / "documents", db_path=self.dir / "empty.db")
        self.assertEqual(data["evolution"]["metrics"]["applications"], 1)
        self.assertEqual(data["evolution"]["metrics"]["applications_with_cv"], 1)
        self.assertIn("projects", data["validation"]["sources"])

    def test_applications_read_the_tracker(self):
        self.tracker.write_text("date,company,role,status\n2026-10-01,Zeta,PM,applied\n", encoding="utf-8")
        self.assertEqual(painel.applications(self.tracker), [{"date": "2026-10-01", "company": "Zeta", "role": "PM", "status": "applied"}])
        self.assertEqual(painel.applications(self.dir / "nao-existe.csv"), [])

    def test_claude_answer_files_are_named_by_hash_inside_the_folder(self):
        f = painel.claude_file("https://x/../../etc", "avaliar", self.dir)
        self.assertEqual(f.parent, self.dir)
        self.assertRegex(f.name, r"^[0-9a-f]{16}_avaliacao\.md$")


if __name__ == "__main__":
    unittest.main()
