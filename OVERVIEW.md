# ITE - AI Coding Agent

ITE (Interactive Terminal Agent) is a CLI-based AI coding assistant that helps developers accomplish tasks through natural language commands. It leverages large language models (LLMs) with a rich set of tools for file operations, code execution, and task management.

## Overview

ITE operates as an autonomous agent that:
- Executes tasks iteratively until completion or max turns reached
- Uses tools to interact with the filesystem, run shell commands, and manage code
- Supports both single-prompt and interactive CLI modes
- Integrates with MCP (Model Context Protocol) servers for extended capabilities

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI (main.py)                        │
│                    Interactive / Single Mode                 │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                     Agent (agent/agent.py)                    │
│              Main agentic loop & orchestration               │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                    Session (agent/session.py)                │
│      Tool Registry │ LLM Client │ Context Manager           │
└──────────┬──────────────────────┬────────────────────────────┘
           │                      │
    ┌──────▼──────┐      ┌───────▼──────┐
    │    Tools    │      │   Context    │
    │ (tools/*)   │      │ (context/*)  │
    └─────────────┘      └──────────────┘
```

## Core Components

### Agent (`agent/`)
- **agent.py** - Main `Agent` class implementing the agentic loop (LLM calls → tool execution → repeat)
- **session.py** - `Session` management including tool registry, LLM client, and context
- **events.py** - Event types for streaming responses (text deltas, tool calls, errors)

### Client (`client/`)
- **llm_client.py** - OpenAI-compatible API client with streaming support, retries, and rate limiting
- **response.py** - Response parsing for tool calls, tokens, and streaming events

### Config (`config/`)
- **config.py** - Pydantic models for configuration (model, shell environment, MCP servers)
- **loader.py** - Configuration loading from environment and `.ite/` directory

### Tools (`tools/`)
- **registry.py** - `ToolRegistry` for registering and invoking tools
- **base.py** - Base `Tool` class and `ToolResult` types
- **builtin/** - Built-in tools:
  - `read_file`, `write_file`, `edit_file` - File operations
  - `shell` - Execute shell commands
  - `grep`, `glob` - Search and discovery
  - `list_dir` - Directory listing
  - `memory`, `todo` - Task management
  - `web_search`, `web_fetch` - Web utilities
- **subagent.py** - Subagent tool for delegating to specialized agents
- **subagent_loader.py** - Loads user-defined subagents from `.ite/subagents/`
- **mcp/** - MCP server integration
- **discovery.py** - Tool discovery manager

### Context (`context/`)
- **manager.py** - Message history and context management for LLM conversations

### Prompts (`prompts/`)
- **system.py** - Dynamic system prompt generation with environment info, tool guidelines, and operational instructions

### UI (`ui/`)
- **tui.py** - Rich-based terminal UI for interactive mode with streaming display

## Configuration

ITE is configured via:
1. **Environment Variables**:
   - `API_KEY` - LLM API key
   - `BASE_URL` - LLM API endpoint
   - `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. (alternative keys)

2. **`.ite/config.toml`** (optional):
   ```toml
   [model]
   name = "gpt-4o"
   temperature = 1.0

   [shell_environment]
   ignore_default_excludes = false
   exclude_patterns = ["*KEY*", "*SECRET*", "*TOKEN*"]

   max_turns = 100
   
   [mcp_servers.server_name]
   enabled = true
   command = "npx"
   args = ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
   ```

3. **`.ite/subagents/`** - User-defined subagents as TOML files

## Usage

### Interactive Mode
```bash
python main.py
```

### Single Prompt
```bash
python main.py "Fix the bug in src/auth.py"
```

### With Custom Directory
```bash
python main.py -c /path/to/project "Analyze this codebase"
```

## Subagents

Subagents are specialized AI agents with focused goals. Default subagents include:
- **Codebase Investigator** - Explore and understand code structure
- **Code Reviewer** - Review code changes for bugs and improvements
- **Security Auditor** - Audit code for security vulnerabilities

Users can create custom subagents in `.ite/subagents/`:
```toml
name = "my-agent"
description = "Description of what this agent does"
allowed_tools = ["read_file", "grep", "shell"]

goal_prompt = """
You are an agent that...
"""
```

## Tool Execution Flow

1. Agent sends message to LLM with available tool schemas
2. LLM responds with text and/or tool calls
3. For each tool call:
   - Emit `TOOL_CALL_START` event
   - Invoke tool via registry
   - Emit `TOOL_CALL_COMPLETE` with result
4. Add tool results to conversation context
5. Repeat until LLM responds without tool calls or max turns reached
