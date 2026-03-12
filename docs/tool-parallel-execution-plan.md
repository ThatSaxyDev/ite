# Plan: Enable Parallel Tool Execution for Independent Read Operations

## Summary

Improve tool calling throughput by executing independent read-only tools concurrently using `asyncio.gather`. Mutating tools (write/shell) will still run sequentially. The agent loop in `src/ite/agent/agent.py` will be modified to group tool calls into parallel batches based on tool kind.

## Current State

Tool calling is handled in `src/ite/agent/agent.py` within the `_agentic_loop` method:

1. **Parse** - LLM responses are parsed in `client/llm_client.py` to extract `ToolCall` objects
2. **Emit START** - For each tool call, emit `TOOL_CALL_START` event
3. **Execute** - Tools are invoked sequentially via `session.tool_registry.invoke()`
4. **Emit COMPLETE** - Emit `TOOL_CALL_COMPLETE` event with result
5. **Add to context** - Tool results are added back to conversation context
6. **Loop** - Agent loops back to send results to LLM for next turn

**Key behaviors:**
- Sequential execution - Tools run one at a time, not in parallel
- Plan mode special handling - `plan_question` tool is prioritized

## Implementation Changes

### 1. Dependency Analysis (`src/ite/tools/base.py`)

Add method to `Tool` class to determine parallelizability. Read tools (`ToolKind.READ`) are parallelizable; mutating tools are not.

```python
# In Tool class:
def can_run_parallel_with(self, other_tool: "Tool") -> bool:
    """Check if this tool can run in parallel with another tool."""
    # Read tools can run in parallel with each other
    if self.kind == ToolKind.READ and other_tool.kind == ToolKind.READ:
        return True
    return False
```

### 2. Tool Call Batching (`src/ite/agent/agent.py`)

After collecting `tool_calls` from LLM, group into batches:

- **Batch 1**: All read-only tools → run via `asyncio.gather`
- **Batch 2** (sequentially): Mutating tools after reads complete

```python
# Group tool calls
read_tool_calls = []
mutating_tool_calls = []

for tool_call in tool_calls:
    tool = session.tool_registry.get(tool_call.name)
    if tool and tool.kind == ToolKind.READ:
        read_tool_calls.append(tool_call)
    else:
        mutating_tool_calls.append(tool_call)

# Execute reads in parallel
if read_tool_calls:
    # Emit START events for all
    for tc in read_tool_calls:
        yield AgentEvent.tool_call_start(tc.call_id, tc.name, tc.arguments)
    
    # Run in parallel
    read_results = await asyncio.gather(*[
        session.tool_registry.invoke(...)
        for tc in read_tool_calls
    ])
    
    # Emit COMPLETE events
    for tc, result in zip(read_tool_calls, read_results):
        yield AgentEvent.tool_call_complete(tc.call_id, tc.name, result)

# Execute mutating sequentially (existing behavior)
for tool_call in mutating_tool_calls:
    ...
```

### 3. Tool Registry Enhancement (`src/ite/tools/registry.py`)

Add helper method to check if tool is parallelizable with others:

```python
def is_tool_parallelizable(self, name: str) -> bool:
    tool = self.get(name)
    return tool and tool.kind == ToolKind.READ
```

Consider tool-level timeout to prevent hanging parallel tasks.

### 4. Event Emission

- Emit individual `TOOL_CALL_START` events for all parallel tools before execution
- Then gather results and emit `TOOL_CALL_COMPLETE` after all finish
- Ensure UI (TUI/GUI) can handle multiple concurrent tool calls

## Tests & Validation

### Unit Tests

- **test_tool_grouping**: Verify read tools grouped together, mutating separated
- **test_parallel_execution**: Mock 2+ read tools, verify concurrent execution using `asyncio.gather`
- **test_sequential_fallback**: Verify mutating tools wait for reads to complete
- **test_mixed_batch**: Mix of read + mutating tools executes correctly

### Integration Tests

- Agent with multiple `read_file` calls in one turn
- Mix of `grep` + `read_file` + `write_file` in one turn

### Manual Verification

- Run agent with `grep` + `read_file` in same turn; verify they run in parallel
- Verify timing improvement (optional logging)

## Assumptions & Risks

### Assumptions

- Tool dependencies only matter at the kind level (read vs mutating), not file-level
- True dependency analysis (e.g., "can't read X until write Y completes") would require more complex graph analysis

### Risks

- **Memory**: Parallel tools may have higher total memory usage
  - **Mitigation**: Limit parallel batch size (e.g., max 5 concurrent)
- **Failure handling**: If one tool in parallel batch fails, others continue
  - **Decision**: This is desired behavior - fail-fast for individual tools
- **Rollback**: Changes isolated to agent loop; can revert to sequential by removing batching logic

## Implementation Order

1. Add `ToolKind` check to registry (Step 3)
2. Modify agent loop to batch tool calls (Step 2)
3. Add unit tests
4. Integration testing