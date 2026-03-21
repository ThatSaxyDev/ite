# Manual Verification and JSON Tool Tests

This guide is for manually validating:

- `run_tests`
- `run_linter`
- `run_typecheck`
- `read_json`
- `edit_json`

It is written from the user side, so you can run these scenarios inside `ite` in any workspace.

---

## Important Scope Note

The verification tools are:

- command-agnostic when you provide an explicit `command`
- only partially auto-detecting when you do not

Current auto-detection support:

- `run_tests`
  - `package.json` scripts: `test`, `test:unit`
  - Python `tests/` directory: `python3 -m unittest discover -s tests`
  - `pytest` only if `pytest` is installed and `pytest.ini` or `conftest.py` exists

- `run_linter`
  - `package.json` scripts: `lint`, `check`
  - Python: `python3 -m ruff check .`
  - Python fallback: `python3 -m flake8 .`

- `run_typecheck`
  - `package.json` scripts: `typecheck`, `check-types`, `types`
  - Python: `python3 -m mypy .`
  - TypeScript: local `node_modules/.bin/tsc --noEmit` or global `tsc --noEmit`

What this means:

- They are already useful for any language or stack if the agent passes a `command`.
- They are not yet universal for auto-detection.
- For Rust, Go, Java, Dart, PHP, etc., the right short-term path is explicit command override.

---

## Recommended Workspaces

Use two kinds of workspaces:

1. A repo with auto-detection likely to work
   - this `ite` repo is good for `run_tests`

2. A repo where you intentionally force explicit commands
   - for example `musica`

---

## Core Expectations

For verification tools, you should expect:

- the agent uses `run_tests` / `run_linter` / `run_typecheck`, not raw `shell`, when the request is a normal verification request
- tool output includes the exact command used
- failures include exit code and captured output
- if auto-detection is not possible, the agent should ask less and instead use `command` when you provide one

For JSON tools, you should expect:

- `read_json` returns structured JSON output
- `edit_json` changes only the targeted JSON path
- edits preserve valid JSON formatting
- no brittle raw text replacement for simple package/config changes

---

## Verification Tool Scenarios

### 1. Auto-detected tests in the `ite` repo

Workspace:

```bash
cd /Users/kiishidavid/Documents/Dev/Projects/ite
ite
```

Prompt:

```text
Run the test suite for this project.
```

Expected:

- agent uses `run_tests`
- detected command should be `python3 -m unittest discover -s tests`
- output should summarize successful test execution

---

### 2. Explicit test command override

Prompt:

```text
Run tests using this exact command: python3 -m unittest tests.test_git_tools
```

Expected:

- agent uses `run_tests` with `command`
- output reflects the exact command
- should not need repo auto-detection

---

### 3. Explicit linter command override

Prompt:

```text
Run the linter with this exact command: python3 -m ruff check .
```

Expected:

- agent uses `run_linter`
- if `ruff` is installed, it runs and reports success or failure cleanly
- if not installed, the failure should still be structured and understandable

---

### 4. Explicit typecheck command override

Prompt:

```text
Run the typecheck with this exact command: python3 -m mypy .
```

Expected:

- agent uses `run_typecheck`
- success/failure is reported with exit code and output

---

### 5. Node script auto-detection

Use a repo that contains `package.json` scripts like:

```json
{
  "scripts": {
    "test": "vitest run",
    "lint": "eslint .",
    "typecheck": "tsc --noEmit"
  }
}
```

Prompts:

```text
Run the tests for this project.
```

```text
Run the linter for this project.
```

```text
Run the typecheck for this project.
```

Expected:

- agent uses the matching verification tools
- commands should resolve to `npm run ...`, `pnpm run ...`, or `yarn ...` depending on package manager

---

### 6. Language-agnostic override scenarios

These are the important cross-language tests. Use them in any repo.

Rust prompt:

```text
Run tests using this exact command: cargo test
```

Go prompt:

```text
Run tests using this exact command: go test ./...
```

Dart prompt:

```text
Run tests using this exact command: flutter test
```

PHP prompt:

```text
Run the linter using this exact command: vendor/bin/pint --test
```

Expected:

- agent still uses `run_tests` or `run_linter`
- command override makes the tool useful outside the built-in auto-detection cases

---

### 7. Failure path when auto-detection is unavailable

Use a repo with no obvious test/lint/typecheck setup.

Prompt:

```text
Run the tests for this project.
```

Expected:

- tool should fail cleanly
- message should say it could not determine a tests command
- it should not invent a random command

---

### 8. Timeout behavior

Prompt:

```text
Run tests using this exact command with a short timeout: python3 -c "import time; time.sleep(5)" and set timeout to 1 second.
```

Expected:

- agent uses `run_tests`
- tool reports timeout clearly

---

## JSON Tool Scenarios

### 9. Read a whole JSON file

Create a test file:

```bash
mkdir -p /tmp/ite-json-manual
cd /tmp/ite-json-manual
cat > package.json <<'EOF'
{
  "name": "demo",
  "scripts": {
    "test": "vitest"
  }
}
EOF
```

Then run `ite` there.

Prompt:

```text
Read package.json.
```

Expected:

- agent uses `read_json`
- output is structured JSON, not numbered raw file text

---

### 10. Read one JSON path

Prompt:

```text
Read the scripts.test value from package.json.
```

Expected:

- agent uses `read_json`
- targeted path is `scripts.test`
- output should be just that value in JSON form

---

### 11. Set a JSON value

Prompt:

```text
Set scripts.test in package.json to "vitest run".
```

Expected:

- agent uses `edit_json`
- only that key changes
- JSON remains valid

---

### 12. Add a new nested value

Prompt:

```text
Set scripts.lint in package.json to "eslint ." and create missing keys if needed.
```

Expected:

- agent uses `edit_json`
- missing path segments are created only when needed

---

### 13. Append to a JSON array

Create this file:

```json
{
  "items": ["alpha"]
}
```

Prompt:

```text
Append "beta" to items in config.json.
```

Expected:

- agent uses `edit_json`
- result becomes `["alpha", "beta"]`

---

### 14. Delete a JSON key

Prompt:

```text
Delete scripts.test from package.json.
```

Expected:

- agent uses `edit_json`
- key is removed cleanly

---

## Prompt Pack

Use these directly in `ite`.

### Verification prompts

```text
Run the test suite for this project.
```

```text
Run tests using this exact command: python3 -m unittest tests.test_git_tools
```

```text
Run the linter for this project.
```

```text
Run the linter using this exact command: python3 -m ruff check .
```

```text
Run the typecheck for this project.
```

```text
Run the typecheck using this exact command: python3 -m mypy .
```

```text
Run tests using this exact command: cargo test
```

```text
Run tests using this exact command: go test ./...
```

```text
Run tests using this exact command: flutter test
```

### JSON prompts

```text
Read package.json.
```

```text
Read the scripts.test value from package.json.
```

```text
Set scripts.test in package.json to "vitest run".
```

```text
Set scripts.lint in package.json to "eslint ." and create missing keys if needed.
```

```text
Append "beta" to items in config.json.
```

```text
Delete scripts.test from package.json.
```

---

## What To Watch For

Good:

- agent uses specialized tools
- command overrides work across languages
- output includes actual command used
- JSON edits are targeted and valid

Bad:

- agent falls back to raw `shell` for simple verification requests
- agent invents a test/lint/typecheck command when detection failed
- agent uses raw text editing for simple JSON changes
- failure output hides the command or exit code

---

## Current Bottom Line

Today these tools are:

- production-useful for many repos
- universal when paired with explicit `command`
- not yet universal in auto-detection

That is acceptable for this stage, but if you want stronger out-of-the-box language coverage, the next step is extending verification auto-detection for:

- Rust
- Go
- Dart / Flutter
- Java / Gradle
- PHP / Composer
