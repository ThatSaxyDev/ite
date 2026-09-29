# Repository tour

## Why this exists

`AGENTS.md` and `DESIGN.md` describe the architecture, but neither answers the
first question a new contributor asks: *where do I actually start reading?* A
wrong first hour is expensive in a codebase this size, and a hand-written
onboarding section in `README.md` goes stale the moment a file moves.

`scripts/repository_tour.py` solves that by being executable rather than
prose. It is a small, standard-library-only script that prints four stops, each
naming real paths in the tree and explaining why a contributor would visit
them. Because the paths are data inside the script, the tour cannot rot
silently: `tests/test_repository_tour.py` fails if a stop references a path that
no longer exists.

The tour is deliberately not wired into the CLI. It is a contributor aid, not a
user-facing feature, so it stays out of `src/ite/`.

## How to run it

From the repository root:

```bash
python scripts/repository_tour.py
```

Machine-readable output:

```bash
python scripts/repository_tour.py --format json
```

The script locates the repository root by walking upward from the current
directory, so it also works from a subdirectory:

```bash
cd src/ite && python ../../scripts/repository_tour.py
```

Options:

| Flag | Effect |
|------|--------|
| `--format {text,json}` | Output format; `text` is the default. |
| `--root PATH` | Start the root search at `PATH` instead of the current directory. |

Exit codes: `0` on success, `2` when the repository root cannot be found (the
error message names the markers it looked for and shows the command to run).

## The four stops

| Stop | Key | Paths |
|------|-----|-------|
| Entry point | `entry-point` | `src/ite/main.py`, `src/ite/config/loader.py` |
| Agent and runtime | `agent-runtime` | `src/ite/agent/agent.py`, `src/ite/agent/session.py`, `src/ite/tools/registry.py` |
| Textual UI | `textual-ui` | `src/ite/ui/reup/app.py`, `src/ite/ui/reup/widgets/prompt_area.py`, `src/ite/ui/reup/reup.tcss` |
| Tests | `tests` | `tests/`, `tests/test_cli_modes.py` |

## Changing the tour

Edit the `STOPS` tuple in `scripts/repository_tour.py`. Keep exactly four stops
and give every stop at least one existing path plus a non-empty `why` string —
the tests enforce both. If a refactor moves a file, the test failure names the
stop that needs updating.
