# PRD: Frictionless iTE Install And First Run

## Summary

iTE should be installable and usable with the fewest possible user-managed dependencies.

The target experience is:

```bash
curl -fsSL https://ite.kiishi.space/install.sh | sh
ite
```

After that, the user should reach a working iTE session without manually installing Python, `pipx`, Ollama, pulling a model, entering an API key, or editing config.

`pipx install ite-agent` remains supported for terminal-first Python users, contributors, and CI, but it should no longer be the primary path for a new user who simply wants iTE to work.

## Problem

iTE currently exposes too much setup complexity to users.

A new user may need to understand and perform several separate tasks:

1. Install Python tooling or `pipx`.
2. Install iTE.
3. Launch iTE.
4. Complete onboarding.
5. Choose a model provider.
6. Learn what Ollama is.
7. Install Ollama.
8. Start Ollama.
9. Pull a model.
10. Configure iTE to use that model.

Each individual step is reasonable for an experienced developer, but the combined experience feels fragmented. A product that offers local/free models should own the local model setup rather than sending users to assemble the runtime themselves.

## Product Goal

A new user should be able to install iTE and start coding through one clear path:

1. Run the iTE installer.
2. Launch `ite`.
3. iTE prepares whatever local runtime is needed.
4. iTE opens a working chat.

The user should not need to understand Ollama, Python packaging, PATH, local servers, model pulls, base URLs, or API keys before seeing value.

## User Promise

```text
Install iTE. Run iTE. Start coding.
```

iTE may still ask for consent before installing third-party software or downloading models, but the product should make those actions feel like part of iTE setup, not separate homework.

## Guiding Principles

- Prefer a working default over a setup wizard.
- Do not pass solvable dependency work to the user.
- Ask for consent before installing software or downloading large model files.
- Keep advanced provider setup available, but make it optional.
- Preserve `pipx` and `uv` as supported install paths.
- Make every failure recoverable with a clear next action.
- Keep implementation details like “bootstrap” out of the primary user journey.

## Non-Goals

- Do not remove OpenRouter, OpenAI, or custom OpenAI-compatible provider support.
- Do not remove manual Ollama configuration for advanced users.
- Do not silently install software without explicit consent.
- Do not require `pipx`, Homebrew, Node, or `uv` for the primary installer.
- Do not build a custom inference engine in this phase.
- Do not make users pick a provider before they can try iTE.

## Current State

Current defaults in `src/ite/config/config.py`:

- `DEFAULT_BASE_URL = "http://localhost:11434/v1"`
- `DEFAULT_API_KEY = "ollama"`
- Ollama is already treated as an OpenAI-compatible local endpoint.

Current Reup first-run behavior:

- Onboarding asks for user identity/context.
- If config is incomplete, iTE opens setup.
- Setup asks the user to choose between Ollama, OpenRouter, or another provider.
- Ollama setup fills hidden defaults for base URL and API key.
- iTE does not install Ollama.
- iTE does not start Ollama.
- iTE does not pull a model.
- iTE does not verify that the selected Ollama model exists.

## Desired End State

### New User

The new user runs:

```bash
curl -fsSL https://ite.kiishi.space/install.sh | sh
ite
```

iTE handles:

- iTE runtime install/update
- local model runtime detection
- Ollama install, if missing and approved
- Ollama start, if installed but not running
- default model selection
- model download, if missing and approved
- iTE config creation
- first usable chat

### Existing iTE User

If the user already has iTE installed through `pipx`, `uv`, or a managed runtime:

- the installer must not delete or corrupt that install
- iTE should identify which executable is active
- iTE should continue to work with existing config
- local setup should only run when there is no usable model provider

### User With API Key

If the user wants OpenRouter, OpenAI, or another provider:

- they can choose that path
- local model setup is skipped
- provider setup remains available through `/setup`

### User With Ollama Already Installed

iTE should:

- detect Ollama
- start it if needed
- check for the selected/default model
- pull the model only if missing and approved
- save config automatically

## User-Facing Flows

### Primary Install Flow

```text
Installing iTE

Detected macOS arm64.
Downloading iTE...
Verifying download...
Installing to ~/.ite/bin/ite...
iTE installed.

Run `ite` to start.
```

If PATH can be updated safely:

```text
iTE installed.
Run `ite` to start.
```

If PATH cannot be updated safely:

```text
iTE installed at ~/.ite/bin/ite.

Add this to your shell profile:
export PATH="$HOME/.ite/bin:$PATH"
```

### First Run With No Provider

```text
Welcome to iTE

iTE can start with a free local model on this computer.
No API key is required.

[Continue] [Use API key instead]
```

If the user continues:

```text
Preparing iTE

Checking local model runtime...
Installing Ollama...
Starting Ollama...
Downloading local model...
Configuring iTE...
Ready.
```

Then iTE opens the chat.

### First Run With Existing Provider

```text
Welcome back

Using configured provider: <provider/model>.
```

iTE skips local model setup.

### Failure Recovery

If local setup fails:

```text
iTE could not finish local setup.

[Try again] [Use API key instead] [View details]
```

The user should never be stranded with a stack trace or vague setup failure.

## Functional Requirements

### FR1: One-Shot iTE Installer

iTE must provide a first-class installer that does not depend on `pipx`.

macOS/Linux:

```bash
curl -fsSL https://ite.kiishi.space/install.sh | sh
```

Windows:

```powershell
irm https://ite.kiishi.space/install.ps1 | iex
```

The installer must not require users to install Python, pip, `pipx`, `uv`, Node, Homebrew, or any other package manager first.

Installer responsibilities:

1. Detect OS and architecture.
2. Fetch the iTE release manifest.
3. Select the correct runtime artifact.
4. Download the artifact.
5. Verify checksum.
6. Install into a user-writable managed location.
7. Add iTE to PATH where safe.
8. Print exact next steps if PATH cannot be modified.
9. Preserve existing `pipx` or `uv` installs.

Default managed install locations:

macOS/Linux:

```text
~/.ite/bin/ite
```

Windows:

```text
%LOCALAPPDATA%\iTE\bin\ite.exe
```

The installer must be idempotent:

- same version installed: verify and no-op
- older version installed: update
- broken install found: repair
- system `ite` found elsewhere: leave it alone

### FR2: Runtime Release Manifest

iTE must publish a runtime manifest.

Default manifest URL:

```text
https://ite.kiishi.space/releases/manifest.json
```

Example:

```json
{
  "version": "0.0.68",
  "assets": {
    "darwin-arm64": {
      "url": "https://github.com/kiishidavid/ite/releases/download/v0.0.68/ite-0.0.68-darwin-arm64.tar.gz",
      "sha256": "...",
      "archiveType": "tar.gz",
      "executable": "ite"
    },
    "linux-x64": {
      "url": "https://github.com/kiishidavid/ite/releases/download/v0.0.68/ite-0.0.68-linux-x64.tar.gz",
      "sha256": "...",
      "archiveType": "tar.gz",
      "executable": "ite"
    },
    "win32-x64": {
      "url": "https://github.com/kiishidavid/ite/releases/download/v0.0.68/ite-0.0.68-win32-x64.zip",
      "sha256": "...",
      "archiveType": "zip",
      "executable": "ite.exe"
    }
  }
}
```

Supported initial targets:

- `darwin-arm64`
- `darwin-x64`
- `linux-x64`
- `win32-x64`

The installer should allow a manifest override for development:

```bash
ITE_INSTALL_MANIFEST_URL=http://localhost:8000/manifest.json \
  curl -fsSL https://ite.kiishi.space/install.sh | sh
```

### FR3: Standalone Runtime Artifacts

iTE must ship standalone runtime archives that include Python and all required iTE dependencies.

The user should not need a Python interpreter installed separately.

Runtime artifact shape:

```text
ite/
  ite
  _internal/
    ...
```

Windows:

```text
ite/
  ite.exe
  _internal/
    ...
```

The runtime artifact is separate from the Python package:

- Python package: `pipx install ite-agent`
- Managed runtime: one-shot installer

### FR4: Existing Install Routes Remain Supported

These remain valid:

```bash
pipx install ite-agent
uv tool install ite-agent
```

Use cases:

- Python users
- contributors
- CI
- users who prefer package-manager-managed CLIs

The managed installer must not call `pipx` internally. It installs iTE directly from runtime artifacts.

If multiple installs exist, iTE diagnostics should show which executable is active:

```text
iTE executable: /Users/me/.ite/bin/ite
Install type: managed runtime
Version: 0.0.68
```

### FR5: First-Run Local Model Preparation

iTE should prepare a local model path automatically when no provider is configured.

This is an implementation capability, not a normal user-facing step.

Internally, expose:

```bash
ite bootstrap --local
ite bootstrap --local --yes
ite bootstrap --local --model <model>
ite bootstrap --local --no-install
ite bootstrap --local --no-pull
ite bootstrap --status
```

Normal users should not need to run these commands. They exist for:

- installer handoff
- diagnostics
- retries
- automation
- support

The Reup UI should call the underlying Python service directly instead of shelling out.

### FR6: Detect Ollama

iTE must detect Ollama in common locations.

macOS:

- `ollama` on PATH
- `/Applications/Ollama.app/Contents/Resources/ollama`
- `~/Applications/Ollama.app/Contents/Resources/ollama`

Linux:

- `ollama` on PATH
- `/usr/local/bin/ollama`
- `/usr/bin/ollama`

Windows:

- `ollama.exe` on PATH
- `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`
- `%LOCALAPPDATA%\Ollama\ollama.exe`

Detection result:

```python
class OllamaDetectionResult(BaseModel):
    installed: bool
    executable: Path | None
    version: str | None
    source: Literal["path", "known_location", "missing"]
    error: str | None
```

### FR7: Detect Ollama Server State

iTE should check:

```http
GET http://localhost:11434/api/tags
```

States:

- running
- not running
- unreachable
- running but unhealthy
- running on user-configured non-default URL

### FR8: Install Ollama With Explicit Consent

If Ollama is missing and local setup is selected, iTE should offer to install it.

Example copy:

```text
iTE can install Ollama to run a free local model.
Ollama is the local model runtime iTE uses for this default setup.

[Install Ollama] [Use API key instead] [Cancel]
```

Installation must be explicit. iTE must not silently install Ollama.

Platform approach:

macOS:

- Preferred: download official Ollama macOS package/app and install to a user-appropriate location.
- Initial acceptable path: open official download page if full install automation is not ready.

Linux:

- Use Ollama's official installer only after clear consent:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Windows:

- Download official installer or standalone CLI archive.
- Run only after explicit consent.

### FR9: Start Ollama

If Ollama is installed but not running, iTE should start it.

macOS:

```bash
open -a Ollama
```

Fallback:

```bash
ollama serve
```

Linux:

Use service if available:

```bash
systemctl --user start ollama
```

or:

```bash
sudo systemctl start ollama
```

Fallback:

```bash
ollama serve
```

Windows:

- Start Ollama app/executable.
- Poll local API until ready.

Readiness policy:

- timeout: 60 seconds
- poll interval: 1-2 seconds
- success: `/api/tags` returns HTTP 200

### FR10: Select And Pull Default Model

iTE should select a default local model and pull it if missing.

Initial proposed default:

```text
qwen2.5-coder:7b
```

This default must be validated before release against:

- coding quality
- tool/function calling behavior
- memory use
- Apple Silicon performance
- low-memory machines
- model download size

If the selected model is missing:

```bash
ollama pull <model>
```

iTE should show progress and support retry.

Future model policy:

```text
Higher-memory machine: stronger coder model
Lower-memory machine: smaller fallback model
Advanced user: choose manually later
```

### FR11: Save iTE Config Automatically

After local setup succeeds, iTE should save:

```toml
base_url = "http://localhost:11434/v1"
api_key = "ollama"

[model]
name = "<selected-local-model>"
context_window = 200000
context_window_source = "provider_fixed_default"
source_kind = "saved"
```

The setup modal should not open after this succeeds.

### FR12: Reup First-Run Integration

Reup should change from provider-first setup:

```text
Onboarding -> setup modal -> choose provider
```

to working-default setup:

```text
Onboarding -> prepare local default if needed -> chat
```

The provider setup modal should appear only when:

- user chooses “Use API key instead”
- local setup fails and user chooses provider setup
- user later runs `/setup`

### FR13: Provider Setup Remains Available

Users must still be able to run:

```text
/setup
```

Provider setup remains useful for:

- OpenRouter
- OpenAI-compatible providers
- custom local endpoints
- manual Ollama config
- changing models

But it is no longer the default first-run path.

### FR14: Diagnostics

Add:

```bash
ite doctor
```

or extend:

```bash
ite bootstrap --status
```

Example:

```text
iTE status

iTE executable: /Users/me/.ite/bin/ite
Install type: managed runtime
Version: 0.0.68

Local model runtime: Ollama
Ollama installed: yes
Ollama executable: /Applications/Ollama.app/Contents/Resources/ollama
Ollama server: running
Base URL: http://localhost:11434
Default model: qwen2.5-coder:7b
Model installed: yes
iTE configured: yes
```

## Technical Architecture

### Installer Layer

Files:

```text
install.sh
install.ps1
```

Responsibilities:

- fetch runtime manifest
- detect platform
- download runtime
- verify checksum
- install managed runtime
- update PATH where safe
- hand off to iTE first-run flow

### Runtime Packaging Layer

Files:

```text
scripts/build_runtime.py
dist/runtime/
```

Responsibilities:

- build standalone runtime artifacts
- generate checksums
- generate release manifest
- support per-platform release publishing

### Local Setup Layer

Files:

```text
src/ite/bootstrap/
├── __init__.py
├── local.py
├── ollama.py
├── models.py
└── types.py
```

Responsibilities:

- Ollama detection
- Ollama install/start
- model detection/pull
- config save
- event streaming for Reup and CLI diagnostics

### Core Types

```python
class SetupStep(str, Enum):
    DETECT_ITE = "detect_ite"
    INSTALL_ITE = "install_ite"
    DETECT_OLLAMA = "detect_ollama"
    INSTALL_OLLAMA = "install_ollama"
    START_OLLAMA = "start_ollama"
    CHECK_MODEL = "check_model"
    PULL_MODEL = "pull_model"
    SAVE_CONFIG = "save_config"
    VERIFY_PROVIDER = "verify_provider"


class SetupStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SKIPPED = "skipped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SetupEvent(BaseModel):
    step: SetupStep
    status: SetupStatus
    message: str
    detail: str | None = None
```

### Event Stream

Local setup should expose an async event stream:

```python
async def prepare_default_local_model(
    *,
    model_name: str | None = None,
    allow_install: bool = True,
    allow_model_pull: bool = True,
    assume_yes: bool = False,
) -> AsyncIterator[SetupEvent]:
    ...
```

Reup consumes events to render progress. CLI diagnostics can consume the same service.

## Security And Trust

iTE should be transparent about machine-level changes:

- Ask before installing Ollama.
- Ask before downloading large model files.
- Show the source domain for external installers.
- Verify checksums for iTE runtime downloads.
- Do not hide privilege escalation.
- Do not claim local privacy unless traffic stays local.
- Never collect prompt content or secrets as telemetry.

Recommended copy:

```text
Local model setup runs on this computer through Ollama.
No API key is required.
```

## Error Handling

### iTE Runtime Install Fails

```text
iTE could not be installed automatically.

[Retry] [View details] [Manual install]
```

### PATH Update Fails

```text
iTE was installed, but your shell PATH was not updated.

Add this to your shell profile:
export PATH="$HOME/.ite/bin:$PATH"
```

### Ollama Install Fails

```text
Ollama could not be installed automatically.

[Retry] [Use API key instead] [Open Ollama download]
```

### Ollama Starts But API Does Not Respond

```text
Ollama started, but iTE could not reach http://localhost:11434.

[Try again] [Use API key instead] [View details]
```

### Model Pull Fails

```text
iTE could not download the local model.

[Retry] [Choose smaller model] [Use API key instead]
```

### Machine May Be Too Small

```text
This local model may be too large for this computer.

[Use smaller model] [Continue anyway] [Use API key instead]
```

## Metrics

Only collect metrics if the project has explicit telemetry consent.

Useful events:

- installer started
- installer succeeded/failed
- managed runtime installed/updated
- first run started
- local setup selected
- provider setup selected
- Ollama already installed
- Ollama install succeeded/failed
- model pull succeeded/failed
- first working chat reached

Do not collect:

- prompts
- file contents
- API keys
- secrets

## Open Questions

1. What is the default local model?
2. What is the smallest acceptable fallback model?
3. Should macOS v1 automate Ollama installation or open the official installer page?
4. Should the installer automatically modify shell profiles or only print PATH instructions?
5. Should first-run onboarding ask for user profile before or after local setup?
6. Should `ite doctor` be added separately or should `ite bootstrap --status` be enough?
7. What is the support policy for Linux distros without systemd?
8. Should managed runtime updates happen automatically or only after user approval?

## Proposed Milestones

### Milestone 1: Runtime Artifacts

- Build standalone iTE runtime archives.
- Generate release manifest with checksums.
- Validate runtime starts on each supported platform.
- Publish test artifacts to a draft release.

### Milestone 2: One-Shot Installer

- Add `install.sh`.
- Add `install.ps1`.
- Detect OS/architecture.
- Download and verify runtime.
- Install to managed location.
- Preserve existing package-manager installs.

### Milestone 3: Local Setup Service

- Add `src/ite/bootstrap`.
- Detect Ollama.
- Detect Ollama server state.
- Start Ollama.
- Detect model.
- Pull model.
- Save config.

### Milestone 4: CLI Diagnostics

- Add `ite bootstrap --status` or `ite doctor`.
- Add `ite bootstrap --local` for support/automation.
- Add tests for detection/config writing.

### Milestone 5: Reup First Run

- Replace provider-first setup with working-default setup.
- Add local setup progress UI.
- Keep “Use API key instead” available.
- Open provider setup only when selected or needed.

### Milestone 6: Ollama Install Automation

- Implement macOS install/start path.
- Implement Linux install/start path.
- Validate Windows install/start path.
- Keep installation consent explicit.

### Milestone 7: Model Policy

- Validate default model.
- Add smaller fallback model.
- Add hardware-based recommendation.
- Add troubleshooting docs.

## Success Criteria

The feature is successful when a new user can:

1. Install iTE without installing Python, `pipx`, `uv`, Homebrew, Node, or another package manager first.
2. Launch `ite`.
3. Reach a working chat without manually installing Ollama, starting Ollama, pulling a model, entering an API key, or editing config.

The ideal path is:

```bash
curl -fsSL https://ite.kiishi.space/install.sh | sh
ite
```

The existing `pipx` route remains supported, but it is no longer the only high-quality install path.

