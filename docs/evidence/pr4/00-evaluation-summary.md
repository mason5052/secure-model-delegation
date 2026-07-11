# PR4 Public Evaluation Evidence

Evidence first, policy authority always.

## Regression

The preserved 63-case regression set achieved policy conformance 0.889 with 0 direct leakage findings. Independent utility labels do not exist for this legacy set, so utility agreement is reported as not applicable.

## SMD-Bench-1400

The generated dataset contains 1400 cases across 70 semantic templates, with 1120 development cases and 280 template-evaluation cases. End-to-end policy conformance is 0.941, while controller-only conformance is 0.996; direct, canonicalized, and structural leakage findings are 0, 0, and 0. Rule-based utility-label agreement is 0.915000, with 119 preserved disagreements.

The route labels and templates were authored from the same documented formal policy family, although the benchmark oracle is stored separately from runtime policy. Therefore, route conformance is evidence within this authored synthetic policy scope, not independent proof of safety or general robustness.

## SMD-Challenge-210

The post-freeze challenge set achieved end-to-end policy conformance 0.876 and controller-only conformance 0.914. It produced 0 security-relevant target-policy violations and 18 overblocked cases. These failures are preserved.

## SMD-Egress-Challenge-36

The separate egress stress set achieved end-to-end policy conformance 0.667. It exposed 8 target-policy violations and 8 direct leakage findings, all tied to undetected semantic business-sensitive evidence. The result is preserved as a publication-relevant limitation rather than used to tune the frozen controller.

## Human Review

The stratified review sample contains 210 cases. All remain pending; no case is claimed as human approved.
