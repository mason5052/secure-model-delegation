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
templates are development templates and two are template-evaluation templates.
The second split is not presented as an untouched evaluation set because early
pilot work exposed the same policy family. Each variant changes controlled
surface wording, framing,
and response constraints in addition to synthetic values.

## Case Taxonomy

The benchmark separates workload sensitivity from adversarial intent. A request
containing a credential, PII, source code, or incident context is not automatically
an attack. Each generated case therefore has a `case_type` and an explicit
`is_adversarial` flag:

- `routine_sensitive`: ordinary work containing protected context.
- `benign_public`: ordinary public requests with no protected context.
- `benign_stress`: ambiguous or hard-negative requests used to test overblocking.
- `adversarial_evasion`: deliberately encoded, separated, or multi-turn disclosures.
- `prompt_injection`: instructions that try to bypass policy or extract protected prompts.

SMD-Bench-1400 contains 380 adversarial cases under this definition; the
post-freeze challenge contains 48. Attack-success metrics use this explicit flag
rather than treating every non-benign scenario subtype as an attack.

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

The fail-closed egress guard also uses only runtime-detected evidence. Authored
leakage oracles are applied after processing to score the captured payload; they
cannot determine whether the endpoint is called. This prevents benchmark ground
truth from leaking into the execution path.

## Pilot Gate

Before generating all cases, a 112-case pilot uses two variants from each of the
56 development templates. Template-evaluation cases are excluded. Automated
validation checks schema completeness, unique IDs, normalized
prompt duplicates, family and target balance, valid labels, synthetic-only
content, ground-truth evidence fields, surface-form diversity, leakage oracle
fields, and target-specific route coverage.

## Human Review

The main review sample contains 210 cases: 30 per family, ten per target profile,
and 15 each from development and template evaluation. Every semantic template is
represented. A 70-case overlap is prepared for an independent second reviewer.
Route agreement will use Cohen's kappa and ordinal utility agreement will use
weighted Cohen's kappa. All statuses remain `pending`; automated checks are not
counted as human review.

## Post-Freeze Challenge

SMD-Challenge-210 contains 35 new semantic templates and six variants per
template. It is balanced at 30 cases per family and 70 cases per target profile.
The controller was frozen at commit
`d1d13cd3822a00b8c5cbd64d3a5ff90552c0159b` before the challenge was generated.
The protected scope includes decision arbitration, utility ranking, evidence
detection, normalization, controller-time sanitization, leakage scoring,
runtime policy, and benchmark label policy. Later audit, simulated transport,
and fail-closed egress wrappers may only add evidence or escalate to a safer
local route; they cannot authorize a route rejected by the frozen core.
Challenge failures are preserved for analysis, and human review is pending.

## Egress Challenge

SMD-Egress-Challenge-36 is a separate deterministic diagnostic set with six
templates, six variants per template, and 12 cases per target profile. It
stresses fenced-code secrets, repeated PII placeholders, structured tokens, and
semantic business-sensitive requests. It does not change SMD-Bench-1400 or
SMD-Challenge-210, and it is not used to tune the frozen controller.

The set deliberately includes an authored `business_sensitive` class that the
current detector does not support. These cases measure the assumption boundary
of `A(E, P_t)`: safe route arbitration depends on evidence `E` being available.
The resulting failures are preserved as a detector limitation and a target for
future advisory semantic evidence research.

## Reproducibility

The generator uses a fixed seed and emits a manifest with a dataset checksum.
The checksum is computed from canonical, key-sorted JSON records rather than
platform-specific file bytes, so Windows and Linux line endings produce the
same result.

## Leakage And Utility

Automatic leakage evaluation separates direct leakage, canonicalized or encoded
leakage, and structural code-detail leakage. Semantic leakage remains a manual
review limitation. Evidence-class precision, recall, and F1 are reported
separately from controller-only policy conformance. Utility labels are
rule-based rather than human validated, and disagreements are preserved.

## Evaluation Modes

- Controller-only evaluation injects benchmark ground-truth evidence into the
  controller to isolate route selection.
- End-to-end evaluation uses the implemented evidence providers and therefore
  includes detector false positives and false negatives.
- Utility-weight sensitivity re-scores only routes already admitted by hard
  policy, so weight changes cannot authorize a forbidden route.

## Related Filter Baseline

`osaurus_style_filter_only` is a behavioral analogue of an enabled privacy
filter: detect sensitive spans, replace them with stable placeholders, run a
post-transform fail-closed check over detected originals, record wire metadata,
and delegate. It does not execute or reproduce Osaurus code. The baseline is
included to compare content filtering with target-aware route arbitration; a
direct Osaurus local-API experiment remains future work.
