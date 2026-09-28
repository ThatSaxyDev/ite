#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass


APP_NAME = "iTE"
APP_VERSION = "0.0.59"


@dataclass(frozen=True)
class InstallProfile:
    operator_name: str
    scope: str
    project_label: str
    companion_enabled: bool


def terminal_width() -> int:
    return max(64, min(96, shutil.get_terminal_size((80, 24)).columns))


def rule(label: str = "") -> None:
    width = terminal_width()
    if not label:
        print("-" * width)
        return
    text = f" {label} "
    side = max(2, (width - len(text)) // 2)
    print(f"{'-' * side}{text}{'-' * max(2, width - side - len(text))}")


def panel(title: str, lines: list[str]) -> None:
    width = terminal_width()
    inner = width - 4
    print("+" + "-" * (width - 2) + "+")
    print("| " + title[:inner].ljust(inner) + " |")
    print("| " + " " * inner + " |")
    for line in lines:
        print("| " + line[:inner].ljust(inner) + " |")
    print("+" + "-" * (width - 2) + "+")


def ask_yes_no(prompt: str, *, default: bool | None = None) -> bool:
    if default is True:
        suffix = "Y/n"
    elif default is False:
        suffix = "y/N"
    else:
        suffix = "y/n"

    while True:
        answer = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not answer and default is not None:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.")


def ask_required(prompt: str) -> str:
    while True:
        answer = input(prompt).strip()
        if answer:
            return answer
        print("Value cannot be empty.")


def ask_choice(prompt: str, options: list[tuple[str, str]], *, default: str) -> str:
    valid = {key for key, _label in options}
    while True:
        print(prompt)
        for key, label in options:
            marker = "default" if key == default else ""
            suffix = f" ({marker})" if marker else ""
            print(f"  {key}. {label}{suffix}")
        answer = input(f"Select an option [{default}]: ").strip() or default
        if answer in valid:
            return answer
        print(f"Choose one of: {', '.join(sorted(valid))}.")


def progress_step(label: str, *, duration: float = 0.45) -> None:
    width = 24
    print(f"  {label:<34}", end="", flush=True)
    for index in range(width + 1):
        filled = "#" * index
        empty = "." * (width - index)
        print(f"\r  {label:<34} [{filled}{empty}]", end="", flush=True)
        time.sleep(duration / width)
    print(" done")


def collect_profile() -> InstallProfile | None:
    rule("Welcome")
    panel(
        f"{APP_NAME} Setup Assistant",
        [
            "This guided installer configures the terminal app, workspace defaults,",
            "and optional Remote Companion support before launching the first run.",
            "",
            f"Package: ite-agent    Version: {APP_VERSION}",
        ],
    )

    if not ask_yes_no("Install iTE on this machine", default=True):
        print("Setup cancelled before changes were prepared.")
        return None

    operator_name = ask_required("Operator name: ")
    print(f"Welcome, {operator_name}.")
    print()

    scope_key = ask_choice(
        "Where should iTE be installed?",
        [
            ("1", "Current user account"),
            ("2", "This project workspace only"),
            ("3", "Portable demo sandbox"),
        ],
        default="1",
    )
    scope = {
        "1": "user",
        "2": "workspace",
        "3": "portable-demo",
    }[scope_key]

    if ask_yes_no("Should we run the second stage", default=True):
        project_label = ask_required("Enter a project label: ")
        print(f"Workspace profile accepted for {project_label}.")
    else:
        project_label = "default"
        print("Second stage skipped. Using the default workspace profile.")

    companion_enabled = ask_yes_no(
        "Configure iTE Remote Companion pairing",
        default=True,
    )

    return InstallProfile(
        operator_name=operator_name,
        scope=scope,
        project_label=project_label,
        companion_enabled=companion_enabled,
    )


def confirm_plan(profile: InstallProfile) -> bool:
    rule("Install Plan")
    companion = "enabled" if profile.companion_enabled else "not configured"
    panel(
        "Ready to install",
        [
            f"Operator:          {profile.operator_name}",
            f"Install scope:     {profile.scope}",
            f"Workspace profile: {profile.project_label}",
            f"Remote Companion:  {companion}",
            "",
            "No real files are changed by this demo; it simulates a full setup run.",
        ],
    )
    return ask_yes_no("Start installation", default=True)


def run_install(profile: InstallProfile) -> None:
    rule("Installing")
    progress_step("Checking Python runtime")
    progress_step("Resolving ite-agent package")
    progress_step(f"Preparing {profile.scope} command shim")
    progress_step(f"Writing {profile.project_label} workspace profile")
    if profile.companion_enabled:
        progress_step("Configuring Remote Companion bridge")
    else:
        progress_step("Skipping Remote Companion bridge", duration=0.25)
    progress_step("Verifying ite command")


def print_receipt(profile: InstallProfile) -> None:
    rule("Complete")
    next_remote = (
        "Run `/remote on` inside iTE to pair your phone."
        if profile.companion_enabled
        else "Run `/remote on` later if you want mobile control."
    )
    panel(
        "iTE is ready",
        [
            "Command: ite",
            f"Workspace: {profile.project_label}",
            f"Scope: {profile.scope}",
            "",
            "Next steps:",
            "  1. Start iTE from your project folder.",
            "  2. Sign in with `/cloud login` if bundled access is required.",
            f"  3. {next_remote}",
        ],
    )


def main() -> int:
    profile = collect_profile()
    if profile is None:
        return 2

    if not confirm_plan(profile):
        print("Installation declined at final confirmation.")
        return 3

    run_install(profile)
    print_receipt(profile)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
