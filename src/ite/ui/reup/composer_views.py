from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.cells import cell_len
from rich.text import Text


@dataclass(frozen=True)
class SlashCommandOption:
    name: str
    description: str


def composer_meta_text(
    *,
    cwd: Path,
    model_name: str,
    attachment_count: int,
    plan_enabled: bool,
    branch_label: str,
) -> tuple[Text, tuple[int, int], tuple[int, int], tuple[int, int]]:
    status_text = "on" if plan_enabled else "off"
    status_style = "bold #5dcf84" if plan_enabled else "bold #e35d6a"
    branch_style = "bold #d1d5db" if branch_label != "no-git" else "bold #9ca3af"

    cell_pos = 0
    text = Text(style="#d1d5db")
    attach_start = cell_pos
    text.append("📎", style="bold #d1d5db")
    cell_pos += cell_len("📎")
    if attachment_count:
        badge = f" {attachment_count}"
        text.append(badge, style="bold #5dcf84")
        cell_pos += cell_len(badge)
    attach_end = cell_pos
    spacer = "     "
    text.append(spacer)
    cell_pos += cell_len(spacer)
    text.append(model_name, style="bold #d1d5db")
    cell_pos += cell_len(model_name)
    text.append(spacer)
    cell_pos += cell_len(spacer)
    plan_start = cell_pos
    text.append("Plan", style="bold #d1d5db")
    cell_pos += cell_len("Plan")
    text.append(" ")
    cell_pos += 1
    text.append(status_text, style=status_style)
    cell_pos += cell_len(status_text)
    plan_end = cell_pos
    text.append(spacer)
    cell_pos += cell_len(spacer)
    branch_start = cell_pos
    git_prefix = "git "
    text.append(git_prefix, style="bold #9ca3af")
    cell_pos += cell_len(git_prefix)
    text.append(branch_label, style=branch_style)
    cell_pos += cell_len(branch_label)
    branch_suffix = " ▾"
    text.append(branch_suffix, style="bold #9ca3af")
    cell_pos += cell_len(branch_suffix)
    branch_end = cell_pos
    return text, (attach_start, attach_end), (branch_start, branch_end), (plan_start, plan_end)


def build_command_palette_options(command_registry: Any) -> list[SlashCommandOption]:
    options = [
        SlashCommandOption(name=command.name, description=command.description)
        for command in command_registry.all_commands()
    ]
    return sorted(options, key=lambda option: option.name.lower())


def extract_slash_query(text: str) -> str | None:
    raw = (text or "").lstrip()
    if not raw or "\n" in raw:
        return None
    token = raw.split(maxsplit=1)[0]
    if not token.startswith("/"):
        return None
    if raw != token and token.startswith("/"):
        return None
    return token.lower()


def filtered_command_palette(
    text: str,
    *,
    command_palette_options: list[SlashCommandOption],
) -> list[SlashCommandOption]:
    query = extract_slash_query(text)
    if query is None:
        return []
    if query == "/":
        return list(command_palette_options)
    return [
        option
        for option in command_palette_options
        if option.name.lower().startswith(query)
    ]


def command_palette_window(
    *,
    filtered_options: list[SlashCommandOption],
    command_palette_index: int,
    max_rows: int,
) -> list[SlashCommandOption]:
    if not filtered_options:
        return []
    window_rows = min(max_rows, len(filtered_options))
    start = max(0, command_palette_index - window_rows + 1)
    end = min(len(filtered_options), start + window_rows)
    start = max(0, end - window_rows)
    return filtered_options[start:end]


def render_command_palette(
    *,
    filtered_options: list[SlashCommandOption],
    command_palette_index: int,
    max_rows: int,
) -> Text:
    text = Text()
    window = command_palette_window(
        filtered_options=filtered_options,
        command_palette_index=command_palette_index,
        max_rows=max_rows,
    )
    if not window:
        return text
    start = filtered_options.index(window[0])
    for idx, option in enumerate(window, start=start):
        selected = idx == command_palette_index
        line_style = "bold #f8fafc on #315b8a" if selected else "#dbe4f2"
        desc_style = "bold #e5eefc on #315b8a" if selected else "#7f8ea3"
        text.append(option.name.ljust(14), style=line_style)
        text.append("  ", style=line_style)
        text.append(option.description, style=desc_style)
        if idx < start + len(window) - 1:
            text.append("\n")
    return text


def build_turn_action_options(*, replacing_queue: bool) -> list[SlashCommandOption]:
    queue_copy = (
        "Replace the queued draft."
        if replacing_queue
        else "Send when the current turn finishes."
    )
    return [
        SlashCommandOption(name="1. Shift", description="Stop now and send this draft."),
        SlashCommandOption(name="2. Queue", description=queue_copy),
        SlashCommandOption(name="3. /aside", description="Ask in the side panel without stopping."),
        SlashCommandOption(name="4. Cancel", description="Keep this draft in the composer."),
    ]


def render_turn_action_palette(turn_action_options: list[SlashCommandOption], command_palette_index: int) -> Text:
    text = Text()
    if not turn_action_options:
        return text
    for idx, option in enumerate(turn_action_options):
        selected = idx == command_palette_index
        line_style = "bold #f8fafc on #315b8a" if selected else "#dbe4f2"
        desc_style = "bold #e5eefc on #315b8a" if selected else "#7f8ea3"
        text.append(option.name.ljust(12), style=line_style)
        text.append("  ", style=line_style)
        text.append(option.description, style=desc_style)
        if idx < len(turn_action_options) - 1:
            text.append("\n")
    return text


def build_empty_state_title(*, cwd: Path, thread_count: int, now: datetime | None = None) -> str:
    current = now or datetime.now()
    hour = current.hour
    if 5 <= hour < 12:
        opener_variants = [
            "Good morning",
            "Fresh start",
            "Morning focus",
            "Let's get momentum",
        ]
    elif 12 <= hour < 17:
        opener_variants = [
            "Good afternoon",
            "Afternoon check-in",
            "Back to shipping",
            "Let's make progress",
        ]
    else:
        opener_variants = [
            "Good evening",
            "Evening build session",
            "Quiet hours, solid output",
            "Let's close the day strong",
        ]

    if thread_count > 0:
        followup_variants = [
            "Continue where you left off.",
            "Pick up your last thread.",
            "Your workspace is ready.",
            "Resume the next step.",
        ]
    else:
        followup_variants = [
            "What should we build next?",
            "Start a thread and let's map it out.",
            "Drop in a goal to begin.",
            "Tell me what you want to ship.",
        ]

    workspace_key = str(cwd.resolve())
    seed = sum(ord(ch) for ch in f"{workspace_key}:{current.date().isoformat()}:{thread_count}")
    opener = opener_variants[seed % len(opener_variants)]
    followup = followup_variants[(seed // 3) % len(followup_variants)]
    return f"{opener}. {followup}"


def build_turn_payload(message: str, attachments: list[str], *, max_attachments: int) -> dict[str, Any]:
    return {
        "message": (message or "").strip(),
        "attachments": attachments[:max_attachments],
    }
