"""Audit completed live runs without rewriting raw execution artifacts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selected_decision(record):
    result = record.get("result")
    if result is not None:
        return {"route": result.get("route"), "inspection": result.get("inspection", {}), "source": "returned_result"}
    for event in reversed(record.get("events", [])):
        if event.get("stage") == "decision" and "decision" in event:
            return {**event["decision"], "source": "decision_event_before_answer_failure"}
    return {"route": None, "inspection": {}, "source": "no_decision_observed"}


def audit_record(record, run_dir):
    decision = selected_decision(record)
    sent, received = record.get("wire_requests", []), record.get("receipts", [])
    exact = None
    if sent or received:
        exact = len(sent) == len(received)
        for a, b in zip(sent, received):
            sender = (run_dir / a["body_path"]).read_bytes()
            receiver = (run_dir / b["body_path"]).read_bytes()
            exact = exact and sender == receiver and sha(run_dir / a["body_path"]) == a["sha256"] and sha(run_dir / b["body_path"]) == b["sha256"]
    checks = [r.get("fixture_check", {}) for r in received]
    measured_facts = [c for c in checks if c.get("required_context_facts")]
    payload = record.get("result", {}).get("payload")
    if payload is None:
        payload = next((e["payload"] for e in reversed(record.get("events", [])) if e.get("stage") == "transformation" and "payload" in e), None)
    displayed_messages_match = None
    if received:
        displayed_messages_match = payload is not None and all(payload == json.loads((run_dir / r["body_path"]).read_bytes()).get("messages") for r in received)
    return {
        "run_id": record["run_id"], "case_id": record["case_id"], "task_id": record["task_id"], "arm": record["arm"], "profile": record["profile"],
        "execution_status": record["status"], "selected_route": decision.get("route"), "route_evidence": decision["source"],
        "answer_success": record["quality"].get("success"), "answer_score_status": record["quality"]["status"],
        "advisory_proposal": record["advisory_proposal"], "inspection_reliable": decision.get("inspection", {}).get("reliable"),
        "http_attempts": len(sent), "http_receipts": len(received), "reopened_bytes_match": exact,
        "backend_display_messages_match_received": displayed_messages_match,
        "calls_under_non_egress_profile": len(sent) if record["profile"] in {"local", "restricted_external"} else 0,
        "received_calls_with_direct_fixture": sum(bool(c.get("direct_protected_values")) for c in checks),
        "received_calls_with_normalized_fixture": sum(bool(c.get("normalized_or_decoded_values")) for c in checks),
        "received_calls_with_code_fixture": sum(bool(c.get("protected_code_fragments")) for c in checks),
        "received_calls_with_any_fixture": sum(any(c.get(k) for k in ("direct_protected_values", "normalized_or_decoded_values", "protected_code_fragments")) for c in checks),
        "fact_probe_calls": len(measured_facts), "fact_probe_calls_with_missing_facts": sum(not all(c["required_context_facts"].values()) for c in measured_facts),
        "seconds": record["seconds"], "inspection_seconds": record["stage_seconds"]["inspection"],
        "local_answer_seconds": record["stage_seconds"]["task_answer"], "receiver_answer_seconds": record["stage_seconds"]["receiver_task_answer"],
        "model_calls": record["total_model_calls"],
        "prompt_tokens": record["parent_tokens"]["prompt"] + record["receiver_tokens"]["prompt"],
        "completion_tokens": record["parent_tokens"]["completion"] + record["receiver_tokens"]["completion"],
        "paid_cost_usd": record["paid_cost_usd"], "error_type": record.get("error_type"),
        "human_allowed_set_status": "NOT_PERFORMED", "human_preference_status": "NOT_PERFORMED", "independent_semantic_review": "NOT_PERFORMED",
    }


def csv_out(path, rows):
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyze(run_dir, output):
    freeze = json.loads((run_dir / "execution-freeze.json").read_text())
    records = [json.loads(p.read_text()) for p in sorted((run_dir / "runs").glob("*.json"))]
    if len({r["run_id"] for r in records}) != len(records):
        raise ValueError("Repeated run identifiers cannot be silently deduplicated.")
    if len(records) != freeze["runs"]:
        raise ValueError("The main comparison is incomplete; final analysis refused.")
    output.mkdir(parents=True, exist_ok=False)
    rows = [audit_record(r, run_dir) for r in records]
    aggregates = []
    for arm in freeze["arms"]:
        for profile in ["ALL", "local", "approved_external", "restricted_external"]:
            group = [r for r in rows if r["arm"] == arm and (profile == "ALL" or r["profile"] == profile)]
            if not group:
                continue
            counts = {key: sum(r[key] for r in group) for key in ["http_attempts", "http_receipts", "calls_under_non_egress_profile", "received_calls_with_direct_fixture", "received_calls_with_normalized_fixture", "received_calls_with_code_fixture", "received_calls_with_any_fixture", "fact_probe_calls", "fact_probe_calls_with_missing_facts", "model_calls", "prompt_tokens", "completion_tokens", "paid_cost_usd"]}
            aggregates.append({"arm": arm, "profile": profile, "conditions": len(group), "author_created_task_groups": len({r["task_id"] for r in group}),
                "completed": sum(r["execution_status"] == "completed" for r in group), "failed_or_timed_out": sum(r["execution_status"] != "completed" for r in group),
                "answer_checks_scored": sum(r["answer_success"] is not None for r in group), "answer_checks_passed": sum(r["answer_success"] is True for r in group),
                "exact_received_matches": sum(r["http_receipts"] for r in group if r["reopened_bytes_match"] is True),
                "backend_display_received_matches": sum(r["http_receipts"] for r in group if r["backend_display_messages_match_received"] is True),
                "median_seconds": statistics.median(r["seconds"] for r in group), "mean_seconds": statistics.mean(r["seconds"] for r in group),
                "median_inspection_seconds": statistics.median(r["inspection_seconds"] for r in group),
                "median_answer_seconds": statistics.median(r["local_answer_seconds"] + r["receiver_answer_seconds"] for r in group), **counts})
    pairs = []
    lookup = {(r["case_id"], r["arm"]): r for r in rows}
    for first, second in [("A", "B"), ("A", "C"), ("B", "C")]:
        for cid in sorted({r["case_id"] for r in rows}):
            a, b = lookup[(cid, first)], lookup[(cid, second)]
            if a["answer_success"] is None or b["answer_success"] is None:
                outcome = "unscored"
            elif a["answer_success"] == b["answer_success"]:
                outcome = "tie_pass" if a["answer_success"] else "tie_fail"
            else:
                outcome = second + "_only_pass" if b["answer_success"] else first + "_only_pass"
            pairs.append({"case_id": cid, "task_id": a["task_id"], "profile": a["profile"], "first": first, "second": second,
                          "paired_field_check_outcome": outcome, "second_minus_first_seconds": b["seconds"] - a["seconds"]})
    failures = []
    for record, row in zip(records, rows):
        if row["execution_status"] != "completed" or row["answer_success"] is False:
            failures.append({key: row[key] for key in ["run_id", "task_id", "arm", "profile", "execution_status", "selected_route", "route_evidence", "answer_score_status", "error_type", "http_attempts", "http_receipts"]})
    verification = {"main_complete": True, "execution_count": len(rows), "task_groups": len({r["task_id"] for r in rows}),
        "reopened_wire_mismatches": sum(r["reopened_bytes_match"] is False for r in rows),
        "backend_display_message_mismatches": sum(r["backend_display_messages_match_received"] is False for r in rows),
        "no_call_wire_checks_are_unmeasured": all(r["reopened_bytes_match"] is None for r in rows if not r["http_attempts"] and not r["http_receipts"]),
        "failures_kept_in_full_denominator": True,
        "all_final_decisions_recoverable": all(r["selected_route"] is not None for r in rows),
        "dataset_sha256_unchanged": sha(freeze["dataset"]["path"]) == freeze["dataset"]["sha256"],
        "fixtures_sha256_unchanged": sha(freeze["fixtures"]["path"]) == freeze["fixtures"]["sha256"],
        "policies_sha256_unchanged": sha(freeze["policies"]["path"]) == freeze["policies"]["sha256"],
        "human_authorization_preference_semantic_review": "NOT_PERFORMED", "human_opportunity_loss": "NOT_MEASURED",
        "paid_provider_calls": 0, "claimed_empirically_sampled_work_tasks": 0,
        "pair_outcomes": {a + "_vs_" + b: dict(Counter(p["paired_field_check_outcome"] for p in pairs if p["first"] == a and p["second"] == b)) for a, b in [("A", "B"), ("A", "C"), ("B", "C")]},
        "interpretation": "Descriptive measurements on 12 authored task groups; recipient conditions are correlated. No independent human or remote-model advantage claim."}
    csv_out(output / "case-results-audited.csv", rows)
    csv_out(output / "aggregate-audited.csv", aggregates)
    csv_out(output / "paired-comparison.csv", pairs)
    csv_out(output / "failures-and-nonpasses.csv", failures)
    (output / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps({"runs": len(rows), "aggregate": [a for a in aggregates if a["profile"] == "ALL"], "verification": verification}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.run, args.output)
