# AGENTS.md

## Project Overview

**Project:** `ite-agent` (iTE - Interactive Terminal Environment)

An AI coding agent for the terminal. Users connect their model service and start coding via a TUI interface. Distributed via pipx/uv as `ite-agent`.

## Architecture

```
src/ite/                    # Python CLI runtime
  __init__.py
  main.py                   # Entry point (click CLI)
  agent/
    agent.py                # Core agent logic
    events.py               # Event system
    session.py              # Session management
  client/                   # LLM client abstraction
  commands/                 # Slash command registry
  config/                   # Configuration loading
  context/                  # Context management
  memory/                   # Memory system
  prompts/                  # System prompts
  skills/                   # Agent skills
  tools/                    # Tool implementations
  ui/                       # TUI/GUI interfaces
ite-cloud-api/              # Fastify TypeScript backend
  src/
    index.ts                # API entry point
ite-cloud-web/              # React TypeScript frontend
  src/
    App.tsx                 # Web app entry
landing-site/               # Marketing site
```

- **Entry point:** `src/ite/main.py:main()` (click group)
- **Version:** 0.0.27
- **Agent class:** `src/ite/agent/agent.py:Agent`

## Development Guidelines

**Python Patterns:**
| Pattern | Convention |
|---------|------------|
| Imports | `from __future__ import annotations` |
| Internal imports | `from ite.module.submodule import Name` |
| Constants | `UPPER_CASE` (e.g., `PLAN_EXECUTE_PROMPT`) |
| Classes | `PascalCase` |
| Functions/vars | `snake_case` |
| Async | Extensive use of `async/await` |

**TypeScript Patterns:**
| Pattern | Convention |
|---------|------------|
| Imports | ES modules with explicit paths |
| Types | Strict TypeScript with interfaces |

**Build Commands:**

Python:
| Command | Usage |
|---------|-------|
| Install | `pipx install ite-agent` or `uv tool install ite-agent` |
| Run | `ite` |

Cloud API:
| Command | Script |
|---------|--------|
| Install | `npm install` |
| Dev | `npm run dev` |
| Migrate | `npm run auth:migrate` |

Cloud Web:
| Command | Script |
|---------|--------|
| Install | `npm install` |
| Dev | `npm run dev` |

**Testing:**
- Python tests in `tests/`
- pytest framework

## Configuration

- **Python config:** `pyproject.toml` (root)
- **User config:** `.ite/config.toml`
- **API env:** `ite-cloud-api/.env.local`
- **Key dependencies:**
  - Python: `click`, `rich`, `prompt_toolkit`, `litellm`
  - API: `fastify`, `better-auth`, `drizzle-orm`, `@libsql/client`
  - Web: `react`, `react-router-dom`, `vite`, `better-auth`

**Runtime Modes:**
- Default: Reup TUI (`ite`)
- Legacy: Terminal wizard (`ite --legacy` / `ite -l`)
- Desktop: GUI app (`ite --desktop` / `ite -d`)
