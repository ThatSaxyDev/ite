# iTE — The AI Agent for Real Work in Your Terminal

**Tagline:** Plan, execute, and stay in control.

## What It Is

iTE is an AI coding agent that lives in your terminal. It reads your codebase, understands project context through `AGENTS.md` files, and executes real work — from explaining code and reviewing PRs to implementing features across your entire project. Think of it as a senior engineer pair programming with you, directly in the shell.

## One-Command Install

```bash
# macOS / Linux
curl -fsSL https://ite.kiishi.space/install.sh | bash

# Windows
irm https://ite.kiishi.space/install.ps1 | iex

# Or via package manager
pipx install ite-agent
uv tool install ite-agent
```

Requires Python 3.11+. Works on Terminal.app, iTerm2, Warp, Ghostty, Windows Terminal, PowerShell, and CMD.

## Why It's Different

| | iTE | Other agents |
|---|---|---|
| **Surface** | Native terminal (macOS, Linux, Windows) | Browser or IDE-locked |
| **Provider** | BYOK (OpenAI, OpenRouter, Ollama) **or** bundled cloud models | Usually one or the other |
| **Control** | 5 approval modes from "ask first" to full auto | Typically binary |
| **Extensibility** | MCP servers, skills packs, custom subagents | Limited or closed |
| **Context** | `AGENTS.md` scope hierarchy — project-aware from the start | Manual prompting each time |

## Key Capabilities

### Plan First, Then Execute
Design solutions with `/plan on`, iterate on the approach, then build with `/plan off`. Changes are undoable — `/undo` and `/redo` give you a safety net.

### 40+ Built-in Tools
- **Read:** file contents, JSON/TOML/YAML, PDFs, images (with OCR), directory listing, glob pattern matching, grep
- **Write:** file creation, surgical text edits, multi-file patches, structured data editing
- **Execute:** shell commands with timeout, persistent shell sessions
- **Git:** status, diff, log, branch management, commit, push
- **Verification:** run tests, linter, type checker — in any language

### Specialist Subagents (Run in Parallel)
| Subagent | Purpose |
|---|---|
| Security Auditor | Vulnerability analysis |
| Code Reviewer | Code quality review |
| Codebase Investigator | Explore structure and patterns |
| Tooling Guardian | Validate tool configurations |
| Verification Reviewer | Regression-focused change validation |
| Init Investigator | Auto-generate AGENTS.md |

### Extensible by Design
- **MCP (Model Context Protocol):** Connect any MCP-compatible server for database access, API integrations, or custom tools
- **Skills:** Install interoperable `SKILL.md` bundles from any agent ecosystem (Claude, Cursor, Codex, Gemini, OpenCode)
- **Custom subagents:** Define specialized agents in `.ite/subagents/<name>.toml`

### Provider Flexibility
Use your own API keys (OpenAI, OpenRouter, Ollama) or subscribe to iTE Pro for bundled cloud access to models like MiniMax M3 and DeepSeek V4 Pro.

## Pricing

**Free:** Local models via Ollama, or bring your own API keys.

**iTE Pro — $3 first month, then $8/month:**
- Cloud coding models included (no separate API bills)
- Fair-use request windows (e.g. ~66K requests/week on MiniMax M3)
- Your own keys still work alongside bundled models
- Cancel anytime

## Project Awareness

iTE understands your codebase through `AGENTS.md` files — project instructions that work like `README.md` for AI:

- `/init` analyzes your project and generates an `AGENTS.md` automatically
- Scope hierarchy: deeper files override parent instructions
- Works across monorepos with language-diverse sub-projects

## Who It's For

- **Developers** who want AI assistance without leaving the terminal
- **Teams** who need consistent, project-aware AI across their codebase
- **Open-source maintainers** who want fast code review and analysis
- **Anyone** who wants an agent that respects their workflow, their tools, and their provider choices

---

**Website:** [ite.kiishi.space](https://ite.kiishi.space)  
**Docs:** [ite.kiishi.space/docs](https://ite.kiishi.space/docs)
