from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from rich.console import Group
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from ite.skills.manager import SkillDefinition


def skill_state(skill: SkillDefinition, active_ids: set[str]) -> str:
    if skill.identifier in active_ids:
        return "active"
    if skill.requires_trust and not skill.trusted:
        return "blocked"
    return "available"


def _style_token(styles: dict[str, str] | None, key: str, fallback: str) -> str:
    """Get style from theme dict or use fallback."""
    if styles is None:
        return fallback
    return styles.get(key, fallback)


def build_skills_help_renderable(styles: dict[str, str] | None = None) -> Group:
    title = Text("skills", style=f"bold {_style_token(styles, 'fg', '#edf1f7')}")
    intro = Text(
        "Skills are optional instruction bundles that can shape how the agent works in this session.",
        style=_style_token(styles, "secondary", "#d7deea"),
    )

    commands = Table.grid(expand=True)
    commands.add_column(width=24)
    commands.add_column(ratio=1)
    cmd_style = _style_token(styles, "primary", "#b7c8e1")
    body_style = _style_token(styles, "secondary", "#d7deea")
    muted_style = _style_token(styles, "muted", "#8c93a1")
    dim_style = _style_token(styles, "disabled", "#6f7785")
    commands.add_row(Text("/skills", style=f"bold {cmd_style}"), Text("List discovered skills and show which ones are active.", style=body_style))
    commands.add_row(Text("/skills help", style=f"bold {cmd_style}"), Text("Show the quick guide and the core workflow.", style=body_style))
    commands.add_row(Text("/skills show <name>", style=f"bold {cmd_style}"), Text("Inspect a skill without activating it.", style=body_style))
    commands.add_row(Text("/skills use <name>", style=f"bold {cmd_style}"), Text("Activate a skill so it affects the current session.", style=body_style))
    commands.add_row(Text("/skills drop <name>", style=f"bold {cmd_style}"), Text("Deactivate one active skill.", style=body_style))
    commands.add_row(Text("/skills clear", style=f"bold {cmd_style}"), Text("Clear the active skill stack.", style=body_style))
    commands.add_row(Text("/skills add <path|owner/repo|url>", style=f"bold {cmd_style}"), Text("Install a local skill directory, git repo, or pack into this workspace.", style=body_style))

    rules = Text()
    rules.append("Key rules", style=f"bold {muted_style}")
    rules.append("\n")
    rules.append("• Showing a skill is read-only.\n", style=body_style)
    rules.append("• Active skills shape the current session until you drop or clear them.\n", style=body_style)
    rules.append("• Project-provided shared skills may require ", style=body_style)
    rules.append("/skills trust", style=f"bold {cmd_style}")
    rules.append(" before they can be activated.", style=body_style)

    example = Text(
        "Example: /skills  →  /skills show critique  →  /skills use critique",
        style=dim_style,
    )
    return Group(title, intro, Text(""), commands, Text(""), rules, Text(""), example)


def build_skills_overview_renderable(
    skills: list[SkillDefinition],
    active_ids: set[str],
    styles: dict[str, str] | None = None,
) -> Group | Text:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#d7deea")
    muted = _style_token(styles, "muted", "#8c93a1")
    primary = _style_token(styles, "primary", "#b7c8e1")
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")
    disabled = _style_token(styles, "disabled", "#6f7785")

    if not skills:
        lead = Text("No skills discovered yet.", style=f"bold {fg}")
        intro = Text(
            "Skills are reusable instruction bundles. Install or add one, then activate it when you want the agent to work differently.",
            style=secondary,
        )
        commands = Text()
        commands.append("Start here: ", style=muted)
        commands.append("/skills", style=f"bold {primary}")
        commands.append("  ·  ", style=disabled)
        commands.append("/skills show <name>", style=f"bold {primary}")
        commands.append("  ·  ", style=disabled)
        commands.append("/skills use <name>", style=f"bold {primary}")
        install = Text(
            "Shared project skills belong in .agents/skills. Use .ite/skills only for local overrides.",
            style=disabled,
        )
        return Group(lead, intro, Text(""), commands, Text(""), install)

    active_count = sum(1 for skill in skills if skill.identifier in active_ids)
    blocked_count = sum(
        1
        for skill in skills
        if skill.identifier not in active_ids and skill.requires_trust and not skill.trusted
    )
    available_count = max(0, len(skills) - active_count - blocked_count)

    summary = Text()
    summary.append("skills ", style=f"bold {fg}")
    summary.append(f"{len(skills)} installed", style=secondary)
    summary.append("  ·  ", style=disabled)
    summary.append(f"{active_count} active", style=f"bold {success}")
    summary.append("  ·  ", style=disabled)
    summary.append(f"{available_count} ready", style=f"bold {primary}")
    if blocked_count:
        summary.append("  ·  ", style=disabled)
        summary.append(f"{blocked_count} blocked", style=f"bold {warning}")

    table = Table.grid(expand=True)
    table.add_column(ratio=5)
    table.add_column(width=10)
    table.add_column(width=9)
    table.add_column(ratio=6)

    ordered = sorted(
        skills,
        key=lambda skill: (
            {"active": 0, "available": 1, "blocked": 2}[skill_state(skill, active_ids)],
            skill.identifier,
        ),
    )
    for i, skill in enumerate(ordered):
        state = skill_state(skill, active_ids)
        title = Text(skill.identifier, style=f"bold {fg}")
        if skill.name != skill.identifier:
            title.append(f"  {skill.name}", style=muted)

        meta_bits = [_format_source_label(skill.source, author=skill.author)]
        if skill.reference_files:
            ref_label = "ref" if len(skill.reference_files) == 1 else "refs"
            meta_bits.append(f"{len(skill.reference_files)} {ref_label}")
        if skill.tags:
            meta_bits.append(", ".join(skill.tags[:2]))
        detail = Text(" · ".join(meta_bits), style=_style_token(styles, "secondary", "#7d8594"))

        description = Text(skill.description, style=secondary)
        table.add_row(
            Group(title, detail),
            _state_badge(state, styles),
            Text("invoke", style=success) if skill.user_invocable else Text("assist", style=muted),
            description,
        )
        if i < len(ordered) - 1:
            table.add_row(Text(""), Text(""), Text(""), Text(""))

    source_counts = Counter(_format_source_label(skill.source, author=skill.author) for skill in skills)
    footer = Text("roots ", style=disabled)
    footer.append(" · ".join(f"{name} {count}" for name, count in sorted(source_counts.items())), style=muted)

    hint = Text(
        "/skills show <name> inspects  ·  /skills use <name> activates  ·  only active skills shape this session",
        style=disabled,
    )
    return Group(summary, Text(""), table, Text(""), footer, hint)


def build_skill_detail_renderable(
    skill: SkillDefinition,
    active_ids: set[str],
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#d7deea")
    muted = _style_token(styles, "muted", "#8c93a1")
    primary = _style_token(styles, "primary", "#b7c8e1")
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")

    state = skill_state(skill, active_ids)
    header = Text(skill.identifier, style=f"bold {fg}")
    if skill.user_invocable:
        header.append("  invoke", style=success)
    header.append(f"  {_format_source_label(skill.source, author=skill.author)}", style=_style_token(styles, "secondary", "#7d8594"))

    description = Text(skill.description, style=secondary)

    meta = Table.grid(expand=True)
    meta.add_column(width=14)
    meta.add_column(ratio=1)
    meta.add_row(Text("state", style=muted), _state_badge(state, styles))
    if skill.aliases:
        meta.add_row(
            Text("aliases", style=muted),
            Text(", ".join(skill.aliases[:8]), style=secondary),
        )
    if skill.version:
        meta.add_row(Text("version", style=muted), Text(skill.version, style=secondary))
    if skill.author:
        meta.add_row(Text("author", style=muted), Text(skill.author, style=secondary))
    if skill.homepage:
        meta.add_row(Text("homepage", style=muted), Text(skill.homepage, style=primary))
    if skill.tags:
        meta.add_row(Text("tags", style=muted), Text(", ".join(skill.tags[:8]), style=secondary))

    references = None
    if skill.reference_files:
        reference_table = Table.grid(expand=True)
        reference_table.add_column(ratio=1)
        for path in skill.reference_files[:12]:
            reference_table.add_row(Text(path, style=primary))
        references = Group(
            Text("references", style=f"bold {muted}"),
            reference_table,
        )

    trust_note = None
    if skill.requires_trust and not skill.trusted:
        trust_note = Text(
            "Blocked until this workspace is trusted with /skills trust.",
            style=f"bold {warning}",
        )

    instructions = Group(
        Text("instructions", style=f"bold {muted}"),
        Markdown(skill.instructions),
    )

    parts = [header, description, Text(""), meta]
    if trust_note is not None:
        parts.extend([Text(""), trust_note])
    if references is not None:
        parts.extend([Text(""), references])
    parts.extend([Text(""), instructions])
    return Group(*parts)


def build_skill_feedback_renderable(
    *,
    title: str,
    message: str,
    active_count: int,
    available_count: int,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#d7deea")
    muted = _style_token(styles, "muted", "#8c93a1")
    success = _style_token(styles, "success", "#8fc7a2")
    disabled = _style_token(styles, "disabled", "#6f7785")
    lead = Text(title, style=f"bold {fg}")
    body = Text(message.strip(), style=secondary)
    stats = Text()
    stats.append(f"{active_count} active", style=success)
    stats.append(f"  ·  ", style=disabled)
    stats.append(f"{available_count} installed", style=muted)
    return Group(lead, body, Text(""), stats)


def build_skills_tool_renderable(
    payload: Mapping[str, object],
    styles: dict[str, str] | None = None,
) -> Group | None:
    action = str(payload.get("action") or "").strip().lower()
    if not action:
        return None

    active_skills = _string_list(payload.get("active_skills"))
    available_count = int(payload.get("available_count") or 0)

    if action == "list":
        skills = payload.get("skills")
        if not isinstance(skills, list):
            return None
        return _build_skills_summary_from_payload(
            skills=skills,
            active_skills=set(active_skills),
            available_count=available_count,
            styles=styles,
        )

    if action in {"show", "activate"}:
        return _build_skill_tool_detail(
            payload=payload,
            active_skills=active_skills,
            available_count=available_count,
            styles=styles,
        )

    if action in {"deactivate", "clear", "trust", "untrust"}:
        title_map = {
            "deactivate": "Skill deactivated",
            "clear": "Cleared active skills",
            "trust": "Workspace skills trusted",
            "untrust": "Workspace skills untrusted",
        }
        return build_skill_feedback_renderable(
            title=title_map[action],
            message=_tool_message_for_action(action, payload),
            active_count=len(active_skills),
            available_count=available_count,
            styles=styles,
        )

    return None


def _state_badge(state: str, styles: dict[str, str] | None = None) -> Text:
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")
    primary = _style_token(styles, "primary", "#b7c8e1")
    if state == "active":
        return Text("active", style=f"bold {success}")
    if state == "blocked":
        return Text("blocked", style=f"bold {warning}")
    return Text("ready", style=f"bold {primary}")


def _format_source_label(source: str, *, author: str | None = None) -> str:
    if source == "shared-project" and str(author or "").strip().lower() == "ite":
        return "ite bundled"
    label = str(source or "").strip().replace("compat-", "").replace("-", " ")
    return label or "skill root"


def _build_skills_summary_from_payload(
    *,
    skills: list[object],
    active_skills: set[str],
    available_count: int,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#d7deea")
    muted = _style_token(styles, "muted", "#8c93a1")
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")
    disabled = _style_token(styles, "disabled", "#6f7785")

    rows: list[tuple[str, str, str, str, bool]] = []
    blocked_count = 0
    for item in skills:
        if not isinstance(item, Mapping):
            continue
        identifier = str(item.get("identifier") or "").strip()
        if not identifier:
            continue
        trusted = str(item.get("trusted") or "true").lower() == "true"
        requires_trust = str(item.get("requires_trust") or "false").lower() == "true"
        state = "active" if identifier in active_skills else "blocked" if requires_trust and not trusted else "available"
        if state == "blocked":
            blocked_count += 1
        rows.append(
            (
                identifier,
                str(item.get("description") or "").strip(),
                str(item.get("source") or "").strip(),
                state,
                str(item.get("user_invocable") or "false").lower() == "true",
            )
        )

    summary = Text()
    summary.append("skills ", style=f"bold {fg}")
    summary.append(f"{available_count or len(rows)} available", style=secondary)
    summary.append("  ·  ", style=disabled)
    summary.append(f"{len(active_skills)} active", style=success)
    if blocked_count:
        summary.append("  ·  ", style=disabled)
        summary.append(f"{blocked_count} blocked", style=warning)

    table = Table.grid(expand=True)
    table.add_column(ratio=4)
    table.add_column(width=10)
    table.add_column(width=9)
    table.add_column(ratio=6)
    for identifier, description, source, state, user_invocable in rows:
        meta = Text(
            _format_source_label(source, author=str(item.get("author") or "").strip() or None),
            style=_style_token(styles, "secondary", "#7d8594"),
        )
        table.add_row(
            Group(Text(identifier, style=f"bold {fg}"), meta),
            _state_badge(state, styles),
            Text("invoke", style=success) if user_invocable else Text("assist", style=muted),
            Text(description, style=secondary),
        )

    footer = Text(
        "The model can inspect other skills without activating them. Only active skills shape the standing session behavior.",
        style=disabled,
    )
    return Group(summary, Text(""), table, Text(""), footer)


def _build_skill_tool_detail(
    *,
    payload: Mapping[str, object],
    active_skills: list[str],
    available_count: int,
    styles: dict[str, str] | None = None,
) -> Group:
    del available_count
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#d7deea")
    success = _style_token(styles, "success", "#8fc7a2")
    primary = _style_token(styles, "primary", "#b7c8e1")
    skill_id = str(payload.get("skill") or payload.get("name") or "").strip()
    title = Text(skill_id or "skill", style=f"bold {fg}")
    if payload.get("action") == "activate":
        title.append("  active now", style=success)
    elif skill_id in active_skills:
        title.append("  active", style=success)
    else:
        title.append("  inspected", style=primary)

    description = Text(str(payload.get("description") or "").strip(), style=secondary)
    return Group(title, description) if description.plain else Group(title)


def _tool_message_for_action(action: str, payload: Mapping[str, object]) -> str:
    active_skills = _string_list(payload.get("active_skills"))
    if action == "deactivate":
        skill = str(payload.get("skill") or "").strip()
        return f"{skill} removed from the active set." if skill else "One skill removed from the active set."
    if action == "clear":
        return "No skills remain active in this session."
    if action == "trust":
        return "Project-provided skills can now be activated in this workspace."
    if action == "untrust":
        if active_skills:
            return "Workspace untrusted. Local project skills were re-evaluated."
        return "Workspace untrusted. Project skills remain discoverable but blocked."
    return "Skills updated."


def _truncate_markdown(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 14].rstrip() + "\n\n...[truncated]"


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
