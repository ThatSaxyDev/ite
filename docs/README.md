# Documentation Structure

This directory contains the source documentation for iTE (ite-agent).

## Files

| File | Purpose |
|------|---------|
| `index.md` | Documentation landing page |
| `installation.md` | Install via pipx, uv |
| `configuration.md` | Provider setup (Ollama, OpenRouter, OpenAI) |
| `initialization.md` | AGENTS.md and /init command |
| `usage.md` | Everyday workflows |
| `commands.md` | Complete command reference |
| `agents.md` | AGENTS.md specification |
| `skills.md` | Skills system |
| `mcp.md` | MCP server integration |

## Data File

`docs-content.json` contains the same content in machine-readable JSON format for the web app.

## Web Integration

To use this content in the web app:

1. Import `docs-content.json` in the app
2. Render sections using the web app's Markdown renderer
3. Use the `sections` array for navigation

## Maintenance

When updating docs:
- Update the `.md` file for readability
- Update `docs-content.json` for the web app
- Keep both in sync
