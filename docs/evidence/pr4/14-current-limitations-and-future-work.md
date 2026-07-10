# Current Limitations

- SMD-Bench-1400 is synthetic and coverage-balanced; it does not estimate real workload frequency.
- The main set remains dependent on 70 authored semantic templates despite structured surface variation.
- The template-evaluation split is not untouched because pilot work exposed its policy family.
- SMD-Challenge-210 is post-freeze, but its human review is still pending.
- The 210-case main review and 70-case second-review samples are pending.
- Evidence detectors have finite coverage and can miss novel encodings or semantic disclosures.
- Semantic leakage is not automatically evaluated.
- Utility labels remain rule-based and weight sensitivity materially changes route conformance.
- Multi-turn support is limited to adjacent-turn synthetic secret reconstruction.
- No real provider, enterprise production, or customer-data validation has been performed.

# Future Work

- Complete post-freeze challenge review and add independently collected enterprise-like cases.
- Complete human annotation and measure inter-rater agreement.
- Evaluate an optional ML advisory router that cannot override policy.
- Add a semantic leakage evaluator with independently validated criteria.
- Run optional sanitized-only provider smoke tests.
- Expand language-aware code abstraction beyond deterministic generalization.
- Study policy lifecycle, versioning, and stakeholder validation.
