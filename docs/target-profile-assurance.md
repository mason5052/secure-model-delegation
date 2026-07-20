# Target-Profile Assurance Model

## Motivation

Enterprise agreements with external AI providers can reduce residual handling
risk. Examples include no-training defaults, configurable retention, zero-data-
retention arrangements, data residency, encryption, and access controls. These
assurances matter, but they do not answer the model-delegation question by
themselves.

A provider promise not to train on a prompt does not make every internal secret,
private code block, incident detail, or confidential business fact appropriate
to disclose. The controller therefore treats provider assurance as part of the
target profile P_t, not as a replacement for content policy.

## Proposed Target Attributes

A future provider-specific target profile should record at least:

| Attribute | Example values | Security purpose |
| --- | --- | --- |
| organization_approved | true, false | Confirms organizational authorization for the service |
| training_use | disabled_by_default, opt_in, unknown | Records whether inputs or outputs may be used for model improvement |
| retention_mode | standard, modified_monitoring, zero_retention, unknown | Captures the agreed data-handling mode |
| retention_window_days | integer or unknown | Makes residual retention explicit |
| application_state | none, endpoint_specific, persistent, unknown | Separates request logs from feature-level stored state |
| abuse_monitoring | standard, modified, exempted, unknown | Records whether prompts may be retained for misuse review |
| data_residency | region list or unspecified | Supports jurisdiction and residency policy |
| processing_region | region list or unspecified | Separates processing location from storage location |
| encryption_controls | provider_managed, customer_managed, unknown | Records at-rest key control |
| contractual_controls | DPA, BAA, enterprise_terms, custom, none | Captures approved legal and compliance controls |
| allowed_data_classes | explicit class list | Limits what the target may receive |
| prohibited_data_classes | explicit class list | Blocks classes regardless of utility |
| profile_evidence_date | ISO date | Prevents stale assurance from being treated as current |
| profile_owner | security, privacy, legal, platform | Identifies who approved and maintains the profile |

## Decision Rule

Target assurance is monotonic and fail-closed:

1. Hard content policy first constructs the allowed route set.
2. Target assurance may remove an external route or require a safer
   transformation.
3. Target assurance cannot restore a route already removed by hard content
   policy.
4. Missing, expired, or unknown assurance must not silently increase
   disclosure.
5. Utility scoring runs only after both content policy and target assurance have
   admitted a route.

Conceptually:

    A_content = routes allowed by detected evidence and disclosure policy
    A_target  = routes allowed by provider assurance
    A_final   = A_content intersect A_target
    R         = highest-utility route in A_final

This preserves the core invariant while making enterprise provider selection
more realistic.

## Current Prototype Status

The evaluated prototype uses three abstract profiles:

- local_private
- approved_external_ai
- high_risk_external_ai

It does not claim to have evaluated OpenAI, Anthropic, Google, their contracts,
or provider-side behavior. The simulated external endpoint remains the measured
egress boundary. Provider-specific profile implementation and sanitized-only
response-quality experiments are future work.

## Official Provider Documentation Reviewed

- OpenAI business data privacy:
  https://openai.com/business-data/
- OpenAI API data controls:
  https://platform.openai.com/docs/models/default-usage-policies-by-endpoint
- Anthropic commercial data retention:
  https://privacy.anthropic.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data
- Anthropic zero-data-retention scope:
  https://privacy.anthropic.com/en/articles/8956058-i-have-a-zero-data-retention-agreement-with-anthropic-what-products-does-it-apply-to
- Google Vertex AI zero data retention:
  https://docs.cloud.google.com/vertex-ai/generative-ai/docs/vertex-ai-zero-data-retention

These pages show why target assurance must be modeled with endpoint- and
configuration-specific attributes rather than a single claim such as "the
provider does not train on enterprise data."
