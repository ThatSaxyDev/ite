# Tools Architecture

This document describes how tools work in this codebase (referred to as "ite").

## Overview

Tools are the primary mechanism for the agent to interact with the external world. They provide capabilities like reading/writing files, executing shell commands, searching the web, and more. The tool system is designed with a plugin-like architecture supporting both builtin tools and external tools via the Model Context Protocol (MCP).

---

## Core Interfaces

### Tool Base Class

**File:** `src/ite/tools/base.py:162-278`

The `Tool` abstract base class defines the interface all tools must implement:

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    @abstractmethod
    def description(self) -> str: ...
    
    @property
    @abstractmethod
    def kind(self) -> ToolKind: ...
    
    @abstractmethod
    async def execute(self, invocation: ToolInvocation) -> ToolResult: ...
```

**Key Methods:**
- `validate_params(params: dict) -> dict` - Validates and sanitizes parameters
- `is_mutating() -> bool` - Returns True if the tool modifies state
- `get_metadata() -> ToolMetadata` - Returns risk level, mutability, output schema
- `get_confirmation() -> ToolConfirmation | None` - Returns confirmation request if needed
- `to_openai_schema() -> dict` - Returns OpenAI function calling format schema

### Tool Kinds

**File:** `src/ite/tools/base.py:14-20`

```python
class ToolKind(Enum):
    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    NETWORK = "network"
    MEMORY = "memory"
    MCP = "mcp"
```

### Risk Levels

**File:** `src/ite/tools/base.py:23-26`

```python
class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
```

---

## Core Data Structures

### ToolInvocation

**File:** `src/ite/tools/base.py:101-103`

```python
@dataclass
class ToolInvocation:
    params: dict                    # Tool parameters
    working_directory: str | None  # Override working directory
```

### ToolResult

**File:** `src/ite/tools/base.py:106-148`

```python
@dataclass
class ToolResult:
    success: bool                   # Whether execution succeeded
    output: str                     # Tool output
    error: str | None               # Error message if failed
    truncated: bool = False         # Whether output was truncated
    diff: str | None = None         # Diff/change info for mutating tools
```

### ToolMetadata

**File:** `src/ite/tools/base.py:29-44`

```python
@dataclass
class ToolMetadata:
    risk_level: ToolRiskLevel       # LOW, MEDIUM, or HIGH
    is_mutating: bool               # Whether tool modifies state
    output_schema: type[BaseModel]  # Schema for tool output
```

### ToolConfirmation

**File:** `src/ite/tools/base.py:151-159`

Request for user confirmation before tool execution (used for high-risk operations).

---

## Tool Registry

**File:** `src/ite/tools/registry.py:25-82`

The `ToolRegistry` class manages tool registration and invocation:

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def register_mcp_tool(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def get_tools(self) -> list[Tool]: ...
    def get_schemas(self) -> list[dict]: ...  # OpenAI function schemas
    def get_tool_contracts(self) -> list[dict]: ...  # Metadata/contracts
    async def invoke(self, name: str, params: dict, context: dict) -> ToolResult: ...
```

### Default Registry Creation

**Files:** `src/ite/tools/registry.py`, `src/ite/agent/session.py`

```python
def create_default_registry(config: Config) -> ToolRegistry:
    registry = ToolRegistry(config)
    
    # 1. Register all builtin tools
    for tool_class in get_all_builtin_tools():
        registry.register(tool_class(config))
    
    # 2. Register subagents against the currently available tool surface
    refresh_subagent_tools(registry, config, log_errors=False)

    return registry

# Later during session initialization:
# - MCP tools are registered
# - discovered workspace/global tools are loaded
# - subagents are refreshed again so allowlists can target those tools too
```

### Tool Invocation Flow

**File:** `src/ite/tools/registry.py:90-324`

The `invoke()` method performs:

1. **Tool Discovery** (Line 118-137): Lookup tool by name
2. **Policy Evaluation** (Line 139-170): Check if tool is allowed based on plan mode/phase
3. **Parameter Validation** (Line 172-196): Validate params against schema
4. **Pre-execution Hooks** (Line 198-201): Trigger `before_tool` hooks
5. **Approval Check** (Line 215-293): Request user confirmation for mutating tools
6. **Execution** (Line 295-305): Call `tool.execute(invocation)`
7. **Post-execution Hooks** (Line 311-315): Trigger `after_tool` hooks

---

## Tool Discovery

**File:** `src/ite/tools/discovery.py:15-74`

The `ToolDiscoveryManager` class loads custom tools from `.ite/tools/*.py` directories:
- Dynamically imports Python modules
- Discovers `Tool` subclasses
- Registers them with the registry

---

## Builtin Tools

All builtin tools are located in `src/ite/tools/builtin/`.

| Tool | File | Description |
|------|------|-------------|
| `read_file` | `src/ite/tools/builtin/read_file.py` | Read file contents with optional offset/limit |
| `write_file` | `src/ite/tools/builtin/write_file.py` | Create or overwrite files |
| `edit_file` | `src/ite/tools/builtin/edit_file.py` | Surgical text replacement edits |
| `apply_patch` | `src/ite/tools/builtin/apply_patch.py` | Apply multi-file patches atomically |
| `shell` | `src/ite/tools/builtin/shell.py` | Execute shell commands |
| `grep` | `src/ite/tools/builtin/grep.py` | Search file contents with regex |
| `glob` | `src/ite/tools/builtin/glob.py` | Find files matching glob patterns |
| `list_dir` | `src/ite/tools/builtin/list_dir.py` | List directory contents |
| `web_search` | `src/ite/tools/builtin/web_search.py` | Perform web searches |
| `web_fetch` | `src/ite/tools/builtin/web_fetch.py` | Fetch and parse web pages |
| `todos` | `src/ite/tools/builtin/todo.py` | Task management |
| `memory` | `src/ite/tools/builtin/memory.py` | Persistent memory storage |
| `plan_question` | `src/ite/tools/builtin/plan_question.py` | Ask user clarifying questions |

### Tool Parameter Schema

Builtin tools use Pydantic for parameter validation:

```python
class ReadFileParams(BaseModel):
    path: str = Field(..., description="Path to the file...")
    offset: int = Field(1, ge=1, description="Line number to start...")
    limit: int | None = Field(None, ge=1, description="Max number of lines...")
```

---

## Subagents

**File:** `src/ite/tools/subagent.py`

Subagents are special tools that delegate to other AI agents for complex tasks.

### Default Subagents

| Subagent | Purpose |
|----------|---------|
| `subagent_codebase_investigator` | Codebase exploration and understanding |
| `subagent_code_reviewer` | Code review and quality analysis |
| `subagent_tooling_guardian` | Tool configuration and safety audit |
| `subagent_verification_reviewer` | Regression testing and validation |

### User-Defined Subagents

Users can define custom subagents in `.ite/subagents/*.toml` - these are discovered automatically.

---

## MCP (Model Context Protocol) Integration

**File:** `src/ite/tools/mcp/`

The codebase supports external tools via MCP:

- `MCPClient` - Communicates with MCP servers
- `MCPTool` - Wraps MCP tools as native `Tool` instances
- `MCPManager` - Manages MCP server connections and tool registration

---

## Tool Policy

**File:** `src/ite/tools/policy.py`

The policy system controls tool eligibility based on:
- **Plan mode**: Planning vs Execution phase
- **Tool kind**: read, write, shell, etc.
- **Mutating status**: Whether tool modifies state
- **Tool name**: Specific allow/deny lists

Key behaviors:
- Blocks mutating tools during planning phase (unless safe shell command)
- Redirects simple lookups from subagents to direct tools when appropriate
- Respects configuration whitelist (`allowed_tools`)

---

## Configuration

**File:** `src/ite/config/config.py:113-116`

```python
allowed_tools: list[str] | None = Field(
    None,
    description="If set only these tools will be available to the agent",
)
```

When `allowed_tools` is set, only the specified tools are available.

---

## Agent Integration

**File:** `src/ite/agent/agent.py:718-991`

The agent uses tools as follows:

1. Gets tool schemas from registry (Line 718):
   ```python
   tool_schemas = session.tool_registry.get_schemas()
   ```

2. Includes tools in LLM API call (Line 808-817)

3. Invokes tools (Line 929):
   ```python
   result = await session.tool_registry.invoke(...)
   ```

---

## Tool Execution Flow Diagram

```
Agent decides to use tool
            |
            v
   ToolRegistry.invoke(name, params, context)
            |
            v
   Policy Evaluation (allowed for current phase?)
            |
            v
   Parameter Validation (matches schema?)
            |
            v
   Pre-execution Hooks (before_tool)
            |
            v
   User Approval (for mutating tools if required)
            |
            v
   Tool.execute(invocation)
            |
            v
   Post-execution Hooks (after_tool)
            |
            v
   Return ToolResult to agent
```

---

## Extending the Tool System

To add a new builtin tool:

1. Create a new file in `src/ite/tools/builtin/`
2. Define parameter schema (Pydantic `BaseModel`)
3. Create a tool class inheriting from `Tool`
4. Implement `execute()` method
5. Register in `get_all_builtin_tools()` in `src/ite/tools/__init__.py`

Example structure:

```python
# src/ite/tools/builtin/my_tool.py
from pydantic import BaseModel, Field
from ite.tools.base import Tool, ToolKind, ToolResult, ToolMetadata, ToolRiskLevel

class MyToolParams(BaseModel):
    param1: str = Field(..., description="Description")

class MyTool(Tool):
    def __init__(self, config: Config):
        self.config = config
    
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "Description of what my tool does"
    
    @property
    def kind(self) -> ToolKind:
        return ToolKind.READ  # or WRITE, SHELL, NETWORK
    
    @property
    def params_schema(self) -> type[BaseModel]:
        return MyToolParams
    
    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            risk_level=ToolRiskLevel.LOW,
            is_mutating=False,
            output_schema=MyToolOutput,
        )
    
    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = self.validate_params(invocation.params)
        # Implement tool logic
        return ToolResult(success=True, output="...")
```
