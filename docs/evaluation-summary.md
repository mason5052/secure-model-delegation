# Public Evaluation Summary

This document provides public-safe evaluation evidence for the Secure Model
Delegation prototype. It summarizes the current synthetic benchmark results
without publishing raw runtime logs, local absolute paths, real credentials, or
company data.

## Scope

- All benchmark cases are synthetic.
- The external target is a simulated endpoint.
- No real OpenAI, Claude, customer, production, or company data is used.
- The evaluation checks direct leakage of labeled sensitive spans. It does not
  prove full semantic privacy.

## Current Metrics

| Metric | Value |
| --- | ---: |
| Benchmark cases | 32 |
| Delegated cases | 14 |
| Route accuracy against current labels | 1.00 |
| Direct leakage findings | 0 |
| Direct leakage findings per delegated case | 0.00 |

## Route Counts

| Route | Count |
| --- | ---: |
| ask_clarification | 2 |
| delegate_pseudocode_to_external_ai | 4 |
| delegate_sanitized_to_external_ai | 10 |
| deny_request | 1 |
| local_process | 3 |
| local_summary | 12 |

## Utility Labels

| Utility label | Count |
| --- | ---: |
| insufficient | 4 |
| partial | 14 |
| sufficient | 14 |

## Baseline Comparison

| Approach | Delegated cases | Direct leakage findings |
| --- | ---: | ---: |
| no_gateway | 32 | 79 |
| regex_only | 32 | 2 |
| detector_only | 32 | 2 |
| policy_bounded_controller | 14 | 0 |

The baseline values count leakage findings, not probabilities. A single case
can contain multiple leaked spans, so findings per case can exceed 1.0 in raw
evaluation output.

## Representative Route Examples

| Case | Input pattern | Route | Result |
| --- | --- | --- | --- |
| B001 | API key debugging request | delegate_sanitized_to_external_ai | Raw synthetic API key is replaced before delegation. |
| B002 | API key plus source code | local_summary | Request stays local because high-risk evidence is combined. |
| B011 | Proprietary code review | delegate_pseudocode_to_external_ai | Raw implementation details are replaced with a generalized problem statement. |
| B018 | System prompt extraction attempt | deny_request | Request is denied because it asks for protected system instructions. |
| B031 | PII without clear task intent | ask_clarification | Gateway asks for clarification instead of delegating unnecessary PII. |

## Sanitized Delegated Payload Examples

API key debugging:

```text
[USER_PROMPT]
Debug this 401 API error: [API_KEY_1] returns unauthorized.
```

Internal host troubleshooting:

```text
[USER_PROMPT]
Troubleshoot connection timeout from [INTERNAL_HOST_1] to [PRIVATE_IP_1] during a generic outage.
```

Source-code style request:

```text
[USER_PROMPT]
Review this [PROPRIETARY_CODE_LOCAL_ONLY_1] design in the [PROPRIETARY_CODE_LOCAL_ONLY_2] for an authorization bug.

[GENERALIZED_PROBLEM_STATEMENT]
A private implementation detail was replaced with a high-level security question. Review the abstract control-flow or design issue without requiring raw source code.
```

## Public-Safe Audit Example

The real runtime audit log is intentionally ignored by Git. A representative
public-safe audit record looks like this:

```json
{
  "case_id": "B001",
  "request_sha256": "66426fdc95407278a542a676b139679d8e8b9d461210819905aa652f86302671",
  "detected_labels": ["api_key"],
  "span_count": 1,
  "route": "delegate_sanitized_to_external_ai",
  "transport": "simulated_external_endpoint",
  "hard_action": "transform",
  "utility_label": "sufficient",
  "target_profile": "external_ai",
  "rule_ids": ["hard_policy_first", "transformed_payload_safety_plus_remaining_utility"],
  "raw_input_stored": false
}
```

## Interpretation

The current evidence supports a narrow claim: in this synthetic benchmark, when
delegation is mediated by the policy-bounded controller, policy-denied raw spans
do not appear in delegated payloads under the direct leakage oracle.

The evidence does not claim that the prototype detects every possible sensitive
span, prevents semantic leakage, or replaces enterprise DLP systems.
