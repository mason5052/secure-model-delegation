# Secure Model Delegation

Policy-bounded controller prototype for local-to-external AI fallback.

This repository contains a public-safe research prototype developed for a
Georgia Tech CS6727 cybersecurity practicum project. It is published with
synthetic data only so the prototype can be inspected and evaluated without
exposing company, customer, production, or credential data.

This is not a general PII detector, DLP product, or privacy masking tool. The
prototype demonstrates Policy-Bounded Model Delegation Control and Evaluation:
hard disclosure policy is applied first, and advisory routing is applied only
after policy-denied content is blocked or transformed.

## Architecture At A Glance

![Secure Model Delegation architecture](docs/assets/secure-model-delegation-architecture.png)

Diagram source: `docs/assets/secure-model-delegation-architecture.html`.

## Current Scope

- Text-only synthetic enterprise requests.
- Trusted local gateway running in Python.
- External AI is represented as a policy target profile, not a provider-specific
  route.
- Primary external target is a simulated endpoint that records sanitized or
  pseudocode-based delegated payloads for leakage evaluation.
- Real provider API calls are out of scope for the current prototype and remain
  optional sanitized-only future smoke tests.
- Route and transport are separated. For example, a request can use route
  `delegate_sanitized_to_external_ai` through transport
  `simulated_external_endpoint`.
- The controller resolves span-level actions into request-level routes using
  transformed payload safety plus remaining utility.

## Quick Start

Windows:

```powershell
py -3 -m pip install -r requirements.txt
$env:PYTHONPATH = "src"
py -3 scripts\run_demo.py
py -3 scripts\run_eval.py
py -3 -m unittest discover -s tests
```

macOS or Linux:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/run_demo.py
python3 scripts/run_eval.py
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Local Web UI

Install runtime dependencies if needed:

```bash
python3 -m pip install -r requirements.txt
```

Start the local web prototype:

```bash
python3 scripts/run_web.py
```

Open:

```text
http://127.0.0.1:6727
```

The web UI is a local research control panel, not a marketing page. It shows:

- Prompt input and selectable synthetic examples.
- Final route, utility label, hard action, transport, and target profile.
- Detected sensitive labels and safe span previews.
- Policy reasons, rule IDs, and advisory route.
- Delegated payload captured by the simulated external endpoint.
- Direct leakage check results.
- Audit and simulated endpoint artifact references.

Example workflow:

1. Select `API key debugging`.
2. Click `Process`.
3. Confirm the route is `delegate_sanitized_to_external_ai`.
4. Confirm the delegated payload contains `[API_KEY_1]`, not the raw synthetic key.
5. Select `Incident detail plus internal topology`.
6. Confirm the controller keeps the request local through `local_summary`.

This UI uses only the simulated external endpoint. It does not call real
OpenAI, Claude, or any other external model API.

Optional web smoke test:

```bash
python3 scripts/smoke_web.py
```

The demo and evaluation write run artifacts to `runs/`:

- `runs/demo/simulated_external_payloads.jsonl`
- `runs/eval/simulated_external_payloads.jsonl`
- `runs/demo/audit.jsonl`
- `runs/eval/audit.jsonl`

The audit log intentionally avoids storing raw secrets.

## Evaluation Summary

The current synthetic benchmark contains 60 labeled cases. The latest local
validation run produced the following public-safe results:

| Metric | Value |
| --- | ---: |
| Benchmark cases | 60 |
| Delegated cases | 26 |
| Route accuracy against current labels | 1.00 |
| Direct leakage findings | 0 |
| Over-blocked delegation false positives | 0 |
| Unsafe delegation false negatives | 0 |
| Adversarial or mixed-risk cases | 15 |
| Successful direct-leakage bypasses | 0 |
| Average local controller latency | about 1 ms/request |

Baseline comparison:

| Approach | Delegated cases | Direct leakage findings | Leakage case rate |
| --- | ---: | ---: | ---: |
| no_gateway | 60 | 164 | 0.85 |
| regex_only | 60 | 4 | 0.07 |
| detector_only | 60 | 4 | 0.07 |
| policy_bounded_controller | 26 | 0 | 0.00 |

Route distribution:

| Route | Count |
| --- | ---: |
| local_process | 7 |
| local_summary | 21 |
| ask_clarification | 4 |
| deny_request | 2 |
| delegate_sanitized_to_external_ai | 20 |
| delegate_pseudocode_to_external_ai | 6 |

These results are limited to the current synthetic benchmark and direct leakage
oracle. They do not prove full semantic privacy.

For representative route examples, sanitized delegated payloads, public-safe
audit examples, and metric interpretation, see
[`docs/evaluation-summary.md`](docs/evaluation-summary.md).

## Data And Safety Notes

- All benchmark cases are synthetic.
- Do not add company data, customer data, production logs, real credentials, or
  real source code to this repository.
- Runtime artifacts are written to `runs/` and are intentionally ignored by Git.
- The current leakage oracle checks direct leakage only. Semantic leakage
  remains a limitation for later research.
- This public repository intentionally excludes raw runtime logs, local absolute
  paths, course submission drafts, and real provider API traces.

## License

This project is licensed under the MIT License. See `LICENSE`.
