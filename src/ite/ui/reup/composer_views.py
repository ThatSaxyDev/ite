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
    available_width: int | None = None,
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
    muted = theme.get("muted", fg)
    disabled = theme.get("disabled", muted)
    success = theme.get("success", "#5dcf84")
    error = theme.get("error", "#e35d6a")
    warning = theme.get("warning", "#d18a35")
    primary = theme.get("primary", success)

    status_text = "on" if plan_enabled else "off"
    status_style = f"bold {success}" if plan_enabled else f"bold {error}"
    branch_style = f"bold {fg}" if branch_label != "no-git" else f"bold {muted}"

    def _meter(
        *,
        percent: int | None,
        width: int,
        filled_style: str,
        empty_style: str,
        none_style: str,
        thresholds: bool = False,
    ) -> list[tuple[str, str]]:
        if percent is None:
            return [("━" * width, none_style)]
        clamped = max(0, min(100, percent))
        filled = max(0, min(width, round((clamped / 100) * width)))
        empty = width - filled
        style = filled_style
        if thresholds:
            if clamped >= 60:
                style = success
            elif clamped >= 30:
                style = warning
            else:
                style = error
        parts: list[tuple[str, str]] = []
        if filled:
            parts.append(("━" * filled, f"bold {style}"))
        if empty:
            parts.append(("━" * empty, empty_style))
        return parts

    def _shorten(value: str, max_cells: int) -> str:
        if max_cells <= 0:
            return ""
        if cell_len(value) <= max_cells:
            return value
        if max_cells == 1:
            return "…"
        result = ""
        used = 0
        for char in value:
            width = cell_len(char)
            if used + width > max_cells - 1:
                break
            result += char
            used += width
        return f"{result}…"

    def _build(
        *,
        spacer: str,
        include_usage: bool,
        include_context: bool,
        meter_width: int,
        compact_labels: bool,
        include_model: bool = True,
        include_branch: bool = True,
        model_cells: int | None = None,
        branch_cells: int | None = None,
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
        segments: list[tuple[str, list[tuple[str, str]], str | None]] = []
        display_model = _shorten(model_name, model_cells) if model_cells else model_name
        display_branch = (
            _shorten(branch_label, branch_cells) if branch_cells else branch_label
        )
        segments.append(("attach", [("📎", f"bold {fg}")], "attach"))
        if include_model:
            segments.append(
                (
                    "model",
                    [(display_model, f"bold {fg}"), (" ▾", f"bold {muted}")],
                    "model",
                )
            )
        segments.append(
            (
                "plan",
                [
                    ("plan", f"bold {fg}"),
                    (" ", fg),
                    (status_text, status_style),
                ],
                "plan",
            )
        )
        if include_branch:
            segments.append(
                (
                    "branch",
                    [
                        ("git " if not compact_labels else "g ", f"bold {muted}"),
                        (display_branch, branch_style),
                        (" ▾", f"bold {muted}"),
                    ],
                    "branch",
                )
            )
        if include_usage and show_usage:
            usage_text = (
                f"{usage_remaining_percent}%"
                if usage_remaining_percent is not None
                else "--"
            )
            segments.append(
                (
                    "usage",
                    [
                        ("usage " if not compact_labels else "use ", f"bold {muted}"),
                        (usage_text, f"bold {fg}"),
                        (" ", fg),
                        *_meter(
                            percent=usage_remaining_percent,
                            width=meter_width,
                            filled_style=success,
                            empty_style=disabled,
                            none_style=disabled,
                            thresholds=True,
                        ),
                    ],
                    "usage",
                )
            )
        if include_context:
            context_text = (
                f"{context_used_percent}%" if context_used_percent is not None else "--"
            )
            border = theme.get("border", "#7d8591")
            segments.append(
                (
                    "context",
                    [
                        (
                            "context " if not compact_labels else "ctx ",
                            f"bold {muted}",
                        ),
                        (context_text, f"bold {fg}"),
                        (" ", fg),
                        *_meter(
                            percent=context_used_percent,
                            width=meter_width,
                            filled_style=primary,
                            empty_style=border,
                            none_style=border,
                        ),
                    ],
                    "context",
                )
            )

        text = Text(style=fg)
        cell_pos = 0
        hitboxes: dict[str, tuple[int, int]] = {
            "attach": (0, 0),
            "model": (0, 0),
            "branch": (0, 0),
            "plan": (0, 0),
            "context": (0, 0),
            "activity": (0, 0),
            "flow": (0, 0),
        }
        usage_hitbox: tuple[int, int] | None = None
        for index, (name, parts, hitbox_name) in enumerate(segments):
            if index:
                text.append(spacer)
                cell_pos += cell_len(spacer)
            start = cell_pos
            for value, style in parts:
                text.append(value, style=style)
                cell_pos += cell_len(value)
            end = cell_pos
            if hitbox_name == "usage":
                usage_hitbox = (start, end)
            elif hitbox_name:
                hitboxes[hitbox_name] = (start, end)

        return (
            text,
            hitboxes["attach"],
            hitboxes["model"],
            hitboxes["branch"],
            hitboxes["plan"],
            usage_hitbox if show_usage and include_usage else None,
            hitboxes["context"],
            hitboxes["activity"],
            hitboxes["flow"],
        )

    width = available_width if available_width and available_width > 0 else None
    candidates = [
        dict(
            spacer="     ",
            include_usage=show_usage,
            include_context=True,
            meter_width=6,
            compact_labels=False,
        ),
        dict(
            spacer="  ",
            include_usage=show_usage,
            include_context=True,
            meter_width=4,
            compact_labels=True,
        ),
        dict(
            spacer="  ",
            include_usage=False,
            include_context=True,
            meter_width=4,
            compact_labels=True,
        ),
        dict(
            spacer="  ",
            include_usage=False,
            include_context=False,
            meter_width=4,
            compact_labels=True,
        ),
    ]
    if width is None:
        return _build(**candidates[0])

    for candidate in candidates:
        built = _build(**candidate)
        if cell_len(built[0].plain) <= width:
            return built

    reserved_width = cell_len("📎  ") + cell_len("  plan off") + cell_len("  g  ▾")
    flow_width = 0
    available_for_names = max(4, width - reserved_width - flow_width)
    model_cells = max(4, min(cell_len(model_name), available_for_names // 2))
    branch_cells = max(2, available_for_names - model_cells)
    compact = _build(
        spacer="  ",
        include_usage=False,
        include_context=False,
        meter_width=4,
        compact_labels=True,
        model_cells=model_cells,
        branch_cells=branch_cells,
    )
    if cell_len(compact[0].plain) <= width:
        return compact

    for model_cells in range(cell_len(model_name), 0, -1):
        compact = _build(
            spacer="  ",
            include_usage=False,
            include_context=False,
            meter_width=4,
            compact_labels=True,
            include_branch=False,
            model_cells=model_cells,
        )
        if cell_len(compact[0].plain) <= width:
            return compact
    compact = _build(
        spacer="  ",
        include_usage=False,
        include_context=False,
        meter_width=4,
        compact_labels=True,
        include_model=False,
        include_branch=False,
    )
    if cell_len(compact[0].plain) <= width:
        return compact
    return _build(
        spacer="  ",
        include_usage=False,
        include_context=False,
        meter_width=4,
        compact_labels=True,
        include_model=False,
        include_branch=False,
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


def flow_control_text(
    *,
    flow_enabled: bool = False,
    flow_state: Literal["idle", "recording", "transcribing", "missing_key"] = "idle",
    flow_frame: int = 0,
    styles: dict[str, str] | None = None,
) -> Text:
    if not (flow_enabled or flow_state in {"recording", "transcribing"}):
        return Text("")
    theme = styles or {}
    fg = theme.get("fg", "#d1d5db")
    muted = theme.get("muted", fg)
    success = theme.get("success", "#5dcf84")
    error = theme.get("error", "#e35d6a")
    warning = theme.get("warning", "#d18a35")
    primary = theme.get("primary", success)
    label, style = _flow_control_label(
        flow_state=flow_state,
        flow_frame=flow_frame,
        fg=fg,
        muted=muted,
        primary=primary,
        success=success,
        warning=warning,
        error=error,
    )
    return Text(label, style=style)


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
