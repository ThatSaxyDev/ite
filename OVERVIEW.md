# ITE Overview

ITE is a local-first coding agent with three user-facing surfaces built on the same core runtime:

- `ite` launches the Textual chat UI (`reup`).
- `ite -l` / `ite --legacy` launches the legacy Rich terminal UI.
- `ite -d` / `ite --desktop` launches the Flet desktop GUI.

All three surfaces share the same agent loop, session model, tool registry, approval policy, sandboxing, planning mode, todo system, and attachment staging.

## Launch Model

The CLI entrypoint lives in `src/ite/main.py`.

Current launch flags:

- `ite`
  Starts the legacy terminal UI.
- `ite --chat` or `ite -c`
  Starts the Textual chat app.
- `ite --desktop` or `ite -d`
  Starts the desktop GUI.
- `ite --cwd /path/to/workspace` or `ite -w /path/to/workspace`
  Sets the workspace root before loading config and starting the UI.

## First-Run Setup

ITE supports first-run setup, but the flow differs slightly by surface.

- Legacy TUI:
  Uses `src/ite/config/setup.py` to run a terminal setup wizard before the app starts.
- Chat (`reup`):
  Currently goes through the same legacy terminal setup wizard on first run, then launches the Textual app.
- Desktop GUI:
  Skips the terminal wizard and opens an in-app setup screen.

Default startup values are:

- Base URL: `http://localhost:11434/v1`
- API key: `ollama`
- Model: `minimax-m2.5:cloud`
- Approval policy default: `auto`

System config is stored with `platformdirs` under the user config directory. Project-local config may also be loaded from the workspace.

## High-Level Architecture

```text
CLI / Surface router (src/ite/main.py)
        |
        +--> Legacy Rich TUI (src/ite/ui/tui.py)
        +--> Textual chat UI / reup (src/ite/ui/reup/)
        +--> Flet desktop GUI (src/ite/ui/gui/)
        |
        v
Agent runtime (src/ite/agent/)
        |
        +--> Session state
        +--> Tool registry
        +--> Approval manager
        +--> Context manager
        +--> LLM client
        |
        v
Built-in tools / MCP / subagents
```

## Core Runtime

### Agent

`src/ite/agent/agent.py` implements the main agent loop:

1. build prompt and tool context
2. stream model output
3. handle tool calls
4. append tool results to session context
5. continue until the turn completes, is interrupted, or hits policy limits

The agent is event-driven. UI surfaces consume streamed events such as:

- assistant text deltas
- tool call start/complete
- plan questions
- approval requests
- completion / interruption

### Session

`src/ite/agent/session.py` is the shared state container for a conversation. It owns:

- message history
- current plan text
- planning/execution todos
- approval state
- pending attachment paths
- workboard-relevant state
- tool registry and LLM client wiring

### Session Persistence

`src/ite/agent/session_manager.py` provides resume/save behavior across sessions in the same workspace. GUI and `reup` both expose session resume flows; the terminal UI also uses the same persisted session model.

## UI Surfaces

### Legacy TUI

`src/ite/ui/tui.py`

Purpose:

- fast terminal-first interaction
- Rich panels for assistant and tool output
- first-run wizard reference implementation
- compact, high-density transcript

Current behavior highlights:

- startup splash with workspace/model/version
- planning mode feedback in the status line
- compact tool cards with stronger truncation
- attachment queue support
- `/workboard`, `/plan`, `/todos`, `/attach`, `/branch`, `/model`, `/approval`

### Reup

`src/ite/ui/reup/app.py`

Purpose:

- modern Textual chat interface
- native modals for sessions, branches, attachments, and setup
- cleaner card treatment than legacy TUI

Current behavior highlights:

- inline top status indicator with spinner and live activity labels
- composer metadata row for attachments, model, plan mode, and branch
- native `/workboard` rendering
- session resume modal
- branch switch/create modal
- attachment picker modal
- setup modal still exists in code, but first-run setup currently routes through the legacy wizard before launch

### Desktop GUI

`src/ite/ui/gui/`

Purpose:

- Flet-based desktop app
- setup view, chat feed, workboard panel, branch/session controls
- richer approval cards and tool result rendering

Current behavior highlights:

- explicit setup view when config is incomplete
- persistent workboard side panel
- thinking/progress row with live activity text
- shell command cards with running and completed states
- attachment chips and staging

## Planning, Todos, and Workboard

ITE has a real planning mode, not just a prompt convention.

Planning-related pieces:

- plan-mode toggles and commands
- planning questions
- planning todos vs execution todos
- stored plan text on the session
- workboard view for current plan + visible todos

Relevant files:

- `src/ite/commands/info.py`
- `src/ite/commands/todos.py`
- `src/ite/agent/agent.py`
- `src/ite/ui/reup/app.py`
- `src/ite/ui/gui/app.py`
- `src/ite/ui/gui/state.py`

The workboard is:

- a terminal command in legacy TUI
- a native rendered card in `reup`
- a persistent side panel in the GUI

## Tools

Built-in tools live in `src/ite/tools/builtin/`.

Important groups:

- file operations:
  - `read_file`
  - `write_file`
  - `edit_file`
- repo exploration:
  - `list_dir`
  - `glob`
  - `grep`
- execution:
  - `shell`
- web/research:
  - `web_search`
  - `web_fetch`
- state/tasking:
  - `memory`
  - `todo`
- delegation:
  - `subagent`

Tool behavior is registered through `src/ite/tools/registry.py`.

## Safety Model

ITE has two separate safety layers:

### Sandbox

Sandboxing is path-based and workspace-aware. A tool can be blocked even if it is read-only if it tries to access a path outside the allowed workspace or sandbox allow-list.

Relevant files:

- `src/ite/safety/sandbox.py`
- `src/ite/tools/base.py`
- tool-specific sandbox checks in built-in tools

### Approval

Approval policy controls whether a tool call can proceed automatically, must ask, or must be denied by policy.

Approval policies are defined in `src/ite/config/config.py` and enforced in `src/ite/safety/approval.py`.

Current default:

- `auto`

Common policies include:

- `auto`
- `on_request`
- `auto_edit`
- `on_failure`
- `never`
- `yolo`

## Shell and Web Capability

Shell and web are both first-class action surfaces:

- `shell` is the local execution primitive
- `web_search` and `web_fetch` are the external research primitives

These capabilities are documented separately in:

- `docs/SHELL_AND_WEB_CAPABILITIES.md`

The UI surfaces now expose more explicit activity labels so users can tell when the agent is:

- exploring the workspace
- searching code
- reading files
- running commands
- researching the web

instead of only seeing a generic "thinking" state.

## Attachments

Attachments are queued before send, then staged for the next turn.

Relevant pieces:

- `src/ite/attachments.py`
- `src/ite/commands/attach.py`
- `src/ite/ui/gui/app.py`
- `src/ite/ui/reup/app.py`
- `src/ite/main.py`

Flow:

1. user selects or drags files
2. paths are queued on the session
3. on send, files are staged into a temp attachment area
4. staged attachment content is added to the outgoing turn

## Config and Persistence

Main config code:

- `src/ite/config/config.py`
- `src/ite/config/loader.py`
- `src/ite/config/setup.py`

Config sources:

1. system config in the user config directory
2. project config in the workspace
3. environment variables
4. CLI overrides

Current important defaults:

- base URL: `http://localhost:11434/v1`
- API key: `ollama`
- model: `minimax-m2.5:cloud`
- approval: `auto`

## Repository Map

Key directories:

- `src/ite/agent/`
  Agent loop, session model, events, session persistence
- `src/ite/client/`
  OpenAI-compatible API client and streamed response parsing
- `src/ite/commands/`
  Slash commands and user-facing command handlers
- `src/ite/config/`
  Config models, loading, setup wizard, persistence
- `src/ite/context/`
  Prompt/context assembly
- `src/ite/safety/`
  Sandbox and approval logic
- `src/ite/tools/`
  Built-in tools, tool registry, MCP and subagent integration
- `src/ite/ui/tui.py`
  Legacy Rich TUI
- `src/ite/ui/reup/`
  Textual chat UI
- `src/ite/ui/gui/`
  Flet desktop GUI
- `tests/`
  Unit and regression tests

## Current Drift Risks

This codebase evolves quickly, so the most common drift points are:

- CLI flag renames vs tests/docs
- startup/setup routing differences across surfaces
- config persistence behavior across TUI, `reup`, and GUI
- stale docs referencing the old single-surface model

When reviewing or extending the app, validate all three surfaces:

- `ite`
- `ite --chat`
- `ite --desktop`
