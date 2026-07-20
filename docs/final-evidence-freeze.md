# Final Evidence Freeze

Freeze date: 2026-07-19

This document fixes the evidence and claim boundary used for the CS6727 final
presentation and report. All requests and values are synthetic. No live external
model was called.

## Provenance

- Public main source evaluated before presentation-only changes:
  c6c25fa46a6a30f68a2bdd3a1b917644e849c0fd.
- Frozen decision core:
  d1d13cd3822a00b8c5cbd64d3a5ff90552c0159b.
- The final UI explanation control does not change detector, policy, routing,
  sanitization, egress, or benchmark logic.
- The controller freeze check passed after the UI change.
- The full unit test suite passed: 54 tests.
- The web smoke test passed: API online, nine examples, sanitized delegation,
  no raw synthetic key in the delegated payload, and no direct leakage finding.

## Frozen Evaluation Table

| Metric | SMD-Bench-1400 | SMD-Challenge-210 | SMD-Egress-Challenge-36 |
| --- | ---: | ---: | ---: |
| Cases | 1,400 | 210 | 36 |
| Delegated cases | 453 | 53 | 16 |
| End-to-end policy conformance | 0.941429 | 0.876190 | 0.666667 |
| Controller-only conformance | 0.996429 | 0.914286 | 1.000 on 18 evaluable cases |
| Target-policy violations | 0 | 0 | 8 |
| Overblocked expected delegations | 72 | 18 | 0 |
| Direct leakage findings | 0 | 0 | 8 |
| Canonicalized leakage findings | 0 | 0 | 8 |
| Structural code-detail findings | 0 | 0 | 0 |
| Evidence-class macro F1 | 0.935488 | 0.867244 | 0.857143 |
| Rule-based utility-label agreement | 0.915000 | 0.895238 | 0.888889 |
| Explicit adversarial cases | 380 | 48 | Diagnostic set |

The 0.915 main-set utility value is agreement with authored rule-based utility
labels. It is not a measurement of downstream OpenAI, Claude, or other model
answer quality. The current study has not established that transformed prompts
preserve 91.5 percent of external-model usefulness.

## Baseline Result That Supports the Main Distinction

On SMD-Bench-1400, the all-detectors filter-only baseline produced zero
automatic span-leakage findings, but its target-policy violation rate was
0.648571 and its route conformance was 0.342143. The policy-bounded controller
produced zero target-policy violations on the same set and route conformance of
0.941429.

This result supports a bounded distinction: content filtering alone can remove
detected spans without choosing a target-appropriate route. It does not prove
production safety or complete semantic privacy.

## Preserved Eight-Failure Analysis

All eight egress-challenge failures had the same causal chain:

1. The authored label was business_sensitive.
2. The runtime evidence layer detected no protected class.
3. The controller therefore received no business-sensitive evidence to enforce.
4. The request was delegated through a sanitized route without transformation.
5. The exact authored business fact remained in the delegated payload.

The failures fall into two semantic types:

| Type | Cases | Synthetic business fact | Targets |
| --- | --- | --- | --- |
| Acquisition negotiation ceiling | SMDE-F7-T03-V002, V003, V005, V006 | Confidential maximum acquisition value | Approved and high-risk external |
| Confidential pricing forecast | SMDE-F7-T04-V002, V003, V005, V006 | Confidential future price-increase percentage | Approved and high-risk external |

The failure is end-to-end and security relevant. Controller-only conformance
does not erase it. It demonstrates the boundary of the formal invariant:
hard-policy arbitration can constrain only the evidence supplied to it.

## Utility Sensitivity

Changing utility weights changed main-set route conformance from 0.744286 to
0.990714 and challenge-set conformance from 0.733333 to 0.933333. Every compared
route was already inside the hard-policy allowed set.

This supports the ordering of hard policy before utility selection. It does not
validate the chosen utility weights or downstream response quality.

## Final Claim-Evidence Matrix

| Claim | Evidence | Status | Boundary |
| --- | --- | --- | --- |
| Utility scoring cannot choose a route removed by hard policy | Allowed-set construction, controller-only results, and weight sensitivity | Supported by design and current tests | Assumes required evidence reaches the controller |
| Target-aware arbitration adds security behavior beyond filtering | Filter-only baseline has 0.648571 target-policy violation rate despite zero authored span leakage | Supported on SMD-Bench-1400 | Synthetic, coverage-balanced benchmark |
| Main and post-freeze challenge sets had no direct egress finding | Zero direct, canonicalized, and structural findings on 1,400 and 210 cases | Supported for those sets | Does not generalize to all semantic content |
| The complete system prevents all semantic leakage | Eight exact disclosures on the 36-case stress set | Not supported | Semantic evidence remains incomplete |
| Sanitization preserves downstream model answer quality | No live-provider task-quality experiment was run | Not yet evaluated | Rule-based utility-label agreement is only a proxy |
| Provider contracts make raw disclosure safe | Provider assurances reduce residual handling risk but do not authorize prohibited content | Not claimed | Retention and training controls belong in target policy |
| The results establish production prevalence | Benchmark is synthetic and coverage-balanced | Not supported | Independent enterprise-like data and human review remain publication gates |

## Presentation-Safe Result Statement

The current evidence supports a bounded result. When the required evidence is
available, the controller keeps utility scoring inside the hard-policy allowed
route set. On the 1,400-case main benchmark and the 210-case post-freeze
challenge, the system produced no target-policy violation or direct leakage
finding. A separate 36-case semantic stress test exposed eight exact
disclosures because the evidence layer missed two forms of confidential
business context. Those failures are preserved and define the next research
task.

## Files Used for Reproduction

- data/smd_bench_1400.jsonl
- data/smd_challenge_210.jsonl
- data/smd_egress_challenge_36.jsonl
- scripts/run_eval.py
- scripts/run_utility_sensitivity.py
- scripts/check_controller_freeze.py
- docs/evaluation-summary.md
- docs/evidence/pr4/16-preserved-failure-analysis.md
