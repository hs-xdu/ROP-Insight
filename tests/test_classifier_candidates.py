"""Portable checks for the saved classifier evidence snapshot."""

import json
from pathlib import Path
import re
import unittest


class ClassifierCandidatesTests(unittest.TestCase):
    def test_candidate_evidence_has_complete_weights_and_metrics(self):
        docs = Path(__file__).resolve().parents[1] / "docs"
        data = json.loads((docs / "CLASSIFIER_CANDIDATES.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "awaiting_user_selection")
        self.assertEqual(data["classes"], ["Normal", "Stage1", "Stage2", "Stage3"])
        candidates = data["candidates"]
        self.assertEqual([c["id"] for c in candidates], ["A0", "A2", "A6", "A7", "M2", "M3", "B2"])
        paths = []
        for candidate in candidates:
            self.assertIn("rgb", candidate["inputs"])
            self.assertEqual(len(candidate["metrics"]), 2)
            for metric in candidate["metrics"]:
                self.assertGreater(metric["test_n"], 0)
                self.assertTrue(0 <= metric["accuracy"] <= 1)
                self.assertTrue(0 <= metric["macro_f1"] <= 1)
                self.assertGreater(metric["checkpoint_bytes"], 0)
                self.assertTrue(metric["checkpoint"].endswith("best.pt"))
                self.assertRegex(metric["metrics_source_sha256"], r"^[0-9a-f]{64}$")
                paths.append(metric["checkpoint"])
        self.assertEqual(len(paths), len(set(paths)))

    def test_selection_report_references_existing_snapshot(self):
        docs = Path(__file__).resolve().parents[1] / "docs"
        text = (docs / "P2_E_MODEL_SELECTION.md").read_text(encoding="utf-8")
        links = re.findall(r"\]\(([^)]+\.json)\)", text)
        self.assertIn("CLASSIFIER_CANDIDATES.json", links)
        for link in links:
            self.assertTrue((docs / link).is_file())
