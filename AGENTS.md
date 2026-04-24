# ite

Based on my investigation of the project, here is the complete AGENTS.md content:

# AGENTS.md

## Project Overview

**iTE** - Interactive Terminal Environment

An AI coding agent for your terminal. Connect your model service and start coding.

- **Package:** `ite-agent`
- **Version:** 0.0.33
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
version = "0.0.33"
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
