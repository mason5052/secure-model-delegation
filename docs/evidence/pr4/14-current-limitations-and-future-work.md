# Current Limitations

- SMD-Bench-1400 is synthetic and coverage-balanced; it does not estimate real workload frequency.
- Cases remain dependent on 70 authored semantic templates.
- The 210-case human review sample is pending and no human agreement claim is made.
- Evidence detectors have finite coverage and can miss novel encodings or semantic disclosures.
- Semantic leakage is not automatically evaluated.
- Utility labels are heuristic; six generated cases currently disagree with the independent utility oracle.
- Multi-turn support is limited to adjacent-turn synthetic secret reconstruction.
- No real provider, enterprise production, or customer-data validation has been performed.

# Future Work

- Evaluate an independently collected enterprise-like benchmark.
- Complete human annotation and measure inter-rater agreement.
- Evaluate an optional ML advisory router that cannot override policy.
- Add a semantic leakage evaluator with independently validated criteria.
- Run optional sanitized-only provider smoke tests.
- Expand language-aware code abstraction beyond deterministic generalization.
- Study policy lifecycle, versioning, and stakeholder validation.
