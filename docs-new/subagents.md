# Subagents

Subagents are specialized AI agents that handle specific tasks independently. They run in parallel and return structured results to the main agent.

## What Are Subagents?

Subagents extend iTE's capabilities by delegating complex tasks to specialist agents:

- **Security Auditor** — Audits code for vulnerabilities
- **Code Reviewer** — Reviews code changes for quality
- **Codebase Investigator** — Explores and summarizes code structure
- **Tooling Guardian** — Audits tool configurations
- **Verification Reviewer** — Validates changes against regression risks
- **Init Investigator** — Generates AGENTS.md by analyzing projects

## Using Subagents

### Listing Available Subagents

```
/subagent list
```

### Spawning a Subagent

```
spawn_subagent subagent="security_auditor" goal="Audit the authentication module"
```

### Parallel Execution

Spawn multiple subagents at once:

```
spawn_subagents requests=[
  {subagent: "code_reviewer", goal: "Review PR changes"},
  {subagent: "security_auditor", goal: "Check for SQL injection risks"}
]
```

### Waiting for Results

```
wait_subagent run_ids=["run_abc123"] return_when="all_completed" timeout_seconds=300
```

## Built-in Subagents

| Subagent | Purpose |
|----------|---------|
| `security_auditor` | Security vulnerability analysis |
| `code_reviewer` | Code quality review |
| `codebase_investigator` | Explore code structure and patterns |
| `tooling_guardian` | Validate tool configurations |
| `verification_reviewer` | Regression-focused change validation |
| `init_investigator` | Generate AGENTS.md for projects |

## Creating Custom Subagents

Use `/subagent create` to define custom subagents interactively:

1. **Name** — Unique identifier (no spaces)
2. **Description** — What the subagent does
3. **Goal Prompt** — System instructions for the specialist
4. **Allowed Tools** — Which tools the subagent can use (empty = all)

Custom subagents are saved to `.ite/subagents/<name>.toml`.

### Example Subagent Configuration

```toml
name = "api_tester"
description = "Tests API endpoints and validates responses"
allowed_tools = ["http_request", "read_file", "write_file"]

goal_prompt = """
You are an API testing specialist. Your job is to:
1. Read API specifications from the codebase
2. Test endpoints using http_request
3. Validate responses against expected schemas
4. Report findings in a structured format
"""
```

## Deleting Subagents

```
/subagent delete <name>
```

## Subagent Runtime

- Subagents run with **isolated context**
- **Limited tool access** based on configuration
- Results returned as **structured output**
- Can be **cancelled** if no longer needed

## Best Practices

1. **Use for parallelizable tasks** — Multiple independent reviews, audits, or searches
2. **Keep goals specific** — Clear, focused tasks get better results
3. **Limit tools when possible** — Reduces risk and improves performance
4. **Set appropriate timeouts** — Match timeout to task complexity

## Example Workflows

### Security Review

```
# Spawn security audit
spawn_subagent subagent="security_auditor" goal="Audit src/auth/ for vulnerabilities"

# Wait for results
wait_subagent run_ids=["..."] return_when="all_completed"
```

### Pre-Commit Validation

```
# Parallel validation
spawn_subagents requests=[
  {subagent: "code_reviewer", goal: "Review changes in src/"},
  {subagent: "verification_reviewer", goal: "Check for regression risks"}
]
```

### Project Initialization

```
/init
```

This spawns `init_investigator` to analyze your project and create AGENTS.md.

---

[Back to commands →](commands.md)
