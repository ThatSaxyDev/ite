from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from rich.align import Align
from rich.cells import cell_len
from rich.console import Group
from rich.text import Text


@dataclass(frozen=True)
class SlashCommandOption:
    name: str
    description: str
    insert_text: str | None = None
    attachment_path: str | None = None


def composer_meta_text(
    *,
    cwd: Path,
    model_name: str,
    plan_enabled: bool,
    branch_label: str,
    usage_remaining_percent: int | None = None,
    context_used_percent: int | None = None,
    styles: dict[str, str] | None = None,
    show_usage: bool = True,
    flow_enabled: bool = False,
    flow_state: Literal["idle", "recording", "transcribing", "missing_key"] = "idle",
    flow_frame: int = 0,
) -> tuple[
    Text,
    tuple[int, int],
    tuple[int, int],
    tuple[int, int],
    tuple[int, int],
    tuple[int, int] | None,
    tuple[int, int],
    tuple[int, int],
    tuple[int, int],
]:
    theme = styles or {}
    fg = theme.get("fg", "#d1d5db")
    secondary = theme.get("secondary", fg)
    muted = theme.get("muted", secondary)
    disabled = theme.get("disabled", muted)
    success = theme.get("success", "#5dcf84")
    error = theme.get("error", "#e35d6a")
    warning = theme.get("warning", "#d18a35")
    primary = theme.get("primary", success)

    status_text = "on" if plan_enabled else "off"
    status_style = f"bold {success}" if plan_enabled else f"bold {error}"
    branch_style = f"bold {fg}" if branch_label != "no-git" else f"bold {muted}"

    cell_pos = 0
    text = Text(style=fg)
    attach_start = cell_pos
    text.append("📎", style=f"bold {fg}")
    cell_pos += cell_len("📎")
    attach_end = cell_pos
    spacer = "     "
    text.append(spacer)
    cell_pos += cell_len(spacer)
    model_start = cell_pos
    text.append(model_name, style=f"bold {fg}")
    cell_pos += cell_len(model_name)
    model_suffix = " ▾"
    text.append(model_suffix, style=f"bold {muted}")
    cell_pos += cell_len(model_suffix)
    model_end = cell_pos
    text.append(spacer)
    cell_pos += cell_len(spacer)
    plan_start = cell_pos
    text.append("plan", style=f"bold {fg}")
    cell_pos += cell_len("plan")
    text.append(" ")
    cell_pos += 1
    text.append(status_text, style=status_style)
    cell_pos += cell_len(status_text)
    plan_end = cell_pos
    text.append(spacer)
    cell_pos += cell_len(spacer)
    branch_start = cell_pos
    git_prefix = "git "
    text.append(git_prefix, style=f"bold {muted}")
    cell_pos += cell_len(git_prefix)
    text.append(branch_label, style=branch_style)
    cell_pos += cell_len(branch_label)
    branch_suffix = " ▾"
    text.append(branch_suffix, style=f"bold {muted}")
    cell_pos += cell_len(branch_suffix)
    branch_end = cell_pos
    text.append(spacer)
    cell_pos += cell_len(spacer)
    usage_start = -1
    usage_end = -1
    if show_usage:
        usage_start = cell_pos
        usage_label = "usage "
        text.append(usage_label, style=f"bold {muted}")
        cell_pos += cell_len(usage_label)
        usage_text = (
            f"{usage_remaining_percent}%"
            if usage_remaining_percent is not None
            else "--"
        )
        text.append(usage_text, style=f"bold {fg}")
        cell_pos += cell_len(usage_text)
        text.append(" ")
        cell_pos += 1
        meter_width = 6
        if usage_remaining_percent is None:
            filled = 0
        else:
            remaining_percent = max(0, min(100, usage_remaining_percent))
            filled = max(
                0, min(meter_width, round((remaining_percent / 100) * meter_width))
            )
        empty = meter_width - filled
        if usage_remaining_percent is None:
            usage_meter_style = disabled
        elif usage_remaining_percent >= 60:
            usage_meter_style = success
        elif usage_remaining_percent >= 30:
            usage_meter_style = warning
        else:
            usage_meter_style = error
        if filled:
            text.append("━" * filled, style=f"bold {usage_meter_style}")
            cell_pos += filled
        if empty:
            text.append("━" * empty, style=disabled)
            cell_pos += empty
        usage_end = cell_pos
        text.append(spacer)
        cell_pos += cell_len(spacer)
    context_start = cell_pos
    context_label = "context "
    text.append(context_label, style=f"bold {muted}")
    cell_pos += cell_len(context_label)
    context_text = (
        f"{context_used_percent}%" if context_used_percent is not None else "--"
    )
    text.append(context_text, style=f"bold {fg}")
    cell_pos += cell_len(context_text)
    text.append(" ")
    cell_pos += 1
    context_meter_width = 6
    if context_used_percent is None:
        context_filled = 0
    else:
        context_filled = max(
            0,
            min(
                context_meter_width,
                round((context_used_percent / 100) * context_meter_width),
            ),
        )
    context_empty = context_meter_width - context_filled
    # Use border color for empty bar for visibility in both themes
    border = theme.get("border", "#7d8591")
    if context_filled:
        text.append("━" * context_filled, style=f"bold {primary}")
        cell_pos += context_filled
    if context_empty:
        text.append("━" * context_empty, style=border)
        cell_pos += context_empty
    context_end = cell_pos
    text.append(spacer)
    cell_pos += cell_len(spacer)
    activity_start = cell_pos
    activity_label = "activity"
    text.append(activity_label, style=f"bold {secondary}")
    cell_pos += cell_len(activity_label)
    activity_end = cell_pos
    flow_start = flow_end = 0
    if flow_enabled or flow_state in {"recording", "transcribing"}:
        text.append(spacer)
        cell_pos += cell_len(spacer)
        flow_start = cell_pos
        flow_label, flow_style = _flow_control_label(
            flow_state=flow_state,
            flow_frame=flow_frame,
            fg=fg,
            muted=muted,
            primary=primary,
            success=success,
            warning=warning,
            error=error,
        )
        text.append(flow_label, style=flow_style)
        cell_pos += cell_len(flow_label)
        flow_end = cell_pos
    usage_hitbox = (usage_start, usage_end) if show_usage else None
    return (
        text,
        (attach_start, attach_end),
        (model_start, model_end),
        (branch_start, branch_end),
        (plan_start, plan_end),
        usage_hitbox,
        (context_start, context_end),
        (activity_start, activity_end),
        (flow_start, flow_end),
    )


def send_control_text(
    *,
    turn_running: bool,
    send_frame: int,
    styles: dict[str, str] | None = None,
) -> Text:
    theme = styles or {}
    fg = theme.get("fg", "#d1d5db")
    primary = theme.get("primary", "#5dcf84")
    error = theme.get("error", "#e35d6a")
    success = theme.get("success", primary)
    if not turn_running:
        return Text("send ↵", style=f"bold {primary or success or fg}")
    frames = (
        "■  ▰▱▱",
        "■  ▱▰▱",
        "■  ▱▱▰",
        "■  ▱▰▱",
    )
    return Text(frames[send_frame % len(frames)], style=f"bold {error}")


def _flow_control_label(
    *,
    flow_state: Literal["idle", "recording", "transcribing", "missing_key"],
    flow_frame: int,
    fg: str,
    muted: str,
    primary: str,
    success: str,
    warning: str,
    error: str,
) -> tuple[str, str]:
    if flow_state == "recording":
        frames = (
            "■  ▰▱▱",
            "■  ▱▰▱",
            "■  ▱▱▰",
            "■  ▱▰▱",
        )
        return frames[flow_frame % len(frames)], f"bold {error}"
    if flow_state == "transcribing":
        frames = (
            "🎙  ▰▱▱",
            "🎙  ▱▰▱",
            "🎙  ▱▱▰",
            "🎙  ▱▰▱",
        )
        return frames[flow_frame % len(frames)], f"bold {primary}"
    if flow_state == "missing_key":
        return "flow 🎙 setup", f"bold {warning}"
    return "flow 🎙", f"bold {success or fg or muted}"


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
    styles: dict[str, str] | None = None,
) -> Text:
    theme = styles or {}
    fg = theme.get("fg", "#edf1f7")
    muted = theme.get("muted", "#8c93a1")
    primary = theme.get("primary", "#4edea3")
    selected_fg = theme.get("background", "#07120d")
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
        line_style = f"bold {selected_fg} on {primary}" if selected else f"bold {fg}"
        desc_style = f"bold {selected_fg} on {primary}" if selected else muted
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
        SlashCommandOption(
            name="1. Shift", description="Stop now and send this draft."
        ),
        SlashCommandOption(name="2. Queue", description=queue_copy),
        SlashCommandOption(
            name="3. /aside", description="Ask in the side panel without stopping."
        ),
        SlashCommandOption(
            name="4. Cancel", description="Keep this draft in the composer."
        ),
    ]


def render_turn_action_palette(
    turn_action_options: list[SlashCommandOption],
    command_palette_index: int,
    *,
    styles: dict[str, str] | None = None,
) -> Text:
    theme = styles or {}
    fg = theme.get("fg", "#edf1f7")
    muted = theme.get("muted", "#8c93a1")
    primary = theme.get("primary", "#4edea3")
    selected_fg = theme.get("background", "#07120d")
    text = Text()
    if not turn_action_options:
        return text
    for idx, option in enumerate(turn_action_options):
        selected = idx == command_palette_index
        line_style = f"bold {selected_fg} on {primary}" if selected else f"bold {fg}"
        desc_style = f"bold {selected_fg} on {primary}" if selected else muted
        text.append(option.name.ljust(12), style=line_style)
        text.append("  ", style=line_style)
        text.append(option.description, style=desc_style)
        if idx < len(turn_action_options) - 1:
            text.append("\n")
    return text


def build_empty_state_title(
    *, cwd: Path, thread_count: int, now: datetime | None = None
) -> str:
    current = now or datetime.now()
    hour = current.hour
    is_weekend = current.weekday() >= 5
    if 5 <= hour < 12:
        opener_variants = [
            "Good morning",
            "Morning session",
            "Ready when you are",
            "Workspace ready",
            "Back at it",
            "Start the day here",
        ]
    elif 12 <= hour < 17:
        opener_variants = [
            "Good afternoon",
            "Afternoon session",
            "Workspace ready",
            "Back at it",
            "Ready to continue",
            "Set to work",
        ]
    elif 17 <= hour < 22:
        opener_variants = [
            "Good evening",
            "Evening session",
            "Workspace ready",
            "Ready to continue",
            "Set to work",
            "Back at it",
        ]
    else:
        opener_variants = [
            "Late session",
            "The workspace is ready",
            "Ready to continue",
            "Back at it",
            "Set to work",
        ]

    if thread_count > 0:
        followup_variants = [
            "Continue where you left off.",
            "Pick up your last thread.",
            "Your workspace is ready.",
            "Continue the current thread.",
            "Resume your work.",
            "Open the next task.",
            "Return to the last task.",
            "Pick up the current task.",
            "Step back into the workspace.",
            "Continue with the next item.",
        ]
    else:
        followup_variants = [
            "What should we build next?",
            "Start a thread and we can map it out.",
            "Drop in a goal to begin.",
            "Tell me what you want to ship.",
            "Describe the task to begin.",
            "Start with a clear goal.",
        ]

    if is_weekend:
        opener_variants = [
            "Weekend session",
            "Workspace ready",
            "Ready to continue",
            "Set to work",
        ] + opener_variants[:3]

    if thread_count == 0 and hour >= 22:
        followup_variants = [
            "Start with one clear task.",
            "Describe the work to begin.",
            "Open a thread with the task.",
            "Begin with the next priority.",
        ]

    workspace_key = str(cwd.resolve())
    seed = sum(
        ord(ch)
        for ch in (
            f"{workspace_key}:{current.date().isoformat()}:"
            f"{current.hour}:{thread_count}:{int(is_weekend)}"
        )
    )
    opener = opener_variants[seed % len(opener_variants)]
    followup = followup_variants[(seed // 3) % len(followup_variants)]
    if opener.rstrip(".") in followup:
        followup = followup_variants[(seed // 5 + 1) % len(followup_variants)]
    if opener == "Ready to continue" and followup in {
        "Continue the current thread.",
        "Continue where you left off.",
        "Resume your work.",
    }:
        followup = followup_variants[(seed // 7 + 2) % len(followup_variants)]
    return f"{opener}. {followup}"


def build_empty_state_welcome(title: str, styles: dict[str, str] | None = None) -> Text:
    theme = styles or {}
    welcome = Text(justify="center")
    welcome.append(title, style=f"bold {theme.get('fg', '#f7fafc')}")
    return welcome


def build_empty_state_ascii(styles: dict[str, str] | None = None) -> Text:
    theme = styles or {}
    lines = [
        "  ██╗ ████████╗ ███████╗",
        "  ╚═╝ ╚══██╔══╝ ██╔════╝",
        "  ██╗    ██║    █████╗  ",
        "  ██║    ██║    ██╔══╝  ",
        "  ██║    ██║    ███████╗",
        "  ╚═╝    ╚═╝    ╚══════╝",
    ]
    art = Text(justify="center")
    for index, line in enumerate(lines):
        art.append(line, style=f"bold {theme.get('secondary', '#8d94a0')}")
        if index < len(lines) - 1:
            art.append("\n")
    return art


def build_empty_state_renderable(
    *,
    cwd: Path,
    thread_count: int,
    now: datetime | None = None,
    styles: dict[str, str] | None = None,
) -> Any:
    title = build_empty_state_title(cwd=cwd, thread_count=thread_count, now=now)
    return Align.center(
        Group(
            build_empty_state_ascii(styles),
            Text(""),
            build_empty_state_welcome(title, styles),
        ),
        vertical="middle",
    )


def build_signed_out_state_renderable(
    status: str | None = None,
    styles: dict[str, str] | None = None,
) -> Any:
    theme = styles or {}
    title = Text(justify="center")
    title.append("Sign in to continue", style=f"bold {theme.get('fg', '#f7fafc')}")

    body = Text(justify="center")
    body.append(
        "We will open your browser and resume here when sign-in is complete.",
        style=theme.get("secondary", "#8c93a1"),
    )

    parts: list[Any] = [
        build_empty_state_ascii(styles),
        Text(""),
        title,
        Text(""),
        body,
    ]

    return Align.center(Group(*parts), vertical="middle")


def build_turn_payload(
    message: str,
    attachments: list[str],
    *,
    max_attachments: int,
    display_message: str | None = None,
) -> dict[str, Any]:
    return {
        "message": (message or "").strip(),
        "display_message": (display_message or message or "").strip(),
        "attachments": attachments[:max_attachments],
    }
