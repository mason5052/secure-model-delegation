# aethon Desktop Validation

Validation date: October 31, 2026, America/New_York.

## What this validates

This is a software preview of aethon, with Secure Model Delegation as its policy and model-routing component. It does not replace the preserved research evaluator, change its datasets or expected labels, establish independent policy accuracy, or add new paper evaluation results.

The test host is an Apple Silicon Mac with 16 GB of unified memory and macOS 27.2. The product targets macOS 15 and later. The MLX build explicitly selects the official macOS 15 wheels instead of the newer-OS wheels chosen automatically on this host. Native deployment headers are checked; physical execution on macOS 15 has not been performed.

## Automated checks

The final source suite passed 168 Python tests and 8 desktop JavaScript tests. The frontend smoke, script syntax, whitespace and preserved-source comparisons also passed.

- The Python unit/integration suite covers the existing application and research tests, project retention, missing-history disclosure, fork/search, one-time approvals, stale-file rejection, document structure operations, model adapters, and gateway authentication.
- Desktop lifecycle tests cover private environment filtering, readiness, owned-process shutdown, data-directory compatibility, and native API-key cancellation/transport. Keys are not returned through the renderer bridge.
- The frontend smoke test covers navigation, project/session setup, explicit edit approval, document controls, MLX discovery controls, and the desktop provider configuration interface.
- A controlled HTTP interruption test retains an incomplete model-weight file, resumes from its exact byte offset with Range, and compares the final SHA-256 with the complete source. Disk-space rejection occurs before transfer.
- Source comparison confirms no change to the research controller, benchmark packages, policies, datasets, labels, or manuscript directories from the pre-desktop application commit.

## Actual local execution

| Check | Observed result |
| --- | --- |
| GGUF model and agent | Qwen3 4B read a synthetic README with the real file tool and completed a final answer containing Cedar. Two local model calls; approximately 58.5 seconds on this host. |
| MLX model selection | A separately selected SmolLM2 135M MLX model downloaded, activated, and produced an actual local response. This small model did not provide reliable structured policy inspection; external delegation remained disabled when inspection failed. |
| Speech | A separately selected Whisper Tiny English 4-bit MLX speech model transcribed locally generated synthetic speech. Returned text included 'verification word is cedar.' No microphone recording or private speech was used. |
| Download control | A public MLX model download was paused and resumed to completion through the application API. Exact partial-file byte resumption was separately verified by the controlled HTTP test. |
| Files and commands | Browser-driven file/document proposals remained pending until approval. An approved synthetic command returned Cedar; rejected or unapproved proposals did not execute. |
| Documents | DOCX, XLSX, PPTX and PDF creation/inspection passed. The bundled LibreOffice converted a synthetic DOCX to PDF. The locally bundled PDF.js viewer visibly rendered its title, paragraph and table. |
| Drawing | The locally bundled Excalidraw editor opened without a CDN dependency. |
| Outbound model content | A mock provider receiver received the same JSON body recorded by the adapter; an email in an earlier synthetic turn was removed. This is a controlled receiver test, not a live OpenAI/Anthropic transaction or a complete semantic-leak review. |
| Agent permissions | The actual packaged OpenCode engine completed read and repeated write workflows using a controlled synthetic model. Each write required a distinct one-time approval. The target file was absent before approval and matched expected bytes afterward. |
| Project boundaries | Actual OpenCode probes rejected outside and symlink read/edit paths. Controlled recursive list/glob/grep tools excluded symlink content outside the selected root. Supervised arbitrary commands remain outside an operating-system sandbox. |
| Host prerequisites | The packaged agent and bundled MLX server started with a system-only PATH, without a host Node, Bun or Python command. This is an isolated-environment check on the existing test Mac, not a separate clean-machine trial. |

The actual local-model test and controlled-model protocol tests are separate evidence. A controlled model returning a tool call does not establish the quality of an arbitrary downloaded model.

Local-only agent calls without restrictive local-processing clauses use pattern checks rather than a semantic model inspection. Their audit explicitly records that distinction. External routes require validated inspection of the complete supported envelope; uncertain or failed inspection does not authorize external transmission.

## Reference analysis and limits

REA 6.8.0 is installed with its supported Node runtime and connected to Codex. An actual Codex REA tool call inspected the installed reference app. Limited selected-source analysis and its coverage are documented in [reference-audit.md](reference-audit.md). A fresh-profile Bionic runtime comparison did not complete because its existing-instance guard rejected startup; feature parity is not claimed as empirically established.

Raw REA output, Bionic implementation files, original application assets, credentials, private work conversations and local test profiles are excluded from this repository and the distribution.

## Distribution state

The first distribution is an ad-hoc-signed, unnotarized development test build. Its package manifest and checksum identify the delivered DMG. It includes original aethon artwork, application/runtime code, and third-party notices. It includes no selected chat or speech model checkpoints; small auxiliary file-format classifier assets are listed separately in the package manifest.

The final macOS 15-targeted bundled MLX helper also completed actual local speech inference on the test host after the wheel replacement. This confirms inference with the delivered native library selection, while the physical macOS 15 coverage limitation above still applies.

The final DMG passed image checksum verification and strict signature verification of the app inside the read-only image. A copy made only from that image launched with a system-only PATH and fresh profile, initialized its UI and local engine with no selected model, and stopped its owned backend/engine processes on quit. The first two image attempts were discarded after incomplete-copy and post-signing Finder-metadata failures; the packaging script now validates the image contents before writing a success manifest.

Delivered DMG SHA-256:

```text
4f368c731a824d13d40a46052b84b47a39af36214d3fd2459c923c5d6a15bb38  aethon-arm64.dmg
```

Real paid-provider calls, independent human policy adjudication, a complete semantic confidentiality review, and external answer-quality evaluation were not performed. Model and tool compatibility is checked per model and workflow, rather than asserted for every open model or MCP server.
