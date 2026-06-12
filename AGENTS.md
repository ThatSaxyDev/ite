# AGENTS.md

## Project Overview

**iTE** - Interactive Terminal Environment

An AI coding agent for the terminal. Users connect a model service, authenticate where needed, and work through the Reup Textual runtime.

- **Package:** `ite-agent`
- **Version:** 0.1.25
- **Install:** `pipx install ite-agent` or `uv tool install ite-agent`
- **Local editable install:** `uv pip install -e .` from the repo root, or `source .venv/bin/activate && python -m pip install -e .`

## ⚠️ ATTENTION — GIT PAGER WILL HANG YOUR SHELL CALLS ⚠️

**This is a warning to you, the agent reading this file.** Read it.

When you use `shell` to run `git log`, `git diff`, `git show`, `git blame`, or any other git command that produces multi-screen output, **git will auto-launch `less` as its pager** because the `shell` tool allocates a pseudo-terminal (PTY). `less` will print the first screenful and then block, waiting for keyboard input that will never arrive. The command will hang until the timeout kills it.

**What this looks like**: the output streams commit IDs and titles, then just stops — silence, no prompt return, no exit.

**How to avoid it — always do one of these:**

- ✅ **USE THE DEDICATED GIT TOOLS.** They exist for exactly this reason: `git_log`, `git_diff`, `git_status`, `git_commit`, `git_push`, `git_branch`, `git_remote`. They never invoke a pager. ALWAYS prefer these over `shell` for git operations.
- ✅ If you must use `shell`, **always** prefix with `GIT_PAGER=cat` or append `--no-pager` (e.g., `GIT_PAGER=cat git log ...` or `git --no-pager log ...`).

**Do not skip this.** If you run a raw `git log` through `shell` without disabling the pager, you will waste a turn, confuse the user, and look like you don't know what you're doing.

## Current Runtime

Reup Textual is the only supported runtime UI.

| Command | Runtime |
|---------|---------|
| `ite` | Reup Textual terminal app |

Removed runtime surfaces:

- The old Rich/prompt_toolkit terminal UI has been removed.
- The Flet desktop GUI has been removed.
- `--legacy`, `-l`, `--desktop`, and `-d` are not supported runtime flags.
- Do not reintroduce `src/ite/ui/tui.py`, `src/ite/ui/gui.py`, or `src/ite/ui/gui/`.
- Do not add `flet` or `prompt_toolkit` back to dependencies unless the user explicitly asks to revive those products.

## Architecture

```
src/ite/
├── main.py              # CLI entry point; runs Reup by default
├── agent/               # Agent orchestration
│   ├── agent.py         # Core agent implementation
│   ├── session.py       # Session management
│   └── events.py        # Agent event types
├── client/              # LLM client
├── cloud/               # Cloud auth/integration
├── commands/            # Slash commands (/, plan, skills, etc.)
├── config/              # Configuration models and loading
├── context/             # Context management
├── git/                 # Git utilities
├── hooks/               # Custom hooks
├── memory/              # Memory management
├── prompts/             # System prompts
├── remote/              # Remote runtime protocol/server
├── safety/              # Sandbox and approval
├── skills/              # Extensible skills
├── tools/               # Built-in and MCP tools
├── ui/
│   ├── reup/            # Textual runtime UI
│   ├── assets/          # Shared UI assets
│   └── tool_narrative.py
└── utils/               # Utilities
```

## Runtime Focus

- All runtime UI work belongs in `src/ite/ui/reup/`.
- `src/ite/main.py` should stay thin: parse CLI options, load config, validate config, and call `ite.ui.reup.run_reup(config)`.
- Slash commands should remain runtime-agnostic where possible. They receive a `CommandContext` whose `tui` field is the active Reup adapter.
- Do not split fixes across old UI surfaces. There are no old UI surfaces to keep in sync.
- When debugging runtime behavior, start with Reup widgets, Reup app flow, Reup command rendering, and Reup styling in `src/ite/ui/reup/reup.tcss`.
- Prefer focused Reup tests and import/package-shape checks when changing runtime behavior.

## Local Development Setup

Use the project virtualenv unless you intentionally need a separate environment.

```sh
cd /Users/kiishidavid/Documents/Dev/Projects/itetheagt/ite
source .venv/bin/activate
python -m pip install -e .
```

`python3` may point at a system Python instead of this repo's `.venv`. Prefer `python` after activation, `.venv/bin/python`, or `uv`.

Useful checks:

```sh
source .venv/bin/activate
type ite
ite --version
python -m ite.main --help
```

In this workspace, `.venv/bin/activate` defines an `ite` shell function that runs `python -m ite.main "$@"`. This avoids local script-launch hangs seen with direct shebang execution while still exercising the same package entry point.

## Reup Thread Navigation

- Thread switching is a first-class Reup UI flow, not only a slash-command flow.
- Keep `/sessions` available; do not remove or degrade it.
- The thread nav opens from the left and is controlled by a hamburger glyph at the far left of the top bar.
- The hamburger should always be available when signed in, even if there is only one thread.
- Do not place a `/threads` text button on the right side of the header.
- The thread nav must remain collapsible with a close control.
- The top of the thread nav should contain a solid `New chat` action equivalent to `/new`.
- Thread rows should be text-like navigation rows, not solid buttons.
- Thread rows should align left, remain one line, and truncate with `...`.
- The selected/current thread should be indicated visually with row treatment and a thin left-edge indicator, not with inline `current` text.
- Empty draft threads titled `New thread` should not appear as rows until they contain real content.
- When a new draft becomes a real thread after a message, it should appear at the top rather than at the bottom.
- Thread row order should be stable. Switching or selecting a thread must not reorder the side nav.
- Include saved former sessions from `SessionManager().list_sessions(...)` in the thread nav, deduped against open sessions.

## Reup Multi-Thread Runtime Rules

- Treat each open Reup thread as an independent runtime session with its own `Session`, `Agent`, `SessionRunState`, and workspace.
- Do not temporarily assign `self.agent` to another open agent just to save, inspect, or finish a background thread. That can race with the active UI thread and cause freezes or wrong-thread sends.
- Sends must bind to the session that was active when the user submitted the composer payload. If the user switches immediately afterward, the in-flight turn should still run in the originally submitted session.
- Background turn completion should update that session and its nav/header state without mutating the active visible agent.
- Each open session should use a workspace-scoped config copy. Do not let one shared mutable `Config.cwd` leak into other running agents.
- Attachment staging, manifest creation, and cleanup should use the workspace captured for the target session, not whatever workspace is active after the user switches.
- Side-nav refresh should be incremental where possible. Avoid removing/remounting all rows on every state change because it causes visible stutter and can interrupt interaction.
- Be careful with Textual mount timing. Do not mount children into a `VerticalScroll` or panel before that widget is attached.
- Prefer focused Reup tests for send binding, inactive-thread save, per-session config/workspace isolation, thread order stability, and resume/open behavior.

## Reup Textual UI Constraints

- Reup background workers must be lifecycle-safe around Textual widgets.
- Widgets such as `_activity_widget`, session tabs, thread nav, and change review panels can be removed, replaced, or nulled while an async worker is awaiting `mount()`, `remove()`, `query_one()`, or another UI operation.
- Never dereference a mutable widget field after an `await` unless you re-check that it is still the same non-`None` mounted widget.
- Prefer capturing the widget in a local variable, checking `self._field is widget` after awaits, and returning quietly if the version/widget changed.
- Textual scrollbar sizes are terminal-cell based.
- `scrollbar-size-vertical: 1` and `scrollbar-size-horizontal: 1` are the smallest practical visible scrollbar sizes.
- Setting scrollbar size to `0` hides that scrollbar; do not use this when the user needs a draggable scroll indicator.
- Prefer global scrollbar sizing in `src/ite/ui/reup/reup.tcss` for consistency across chat feed, thread nav, change review, aside panel, and nested scroll cards.
- Do not chase browser-like fractional scrollbar styling in Textual. If a scrollbar still feels heavy at size `1`, reduce horizontal overflow or adjust colors instead.

## Development Commands

| Command | Purpose |
|---------|---------|
| `python -m build` | Build distribution |
| `pytest` | Run tests |
| `ruff check .` | Lint |
| `mypy src/ite` | Type check |
| `uv lock` | Refresh lockfile after dependency changes |

## Code Patterns

| Convention | Pattern |
|------------|---------|
| Imports | `from __future__ import annotations` |
| Async | Extensive asyncio usage with `async for` generators |
| Pydantic | Config uses Pydantic models |
| Enums | Use `str, Enum` for policies |
| Type hints | Full typing with `|` union syntax |
| Constants | UPPER_CASE pattern |

## Key Types

```python
class AgentEventType(Enum):
    TEXT_DELTA = "text_delta"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    CONTEXT_COMPACTED = "context_compacted"

class ToolResult(BaseModel):
    success: bool
    output: str
    error: str | None = None
```

## Configuration

Config loading:

- User config: `~/.ite/config.toml`
- Project config: `.ite/config.toml`
- CLI flags override file config
- Env vars include `API_KEY`, `BASE_URL`, and `ITE_CLOUD_AUTH_ENABLED`

Current dependency notes:

- `textual[syntax]` is the runtime UI dependency.
- `rich` remains in use for renderables and command output.
- `flet` is removed.
- `prompt_toolkit` is removed.

Python path:

- Source package: `src/ite`
- Tests: `tests/`
