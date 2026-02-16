# Agent Instructions for ITE

You are working on ITE (Interactive Terminal Agent), a CLI-based AI coding assistant.

## Project Context

- **Working Directory**: `/Users/kiishidavid/Documents/Dev/Projects/ite`
- **Tech Stack**: Python, async/await patterns, Pydantic for config
- **Architecture**: Agent loop → Session (tool registry, LLM client, context) → Tools

## Key Files

- `main.py` - CLI entry point
- `agent/agent.py` - Main agent loop
- `agent/session.py` - Session management
- `tools/registry.py` - Tool invocation
- `client/llm_client.py` - LLM API calls
- `config/config.py` - Configuration models

## Coding Conventions

- Use **async/await** for I/O operations
- Follow existing patterns in each module
- Keep changes minimal and focused
- Add tests for new functionality

## Important Guidelines

1. **File Operations**: Use `read_file`, `edit`, `write_file` tools — avoid shell for file content
2. **Confirmation**: For destructive operations (file deletion, git push), confirm with user first
3. **Error Handling**: Return meaningful errors, don't crash silently
4. **Context**: Be aware of token limits; summarize long conversations when needed
5. **Security**: Never expose secrets, API keys, or passwords in output

## Tool Usage

- `shell`: Run commands only, not for file reading/writing
- `grep`/`glob`: Prefer over shell find commands
- `todos`: Track multi-step tasks

## Before Making Changes

1. read_file relevant files to understand current implementation
2. Check for existing tests in `tests/`
3. Verify with `pytest` or existing test commands

## Workflow

Understand → Plan → Implement → Verify (tests) → Verify (lint/type-check) → Done
