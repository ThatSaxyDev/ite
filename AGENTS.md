# iTE - Interactive Terminal Environment

## Project Overview

iTE is an AI coding agent for the terminal that connects to LLM model services (OpenAI-compatible). Users configure a model provider via `/setup` command and interact with the agent through natural language prompts. The agent reads code files, executes commands, and assists with development tasks.

## Architecture

```
src/ite/              # Main Python package
├── __init__.py       # Empty package marker
├── main.py           # Entry point (ite command)
├── attachments.py    # File attachment handling (images, PDFs, text)
├── attachment_refs.py # Inline @file reference parsing
├── setup.py          # Configuration management
├── prompts/          # System prompts and message handling
└── [other modules]

tests/                # Test suite
docs/                 # Documentation
ite-cloud-api/        # Backend API service
ite-cloud-web/        # Web frontend
landing-site/         # Marketing site
```

**Key Dependencies:**
- CLI: `click`, `prompt_toolkit>=3.0.52`
- UI: `rich`, `textual[syntax]>=0.70.0`, `flet`
- AI: `openai`, `tiktoken`
- Parsing: `beautifulsoup4`, `html2text`, `lxml`, `pypdf`, `pytesseract`
- Config: `pydantic`, `PyYAML`, `platformdirs`, `fastmcp`
- Utils: `ddgs` (search), `Pillow`

**Python Requirement:** >=3.11

## Development Guidelines

### Build & Package

```bash
# Development install with editable mode
pip install -e .

# Or using hatch
hatch run pip install -e .

# Build wheel
hatch build

# Install published version
pipx install ite-agent
# or
uv tool install ite-agent
```

### Entry Point

The `ite` command is provided by the `ite` package's `main:main` function:
```python
# pyproject.toml
[project.scripts]
ite = "ite.main:main"
```

### Code Patterns

**Imports:**
```python
from __future__ import annotations  # Required in all modules
```

**Immutable Data Classes:**
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class InlineAttachmentRef:
    raw: str
    value: str
    start: int
    end: int
    trailing: str = ""
```

**File Extensions (from `attachments.py`):**
```python
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_EXTS = {".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ...}
PDF_EXTS = {".pdf"}
```

**Constants Pattern:**
- `MAX_ATTACHMENTS = 3`
- `MAX_FILE_SIZE_BYTES = 35 * 1024 * 1024` (35MB limit)

**Skipped Directories (attachment discovery):**
```python
_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next",
    "dist", "build", "coverage", ".idea", ".vscode"
}
```

**Inline Reference Pattern:**
Files can be referenced inline using `@filename.ext` syntax (parsed by `attachment_refs.py`)

### Testing

Tests are located in the `tests/` directory. Run with pytest or hatch.

## Tool Preferences

| File Type | Tool | Notes |
|-----------|------|-------|
| `.py` | ruff, ruff format | Primary linting/formatting |
| `.txt`, `.md` | plain text | Documentation |
| `.json`, `.yaml`, `.toml` | native parsers | Config files |
| `.pdf` | pypdf + pytesseract | Document parsing |
| Images | Pillow + pytesseract | OCR support |

## Configuration

- User config stored via `platformdirs` (cross-platform config directory)
- Provider configuration via `/setup` command in session
- Workspace stored at `.ite/tmp_attachments` (gitignored)
