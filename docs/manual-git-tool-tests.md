# Manual Git Tool Tests

This guide is for manually validating the first-class git tools from the user side.

Tools covered:
- `git_status`
- `git_diff`
- `git_log`
- `git_branch`
- `git_commit`
- `git_push`

---

## Recommended Setup

Use a disposable repository so you can test mutating flows safely.

### Create a scratch repo

```bash
mkdir -p /tmp/ite-git-tool-test
cd /tmp/ite-git-tool-test
git init
git config user.name "ITE Manual Test"
git config user.email "ite-manual@example.com"
printf "print('hello')\n" > app.py
git add app.py
git commit -m "initial commit"
```

Then point `ite` at that workspace.

---

## Core Scenarios

### 1. Clean repository status

User prompt:

```text
Show me the git status for this repo.
```

Expected:
- agent uses `git_status`, not `shell`
- reports current branch
- reports clean working tree
- metadata should imply `clean=true`

### 2. Mixed staged, unstaged, and untracked changes

In the repo:

```bash
printf "print('changed')\n" > app.py
printf "print('staged')\n" > staged.py
git add staged.py
printf "print('new')\n" > untracked.py
```

User prompt:

```text
What changed in git right now?
```

Expected:
- agent uses `git_status`
- output distinguishes staged, unstaged, and untracked
- per-file state is coherent
- `app.py` should be unstaged
- `staged.py` should be staged
- `untracked.py` should be untracked

### 3. Diff for one file

User prompt:

```text
Show me the diff for app.py only.
```

Expected:
- agent uses `git_diff`
- output contains diff for only `app.py`
- metadata selection reflects filtered diff

### 4. Staged-only diff

User prompt:

```text
Show me only the staged diff.
```

Expected:
- agent uses `git_diff` with staged filter
- output excludes unstaged-only changes

### 5. Commit history

User prompt:

```text
Show me the last 5 commits.
```

Expected:
- agent uses `git_log`
- output is concise and ordered newest first
- commit subjects match actual history

### 6. Branch listing

User prompt:

```text
List my local branches.
```

Expected:
- agent uses `git_branch` with list action
- current branch is called out

### 7. Create a branch

User prompt:

```text
Create a new branch called feature/manual-test.
```

Expected:
- agent uses `git_branch`
- approval is requested because the action mutates repo state
- after approval, branch switches successfully

### 8. Commit staged changes

Stage the desired files first if needed.

User prompt:

```text
Commit the staged changes with message: add staged file.
```

Expected:
- agent uses `git_commit`
- approval is requested
- commit succeeds
- latest commit message matches prompt

### 9. Commit including unstaged changes

Make a new unstaged edit.

User prompt:

```text
Commit everything with message: save current work.
```

Expected:
- agent may use `git_commit` with `include_unstaged=true`
- approval is requested
- resulting commit contains staged and unstaged work

### 10. Push without remote

User prompt:

```text
Push this branch.
```

Expected:
- agent uses `git_push`
- if no remote exists, failure is clean and understandable
- error should not be a raw git dump unless git provided no better signal

---

## Publish and Push Scenarios

### 11. Remote exists but branch is unpublished

Create a bare remote and attach it:

```bash
mkdir -p /tmp/ite-git-remote.git
git init --bare /tmp/ite-git-remote.git
git remote add origin /tmp/ite-git-remote.git
```

User prompt:

```text
What is the git status now?
```

Expected:
- `git_status` reports that publish is required
- metadata should indicate `needs_publish=true`
- output should mention publish intent, not just raw ahead counts

### 12. Push/publish to remote

User prompt:

```text
Publish this branch.
```

Expected:
- agent uses `git_push`
- approval is requested
- branch is pushed with upstream tracking if needed

---

## Failure Scenarios

### 13. Not a git repo

Open `ite` in a non-git directory.

User prompt:

```text
Show me the git status.
```

Expected:
- tool fails cleanly
- user gets a direct “not a git repository” style message

### 14. Invalid branch name

User prompt:

```text
Create a branch called bad branch name.
```

Expected:
- `git_branch` rejects the branch name cleanly
- user sees a validation-style error, not a stack trace

### 15. Commit with no staged changes

User prompt:

```text
Commit the staged changes with message: noop.
```

Expected:
- `git_commit` fails cleanly with a “No staged changes to commit” style result

---

## What To Watch For

These are the main product-level checks:

- The agent prefers the git tools over `shell` for normal git tasks.
- Read-only git requests do not ask for approval.
- Mutating git requests do ask for approval.
- Output is concise for the user but metadata is structured enough for the model.
- Failure cases are translated into understandable messages.

---

## Suggested User Prompts

If you want a fast smoke test, these prompts are enough:

1. `Show me the git status for this repo.`
2. `Show me only the staged diff.`
3. `Show me the last 3 commits.`
4. `Create a branch called feature/manual-test.`
5. `Commit the staged changes with message: manual test commit.`
6. `Push this branch.`

---

*Created: March 20, 2026*
