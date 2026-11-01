# Desktop reference audit

Date: 2026-10-31

This audit uses the installed Bionic 1.1.10+8 application and the vendor's public
documentation to define user-visible workflow requirements for Secure Model
Delegation. Artifact inspection, documented features, and observed runtime
behavior have different evidence states below.

## Verified artifact and analysis tools

- The installed application identifies itself as Bionic 1.1.10+8, bundle
  identifier `ai.elementlabs.bionic`, with an arm64 executable and Electron
  Framework. Its package metadata identifies the main JavaScript entry.
- REA 6.8.0 was invoked through its installed CLI. A separate local MCP client
  connected to the same installed server, listed 229 tools, and successfully
  called `inspect_desktop_application`. The active Codex session subsequently
  registered the REA tools and independently completed that inspection too.
- Desktop inspection examined 2,056 directory entries, probed 21 files, and
  read 1,584 header bytes. The directory identity covers retained metadata and
  read ranges; it is not a hash of every application's file contents.
- Selected JavaScript inspection read `package.json` and two preload files:
  857,969 text bytes and two parsed JavaScript sources, with zero parse failures.
  It left 699 inventoried files outside source-analysis scope.
- Semantic coverage was explicitly partial. The selected files did not yield
  resolved Electron IPC pairings in the analyzer. This is an unresolved static
  analysis result, not evidence that the application lacks IPC or those features.
- Electron fuse inspection observed enabled Node Inspector and RunAsNode fuses.
  Fuse declarations establish available launch mechanisms, not actual execution.

Canonical reference identifiers:

| Observation | REA Evidence identifier |
| --- | --- |
| Desktop inventory | `ev_a306d36d9b46b62604b90c2707ba745291a51c054d1229aa017b9492e9c005a4` |
| Active Codex inspection summary | `ev_2ed7fcb7de8b01566bac6a8d814b4b90ecbdea12fa7f8fbf66207c9c0ff5bbba` |
| Selected JavaScript application | `ev_2e44839db9e79638342b35031ce3373e6ab7020c4b202297b7a33a00eb62f24e` |
| Electron fuses | `ev_765b3fd04db1fcc85a0e7aaed8d0c528411e79aabc8fe1da48f99fa6ce897f2e` |

Complete analysis records remain in a private temporary audit directory. This
document records sanitized observations and requirements for independent code.

## Documented user workflows

These are vendor-documented capabilities, not claims that each was exercised
by the artifact inspection.

| Workflow | Documented behavior | Primary source |
| --- | --- | --- |
| Models | Search, choose format and variant, download, pause/resume/cancel/retry, then select a downloaded model. Device-fit information helps selection. | [Local models](https://lmstudio.ai/docs/bionic/models/download-local-models) |
| Execution location | Sessions can use local models, vendor cloud models, or another device through LM Link. | [Model locations](https://lmstudio.ai/docs/bionic/models) |
| Projects and sessions | Shared project files, independent task sessions, pinned/renamed/archived sessions, tabs, splits, forks, and background work. | [Projects and sessions](https://lmstudio.ai/docs/bionic/projects-and-sessions) |
| Code tasks | Search and edit a selected folder, run shell commands and tests, inspect Git changes, and investigate through sub-sessions. | [Coding](https://lmstudio.ai/docs/bionic/agent/code-project) |
| Documents | Create and revise documents, spreadsheets, presentations, PDFs, images, and text; previews and editing depend on format. Web search is optional. | [Working with documents](https://lmstudio.ai/docs/bionic/agent/work-project) |
| Skills | Standard `SKILL.md` instructions, explicit references, creation and installation, and selectively enabled compatible skills from other apps. | [Skills](https://lmstudio.ai/docs/bionic/agent/skills) |
| Voice input | Local speech transcription using Voxtral, with optional automatic model loading. | [Voice input](https://lmstudio.ai/docs/bionic/voice-input) |
| Additional desktop tools | Public in-app terminal, runtime selection, Excalidraw previews, model catalog extensions, and offline read-aloud voices. | [1.1.10 release](https://lmstudio.ai/changelog/bionic-v1.1.10) |
| Integrations and continuity | On-demand MCP tool discovery, session references, CSV/TSV previews, and cross-session attachments. | [1.1.9 release](https://lmstudio.ai/changelog/bionic-v1.1.9) |
| Office previews and APIs | In-app Office/HTML previews and decision-model management/API endpoints. | [1.1.8 release](https://lmstudio.ai/changelog/bionic-v1.1.8) |

Public evidence reviewed here does not establish the precise extent of autonomous
browser actions or the backend used for generic image generation. These remain
separate acceptance questions rather than inferred requirements from filenames.

## Bounded runtime attempt

One REA-owned startup attempt used a temporary HOME and user-data argument,
with a wrapper intended to isolate standard Electron paths and block common
external HTTP calls. No account login, model download, or personal conversation
was part of the requested scenario.

The packaged application reported that another instance was already running and
exited before a window or model-catalog interaction could be observed. The wrapper
and full profile isolation therefore were not independently confirmed. The REA
launch record reports exit code zero and temporary-directory cleanup. The existing
instance was left running. The attempt was not repeated.

This is a failed startup probe, not a completed behavioral comparison. It supports
no claims about model download reliability, voice accuracy, document rendering,
agent tool approvals, or Secure Model Delegation enforcement in Bionic.

## Independent implementation choices

Secure Model Delegation uses its own policy controller and provider gateway.
Project files, document text, tool outputs, and voice transcripts must enter that
gateway before external model delegation. Agent file edits and shell commands
require a new one-time user approval. An approved shell command or external MCP
program runs with the user's account permissions; folder selection is not an
operating-system sandbox.

A first-party agent plugin checks file-tool paths and supplies bounded folder
listing, glob, and literal-text search that skip symbolic links and control
directories. Recursive searches also skip common dependency folders. Its loading
is checked before agent sessions start. These application checks are separate
from the broader permissions of a user-approved shell command.

Compatible model choices are exposed through runtime adapters and explicit local
compatibility checks. A public model listing alone does not establish support for
every architecture. Model weights are selected and downloaded by the user rather
than fixed inside the installer.

The proposed remote-device feature is an authenticated endpoint for user-owned
servers. LM Link protocol compatibility is unverified. External cloud use is
through user-supplied API keys; vendor credits, subscriptions, and organization
billing require a separate service scope.

Useful independent components include MIT-licensed
[MLX-Audio](https://github.com/Blaizzy/mlx-audio) for selected Apple Silicon speech
models, [whisper.cpp](https://github.com/ggml-org/whisper.cpp) for local Whisper
transcription, and [Excalidraw](https://github.com/excalidraw/excalidraw) for an
editable drawing format. Engine licensing and individual model-weight licensing
are evaluated separately.

Structured document creation can use python-docx, openpyxl, and python-pptx.
Those libraries alone do not establish Office rendering fidelity. In particular,
[openpyxl does not evaluate formulas](https://openpyxl.readthedocs.io/en/stable/simple_formulae.html).
Local PDF rendering uses the separately packaged LibreOffice engine and requires
rendered-output checks before a document is described as visually verified.
