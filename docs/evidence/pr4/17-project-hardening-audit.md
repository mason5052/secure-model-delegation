# Project Hardening Audit

## Findings And Resolutions

1. Formal model and runtime selection were only partially aligned. The
   controller now calculates policy-allowed routes before utility comparison,
   and utility cannot restore an eliminated route.
2. Policy definitions were duplicated between YAML and Python. Runtime
   severity, span action, allowed routes, target policy, and conflict priority
   now come from validated `configs/policy.yaml`.
3. Span action and request route were conflated in result metadata. They are now
   separate structured fields with candidate routes and eliminated-route
   reasons.
4. Conflict outcomes depended on branch order. Rules now carry explicit IDs and
   priorities, and the winning rule is recorded in the decision trace.
5. Utility was previously self-reported by the controller. SMD-Bench now stores
   a separate utility oracle and preserves six disagreements.
6. Earlier filter baselines were functionally identical. Four baselines now
   provide materially different no-gateway, structured-regex, all-detector, and
   policy-controller behavior.
7. Adversarial cases were inferred from category text. Family, risk class,
   attack family, split, and target profile are now explicit fields.
8. Leakage evaluation covered direct matches only. It now reports direct,
   canonicalized or encoded, and structural code-detail leakage separately.
9. The code route could imply real pseudocode even when only placeholders were
   produced. Results now report `generalized_problem_statement` unless a
   deterministic structural abstraction is actually available.
10. Runtime and benchmark expectations risked circular evaluation. Runtime uses
    `configs/policy.yaml`, while labels use `benchmark/oracle_policy.yaml`.
    Because both derive from the same formal policy family, route accuracy is
    reported as policy conformance rather than independent prediction accuracy.

## Remaining Research Risk

These changes strengthen traceability and evaluation discipline, but they do
not establish perfect detection, semantic privacy, real-workload prevalence, or
production safety. Human review remains pending and is not represented as
completed.
