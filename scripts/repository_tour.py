#!/usr/bin/env python3
"""Self-contained contributor tour of the iTE repository.

Run it from anywhere inside the checkout:

    python scripts/repository_tour.py
    python scripts/repository_tour.py --format json

The tour is intentionally data-driven: every stop names real paths in this
repository, and the script verifies those paths exist before printing them. No
network access, no repository mutation, standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: Files that identify the repository root when walking up from a start path.
ROOT_MARKERS: tuple[str, ...] = (
    "pyproject.toml",
    "src/ite/main.py",
    "AGENTS.md",
)


@dataclass(frozen=True)
class Stop:
    """One stop on the tour."""

    key: str
    title: str
    summary: str
    paths: tuple[str, ...] = field(default=())
    why: str = ""


STOPS: tuple[Stop, ...] = (
    Stop(
        key="entry-point",
        title="Entry point",
        summary="The CLI surface Click wires up, plus the config it loads at startup.",
        paths=("src/ite/main.py", "src/ite/config/loader.py"),
        why=(
            "Start here to learn how a command line becomes a running session: "
            "main.py declares the IteGroup CLI and hands off to the Reup runtime, "
            "while loader.py resolves the layered user/project TOML config."
        ),
    ),
    Stop(
        key="agent-runtime",
        title="Agent and runtime",
        summary="The turn loop, session state, and the tool registry the model calls.",
        paths=(
            "src/ite/agent/agent.py",
            "src/ite/agent/session.py",
            "src/ite/tools/registry.py",
        ),
        why=(
            "Most behavioural changes land here. agent.py drives a conversation "
            "turn, session.py owns conversation state, and registry.py is the "
            "single place where tool schemas are collected and dispatched."
        ),
    ),
    Stop(
        key="textual-ui",
        title="Textual UI",
        summary="The Reup Textual runtime: app shell, widgets, and the .tcss theme.",
        paths=(
            "src/ite/ui/reup/app.py",
            "src/ite/ui/reup/widgets/prompt_area.py",
            "src/ite/ui/reup/styles/base.tcss",
        ),
        why=(
            "This is the only supported runtime surface. app.py is the App class, "
            "widgets/ holds the reusable pieces it composes, and styles/ carries "
            "the visual contract documented in DESIGN.md."
        ),
    ),
    Stop(
        key="tests",
        title="Tests",
        summary="The unittest-based suite that guards the layers above.",
        paths=("tests/", "tests/test_cli_modes.py"),
        why=(
            "Read a neighbouring test before changing behaviour: the suite mirrors "
            "the tour order, so a failing area usually points back at the stop that "
            "owns it. Run it with pytest."
        ),
    ),
)


class TourError(RuntimeError):
    """Raised when the repository root cannot be located."""


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` looking for this repository's root markers.

    Raises:
        TourError: if no directory up to the filesystem root looks like the repo.
    """
    base = (start or Path.cwd()).resolve()
    if base.is_file():
        base = base.parent

    for candidate in (base, *base.parents):
        if all((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate

    raise TourError(
        f"Could not find the iTE repository root starting from {base}.\n"
        "Expected a directory containing: " + ", ".join(ROOT_MARKERS) + ".\n"
        "Run this script from inside a checkout, e.g. `python scripts/repository_tour.py`."
    )


def build_stops(root: Path) -> list[dict[str, object]]:
    """Describe each stop, flagging any path that is missing from ``root``."""
    stops: list[dict[str, object]] = []
    for stop in STOPS:
        stops.append(
            {
                "key": stop.key,
                "title": stop.title,
                "summary": stop.summary,
                "paths": list(stop.paths),
                "missing_paths": [p for p in stop.paths if not (root / p).exists()],
                "why": stop.why,
            }
        )
    return stops


def render_text(root: Path, stops: list[dict[str, object]]) -> str:
    lines: list[str] = [
        "iTE contributor tour",
        f"Repository root: {root}",
        "",
    ]
    for index, stop in enumerate(stops, start=1):
        lines.append(f"Stop {index}: {stop['title']}")
        lines.append(f"  {stop['summary']}")
        lines.append("  Look at:")
        for path in stop["paths"]:  # type: ignore[index]
            marker = "  " if (root / str(path)).exists() else "  (missing) "
            lines.append(f"    {marker}{path}")
        lines.append(f"  Why: {stop['why']}")
        lines.append("")

    missing = sorted({p for stop in stops for p in stop["missing_paths"]})  # type: ignore[index]
    if missing:
        lines.append("Heads up: these paths are missing from this checkout:")
        lines.extend(f"  - {path}" for path in missing)
    else:
        lines.append("Every path in this tour exists in this checkout.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="repository_tour.py",
        description="Print a short tour of the iTE repository for new contributors.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Directory to search upwards from (default: current working directory).",
    )
    args = parser.parse_args(argv)

    try:
        root = find_repo_root(Path(args.root) if args.root else None)
    except TourError as error:
        print(str(error), file=sys.stderr)
        return 2

    stops = build_stops(root)
    if args.format == "json":
        print(
            json.dumps(
                {"repository_root": str(root), "stop_count": len(stops), "stops": stops},
                indent=2,
            )
        )
    else:
        print(render_text(root, stops))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
