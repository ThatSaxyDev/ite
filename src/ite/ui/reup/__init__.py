"""Textual-based reup TUI entrypoints."""

from __future__ import annotations

from ite.config.config import Config


def run_reup(config: Config) -> None:
    # Lazy import so `ite` can still run without Textual unless --reup is used.
    from .app import run_reup as _run_reup

    _run_reup(config)


__all__ = ["run_reup"]
