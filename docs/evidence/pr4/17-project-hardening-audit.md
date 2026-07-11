# Project Hardening Audit

## Corrected Research Claims

- The controller now scores every route in the hard-policy allowed set instead of scoring external routes only.
- Target-specific source-code policy is executable and constrains the allowed route set.
- The `template_evaluation` split is explicitly not described as untouched because pilot work exposed its policy family.
- Route accuracy is reported as policy conformance, not independent proof of safety.
- Utility results are described as agreement with authored rule-based labels, not independent utility ground truth.
- Detector and controller performance are evaluated separately.
- Benchmark leakage oracles are post-hoc evaluators and cannot influence runtime egress decisions.
- Stable placeholders preserve repeated-value relationships while reversible mappings remain local.
- A fail-closed post-transform guard records exact wire metadata and escalates blocked delegations to local summary.

## Added Comparative Evidence

- `always_local` shows the safety and utility cost of never delegating.
- `all_detectors_filter_only` shows that zero span leakage does not establish target-policy compliance.
- `target_agnostic_controller` isolates the value of target-specific policy.
- `hard_policy_without_utility` isolates the effect of route-specific utility selection.
- `osaurus_style_filter_only` is a documented behavioral analogue of a privacy-filter pipeline, not a claim that Osaurus code was executed.
- SMD-Challenge-210 records a post-freeze evaluation against 35 unseen semantic templates.
- SMD-Egress-Challenge-36 preserves semantic business-sensitivity failures instead of tuning the frozen controller.

## Remaining Publication Gates

- Mason must review the 210-case main sample.
- A second reviewer must independently assess the 70-case overlap.
- Challenge labels require human review before publication.
- Semantic leakage still requires a validated human or automated rubric.
- Independent enterprise-like cases are still needed before making external-validity claims.
