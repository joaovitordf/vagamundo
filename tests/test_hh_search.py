import json
import unittest
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


class TestHHSearch(unittest.TestCase):
    def test_hh_search_cli_help(self):
        proc = subprocess.run(
            ["bun", "run", ".agents/skills/hh-search/cli/src/cli.ts", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("hh-search", proc.stdout)

    def test_hh_search_schema_compliance(self):
        sample_html = """
        <div data-qa="vacancy-serp__vacancy">
          <a data-qa="serp-item__title" href="https://hh.ru/vacancy/99887766">Senior Python Developer</a>
          <a data-qa="vacancy-serp__vacancy-employer">Yandex LLC</a>
          <span data-qa="vacancy-serp__vacancy-address">Москва, Россия</span>
          <span data-qa="vacancy-serp__vacancy-compensation">от 300 000 ₽</span>
        </div>
        """
        # Testa a execução do script com mock ou parsing de helper
        test_script = f"""
        import {{ parseHHSearch }} from "./.agents/skills/hh-search/cli/src/helpers.ts"
        const html = {json.dumps(sample_html)}
        const res = parseHHSearch(html)
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
        self.assertEqual(r["id"], "hh-99887766")
        self.assertEqual(r["title"], "Senior Python Developer")
        self.assertEqual(r["company"], "Yandex LLC")
        self.assertEqual(r["country_code"], "RU")
        self.assertIn("300 000 ₽", r["salary"])


if __name__ == "__main__":
    unittest.main()

