# SMD-Bench-1400 Methodology

SMD-Bench-1400 is a deterministic, synthetic, coverage-balanced benchmark for
target-specific model-delegation policy evaluation. It is not a sample of real
enterprise traffic and does not claim to estimate production frequency.

## Families

The benchmark contains 200 cases in each family:

1. Secrets and credentials
2. PII and support tickets
3. Source code and proprietary logic
4. Internal infrastructure and incident details
5. Prompt injection and restricted-access attempts
6. Benign public requests
7. Mixed-risk requests

Each family uses ten semantic templates and twenty variants per template. Eight
templates are development templates and two are locked holdout templates. No
template appears in both splits.

## Target Balance

Each family contains 67 `local_private`, 67 `approved_external_ai`, and 66
`high_risk_external_ai` cases. Across the benchmark this produces 469, 469, and
462 cases respectively.

## Oracle Separation

The runtime controller loads `configs/policy.yaml`. Benchmark labels are created
from the separate `benchmark/oracle_policy.yaml` artifact. The runtime does not
import the benchmark oracle. Both policies derive from the same documented
formal model, so route accuracy is described as policy conformance rather than
independent prediction accuracy.

## Pilot Gate

Before generating all cases, a 140-case pilot uses two variants from every
template. Automated validation checks schema completeness, unique IDs, normalized
prompt duplicates, family and target balance, valid labels, synthetic-only
content, leakage oracle fields, template diversity, and target-specific route
coverage.

## Human Review

The review sample contains 210 cases: 30 per family, ten per target profile, and
15 each from development and holdout. Every semantic template is represented.
All generated review statuses remain `pending`; automated checks and AI-assisted
pre-review are not counted as human review.

## Leakage And Utility

Automatic leakage evaluation separates direct leakage, canonicalized or encoded
leakage, and structural code-detail leakage. Semantic leakage remains a manual
review limitation. Utility is compared against a separate per-case oracle and
reports preserved disagreements instead of changing labels to match output.
