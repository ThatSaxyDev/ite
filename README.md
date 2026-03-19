# ITE - Interactive Terminal Environment

An AI coding agent for your terminal.

## Installation

### Option 1: Development Install (Local)

Clone the repository and install in editable mode:

```bash
git clone https://github.com/yourusername/ite.git
cd ite
pip install -e .
```

### Option 2: Install from Source (Global)

Install globally using `pipx` (recommended) or `pip`:

```bash
### Method 1: The Best Experience (Recommended)
We recommend using **pipx** to install `ite`. This ensures the `ite` command is available globally without conflicting with other Python packages.

1. **Install pipx** (if you haven't already):
   ```bash
   brew install pipx
   pipx ensurepath
   ```
   *(Restart your terminal after this)*

2. **Install ite-agent**:
   ```bash
   pipx install ite-agent
   ```

3. **Run it**:
   ```bash
   ite
   ```

### Method 2: Standard Pip
If you prefer standard pip:
```bash
pip install ite-agent
```
*Note: You may need to add your Python binary location to your PATH to run the `ite` command directly.*
```

### Option 3: Install from Git

```bash
pipx install git+https://github.com/yourusername/ite.git
```

## Distribution

To distribute ITE, you can build a wheel file:

1. Install `build`:
   ```bash
   pip install build
   ```

2. Build the package:
   ```bash
   python -m build
   ```

This generates `dist/ite_agent-0.0.14-py3-none-any.whl`, which can be shared and installed anywhere:

```bash
pipx install ite_agent-0.0.14-py3-none-any.whl
```

## Usage

```bash
# Start interactive session
ite
```

## Configuration

Run `ite` for the first time to set up your API credentials interactively.
Or use the `/setup` command within the tool.

## Architecture

ITE is an AI coding agent combining four major capabilities: a terminal UI for interactive conversation, tool execution with policy controls, persistent multi-layered memory, and session-based state management with recovery features.

### Core Components

**CLI (`main.py`)** — The main orchestrator handles terminal interaction: reading multi-line input with paste detection, processing slash commands, detecting user intent for planning vs execution, and rendering the TUI. It includes intelligent paste detection that waits briefly for follow-up lines, intent detection that prompts users to enable/disable plan mode appropriately, and auto-save after every agent turn plus checkpoints every 5 turns.

**Agent (`agent/agent.py`)** — Drives the core agentic loop with plan mode handling, memory integration, response controls, and automatic todo progression.

- **Plan Mode**: A state machine with phases "idle" → "asking_questions" → "writing_plan" → "awaiting_implementation_confirmation" → "executing". The agent asks 3-5 clarifying questions based on task complexity, then writes a plan for user approval before execution begins.
- **Execution Mode**: Seeds todo items automatically from multi-step user requests, then auto-completes them based on tool invocations (file writes complete implementation todos, test/lint commands complete verification todos).
- **Memory Integration**: Intercepts explicit memory instructions ("remember...") and exact recall probes ("what phrase did I ask you to remember") for direct processing without LLM calls.
- **Response Controls**: Reads user preferences from memory and adjusts outputs (e.g., flattening bullet points if user prefers that).

**Session (`agent/session.py`)** — Maintains all per-conversation state including the LLM client, tool registry, context manager, memory manager, plan state, todo tool, change history, hook system, and MCP manager.

**Session Persistence (`agent/session_manager.py`)**

- Sessions stored in `{data_dir}/sessions/{session_id}.json`
- Checkpoints in `{data_dir}/checkpoints/{session_id}_{timestamp}.json`
- Snapshot compaction keeps the 12 most recent tool results intact, truncates older ones to 480 chars, tool call args to 320 chars, and messages over 12K chars
- Atomic writes with fsync for reliability
- Automatic quarantine of corrupt session files

### Memory System (`memory/manager.py`)

Four stores with different scopes:

| Store | Scope | Location |
|-------|-------|----------|
| short_term | Per-session | `{data_dir}/memory/sessions/{session_id}/` |
| long_term | User-global | `{data_dir}/memory/long_term.json` |
| semantic | Per-workspace | `{data_dir}/memory/projects/{hash}/semantic.json` |
| episodic | Per-workspace | `{data_dir}/memory/projects/{hash}/episodic.json` |

Retrieval uses weighted scoring: lexical match (query terms in key/summary/value), hotness (recency × access frequency with 7-day half-life decay), and store-specific boosts to favor recent over global memory. Supports conditional preferences that activate only in specific query contexts (e.g., "prefer bullet lists when explaining architecture").

### Tools System

- **Registry** (`tools/registry.py`): Maintains available tools with OpenAI function-calling schemas
- **Builtin Tools** (`tools/builtin/`): todos (planning/execution scopes), memory, plan_question, file operations, shell, glob, grep, web_search, web_fetch
- **MCP Integration** (`tools/mcp/`): Connects to external MCP servers, transparently registering their tools
- **Policy** (`tools/policy.py`): Sandbox restrictions for file operations
- **Approval Manager**: Gates dangerous operations (deletions, destructive shell) with TUI callbacks

### Context Management (`context/manager.py`)

Maintains conversation history with token estimation, triggers compression via ChatCompactor when nearing limits, and prunes tool outputs. Compression generates a summary using the LLM and records it as an episodic memory entry.

### Additional Subsystems

- **Loop Detector** (`context/loop_detector.py`): Detects repetitive patterns and injects loop-breaker prompts
- **Change History** (`agent/change_history.py`): Records file diffs from successful writes
- **Hook System** (`hooks/`): Lifecycle callbacks (before/after agent runs)
- **TUI** (`ui/tui.py`): Rich-based terminal UI with streaming, tool visualization, and confirmation prompts
