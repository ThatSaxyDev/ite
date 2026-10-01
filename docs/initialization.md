# Initialization

Projects can include an `AGENTS.md` file at the root to provide instructions to iTE on how to work with the codebase.

## `/init` Command

The `/init` command analyzes your project and creates an `AGENTS.md` file:

```
/init
```

This detects:
- Language/framework (Python, JavaScript, Rust, etc.)
- Test/build setup
- Key directory structure

The investigator reads project guidance, manifests, entry points, representative
source files and tests. It uses targeted code searches and finishes when it has
enough evidence. The chat feed shows actual investigation activity in a single
card styled like `/workboard`, followed by the saved file, size and instruction
activation status.

Before saving, iTE checks document structure, repository paths, command sources
and the combined instruction budget. Markdown is accepted directly; file-read
evidence is captured from successful tool calls rather than requiring the model
to format a JSON envelope. An invalid draft gets one focused revision attempt,
limited to four cycles and two minutes within the same overall deadline, without
repeating broad discovery. Oversized output is never cut off. Failures leave the
existing file intact; Ctrl+C stops initialization and cancels the investigator.
Initialization runs in a background worker so the UI remains responsive to the
interrupt key. Successfully generated
instructions become available in the current chat immediately.

If a usable draft still fails validation, the unapplied response is retained under
`.ite/init-drafts/` and its path appears in the result card. It is never activated
as project instructions. The investigator uses local read tools and does not
reconnect MCP servers or run hooks.

### Investigation and instruction budgets

Configure these settings in `.ite/config.toml` or `~/.ite/config.toml`:

```toml
init_max_turns = 40
init_timeout_seconds = 600
agents_max_bytes = 32768
```

`init_max_turns` limits model/tool cycles per investigation attempt, rather than
the number of files read. The time limit covers investigation, retries and draft
revision together. Instruction size is a separate budget: `agents_max_bytes`
applies to all applicable AGENTS files combined, including framing. Increase it
when a project needs more guidance, accounting for the model's context capacity.
The loader explicitly reports files omitted because of this budget; `/init`
rejects a draft that would cause any applicable instructions to be omitted.

Keep root guidance focused and link to detailed project documentation. Nested
AGENTS files are useful for rules specific to a subtree.

### Force overwrite

To regenerate and overwrite an existing `AGENTS.md`:

```
/init --force
```

Regeneration asks the investigator to preserve existing maintainer constraints.
If the file changes while investigation runs, iTE refuses to replace it. A local
`AGENTS.override.md` takes precedence, so `/init` reports that override instead of
creating an AGENTS file that would not be used.

## AGENTS.md Scope

`AGENTS.md` files support scope hierarchy:

- The scope is the directory containing the file and all subdirectories
- Deeper files override parent instructions
- Multiple files can exist in a project, each governing its subtree

Example structure:

```
/AGENTS.md              # Root-level instructions
/src/                   # Follows root instructions
/src/api/               # Follows root instructions
/src/web/               # Follows root instructions
/src/web/AGENTS.md      # Specific to frontend code
/tests/                 # Follows root instructions
/docs/                  # Follows root instructions
```

## What to Include

Typical `AGENTS.md` contents:

- **Architecture overview**: How the project is structured
- **Coding conventions**: Style guides, naming patterns
- **Testing approach**: How to run tests, what to verify
- **Tool preferences**: Which tools to use for which tasks
- **Workflow guidelines**: Code review process, commit standards

---

## Next Steps

[Learn everyday usage →](usage.md)
