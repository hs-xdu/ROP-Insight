"""Verify the P2-A spec's local references and unique acceptance IDs."""

from pathlib import Path
import re
import unittest


class P2ASpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = Path(__file__).resolve().parents[1] / "docs"
        cls.text = (cls.docs / "P2_A_SPEC.md").read_text(encoding="utf-8")

    def test_spec_references_resolve(self):
        links = re.findall(r"\]\(([^)]+\.md)\)", self.text)
        self.assertIn("IMPLEMENTATION_ROADMAP.md", links)
        self.assertIn("TECHNICAL_PLAN.md", links)
        for target in links:
            self.assertTrue((self.docs / target).is_file(), target)

    def test_acceptance_ids_are_complete_and_unique(self):
        ids = re.findall(r"^\| (A\d{2}) \| [^|]+ \| [^|]+ \|$", self.text, re.MULTILINE)
        self.assertEqual(ids, [f"A{number:02d}" for number in range(1, 11)])


if __name__ == "__main__":
    unittest.main()
