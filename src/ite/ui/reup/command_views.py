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


def build_tools_command_renderable(tools: list[Tool]) -> Group:
    grouped: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
        grouped[_tool_section_name(tool)].append(tool)

    summary = Text()
    summary.append("built-in ", style="#8c93a1")
    summary.append(str(len(grouped.get("Built-in", []))), style="bold #edf1f7")
    summary.append("  •  ", style="#6f7785")
    summary.append("verification ", style="#8c93a1")
    summary.append(str(len(grouped.get("Verification", []))), style="bold #d5b07a")
    summary.append("  •  ", style="#6f7785")
    summary.append("runtime ", style="#8c93a1")
    summary.append(str(len(grouped.get("Subagent Runtime", []))), style="bold #b7c8e1")
    summary.append("  •  ", style="#6f7785")
    summary.append("specialists ", style="#8c93a1")
    summary.append(str(len(grouped.get("Subagent Specialists", []))), style="bold #8fc7a2")
    summary.append("  •  ", style="#6f7785")
    summary.append("custom ", style="#8c93a1")
    summary.append(str(len(grouped.get("Custom", []))), style="bold #d7deea")
    summary.append("  •  ", style="#6f7785")
    summary.append("mcp ", style="#8c93a1")
    summary.append(str(len(grouped.get("MCP", []))), style="bold #b8d8ff")

    sections: list[object] = [
        Text.assemble(("available tools ", "bold #edf1f7"), (str(len(tools)), "bold #b8d8ff")),
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
        sections.append(_section_header(section_name, len(section_tools)))
        if section_name == "MCP":
            sections.append(_render_mcp_tool_groups(section_tools))
        else:
            sections.append(_render_tool_table(section_tools))

    return Group(*sections)


def build_mcp_command_renderable(servers: list[dict[str, object]]) -> Group:
    if not servers:
        return Group(
            Text("no mcp servers configured", style="bold #edf1f7"),
            Text("Add servers in .ite/config.toml under [mcp_servers].", style="#8c93a1"),
        )

    connected = sum(1 for item in servers if item.get("status") == "connected")
    ready = sum(1 for item in servers if item.get("status") == "ready")
    failed = sum(1 for item in servers if item.get("status") == "error")

    summary = Text()
    summary.append("connected ", style="#8c93a1")
    summary.append(str(connected), style="bold #8fc7a2")
    summary.append("  •  ", style="#6f7785")
    summary.append("ready ", style="#8c93a1")
    summary.append(str(ready), style="bold #b8d8ff")
    summary.append("  •  ", style="#6f7785")
    summary.append("failed ", style="#8c93a1")
    summary.append(str(failed), style="bold #d5b07a" if failed else "bold #edf1f7")

    blocks: list[object] = [
        Text.assemble(("configured servers ", "bold #edf1f7"), (str(len(servers)), "bold #b8d8ff")),
        summary,
    ]

    for server in servers:
        blocks.append(Text(""))
        blocks.append(_render_mcp_server(server))

    blocks.append(Text(""))
    blocks.append(
        Text(
            "Use /mcp start <server> to connect and /mcp stop <server> to disconnect.",
            style="#6f7785",
        )
    )
    return Group(*blocks)


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


def _section_header(name: str, count: int) -> Text:
    header = Text()
    header.append(_section_icon(name), style="#7d8591")
    header.append("  ")
    header.append(name.lower(), style="bold #edf1f7")
    header.append("  ")
    header.append(str(count), style="bold #b8d8ff")
    return header


def _render_tool_table(tools: list[Tool]) -> Table:
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=5)
    table.add_column(width=9)
    table.add_column(width=8)
    table.add_column(ratio=7)

    for tool in sorted(tools, key=lambda item: item.name):
        access = _tool_access_label(tool)
        risk_label, risk_style = _tool_risk_style(tool)
        table.add_row(
            Text(tool.name, style="bold #edf1f7"),
            _badge(access, _access_style(access)),
            _badge(risk_label, risk_style),
            Text(_truncate_tool_desc(tool), style="#c9d3e0"),
        )
    return table


def _render_mcp_tool_groups(tools: list[Tool]) -> Group:
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
                (server_name, "bold #b8d8ff"),
                ("  "),
                (f"{len(by_server[server_name])} tools", "#6f7785"),
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
                Text(display_name, style="bold #edf1f7"),
                _badge(access, _access_style(access)),
                _badge(risk_label, risk_style),
                Text(_truncate_tool_desc(tool), style="#c9d3e0"),
            )
        blocks.append(table)
    return Group(*blocks)


def _render_mcp_server(server: dict[str, object]) -> Group:
    name = str(server.get("name") or "server")
    status = str(server.get("status") or "unknown")
    detail = str(server.get("detail") or server.get("last_error") or "").strip()
    tools = str(server.get("tools", 0))
    transport = str(server.get("transport") or "remote")
    mode = "auto" if server.get("auto_connect") else "manual"

    lines: list[object] = [
        Text.assemble(
            (name, "bold #edf1f7"),
            ("  "),
            _badge(status, _status_style(status)),
            ("  "),
            (transport, "#8c93a1"),
            ("  •  ", "#6f7785"),
            (mode, "#8c93a1"),
            ("  •  ", "#6f7785"),
            (f"{tools} tools", "#8c93a1"),
        )
    ]
    if detail:
        lines.append(Text(detail, style="#c9d3e0"))
    return Group(*lines)


def _badge(label: str, style: str) -> Text:
    return Text(f" {label.upper()} ", style=style)


def _access_style(access: str) -> str:
    return "bold #d9ecff on #24384a" if access == "write" else "bold #d6f1e1 on #21372f"


def _status_style(status: str) -> str:
    if status == "connected":
        return "bold #d6f1e1 on #21372f"
    if status in {"connecting", "auth_required", "opening_browser", "waiting_for_callback"}:
        return "bold #fff0d1 on #4c3a20"
    if status == "ready":
        return "bold #d9ecff on #24384a"
    return "bold #ffe1d6 on #4c2824"


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

    summary = Text()
    summary.append("filesystem ", style=muted)
    summary.append(
        "on",
        style=f"bold {success}" if enabled else f"bold {warning}",
    )
    summary.append("  •  ", style=disabled)
    summary.append(str(len(allowed_paths)), style=f"bold {fg}")
    summary.append(" allowed path(s)", style=muted)

    blocks: list[object] = [
        Text("sandbox", style=f"bold {fg}"),
        summary,
    ]

    blocks.append(Text(""))
    blocks.append(Text("project cwd", style=f"bold {secondary}"))
    blocks.append(Text(cwd, style=primary))

    if allowed_paths:
        blocks.append(Text(""))
        blocks.append(Text("allowed paths", style=f"bold {secondary}"))
        for path in allowed_paths:
            blocks.append(Text(f"  + {path}", style=primary))

    blocks.append(Text(""))
    blocks.append(Text("commands", style=f"bold {fg}"))
    blocks.append(Text("  on|off    ", style=f"{muted}"))
    blocks.append(Text("toggle filesystem sandbox", style=muted))
    blocks.append(Text("  allow     ", style=f"{muted}"))
    blocks.append(Text("allow an extra path", style=muted))
    blocks.append(Text("  remove    ", style=f"{muted}"))
    blocks.append(Text("remove an allowed path", style=muted))
    blocks.append(Text("  clear     ", style=f"{muted}"))
    blocks.append(Text("clear all allowed paths", style=muted))
    blocks.append(Text("  list      ", style=f"{muted}"))
    blocks.append(Text("list allowed paths", style=muted))

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
