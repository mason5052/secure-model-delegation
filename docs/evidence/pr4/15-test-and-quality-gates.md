# Test And Quality Gates

- Forty-seven unit and integration tests pass locally.
- The SMD-Bench generator is deterministic and uses canonical JSON checksums.
- The 112-case pilot contains development templates only.
- SMD-Bench-1400 contains 1,400 unique cases, 70 templates, and 20 surface variations per template.
- SMD-Challenge-210 contains 35 new post-freeze templates and records controller commit `d1d13cd3822a00b8c5cbd64d3a5ff90552c0159b`.
- Controller-only and end-to-end evaluation results are reported separately.
- Baselines report route conformance, target-policy violations, overblocking, and leakage.
- Human-review artifacts remain pending and are not represented as completed validation.
- CI regenerates checked-in benchmark artifacts, verifies the controller freeze,
  evaluates the development pilot, full main set, and challenge set, runs utility
  sensitivity, and smoke-tests the Web UI.

The local Python environment emits a Starlette warning about future `httpx2` migration. It does not affect current test results, but dependency compatibility should be revisited before a long-term release.
