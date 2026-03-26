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


def build_skills_help_renderable() -> Group:
    title = Text("skills", style="bold #edf1f7")
    intro = Text(
        "Skills are optional instruction bundles that can shape how the agent works in this session.",
        style="#d7deea",
    )

    commands = Table.grid(expand=True)
    commands.add_column(width=24)
    commands.add_column(ratio=1)
    commands.add_row(Text("/skills", style="bold #b7c8e1"), Text("List discovered skills and show which ones are active.", style="#d7deea"))
    commands.add_row(Text("/skills help", style="bold #b7c8e1"), Text("Show the quick guide and the core workflow.", style="#d7deea"))
    commands.add_row(Text("/skills show <name>", style="bold #b7c8e1"), Text("Inspect a skill without activating it.", style="#d7deea"))
    commands.add_row(Text("/skills use <name>", style="bold #b7c8e1"), Text("Activate a skill so it affects the current session.", style="#d7deea"))
    commands.add_row(Text("/skills drop <name>", style="bold #b7c8e1"), Text("Deactivate one active skill.", style="#d7deea"))
    commands.add_row(Text("/skills clear", style="bold #b7c8e1"), Text("Clear the active skill stack.", style="#d7deea"))
    commands.add_row(Text("/skills add <path|owner/repo|url>", style="bold #b7c8e1"), Text("Install a local skill directory, git repo, or pack into this workspace.", style="#d7deea"))

    rules = Text()
    rules.append("Key rules", style="bold #8c93a1")
    rules.append("\n")
    rules.append("• Showing a skill is read-only.\n", style="#d7deea")
    rules.append("• Active skills shape the current session until you drop or clear them.\n", style="#d7deea")
    rules.append("• Project-provided shared skills may require ", style="#d7deea")
    rules.append("/skills trust", style="bold #b7c8e1")
    rules.append(" before they can be activated.", style="#d7deea")

    example = Text(
        "Example: /skills  →  /skills show critique  →  /skills use critique",
        style="#6f7785",
    )
    return Group(title, intro, Text(""), commands, Text(""), rules, Text(""), example)


def build_skills_overview_renderable(
    skills: list[SkillDefinition],
    active_ids: set[str],
) -> Group | Text:
    if not skills:
        lead = Text("No skills discovered yet.", style="bold #edf1f7")
        intro = Text(
            "Skills are reusable instruction bundles. Install or add one, then activate it when you want the agent to work differently.",
            style="#d7deea",
        )
        commands = Text()
        commands.append("Start here: ", style="#8c93a1")
        commands.append("/skills", style="bold #b7c8e1")
        commands.append("  ·  ", style="#6f7785")
        commands.append("/skills show <name>", style="bold #b7c8e1")
        commands.append("  ·  ", style="#6f7785")
        commands.append("/skills use <name>", style="bold #b7c8e1")
        install = Text(
            "Shared project skills belong in .agents/skills. Use .ite/skills only for local overrides.",
            style="#6f7785",
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
    summary.append("skills ", style="bold #edf1f7")
    summary.append(f"{len(skills)} installed", style="#d7deea")
    summary.append("  ·  ", style="#6f7785")
    summary.append(f"{active_count} active", style="bold #8fc7a2")
    summary.append("  ·  ", style="#6f7785")
    summary.append(f"{available_count} ready", style="bold #b7c8e1")
    if blocked_count:
        summary.append("  ·  ", style="#6f7785")
        summary.append(f"{blocked_count} blocked", style="bold #d5b07a")

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
    for skill in ordered:
        state = skill_state(skill, active_ids)
        title = Text(skill.identifier, style="bold #edf1f7")
        if skill.name != skill.identifier:
            title.append(f"  {skill.name}", style="#8c93a1")

        meta_bits = [_format_source_label(skill.source)]
        if skill.reference_files:
            ref_label = "ref" if len(skill.reference_files) == 1 else "refs"
            meta_bits.append(f"{len(skill.reference_files)} {ref_label}")
        if skill.tags:
            meta_bits.append(", ".join(skill.tags[:2]))
        detail = Text(" · ".join(meta_bits), style="#7d8594")

        description = Text(skill.description, style="#d7deea")
        table.add_row(
            Group(title, detail),
            _state_badge(state),
            Text("invoke", style="#8fc7a2") if skill.user_invocable else Text("assist", style="#8c93a1"),
            description,
        )

    source_counts = Counter(_format_source_label(skill.source) for skill in skills)
    footer = Text("roots ", style="#6f7785")
    footer.append(" · ".join(f"{name} {count}" for name, count in sorted(source_counts.items())), style="#8c93a1")

    hint = Text(
        "/skills show <name> inspects  ·  /skills use <name> activates  ·  only active skills shape this session",
        style="#6f7785",
    )
    return Group(summary, Text(""), table, Text(""), footer, hint)


def build_skill_detail_renderable(
    skill: SkillDefinition,
    active_ids: set[str],
) -> Group:
    state = skill_state(skill, active_ids)
    header = Text(skill.identifier, style="bold #edf1f7")
    if skill.user_invocable:
        header.append("  invoke", style="#8fc7a2")
    header.append(f"  {_format_source_label(skill.source)}", style="#7d8594")

    description = Text(skill.description, style="#d7deea")

    meta = Table.grid(expand=True)
    meta.add_column(width=14)
    meta.add_column(ratio=1)
    meta.add_row(Text("state", style="#8c93a1"), _state_badge(state))
    if skill.aliases:
        meta.add_row(
            Text("aliases", style="#8c93a1"),
            Text(", ".join(skill.aliases[:8]), style="#d7deea"),
        )
    if skill.version:
        meta.add_row(Text("version", style="#8c93a1"), Text(skill.version, style="#d7deea"))
    if skill.author:
        meta.add_row(Text("author", style="#8c93a1"), Text(skill.author, style="#d7deea"))
    if skill.homepage:
        meta.add_row(Text("homepage", style="#8c93a1"), Text(skill.homepage, style="#b7c8e1"))
    if skill.tags:
        meta.add_row(Text("tags", style="#8c93a1"), Text(", ".join(skill.tags[:8]), style="#d7deea"))

    references = None
    if skill.reference_files:
        reference_table = Table.grid(expand=True)
        reference_table.add_column(ratio=1)
        for path in skill.reference_files[:12]:
            reference_table.add_row(Text(path, style="#b7c8e1"))
        references = Group(
            Text("references", style="bold #8c93a1"),
            reference_table,
        )

    trust_note = None
    if skill.requires_trust and not skill.trusted:
        trust_note = Text(
            "Blocked until this workspace is trusted with /skills trust.",
            style="bold #d5b07a",
        )

    instructions = Group(
        Text("instructions", style="bold #8c93a1"),
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
) -> Group:
    lead = Text(title, style="bold #edf1f7")
    body = Text(message.strip(), style="#d7deea")
    stats = Text()
    stats.append(f"{active_count} active", style="#8fc7a2")
    stats.append("  ·  ", style="#6f7785")
    stats.append(f"{available_count} installed", style="#8c93a1")
    return Group(lead, body, Text(""), stats)


def build_skills_tool_renderable(payload: Mapping[str, object]) -> Group | None:
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
        )

    if action in {"show", "activate"}:
        return _build_skill_tool_detail(
            payload=payload,
            active_skills=active_skills,
            available_count=available_count,
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
        )

    return None


def _state_badge(state: str) -> Text:
    if state == "active":
        return Text("active", style="bold #8fc7a2")
    if state == "blocked":
        return Text("blocked", style="bold #d5b07a")
    return Text("ready", style="bold #b7c8e1")


def _format_source_label(source: str) -> str:
    label = str(source or "").strip().replace("compat-", "").replace("-", " ")
    return label or "skill root"


def _build_skills_summary_from_payload(
    *,
    skills: list[object],
    active_skills: set[str],
    available_count: int,
) -> Group:
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
    summary.append("skills ", style="bold #edf1f7")
    summary.append(f"{available_count or len(rows)} available", style="#d7deea")
    summary.append("  ·  ", style="#6f7785")
    summary.append(f"{len(active_skills)} active", style="#8fc7a2")
    if blocked_count:
        summary.append("  ·  ", style="#6f7785")
        summary.append(f"{blocked_count} blocked", style="#d5b07a")

    table = Table.grid(expand=True)
    table.add_column(ratio=4)
    table.add_column(width=10)
    table.add_column(width=9)
    table.add_column(ratio=6)
    for identifier, description, source, state, user_invocable in rows:
        meta = Text(_format_source_label(source), style="#7d8594")
        table.add_row(
            Group(Text(identifier, style="bold #edf1f7"), meta),
            _state_badge(state),
            Text("invoke", style="#8fc7a2") if user_invocable else Text("assist", style="#8c93a1"),
            Text(description, style="#d7deea"),
        )

    footer = Text(
        "The model can inspect other skills without activating them. Only active skills shape the standing session behavior.",
        style="#6f7785",
    )
    return Group(summary, Text(""), table, Text(""), footer)


def _build_skill_tool_detail(
    *,
    payload: Mapping[str, object],
    active_skills: list[str],
    available_count: int,
) -> Group:
    del available_count
    skill_id = str(payload.get("skill") or payload.get("name") or "").strip()
    title = Text(skill_id or "skill", style="bold #edf1f7")
    if payload.get("action") == "activate":
        title.append("  active now", style="#8fc7a2")
    elif skill_id in active_skills:
        title.append("  active", style="#8fc7a2")
    else:
        title.append("  inspected", style="#b7c8e1")

    description = Text(str(payload.get("description") or "").strip(), style="#d7deea")
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
