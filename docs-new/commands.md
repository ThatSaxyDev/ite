# Commands

Type `/help` in iTE to see available commands.

## Session Management

| Command | Description |
| ------- | ----------- |
| `/new` | Start a new conversation thread |
| `/sessions` | List saved conversations and resume |
| `/rename <name>` | Rename the current conversation |
| `/compact` | Compact conversation history |
| `/exit` or `/quit` | Close iTE |
| `/close` | Close the current thread (multi-thread UI) |

## Configuration

| Command | Description |
| ------- | ----------- |
| `/setup` | Configure model provider |
| `/config` | View current configuration |
| `/model <name>` | Change model |
| `/approval <mode>` | Set approval mode: `on_request`, `on_failure`, `auto`, `auto_edit`, `yolo` |
| `/approval help` | Show all approval modes with descriptions |
| `/stats` | Show token usage statistics |
| `/tools` | List available tools |
| `/theme` | Change UI theme (re-up UI) |
| `/logout` | Log out of iTE Cloud |

## Workflow

| Command | Description |
| ------- | ----------- |
| `/plan` | Show plan mode status |
| `/plan on` | Enable plan mode |
| `/plan off` | Disable plan mode |
| `/todos` | Manage task lists |
| `/aside` | Ask in side panel without interrupting main flow |
| `/attach <path>` | Queue files for next message |
| `/clear` | Clear conversation history |
| `/workboard` | Show current plan and todos together |

## Version Control & History

| Command | Description |
| ------- | ----------- |
| `/branch` | List or switch git branches |
| `/branch <name>` | Switch to branch |
| `/branch --create <name>` | Create and switch to new branch |
| `/history` | Show recorded file change sets |
| `/undo` | Revert file changes from last turn |
| `/redo` | Reapply reverted changes |

## Project & Skills

| Command | Description |
| ------- | ----------- |
| `/init` | Analyze project and create AGENTS.md |
| `/init --force` | Overwrite existing AGENTS.md |
| `/skills` | List available skills |
| `/skills show <name>` | Inspect a skill |
| `/skills use <name>` | Activate a skill |
| `/skills add <path>` | Install a skill pack |
| `/skills add owner/repo` | Install from GitHub shorthand |
| `/skills add <git-url>` | Install from Git repository |
| `/skills trust` | Trust project skills |
| `/skills untrust` | Untrust project skills |
| `/skills clear` | Clear all active skills |
| `/skills drop <name>` | Deactivate a skill |
| `/skills help` | Show skills usage help |

## MCP Servers

| Command | Description |
| ------- | ----------- |
| `/mcp` | Show MCP server status |
| `/mcp start <server>` | Connect an MCP server |
| `/mcp stop <server>` | Disconnect an MCP server |
| `/mcp env list [server]` | List MCP environment variables |
| `/mcp env where <server>` | Show where env vars are stored |
| `/mcp env set <server> <KEY> <VALUE>` | Set MCP env var |
| `/mcp env import <server> <KEY>` | Import env var from process |
| `/mcp env unset <server> <KEY>` | Remove MCP env var |
| `/mcp add <server>` | Copy server config between scopes |
| `/mcp doctor <server>` | Diagnose MCP server issues |

## Cloud & Subagents

| Command | Description |
| ------- | ----------- |
| `/cloud status` | Show cloud auth status |
| `/cloud login` | Log in to iTE Cloud |
| `/cloud logout` | Log out of iTE Cloud |
| `/usage` | Show usage summary from iTE Cloud |
| `/activity` | Show recent activity from iTE Cloud |
| `/subagent list` | List available subagents |
| `/subagent create` | Create a new subagent interactively |
| `/subagent delete <name>` | Delete a subagent |
| `/list` | Alias for `/subagent list` |

## Memory & Inspection

| Command | Description |
| ------- | ----------- |
| `/memory` | Inspect active controls and stored memory |
| `/memory prompt <query>` | Debug what memory would be included in a prompt |

## Approval Modes

| Mode | Description |
| ---- | ----------- |
| `on_request` | Ask before every mutating action |
| `on_failure` | Auto-approve, ask only on failure |
| `auto` | Auto-approve all safe operations |
| `auto_edit` | Auto-approve edits, confirm commands |
| `never` | Only allow safe commands, reject all else |
| `yolo` | Approve everything — no guardrails |

---

[Learn about tools →](tools.md)
