# AGENTS.md

## Project Overview

**iTE** — AI coding agent for the terminal. Users connect a model service, authenticate where needed, and work through the Reup Textual runtime.

- **Package:** `ite-agent` (version 0.2.9)
- **Install:** `pipx install ite-agent` or `uv tool install ite-agent`
- **Local editable install:** `uv pip install -e .` from the repo root, or `source .venv/bin/activate && python -m pip install -e .`
- **Python:** ≥3.11

## Workspace Layout

```
├── docs/                # User documentation (installation, configuration, etc.)
│   └── design/          # Design docs, PRDs, architecture notes
├── hooks/               # PyInstaller runtime hooks
├── scripts/             # Build, release, and analysis tooling
│   └── decon/           # App deconstruction helpers (from the app.py refactor)
├── src/ite/             # Package source
├── tests/               # Test suite
├── install.sh           # One-shot macOS/Linux installer (curl pipe)
├── install.ps1          # One-shot Windows installer (irm pipe)
├── pyproject.toml       # Build config (hatchling)
├── uv.lock              # Locked dependencies
├── AGENTS.md            # This file
├── DESIGN.md            # Textual UI design contract
└── README.md
```

## Package Architecture (`src/ite/`)

```
src/ite/
├── main.py              # CLI entry point; runs Reup by default
├── __init__.py           # Package init; __version__
├── agent/               # Agent orchestration (agent.py, session.py, events.py)
├── client/              # LLM client abstraction
├── cloud/               # Cloud auth/integration
├── commands/            # Slash commands (/, plan, skills, etc.)
├── config/              # Config models (config.py, loader.py, setup.py)
├── context/             # Context window management
├── git/                 # Git utilities
├── hooks/               # Custom hooks
├── memory/              # Memory management
├── prompts/             # System prompt templates
├── remote/              # Remote runtime protocol/server
├── safety/              # Sandbox and approval gating
├── skills/              # Extensible skill manager
├── tools/               # Built-in tools and MCP tool support
├── ui/
│   ├── reup/            # Textual runtime UI
│   │   ├── app.py         # Main App class (ReupApp)
│   │   ├── _cloud.py      # Cloud/onboarding flows
│   │   ├── _composer.py   # Message composer input
│   │   ├── _helpers.py    # Shared helpers (voice insert, redaction)
│   │   ├── _panels.py     # Panel layout management
│   │   ├── _streaming.py  # LLM streaming → UI
│   │   ├── _threads.py    # Thread/header management
│   │   ├── _turn.py       # Turn orchestration
│   │   ├── modals.py      # Modal dialogs (setup, quit, etc.)
│   │   ├── change_tree.py, change_views.py, composer_views.py
│   │   ├── command_views.py, tool_views.py
│   │   ├── markdown_widget.py
│   │   ├── legacy/          # ⚠️ OLD GOD CLASS — do NOT read; see note below
│   │   └── widgets/       # Reusable widgets
│   │       ├── message_row.py, prompt_area.py
│   │       ├── side_panels.py, tool_cards.py
│   │       ├── thread_switcher.py, remote_bridge.py
│   │       ├── state.py, system_commands.py
│   │       └── __init__.py
│   ├── assets/          # Shared UI assets
│   └── tool_narrative.py
├── utils/               # Shared utilities
├── voice/               # Voice input support
└── web/                 # Web search/retrieval
```

> ⚠️ **legacy/ — DO NOT READ THESE FILES**  
> `src/ite/ui/reup/legacy/` contains pre-refactor snapshots of `app.py` from when it was a single ~14,500-line god class. These files (`app.py.backup`, `app.py.original`, `app.py.patch`, `app_prestrip.py`, `app_refactored.py`) are preserved solely for historical reference during the modularisation. They are **not** part of the active codebase. **Do not `read_file` or `grep` them unless you have a specific reason to trace pre-refactor history.** Loading them will waste context and may poison your understanding of the current architecture. The refactored code lives in `app.py` (~1,600 lines), the `_*.py` mixins, `widgets/`, and supporting views.

- Entry point: `src/ite/main.py` (Click CLI group `IteGroup`)
- Runtime UI: Textual `src/ite/ui/reup/` — the only supported runtime surface
- Config loading: `src/ite/config/loader.py` → `load_config()` with workspace-aware TOML layering

### Reup app.py: Re-export migration (backward compatibility)

`app.py` was refactored from a single ~14,500-line god class into the modular structure above. Seven symbols are re-exported at the bottom of `app.py` (line ~1570) to avoid breaking existing callers:

| Symbol | Canonical Location (import from here) |
|--------|---------------------------------------|
| `ReupPromptTextArea` | `.widgets.prompt_area` |
| `UserMessageRow` | `.widgets.message_row` |
| `ChangeReviewSidePanel` | `.widgets.side_panels` |
| `pluralize_tool_title` | `.widgets.tool_cards` |
| `insert_voice_text_into_widget` | `._helpers` |
| `redact_sensitive_command_text` | `._helpers` |
| `CLOUD_NETWORK_*`, `ONBOARDING_OTHER_VALUE` | `._cloud` |

When writing **new code**, import from the canonical location. When touching **existing callers** (5 test files, `modals.py`), update the import and drop the re-export once no callers remain.

## Development Guidelines

**Quality Commands:**
| Command | Purpose |
|---------|---------|
| `python -m build` | Build distribution (hatchling) |
| `pytest` | Run tests |
| `ruff check .` | Lint |
| `mypy src/ite` | Type check |
| `uv lock` | Refresh lockfile after dependency changes |

**Key Dependencies:**
| Category | Packages |
|----------|----------|
| Runtime UI | `textual[syntax]>=8.2.0`, `rich` |
| LLM Client | `openai`, `tiktoken` |
| Config/Data | `click`, `pydantic`, `tomli`, `platformdirs`, `PyYAML` |
| Tools/Media | `pypdf`, `Pillow`, `pytesseract`, `html2text`, `beautifulsoup4`, `lxml` |
| Sandbox/MCP | `fastmcp` |
| Auth/Libs | `cryptography>=46.0.0`, `certifi` |
| Dev | `pyinstaller>=6.0`, `ruff`, `mypy`, `pytest` |

**Code Patterns:**
| Convention | Pattern |
|------------|---------|
| Imports | `from __future__ import annotations` |
| Async | Extensive asyncio with `async for` generators |
| Config models | Pydantic `BaseModel` |
| Enums | `str, Enum` |
| Data transfer | `@dataclass` |
| Type hints | Full typing with `|` union syntax |
| Constants | `UPPER_CASE` |

**Key Types:**
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

**File Type → Tool:**
| File type | Tool |
|-----------|------|
| `.py` | `ruff`, `mypy`, `pytest` |
| `.tcss` | Textual CSS — no dedicated linter |
| `.toml` | `pyproject.toml` config |

## Configuration

- User config: `~/.ite/config.toml`
- Project config: `.ite/config.toml`
- CLI flags override file config
- Env vars: `API_KEY`, `BASE_URL`, `ITE_CLOUD_AUTH_ENABLED`
- Workspace layout: managed by `ensure_workspace_layout()` in `src/ite/config/loader.py`
