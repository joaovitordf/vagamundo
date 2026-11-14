"""Guards for the rule that keeps free-form `notes` from breaking a tracker row.

No writer in this framework emits a quoted tracker field, so a comma inside
`notes` splits the row - for the `csv.DictReader` in `tools/rank_state.py` as
much as for a naive split - and shifts `cv_file`, `cover_letter_file` and
`source` a column left. A line break is worse: it ends the row. Two writers put
free-form text into `notes`: `/gmail-sync` Step 7a copies an email subject, and
`/outcome` Step 4 writes a short note of its own. The fixed-format writers
(`followed up YYYY-MM-DD`, `stale resolved no_response (YYYY-MM-DD)`,
`redrafted`) cannot contain the characters and are not listed.

The spec IS the implementation, so the guard is `CASES`: each rule must sit on
the line that instructs the append, not merely somewhere in the section.
"""
import re
import unittest
from pathlib import Path

import sys
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo import REPO, REPO_ROOT
COMMANDS = REPO / ".claude" / "commands"
GMAIL_SYNC = COMMANDS / "gmail-sync.md"
OUTCOME = COMMANDS / "outcome.md"

TRACKER_HEADER = (
    "date,company,sector,role,role_type,channel,status,contact_person,"
    "fit_rating,notes,cv_file,cover_letter_file,source,deadline"
)


def section(path, heading):
    """The body of one markdown section, up to the next heading of any depth."""
    text = path.read_text(encoding="utf-8")
    start = text.index(heading) + len(heading)
    rest = text[start:]
    end = re.search(r"^#{1,4} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


class FreeFormNotesWritersStateTheRule(unittest.TestCase):
    """Format: (path, heading, line_anchor, rule, why)"""

    CASES = [
        (
            GMAIL_SYNC,
            "### Passo 7a: Gravar as atualizações aprovadas",
            "acrescente em `notes`",
            "apagando antes do assunto toda vírgula, aspas duplas e quebra de linha",
            "Step 7a item 2 deliberately keeps the subject verbatim in `outcome.md`, "
            "so the rule must sit on the tracker append, not anywhere in the step",
        ),
        (
            OUTCOME,
            "## Passo 4: Atualizar o tracker",
            "acrescente uma nota curta com data",
            "sem vírgulas, aspas duplas nem quebras de linha",
            "Step 4 is the primary status-update path and its note is written "
            "free-form - `rejected, no feedback given` is the natural sentence",
        ),
    ]

    def test_rule_is_stated_where_the_append_happens(self):
        for path, heading, anchor, rule, why in self.CASES:
            with self.subTest(path=path.name, heading=heading):
                lines = [l for l in section(path, heading).splitlines() if anchor in l]
                self.assertEqual(len(lines), 1, f"expected one append instruction: {why}")
                self.assertIn(rule, lines[0], why)


if __name__ == "__main__":
    unittest.main()
