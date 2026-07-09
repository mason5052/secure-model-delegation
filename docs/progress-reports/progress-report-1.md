> Public-safe copy of the submitted CS6727 progress report. Course-private attachments and raw runtime artifacts are not included. Company-specific names, if any, are generalized.
# Progress Report 1: Secure Model Delegation: Policy-Bounded Control for Local-to-Cloud LLM Fallback

Section: CS
Name: Junkuk Kim

## Problem Statement

Many AI systems are no longer built around a single model running in one place. In practice, an enterprise AI assistant may start with a local or private model, but then send selected difficult requests to a stronger cloud-based LLM when the local model is not capable enough. I am interested in this local/private-to-cloud fallback pattern because it creates a security boundary that is easy to overlook. The request being delegated may include user prompts, retrieved context, logs, code snippets, incident notes, or support tickets, and those materials may contain credentials, personal information, proprietary code, internal infrastructure details, or regulated data that should not be exposed to the cloud model.

For my practicum project, I am studying this fallback path as a policy enforcement problem. I plan to design, implement, and evaluate a Secure Model Delegation gateway that sits between the trusted local or private environment and the less-trusted cloud LLM. Given a text request, the gateway will identify sensitive spans, apply target-specific disclosure rules, and decide whether the request should be handled locally, denied, or sanitized before any cloud delegation occurs.

In response to Professor Ahamad's feedback, I am making the deployment and evaluation plan more concrete. The project will use my AI-focused desktop as the trusted local testbed. The less-trusted external targets will be real hosted model APIs, specifically OpenAI and Anthropic Claude. This matches the enterprise assistant pattern that motivated the project, including what I have observed from an active AI assistant project at my workplace, where Claude is accessed through an API.

I will not use proprietary company project data, customer information, internal documents, production logs, or real secrets. All evaluation inputs will be synthetic enterprise-style examples. For reproducibility and leakage measurement, the gateway will record the exact synthetic payload that would be sent to OpenAI or Claude, and API-based tests will use only synthetic or sanitized content.

## Solution Statement

This research will build and evaluate a policy-bounded gateway for local/private-to-cloud LLM fallback in order to reduce direct sensitive-data leakage while preserving enough task utility for selected enterprise-style requests.

The design separates two decisions that should not be mixed together. The first is mandatory disclosure control: hard policy rules decide which sensitive classes are never allowed to leave the trusted boundary, which classes may be transformed, and which classes may be delegated. The second is routing and utility estimation: a lightweight machine-learning classifier, supported by deterministic features from the gateway, will estimate whether a request should be handled locally, denied, clarified, summarized locally, or sanitized and delegated to OpenAI or Claude.

I will minimize reliance on a local LLM as the security authority. If a local LLM is used, it will be an advisory baseline or feature generator, not the component that can override policy. This keeps the security claim bounded: ML or local-model reasoning may recommend a route, but hard policy rules still block high-risk disclosures such as credentials, private code, and other policy-denied spans.

The concrete work products will be a threat model, target-specific policy matrix, Python prototype, synthetic benchmark, OpenAI/Claude API adapters, baseline comparison, evaluation results, final report, and final presentation.

## Completed Tasks (Last 2 Weeks)

- Submitted the initial project proposal and received feedback from Professor Ahamad on 2026-05-27.
- Reviewed the feedback and identified three areas that needed more concrete detail: deployment/test environment, policy choice, and benchmark/evaluation design.
- Refined the project scope to text-only local/private-to-cloud LLM fallback using synthetic enterprise-style data.
- Defined the local AI desktop as the trusted testbed and real OpenAI and Anthropic Claude API endpoints as the less-trusted delegation targets, using only synthetic or sanitized content.
- Drafted an initial policy matrix covering credentials, PII, internal infrastructure, proprietary code, incident/security details, public context, and prompt-injection content.
- Designed an initial benchmark plan using 80-120 synthetic enterprise-style text requests with expected sensitive spans, expected policy action, expected route, expected API target, and expected leakage outcome.
- Revised the proposal language to emphasize a policy-bounded gateway with machine-learning-assisted routing rather than a pure keyword filter or an LLM-based security judge.

## Tasks for the Next Project Report

- Create the project repository skeleton for the gateway prototype: sensitive-span classifier, policy engine, ML-assisted router, sanitizer, verifier, audit logger, benchmark runner, and API adapters.
- Define the first YAML or JSON policy file for the cloud target using allow, transform, deny, and local-summary-only actions.
- Build OpenAI and Anthropic Claude API adapter stubs plus a local payload-capture logger so leakage can be measured before and after actual API calls.
- Create the first 30 synthetic benchmark cases across credentials, PII, internal infrastructure, code snippets, incident notes, benign prompts, and prompt-injection attempts.
- Implement initial regex/custom detectors for credentials, emails, phone numbers, private hostnames, private IP ranges, code blocks, and prompt-injection language.
- Train or configure a first lightweight ML routing classifier on labeled synthetic cases and compare it with deterministic routing rules.
- Draft the formal threat model and complete mediation assumption for the PR2 solution approach.
- Run first baselines: no gateway to OpenAI/Claude, regex-only sanitizer, and ML-assisted policy gateway on the initial benchmark set.

## Questions I Have or Issues I Am Running Into

- Is the proposed deployment/test environment concrete enough: AI desktop as the trusted local environment, Python gateway as the control point, and real OpenAI and Anthropic Claude APIs as the less-trusted external targets?
- Is the policy-bounded, machine-learning-assisted router a reasonable way to decide local handling versus sanitized external delegation, as long as hard policy rules cannot be overridden?
- Are the initial policy categories reasonable for this scope: credentials, PII, internal infrastructure, proprietary code, incident/security details, public context, and prompt-injection text?
- Is an 80-120 case synthetic enterprise benchmark an appropriate target size for the final evaluation?

## Methodology Paragraph Summary

My methodology will follow a systematic security-engineering process. First, I will define the local/private-to-cloud fallback threat model, including assets, trust boundaries, adversaries, non-goals, and complete mediation assumptions. Second, I will define a target-specific disclosure policy that maps sensitive classes to actions such as allow, transform, deny, or local-summary-only for OpenAI and Claude delegation. Third, I will implement a Python gateway on my AI desktop with sensitive-span detectors, a policy engine, a lightweight ML-assisted router, sanitizer, response verifier, audit log, and API adapters. Fourth, I will build a synthetic enterprise benchmark and run multiple baselines: no gateway to OpenAI/Claude, regex-only sanitizer, local-LLM or LLM-as-router baseline if feasible, and the policy-bounded ML-assisted gateway. Finally, I will evaluate leakage reduction, routing correctness, utility preservation, latency overhead, and adversarial bypass resistance.

## Timeline

Schedule note: I am treating this as an 11-active-week practicum. Based on Canvas and Ed guidance, the final report is due by 2026-08-02 at 11:59 PM ET. The week beginning 2026-08-03 is the final exam/grading week; this course has no final exam, and that period is reserved for staff review of final reports rather than continued project work.

| Week # | Description of Task | Status |
| --- | --- | --- |
| W1 (May 18 to May 24) | Define first project scope, problem statement, motivation, expected deliverables, and course workspace structure. | Completed |
| W1 | Capture syllabus, Canvas dates, Ed guidance, project notes, and initial Secure Model Delegation framing. | Completed |
| W2 (May 25 to May 31) | Review Professor Ahamad's feedback and revise project scope with a concrete deployment and evaluation plan. | Completed |
| W2 | Define AI desktop local testbed, OpenAI/Claude API targets, initial policy matrix, ML-assisted routing design, and benchmark schema. | In progress |
| W2 | Draft initial threat-model notes and identify the minimum viable prototype components for the next reporting cycle. | In progress |
| W3 (Jun 1 to Jun 7) | Create prototype repository skeleton with sensitive-span detector, policy engine, ML-assisted router, sanitizer, verifier, audit, and benchmark modules. | Planned |
| W3 | Implement OpenAI/Claude API adapter stubs and first no-gateway delegation payload logger. | Planned |
| W3 | Create first 30 synthetic benchmark cases with labeled sensitive spans, expected policy actions, expected routes, and API targets. | Planned |
| W4 (Jun 8 to Jun 14) | Implement initial detectors for credentials, PII, internal infrastructure, private IPs, hostnames, code blocks, and injection phrases. | Planned |
| W4 | Write first YAML/JSON policy file, implement first ML-assisted routing classifier, and run classifier/sanitizer tests. | Planned |
| W4 | Expand literature notes and convert the solution approach into draft report sections with links to code and benchmark artifacts. | Planned |
| W5 (Jun 15 to Jun 21) | Expand benchmark to 60 cases and implement stable placeholders for transformed sensitive spans. | Planned |
| W5 | Add audit log format that records metadata without raw secrets. | Planned |
| W5 | Run first detector and sanitizer quality checks and document early false positives, false negatives, and utility tradeoffs. | Planned |
| W6 (Jun 22 to Jun 28) | Implement routing decisions: process_local, deny, ask_clarification, delegate_sanitized, and local_summary_then_delegate. | Planned |
| W6 | Run no-gateway to OpenAI/Claude, regex-only sanitizer, and ML-assisted gateway baselines. | Planned |
| W6 | Package initial evaluation evidence: metrics tables, representative cases, audit log examples, and observed limitations. | Planned |
| W7 (Jun 29 to Jul 5) | Expand benchmark to 80-120 cases including adversarial prompt-injection examples. | Planned |
| W7 | Add optional local-LLM or LLM-as-router baseline if feasible and compare prompt-injection behavior. | Planned |
| W7 | Refine benchmark labels and update threat model based on bypass attempts and routing failures. | Planned |
| W8 (Jul 6 to Jul 12) | Run full policy-first gateway evaluation on benchmark set. | Planned |
| W8 | Draft final report outline and limitations section. | Planned |
| W8 | Freeze final report structure and identify any remaining evidence gaps before final evaluation write-up. | Planned |
| W9 (Jul 13 to Jul 19) | Analyze direct leakage, policy accuracy, detection precision/recall, latency, utility, and bypass results. | Planned |
| W9 | Revise prototype, benchmark, and policy matrix based on evaluation results and peer/staff feedback. | Planned |
| W10 (Jul 20 to Jul 26) | Create final presentation narrative and figures from the implemented system, benchmark, and evaluation results. | Planned |
| W10 | Draft final report body and include architecture, benchmark, and evaluation tables. | Planned |
| W11 (Jul 27 to Aug 2) | Complete final revision buffer: check citations, verify artifacts, finalize limitations, and submit the final project report by 2026-08-02 11:59 PM ET. | Planned |

## Evaluation

| Metric | How It Will Be Measured | Purpose |
| --- | --- | --- |
| Direct leakage rate | leaked_denied_spans / total_denied_spans in captured OpenAI/Claude payloads | Target: zero for correctly classified denied spans |
| Policy and routing accuracy | Correct policy action, route, and API target / total cases | Checks whether the gateway applies policy and routing decisions as expected |
| Detection precision/recall | Classifier results vs labeled synthetic spans | Shows detector strengths and weaknesses |
| ML routing performance | ML router prediction vs labeled expected route | Shows whether ML adds value beyond deterministic routing |
| Utility preservation | Human rubric or LLM-as-judge on sanitized OpenAI/Claude task output | Measures task quality after sanitization |
| Latency overhead | classification_time + policy_time + ML_routing_time + sanitization_time | Measures gateway cost |
| Adversarial bypass rate | successful_policy_bypasses / adversarial_cases | Measures prompt-injection resistance |

## Report Outline

- 1. Introduction and problem motivation
- 2. Background: local/private-to-cloud LLM fallback, privacy gateways, DLP, and prompt injection
- 3. Threat model and security goals
- 4. Policy model and disclosure rules
- 5. System design: sensitive-span detectors, policy engine, ML-assisted router, sanitizer, verifier, audit log, API adapters
- 6. Deployment/test environment on AI desktop with OpenAI and Anthropic Claude API targets
- 7. Synthetic benchmark design
- 8. Evaluation methodology and results
- 9. Limitations: semantic leakage, classifier false negatives, metadata, utility loss
- 10. Conclusion and future work

## References

- NIST. Artificial Intelligence Risk Management Framework (AI RMF 1.0), 2023. https://www.nist.gov/itl/ai-risk-management-framework
- NIST. Security and Privacy Controls for Information Systems and Organizations, SP 800-53 Rev. 5, especially information flow enforcement concepts. https://csrc.nist.gov/publications/detail/sp/800-53/rev-5/final
- OWASP. Top 10 for Large Language Model Applications. https://owasp.org/www-project-top-10-for-large-language-model-applications/
- Microsoft Presidio. Data protection and de-identification SDK. https://microsoft.github.io/presidio/
- Ruan et al. AgentDojo: A Dynamic Environment to Evaluate Attacks and Defenses for LLM Agents, NeurIPS 2024. https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html
- PRISM: Privacy-Aware Routing for Adaptive Cloud-Edge LLM Inference. https://arxiv.org/abs/2511.22788
- Portcullis: Privacy-preserving prompt gateway work for LLMs. https://ojs.aaai.org/index.php/AAAI/article/view/32088

## Appendix

Architecture sketch:

```text
User request + retrieved text
        -> trusted local/private AI environment on AI desktop
        -> Secure Model Delegation gateway
        -> hard policy gate + ML-assisted routing
        -> process locally OR deny OR ask clarification OR sanitized delegation
        -> less-trusted OpenAI API and Anthropic Claude API targets
```

### Initial Policy Matrix

| Sensitive Class | Examples | Default Action for OpenAI/Claude Delegation |
| --- | --- | --- |
| Credentials | API keys, passwords, tokens, SSH keys | Deny/remove before cloud delegation |
| PII | Names, emails, phone numbers, addresses | Transform to stable placeholders |
| Internal infrastructure | Internal hostnames, private IPs, topology, secret paths | Transform or generalize |
| Proprietary code | Private source code, internal repo snippets | Deny or local-summary-only |
| Incident/security details | Investigation notes, alert context, internal findings | Transform or summarize |
| Public/benign context | Public docs, generic error messages | Allow |
| Prompt-injection text | Instructions to bypass policy or reveal secrets | Treat as data; never policy authority |

### Initial Benchmark Schema

| Field | Meaning | Example |
| --- | --- | --- |
| case_id | Unique identifier for each synthetic case | T001 |
| input_text | Synthetic enterprise-style request | Support ticket, log snippet, code snippet, incident note |
| sensitive_spans | Expected labeled sensitive spans | email, API key, hostname |
| policy_actions | Expected action for each class | transform, deny, allow |
| expected_route | Expected router decision | process_local, deny, delegate_sanitized |
| api_target | Expected external target when delegation is allowed | OpenAI, Claude, or none |
| expected_delegated_text | Gold sanitized output for direct leakage checks | Text with stable placeholders |
| utility_task | Task to preserve after sanitization | Summarize, debug, classify, explain |

AI Assistance Disclosure: I used generative AI as a supplementary aid for planning, outlining, and drafting this report. I reviewed and revised the content and remain responsible for the project direction, claims, and final submission.
