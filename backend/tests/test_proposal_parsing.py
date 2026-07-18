import unittest
from backend.app.features.ai.service import PROPOSAL_RE


class ProposalParsingTests(unittest.TestCase):
    def test_standard_proposal_format(self):
        text = """
Some initial text.
[PROPOSAL: app/main.py]
<<<< ORIGINAL
print("old")
====
print("new")
>>>>
Some trailing text.
"""
        matches = list(PROPOSAL_RE.finditer(text))
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match.group("path").strip(), "app/main.py")
        self.assertEqual(match.group("original").strip(), 'print("old")')
        self.assertEqual(match.group("updated").strip(), 'print("new")')

    def test_original_header_variation(self):
        # Testing without the word "ORIGINAL" in header
        text = """
[PROPOSAL: test.txt]
<<<<
old line
====
new line
>>>>
"""
        matches = list(PROPOSAL_RE.finditer(text))
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match.group("path").strip(), "test.txt")
        self.assertEqual(match.group("original").strip(), "old line")
        self.assertEqual(match.group("updated").strip(), "new line")

    def test_empty_original_block_new_file(self):
        # Testing new file creation where ORIGINAL section is empty
        text = """
[PROPOSAL: src/components/NewButton.tsx]
<<<< ORIGINAL
====
export const NewButton = () => <button>Click</button>;
>>>>
"""
        matches = list(PROPOSAL_RE.finditer(text))
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match.group("path").strip(), "src/components/NewButton.tsx")
        self.assertEqual(match.group("original").strip(), "")
        self.assertEqual(match.group("updated").strip(), "export const NewButton = () => <button>Click</button>;")

    def test_three_angle_bracket_tolerance(self):
        # Testing tolerance for 3 brackets instead of 4
        text = """
[PROPOSAL: test.txt]
<<<<
old
====
new
>>>
"""
        matches = list(PROPOSAL_RE.finditer(text))
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match.group("original").strip(), "old")
        self.assertEqual(match.group("updated").strip(), "new")

    def test_malformed_proposals_do_not_match(self):
        # Missing original block opening
        text1 = """
[PROPOSAL: app/main.py]
print("old")
====
print("new")
>>>>
"""
        # Missing divider
        text2 = """
[PROPOSAL: app/main.py]
<<<< ORIGINAL
print("old")
print("new")
>>>>
"""
        # Missing end brackets
        text3 = """
[PROPOSAL: app/main.py]
<<<< ORIGINAL
print("old")
====
print("new")
"""
        self.assertEqual(len(list(PROPOSAL_RE.finditer(text1))), 0)
        self.assertEqual(len(list(PROPOSAL_RE.finditer(text2))), 0)
        self.assertEqual(len(list(PROPOSAL_RE.finditer(text3))), 0)


if __name__ == "__main__":
    unittest.main()
