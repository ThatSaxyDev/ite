"""Reviewed profile updates, separate from the agent's source-writing tools."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ite.agent.learning import PROFILE_MAX_BYTES, PROFILE_TEMPLATE

START = "<!-- ite:learning-preferences:start -->"
END = "<!-- ite:learning-preferences:end -->"
PACES = (
    "One small step at a time",
    "Explain, then let me explore",
    "Brief hints first",
)


@dataclass
class LearningPreferences:
    objective: str = ""
    starting_point: str = ""
    pace: str = PACES[0]
    preferences: str = ""

    @classmethod
    def from_profile(cls, profile: str) -> LearningPreferences:
        if START not in profile or END not in profile:
            return cls()
        section = profile.split(START, 1)[1].split(END, 1)[0]
        fields = {}
        for key, title in (
            ("objective", "Objective"),
            ("starting_point", "Starting point"),
            ("pace", "Pace"),
            ("preferences", "Preferences"),
        ):
            match = re.search(rf"(?ms)^### {title}\n(.*?)(?=^### |\Z)", section)
            if match:
                fields[key] = match.group(1).strip()
        return cls(**fields)


def read_setup_profile(path: Path) -> str | None:
    if path.is_symlink():
        raise ValueError(
            "learn.md is a symbolic link. Edit its target yourself or use a regular file."
        )
    try:
        with path.open("rb") as stream:
            raw = stream.read(PROFILE_MAX_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(raw) > PROFILE_MAX_BYTES:
        raise ValueError("learn.md exceeds 16 KiB. Shorten it before guided setup.")
    try:
        return raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("learn.md must be UTF-8 to use guided setup.") from exc


def build_profile(original: str | None, preferences: LearningPreferences) -> str:
    values = (
        preferences.objective,
        preferences.starting_point,
        preferences.pace,
        preferences.preferences,
    )
    if any(START in value or END in value for value in values):
        raise ValueError("Answers cannot contain iTE's profile section markers.")
    section = f"""{START}
## My learning preferences

### Objective
{preferences.objective.strip()}

### Starting point
{preferences.starting_point.strip()}

### Pace
{preferences.pace}

### Preferences
{preferences.preferences.strip()}
{END}"""
    base = original if original is not None else PROFILE_TEMPLATE
    if START in base or END in base:
        if (
            base.count(START) != 1
            or base.count(END) != 1
            or base.index(START) > base.index(END)
        ):
            raise ValueError(
                "The guided preferences section is malformed. Fix its markers before setup."
            )
        before, rest = base.split(START, 1)
        _, after = rest.split(END, 1)
        return before + section + after
    return base.rstrip() + "\n\n" + section + "\n"


def save_profile(path: Path, text: str, *, expected: str | None) -> None:
    if not text.strip():
        raise ValueError("The learning profile cannot be empty.")
    if len(text.encode("utf-8")) > PROFILE_MAX_BYTES:
        raise ValueError(
            "The learning profile exceeds 16 KiB. Shorten the preview before saving."
        )
    if read_setup_profile(path) != expected:
        raise ValueError(
            "learn.md changed while setup was open. Cancel and reopen setup to keep those changes."
        )
    descriptor, temporary = tempfile.mkstemp(
        prefix=".learn-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        if expected is None:
            # Exclusive creation: do not replace a file created while the dialog was open.
            os.link(temporary, path)
        else:
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
