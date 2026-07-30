import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.features.terminal.service import _is_cd_command
from app.features.ai.service import PROPOSAL_RE, KNOWN_PLACEHOLDERS
from app.features.ai.agents.planner import PLANNER_SYSTEM_PROMPT


class TestLogicSuite(unittest.TestCase):
    def test_cd_command_detection(self):
        """Verify _is_cd_command matches ONLY actual cd command and arguments, not cdk/cdrom."""
        self.assertTrue(_is_cd_command("cd"))
        self.assertTrue(_is_cd_command("cd /tmp"))
        self.assertTrue(_is_cd_command("cd  .."))
        self.assertFalse(_is_cd_command("cdk deploy"))
        self.assertFalse(_is_cd_command("cdrom"))
        self.assertFalse(_is_cd_command("cdc-cli"))

    def test_proposal_extraction_variations(self):
        """Verify PROPOSAL_RE correctly extracts proposals from AI raw text."""
        raw_text = """
Here is the proposed change:

[PROPOSAL: app/main.py]
<<<<<<< SEARCH
def foo():
    pass
=======
def foo():
    return "bar"
>>>>>>> REPLACE
        """
        matches = list(PROPOSAL_RE.finditer(raw_text))
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.group("path").strip(), "app/main.py")
        self.assertIn("def foo():", m.group("original"))
        self.assertIn("return \"bar\"", m.group("updated"))

    def test_placeholder_detection_exact_match(self):
        """Verify known placeholders list contains exact phrases."""
        self.assertIn("# empty file", KNOWN_PLACEHOLDERS)
        self.assertIn("// empty file", KNOWN_PLACEHOLDERS)
        self.assertNotIn("# TODO: empty file after processing", KNOWN_PLACEHOLDERS)

    def test_planner_advertises_only_implemented_agents(self):
        """Verify planner prompt only lists agents that exist."""
        self.assertIn("Coding Agent", PLANNER_SYSTEM_PROMPT)
        self.assertIn("Review Agent", PLANNER_SYSTEM_PROMPT)
        self.assertIn("Testing Agent", PLANNER_SYSTEM_PROMPT)
        self.assertIn("Documentation Agent", PLANNER_SYSTEM_PROMPT)
        self.assertNotIn("Security Agent:", PLANNER_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
