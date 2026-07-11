> Public-safe copy of the CS6727 progress report. Course-private attachments and raw runtime artifacts are not included. All benchmark content is synthetic.

# Progress Report 4

**Section:** CS
**Project Title:** Secure Model Delegation: A Policy-Bounded Controller for Local-to-Cloud LLM Fallback
**Name:** Junkuk Kim
**Due Date:** 2026-07-12 11:59 PM ET

**AI Assistance Disclosure:** I used generative AI tools as a support tool for brainstorming, language polishing, code review, and organizing project evidence. I made the final design decisions, reviewed and revised the submitted content, verified citations and results, and remain responsible for the work.

## Problem Statement

Not all of the enterprise AI assistants function as a single model in one place. In a realistic system, an AI might process the request in its local or private environment and then delegate the request to a better-performing hosted model whenever local processing is inadequate. I am interested in studying the local/private-to-cloud delegation because there is a possibility of a security boundary at the point of delegation. The request that escapes the trusted side could carry information beyond just the user's request. This could be the retrieved context, logs, support tickets, code snippets, configuration text, incident notes, etc.

Starting from PR1, my aim was to back up my problem statement with more evidence than just observation. There is plenty of prior work, tools, and demonstrations showing the reality of sensitive span filtering, prompt privacy, routing privacy, and agent leakage. This project does not make any claim about these research topics being unresolved by now. On the contrary, it focuses on a more narrow boundary: before the text leaves a trusted local/private environment, a controller needs to determine whether the request should be localized, blocked, clarified, localized and summarized, or sanitized and delegated.

Since PR3, I have moved from a 32-case prototype demonstration to a reproducible system-and-evaluation study. I implemented SMD-Bench-1400, added a 210-case post-freeze challenge set, separated end-to-end detector effects from controller-only behavior, and preserved failures rather than relabeling them to match the implementation. All evaluation data remain synthetic. I do not use real company data, customer data, production logs, credentials, API keys, or proprietary source code.

## Solution Statement

The current solution remains a Python-based prototype of a policy-bounded gateway for local/private-to-cloud fallback. The gateway prepares the request, gathers evidence about sensitive spans and risk signals, applies the policy-bounded controller, sanitizes or generalizes approved payloads, and sends them only to a simulated external AI endpoint. The endpoint records exactly what would cross the trust boundary without involving live OpenAI or Claude APIs.

The research contribution is still Policy-Bounded Model Delegation Control and Evaluation. The supporting components are Privacy Filter, Presidio, TruffleHog-like patterns, and regex-based rules - they are only the detectors or baselines, not the primary contribution. The controller is the primary artifact that uses the detector evidence, disclosure rules, route labels, conflict resolution rules, and payload evaluation for the delegated payloads.

The hard policy constraints are still authoritative. ML-assisted or heuristic routing can improve utility and route estimation, but it cannot overwrite the policy-denied class such as raw API keys, authentication tokens, system prompts, private code, or high-risk incident topology.

I now express the decision model in two stages. Let `E` be the detected evidence, `P_t` the policy for target profile `t`, and `R` the route set:

```text
A(E, P_t) = { r in R | H(r, E, P_t) = 1 }
R* = arg max over r in A(E, P_t) of U(r | x, t, E, P_t)
```

`H` is the hard disclosure-policy predicate. It first removes forbidden routes. Utility scoring `U` then ranks only the remaining policy-allowed routes. This makes the security boundary different from a filter-only system: the controller may keep the request local, deny it, ask for clarification, create a local summary, or delegate a sanitized or generalized payload. For source code, the implemented target matrix allows raw local processing for a local/private target, pseudocode delegation for an approved external target, and local-summary-only handling for a high-risk external target.

OpenAI and Claude remain future provider mappings rather than live dependencies in the current experiment. The implemented profiles are `local_private`, `approved_external_ai`, and `high_risk_external_ai`, and the simulated endpoint remains the primary reproducible egress target.

## Completed Tasks (Last 2 Weeks)

- Replaced the small hand-maintained benchmark with SMD-Bench-1400, a deterministic generator containing 1,400 unique synthetic cases from 70 semantic templates and 20 controlled variants per template.
- Balanced the benchmark across seven policy families and three target profiles so the evaluation measures coverage rather than pretending to estimate production workload frequency.
- Added 380 explicit adversarial-evasion or prompt-injection cases to the main benchmark while keeping routine sensitive requests separate from attack cases.
- Froze the controller and runtime-policy implementation at commit `d1d13cd3822a00b8c5cbd64d3a5ff90552c0159b`, then generated SMD-Challenge-210 from 35 new semantic templates without changing the frozen controller.
- Separated end-to-end evaluation from controller-only evaluation. The first uses implemented detectors; the second injects ground-truth evidence so detector failures are not incorrectly attributed to the controller.
- Added baselines for no gateway, always local, regex secret/PII filtering, all-detectors filtering, target-agnostic control, hard policy without utility, and the full policy-bounded controller.
- Implemented target-specific source-code behavior: raw code can remain local, approved external targets receive generalized pseudocode, and high-risk external targets receive no raw egress.
- Added canonicalized, encoded, and structural code-detail leakage checks in addition to direct string leakage checks.
- Added utility-weight sensitivity analysis that compares route preferences only after hard policy has admitted the candidate routes.
- Created stratified human-review artifacts for 210 main cases, a 70-case second-review overlap, and the 210 challenge cases. These reviews are explicitly marked pending rather than claimed as completed validation.
- Preserved main and challenge failures, including overblocking and weak evidence classes, instead of tuning labels to make the results appear perfect.
- Expanded automated validation to 47 unit and integration tests, deterministic generation checks, controller-freeze verification, full benchmark evaluation, challenge evaluation, and web smoke testing in GitHub Actions.
- Merged the hardened benchmark and evaluation implementation into the public personal repository's `main` branch with a history-preserving merge commit.

## Tasks for the Next Project Report and Final Deliverables

- Complete the 210-case main human review and record corrections without silently changing the original automated labels.
- Obtain an independent second review for the 70-case overlap and calculate raw agreement and Cohen's kappa for route and utility judgments.
- Review all 210 challenge cases while keeping the frozen result as the primary post-freeze evidence.
- Define and apply a limited semantic-leakage rubric because zero direct, encoded, or structural leakage does not prove full semantic privacy.
- Analyze the preserved challenge failures, especially unseen proprietary-code phrasing and internal-infrastructure evidence, without presenting the same challenge set as a new untouched test after tuning.
- Convert the related-work notes into a concise synthesis that explains why filter-only and target-agnostic approaches do not answer the same delegation question.
- Prepare the final presentation around the decision model, comparative evaluation, challenge failures, bounded security claim, and limitations.
- Complete the final report and keep optional sanitized-only OpenAI/Claude smoke tests separate from the primary reproducible experiment.

## Questions I Have or Issues I Am Running Into

| Question or Issue | Current Working Position |
| --- | --- |
| How should I present the lower challenge-set performance? | I plan to foreground it as the more informative post-freeze result rather than hiding it behind the stronger authored main-set score. |
| Can zero automatic leakage be described as proof of privacy? | No. I will limit the claim to direct, encoded, and structural leakage under the implemented synthetic oracles and state that semantic privacy remains unproven. |
| How should I use the human-review results if they are incomplete by the final presentation? | I will report the exact completed count and agreement status, and I will not describe pending cases as human validated. |
| Should OpenAI and Claude be called evaluated providers? | No. They are intended provider mappings. The current experiment evaluates target-policy profiles and a simulated endpoint, not provider-side behavior. |

## Methodology Paragraph Summary

My methodology now follows a system-and-evaluation sequence. I first define the local-to-cloud trust boundary, route set, evidence classes, target-specific policy, and bounded non-disclosure claim. I then encode the policy independently from the benchmark oracle, generate coverage-balanced synthetic cases, and evaluate both the full pipeline and the controller with ground-truth evidence. The controller first constructs the hard-policy allowed set and only then applies route-specific utility scoring. External routes pass through sanitization or code generalization before the simulated endpoint records the delegated payload.

The primary comparative question is not whether a detector can mask a span. It is whether the system chooses an appropriate route and disclosure form for the target. I therefore compare route conformance, security-relevant target-policy violations, overblocking, evidence-class performance, utility-label agreement, and multiple leakage oracles. I also freeze the controller before a separate challenge set so that lower post-freeze results remain visible. The study supports a bounded claim inside the authored synthetic policy scope; it is not independent proof of production safety.

## Deployment and Cost-Benefit Tradeoff

The simulated endpoint remains the primary evaluation environment because it is reproducible, inexpensive, and lets me inspect the exact egress payload. Local processing provides the strongest confidentiality boundary but can limit capability, while external assistance can improve utility at the cost of disclosure risk and provider expense. The controller makes this tradeoff auditable by recording the evidence, allowed route set, selected route, transformation, and egress result without storing raw sensitive input in the audit log.

## Timeline

| Week | Dates | Project Work | Status |
| --- | --- | --- | --- |
| W1 | May 18-24 | Initial proposal and project framing | Completed |
| W2 | May 25-31 | Revised deployment, policy, benchmark, and evaluation plan | Completed |
| W3 | Jun 1-7 | Sensitive-category refinement and related-work review | Completed |
| W4 | Jun 8-14 | Architecture, differentiation, policy matrix, and benchmark schema | Completed |
| W5 | Jun 15-21 | Prototype skeleton, web UI, policy YAML, and simulated endpoint | Completed |
| W6 | Jun 22-28 | PR3 implementation evidence and initial 32-case evaluation | Completed |
| W7 | Jun 29-Jul 5 | Formal decision model, benchmark generator design, and evaluation hardening | Completed |
| W8 | Jul 6-12 | SMD-Bench-1400, frozen challenge evaluation, baselines, sensitivity analysis, and PR4 | Completed / PR4 ready |
| W9 | Jul 13-19 | Human review, failure analysis, semantic-leakage rubric, and final presentation preparation | Planned |
| W10 | Jul 20-26 | Final presentation, peer review, and final report draft | Planned |
| W11 | Jul 27-Aug 2 | Final analysis, report polish, and submission | Planned |

## Evaluation

### Evaluation Sets

| Set | Cases | Purpose |
| --- | ---: | --- |
| Preserved regression set | 63 | Detect behavior changes from the earlier prototype. |
| SMD-Bench development | 1,120 | Coverage-balanced implementation development. |
| SMD-Bench template evaluation | 280 | Evaluate separated templates; not claimed as untouched. |
| SMD-Challenge-210 | 210 | Post-freeze evaluation using 35 new semantic templates. |
| Main human-review sample | 210 | Stratified review; pending. |
| Second-review overlap | 70 | Independent agreement measurement; pending. |

SMD-Bench-1400 contains 70 semantic templates with 20 synthetic variants each. It is balanced across seven policy families and approximately balanced across the three target profiles. It is designed for controlled security coverage, not as an estimate of real enterprise request frequency.

### Current Results

| Metric | Regression 63 | SMD-Bench-1400 | SMD-Challenge-210 |
| --- | ---: | ---: | ---: |
| End-to-end policy conformance | 0.905 | 0.941 | 0.876 |
| Controller-only policy conformance | Not labeled | 0.996 | 0.914 |
| Security-relevant target-policy violations | 0 | 0 | 0 |
| Overblocked expected delegations | 2 | 72 | 18 |
| Direct leakage findings | 0 | 0 | 0 |
| Canonicalized or encoded leakage findings | 0 | 0 | 0 |
| Structural code-detail leakage findings | 0 | 0 | 0 |
| Evidence-class macro F1 | Not labeled | 0.935 | 0.867 |
| Rule-based utility-label agreement | Not labeled | 0.915 | 0.895 |

The difference between 0.941 end-to-end conformance and 0.996 controller-only conformance on the main set shows that detector behavior contributes more error than policy arbitration when the controller receives correct evidence. The challenge set provides a less optimistic post-freeze signal: end-to-end conformance fell to 0.876, proprietary-code recall was zero for unseen phrasing, and internal-infrastructure F1 was 0.364. I preserved these failures for the final analysis.

### Baseline Comparison on SMD-Bench-1400

| Approach | Route Conformance | Target-Policy Violation Rate | Overblocked Rate | Direct Leakage Cases |
| --- | ---: | ---: | ---: | ---: |
| no_gateway | 0.342 | 0.649 | 0.000 | 880 |
| always_local | 0.379 | 0.000 | 0.375 | 0 |
| regex_secret_pii_filter | 0.342 | 0.649 | 0.000 | 240 |
| all_detectors_filter_only | 0.342 | 0.649 | 0.000 | 0 |
| target_agnostic_controller | 0.635 | 0.215 | 0.051 | 0 |
| hard_policy_without_utility | 0.984 | 0.009 | 0.000 | 0 |
| policy_bounded_controller | 0.941 | 0.000 | 0.051 | 0 |

The all-detectors filter baseline is particularly important. It produced zero automatic span-leakage cases on the authored main set, but it still used a less-protective external route in 64.9 percent of cases. This shows why zero detected span leakage is not equivalent to a correct model-delegation decision. The always-local baseline avoided external violations but overblocked 37.5 percent of expected delegations. The target-agnostic controller also underperformed, which supports the need for target-specific policy.

A target-policy violation is counted only when a security-relevant request is sent through an external route with less disclosure protection than the authored expected route. A safer but less useful route is recorded as a route mismatch or overblocking, not as a security violation.

### Utility Sensitivity

Changing the utility weights changed main-set route conformance from 0.744 to 0.991 and challenge-set conformance from 0.733 to 0.933. Every compared route was already inside the hard-policy allowed set. This result supports the architecture's security ordering, but it also shows that the operational route choice depends on utility assumptions that still require human validation.

### Bounded Interpretation

The current evidence supports a bounded result: in these synthetic evaluations, utility scoring did not select a route outside the hard-policy allowed set, and the controller-mediated delegated payloads produced no automatic direct, encoded, or structural leakage findings. This does not establish perfect detector coverage, semantic privacy, production prevalence, provider behavior, or general robustness. Human review, inter-rater agreement, semantic-leakage assessment, and independently collected enterprise-like cases remain publication gates.

## Report Outline

1. Introduction and problem motivation
2. Background and related work
3. Threat model and trust boundary
4. Formal decision model and target-specific policy
5. Prototype architecture and implementation
6. SMD-Bench design and generation methodology
7. Evaluation methodology and bounded security properties
8. Main, baseline, sensitivity, and challenge results
9. Failure analysis and deployment tradeoffs
10. Limitations and threats to validity
11. Conclusion and future work

## References

- OpenAI. Privacy Filter. https://github.com/openai/privacy-filter
- Microsoft. Presidio: Data protection and de-identification SDK. https://microsoft.github.io/presidio/
- Truffle Security. TruffleHog. https://github.com/trufflesecurity/trufflehog
- OWASP. Top 10 for Large Language Model Applications. https://owasp.org/www-project-top-10-for-large-language-model-applications/
- NIST. Artificial Intelligence Risk Management Framework (AI RMF 1.0), 2023. https://www.nist.gov/itl/ai-risk-management-framework
- Debenedetti et al. AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents. NeurIPS 2024. https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html
- Zhan et al. Portcullis: A Scalable and Verifiable Privacy Gateway for Third-Party LLM Inference. AAAI 2025. https://ojs.aaai.org/index.php/AAAI/article/view/32088
- Zhan et al. PRISM: Privacy-Aware Routing for Adaptive Cloud-Edge LLM Inference via Semantic Sketch Collaboration. https://arxiv.org/abs/2511.22788
- Wu et al. Privacy-Preserving LLMs Routing (PPRoute). https://arxiv.org/abs/2604.15728
- Lan et al. Silent Egress: When Implicit Prompt Injection Makes LLM Agents Leak Without a Trace. https://arxiv.org/abs/2602.22450
- Alizadeh et al. Simple Prompt Injection Attacks Can Leak Personal Data Observed by LLM Agents During Task Execution. https://arxiv.org/abs/2506.01055

## Public Evidence

- Architecture: [Secure Model Delegation architecture](../assets/secure-model-delegation-architecture.png)
- Evaluation summary: [Public Evaluation Summary](../evaluation-summary.md)
- Benchmark methodology: [SMD-Bench-1400 Methodology](../smd-bench-1400-methodology.md)
- Detailed PR4 evidence: [`docs/evidence/pr4/`](../evidence/pr4/)
- Repository: https://github.com/mason5052/secure-model-delegation
