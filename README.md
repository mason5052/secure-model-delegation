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

## Decision Model

The core decision problem is not whether the gateway can detect sensitive text.
The core problem is deciding how an AI request should cross, or not cross, a
model boundary.

At a high level, the controller evaluates each request as:

```text
route = controller(evidence, target_profile, disclosure_policy, utility_signal)
```

Where:

- `evidence` is the set of detected signals in the request, such as API keys,
  authentication tokens, PII, internal hostnames, source code, incident details,
  or prompt-injection text.
- `target_profile` describes the intended model target, such as a trusted local
  model, an approved external AI target, or a high-risk external target.
- `disclosure_policy` defines what each target is allowed to receive, what must
  be transformed, and what must remain inside the trusted boundary.
- `utility_signal` is an advisory estimate of whether a transformed request is
  still useful enough to delegate.

The controller returns one of a small set of route decisions:

| Route | Meaning |
| --- | --- |
| `local_process` | Keep the request inside the trusted local/private boundary. |
| `deny_request` | Refuse the request because the policy risk is too high. |
| `ask_clarification` | Ask the user to narrow or clarify the request before routing. |
| `local_summary` | Produce a local-only summary without external delegation. |
| `delegate_sanitized_to_external_ai` | Send only a sanitized payload to the simulated external target. |
| `delegate_pseudocode_to_external_ai` | Send only pseudocode or a generalized problem statement to the simulated external target. |

The policy order is intentional. Hard disclosure policy is applied before
advisory routing. Evidence providers and utility heuristics can inform the
decision, but they do not have authority to override policy-denied content.

For example, source code can be handled differently depending on the target:

| Target profile | Source-code policy | Resulting route |
| --- | --- | --- |
| `local_private` | Raw code may be used locally. | `local_process` |
| `approved_external_ai` | Raw code cannot cross the boundary; convert to pseudocode or a generalized problem statement. | `delegate_pseudocode_to_external_ai` |
| `high_risk_external_ai` | No code-derived external payload is allowed. | `local_summary` |

This is the main distinction from a generic privacy filter. A detector might
say "this span looks sensitive." The Secure Model Delegation controller decides
what model target, if any, may receive the request and in what form.

## Current Scope

- Text-only synthetic enterprise requests.
- Trusted local gateway running in Python.
- External AI is represented as a policy target profile, not a provider-specific
  route.
- Current target profiles include `local_private`, `approved_external_ai`, and
  `high_risk_external_ai`. The legacy `external_ai` profile is treated as an
  approved external profile for compatibility.
- Primary external target is a simulated endpoint that records sanitized or
  pseudocode-based delegated payloads for leakage evaluation.
- Real provider API calls are out of scope for the current prototype and remain
  optional sanitized-only future smoke tests.
- Route and transport are separated. For example, a request can use route
  `delegate_sanitized_to_external_ai` through transport
  `simulated_external_endpoint`.
- The controller resolves span-level actions into request-level routes using
  transformed payload safety plus remaining utility.
- Source-code requests demonstrate target-specific control: raw source code can
  be processed by a trusted local/private model, approved external targets get
  pseudocode or a generalized problem statement only, and high-risk external
  targets receive local summary only.

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
7. Select the source-code examples to compare local, approved external, and
   high-risk external target profiles.

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

The current synthetic benchmark contains 63 labeled cases. The latest local
validation run produced the following public-safe results:

| Metric | Value |
| --- | ---: |
| Benchmark cases | 63 |
| Delegated cases | 27 |
| Route accuracy against current labels | 1.00 |
| Direct leakage findings | 0 |
| Over-blocked delegation false positives | 0 |
| Unsafe delegation false negatives | 0 |
| Adversarial or mixed-risk cases | 15 |
| Successful direct-leakage bypasses | 0 |
| Average local controller latency | about 0.6 ms/request |

Baseline comparison:

| Approach | Delegated cases | Direct leakage findings | Leakage case rate |
| --- | ---: | ---: | ---: |
| no_gateway | 63 | 170 | 0.86 |
| regex_only | 63 | 4 | 0.06 |
| detector_only | 63 | 4 | 0.06 |
| policy_bounded_controller | 27 | 0 | 0.00 |

Route distribution:

| Route | Count |
| --- | ---: |
| local_process | 8 |
| local_summary | 22 |
| ask_clarification | 4 |
| deny_request | 2 |
| delegate_sanitized_to_external_ai | 20 |
| delegate_pseudocode_to_external_ai | 7 |

These results are limited to the current synthetic benchmark and direct leakage
oracle. They do not prove full semantic privacy.

For representative route examples, sanitized delegated payloads, public-safe
audit examples, and metric interpretation, see
[`docs/evaluation-summary.md`](docs/evaluation-summary.md).

## Project Progress Reports

Public-safe Markdown copies of the submitted CS6727 progress reports are
available in [`docs/progress-reports/`](docs/progress-reports/). They show how
the project moved from revised proposal, to architecture, to prototype evidence,
to expanded evaluation planning.

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
