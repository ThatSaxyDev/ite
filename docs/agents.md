# AGENTS.md

`AGENTS.md` files provide project-specific instructions to iTE, similar to how `README.md` works for humans.

## Creating AGENTS.md

Use the `/init` command:

```
/init
```

Or create it manually at your project root.

## Scope Hierarchy

`AGENTS.md` files support scope-based overrides:

- The file covers its directory and all subdirectories
- Deeper files override parent files for their scope
- Multiple files can exist in one project

Example:

```
/AGENTS.md           # Root instructions (all files)
/src/
/src/web/
/src/web/AGENTS.md   # Frontend-specific instructions
/src/api/            # Follows root instructions
/tests/              # Follows root instructions
```

## Example

```markdown
# My Project

## Architecture
- Python/FastAPI backend in src/api/
- React frontend in src/web/

## Development Guidelines
- Use pytest for tests
- Run `make test` before committing
- Prefer `read_json`/`edit_json` for structured files
- Follow PEP 8 for Python code

## Tool Preferences
- Use `uv` for package management
- Use `ruff` for linting
- Test commands: `pytest tests/`
```

## Effective Use

- Keep instructions concise (200-500 words)
- Focus on project-specific conventions
- Avoid duplicating general iTE capabilities
- Update when conventions change

---

[Learn about skills →](skills.md)
