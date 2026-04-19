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

## Configuration

| Command | Description |
| ------- | ----------- |
| `/setup` | Configure model provider |
| `/config` | View current configuration |
| `/model <name>` | Change model |
| `/approval <mode>` | Set approval mode: `on_request`, `on_failure`, `auto`, `auto_edit`, `yolo` |
| `/stats` | Show token usage statistics |
| `/tools` | List available tools |
| `/theme` | Change UI theme |

## Workflow

| Command | Description |
| ------- | ----------- |
| `/plan` | Toggle plan mode on/off |
| `/todos` | Manage task lists (use `todos` tool for persistent tasks) |
| `/aside` | Ask in side panel without interrupting main flow |
| `/attach <path>` | Queue files for next message |
| `/clear` | Clear the screen |

## Version Control & History

| Command | Description |
| ------- | ----------- |
| `/branch` | List or switch git branches |
| `/branch <name>` | Create and switch to new branch |
| `/history` | Show recent messages |
| `/undo` | Revert file changes from last turn |
| `/redo` | Reapply reverted changes |
| `/workboard` | Show current plan and todos |

## Project & Skills

| Command | Description |
| ------- | ----------- |
| `/init` | Analyze project and create AGENTS.md |
| `/skills` | List available skills |
| `/skills use <name>` | Activate a skill |
| `/skills add <path>` | Install a skill pack |
| `/skills trust` | Trust project skills |
| `/mcp` | Show MCP server status |
| `/mcp start <server>` | Connect MCP server |
| `/mcp stop <server>` | Disconnect MCP server |

## Cloud & Subagents

| Command | Description |
| ------- | ----------- |
| `/cloud <action>` | Manage cloud features |
| `/subagent <name>` | Use a subagent |
| `/list` | List subagents |
| `/sandbox` | Manage filesystem sandbox |

## Help

| Command | Description |
| ------- | ----------- |
| `/help` | Show all commands |
| `/help <command>` | Show detailed help for a command |
