# Release Bump Workflow

This document describes the exact workflow to follow when the user says:

- "bump to `X.Y.Z`"
- "let's push `X.Y.Z`"
- "release `X.Y.Z`"

It is written for agents working in this repository.

## Goal

Update the repo to a new package/app version, rebuild the artifacts, and return the exact upload command and affected files.

## Current Version Files

When bumping a version in this repo, update these files:

1. `pyproject.toml`
   - package version
2. `src/ite/main.py`
   - Click `@click.version_option(...)`
3. `src/ite/ui/tui.py`
   - visible legacy TUI version string
4. `src/ite/ui/reup/app.py`
   - visible `reup` version string
5. `README.md`
   - wheel filename examples in the distribution section

## Standard Workflow

### 1. Announce the work

Send a short progress update before doing anything substantial.

Typical phrasing:

- "I’m bumping the package and visible app versions to `X.Y.Z`, then I’ll rebuild so the release artifacts line up with the new version."

### 2. Inspect the current state

Check:

- current version references
- git status

Commands:

```bash
rg -n "OLD_VERSION|NEW_VERSION" pyproject.toml README.md src/ite/main.py src/ite/ui/tui.py src/ite/ui/reup/app.py
git status --short
```

What to note:

- whether the tree is clean
- whether unrelated untracked directories are present

Rule:

- do not modify unrelated untracked directories
- mention them briefly and leave them alone

### 3. Patch the version strings

Use `edit` for single-file version bumps and exact one-file replacements.
Use `apply_patch` only when coordinating the same version change across multiple files in one patch.

Update:

- `pyproject.toml`
- `src/ite/main.py`
- `src/ite/ui/tui.py`
- `src/ite/ui/reup/app.py`
- `README.md`

README must use the actual built artifact naming:

- `ite_agent-X.Y.Z-py3-none-any.whl`

not:

- `ite-X.Y.Z-py3-none-any.whl`

### 4. Verify syntax

Run a quick compile check on the main runtime files:

```bash
python3 -m py_compile src/ite/main.py src/ite/ui/tui.py src/ite/ui/reup/app.py
```

If this fails:

- stop and fix the syntax/runtime import issue before building

### 5. Build release artifacts

Run:

```bash
python3 -m build --no-isolation
```

Expected outputs:

- `dist/ite_agent-X.Y.Z.tar.gz`
- `dist/ite_agent-X.Y.Z-py3-none-any.whl`

### 6. Confirm the artifacts exist

Do not trust shell globbing blindly.

Preferred command:

```bash
find dist -maxdepth 1 -type f | grep 'X.Y.Z'
```

Reason:

- `dist/` may also contain unrelated files like `index.html` or `assets`
- `zsh` no-match behavior can make direct globs misleading during verification

### 7. Return a release summary

The final answer should include:

- version bumped and built
- files updated
- verification commands run
- artifact filenames
- exact TestPyPI upload command

Recommended upload command:

```bash
python3 -m twine upload --repository testpypi dist/ite_agent-X.Y.Z*
```

Do not recommend:

```bash
python3 -m twine upload --repository testpypi dist/*
```

because `dist/` may contain non-distribution files.

## Expected Final Answer Shape

Keep it concise. Include:

1. version bumped and built
2. updated files list
3. verification list
4. artifacts list
5. exact upload command
6. note about unrelated untracked directories if any

Example structure:

```md
`X.Y.Z` is bumped and built.

Updated:
- ...

Verified:
- ...

Artifacts:
- ...

Upload command:
```bash
python3 -m twine upload --repository testpypi dist/ite_agent-X.Y.Z*
```
```

## Behavior Rules

- Use `edit` for single-file replacements.
- Use `apply_patch` for multi-file coordinated edits.
- Do not remove unrelated files from `dist/`.
- Do not modify unrelated untracked directories.
- Do not tag, commit, or push unless the user explicitly asks.
- Do not assume `dist/*` is safe.
- Keep the workflow deterministic and repeatable.

## Optional Follow-Up

If the user asks for git release steps after the bump, provide:

```bash
git add README.md pyproject.toml src/ite/main.py src/ite/ui/tui.py src/ite/ui/reup/app.py
git commit -m "Release X.Y.Z"
git tag vX.Y.Z
git push origin HEAD
git push origin vX.Y.Z
```

Only provide this when asked or when it is clearly the next requested step.
