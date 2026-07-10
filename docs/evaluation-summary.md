# Public Evaluation Summary

This document provides public-safe evaluation evidence for Secure Model
Delegation. All requests, credentials, identities, code, and infrastructure
markers are synthetic. External AI is represented only by a simulated local
endpoint.

## Evaluation Sets

| Set | Cases | Purpose |
| --- | ---: | --- |
| Preserved regression set | 63 | Detect behavior changes from the earlier prototype. |
| SMD-Bench development | 1,120 | Coverage-balanced policy and implementation development. |
| SMD-Bench locked holdout | 280 | Template-level holdout evaluation. |
| Pending human-review sample | 210 | Stratified manual validation by Mason; not yet completed. |

SMD-Bench-1400 uses 70 semantic templates, with eight development templates and
two holdout templates per family. Each template produces 20 deterministic
synthetic variants. The distribution is designed for security coverage and does
not estimate real enterprise workload frequency.

## Current Results

| Metric | Regression 63 | SMD-Bench-1400 |
| --- | ---: | ---: |
| Policy conformance | 1.000 | 1.000 |
| Delegated cases | 27 | 525 |
| Macro route F1 | 1.000 | 1.000 |
| Unsafe delegation false negatives | 0 | 0 |
| Over-blocked delegation false positives | 0 | 0 |
| Direct leakage findings | 0 | 0 |
| Canonicalized or encoded leakage findings | 0 | 0 |
| Structural code-detail leakage findings | 0 | 0 |
| Utility-oracle agreement | Not labeled | 0.995714 |
| Preserved utility disagreements | Not applicable | 6 |
| Controller latency p50 | 0.692 ms | 0.749 ms |
| Controller latency p95 | 1.292 ms | 1.477 ms |

The six utility disagreements are preserved rather than relabeled to match the
controller. They all come from one internal service-mesh template where the
runtime heuristic judged local raw context as sufficient while the independent
utility oracle labeled it partial.

## Baseline Separation

The baselines now perform materially different functions.

| SMD-Bench approach | Delegated | Direct leakage findings | Canonicalized findings | Structural code findings |
| --- | ---: | ---: | ---: | ---: |
| `no_gateway` | 1,400 | 1,340 | 1,284 | 720 |
| `regex_secret_pii_filter` | 1,400 | 240 | 240 | 720 |
| `all_detectors_filter_only` | 1,400 | 0 | 0 | 0 |
| `policy_bounded_controller` | 525 | 0 | 0 | 0 |

The all-detectors baseline demonstrates why zero span leakage alone is not the
project claim: it transforms every request and always delegates. Only the
controller applies target policy, conflict resolution, utility checks, and
request-level route arbitration.

## Interpretation

The current evidence supports a bounded claim: within these authored synthetic
templates and explicit oracle policies, the controller conforms to the expected
route labels and no automatic direct, canonicalized, or structural leakage is
observed in delegated payloads.

This is policy-conformance evidence, not independent proof of complete safety.
The runtime policy and benchmark oracle are stored separately, but both derive
from the same documented formal policy family. Template dependence, pending
human review, detector limits, and the lack of automatic semantic-leakage
evaluation remain material limitations.

Detailed public evidence is under [`docs/evidence/pr4/`](evidence/pr4/).

## Current Limitations

- SMD-Bench is synthetic and coverage-balanced rather than prevalence-based.
- The 1,400 cases depend on 70 authored templates.
- The 210-case human review sample remains entirely pending.
- Detector coverage is finite and novel encodings may be missed.
- Semantic leakage has no validated automatic oracle.
- Utility evaluation is heuristic and has six known disagreements.
- Multi-turn support covers adjacent-turn synthetic secret reconstruction only.
- No real provider or production validation has been performed.

## Future Work

- Collect an independent enterprise-like benchmark.
- Complete human annotation and measure inter-rater agreement.
- Evaluate an optional ML advisory router that cannot override policy.
- Develop and validate a semantic leakage evaluator.
- Run optional sanitized-only provider smoke tests.
- Expand language-aware code abstraction.
- Study policy lifecycle and stakeholder validation.
