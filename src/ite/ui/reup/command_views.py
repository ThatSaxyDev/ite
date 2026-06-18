from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from rich.console import Group
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ite.tools.base import Tool, ToolRiskLevel
from ite.tools.mcp.mcp_tool import MCPTool
from ite.tools.subagent import SubagentTool

if TYPE_CHECKING:
    from ite.agent.session import Session


def _style_token(styles: dict[str, str] | None, key: str, fallback: str) -> str:
    if styles is None:
        return fallback
    return styles.get(key, fallback)


def build_tools_command_renderable(
    tools: list[Tool],
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    primary = _style_token(styles, "primary", "#b8d8ff")
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")
    sub_runtime = _style_token(styles, "sub_runtime", "#b7c8e1")
    sub_specialist = _style_token(styles, "sub_specialist", "#8fc7a2")
    custom_col = _style_token(styles, "custom", "#d7deea")

    grouped: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
        grouped[_tool_section_name(tool)].append(tool)

    summary = Text()
    summary.append("built-in ", style=muted)
    summary.append(str(len(grouped.get("Built-in", []))), style=f"bold {fg}")
    summary.append("  •  ", style=disabled)
    summary.append("verification ", style=muted)
    summary.append(str(len(grouped.get("Verification", []))), style=f"bold {warning}")
    summary.append("  •  ", style=disabled)
    summary.append("runtime ", style=muted)
    summary.append(str(len(grouped.get("Subagent Runtime", []))), style=f"bold {sub_runtime}")
    summary.append("  •  ", style=disabled)
    summary.append("specialists ", style=muted)
    summary.append(str(len(grouped.get("Subagent Specialists", []))), style=f"bold {sub_specialist}")
    summary.append("  •  ", style=disabled)
    summary.append("custom ", style=muted)
    summary.append(str(len(grouped.get("Custom", []))), style=f"bold {custom_col}")
    summary.append("  •  ", style=disabled)
    summary.append("mcp ", style=muted)
    summary.append(str(len(grouped.get("MCP", []))), style=f"bold {primary}")

    sections: list[object] = [
        Text.assemble(("available tools ", f"bold {fg}"), (str(len(tools)), f"bold {primary}")),
        summary,
    ]
    order = [
        "Built-in",
        "Verification",
        "Subagent Runtime",
        "Subagent Specialists",
        "Custom",
        "MCP",
    ]
    for section_name in order:
        section_tools = grouped.get(section_name, [])
        if not section_tools:
            continue
        sections.append(Text(""))
        sections.append(_section_header(section_name, len(section_tools), styles=styles))
        if section_name == "MCP":
            sections.append(_render_mcp_tool_groups(section_tools, styles=styles))
        else:
            sections.append(_render_tool_table(section_tools, styles=styles))

    return Group(*sections)


def build_mcp_command_renderable(
    servers: list[dict[str, object]],
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    primary = _style_token(styles, "primary", "#b8d8ff")
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")

    connected_count = sum(1 for s in servers if s.get("status") == "connected")
    ready_count = sum(1 for s in servers if s.get("status") == "ready")
    error_count = sum(1 for s in servers if s.get("status") == "error")

    summary = Text()
    summary.append("servers ", style=f"bold {fg}")
    summary.append(f"{len(servers)} installed", style=secondary)
    summary.append("  ·  ", style=disabled)
    summary.append(f"{connected_count} connected", style=f"bold {success}")
    summary.append("  ·  ", style=disabled)
    summary.append(f"{ready_count} ready", style=f"bold {primary}")
    if error_count:
        summary.append("  ·  ", style=disabled)
        summary.append(f"{error_count} error", style=f"bold {warning}")

    if not servers:
        lead = Text("No MCP servers configured.", style=f"bold {fg}")
        intro = Text(
            "MCP servers provide tools the agent can call. Define them in config, then connect.",
            style=secondary,
        )
        start_here = Text()
        start_here.append("Start here: ", style=muted)
        start_here.append("/mcp start <name>", style=f"bold {primary}")
        start_here.append("  ·  ", style=disabled)
        start_here.append("/mcp env set <name> <KEY> <VALUE>", style=f"bold {primary}")
        config_note = Text(
            "Add [mcp_servers.<name>] blocks in .ite/config.toml or ~/.ite/config.toml.",
            style=disabled,
        )
        return Group(summary, Text(""), lead, intro, Text(""), start_here, Text(""), config_note)

    table = Table.grid(expand=True)
    table.add_column(ratio=5)
    table.add_column(width=10)
    table.add_column(width=9)
    table.add_column(ratio=6)

    ordered = sorted(
        servers,
        key=lambda s: (
            {"connected": 0, "ready": 1, "error": 2}.get(str(s.get("status", "")), 3),
            str(s.get("name", "")),
        ),
    )

    for i, server in enumerate(ordered):
        name_str = str(server.get("name") or "server")
        status = str(server.get("status") or "unknown")
        detail_str = str(server.get("detail") or server.get("last_error") or "").strip()
        tools = str(server.get("tools", 0))
        transport = str(server.get("transport") or "")

        meta_bits = [transport] if transport else []
        if server.get("url"):
            meta_bits.append(str(server["url"]))
        if detail_str:
            meta_bits.append(detail_str)
        detail = Text(" · ".join(b for b in meta_bits if b), style=muted) if meta_bits else None

        title = Text(name_str, style=f"bold {fg}")
        col1 = Group(title, detail) if detail else title

        if status == "connected":
            status_badge = Text("connected", style=f"bold {success}")
        elif status == "ready":
            status_badge = Text("ready", style=f"bold {primary}")
        elif status == "error":
            status_badge = Text("error", style=f"bold {warning}")
        else:
            status_badge = Text(status, style=disabled)

        auto_label = (
            Text("auto", style=warning) if server.get("auto_connect")
            else Text("manual", style=muted)
        )
        tool_text = Text(f"{tools} tools", style=secondary)

        table.add_row(col1, status_badge, auto_label, tool_text)
        if i < len(ordered) - 1:
            table.add_row(Text(""), Text(""), Text(""), Text(""))

    transport_counts: dict[str, int] = {}
    for s in servers:
        t = str(s.get("transport") or "")
        if t:
            transport_counts[t] = transport_counts.get(t, 0) + 1
    footer = Text()
    for i, (t, c) in enumerate(sorted(transport_counts.items())):
        if i:
            footer.append("  ·  ", style=disabled)
        footer.append(f"{c} via ", style=muted)
        footer.append(t, style=f"bold {secondary}")

    hint = Text()
    hint.append("/mcp start ", style=f"bold {primary}")
    hint.append("<name>", style=primary)
    hint.append("      connect and register tools", style=muted)
    hint.append("\n", style="")
    hint.append("/mcp stop ", style=f"bold {primary}")
    hint.append("<name>", style=primary)
    hint.append("       disconnect", style=muted)
    hint.append("\n", style="")
    hint.append("/mcp env set ", style=f"bold {primary}")
    hint.append("<name> <KEY> <VALUE>", style=primary)
    hint.append("  store API key or token", style=muted)
    hint.append("\n", style="")
    hint.append("/mcp reset ", style=f"bold {primary}")
    hint.append("<name>", style=primary)
    hint.append("      clear OAuth tokens", style=muted)
    hint.append("\n", style="")
    hint.append("/mcp doctor ", style=f"bold {primary}")
    hint.append("<name>", style=primary)
    hint.append("     check for issues", style=muted)
    return Group(summary, Text(""), table, Text(""), footer, Text(""), hint)


def build_stats_command_renderable(
    stats: dict[str, object],
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    primary = _style_token(styles, "primary", "#b8d8ff")
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")

    last_compacted = stats.get("last_compacted_at")
    last_compacted_display = (
        datetime.fromisoformat(str(last_compacted)).strftime("%b %d · %I:%M %p")
        if last_compacted
        else "never"
    )
    token_usage = _token_usage_payload(stats.get("token_usage"))
    context_window = int(stats.get("context_window") or 0)
    latest_tokens = int(stats.get("latest_tokens") or 0)
    latest_cached_tokens = int(stats.get("latest_cached_tokens") or 0)
    used_pct = float(stats.get("context_used_pct") or 0.0)
    left_pct = float(stats.get("context_left_pct") or 0.0)
    turn_count = int(stats.get("turn_count") or 0)
    message_count = int(stats.get("message_count") or 0)

    headline = Text.assemble(
        ("session statistics", f"bold {fg}"),
        ("  •  ", disabled),
        (str(stats.get("session_id", "")), primary),
    )

    context_summary = Text()
    context_summary.append("context ", style=muted)
    context_summary.append(f"{used_pct:.1f}% used", style=f"bold {fg}")
    context_summary.append("  •  ", style=disabled)
    context_summary.append(f"{left_pct:.1f}% left", style=secondary)
    context_summary.append("  •  ", style=disabled)
    context_summary.append(
        f"{latest_tokens:,}/{context_window:,} tokens",
        style=f"bold {primary}",
    )

    activity = Text()
    activity.append("turns ", style=muted)
    activity.append(str(turn_count), style=f"bold {fg}")
    activity.append("  •  ", style=disabled)
    activity.append("messages ", style=muted)
    activity.append(str(message_count), style=f"bold {fg}")
    activity.append("  •  ", style=disabled)
    activity.append("compactions ", style=muted)
    activity.append(str(stats.get("compaction_count", 0)), style=f"bold {warning}")

    summary = Table.grid(expand=True, padding=(0, 2))
    summary.add_column(width=18)
    summary.add_column(ratio=1)
    summary.add_row(
        Text("Latest context", style=muted),
        Text(
            f"{latest_tokens:,} live · {latest_cached_tokens:,} cached",
            style=fg,
        ),
    )
    summary.add_row(
        Text("Plan state", style=muted),
        Text(
            ("on" if stats.get("plan_mode_enabled") else "off")
            + f"  •  {stats.get('plan_phase', 'idle')}",
            style=fg,
        ),
    )
    summary.add_row(
        Text("Tooling", style=muted),
        Text(
            f"{stats.get('tools_enabled', 0)} tools  •  {stats.get('mcp_servers', 0)} MCP connected",
            style=fg,
        ),
    )
    summary.add_row(Text("Last compacted", style=muted), Text(last_compacted_display, style=fg))

    usage_table = Table.grid(expand=True, padding=(0, 2))
    usage_table.add_column(width=18)
    usage_table.add_column(width=14, justify="right")
    usage_table.add_column(ratio=1)
    usage_table.add_row(
        Text("Prompt", style=muted),
        Text(f"{token_usage['prompt_tokens']:,}", style=f"bold {fg}"),
        Text("input tokens sent to the model", style=disabled),
    )
    usage_table.add_row(
        Text("Completion", style=muted),
        Text(f"{token_usage['completion_tokens']:,}", style=f"bold {fg}"),
        Text("assistant tokens returned", style=disabled),
    )
    usage_table.add_row(
        Text("Cached", style=muted),
        Text(f"{token_usage['cached_tokens']:,}", style=f"bold {success}"),
        Text("tokens reused from cache", style=disabled),
    )
    usage_table.add_row(
        Text("Total", style=muted),
        Text(f"{token_usage['total_tokens']:,}", style=f"bold {primary}"),
        Text("aggregate token usage so far", style=disabled),
    )

    detail_table = Table.grid(expand=True, padding=(0, 2))
    detail_table.add_column(width=18)
    detail_table.add_column(ratio=1)
    detail_table.add_row(Text("Pruned tool msgs", style=muted), Text(str(stats.get("pruned_tool_msgs", 0)), style=fg))
    detail_table.add_row(Text("Plan questions", style=muted), Text(f"{stats.get('plan_questions_asked', 0)}/{stats.get('plan_target_questions', 0)}", style=fg))
    detail_table.add_row(Text("Active plan", style=muted), Text("yes" if stats.get("active_plan_available") else "no", style=fg))
    detail_table.add_row(Text("Pending plan", style=muted), Text("yes" if stats.get("pending_plan_available") else "no", style=fg))
    detail_table.add_row(Text("Attachments", style=muted), Text(str(stats.get("pending_attachments", 0)), style=fg))
    detail_table.add_row(Text("Skills", style=muted), Text(f"{stats.get('active_skills', 0)} active  •  {stats.get('available_skills', 0)} available", style=fg))

    return Group(
        headline,
        Text("runtime health, context pressure, and plan state", style=muted),
        Text(""),
        context_summary,
        activity,
        Text(""),
        Rule(style=_style_token(styles, "border", "#2a2f3a")),
        Text("overview", style=f"bold {muted}"),
        summary,
        Text(""),
        Text("token usage", style=f"bold {muted}"),
        usage_table,
        Text(""),
        Text("planning and diagnostics", style=f"bold {muted}"),
        detail_table,
    )


def build_todos_command_renderable(
    session: Session,
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    state = session.export_todos_state()
    if not isinstance(state, dict):
        state = {}
    planning = state.get("planning", [])
    execution = state.get("execution", [])
    if not isinstance(planning, list):
        planning = []
    if not isinstance(execution, list):
        execution = []

    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    primary = _style_token(styles, "primary", "#b8d8ff")
    success = _style_token(styles, "success", "#8fc7a2")

    planning_visible = session.show_planning_todos
    planning_done = sum(1 for e in planning if bool(e.get("completed", False)))
    exec_done = sum(1 for e in execution if bool(e.get("completed", False)))
    total_done = planning_done + exec_done
    total = len(planning) + len(execution)

    summary = Text()
    summary.append("planning ", style=muted)
    summary.append(
        "shown" if planning_visible else "hidden",
        style=f"bold {primary}" if planning_visible else f"bold {muted}",
    )
    summary.append("  •  ", style=disabled)
    summary.append("execution scope ", style=muted)
    summary.append(str(len(execution)), style=f"bold {success}")
    summary.append("  •  ", style=disabled)
    summary.append("completed ", style=muted)
    summary.append(f"{total_done}/{total}", style=f"bold {fg}")

    blocks: list[object] = [
        Text("todos", style=f"bold {fg}"),
        summary,
    ]

    if execution:
        blocks.append(Text(""))
        blocks.append(_render_todos_scope("execution", execution, styles=styles))
    if planning and planning_visible:
        blocks.append(Text(""))
        blocks.append(_render_todos_scope("planning", planning, styles=styles))
    elif planning and not planning_visible:
        blocks.append(Text(""))
        blocks.append(
            Text(
                f"Planning has {len(planning)} items hidden. Use /todos planning on to see them.",
                style=disabled,
            )
        )

    blocks.append(Text(""))
    blocks.append(
        Text(
            "Use /todos planning on|off to toggle.  /todos list planning shows internals.",
            style=disabled,
        )
    )
    return Group(*blocks)


def _render_todos_scope(
    scope: str,
    entries: list[dict[str, object]],
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    success = _style_token(styles, "success", "#8fc7a2")
    primary = _style_token(styles, "primary", "#b8d8ff")

    scope_label = "execution" if scope == "execution" else "planning"
    accent = success if scope == "execution" else primary
    pending = [e for e in entries if not bool(e.get("completed", False))]
    done = [e for e in entries if bool(e.get("completed", False))]

    lines: list[object] = [
        Text.assemble(
            (scope_label, f"bold {accent}"),
            ("  "),
            (f"{len(done)}/{len(entries)} done", muted),
        ),
    ]
    for entry in pending[:8]:
        content = str(entry.get("content", "")).strip()
        if content:
            lines.append(Text.assemble(("○ ", disabled), (content, fg)))
    if done:
        lines.append(Text("recently done", style=disabled))
        for entry in done[:4]:
            content = str(entry.get("content", "")).strip()
            if content:
                lines.append(Text.assemble(("● ", accent), (content, muted)))
    return Group(*lines)


def build_workboard_command_renderable(
    session: Session,
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    state = session.export_todos_state()
    if not isinstance(state, dict):
        state = {}
    scopes = ["execution"] + (["planning"] if bool(session.show_planning_todos) else [])

    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    primary = _style_token(styles, "primary", "#b8d8ff")
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")

    completed = 0
    total = 0
    for scope in scopes:
        entries = state.get(scope, [])
        if not isinstance(entries, list):
            continue
        total += len(entries)
        completed += sum(1 for item in entries if bool(item.get("completed", False)))

    summary = Text()
    summary.append("plan ", style=muted)
    summary.append(
        "on",
        style=f"bold {success}" if session.plan_mode_enabled else f"bold {warning}",
    )
    summary.append("  •  ", style=disabled)
    summary.append(str(session.plan_phase), style=f"bold {primary}")
    summary.append("  •  ", style=disabled)
    summary.append(
        f"{completed}/{total} completed",
        style=f"bold {fg}" if total else muted,
    )

    blocks: list[object] = [
        Text("workboard", style=f"bold {fg}"),
        summary,
    ]
    for scope in scopes:
        entries = state.get(scope, [])
        if not isinstance(entries, list):
            continue
        blocks.append(Text(""))
        blocks.append(_render_workboard_scope(scope, entries, styles=styles))

    plan_text = (session.current_plan_text() or "").strip()
    if plan_text:
        blocks.append(Text(""))
        blocks.append(Text("implementation plan", style=f"bold {fg}"))
        for line in plan_text.splitlines()[:12]:
            stripped = line.strip()
            if stripped:
                blocks.append(Text(stripped, style=secondary))
    return Group(*blocks)


def build_subagent_command_renderable(
    subagents: list[object],
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    primary = _style_token(styles, "primary", "#b8d8ff")
    success = _style_token(styles, "success", "#8fc7a2")

    if not subagents:
        return Group(
            Text("no subagents discovered", style=f"bold {fg}"),
            Text(
                "Place subagent definitions in .ite/subagents/*.toml or use /subagent create.",
                style=muted,
            ),
        )

    summary = Text()
    summary.append("subagents ", style=f"bold {fg}")
    summary.append(str(len(subagents)), style=f"bold {primary}")
    summary.append("  •  ", style=disabled)
    summary.append("specialists ", style=muted)
    summary.append(str(len(subagents)), style=f"bold {success}")

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=5)
    table.add_column(ratio=7)

    for sa in sorted(subagents, key=lambda item: getattr(item, "name", "")):
        name = getattr(sa, "name", "")
        desc = getattr(sa, "description", "") or ""
        table.add_row(
            Text(name, style=f"bold {fg}"),
            Text(_truncate_tool_desc_str(desc), style=secondary),
        )

    hint = Text(
        "/subagent create adds a specialist  •  restart the agent after adding toml files to load them",
        style=disabled,
    )
    return Group(summary, Text(""), table, Text(""), hint)


def _truncate_tool_desc_str(desc: str, max_chars: int = 100) -> str:
    if len(desc) <= max_chars:
        return desc
    return desc[: max_chars - 3].rstrip() + "..."


def build_memory_command_renderable(
    *,
    session_id: str,
    workspace: str,
    controls: dict[str, object],
    long_term: list[dict],
    semantic: list[dict],
    short_term: list[dict],
    episodic: list[dict],
) -> Group:
    summary = Text()
    summary.append("session ", style="#8c93a1")
    summary.append(session_id, style="bold #edf1f7")
    summary.append("  •  ", style="#6f7785")
    summary.append("workspace ", style="#8c93a1")
    summary.append(workspace, style="bold #b8d8ff")

    inventory = Text()
    inventory.append("long-term ", style="#8c93a1")
    inventory.append(str(len(long_term)), style="bold #8fc7a2")
    inventory.append("  •  ", style="#6f7785")
    inventory.append("semantic ", style="#8c93a1")
    inventory.append(str(len(semantic)), style="bold #b8d8ff")
    inventory.append("  •  ", style="#6f7785")
    inventory.append("session ", style="#8c93a1")
    inventory.append(str(len(short_term)), style="bold #d5b07a")

    blocks: list[object] = [
        Text("memory", style="bold #edf1f7"),
        summary,
        inventory,
        Text(""),
        Text("active controls", style="bold #edf1f7"),
        _render_controls(controls),
        Text(""),
        Text("stores", style="bold #edf1f7"),
        _render_memory_store_table(long_term, "long-term"),
        Text(""),
        _render_memory_store_table(semantic, "workspace"),
        Text(""),
        _render_memory_store_table(short_term, "session"),
        Text(""),
        Text("recent episodes", style="bold #edf1f7"),
        _render_episode_lines(episodic),
    ]
    return Group(*blocks)


def _token_usage_payload(value: object) -> dict[str, int]:
    if isinstance(value, Mapping):
        prompt = int(value.get("prompt_tokens") or 0)
        completion = int(value.get("completion_tokens") or 0)
        total = int(value.get("total_tokens") or 0)
        cached = int(value.get("cached_tokens") or 0)
    else:
        prompt = int(getattr(value, "prompt_tokens", 0) or 0)
        completion = int(getattr(value, "completion_tokens", 0) or 0)
        total = int(getattr(value, "total_tokens", 0) or 0)
        cached = int(getattr(value, "cached_tokens", 0) or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
    }


def build_memory_prompt_command_renderable(query: str, bundle: dict[str, object]) -> Group:
    controls = bundle.get("controls", {}) if isinstance(bundle, dict) else {}
    blocks: list[object] = [
        Text("prompt memory debug", style="bold #edf1f7"),
        Text.assemble(("query ", "#8c93a1"), (query, "bold #b8d8ff")),
        Text(""),
        Text("selected controls", style="bold #edf1f7"),
        _render_controls(controls if isinstance(controls, dict) else {}),
        Text(""),
        Text("selected memory", style="bold #edf1f7"),
        _render_key_value_table(bundle.get("long_term", {}) if isinstance(bundle, dict) else {}, "long-term"),
        Text(""),
        _render_key_value_table(bundle.get("semantic", {}) if isinstance(bundle, dict) else {}, "workspace"),
        Text(""),
        _render_key_value_table(bundle.get("short_term", {}) if isinstance(bundle, dict) else {}, "session"),
        Text(""),
        Text("episodes", style="bold #edf1f7"),
        _render_episode_lines(bundle.get("episodic", []) if isinstance(bundle, dict) else []),
    ]
    return Group(*blocks)


def _render_workboard_scope(
    scope: str,
    entries: list[dict[str, object]],
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    primary = _style_token(styles, "primary", "#b8d8ff")
    success = _style_token(styles, "success", "#8fc7a2")
    title = "execution checklist" if scope == "execution" else "planning checklist"
    tone = success if scope == "execution" else primary
    pending = [entry for entry in entries if not bool(entry.get("completed", False))]
    done = [entry for entry in entries if bool(entry.get("completed", False))]

    lines: list[object] = [
        Text.assemble(
            (title, f"bold {tone}"),
            ("  ", disabled),
            (f"{len(done)}/{len(entries)} done", muted),
        ),
    ]
    for entry in pending[:5]:
        content = str(entry.get("content", "")).strip()
        if content:
            lines.append(Text.assemble(("○ ", disabled), (content, fg)))
    if done:
        lines.append(Text("recently done", style=disabled))
        for entry in done[:3]:
            content = str(entry.get("content", "")).strip()
            if content:
                lines.append(Text.assemble(("● ", tone), (content, muted)))
    return Group(*lines)


def _render_controls(controls: dict[str, object]) -> Group:
    sources = controls.get("sources", {}) if isinstance(controls, dict) else {}
    rows: list[object] = []
    visible = {key: value for key, value in controls.items() if key != "sources"} if isinstance(controls, dict) else {}
    matched = visible.pop("matched_contexts", []) if isinstance(visible, dict) else []
    if matched:
        rows.append(
            Text.assemble(
                ("matched contexts ", "#8c93a1"),
                (", ".join(str(item) for item in matched), "bold #b8d8ff"),
            )
        )
    for key, value in visible.items():
        source = str(sources.get(key, "")).strip() if isinstance(sources, dict) else ""
        line = Text.assemble(
            (f"{key.replace('_', ' ')} ", "#8c93a1"),
            (str(value), "bold #edf1f7"),
        )
        if source:
            line.append("  ←  ", style="#6f7785")
            line.append(source, style="#c9d3e0")
        rows.append(line)
    if not rows:
        rows.append(Text("No active controls.", style="#8c93a1"))
    return Group(*rows)


def _render_memory_store_table(records: list[dict], label: str) -> Group:
    if not records:
        return Group(
            Text.assemble((label, "bold #b8d8ff"), ("  "), ("no entries", "#8c93a1"))
        )
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=20)
    table.add_column(ratio=1)
    for record in records[:8]:
        table.add_row(
            Text(str(record.get("key", "")), style="bold #edf1f7"),
            Text(str(record.get("summary") or record.get("value") or ""), style="#c9d3e0"),
        )
    header = Text.assemble((label, "bold #b8d8ff"), ("  "), (f"{len(records)} entries", "#6f7785"))
    return Group(header, table)


def _render_key_value_table(records: object, label: str) -> Group:
    if not isinstance(records, dict) or not records:
        return Group(
            Text.assemble((label, "bold #b8d8ff"), ("  "), ("no entries", "#8c93a1"))
        )
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=20)
    table.add_column(ratio=1)
    for key, value in list(records.items())[:8]:
        table.add_row(
            Text(str(key), style="bold #edf1f7"),
            Text(str(value), style="#c9d3e0"),
        )
    return Group(
        Text.assemble((label, "bold #b8d8ff"), ("  "), (f"{len(records)} entries", "#6f7785")),
        table,
    )


def _render_episode_lines(records: object) -> Group:
    if not isinstance(records, list) or not records:
        return Group(Text("No recent episodes.", style="#8c93a1"))
    lines: list[object] = []
    for record in records[:6]:
        timestamp = str(record.get("timestamp", ""))[:16].replace("T", " ")
        summary = str(record.get("summary", "")).strip()
        lines.append(
            Text.assemble(
                (f"{timestamp}  ", "#6f7785"),
                (summary or "episode", "#c9d3e0"),
            )
        )
    return Group(*lines)


def _section_header(
    name: str,
    count: int,
    *,
    styles: dict[str, str] | None = None,
) -> Text:
    fg = _style_token(styles, "fg", "#edf1f7")
    primary = _style_token(styles, "primary", "#b8d8ff")
    section_icon = _style_token(styles, "section_icon", "#7d8591")
    header = Text()
    header.append(_section_icon(name), style=section_icon)
    header.append("  ")
    header.append(name.lower(), style=f"bold {fg}")
    header.append("  ")
    header.append(str(count), style=f"bold {primary}")
    return header


def _render_tool_table(
    tools: list[Tool],
    *,
    styles: dict[str, str] | None = None,
) -> Table:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=5)
    table.add_column(width=9)
    table.add_column(width=8)
    table.add_column(ratio=7)

    for tool in sorted(tools, key=lambda item: item.name):
        access = _tool_access_label(tool)
        risk_label, risk_style = _tool_risk_style(tool)
        table.add_row(
            Text(tool.name, style=f"bold {fg}"),
            _badge(access, _access_style(access)),
            _badge(risk_label, risk_style),
            Text(_truncate_tool_desc(tool), style=secondary),
        )
    return table


def _render_mcp_tool_groups(
    tools: list[Tool],
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    primary = _style_token(styles, "primary", "#b8d8ff")
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    disabled = _style_token(styles, "disabled", "#6f7785")
    by_server: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
        server, _, _ = tool.name.partition("__")
        by_server[server or "unknown"].append(tool)

    blocks: list[object] = []
    for index, server_name in enumerate(sorted(by_server)):
        if index:
            blocks.append(Text(""))
        blocks.append(
            Text.assemble(
                (server_name, f"bold {primary}"),
                ("  "),
                (f"{len(by_server[server_name])} tools", disabled),
            )
        )
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(ratio=5)
        table.add_column(width=9)
        table.add_column(width=8)
        table.add_column(ratio=7)
        for tool in sorted(by_server[server_name], key=lambda item: item.name):
            display_name = tool.name.partition("__")[2] or tool.name
            access = _tool_access_label(tool)
            risk_label, risk_style = _tool_risk_style(tool)
            table.add_row(
                Text(display_name, style=f"bold {fg}"),
                _badge(access, _access_style(access)),
                _badge(risk_label, risk_style),
                Text(_truncate_tool_desc(tool), style=secondary),
            )
        blocks.append(table)
    return Group(*blocks)


def _badge(label: str, style: str) -> Text:
    return Text(f" {label.upper()} ", style=style)


def _access_style(access: str) -> str:
    return "bold #d9ecff on #24384a" if access == "write" else "bold #d6f1e1 on #21372f"


_MCP_STATUS_LABELS: dict[str, str] = {
    "connected": "connected",
    "ready": "ready",
    "error": "error",
    "connecting": "connecting",
    "auth_required": "auth needed",
    "opening_browser": "opening",
    "waiting_for_callback": "waiting",
}


def _mcp_status_label(status: str) -> str:
    return _MCP_STATUS_LABELS.get(status, status.replace("_", " "))


def _mcp_status_color(status: str, *, styles: dict[str, str] | None = None) -> str:
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")
    primary = _style_token(styles, "primary", "#b8d8ff")
    error = _style_token(styles, "error", "#d28081")
    if status == "connected":
        return success
    if status in {"connecting", "auth_required", "opening_browser", "waiting_for_callback"}:
        return warning
    if status == "ready":
        return primary
    return error


def _tool_section_name(tool: Tool) -> str:
    if isinstance(tool, MCPTool):
        return "MCP"
    if isinstance(tool, SubagentTool):
        return "Subagent Specialists"
    module_name = tool.__class__.__module__
    if module_name.startswith("ite.tools.builtin.subagent_runtime_tools"):
        return "Subagent Runtime"
    if tool.name in {"run_tests", "run_linter", "run_typecheck"}:
        return "Verification"
    if module_name.startswith("ite.tools.builtin."):
        return "Built-in"
    if module_name.startswith("discovered_tool_") or not module_name.startswith("ite."):
        return "Custom"
    return "Built-in"


def _tool_access_label(tool: Tool) -> str:
    metadata = tool.get_metadata({})
    return "write" if metadata.mutating else "read"


def _tool_risk_style(tool: Tool) -> tuple[str, str]:
    metadata = tool.get_metadata({})
    styles = {
        ToolRiskLevel.LOW: ("low", "bold #d6f1e1 on #21372f"),
        ToolRiskLevel.MEDIUM: ("med", "bold #fff0d1 on #4c3a20"),
        ToolRiskLevel.HIGH: ("high", "bold #ffe1d6 on #4c2824"),
    }
    return styles.get(metadata.risk_level, ("med", "bold #fff0d1 on #4c3a20"))


def _truncate_tool_desc(tool: Tool, max_chars: int = 88) -> str:
    desc = getattr(tool, "description", "") or ""
    if len(desc) <= max_chars:
        return desc
    return desc[: max_chars - 3].rstrip() + "..."


def build_sandbox_command_renderable(
    enabled: bool,
    allowed_paths: list[str],
    cwd: str,
    *,
    styles: dict[str, str] | None = None,
) -> Group:
    fg = _style_token(styles, "fg", "#edf1f7")
    secondary = _style_token(styles, "secondary", "#c9d3e0")
    muted = _style_token(styles, "muted", "#8c93a1")
    disabled = _style_token(styles, "disabled", "#6f7785")
    primary = _style_token(styles, "primary", "#b8d8ff")
    success = _style_token(styles, "success", "#8fc7a2")
    warning = _style_token(styles, "warning", "#d5b07a")
    border = _style_token(styles, "border", "#2a2f3a")

    status_icon = "🔒" if enabled else "🔓"
    status_text = "enabled" if enabled else "disabled"
    status_color = success if enabled else warning

    status_line = Text()
    status_line.append(f"{status_icon}  ", style="")
    status_line.append(status_text, style=f"bold {status_color}")
    allowed_path_count = len(allowed_paths)
    path_label = "allowed path" if allowed_path_count == 1 else "allowed paths"
    status_line.append("  •  ", style=disabled)
    status_line.append(str(allowed_path_count), style=f"bold {fg}")
    status_line.append(f" {path_label}", style=muted)

    divider = Rule(style=border)

    blocks: list[object] = [
        Text("filesystem sandbox", style=f"bold {fg}"),
        status_line,
        Text(""),
        divider,
        Text(""),
    ]

    blocks.append(Text("workspace", style=f"bold {secondary}"))
    blocks.append(Text(cwd, style=primary))

    if allowed_paths:
        blocks.append(Text(""))
        blocks.append(Text("allowed paths", style=f"bold {secondary}"))
        for path in allowed_paths:
            blocks.append(Text(f"  + {path}", style=primary))

    blocks.append(Text(""))
    blocks.append(divider)
    blocks.append(Text(""))

    blocks.append(Text("quick reference", style=f"bold {fg}"))
    commands_table = Table(show_header=False, box=None, padding=(0, 1, 0, 0))
    commands_table.add_column("alias", style=primary, width=16)
    commands_table.add_column("description", style=muted)
    commands_table.add_row(
        "off" if enabled else "on",
        "disable sandbox" if enabled else "enable sandbox",
    )
    commands_table.add_row("allow <path>", "grant access to a path")
    commands_table.add_row("remove <path>", "revoke access to a path")
    commands_table.add_row("clear", "remove all allowed paths")
    commands_table.add_row("list", "show allowed paths")
    blocks.append(commands_table)

    return Group(*blocks)


def _section_icon(section_name: str) -> str:
    icons = {
        "Built-in": "◆",
        "Verification": "✓",
        "Subagent Runtime": "⇄",
        "Subagent Specialists": "◉",
        "Custom": "✦",
        "MCP": "⎇",
    }
    return icons.get(section_name, "•")
