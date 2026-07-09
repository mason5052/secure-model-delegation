> Public-safe copy of the submitted CS6727 progress report. Course-private attachments and raw runtime artifacts are not included. Company-specific names, if any, are generalized.
# Progress Report 3: Secure Model Delegation

**Section:** CS
**Project Title:** Secure Model Delegation: A Policy-Bounded Controller for Local-to-Cloud LLM Fallback
**Name:** Junkuk Kim
**Due Date:** 2026-06-28 11:59 PM ET

**AI Assistance Disclosure: I used generative AI tools as a support tool for brainstorming, language polishing, code review, and organizing project evidence. I made the final design decisions, reviewed and revised the submitted content, verified citations and results, and remain responsible for the work.**

## Problem Statement
Many enterprise AI assistants do not operate as a single model in a single place. A realistic system may first work inside a local or private environment and then delegate selected requests to a stronger hosted model when local handling is not enough. I am studying this local/private-to-cloud fallback path because the delegation step can become a security boundary. The request that leaves the trusted side may contain more than the user question. It may include retrieved context, logs, support tickets, code snippets, configuration text, incident notes, or other enterprise context.

Since PR1, I have tried to support this problem statement with more evidence instead of only personal observation. Prior work and tools such as Privacy Filter, Presidio, TruffleHog, Portcullis, PRISM, PPRoute, AgentDojo, prompt-injection studies, and egress-leakage work show that sensitive-span filtering, prompt privacy, routing privacy, and agent leakage are real concerns. My project does not claim that these areas are unsolved. Instead, it focuses on a narrower boundary: before text leaves a trusted local/private environment, a controller should decide whether the request should stay local, be denied, require clarification, be summarized locally, or be sanitized and delegated.

For PR3, I moved from planning into prototype evidence. I implemented the first Secure Model Delegation gateway skeleton, prepared policy and benchmark artifacts, and began testing how requests are classified, routed, sanitized, and logged before reaching a simulated external AI endpoint. I still use only synthetic enterprise-style examples. I do not use company-specific data, internal assistant project data, customer data, production logs, real credentials, real API keys, or proprietary source code.

## Solution Statement
The current solution is a Python prototype of a policy-bounded gateway for local/private-to-cloud fallback. The gateway assembles and normalizes a request, collects evidence about sensitive spans and risk signals, applies a policy-bounded controller, sanitizes or generalizes approved payloads, and sends only approved payloads to a simulated external endpoint. The simulated endpoint is useful for PR3 because it captures exactly what would have crossed the trust boundary without requiring real OpenAI or Claude API calls.

The research contribution remains Policy-Bounded Model Delegation Control and Evaluation. Privacy Filter, Presidio, TruffleHog-style patterns, and regex rules are supporting detector or baseline components. They are not the main contribution. The controller is the main artifact because it combines detector evidence, hard disclosure rules, route labels, conflict resolution, and delegated-payload evaluation. Hard policy constraints remain the authority. ML-assisted or heuristic routing can support utility and route estimation, but it cannot override policy-denied classes such as raw API keys, authentication tokens, system prompts, private code, or high-risk incident topology.

For PR3, OpenAI and Claude are represented as external target-policy profiles rather than live API dependencies. The current prototype uses a shared external_ai simulated endpoint so that the same policy-bounded egress path can be measured safely and reproducibly. Provider-specific OpenAI and Claude policy differences will be separated in PR4 and the final report.

## Completed Tasks (Last 2 Weeks)
- Implemented the first prototype skeleton for Secure Model Delegation in the local staging copy, including request modeling, normalization, evidence detection, policy/routing logic, sanitization, delegation logging, audit logging, a web UI, and an evaluation harness.
- Prepared a simulated external endpoint that records only the payloads approved for external delegation, which allows direct leakage checks before any real API use.
- Created and updated a YAML policy artifact with route labels, sensitive classes, hard disclosure rules, conflict-resolution rules, and leakage-oracle defaults.
- Expanded the benchmark from planning artifacts into 32 executable synthetic enterprise-style cases with expected routes and leakage oracles.
- Generated web UI evidence for three representative flows: API-key debugging with sanitized delegation, source-code debugging with pseudocode/generalized delegation, and incident topology routed to local summary with no external delegation.
- Implemented early baseline comparisons for no gateway, regex-only, detector-only, and policy-bounded controller behavior.
- Produced audit-log records that store decision metadata, detected labels, hashes, routes, and raw_input_stored=false instead of storing raw sensitive input.
- Ran validation checks: 13 unit and web tests passed, the web smoke test passed, the benchmark count is 32, route accuracy is 1.0 for the current labeled set, and direct leakage count is 0 for the policy-bounded controller run.
- Incorporated PR1 feedback by adding evidence-backed motivation, benchmark representativeness arguments, deployment tradeoff discussion, and safer synthetic-data controls.
- Incorporated PR2 feedback by adding an AI assistance disclosure and appendix evidence that shows actual project progress rather than only planning.

## Tasks for the Next Project Report
- Expand the benchmark from 32 cases toward 60 high-quality cases, prioritizing realistic coverage over raw count.
- Add more adversarial cases for obfuscated secrets, encoded policy-bypass text, prompt injection, source-code leakage, and mixed sensitive classes.
- Add latency measurement for the main gateway stages and compare it against the no-gateway baseline.
- Refine utility preservation scoring so the final report can discuss when sanitization still leaves a useful task and when local summary or clarification is better.
- Improve semantic leakage review. The current direct leakage check catches exact and pattern-based leakage, but semantic leakage still needs additional review.
- Prepare PR4 and final-report results tables that separate detector performance, route correctness, leakage results, utility tradeoffs, and implementation limitations.
- Keep the prototype reproducible in the trusted local development environment and document setup commands for PR4 and the final report.

## Questions I Have or Issues I Am Running Into
| Question or Issue | Current Working Assumption |
| --- | --- |
| Is a simulated external endpoint sufficient for PR3 evidence? | My working assumption is yes, because it directly shows what would have crossed the trust boundary without exposing data to a real provider. OpenAI and Claude remain target-policy profiles for now. |
| Is direct leakage count enough for the final report? | No. It is enough for the first prototype evidence, but the final evaluation should also discuss semantic leakage, utility preservation, false positives, false negatives, latency, and adversarial bypass. |
| How large should the final benchmark be? | I plan to grow from 32 cases toward 60 cases first. I will expand further only if labels and expected routes remain reliable. |
| How should I explain representativeness without real enterprise data? | I will map each synthetic category to a common enterprise workflow such as support tickets, log analysis, configuration review, code debugging, incident summarization, and internal troubleshooting. |

## Methodology Paragraph Summary
My methodology is to build and evaluate the gateway in small, testable layers. I first use related work to define the problem boundary and avoid overstating novelty. I then define a target-specific policy model, encode it in YAML, implement a prototype controller, and test it with synthetic enterprise-style benchmark cases. The benchmark records expected routes and leakage oracles, so the evaluation can compare the controller against simpler baselines. For PR3, the primary evidence is the captured delegated payload: if the simulated external endpoint receives a payload, I can inspect exactly what would have left the trusted boundary. This supports the bounded claim that direct policy-denied spans should not appear in delegated payloads when the gateway mediates the request and the sensitive spans are detected correctly.

## Deployment and Cost-Benefit Tradeoff
The deployment and cost tradeoff is part of the evaluation plan. The simulated external endpoint is safer, cheaper, and more reproducible than calling a live API during early testing because it records exactly what would have crossed the trust boundary. Local processing is safer but may have capability limits, while external AI can improve utility at the cost of API expense and additional disclosure risk; the gateway is intended to make that tradeoff auditable.

## Timeline
| Week | Task | Status |
| --- | --- | --- |
| W1 May 18-24 | Initial project proposal and workspace setup | Completed |
| W2 May 25-31 | Revised deployment, policy, benchmark, and evaluation plan after PR1 feedback | Completed |
| W3 Jun 1-7 | Peer feedback analysis, sensitive category refinement, related-work review | Completed |
| W4 Jun 8-14 | PR2 architecture, differentiation lock, policy matrix, benchmark schema, evaluation plan | Completed |
| W5 Jun 15-21 | Prototype skeleton, policy YAML, simulated endpoint, benchmark conversion, audit design | Completed |
| W6 Jun 22-28 | Web UI evidence, route tests, baseline comparison, evaluation output, PR3 appendix artifacts | In progress / PR3 evidence complete |
| W7 Jun 29-Jul 5 | Expand benchmark and adversarial cases; prepare Video 3 evidence | Planned |
| W8 Jul 6-12 | Run deeper evaluation and prepare PR4/final report outline | Planned |
| W9 Jul 13-19 | Analyze results, utility, false positives, false negatives, and limitations | Planned |
| W10 Jul 20-26 | Prepare final presentation and final report draft | Planned |
| W11 Jul 27-Aug 2 | Finalize report and submit by 2026-08-02 11:59 PM ET | Planned |

## Evaluation
The current evaluation is early, but it is now executable. The most important result for PR3 is that delegated payloads can be captured and checked before any real external API use. The direct leakage result below is limited to the current 32 synthetic cases and exact/pattern-based leakage checks; semantic leakage still needs additional review.

| Metric | Current Result |
| --- | --- |
| Benchmark count | 32 |
| Delegated cases | 14 |
| Route accuracy on current labeled set | 1.00 |
| Direct leakage count | 0 |
| Direct leakage findings per delegated case | 0.00 |
| Route counts | ask_clarification: 2, delegate_pseudocode_to_external_ai: 4, delegate_sanitized_to_external_ai: 10, deny_request: 1, local_process: 3, local_summary: 12 |

| Baseline | Delegated Cases | Direct Leakage Count | Direct Leakage Findings per Delegated Case |
| --- | ---: | ---: | ---: |
| no_gateway | 32 | 79 | 2.46875 |
| regex_only | 32 | 2 | 0.0625 |
| detector_only | 32 | 2 | 0.0625 |
| policy_bounded_controller | 14 | 0 | 0.0 |

Note: Direct leakage findings per delegated case is not a probability. It counts detected leakage findings divided by delegated cases, so it can exceed 1.0 when multiple sensitive spans leak in one case. The current route accuracy is measured on my self-constructed labeled synthetic set and will need broader validation in PR4 and the final report.

## Benchmark Representativeness
To address PR1 feedback, I am not claiming that synthetic data is identical to production data. Instead, I map each synthetic case type to a common enterprise AI assistant workflow and test whether the gateway prevents the corresponding sensitive spans from crossing the boundary.

| Synthetic Category | Enterprise Workflow | Why It Is Relevant |
| --- | --- | --- |
| API key or token debugging | Developer or support engineer asks for help with an authentication error | Tests whether secret-like strings are replaced before delegation. |
| Configuration review | Engineer asks for help with environment or connection settings | Tests mixed benign settings, hostnames, and secret fields. |
| Source-code debugging | Developer asks for bug review or explanation | Tests whether raw private code is kept local or converted to pseudocode. |
| Incident topology | Security or operations user asks for incident summary or next steps | Tests sensitive combinations of internal hosts, private IPs, and incident details. |
| Support ticket with PII | Support user asks for a customer-facing draft | Tests whether useful writing tasks can continue after placeholder transformation. |
| Prompt-injection text | Retrieved or user-provided text attempts to override the gateway | Tests whether malicious text is treated as data, not as policy authority. |

## Report Outline
| Section | Planned Final Report Content |
| --- | --- |
| 1 | Introduction and problem motivation |
| 2 | Background and related work |
| 3 | Threat model and trust boundary |
| 4 | Policy model and route labels |
| 5 | Prototype architecture and implementation |
| 6 | Synthetic benchmark design and representativeness |
| 7 | Evaluation methodology |
| 8 | Results and baseline comparison |
| 9 | Deployment challenges and cost/benefit tradeoffs |
| 10 | Limitations and future work |

## References
- OpenAI. Privacy Filter. https://github.com/openai/privacy-filter
- Microsoft. Presidio: Data protection and de-identification SDK. https://microsoft.github.io/presidio/
- Truffle Security. TruffleHog. https://github.com/trufflesecurity/trufflehog
- OWASP. Top 10 for Large Language Model Applications. https://owasp.org/www-project-top-10-for-large-language-model-applications/
- NIST. Artificial Intelligence Risk Management Framework (AI RMF 1.0), 2023. https://www.nist.gov/itl/ai-risk-management-framework
- Debenedetti et al. AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents, NeurIPS 2024. https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html
- Zhan et al. Portcullis: A Scalable and Verifiable Privacy Gateway for Third-Party LLM Inference, AAAI 2025. https://ojs.aaai.org/index.php/AAAI/article/view/32088
- Zhan et al. PRISM: Privacy-Aware Routing for Adaptive Cloud-Edge LLM Inference via Semantic Sketch Collaboration. https://arxiv.org/abs/2511.22788
- Wu et al. Privacy-Preserving LLMs Routing (PPRoute). https://arxiv.org/abs/2604.15728
- Lan et al. Silent Egress: When Implicit Prompt Injection Makes LLM Agents Leak Without a Trace. https://arxiv.org/abs/2602.22450
- Alizadeh et al. Simple Prompt Injection Attacks Can Leak Personal Data Observed by LLM Agents During Task Execution. https://arxiv.org/abs/2506.01055

## Appendix A: PR3 Evidence Index
All appendix evidence is stored in `submissions/pr3-evidence/`.

| Item | File | Purpose |
| --- | --- | --- |
| A1 | `01-architecture-v7-portrait.png` | Architecture diagram v7 |
| A2 | `02-web-ui-home.png` | Prototype web UI screenshot |
| A3 | `03-api-key-test-result.png` | API-key sanitized delegation test |
| A4 | `04-source-code-pseudocode-test-result.png` | Source-code pseudocode/generalization test |
| A5 | `05-local-summary-test-result.png` | Incident topology local-summary test |
| A6 | `06-policy-yaml-excerpt.txt` | Policy YAML excerpt |
| A7 | `07-benchmark-case-samples.csv` | Benchmark case samples |
| A8 | `08-simulated-external-endpoint-log-sample.jsonl` | Simulated external endpoint log sample |
| A9 | `09-audit-log-sample.jsonl` | Audit log sample |
| A10 | `10-evaluation-output-sample.txt` | Evaluation output sample |
| A11 | `11-route-decision-examples.md` | Route decision examples |
| A12 | `12-sanitized-payload-examples.md` | Sanitized payload examples |
| A13 | `13-validation-results.md` | Validation results |

## Appendix B: Architecture and Prototype Flow
![Gateway Architecture v7](pr3-evidence/01-architecture-v7-portrait.png)

- Request normalization creates a consistent request object from the prompt, context, metadata, and target profile.
- Evidence providers are supporting components that identify sensitive spans and risk signals.
- The policy-bounded controller is the research core. It resolves conflicts and decides the final route.
- The egress guard and sanitizer run before any simulated external call.
- The simulated external endpoint records approved payloads for leakage evaluation.
- Audit logging records decision metadata and hashes without storing raw sensitive input.

## Appendix C: Web UI Evidence
![Web UI home](pr3-evidence/02-web-ui-home.png)

![API key sanitized delegation](pr3-evidence/03-api-key-test-result-redacted.png)

![Source code pseudocode delegation](pr3-evidence/04-source-code-pseudocode-test-result-redacted.png)

![Incident topology local summary](pr3-evidence/05-local-summary-test-result-redacted.png)

## Appendix D: Benchmark Case Samples
| Case ID | Category | Expected Route | Utility Goal | Must Not Contain |
| --- | --- | --- | --- | --- |
| B001 | api_key_generic_debugging | delegate_sanitized_to_external_ai | Explain likely authentication issue without exposing the raw key. | synthetic-service-key-123456 |
| B006 | internal_topology_plus_incident_detail | local_summary | Keep detailed incident topology local. | vpn-gw-prod; prod-db-01.acme.internal; privileged admin subnet |
| B012 | source_code_to_pseudocode | delegate_pseudocode_to_external_ai | Use pseudocode/generalized problem statement rather than raw code. | function updateOrder; order.status = 'paid' |
| B016 | pii_support_ticket | delegate_sanitized_to_external_ai | Draft a generic support reply after PII replacement. | Jane Park; jane.park@example.com; 404-555-0181 |
| B018 | system_prompt_extraction_attempt | deny_request | Deny hidden instruction extraction attempts. | system prompt; hidden router instructions |
| B030 | public_policy_explanation | delegate_sanitized_to_external_ai | Allow public training content delegation. |  |
| B031 | pii_without_task_intent | ask_clarification | Ask clarification because the task intent is missing. | Jane Park; jane.park@example.com; 404-555-0181 |
| B032 | private_ip_plus_incident | local_summary | Keep incident plus private IP local. | 192.168.10.50; attacker accessed |

## Appendix E: Validation Results
See `submissions/pr3-evidence/13-validation-results.md` for the test, smoke, benchmark, and local staging validation notes used for PR3.