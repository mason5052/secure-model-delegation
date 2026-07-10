# Test And Quality-Gate Summary

The final local validation used only synthetic data and the simulated external
endpoint. It did not call a real external AI provider.

## Automated Tests

- Python unit and integration tests: 38 passed
- Existing 63-case route regression: 63 of 63 policy-conformant
- Regression direct leakage findings: 0
- Regression canonicalized or encoded leakage findings: 0
- Regression structural code-detail leakage findings: 0
- Web UI smoke test: passed
- Raw synthetic key in delegated smoke-test payload: false

## Benchmark Gates

- Pilot cases: 140
- Full cases: 1,400
- Unique case IDs: 1,400
- Normalized duplicate prompts: 0
- Semantic templates: 70
- Development cases: 1,120
- Holdout cases: 280
- Template split isolation: passed
- Target distribution: 469 local, 469 approved external, 462 high-risk external
- Human-review sample: 210, all pending
- Repeated generated-dataset checksum: deterministic
- Repeated evaluation, excluding runtime latency: deterministic

The repository also includes a provider-free GitHub Actions workflow that runs
the tests, regenerates the benchmark, checks checked-in artifact
reproducibility, evaluates the pilot, and smoke-tests the local Web UI. The
workflow never calls a real external AI provider.
