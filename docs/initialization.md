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

### Force overwrite

To regenerate and overwrite an existing `AGENTS.md`:

```
/init --force
```

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
