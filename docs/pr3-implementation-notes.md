# PR3 Implementation Notes

## What Changed From The Skeleton

- Replaced provider-specific routes such as OpenAI or Claude delegation with provider-neutral route labels.
- Separated request route from transport. The PR3 prototype routes to External AI, then uses `simulated_external_endpoint` as the transport.
- Expanded the policy model from action-priority logic into a policy-bounded controller that considers transformed payload safety and remaining utility.
- Added source-code handling that blocks raw code delegation and uses pseudocode or generalized problem statements when external assistance is allowed.
- Changed prompt injection handling from a simple local-process case into a risk-amplifier signal that escalates when combined with credentials, code, or incident details.
- Expanded the benchmark from 6 to 32 synthetic cases.
- Added baseline comparison output for `no_gateway`, `regex_only`, `detector_only`, and the policy-bounded controller result.
- Added a local FastAPI web UI for browser-based manual testing and PR3/video demonstration.

## Implemented Components

- Request assembly and normalization.
- Evidence providers for synthetic API keys, auth tokens, config secrets, PII, internal hosts, private IPs, internal infrastructure cues, source code, proprietary code, incident details, system prompt extraction attempts, and prompt injection.
- Policy-bounded model delegation controller.
- Hard disclosure policy first.
- Advisory routing and utility estimation second.
- Sanitizer with stable placeholders and pseudocode/generalized-problem transformation support.
- Simulated external endpoint that records only approved delegated payloads.
- Audit log that stores decision metadata and request hashes, not raw input.
- Leakage oracle for direct raw span leakage, case-insensitive matching, whitespace-normalized matching, and forbidden patterns.
- Evaluation harness for route correctness, leakage rate, route counts, utility label counts, and baseline comparison.
- Web API and vanilla HTML/CSS/JavaScript control panel.

## Route Labels

- `local_process`
- `deny_request`
- `ask_clarification`
- `local_summary`
- `delegate_sanitized_to_external_ai`
- `delegate_pseudocode_to_external_ai`

## Conflict Resolution Logic

The controller does not choose the final route only from the single riskiest class. It applies the following PR3 v1 sequence:

1. Detect sensitive spans and risk signals.
2. Apply hard policy first.
3. Treat prompt injection as untrusted data and a risk amplifier, not as policy authority.
4. Keep system prompt extraction attempts inside the trusted boundary or deny them.
5. Keep incident detail plus topology local.
6. Convert source code to pseudocode or generalized problem statements when external help is safe enough.
7. Build a transformed payload.
8. Estimate whether enough utility remains.
9. Delegate only if the transformed payload is safe and useful enough.

## How To Run

```bash
python3 scripts/run_demo.py
python3 scripts/run_eval.py
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/run_web.py
```

## Current Demo

The demo covers:

- API key plus generic debugging, routed to sanitized external delegation.
- Source code review, routed to pseudocode external delegation.
- Prompt injection plus API key, routed to local summary.
- Benign public request, routed to sanitized external delegation.

## Current Evaluation Result

Latest Mac run:

- Benchmark count: 32
- Delegated cases: 14
- Route accuracy: 1.0
- Direct leakage count: 0
- Direct leakage rate: 0.0
- Utility labels: 4 insufficient, 14 partial, 14 sufficient
- Route counts: 2 ask clarification, 4 pseudocode delegation, 10 sanitized delegation, 1 deny, 3 local process, 12 local summary
- Unit tests: 13 tests passing

## Baseline Comparison

Latest Mac run:

- `no_gateway`: 32 delegated cases, 79 direct leakage findings
- `regex_only`: 32 delegated cases, 2 direct leakage findings
- `detector_only`: 32 delegated cases, 2 direct leakage findings
- `policy_bounded_controller`: 14 delegated cases, 0 direct leakage findings in the main evaluation

This comparison is intentionally limited. The baseline leakage values are direct
leakage finding counts, not proof of full privacy. They are useful PR3 evidence
that route-aware control matters, but they do not prove full semantic privacy.

## Remaining Limitations

- The detector layer is still rule-based and synthetic.
- The policy YAML is implemented as a design artifact, while the current runtime logic is encoded in Python.
- Utility estimation is rule-based and coarse.
- Baselines are simple and should be expanded before the final report.
- The leakage oracle checks direct leakage only. Semantic leakage remains a manual-review limitation.
- No real provider API calls are used in PR3.
- No real company data, internal data, customer data, logs, or secrets are used.

## PR3 Evidence

- Executable gateway prototype.
- Structured policy YAML artifact.
- 32 synthetic benchmark cases.
- Simulated external endpoint payload capture.
- Audit log with `raw_input_stored=false`.
- Direct leakage evaluation with zero findings for the policy-bounded controller.
- Baseline comparison showing why route-aware policy control is different from detector-only masking.
