#!/usr/bin/env python3
from __future__ import annotations

import sys
import time


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
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


def main() -> int:
    print("Interactive prompt demo")
    print("This script asks several questions before it finishes.")
    print()

    if not ask_yes_no("Do you want to continue"):
        print("Stopped at the first confirmation.")
        return 2

    name = ask_required("Proceed by entering your name: ")
    print(f"Hello, {name}.")

    if ask_yes_no("Should we run the second stage"):
        project = ask_required("Enter a project label: ")
        print(f"Second stage accepted for {project}.")
    else:
        print("Second stage skipped.")

    if ask_yes_no("Do you confirm the final action"):
        print("Final action confirmed.")
    else:
        print("Final action declined.")
        return 3

    print()
    print("Working", end="", flush=True)
    for _ in range(3):
        time.sleep(0.4)
        print(".", end="", flush=True)
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
