> Public-safe copy of the submitted CS6727 progress report. Course-private attachments and raw runtime artifacts are not included. Company-specific names, if any, are generalized.
# CS6727 Progress Report 4

Student: Junkuk Kim

Section: CS

Project Title: Secure Model Delegation: A Policy-Bounded Controller for Local-to-Cloud LLM Fallback

Date: July 6, 2026

AI Assistance Disclosure: AI was used as a supporting aid for brainstorming, language polishing, code review, and organizing evidence. I made the final design decisions, reviewed and revised the content, verified results, and remain responsible for the work.

## Problem Statement

My project studies a specific security boundary in enterprise AI systems: the moment when a local or private AI assistant decides whether a user request should remain inside the trusted environment or be delegated to an external model. This fallback path is useful because external models can be more capable, but it can also expose sensitive information if the request contains credentials, personal data, internal infrastructure details, source code, incident context, or prompt-injection text.

The problem I am working on is not simply "detect PII" or "mask secrets." Those are supporting tasks. The core problem is deciding what should happen to a request before it crosses the local-to-cloud boundary. A secure delegation system needs to decide whether the request should be processed locally, denied, clarified, summarized locally, sanitized and delegated, or converted to pseudocode/generalized form before delegation.

## Solution Statement

Since PR3, I moved from initial prototype evidence into deeper evaluation. I expanded the synthetic benchmark, added adversarial and mixed-risk cases, measured routing and leakage behavior against baselines, and began analyzing utility, latency, false positives, false negatives, and remaining limitations.

The current prototype implements a policy-bounded model delegation controller. Evidence providers identify sensitive spans and risk signals, but they are not the main contribution. The controller applies hard disclosure policy first, then uses routing and utility information second. This means advisory evidence can help the route decision, but it cannot override policy constraints such as keeping raw secrets, source code with tokens, system prompts, or incident topology inside the trusted boundary.

For PR4, I kept the external target as a simulated endpoint. This is safer and more reproducible than using live OpenAI or Claude APIs during evaluation. It lets me inspect exactly what would have crossed the boundary without sending any sensitive-looking benchmark text to a real external service. OpenAI and Claude remain target profiles for future provider-specific policy testing, but the PR4 evidence focuses on the simulated endpoint.

## Completed Tasks

- Expanded the synthetic benchmark from 32 cases to 60 cases.
- Added cases for obfuscated secrets, encoded policy-bypass text, prompt injection with sensitive data, source code with tokens, source code with incident details, PII with unclear intent, internal topology with incident details, benign false-positive controls, mixed sensitive classes, and over-sanitization cases.
- Improved the evidence provider layer to detect additional config-secret formats and simple one-line function blocks that previously left too much source-code detail in pseudocode mode.
- Updated the evaluation script to report route accuracy, direct leakage findings, leakage case rate, false positives, false negatives, route mismatches, utility preservation, lightweight latency, adversarial bypass resistance, and baseline comparison.
- Preserved the baseline comparison against no gateway, regex-only sanitizer, detector-only sanitizer, and the policy-bounded controller.
- Created public-safe PR4 evidence summaries instead of using raw runtime logs with local paths.
- Created a utility scoring rubric with sufficient, partial, and insufficient labels.
- Created a final report outline and mapped current evidence to the sections I need for the final report.

## Tasks For The Next Project Report And Final Report

- Expand the evaluation discussion from metrics into interpretation: why the controller reduced direct leakage, where it may over-block, and where utility may be lost.
- Add a concise final threat model section with assets, trust boundaries, adversaries, security goals, and non-goals.
- Convert related-work notes into a short synthesis rather than a long source list.
- Add provider-specific policy differences for OpenAI and Claude as future or optional evaluation work.
- Review the synthetic benchmark labels and decide whether any expected routes should be adjusted before the final report.
- Add more discussion of semantic leakage, because direct span non-disclosure does not prove that all sensitive meaning has been removed.
- Prepare final presentation slides with evaluation results, not only architecture.

## Questions Or Issues

- Is the current simulated endpoint evaluation sufficient for the final report if I clearly explain that live OpenAI and Claude API calls are optional future smoke tests?
- Are the current route labels too many for the final report, or should I combine some labels for readability while keeping the detailed labels in the appendix?
- For utility preservation, is my simple sufficient, partial, and insufficient rubric adequate, or should I add a small human-review step before the final report?
- The benchmark is synthetic by design. I need to be careful not to overclaim representativeness, so the final report should state what the benchmark covers and what it does not cover.

## Methodology

My methodology is now organized around evaluation rather than only design. First, I define the local-to-cloud trust boundary and the sensitive classes that matter for delegated requests. Second, I use evidence providers to identify spans and risk signals in a normalized request. Third, the policy-bounded controller resolves the request-level route using hard policy first and utility/routing advice second. Fourth, if delegation is allowed, the sanitizer or pseudocode path creates a safer payload for the simulated external endpoint. Finally, the evaluator checks route correctness, direct leakage, utility labels, latency, and baseline performance.

The key evaluation choice is to inspect what reaches the external boundary. I am not only looking at whether a final answer appears safe. I am measuring whether the delegated payload itself contains policy-denied material.

## Timeline

| Week | Dates | Planned Work | Status |
| --- | --- | --- | --- |
| Week 1 | May 18 to May 24 | Initial proposal and project framing | Complete |
| Week 2 | May 25 to May 31 | Revised proposal, deployment plan, policy model, benchmark plan | Complete |
| Week 3 | June 1 to June 7 | First video update and prototype planning | Complete |
| Week 4 | June 8 to June 14 | Architecture refinement, related work comparison, PR2 | Complete |
| Week 5 | June 15 to June 21 | Prototype skeleton, web UI, policy YAML, simulated endpoint | Complete |
| Week 6 | June 22 to June 28 | PR3 evidence, initial 32-case evaluation, appendix evidence | Complete |
| Week 7 | June 29 to July 5 | Benchmark expansion, adversarial cases, evaluation improvements | Complete |
| Week 8 | July 6 to July 12 | PR4 submission, final evaluation planning, final report outline | In progress |
| Week 9 | July 13 to July 19 | Final presentation preparation and final evaluation interpretation | Planned |
| Week 10 | July 20 to July 26 | Final presentation, peer review, final report drafting | Planned |
| Week 11 | July 27 to August 2 | Final report polish and submission | Planned |

## Evaluation

The expanded PR4 benchmark contains 60 synthetic cases. The current evaluation run produced the following summary:

| Metric | Value |
| --- | ---: |
| Benchmark cases | 60 |
| Delegated cases | 26 |
| Route accuracy | 1.00 |
| Direct leakage findings | 0 |
| Direct leakage case rate | 0.00 |
| Direct leakage findings per delegated case | 0.00 |
| Over-blocked delegation false positives | 0 |
| Unsafe delegation false negatives | 0 |
| Route mismatches | 0 |
| Adversarial cases | 15 |
| Successful adversarial bypasses | 0 |
| Adversarial resistance rate | 1.00 |

Route distribution in this run:

| Route | Count |
| --- | ---: |
| ask_clarification | 4 |
| delegate_pseudocode_to_external_ai | 6 |
| delegate_sanitized_to_external_ai | 20 |
| deny_request | 2 |
| local_process | 7 |
| local_summary | 21 |

Baseline comparison:

| Path | Delegated cases | Direct leakage findings | Leakage case rate | Findings per case |
| --- | ---: | ---: | ---: | ---: |
| no_gateway | 60 | 164 | 0.85 | 2.73 |
| regex_only | 60 | 4 | 0.07 | 0.07 |
| detector_only | 60 | 4 | 0.07 | 0.07 |
| policy_bounded_controller | 26 | 0 | 0.00 | 0.00 |

The baseline comparison is intentionally limited. Regex-only and detector-only baselines can remove many sensitive spans, but they still delegate every case. The policy-bounded controller changes the decision problem: it can keep high-risk requests local, deny some requests, ask for clarification, or delegate only sanitized/pseudocode payloads. This is why the project should be evaluated on route correctness and egress leakage, not only detector accuracy.

The current latency measurement is lightweight and local:

| Path | Average ms | Median ms |
| --- | ---: | ---: |
| no-gateway minimal baseline | 0.005 | 0.005 |
| policy-bounded controller | 0.608 | 0.479 |

The measured overhead was about 0.603 ms in this local synthetic run. This is not a production latency benchmark, but it shows that the prototype can collect basic implementation-level latency evidence.

Limitations remain. The benchmark is synthetic, the labels are my own expected routes, and the leakage oracle measures direct span leakage rather than full semantic leakage. For the final report, I need to explain these limits clearly and avoid claiming complete privacy.

## Report Outline

1. Introduction and problem motivation
2. Background and related work
3. Threat model and trust boundary
4. Policy model and route labels
5. Prototype architecture
6. Benchmark design and representativeness
7. Evaluation methodology
8. Results and baseline comparison
9. Deployment challenges and cost-benefit tradeoffs
10. Limitations and future work
11. Conclusion

## References

- OpenAI Privacy Filter. https://github.com/openai/privacy-filter
- Microsoft Presidio. https://github.com/microsoft/presidio
- TruffleHog. https://github.com/trufflesecurity/trufflehog
- Zhan et al., Portcullis: A Scalable and Verifiable Privacy Gateway for Third-Party LLM Inference. https://ojs.aaai.org/index.php/AAAI/article/view/32088
- Zhan et al., PRISM: Privacy-Aware Routing for Adaptive Cloud-Edge LLM Inference via Semantic Sketch Collaboration. https://arxiv.org/abs/2511.22788
- Wu et al., Privacy-Preserving LLMs Routing. https://arxiv.org/abs/2604.15728
- Debenedetti et al., AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents. https://arxiv.org/abs/2406.13352
- Lan et al., Silent Egress: When Implicit Prompt Injection Makes LLM Agents Leak Without a Trace. https://arxiv.org/abs/2602.22450
- Alizadeh et al., Simple Prompt Injection Attacks Can Leak Personal Data Observed by LLM Agents During Task Execution. https://arxiv.org/abs/2506.01055

## Appendix Evidence

PR4 evidence is organized in `submissions/pr4-evidence/`.

| File | Purpose |
| --- | --- |
| 01-benchmark-category-summary.csv | Counts the expanded synthetic benchmark categories. |
| 02-expanded-benchmark-samples.csv | Shows representative benchmark cases and expected routes. |
| 03-evaluation-summary.md | Summarizes route, leakage, utility, latency, and adversarial results. |
| 04-baseline-comparison.csv | Compares no-gateway, regex-only, detector-only, and policy-bounded controller paths. |
| 05-route-accuracy-and-errors.md | Reviews route accuracy, false positives, false negatives, and mismatches. |
| 06-utility-scoring-rubric.md | Defines sufficient, partial, and insufficient utility labels. |
| 07-latency-summary.csv | Summarizes lightweight local latency measurements. |
| 08-adversarial-case-examples.md | Lists representative adversarial and mixed-risk cases. |
| 09-sanitized-payload-examples.md | Shows sanitized or pseudocode payload examples using synthetic data only. |
| 10-final-report-outline-mapping.md | Maps final report sections to available and remaining evidence. |

