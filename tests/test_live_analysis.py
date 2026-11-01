import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("live_analysis", Path(__file__).resolve().parents[1] / "scripts/analyze_live_model_evaluation.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class AnalysisTests(unittest.TestCase):
    def test_complete_artifact_read_checks_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.json"
            path.write_bytes(b'{"complete": true}')
            self.assertEqual(analysis.read_artifact(path), b'{"complete": true}')

    def test_short_artifact_read_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.bin"
            path.write_bytes(b"12345")
            with patch.object(analysis.os, "read", side_effect=[b"12", b""]):
                with self.assertRaisesRegex(OSError, "Incomplete artifact read"):
                    analysis.read_artifact(path)

    def test_oversized_artifact_is_rejected_before_allocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.bin"
            path.write_bytes(b"12345")
            with self.assertRaisesRegex(ValueError, "size bound"):
                analysis.read_artifact(path, max_bytes=4)

    def test_filesystem_open_stall_has_bounded_caller_wait(self):
        release = threading.Event()
        finished = threading.Event()

        def blocked_open(*args):
            release.wait(1)
            finished.set()
            raise OSError("Synthetic open failure after the caller timeout")

        with patch.object(analysis.os, "open", side_effect=blocked_open):
            try:
                with self.assertRaisesRegex(TimeoutError, "timed out"):
                    analysis.read_artifact(Path("synthetic-stalled-artifact"), timeout=.01)
            finally:
                release.set()
                self.assertTrue(finished.wait(1))

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

    def test_failed_receiver_generation_still_counts_native_tokens(self):
        record = {"run_id": "case-B", "receipts": [{"sequence": 7, "status": "failed"}]}
        index = {"receipt-00007": [{"response": {"prompt_eval_count": 43, "eval_count": 19, "done_reason": "length"}}]}
        result = analysis.measured_native_usage(record, index)
        self.assertEqual(result["prompt_tokens"], 43)
        self.assertEqual(result["completion_tokens"], 19)
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(result["output_limit_native_calls"], 1)
        self.assertEqual(result["native_usage_unobserved_calls"], 0)

    def test_cancelled_call_with_no_usage_is_unknown_compute(self):
        result = analysis.measured_native_usage({"run_id": "case-C"}, {"case-C": [{"status": "cancelled"}]})
        self.assertEqual(result["native_usage_unobserved_calls"], 1)

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
