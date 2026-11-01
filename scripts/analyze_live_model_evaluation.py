"""Audit completed live runs without rewriting raw execution artifacts."""
from __future__ import annotations

import argparse
import csv
import errno
import hashlib
import json
import os
import queue
import statistics
import threading
import time
from collections import Counter
from pathlib import Path


def read_artifact(path, *, timeout=10.0, max_bytes=64 * 1024**2):
    """Read a complete immutable artifact, rejecting stalled or partial reads.

    Nonblocking descriptors address local artifact read stalls observed on macOS. A
    daemon reader also bounds the caller's wait when a filesystem ignores that
    flag. A stalled read is never treated as an empty or successfully read file.
    """
    path = Path(path)
    if timeout <= 0 or max_bytes < 0:
        raise ValueError("Artifact read bounds must be positive.")
    results = queue.Queue(maxsize=1)
    deadline = time.monotonic() + timeout

    def read_complete():
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
            before = os.fstat(descriptor)
            if before.st_size > max_bytes:
                raise ValueError(f"Artifact exceeds the read size bound: {path.name}")
            chunks, count = [], 0
            while count < before.st_size:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Artifact read timed out: {path.name}")
                try:
                    chunk = os.read(descriptor, min(1024**2, before.st_size - count))
                except OSError as exc:
                    if exc.errno not in {errno.EAGAIN, errno.EWOULDBLOCK}:
                        raise
                    time.sleep(min(.02, max(0, deadline - time.monotonic())))
                    continue
                if not chunk:
                    raise OSError(f"Incomplete artifact read: {path.name} ({count}/{before.st_size} bytes)")
                chunks.append(chunk)
                count += len(chunk)
            after = os.fstat(descriptor)
            if count != before.st_size or after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
                raise OSError(f"Artifact changed during the read: {path.name}")
            results.put((True, b"".join(chunks)))
        except BaseException as exc:
            results.put((False, exc))
        finally:
            if descriptor is not None:
                os.close(descriptor)

    reader = threading.Thread(target=read_complete, daemon=True)
    reader.start()
    try:
        success, value = results.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"Artifact read timed out: {path.name}") from None
    reader.join(timeout=max(0, deadline - time.monotonic()))
    if reader.is_alive():
        raise TimeoutError(f"Artifact descriptor cleanup timed out: {path.name}")
    if not success:
        raise value
    return value


def sha(path):
    return hashlib.sha256(read_artifact(path)).hexdigest()


def progress(stage, **metadata):
    print(json.dumps({"stage": stage, **metadata}), flush=True)


def selected_decision(record):
    result = record.get("result")
    if result is not None:
        return {"route": result.get("route"), "inspection": result.get("inspection", {}), "source": "returned_result"}
    for event in reversed(record.get("events", [])):
        if event.get("stage") == "decision" and "decision" in event:
            return {**event["decision"], "source": "decision_event_before_answer_failure"}
    return {"route": None, "inspection": {}, "source": "no_decision_observed"}


def native_call_index(run_dir):
    index = {}
    paths = sorted((run_dir / "model-calls").glob("*.json"))
    progress("reading_native_calls", total=len(paths))
    for sequence, path in enumerate(paths, 1):
        call = json.loads(read_artifact(path))
        index.setdefault(call["run_id"], []).append(call)
        if sequence % 25 == 0 or sequence == len(paths):
            progress("native_calls_read", count=sequence, total=len(paths))
    return index


def measured_native_usage(record, index):
    calls = list(index.get(record["run_id"], []))
    for receipt in record.get("receipts", []):
        calls.extend(index.get(f"receipt-{receipt['sequence']:05d}", []))
    return {"model_calls": len(calls),
            "prompt_tokens": sum(c.get("response", {}).get("prompt_eval_count", 0) for c in calls),
            "completion_tokens": sum(c.get("response", {}).get("eval_count", 0) for c in calls),
            "native_usage_unobserved_calls": sum("prompt_eval_count" not in c.get("response", {}) or "eval_count" not in c.get("response", {}) for c in calls),
            "output_limit_native_calls": sum(c.get("response", {}).get("done_reason") == "length" for c in calls)}


def audit_record(record, run_dir, native_index=None):
    decision = selected_decision(record)
    sent, received = record.get("wire_requests", []), record.get("receipts", [])
    exact = None
    received_messages = []
    if sent or received:
        exact = len(sent) == len(received)
        for a, b in zip(sent, received):
            sender = read_artifact(run_dir / a["body_path"])
            receiver = read_artifact(run_dir / b["body_path"])
            exact = exact and sender == receiver and hashlib.sha256(sender).hexdigest() == a["sha256"] and hashlib.sha256(receiver).hexdigest() == b["sha256"]
            received_messages.append(json.loads(receiver).get("messages"))
    checks = [r.get("fixture_check", {}) for r in received]
    measured_facts = [c for c in checks if c.get("required_context_facts")]
    payload = record.get("result", {}).get("payload")
    if payload is None:
        payload = next((e["payload"] for e in reversed(record.get("events", [])) if e.get("stage") == "transformation" and "payload" in e), None)
    displayed_messages_match = None
    if received:
        displayed_messages_match = payload is not None and len(received_messages) == len(received) and all(payload == messages for messages in received_messages)
    usage = measured_native_usage(record, native_index) if native_index is not None else {"model_calls": record["total_model_calls"], "prompt_tokens": record["parent_tokens"]["prompt"] + record["receiver_tokens"]["prompt"], "completion_tokens": record["parent_tokens"]["completion"] + record["receiver_tokens"]["completion"], "native_usage_unobserved_calls": None, "output_limit_native_calls": None}
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
        **usage,
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
    progress("reading_execution_freeze")
    freeze = json.loads(read_artifact(run_dir / "execution-freeze.json"))
    paths = sorted((run_dir / "runs").glob("*.json"))
    records = []
    progress("reading_run_records", total=len(paths))
    for sequence, path in enumerate(paths, 1):
        records.append(json.loads(read_artifact(path)))
        if sequence % 25 == 0 or sequence == len(paths):
            progress("run_records_read", count=sequence, total=len(paths))
    if len({r["run_id"] for r in records}) != len(records):
        raise ValueError("Repeated run identifiers cannot be silently deduplicated.")
    if len(records) != freeze["runs"]:
        raise ValueError("The main comparison is incomplete; final analysis refused.")
    output.mkdir(parents=True, exist_ok=False)
    native_index = native_call_index(run_dir)
    rows = []
    progress("auditing_received_bodies", total_runs=len(records))
    for sequence, record in enumerate(records, 1):
        rows.append(audit_record(record, run_dir, native_index))
        if sequence % 25 == 0 or sequence == len(records):
            progress("received_body_audits", count=sequence, total_runs=len(records))
    aggregates = []
    for arm in freeze["arms"]:
        for profile in ["ALL", "local", "approved_external", "restricted_external"]:
            group = [r for r in rows if r["arm"] == arm and (profile == "ALL" or r["profile"] == profile)]
            if not group:
                continue
            counts = {key: sum(r[key] for r in group) for key in ["http_attempts", "http_receipts", "calls_under_non_egress_profile", "received_calls_with_direct_fixture", "received_calls_with_normalized_fixture", "received_calls_with_code_fixture", "received_calls_with_any_fixture", "fact_probe_calls", "fact_probe_calls_with_missing_facts", "model_calls", "prompt_tokens", "completion_tokens", "native_usage_unobserved_calls", "output_limit_native_calls", "paid_cost_usd"]}
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
        "token_accounting": "Recomputed from native model HTTP traces, including received requests whose answer hit its output limit. Calls without native usage are marked unknown, not zero compute.",
        "pair_outcomes": {a + "_vs_" + b: dict(Counter(p["paired_field_check_outcome"] for p in pairs if p["first"] == a and p["second"] == b)) for a, b in [("A", "B"), ("A", "C"), ("B", "C")]},
        "interpretation": "Descriptive measurements on 12 authored task groups; recipient conditions are correlated. No independent human or remote-model advantage claim."}
    verification["artifact_read_method"] = "Bounded nonblocking descriptor reads; byte count and immutable-file size/mtime verified; partial reads rejected."
    progress("writing_final_analysis", runs=len(rows))
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
