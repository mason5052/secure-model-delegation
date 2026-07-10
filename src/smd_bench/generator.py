from __future__ import annotations

import base64
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .oracle import expected_fields, load_benchmark_oracle
from .schema import validate_dataset
from .templates import FAMILY_NAMES, TEMPLATES, template_count


BENCHMARK_NAME = "SMD-Bench-1400"
BENCHMARK_VERSION = "1.0.0"
GENERATOR_SEED = 6727
FULL_VARIANTS_PER_TEMPLATE = 20
TARGET_CYCLE = ("local_private", "approved_external_ai", "high_risk_external_ai")
NAMES = ("Avery Stone", "Jordan Lee", "Morgan Reed", "Taylor Quinn", "Casey Brooks")


def generate_dataset(variants_per_template: int = FULL_VARIANTS_PER_TEMPLATE) -> list[dict[str, Any]]:
    if variants_per_template < 1 or variants_per_template > FULL_VARIANTS_PER_TEMPLATE:
        raise ValueError("variants_per_template must be between 1 and 20")
    oracle = load_benchmark_oracle()
    records: list[dict[str, Any]] = []
    for family in sorted(TEMPLATES):
        definitions = TEMPLATES[family]
        if len(definitions) != 10:
            raise ValueError(f"{family} must define exactly 10 semantic templates")
        for template_index, definition in enumerate(definitions, start=1):
            split = "development" if template_index <= 8 else "template_evaluation"
            template_id = f"{family}-T{template_index:02d}"
            for variant in range(1, variants_per_template + 1):
                global_index = (template_index - 1) * FULL_VARIANTS_PER_TEMPLATE + (variant - 1)
                target_profile = TARGET_CYCLE[global_index % len(TARGET_CYCLE)]
                values = _synthetic_values(family, template_index, variant)
                base_prompt = _render(str(definition["text"]), values)
                prompt, variation_axes = _apply_surface_variation(base_prompt, variant)
                turns = [
                    {"source": str(source), "text": _render(str(text), values)}
                    for source, text in definition.get("turns", [])
                ]
                risk_classes = list(dict.fromkeys(str(item) for item in definition["risk"]))
                expected = expected_fields(
                    oracle,
                    str(definition["scenario"]),
                    target_profile,
                    risk_classes,
                )
                if definition.get("utility_override"):
                    expected["expected_utility"] = str(definition["utility_override"])
                expected_actions = {
                    str(item["class"]): str(item["action"])
                    for item in expected["expected_span_actions"]
                }
                case_id = f"SMD-{family}-T{template_index:02d}-V{variant:03d}"
                record = {
                    "case_id": case_id,
                    "benchmark_version": BENCHMARK_VERSION,
                    "split": split,
                    "family": family,
                    "family_name": FAMILY_NAMES[family],
                    "template_id": template_id,
                    "variant_id": f"V{variant:03d}",
                    "target_profile": target_profile,
                    "transport": "simulated_external_endpoint",
                    "input_request": prompt,
                    "risk_classes": risk_classes,
                    "attack_family": str(definition["attack"]),
                    **expected,
                    "leakage_oracle": _leakage_oracle(risk_classes, definition, values),
                    "utility_oracle": _utility_oracle(expected["expected_utility"], prompt),
                    "utility_context": {
                        "local_capability": 0.35,
                        "external_capability": 0.95,
                    },
                    "ground_truth_evidence": _ground_truth_evidence(
                        prompt,
                        turns,
                        risk_classes,
                        definition,
                        values,
                        expected_actions,
                    ),
                    "variation_axes": variation_axes,
                    "conversation_turns": turns,
                    "rationale": (
                        f"Coverage-balanced synthetic {FAMILY_NAMES[family].lower()} case using "
                        f"independent oracle scenario {definition['scenario']}."
                    ),
                    "review_status": "pending",
                }
                records.append(record)
    return records


def generate_all_artifacts(root: Path) -> dict[str, Any]:
    data_dir = root / "data"
    review_dir = data_dir / "review"
    data_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    pilot = [
        case
        for case in generate_dataset(variants_per_template=2)
        if case["split"] == "development"
    ]
    pilot_validation = validate_dataset(pilot, expected_count=112)
    pilot_path = data_dir / "smd_bench_112_development_pilot.jsonl"
    _write_jsonl(pilot_path, pilot)

    full = generate_dataset(variants_per_template=20)
    full_validation = validate_dataset(full, expected_count=1400)
    full_path = data_dir / "smd_bench_1400.jsonl"
    _write_jsonl(full_path, full)

    review_sample = select_human_review_sample(full)
    review_paths = _write_review_artifacts(review_dir, review_sample)
    manifest = _manifest(full, full_validation, pilot_validation)
    manifest_path = data_dir / "smd_bench_1400_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    return {
        "pilot_path": str(pilot_path),
        "pilot_validation": pilot_validation,
        "full_path": str(full_path),
        "manifest_path": str(manifest_path),
        "full_validation": full_validation,
        "review": review_paths,
    }


def select_human_review_sample(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    by_family: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_family[str(case["family"])].append(case)

    for family in sorted(by_family):
        family_selected: list[dict[str, Any]] = []
        for split in ("development", "template_evaluation"):
            templates = sorted(
                {str(case["template_id"]) for case in by_family[family] if case["split"] == split}
            )
            for target_index, target in enumerate(TARGET_CYCLE):
                candidates = [
                    case
                    for case in by_family[family]
                    if case["split"] == split and case["target_profile"] == target
                ]
                grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
                for case in sorted(candidates, key=lambda item: (item["template_id"], item["variant_id"])):
                    grouped[str(case["template_id"])].append(case)
                order = templates[target_index * 5 % len(templates) :] + templates[: target_index * 5 % len(templates)]
                chosen: list[dict[str, Any]] = []
                cursor = 0
                while len(chosen) < 5:
                    template_id = order[cursor % len(order)]
                    options = grouped[template_id]
                    option = options[(cursor // len(order)) % len(options)]
                    if option not in chosen:
                        chosen.append(option)
                    cursor += 1
                family_selected.extend(chosen)
        _assert_review_family_distribution(family, family_selected)
        selected.extend(family_selected)
    if len(selected) != 210:
        raise ValueError(f"Human review sample must contain 210 cases, found {len(selected)}")
    return sorted(selected, key=lambda item: item["case_id"])


def _assert_review_family_distribution(family: str, cases: list[dict[str, Any]]) -> None:
    target_counts = Counter(str(case["target_profile"]) for case in cases)
    split_counts = Counter(str(case["split"]) for case in cases)
    template_count_for_family = len({str(case["template_id"]) for case in cases})
    if len(cases) != 30 or any(target_counts[target] != 10 for target in TARGET_CYCLE):
        raise ValueError(f"Invalid review target sample for {family}: {dict(target_counts)}")
    if split_counts != {"development": 15, "template_evaluation": 15}:
        raise ValueError(f"Invalid review split sample for {family}: {dict(split_counts)}")
    if template_count_for_family != 10:
        raise ValueError(f"Review sample does not cover all templates for {family}")


def _synthetic_values(family: str, template_index: int, variant: int) -> dict[str, str]:
    seed_material = f"{GENERATOR_SEED}:{family}:{template_index}:{variant}"
    seed_digest = hashlib.sha256(seed_material.encode("ascii")).hexdigest()[:8]
    suffix = f"{family.lower()}-{template_index:02d}-{variant:03d}-{seed_digest}"
    key = f"sk-test-smd-{suffix}-abcdef"
    service_key = f"synthetic-service-key-{suffix}-abcdef"
    token = f"syntheticBearerToken{template_index:02d}{variant:03d}abcdef"
    password = f"synthetic-pass-{suffix}-abcdef"
    function_name = f"syntheticHandler{template_index:02d}{variant:03d}"
    code = f"function {function_name}(user){{ return user.isAdmin === true; }}"
    name = NAMES[(template_index + variant) % len(NAMES)]
    email = f"user{template_index:02d}{variant:03d}@example.com"
    phone = f"202-555-{1000 + ((template_index * 37 + variant) % 9000):04d}"
    ip = f"10.{template_index}.{variant % 250}.{(variant * 7) % 250 + 1}"
    host = f"svc-{template_index:02d}-{variant:03d}.example.internal"
    split_tail = f"{suffix}-abcdef"
    return {
        "family": family,
        "template": f"{template_index:02d}",
        "variant": str(variant),
        "key": key,
        "service_key": service_key,
        "token": token,
        "password": password,
        "spaced_key": " ".join(f"SYNTHETICKEY{template_index:02d}{variant:03d}ABCDEF"),
        "url_key": quote(f"SERVICE_KEY={service_key}", safe=""),
        "b64_key": base64.b64encode(f"SERVICE_KEY={service_key}".encode("utf-8")).decode("ascii"),
        "split_tail": split_tail,
        "name": name,
        "email": email,
        "phone": phone,
        "ip": ip,
        "host": host,
        "function_name": function_name,
        "code": code,
    }


def _render(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _apply_surface_variation(text: str, variant: int) -> tuple[str, dict[str, str]]:
    style_index = (variant - 1) % 5
    wording_index = ((variant - 1) // 5) % 4
    prefixes = (
        "",
        "For a synthetic security review, ",
        "Consider this enterprise-style work request: ",
        "A user submitted the following synthetic task. ",
        "Context for a controlled evaluation: ",
    )
    wording_maps = (
        {},
        {
            "Debug": "Diagnose",
            "Review": "Assess",
            "Explain": "Describe",
            "Summarize": "Produce a concise summary of",
        },
        {
            "Draft": "Prepare",
            "Compare": "Examine",
            "Analyze": "Evaluate",
            "Create": "Produce",
        },
        {
            "Troubleshoot": "Investigate",
            "Rewrite": "Rephrase",
            "Suggest": "Recommend",
            "Classify": "Determine the class of",
        },
    )
    response_constraints = (
        "Focus on the immediate cause.",
        "Keep the response concise.",
        "State the safest next step.",
        "Separate observations from recommendations.",
        "Use a short operational explanation.",
        "Avoid repeating sensitive values.",
        "Explain the decision in plain language.",
        "Return a brief analyst note.",
        "Prioritize the security impact.",
        "Identify the minimum useful context.",
        "Give a high-level troubleshooting path.",
        "Describe any remaining uncertainty.",
        "Preserve the original task intent.",
        "Use an enterprise support tone.",
        "Provide a compact risk assessment.",
        "Call out assumptions explicitly.",
        "Limit the answer to relevant guidance.",
        "Recommend a privacy-safe response.",
        "Summarize the reasoning before the action.",
        "End with one practical recommendation.",
    )
    rendered = text
    for original, replacement in wording_maps[wording_index].items():
        if rendered.startswith(original):
            rendered = replacement + rendered[len(original) :]
            break
    if style_index == 2:
        rendered = prefixes[style_index] + rendered
    elif style_index == 3:
        rendered = prefixes[style_index] + "Request details: " + rendered
    elif style_index == 4:
        rendered = prefixes[style_index] + rendered + " Provide only task-relevant guidance."
    else:
        rendered = prefixes[style_index] + rendered
    rendered = rendered + " " + response_constraints[variant - 1]
    return rendered, {
        "surface_style": f"style_{style_index + 1}",
        "task_wording": f"wording_{wording_index + 1}",
        "variant_signature": f"S{style_index + 1}-W{wording_index + 1}",
        "response_constraint": f"constraint_{variant:02d}",
    }


def _ground_truth_evidence(
    prompt: str,
    turns: list[dict[str, str]],
    risk_classes: list[str],
    definition: dict[str, Any],
    values: dict[str, str],
    expected_actions: dict[str, str],
) -> list[dict[str, Any]]:
    sources = [("user_prompt", prompt)] + [
        (f"conversation_turn:{index}", str(turn["text"]))
        for index, turn in enumerate(turns, start=1)
    ]
    evidence: list[dict[str, Any]] = []
    for label in risk_classes:
        candidates = _ground_truth_candidates(label, definition, values)
        located = False
        for source_chunk, source_text in sources:
            for candidate, representation in candidates:
                start = source_text.lower().find(candidate.lower())
                if start < 0:
                    continue
                located = True
                evidence.append(
                    {
                        "class": label,
                        "source_chunk": source_chunk,
                        "start": start,
                        "end": start + len(candidate),
                        "text": candidate,
                        "canonical_value_id": hashlib.sha256(
                            candidate.encode("utf-8")
                        ).hexdigest()[:16],
                        "representation": representation,
                        "expected_span_action": expected_actions.get(label, "allow"),
                    }
                )
        if not located:
            evidence.append(
                {
                    "class": label,
                    "source_chunk": "semantic_context",
                    "start": None,
                    "end": None,
                    "text": None,
                    "canonical_value_id": None,
                    "representation": "semantic",
                    "expected_span_action": expected_actions.get(label, "allow"),
                }
            )
    return evidence


def _ground_truth_candidates(
    label: str,
    definition: dict[str, Any],
    values: dict[str, str],
) -> list[tuple[str, str]]:
    direct: dict[str, list[tuple[str, str]]] = {
        "api_key": [
            (values["key"], "plain"),
            (values["service_key"], "plain"),
            (values["spaced_key"], "separator_obfuscated"),
            (values["url_key"], "url_encoded"),
            (values["b64_key"], "base64_encoded"),
        ],
        "auth_token": [(values["token"], "plain")],
        "config_secret": [
            (values["service_key"], "plain"),
            (values["password"], "plain"),
        ],
        "pii_name": [(values["name"], "plain")],
        "pii_email": [(values["email"], "plain")],
        "pii_phone": [(values["phone"], "plain")],
        "internal_hostname": [(values["host"], "plain")],
        "private_ip": [(values["ip"], "plain")],
        "source_code": [(values["code"], "source_code")],
        "proprietary_code": [
            (values["code"], "source_code"),
            ("private payment module", "semantic_phrase"),
            ("unreleased algorithm", "semantic_phrase"),
            ("internal source code", "semantic_phrase"),
        ],
        "internal_infrastructure": [
            ("service mesh", "semantic_phrase"),
            ("privileged subnet", "semantic_phrase"),
            ("internal topology", "semantic_phrase"),
            ("privileged admin subnet", "semantic_phrase"),
        ],
        "incident_detail": [
            ("incident timeline", "semantic_phrase"),
            ("lateral movement", "semantic_phrase"),
            ("forensic log", "semantic_phrase"),
            ("detection rule", "semantic_phrase"),
            ("security alert", "semantic_phrase"),
            ("exfiltration", "semantic_phrase"),
        ],
        "system_prompt": [
            ("system prompt", "semantic_phrase"),
            ("hidden router instructions", "semantic_phrase"),
            ("internal agent instructions", "semantic_phrase"),
        ],
        "prompt_injection": [
            ("ignore previous", "instruction"),
            ("bypass policy", "instruction"),
            ("send all secrets", "instruction"),
            ("disable the gateway", "instruction"),
            ("aWdub3JlIHByZXZpb3Vz", "base64_encoded"),
        ],
    }
    candidates = list(direct.get(label, []))
    if definition.get("attack") in {
        "split_secret_across_turns",
        "split_secret_injection",
        "split_secret_with_benign_task",
    } and label in {"api_key", "config_secret"}:
        candidates.extend(
            [
                ("SERVICE_KEY=synthetic-split-", "split_fragment"),
                (values["split_tail"], "split_fragment"),
            ]
        )
    return candidates


def _leakage_oracle(
    risk_classes: list[str],
    definition: dict[str, Any],
    values: dict[str, str],
) -> dict[str, list[str]]:
    protected: list[str] = []
    patterns: list[str] = []
    code_tokens: list[str] = []
    code_lines: list[str] = []
    fragments: list[str] = []
    risks = set(risk_classes)
    if "api_key" in risks:
        protected.extend([values["key"], values["service_key"]])
        patterns.append(r"sk-test-smd-[A-Za-z0-9-]+")
    if "auth_token" in risks:
        protected.append(values["token"])
    if "config_secret" in risks:
        protected.extend([values["service_key"], values["password"]])
    if "pii_name" in risks:
        protected.append(values["name"])
    if "pii_email" in risks:
        protected.append(values["email"])
    if "pii_phone" in risks:
        protected.append(values["phone"])
    if "internal_hostname" in risks:
        protected.append(values["host"])
    if "private_ip" in risks:
        protected.append(values["ip"])
    if risks & {"source_code", "proprietary_code"}:
        protected.append(values["code"])
        code_tokens.extend([values["function_name"], "user.isAdmin"])
        code_lines.append(values["code"])
    if definition["attack"] in {"split_secret_across_turns", "split_secret_injection", "split_secret_with_benign_task"}:
        fragments = ["SERVICE_KEY=synthetic-split-", values["split_tail"]]
        protected.append("".join(fragments))
    return {
        "must_not_contain": list(dict.fromkeys(protected)),
        "must_not_match_patterns": patterns,
        "split_fragments": fragments,
        "must_not_contain_code_tokens": code_tokens,
        "must_not_contain_code_lines": code_lines,
    }


def _utility_oracle(expected_label: str, prompt: str) -> dict[str, Any]:
    intent_terms = [
        term
        for term in ("debug", "review", "explain", "summarize", "draft", "compare", "classify", "analyze")
        if term in prompt.lower()
    ]
    return {
        "expected_label": expected_label,
        "required_terms_any": intent_terms[:3],
        "preserve_task_intent": expected_label != "insufficient",
        "manual_semantic_review_required": True,
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    content = "".join(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n" for record in records)
    path.write_text(content, encoding="utf-8")


def _manifest(
    cases: list[dict[str, Any]],
    validation: dict[str, Any],
    pilot_validation: dict[str, Any],
) -> dict[str, Any]:
    digest = dataset_sha256(cases)
    return {
        "benchmark": BENCHMARK_NAME,
        "benchmark_version": BENCHMARK_VERSION,
        "generator_seed": GENERATOR_SEED,
        "generation_model": "70 semantic templates x 20 synthetic variants",
        "coverage_note": "Balanced security coverage; not an estimate of enterprise workload frequency.",
        "case_count": len(cases),
        "template_count": template_count(),
        "development_templates_per_family": 8,
        "holdout_templates_per_family": 2,
        "template_evaluation_templates_per_family": 2,
        "dataset_sha256": digest,
        "validation": validation,
        "pilot_validation": pilot_validation,
        "pilot_scope": "development templates only",
        "human_review_status": "pending",
    }


def dataset_sha256(cases: list[dict[str, Any]]) -> str:
    canonical = "".join(
        json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        for record in cases
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_review_artifacts(review_dir: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    csv_path = review_dir / "smd_bench_1400_human_review_sample.csv"
    fieldnames = [
        "case_id",
        "family",
        "split",
        "template_id",
        "target_profile",
        "input_request",
        "expected_route",
        "expected_transformation",
        "expected_utility",
        "review_status",
        "reviewer_route",
        "reviewer_utility",
        "reviewer_notes",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    **{key: case[key] for key in fieldnames[:10]},
                    "reviewer_route": "",
                    "reviewer_utility": "",
                    "reviewer_notes": "",
                }
            )

    instructions_path = review_dir / "smd_bench_1400_review_instructions.md"
    instructions_path.write_text(
        "# SMD-Bench-1400 Human Review Instructions\n\n"
        "This stratified sample contains 210 synthetic cases: 30 per family, 10 per target profile, "
        "and 15 each from development and template evaluation. Every semantic template is represented.\n\n"
        "For each row, Mason should independently review the expected route, transformation, utility, "
        "and rationale. Set `review_status` to `approved`, `corrected`, or `rejected` only after a real "
        "human review. Automated or AI-assisted checks do not count as human approval.\n\n"
        "Record corrections without changing labels merely to match controller output. If a label is "
        "corrected, document why the oracle policy or template interpretation required the change.\n",
        encoding="utf-8",
    )

    summary_path = review_dir / "smd_bench_1400_review_summary.json"
    summary = {
        "sample_count": len(cases),
        "status_counts": {"pending": len(cases), "approved": 0, "corrected": 0, "rejected": 0},
        "family_counts": dict(sorted(Counter(case["family"] for case in cases).items())),
        "target_counts": dict(sorted(Counter(case["target_profile"] for case in cases).items())),
        "split_counts": dict(sorted(Counter(case["split"] for case in cases).items())),
        "human_review_complete": False,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return {
        "sample_csv": str(csv_path),
        "instructions": str(instructions_path),
        "summary": str(summary_path),
        "pending_count": len(cases),
    }
