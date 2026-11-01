# aethon Desktop Installation

## Install the Mac test build

The desktop product is named `aethon`. Secure Model Delegation is its information-policy and model-routing component; the research paper and historical evaluator retain their existing names.

Requirements:

- An Apple Silicon Mac running macOS 15 or later.
- Free disk space for the application, the selected model weights, and model caches.
- Internet access to browse or download models. Previously downloaded compatible models can process requests locally without an external AI API connection.

Open `aethon-arm64.dmg`, drag `aethon.app` to Applications, and open aethon from Applications, Finder, or the Dock. The app includes its desktop shell, Python service, agent engine, model engines, and local document renderer. End users do not install Python, Node, Bun, Ollama, or Microsoft Office, and do not keep a terminal or separate browser running.

This first distribution is an ad-hoc-signed development test build. It is not Developer ID signed or notarized. Use its supplied checksum and package manifest to identify the exact artifact. Public distribution with Apple's standard Developer ID and notarization process is separate work. This guide does not require disabling macOS security settings.

## First session

1. Open Models. Choose GGUF or MLX, search the live Hugging Face catalog, and inspect a repository and its license. No model is bundled or selected automatically.
2. Select a variant or repository and download it. Downloading and activation are separate actions. Choose Use to run the model's local checks and activate it. Unload releases the active model from memory while retaining its downloaded files. Model architecture, memory requirements, tool support, and structured-output behavior vary.
3. Open Policy. Write your information rules, review the locally interpreted clauses, and activate the policy revision. A draft does not replace the active policy until activation.
4. Create a project or open a folder. Start a session and submit a task. Review each proposed file modification or command before approving it once. Denied operations do not execute.
5. Optionally configure OpenAI, Anthropic, or your own OpenAI-compatible endpoint in Connections. API keys are held in memory and must be entered again after the app restarts. A model subscription or another application's sign-in is not an API credential.

A configured external model is an available policy destination, not an instruction to send every request to it. Information rules and the local controller determine whether a request stays local, is transformed for external use, is declined, or needs clarification. Local model capability estimates are advisory and can be wrong.

## Workspace tools

- Sessions support renaming, pinning, archiving, deletion, export, branching, tabs, and a reference split pane. Tasks can continue while another session is selected.
- The file editor opens project files and shows proposed changes for approval. File writes include the original file hash; a changed file requires a new review.
- Terminal commands run in the selected project after a one-time approval. They use the tools actually available on that Mac. Installing every programming language or project dependency is not part of the application bundle.
- The document workshop creates DOCX, XLSX, PPTX, Markdown, HTML, CSV, and plain-text files. Its structure editor exposes supported paragraphs, tables, sheets, cells, formulas, and slide text. It is not a complete Word, Excel, or PowerPoint layout editor. LibreOffice renders supported Office files locally for PDF preview; inspect the resulting layout before sharing a file.
- Canvas embeds a locally bundled Excalidraw editor. Drawings can be opened and exported as editable `.excalidraw`, PNG, or SVG files. Drawings are not sent to a model automatically.
- Web reads public pages and can connect a user-selected public SearXNG JSON endpoint. Page requests and search queries are subject to the information policy.
- Skills exposes reusable SKILL.md instructions for inspection before enabling them. MCP servers are added explicitly; discovering or executing their tools requires the applicable review and policy checks.
- Local dictation requires a separately selected speech model. Search and download that model in Extensions, record a short clip or choose a PCM WAV file, and review the transcription before using it. Read aloud uses installed macOS voices and includes a stop control.

## Local storage and observation

Project files and saved content remain in the application's selected local directories. Metadata and settings are stored outside the app bundle. Existing Secure Model Delegation application data is retained through the product rename.

Conversation-body storage is opt-in. Metadata-only sessions cannot restore their previous text after the app closes; the interface identifies that missing context. Disabling project content storage removes its saved conversation bodies after confirmation. Project-record deletion preserves project files.

Activity distinguishes saved request records from the current app session's agent calls. Inspect the route, policy clauses, inspection reliability, and any body passed to a provider adapter. An adapter record is not independent proof of network receipt or semantic confidentiality.

Model-boundary checks include the complete supported request envelope and tool results. Supervised shell execution and third-party MCP processes are not operating-system sandboxes. Do not interpret a model gateway as preventing arbitrary networking by a command you approve.

## Rebuild from source

Developers need an Apple Silicon Mac, Python 3.12, Node/npm, and the macOS build tools. The pinned MLX wheel targets Python 3.12 and macOS 15 ARM64. These are build-machine requirements, not end-user installation steps. Build only from the application repository; do not copy private workspace data or model weights into the bundle.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r desktop/requirements-runtime.lock -r desktop/requirements-build.txt
.venv/bin/python -m pip install -e . --no-deps
npm ci
npm --prefix frontend ci
npm --prefix frontend run build
npm run test:desktop
node frontend/ui-smoke.mjs
.venv/bin/python -m unittest discover -s tests -p 'test_app_*.py' -v
```

The drawing module is rebuilt from `frontend/package-lock.json`. The PDF.js renderer is also bundled locally. Generated viewer assets and notices are included recursively in the Python service.

Prepare the separate MLX environment from the actual resolved build lock:

```bash
python3.12 -m venv .venv-mlx
.venv-mlx/bin/python -m pip install -r desktop/requirements-mlx.lock
```

`desktop/requirements-mlx.txt` records the intended oMLX 0.7.3 seed and macOS 15-compatible wheels. `desktop/requirements-mlx.lock` records the actual resolved versions, source commits, and MLX wheel URLs used for the helper. `desktop/requirements-runtime.lock` pins the application service environment, and `desktop/requirements-build.txt` pins packaging tools. Keep these files aligned when intentionally updating dependencies.

The application uses a separate frozen helper so MLX dependencies do not need to be installed on the user's Mac. Custom Metal kernels, when included, are compiled on the build machine; they are not compiled on first launch.

Prepare a verified public Ollama engine directory containing its executable, libraries, and `runtime.json` receipt. It must not contain model weights or user configuration. Then build the complete distribution:

```bash
.venv/bin/python scripts/build_desktop.py \
  --ollama-dir /absolute/path/to/verified-ollama-engine \
  --mlx-python "$PWD/.venv-mlx/bin/python" \
  --libreoffice
.venv/bin/python scripts/package_desktop.py
```

The build script verifies pinned public download digests, freezes the Python services, and stages the bundled engines. The packaging script creates the application and compressed DMG, applies an ad-hoc signature, verifies the image, and writes build/package manifests. Keep these manifests with the delivered artifact. Run the packaged application with a fresh, isolated data directory and report actual model/device/provider checks separately from automated tests.

The source build does not confer Developer ID signing or notarization. A future public release must use the project's own Apple signing identity. Bionic code, binaries, assets, and private analysis output are not inputs to this build.
