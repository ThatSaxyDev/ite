# iTE — an agent that lives in the terminal

iTE is a terminal-native coding agent. Point it at a repository and it reads the code, plans changes, runs tools, and shows you a reviewable diff before anything lands. It installs as a single binary or a Python package, talks to any OpenAI-compatible provider, and keeps the awkward parts — approvals, undo, session history, context compaction — in the terminal instead of a browser tab.

## Setup

Three commands, in order.

```bash
curl -fsSL https://ite.kiishi.space/install.sh | bash
```

The installer in [`install.sh`](install.sh) detects your OS and architecture, verifies each download against the release manifest, and puts `ite` on your PATH. (Windows PowerShell: `irm https://ite.kiishi.space/install.ps1 | iex`.)

```bash
ite --version
```

Expect `ite, version 0.2.21`. Then launch it from inside the project you want to work on:

```bash
ite
```

First run opens a Textual UI and prompts for a provider. `/setup` accepts Ollama, OpenRouter, or OpenAI; credentials land in `~/.ite/config.toml`, and `API_KEY` / `BASE_URL` in your environment override the file. See [`docs/configuration.md`](docs/configuration.md) and [`docs/installation.md`](docs/installation.md).

## First 10 minutes

1. **Aim it at a real project.** `cd` into the repository root and run `ite`. That directory becomes the workspace.

2. **Teach it the repo.** Run `/init` in the composer. iTE scans the project and writes an `AGENTS.md` — architecture, conventions, and which commands verify a change. Commit it; the next session starts smarter.

3. **Ask something read-only first.** `How is auth handled?` You get an answer with file references and no files touched — a cheap way to confirm the model actually knows your codebase.

4. **Make a real change, with a plan.** Run `/plan on`, describe the change, read the plan, then `/plan off` and say "go ahead." Plan mode is why the diff lands the way you expected instead of the way the model felt like.

5. **Check the work, and keep it.** Review the change set, then run `pytest` yourself. `/undo` reverts the last turn if you disagree. Nothing is final until you say so.

Full command reference: [`docs/commands.md`](docs/commands.md). Everyday usage: [`docs/usage.md`](docs/usage.md).

## Contributor challenge: fix the empty-string token estimate

[`src/ite/utils/text.py:30`](src/ite/utils/text.py) defines:

```python
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
```

The `max(1, ...)` floor was added to stop `count_tokens("")` from returning `0` and being mistaken for "no content." But it lies in the other direction too: a genuinely empty string now reports as one token, so any caller budgeting a prompt with this fallback over-counts by one on every empty field — attachments, tool results, empty diffs.

**The change:** make the floor apply only to non-empty input, so `estimate_tokens("")` returns `0` while `estimate_tokens("abcd")` still returns `1`. Check every caller in `src/ite/context/` before you change it — a zero that used to mean "unknown" now means "empty," and compaction logic must not treat those the same.

**The test:** add a case to [`tests/test_text_utils.py`](tests/test_text_utils.py) next to `test_count_tokens_falls_back_to_estimate_when_tiktoken_is_unavailable`, then run:

```bash
pytest tests/test_text_utils.py -q
```
