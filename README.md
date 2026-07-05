# Secure Model Delegation

Policy-bounded controller prototype for local-to-external AI fallback.

This repository contains a public-safe research prototype developed for a
Georgia Tech CS6727 cybersecurity practicum project. It is prepared for
evaluation and later open-source release with synthetic data only.

This is not a general PII detector, DLP product, or privacy masking tool. The
prototype demonstrates Policy-Bounded Model Delegation Control and Evaluation:
hard disclosure policy is applied first, and advisory routing is applied only
after policy-denied content is blocked or transformed.

## Current Scope

- Text-only synthetic enterprise requests.
- Trusted local gateway running in Python.
- External AI is represented as a policy target profile, not a provider-specific
  route.
- Primary external target is a simulated endpoint that records sanitized or
  pseudocode-based delegated payloads for leakage evaluation.
- Real provider API calls are out of scope for this PR3 prototype and remain
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

## Evaluation Snapshot

The current synthetic benchmark contains 32 labeled cases. In the latest local
validation run:

- 14 cases were delegated to the simulated external endpoint.
- Route accuracy was 1.00 against the current labels.
- Direct leakage findings for the policy-bounded controller were 0.
- Baseline comparison found 79 direct leakage findings for no gateway, 2 for
  regex-only sanitization, and 2 for detector-only sanitization.

These results are limited to the current synthetic benchmark and direct leakage
oracle. They do not prove full semantic privacy.

For public-safe evidence details, see `docs/evaluation-summary.md`.

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
