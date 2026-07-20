# Public Evaluation Summary

All requests, identities, credentials, code, and infrastructure markers in this
evaluation are synthetic. External AI is represented by a simulated endpoint.

## Evaluation Sets

| Set | Cases | Purpose |
| --- | ---: | --- |
| Preserved regression set | 63 | Detect behavior changes from the earlier prototype. |
| SMD-Bench development | 1,120 | Coverage-balanced implementation development. |
| SMD-Bench template evaluation | 280 | Evaluate templates separated from implementation development; not an untouched evaluation set. |
| SMD-Challenge-210 | 210 | Post-freeze evaluation using 35 new semantic templates. |
| SMD-Egress-Challenge-36 | 36 | Targeted post-freeze stress set for fenced-code secrets, stable placeholders, structured tokens, and semantic business sensitivity. |
| Main human-review sample | 210 | Stratified Mason review; pending. |
| Second-review overlap | 70 | Independent agreement measurement; pending. |

SMD-Bench-1400 is coverage-balanced and does not estimate production workload
frequency. Its 1,400 cases come from 70 semantic templates with controlled
surface, wording, context, and value variation.

The main set includes 380 explicit adversarial-evasion or prompt-injection cases;
SMD-Challenge-210 includes 48. Routine sensitive requests are evaluated for
policy and leakage behavior but are not counted as attacks.

## Current Results

| Metric | Regression 63 | SMD-Bench-1400 | SMD-Challenge-210 | Egress Challenge 36 |
| --- | ---: | ---: | ---: | ---: |
| End-to-end policy conformance | 0.889 | 0.941 | 0.876 | 0.667 |
| Controller-only policy conformance | Not labeled | 0.996 | 0.914 | 1.000 on 18 evaluable cases |
| Security-relevant target-policy violations | 0 | 0 | 0 | 8 |
| Overblocked expected delegations | 3 | 72 | 18 | 0 |
| Direct leakage findings | 0 | 0 | 0 | 8 |
| Canonicalized or encoded leakage findings | 0 | 0 | 0 | 8 |
| Structural code-detail leakage findings | 0 | 0 | 0 | 0 |
| Evidence-class macro F1 | Not labeled | 0.935 | 0.867 | 0.857 |
| Rule-based utility-label agreement | Not labeled | 0.915 | 0.895 | 0.889 |

Controller-only evaluation injects ground-truth evidence. End-to-end evaluation
uses the implemented evidence providers. The difference between the two exposes
detector effects instead of attributing every failure to the controller.

Rule-based utility-label agreement is not downstream model answer quality. No
live-provider task-quality experiment was run, so the current evaluation does
not claim that sanitization preserves a measured percentage of OpenAI, Claude,
or other provider usefulness.

## Baseline Separation

| SMD-Bench approach | Route conformance | Target-policy violation rate | Overblocked rate | Direct leakage cases |
| --- | ---: | ---: | ---: | ---: |
| `no_gateway` | 0.342 | 0.649 | 0.000 | 880 |
| `always_local` | 0.379 | 0.000 | 0.375 | 0 |
| `regex_secret_pii_filter` | 0.342 | 0.649 | 0.000 | 240 |
| `all_detectors_filter_only` | 0.342 | 0.649 | 0.000 | 0 |
| `osaurus_style_filter_only` | 0.342 | 0.649 | 0.000 | 0 |
| `target_agnostic_controller` | 0.635 | 0.215 | 0.051 | 0 |
| `hard_policy_without_utility` | 0.984 | 0.000 | 0.000 | 0 |
| `policy_bounded_controller` | 0.941 | 0.000 | 0.051 | 0 |

The all-detectors baseline reaches zero automatic span leakage on the authored
main set but selects a less-protective external route in 64.9 percent of cases.
This is the central empirical distinction between filtering and model-delegation
control. The always-local baseline is safe but overblocks expected external
assistance.

The Osaurus-style row is a behavioral analogue of an enabled privacy-filter
pipeline. It applies stable placeholders, a post-transform fail-closed check,
and wire metadata before delegation. It does not execute or reproduce Osaurus
code. Its result reinforces that strong content filtering alone does not choose
a target-appropriate route.

On SMD-Egress-Challenge-36, both the analogue and the current controller expose
a separate semantic limitation. The authored `business_sensitive` evidence is
not detected, producing eight controller target-policy violations and eight
direct findings. These failures are preserved and are not used to tune the
frozen controller.

A target-policy violation is counted only when a security-relevant request is
sent through an external route with less disclosure protection than the authored
expected route. A safer but less useful route is instead counted through route
conformance or overblocking; it is not mislabeled as a security violation.

## Utility Sensitivity

Changing utility weights changed SMD-Bench route conformance from 0.744 to 0.991
and challenge conformance from 0.733 to 0.933. Every compared route was already
inside the hard-policy allowed set. The result supports the bounded safety claim
while showing that operational route choice depends on explicit utility
assumptions that require human validation.

## Interpretation

The main and 210-case challenge results support a bounded claim: when required
evidence is available, hard policy prevents utility scoring from selecting a
forbidden route. SMD-Egress-Challenge-36 shows the other side of that boundary:
the invariant cannot protect a class that the evidence layer fails to identify.

It does not establish perfect detector coverage, semantic privacy, production
prevalence, or provider behavior. Human review, inter-rater agreement, semantic
leakage assessment, and independent enterprise-like cases remain publication
gates. Detailed artifacts are available under
[`docs/evidence/pr4/`](evidence/pr4/).

The final frozen metrics and claim boundaries are recorded in the
[final evidence freeze](final-evidence-freeze.md). Provider contract,
retention, and data-control attributes are modeled in the
[target-profile assurance model](target-profile-assurance.md).
