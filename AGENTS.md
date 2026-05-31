# ite

Based on my investigation of the project, here is the complete AGENTS.md content:

# AGENTS.md

## Project Overview

**iTE** - Interactive Terminal Environment

An AI coding agent for your terminal. Connect your model service and start coding.

- **Package:** `ite-agent`
- **Version:** 0.0.83
- **Install:** `pipx install ite-agent` or `uv tool install ite-agent`

## Architecture

```
src/ite/
├── main.py              # CLI entry point
├── agent/               # Agent orchestration
│   ├── agent.py         # Core agent implementation
│   ├── session.py       # Session management
│   └── events.py        # Agent event types
├── client/              # LLM client
├── cloud/               # Cloud auth/integration
├── commands/            # Slash commands (/, plan, skills, etc)
├── config/              # Configuration models
├── context/             # Context management
├── git/                 # Git utilities
├── hooks/               # Custom hooks
├── memory/              # Memory management (short, long, semantic, episodic)
├── prompts/             # System prompts
├── safety/              # Sandbox & approval
├── skills/              # Extensible skills
├── tools/               # Built-in tools
│   ├── base.py
│   ├── builtin/
│   │   ├── read_file.py
│   │   ├── write_file.py
│   │   ├── edit_file.py
│   │   ├── apply_patch.py
│   │   ├── list_dir.py
│   │   ├── glob.py
│   │   ├── grep.py
│   │   ├── shell.py
│   │   ├── git_tools.py
│   │   ├── web_search.py
│   │   ├── web_fetch.py
│   │   ├── http_tools.py
│   │   ├── memory.py
│   │   ├── todo.py
│   │   └── ...
│   └── mcp/             # MCP client tools
├── ui/                  # Three UI modes
│   ├── tui.py          # Legacy terminal UI
│   ├── reup/           # Modern default UI
│   └── gui/            # Desktop GUI
└── utils/               # Utilities
```

**Entry Points:**
| Mode | Command | Description |
|------|---------|-------------|
| Default | `ite` | Modern Reup UI |
| Legacy | `ite -l` or `ite --legacy` | Original terminal UI |
| Desktop | `ite -d` or `ite --desktop` | Desktop GUI app |

## Runtime Focus

- Reup is the primary runtime. Assume all runtime UI work belongs in the Reup Textual path under `src/ite/ui/reup/` unless the task explicitly names another surface.
- `src/ite/ui/tui.py` and `src/ite/ui/gui/` are legacy runtime surfaces. Ignore them by default.
- Do not split effort across Reup, TUI, and GUI. If a fix is for runtime behavior, implement it in Reup first and stop there unless the user explicitly asks for legacy parity.
- Do not proactively port, mirror, or backfill Reup changes into TUI or GUI.
- When debugging runtime behavior, start with Reup widgets, Reup app flow, Reup command rendering, and Reup styling in `src/ite/ui/reup/reup.tcss`.
- Prefer Reup-focused tests and validation. Only inspect or change TUI/GUI code when the task specifically requires those legacy paths.

## Reup Thread Navigation

- Thread switching is a first-class Reup UI flow, not only a slash-command flow.
- Keep `/sessions` available; do not remove or degrade it. The thread nav is the mouse/visual counterpart for users who do not want to type.
- The thread nav opens from the left and is controlled by a hamburger glyph at the far left of the top bar.
- The hamburger should always be available when signed in, even if there is only one thread.
- Do not place a `/threads` text button on the right side of the header. It causes alignment issues and is directionally wrong for a left panel.
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
- Prefer focused Reup tests for these rules: send binding, inactive-thread save, per-session config/workspace isolation, thread order stability, and resume/open behavior.

## Reup Textual UI Constraints

- VERY IMPORTANT: Reup background workers must be lifecycle-safe around Textual widgets. Widgets such as `_activity_widget`, session tabs, thread nav, and change review panels can be removed, replaced, or nulled while an async worker is awaiting `mount()`, `remove()`, `query_one()`, or another UI operation. Never dereference a mutable widget field after an `await` unless you re-check that it is still the same non-`None` mounted widget. Prefer capturing the widget in a local variable, checking `self._field is widget` after awaits, and returning quietly if the version/widget changed. This specifically prevents recurring crashes like `AttributeError: 'NoneType' object has no attribute 'update'` in `_show_activity_indicator`.
- Textual scrollbar sizes are terminal-cell based.
- `scrollbar-size-vertical: 1` and `scrollbar-size-horizontal: 1` are the smallest practical visible scrollbar sizes.
- `scrollbar-size-horizontal: 1` can still look visually thick because one terminal row is a full character cell tall.
- Setting scrollbar size to `0` hides that scrollbar; do not use this when the user needs a draggable scroll indicator.
- Prefer global scrollbar sizing in `src/ite/ui/reup/reup.tcss` for consistency across chat feed, thread nav, change review, aside panel, and nested scroll cards.
- Do not chase browser-like fractional scrollbar styling in Textual. If a scrollbar still feels heavy at size `1`, reduce horizontal overflow or adjust colors instead.

## Development Guidelines

**Build Commands:**

| Command | Purpose |
|---------|---------|
| `python -m build` | Build distribution |
| `pytest` | Run tests |
| `ruff check .` | Lint |
| `mypy src/ite` | Type check |

**Code Patterns:**

| Convention | Pattern |
|------------|---------|
| Imports | `from __future__ import annotations` |
| Async | Extensive asyncio usage with `async for` generators |
| Pydantic | All config uses Pydantic BaseModel |
| Enums | Use `str, Enum` for policies (e.g., ApprovalPolicy) |
| Type hints | Full typing with `|` union syntax |
| Constants | UPPER_CASE pattern |

**Key Types:**

```python
# Agent events for streaming responses
class AgentEventType(Enum):
    TEXT_DELTA = "text_delta"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    CONTEXT_COMPACTED = "context_compacted"

# Tool result pattern
class ToolResult(BaseModel):
    success: bool
    output: str
    error: str | None = None
```

**Tool Categories:**
| Kind | Tools |
|------|-------|
| READ | list_dir, glob, grep, read_file, read_pdf, read_image |
| WRITE | write_file, edit, apply_patch |
| EXECUTE | shell |
| META | todos, memory, plan_question, skills |

## Configuration

**File:** `pyproject.toml`

**Key Sections:**
```toml
[project]
name = "ite-agent"
version = "0.0.83"
dependencies = [
    "click",
    "pydantic",
    "rich",
    "prompt-toolkit",
    "fastmcp",
    "httpx",
]
```

**Config Loading:**
- User config: `~/.ite/config.toml`
- Project config: `.ite/config.toml`
- CLI flags override file config
- Env vars: `API_KEY`, `BASE_URL`, `ITE_CLOUD_AUTH_ENABLED`

**Python Path:** `src/ite`

**Tests:** `tests/` directory, pytest-based
