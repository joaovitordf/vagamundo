import json
import unittest
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


class TestHabrCareerSearch(unittest.TestCase):
    def test_habr_search_cli_help(self):
        proc = subprocess.run(
            ["bun", "run", ".agents/skills/habrcareer-search/cli/src/cli.ts", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("habrcareer-search", proc.stdout)

    def test_habr_search_schema_compliance(self):
        sample_html = """
        <div class="vacancy-card">
          <time class="basic-date" datetime="2026-10-28T10:00:00+03:00">28 октября</time>
          <a class="vacancy-card__title-link" href="/vacancies/123456">Senior Fullstack Developer</a>
          <a class="link-comp" href="/companies/techcorp">TechCorp Russia</a>
          <div class="vacancy-card__salary">от 250 000 ₽</div>
          <div class="vacancy-card__meta">Удаленно • Москва</div>
        </div>
        """
        test_script = f"""
        import {{ parseHabrSearch }} from "./.agents/skills/habrcareer-search/cli/src/helpers.ts"
        const html = {json.dumps(sample_html)}
        const res = parseHabrSearch(html)
        console.log(JSON.stringify(res))
        """
        proc = subprocess.run(
            ["bun", "-e", test_script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        results = json.loads(proc.stdout)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["id"], "habr-123456")
        self.assertEqual(r["title"], "Senior Fullstack Developer")
        self.assertEqual(r["company"], "TechCorp Russia")
        self.assertEqual(r["country_code"], "RU")
        self.assertEqual(r["workplace_type"], "remote")
        self.assertIn("remote", r["signals"])


if __name__ == "__main__":
    unittest.main()

