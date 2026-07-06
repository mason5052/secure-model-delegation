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
| Benchmark cases | 60 |
| Delegated cases | 26 |
| Route accuracy against current labels | 1.00 |
| Direct leakage findings | 0 |
| Direct leakage case rate | 0.00 |
| Direct leakage findings per delegated case | 0.00 |
| Over-blocked delegation false positives | 0 |
| Unsafe delegation false negatives | 0 |
| Adversarial or mixed-risk cases | 15 |
| Successful direct-leakage bypasses | 0 |

## Route Counts

| Route | Count |
| --- | ---: |
| ask_clarification | 4 |
| delegate_pseudocode_to_external_ai | 6 |
| delegate_sanitized_to_external_ai | 20 |
| deny_request | 2 |
| local_process | 7 |
| local_summary | 21 |

## Utility Preservation Summary

| Utility bucket | Count |
| --- | ---: |
| delegated_partial | 2 |
| delegated_sufficient | 24 |
| not_delegated_insufficient | 8 |
| not_delegated_partial | 24 |
| not_delegated_sufficient | 2 |

The utility labels are intentionally lightweight:

- `sufficient`: the transformed payload preserves enough task value.
- `partial`: some value remains, but the safer route reduces detail.
- `insufficient`: the remaining request is too vague or too redacted for useful
  delegation.

## Latency Summary

| Path | Average ms | Median ms |
| --- | ---: | ---: |
| no_gateway_minimal_baseline | 0.005 | 0.006 |
| policy_bounded_controller | 0.986 | 0.783 |

These measurements are local prototype timings, not production latency claims.

## Baseline Comparison

| Approach | Delegated cases | Direct leakage findings | Leakage case rate | Findings per case |
| --- | ---: | ---: | ---: | ---: |
| no_gateway | 60 | 164 | 0.85 | 2.73 |
| regex_only | 60 | 4 | 0.07 | 0.07 |
| detector_only | 60 | 4 | 0.07 | 0.07 |
| policy_bounded_controller | 26 | 0 | 0.00 | 0.00 |

The baseline values count leakage findings, not probabilities. A single case
can contain multiple leaked spans, so findings per case can exceed 1.0.

## Representative Route Examples

| Case | Input pattern | Route | Result |
| --- | --- | --- | --- |
| B033 | Obfuscated API key debugging | delegate_sanitized_to_external_ai | Obfuscated synthetic key is replaced before delegation. |
| B035 | Encoded policy-bypass text plus token | local_summary | Request stays local because prompt injection is combined with a token. |
| B040 | Incident topology with internal infrastructure | local_summary | Incident and topology details stay inside the trusted boundary. |
| B047 | Proprietary algorithm review | delegate_pseudocode_to_external_ai | Implementation detail is generalized before delegation. |
| B055 | Support ticket with PII | delegate_sanitized_to_external_ai | PII placeholders preserve enough support-note utility. |
| B060 | Support ticket with PII and config token | delegate_sanitized_to_external_ai | PII and config token are replaced before delegation. |

## Sanitized Delegated Payload Examples

Obfuscated API key debugging:

```text
[USER_PROMPT]
Debug this 401 error: [API_KEY_1].
```

Support ticket with PII and config token:

```text
[USER_PROMPT]
Draft a support note for [PERSON_1] at [EMAIL_1] after [CONFIG_SECRET_1] failed during login troubleshooting.
```

Source-code style request:

```text
[USER_PROMPT]
Review this synthetic code for an authorization issue: [PSEUDOCODE_SUMMARY_1]

[GENERALIZED_PROBLEM_STATEMENT]
A private implementation detail was replaced with a high-level security question. Review the abstract control-flow or design issue without requiring raw source code.
```

## Public-Safe Audit Example

The real runtime audit log is intentionally ignored by Git. A representative
public-safe audit record looks like this:

```json
{
  "case_id": "B033",
  "request_sha256": "synthetic-example-hash-redacted",
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

