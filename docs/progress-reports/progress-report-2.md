> Public-safe copy of the submitted CS6727 progress report. Course-private attachments and raw runtime artifacts are not included. Company-specific names, if any, are generalized.
# Progress Report 2: Secure Model Delegation

Section: CS

Project Title: Secure Model Delegation: A Policy-Bounded Controller for Local-to-Cloud LLM Fallback

Name: Junkuk Kim

Due Date: 2026-06-14 11:59 PM ET

## Problem Statement

Many enterprise AI systems are moving toward mixed model environments rather than a single model running in one place. In a realistic deployment, an assistant may first operate inside a local or private environment, but may then need to delegate selected difficult requests to a stronger hosted model such as OpenAI or Anthropic Claude. I am studying this local/private-to-cloud fallback path because it creates a security boundary that can be missed if the system only focuses on model capability.

The request that is delegated to the external model may contain more than the user's visible question. It may include retrieved context, logs, support tickets, code snippets, configuration text, incident notes, internal agent instructions, or other enterprise context. Those materials may contain API keys, authentication tokens, configuration secrets, personal information, proprietary code, internal hostnames, private IP addresses, incident details, or business confidential data. If the fallback path sends that material to an external model without a mandatory policy control point, the fallback mechanism can become a sensitive-data exposure path.

My project focuses on this boundary as a technical security problem. The goal is not to create a new general-purpose PII detector or a replacement for enterprise DLP. The goal is to design and evaluate a policy-bounded model delegation controller that decides whether a request should stay local, be denied, require clarification, be summarized locally, or be sanitized and delegated to a specific external model target.

The concrete test environment will use my personal local machine as the trusted local environment for the Python gateway, local handling path, payload capture, and benchmark runner. The primary less-trusted target for evaluation will be a simulated external endpoint that captures exactly what would have been sent outside the trusted boundary. OpenAI and Anthropic Claude will remain explicit target-policy profiles in the design, but real API calls will be optional, small-scale, and limited to sanitized synthetic payloads if they are used at all. The local side may use a local model adapter or a deterministic local-summary stub for reproducible tests, but the local model will not be the security authority. I will use only synthetic enterprise-style data, synthetic secrets, and sanitized payloads. I will not use real proprietary company data, customer information, production logs, internal documents, or real credentials.

## Solution Statement

The solution is a policy-bounded gateway for local/private-to-cloud LLM fallback. In this report, the gateway is the end-to-end boundary system, while the controller is the decision core inside the gateway. I am now framing the core contribution as **Policy-Bounded Model Delegation Control and Evaluation**. This means the important research object is not only whether sensitive text can be detected, but how the controller makes and evaluates delegation decisions before any text leaves the trusted boundary.

The gateway will separate two types of decisions that should not be mixed together. First, mandatory disclosure control will be handled by hard target-specific policy rules. These rules decide which sensitive classes are never allowed to leave the trusted environment, which classes may be transformed, and which classes may be delegated to a simulated OpenAI or Claude target profile. Second, routing and utility estimation will be handled by a lightweight ML-assisted routing layer. The first version of this ML-assisted layer will use labeled synthetic cases and gateway features such as detected sensitive classes, severity level, task type, prompt length, code/log presence, injection indicators, and estimated local feasibility. It may recommend a route only after the hard policy gate has removed or blocked policy-denied content.

The planned architecture is:

1. Request assembly and normalization: build one canonical request object from user prompt, retrieved context, tool output, logs, and metadata, then normalize text formatting so later detectors see a consistent input.
2. Evidence providers: collect evidence from detector baselines and custom rules, including regex rules, Privacy Filter or Presidio-style PII detection, TruffleHog-style secret detection, internal hostname or private IP detection, configuration-file cues, prompt-injection cues, and system-prompt or internal-instruction cues.
3. Policy-bounded model delegation controller: first apply hard disclosure policy, then use ML-assisted routing only for policy-allowed choices, resolve conflicts across detected classes, apply OpenAI-specific and Claude-specific disclosure rules, and decide whether the request stays local, is denied, needs clarification, is summarized locally, or is sanitized and delegated.
4. Egress guard and sanitizer: remove, replace, generalize, or summarize sensitive spans before any payload crosses the trusted boundary.
5. Delegation wrappers, response verifier, and audit log: send approved payloads to the simulated external endpoint, optionally support sanitized-only OpenAI or Claude API smoke tests, scan returned text for unexpected sensitive echoes or policy violations before it is returned to the user, and record a decision trace without storing raw secrets.
6. Evaluation harness: compare the policy-bounded gateway against baselines such as no gateway, regex-only sanitization, detector-only masking, and optional LLM-as-router behavior.

This design keeps the security authority outside the LLM. A local LLM or ML classifier may help estimate difficulty or utility, but it will not be allowed to decide that a denied API key, private code block, or internal system prompt is safe to send. The project does not claim full semantic privacy, cryptographic privacy, a new PII detector, or a replacement for enterprise DLP. The main security claim remains intentionally bounded: under complete mediation and correct sensitive-span classification, policy-denied spans should not appear in delegated payloads for the simulated OpenAI or Claude target profiles in their original form.

## Completed Tasks (Last 2 Weeks)

| No. | Item |
| --- | --- |
| 1 | Consolidated the PR1 project direction into a narrower technical security project: policy-bounded model delegation control for text-only local/private-to-cloud fallback. |
| 2 | Converted the project concept into concrete technical artifacts: a controller-centered solution approach, related-work comparison, policy matrix, benchmark schema, architecture figure, and evaluation plan. |
| 3 | Locked the project differentiation so the project is not framed as a new PII detector, generic DLP system, or ordinary privacy masking gateway. |
| 4 | Completed a related-work comparison matrix covering OpenAI Privacy Filter, Microsoft Presidio, TruffleHog, traditional DLP, Portcullis, PRISM, PPRoute, AgentDojo, prompt-injection work, and egress-leakage work. |
| 5 | Refined the sensitive-data taxonomy. The taxonomy now explicitly includes API keys, authentication tokens, configuration files, system prompts, internal agent instructions, proprietary code, internal infrastructure, incident details, business confidential data, regulated data, benign public context, and prompt-injection or policy-bypass text. |
| 6 | Expanded the first-prototype design to make API keys, authentication tokens, configuration files, false-positive and false-negative risk, benchmark sizing, DLP differentiation, the simulated external endpoint, and OpenAI/Claude target-policy profiles explicit. |
| 7 | Designed the second version of the gateway architecture around a controller-centered model: request assembly and normalization, evidence providers, policy-bounded controller, egress guard, delegation wrappers, response verifier, audit log, and evaluation harness. |
| 8 | Drafted Policy Matrix v1 with sensitive classes, examples, detector or evidence sources, OpenAI action, Claude action, default route, and notes. |
| 9 | Drafted Benchmark Schema v1 with fields for case ID, category, input request, sensitive spans, expected policy action, expected route, expected delegated payload, leakage oracle, utility goal, attack type, and notes. |
| 10 | Created the first set of synthetic benchmark case templates B001 through B016 covering API keys, authentication tokens, configuration files, PII, internal hostnames, private IPs, system prompt leakage, private code, incident notes, business confidential data, regulated-data stress tests, benign requests, prompt injection, obfuscated secrets, clarification cases, and utility-loss cases. |
| 11 | Defined the initial evaluation plan and metrics: direct leakage rate, policy and routing accuracy, span detection precision and recall, utility preservation, latency overhead, false positives, false negatives, and adversarial bypass rate. |
| 12 | Organized architecture, policy, benchmark, and related-work artifacts so the project has supporting evidence beyond narrative planning. |
| 13 | Adjusted the implementation schedule after spending this cycle on research, architecture, policy, and benchmark design. The prototype implementation is now planned for W5 and W6, and PR3 will need to include executable code and early baseline results. |

## Tasks for the Next Project Report

| No. | Item |
| --- | --- |
| 1 | Create the first prototype repository structure with modules for request assembly, evidence providers, policy controller, router, sanitizer, simulated external endpoint adapter, optional OpenAI/Claude adapter stubs, response verifier, audit logger, and benchmark runner. |
| 2 | Implement a first JSON or YAML policy file that encodes target-specific disclosure rules for OpenAI and Claude. |
| 3 | Implement the first detector baselines for emails, phone numbers, private IP addresses, hostnames, API-key-like strings, bearer tokens, configuration-file secrets, and prompt-injection phrases. |
| 4 | Implement a minimal policy controller that can produce the route labels `local_process`, `deny`, `ask_clarification`, `local_summary`, `delegate_openai_sanitized`, and `delegate_claude_sanitized`. |
| 5 | Convert the initial B001 to B016 case templates into executable benchmark records. |
| 6 | Expand the synthetic benchmark toward at least 30 high-quality cases before PR3, prioritizing diversity and correctness over raw count. |
| 7 | Add payload capture before simulated or optional real external calls so delegated-payload leakage can be measured exactly. |
| 8 | Build the simulated external endpoint first, with optional OpenAI and Claude adapter stubs reserved for sanitized-only utility smoke tests if cost and time allow. |
| 9 | Draft the formal threat model and the complete mediation assumption for the final report. |
| 10 | Run the first baseline comparison: no gateway, regex-only sanitizer, detector-only masking, and policy-bounded controller. |

## Questions I Have or Issues I Am Running Into

These are decision points rather than blockers. My current working assumptions are listed with each issue so I can validate or adjust them during PR3 implementation.

| Question or Issue | Current Working Assumption |
| --- | --- |
| Is the controller-centered framing clear enough for a technical security practicum: hard policy first, ML-assisted routing second, and target-specific OpenAI/Claude delegation-profile decisions? | Yes. I will keep the policy-bounded controller as the main artifact and evaluate it through delegated-payload leakage, routing correctness, and utility preservation. |
| Is it acceptable to reuse tools such as Privacy Filter, Presidio, or TruffleHog-style detectors as evidence providers or baselines? | Yes, if they are clearly presented as baselines or evidence providers rather than the main contribution. The project contribution remains delegation control and evaluation. |
| Should the benchmark target 80 to 120 cases by the final report, or would a smaller but more carefully labeled benchmark be stronger? | I will prioritize quality first: about 30 executable cases by PR3, then expand toward 80 to 120 cases only if labels and expected routes remain reliable. |
| Would one or two informal stakeholder conversations improve the final evaluation, or should evaluation remain primarily technical and benchmark-based? | Stakeholder input may be useful as supporting context, but the primary evaluation will remain technical and benchmark-based for this semester. |
| For proprietary code and business confidential content, should the default first-prototype behavior be deny, local summary only, or sanitized delegation with strict generalization? | The first-prototype default will be deny or local summary only. Sanitized delegation will be tested later only for carefully generalized synthetic examples. |
| How much should the OpenAI and Claude disclosure policies differ in the first implementation? | I will keep high-risk disclosure rules equally conservative for both providers, but I will make target-specific routing explicit for allowed or sanitized tasks, such as technical debugging versus long-form summarization. |

## Methodology Paragraph Summary

My methodology is to treat local/private-to-cloud LLM fallback as a bounded security-engineering problem. I will first define the threat model, assets, trust boundary, adversary goals, non-goals, and complete mediation assumption. I will then compare related work to identify what existing tools solve and what remains specific to model delegation. Next, I will define a target-specific policy matrix for OpenAI and Claude profiles, build a Python gateway prototype, and create a synthetic enterprise benchmark with labeled sensitive spans and expected routes. The prototype will use a simulated external endpoint for the primary leakage evaluation so I can measure exactly what would cross the trusted boundary. The prototype will compare multiple baselines against the policy-bounded controller. The final evaluation will measure whether denied spans appear in delegated payloads, whether routing decisions match policy expectations, how much utility remains after sanitization, how often valid requests are overblocked, how often risky requests slip through, how much latency is added, and how well prompt-injection or policy-bypass attempts are resisted. The first implementation milestone has shifted from PR2 to PR3 because I used this reporting cycle to make the deployment model, related-work comparison, policy matrix, and benchmark design concrete before coding.

## Timeline

Schedule note: Canvas lists the final report due date as 2026-08-02 at 11:59 PM ET. Ed guidance says the week beginning 2026-08-03 is the final exam and grading period, and this course has no final exam. Therefore, I am treating 2026-08-02 as the hard completion date for all project work.

| Week # | Description of Task | Status |
| --- | --- | --- |
| W1 (May 18 to May 24) | Define initial project problem, motivation, expected deliverables, and course workspace. | Completed |
| W2 (May 25 to May 31) | Respond to instructor feedback by making deployment, policy, benchmark, and evaluation plans concrete. | Completed |
| W3 (Jun 1 to Jun 7) | Analyze technical feedback from the first video-feedback cycle and update sensitive-data categories, target assumptions, and benchmark risks. | Completed |
| W3 (Jun 1 to Jun 7) | Compare the project against DLP, privacy filters, privacy gateways, privacy-aware routing, and prompt-injection benchmarks. | Completed |
| W4 (Jun 8 to Jun 14) | Lock the project contribution as Policy-Bounded Model Delegation Control and Evaluation. | Completed |
| W4 (Jun 8 to Jun 14) | Draft architecture v2, policy matrix v1, benchmark schema v1, initial synthetic cases, evaluation metrics, and PR2 report. | Completed |
| W4 (Jun 8 to Jun 14) | Document the schedule adjustment: prototype implementation moved to W5-W6 so the design, policy, benchmark, and related-work foundation can be made concrete first. | Completed |
| W5 (Jun 15 to Jun 21) | Build the prototype skeleton and implement request assembly, normalization, detector baseline interfaces, and the initial policy controller. | Planned |
| W5 (Jun 15 to Jun 21) | Encode OpenAI and Claude target policies in JSON or YAML and add audit-log structure without raw secret storage. | Planned |
| W6 (Jun 22 to Jun 28) | Implement sanitizer, route decision output, payload capture, simulated external endpoint, optional OpenAI/Claude adapter stubs, and the first executable benchmark cases. | Planned |
| W6 (Jun 22 to Jun 28) | Run early baseline tests and include initial evidence in PR3. | Planned |
| W7 (Jun 29 to Jul 5) | Expand benchmark to about 60 cases, including mixed-context, obfuscated-secret, prompt-injection, and utility-loss examples. | Planned |
| W7 (Jun 29 to Jul 5) | Refine false-positive and false-negative analysis and update threat model based on early failures. | Planned |
| W8 (Jul 6 to Jul 12) | Expand benchmark toward 80 to 120 cases if feasible and run full controller evaluation for PR4. | Planned |
| W8 (Jul 6 to Jul 12) | Freeze final report outline and draft limitations, related work, and methodology sections. | Planned |
| W9 (Jul 13 to Jul 19) | Analyze direct leakage, routing correctness, utility preservation, latency, and adversarial bypass results. | Planned |
| W9 (Jul 13 to Jul 19) | Revise policy matrix and prototype based on evaluation findings. | Planned |
| W10 (Jul 20 to Jul 26) | Prepare final presentation, final evaluation tables, architecture figures, and draft final report body. | Planned |
| W11 (Jul 27 to Aug 2) | Finalize report, verify citations and artifacts, complete final edits, and submit final report by 2026-08-02 11:59 PM ET. | Planned |

## Evaluation

The evaluation will be implemented around captured delegated payloads, synthetic benchmark labels, and baseline comparisons. The main unit of evaluation is not only whether a detector found a span, but whether the gateway made the correct delegation decision and prevented policy-denied data from leaving the trusted boundary.

| Metric | Measurement | Why It Matters |
| --- | --- | --- |
| Direct leakage rate | Number of policy-denied spans found in delegated payloads divided by total policy-denied spans | Measures whether the gateway prevents direct leakage to the less-trusted target |
| Policy decision accuracy | Correct allow, transform, summarize, or deny action divided by total labeled decisions | Measures whether the policy matrix is applied correctly |
| Routing correctness | Correct route label divided by total benchmark cases | Measures whether the system chooses local, deny, clarification, local summary, or sanitized delegation correctly |
| Sensitive-span precision and recall | Detector output compared against labeled synthetic spans | Shows whether evidence providers miss or over-identify sensitive data |
| False positive rate | Benign content incorrectly treated as sensitive or blocked | Measures unnecessary utility loss |
| False negative rate | Sensitive content missed by detectors or policy | Measures residual leakage risk |
| Utility preservation | Human rubric and optional LLM-as-judge comparison of task usefulness after sanitization | Measures whether the sanitized request can still accomplish the task |
| Latency overhead | Time for detection, policy evaluation, routing, sanitization, and payload capture | Measures practical deployment cost |
| Adversarial bypass rate | Prompt-injection or obfuscation cases that cause unsafe delegation | Measures robustness against manipulation |

Planned baselines:

- No gateway: send the synthetic request directly to the external target and measure what would leak.
- Regex-only sanitizer: use simple deterministic patterns as a low-cost baseline.
- Detector-only masking: use Privacy Filter, Presidio, or TruffleHog-style detection as a masking baseline if setup time allows.
- Optional LLM-as-router: compare against a model-based routing decision to observe prompt-injection and policy-override risks.
- Policy-bounded controller: hard policy first, ML-assisted routing second, with target-specific OpenAI and Claude profile actions.

## Report Outline

| Section | Planned Final Report Content |
| --- | --- |
| 1 | Introduction |
| 2 | Problem motivation: local/private-to-cloud LLM fallback as a security boundary |
| 3 | Background and related work: DLP, privacy filters, privacy gateways, privacy-aware routing, encrypted routing, prompt injection, and egress leakage |
| 4 | Threat model, assets, trust boundaries, assumptions, and non-goals |
| 5 | Deployment and test environment: personal local machine, Python gateway, local handling path, simulated external endpoint, OpenAI/Claude target-policy profiles, optional sanitized-only API smoke tests, payload capture, and synthetic data controls |
| 6 | Policy model: sensitive classes, target-specific disclosure rules, route labels, and conflict resolution |
| 7 | System design: request assembly, normalization, evidence providers, hard policy gate, ML-assisted router, egress guard, sanitizer, delegation wrappers, response verifier, and audit log |
| 8 | Prototype implementation |
| 9 | Synthetic enterprise benchmark design |
| 10 | Evaluation methodology |
| 11 | Results |
| 12 | Limitations: semantic leakage, metadata leakage, classifier misses, utility loss, and benchmark realism |
| 13 | Conclusion and future work |

## References

- OpenAI. Privacy Filter. https://github.com/openai/privacy-filter
- Microsoft. Presidio: Data protection and de-identification SDK. https://microsoft.github.io/presidio/
- Truffle Security. TruffleHog. https://github.com/trufflesecurity/trufflehog
- OWASP. Top 10 for Large Language Model Applications. https://owasp.org/www-project-top-10-for-large-language-model-applications/
- NIST. Artificial Intelligence Risk Management Framework (AI RMF 1.0), 2023. https://www.nist.gov/itl/ai-risk-management-framework
- NIST. Security and Privacy Controls for Information Systems and Organizations, SP 800-53 Rev. 5. https://csrc.nist.gov/publications/detail/sp/800-53/rev-5/final
- Debenedetti et al. AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents, NeurIPS 2024. https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html
- Zhan et al. Portcullis: A Scalable and Verifiable Privacy Gateway for Third-Party LLM Inference, AAAI 2025. https://ojs.aaai.org/index.php/AAAI/article/view/32088
- Zhan et al. PRISM: Privacy-Aware Routing for Adaptive Cloud-Edge LLM Inference via Semantic Sketch Collaboration, arXiv:2511.22788, 2025. https://arxiv.org/abs/2511.22788
- Wu et al. Privacy-Preserving LLMs Routing (PPRoute), arXiv:2604.15728, 2026. https://arxiv.org/abs/2604.15728
- Lan et al. Silent Egress: When Implicit Prompt Injection Makes LLM Agents Leak Without a Trace, arXiv:2602.22450, 2026. https://arxiv.org/abs/2602.22450
- Alizadeh et al. Simple Prompt Injection Attacks Can Leak Personal Data Observed by LLM Agents During Task Execution, arXiv:2506.01055, 2025. https://arxiv.org/abs/2506.01055

## Appendix A: Project Differentiation Lock

Secure Model Delegation is not primarily a new PII detector, generic DLP system, or privacy masking gateway. The core contribution is a policy-bounded model delegation control layer for local/private-to-cloud LLM fallback. It evaluates whether a request should stay local, be denied, require clarification, be summarized locally, or be sanitized and delegated to a simulated external target using a specific model-policy profile such as OpenAI or Claude.

Existing tools and papers address pieces of this problem, including span detection, prompt masking, privacy gateways, privacy-aware routing, encrypted routing, and prompt-injection exfiltration. This project focuses on the enterprise model-delegation boundary: before text leaves a trusted local/private environment, a policy-bounded gateway decides what must remain local, what must be denied or clarified, what can be transformed, and which external target may receive it.

## Appendix B: Related-Work Comparison Matrix

| Work or Tool | Role in This Project | Difference From This Project |
| --- | --- | --- |
| OpenAI Privacy Filter | Detector or masking baseline | Detects and masks sensitive spans, but does not make route decisions such as local, deny, clarification, local summary, or target-specific delegation |
| Microsoft Presidio | PII detector and anonymization baseline | Useful for PII spans, but not a model-delegation security boundary |
| TruffleHog | Secret detector baseline | Good for API keys and tokens, but not a delegation controller |
| Traditional DLP | Conceptual baseline | Controls data movement, but does not directly evaluate LLM fallback routing or utility after sanitization |
| Portcullis | Privacy gateway related work | Relevant privacy-gateway comparison, but this project focuses on target-specific delegation decisions and payload-level evaluation |
| PRISM | Privacy-aware cloud-edge routing related work | Related to routing, but this project keeps hard disclosure policy as the security authority |
| PPRoute | Privacy-preserving routing related work | Related to routing privacy, but this project assumes a trusted local gateway rather than cryptographic routing |
| AgentDojo and prompt-injection benchmarks | Adversarial benchmark inspiration | Useful for bypass cases, but this project measures delegated-payload leakage and policy bypass |
| Silent Egress work | Motivation for egress-level measurement | Supports measuring what actually leaves the boundary rather than only final visible model output |

## Appendix C: Gateway Architecture

Figure C1 shows the planned gateway flow. The controller is the research core: evidence providers supply signals, hard policy runs before ML-assisted routing, and simulated external delegation occurs only after egress control and sanitization. OpenAI and Claude remain target-policy profiles, while real API calls are optional sanitized-only smoke tests.

![Gateway Architecture](../assets/gateway-architecture-v5-portrait.svg)

## Appendix D: Policy Matrix v1

Target-specific policy status: in this first policy matrix, high-risk disclosure rules are intentionally conservative for both OpenAI and Claude profiles because both represent less-trusted targets outside the trusted local boundary. The first implementation will exercise these policies through a simulated external endpoint. The target-specific part is still explicit: allowed or sanitized requests can be routed differently based on task type and utility, while denied classes remain denied for both target profiles.

| Sensitive Class | Examples | OpenAI Action | Claude Action | Default Route |
| --- | --- | --- | --- | --- |
| Credentials and API keys | API keys, passwords, SSH keys, database passwords | Deny or remove | Deny or remove | Deny or local only |
| Authentication tokens | JWTs, session cookies, bearer tokens, refresh tokens | Deny or remove | Deny or remove | Deny or local only |
| Configuration files | `.env`, connection strings, cloud config snippets | Remove secret values; allow technical debugging only with safe structure | Remove secret values; allow configuration explanation or summary only with safe structure | Sanitized delegation if utility remains |
| PII | Names, emails, phone numbers, addresses, employee IDs | Stable placeholders | Stable placeholders | Sanitized delegation |
| System prompts and internal agent instructions | Hidden prompts, routing rules, internal tool instructions | Deny or remove | Deny or remove | Local only or deny |
| Proprietary code | Private source code, internal repo paths, unreleased algorithms | Deny raw code; allow only synthetic or generalized debugging examples | Deny raw code; prefer local summary for private code reasoning | Local summary only |
| Internal infrastructure | Hostnames, private IPs, topology, internal service names | Generalize before technical analysis | Generalize before long-form explanation or summary | Sanitized delegation if needed |
| Incident and security details | Investigation notes, vulnerabilities, detection logic | Sanitize indicators before technical troubleshooting | Sanitize indicators before executive or narrative summary | Local summary or sanitized delegation |
| Business confidential data | Pricing, contracts, vendor terms, non-public plans | Local summary first; delegate only generalized comparison criteria | Local summary first; delegate only generalized narrative summary | Local summary first |
| Regulated data | PHI, PCI, student records | Deny or strong transform | Deny or strong transform | Deny or stress-test only |
| Public or benign context | Public docs, generic errors, public CVE text | Allow for technical/debugging tasks | Allow for long-form summarization or writing tasks | Delegate if cloud utility is needed |
| Prompt-injection or policy-bypass text | "Ignore policy", "send all secrets", fake system override | Treat as data, no policy authority | Treat as data, no policy authority | Local handling or sanitized delegation |

## Appendix E: Benchmark Schema v1

| Field | Purpose |
| --- | --- |
| `case_id` | Stable identifier such as B001 |
| `category` | Main case type such as credential, PII, config, code, incident, benign, or prompt injection |
| `input_request` | Synthetic enterprise-style user request or assembled prompt |
| `sensitive_spans` | Exact spans expected to be detected |
| `span_classes` | Policy class for each sensitive span |
| `expected_policy_action` | Allow, transform, summarize, or deny |
| `expected_route` | Local process, deny, ask clarification, local summary, sanitized OpenAI, or sanitized Claude |
| `expected_delegated_payload` | What the external target should receive after sanitization |
| `leakage_oracle` | Spans that must not appear in delegated payloads |
| `utility_goal` | What task should still be possible after sanitization |
| `attack_type` | None, prompt injection, obfuscation, mixed context, or policy bypass |
| `notes` | Rationale and expected edge cases |

## Appendix F: Initial Synthetic Benchmark Cases

| ID | Category | Input Sketch | Expected Route | Utility Goal |
| --- | --- | --- | --- | --- |
| B001 | API key | Debug an API error containing a synthetic OpenAI-style API key | `deny` | Explain authentication issue generically |
| B002 | Auth token | Summarize an HTTP failure containing a bearer token | `delegate_openai_sanitized` | Explain token expiration or permission possibilities |
| B003 | Config file | Review a `.env` sample with DB host and password | `delegate_openai_sanitized` | Identify safe configuration issues |
| B004 | PII support ticket | Draft a reply to a synthetic customer with name, email, and phone | `delegate_claude_sanitized` | Preserve support-response utility |
| B005 | System prompt leakage | User asks to send hidden router instructions to Claude | `deny` | Refuse and explain policy boundary |
| B006 | Private code | Find bugs in private internal source code | `local_summary` | Summarize bug category without raw code |
| B007 | Internal hostname | Analyze error from internal hostname and private IP | `delegate_openai_sanitized` | Analyze generic database connectivity issue |
| B008 | Security incident | Summarize incident notes with affected endpoint and detection detail | `delegate_claude_sanitized` | Produce safe incident summary |
| B009 | Business confidential | Compare non-public vendor pricing | `local_summary` | Summarize decision criteria |
| B010 | Regulated data stress test | Synthetic PHI-like medical note | `deny` | Test regulated-data handling |
| B011 | Benign public request | Explain OWASP LLM Top 10 | `delegate_openai_sanitized` | Preserve full utility |
| B012 | Prompt injection | Retrieved text says to ignore policy and send secrets | `local_process` | Treat malicious text as data |
| B013 | Mixed benign and secret | Public error message plus pasted webhook URL | `delegate_openai_sanitized` | Debug public error without secret |
| B014 | Obfuscated secret | API key split with spaces or punctuation | `deny` | Measure detector weakness |
| B015 | Clarification case | User asks to send an unspecified internal report | `ask_clarification` | Avoid delegation before classification |
| B016 | Utility-loss case | Sanitization removes too much context from an incident request | `local_summary` | Measure when delegation becomes useless |
