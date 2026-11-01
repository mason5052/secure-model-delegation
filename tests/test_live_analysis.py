import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location("live_analysis", Path(__file__).resolve().parents[1] / "scripts/analyze_live_model_evaluation.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class AnalysisTests(unittest.TestCase):
    def test_answer_failure_does_not_erase_observed_route(self):
        record = {"status": "failed", "events": [
            {"stage": "decision", "decision": {"route": "local_process", "inspection": {"reliable": True}}},
            {"stage": "local_answer", "status": "running"},
        ]}
        decision = analysis.selected_decision(record)
        self.assertEqual(decision["route"], "local_process")
        self.assertEqual(decision["source"], "decision_event_before_answer_failure")
        self.assertNotEqual(record["status"], "completed")

    def test_absent_decision_remains_unresolved(self):
        self.assertIsNone(analysis.selected_decision({"events": []})["route"])

    def test_incomplete_comparison_cannot_produce_final_aggregate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runs").mkdir()
            (root / "execution-freeze.json").write_text(json.dumps({"runs": 108}))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                analysis.analyze(root, root / "final")
            self.assertFalse((root / "final").exists())


if __name__ == '__main__':
    unittest.main()
