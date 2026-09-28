"""Info commands: /stats, /tools, /mcp, /workboard, /memory."""

from collections import Counter, defaultdict
from datetime import datetime
from ite.commands import Command, CommandContext, CommandRegistry
from ite.config.loader import (
    clear_mcp_env_vars,
    get_data_dir,
    invalidate_mcp_keyring_cache,
    get_system_secrets_path,
    get_workspace_secrets_path,
    load_config,
    load_mcp_server_config,
    load_mcp_env_store,
    remove_mcp_env_var,
    save_mcp_server_config,
    save_mcp_env_var,
)
from ite.memory import MemoryManager
from ite.tools.base import Tool, ToolRiskLevel
from ite.tools.mcp.mcp_tool import MCPTool
from ite.tools.subagent import SubagentTool
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Group
from rich.markdown import Markdown
from rich.rule import Rule
from rich import box


async def cmd_stats(ctx: CommandContext, args: list[str]) -> None:
    stats = ctx.agent.session.get_stats()
    last_compacted = stats.get("last_compacted_at")
    last_compacted_display = (
        datetime.fromisoformat(last_compacted).strftime("%b %d · %I:%M %p")
        if last_compacted
        else "never"
    )
    title = Text.assemble(("📊 ", ""), ("Session Statistics", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            Text.assemble(
                ("Session ID: ", "code"),
                (stats["session_id"], "bold cyan"),
                ("\nTurn Count: ", "code"),
                (str(stats["turn_count"]), "bold cyan"),
                ("\nMessage Count: ", "code"),
                (str(stats["message_count"]), "bold cyan"),
                ("\nContext Window: ", "code"),
                (str(stats["context_window"]), "bold cyan"),
                ("\nContext Usage: ", "code"),
                (
                    f'{stats["context_used_pct"]}% used ({stats["context_left_pct"]}% left)',
                    "bold cyan",
                ),
                ("\nLatest Context Tokens: ", "code"),
                (str(stats["latest_tokens"]), "bold cyan"),
                ("\nCached Tokens (latest): ", "code"),
                (str(stats["latest_cached_tokens"]), "bold cyan"),
                ("\nToken Usage (total): ", "code"),
                (str(stats["token_usage"]), "bold cyan"),
                ("\nCompactions: ", "code"),
                (str(stats["compaction_count"]), "bold cyan"),
                ("\nLast Compacted At: ", "code"),
                (last_compacted_display, "bold cyan"),
                ("\nPruned Tool Messages: ", "code"),
                (str(stats["pruned_tool_msgs"]), "bold cyan"),
                ("\nPlan Mode: ", "code"),
                ("on" if stats.get("plan_mode_enabled") else "off", "bold cyan"),
                ("\nPlan Phase: ", "code"),
                (str(stats.get("plan_phase", "idle")), "bold cyan"),
                ("\nPlan Questions Asked: ", "code"),
                (str(stats.get("plan_questions_asked", 0)), "bold cyan"),
                ("\nPlan Question Target: ", "code"),
                (str(stats.get("plan_target_questions", 3)), "bold cyan"),
                ("\nTools Enabled: ", "code"),
                (str(stats["tools_enabled"]), "bold cyan"),
                ("\nMCP Servers: ", "code"),
                (str(stats["mcp_servers"]), "bold cyan"),
            ),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_tools(ctx: CommandContext, args: list[str]) -> None:
    tools = ctx.agent.session.tool_registry.get_tools()
    title = Text.assemble(
        ("🔧 ", ""), (f"Available Tools ({len(tools)})", "bold bright_white")
    )
    grouped: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
        grouped[_tool_section_name(tool)].append(tool)

    summary = Text.assemble(
        ("Built-in ", "code"),
        (str(len(grouped.get("Built-in", []))), "bold cyan"),
        ("  •  Verification ", "code"),
        (str(len(grouped.get("Verification", []))), "bold cyan"),
        ("  •  Subagent Runtime ", "code"),
        (str(len(grouped.get("Subagent Runtime", []))), "bold cyan"),
        ("  •  Specialists ", "code"),
        (str(len(grouped.get("Subagent Specialists", []))), "bold cyan"),
        ("  •  Custom ", "code"),
        (str(len(grouped.get("Custom", []))), "bold cyan"),
        ("  •  MCP ", "code"),
        (str(len(grouped.get("MCP", []))), "bold cyan"),
    )

    sections: list[object] = [summary]
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
        sections.append(Rule(style="grey35"))
        sections.append(_render_tool_section(section_name, section_tools))

    ctx.console.print()
    ctx.console.print(
        Panel(
            Group(*sections),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
            )
        )


def _visible_workboard_scopes(show_planning_todos: bool) -> list[str]:
    scopes = ["execution"]
    if show_planning_todos:
        scopes.append("planning")
    return scopes


def _todo_progress(state: dict[str, object], scopes: list[str]) -> tuple[int, int, int]:
    total = 0
    completed = 0
    pending = 0
    for scope in scopes:
        entries = state.get(scope, [])
        if not isinstance(entries, list):
            continue
        total += len(entries)
        for entry in entries:
            if bool(getattr(entry, "get", lambda *_: False)("completed", False)):
                completed += 1
            else:
                pending += 1
    return completed, pending, total


def _render_workboard_scope(
    scope: str,
    entries: list[dict[str, object]],
) -> Panel:
    pending = [entry for entry in entries if not bool(entry.get("completed", False))]
    completed = [entry for entry in entries if bool(entry.get("completed", False))]
    total = len(entries)
    done = len(completed)
    title = "Execution checklist" if scope == "execution" else "Planning checklist"
    tone = "green" if scope == "execution" else "cyan"

    lines: list[Text] = [
        Text.assemble(
            (f"{done}/{total} completed", f"bold {tone}"),
            ("  ", ""),
            (f"{len(pending)} pending", "yellow"),
        )
    ]

    if pending:
        lines.append(Text("Up next", style="muted"))
        for entry in pending[:6]:
            content = str(entry.get("content", "")).strip()
            if content:
                lines.append(Text.assemble(("  ☐ ", "muted"), (content, "code")))
        if len(pending) > 6:
            lines.append(Text(f"  +{len(pending) - 6} more pending", style="muted"))

    if completed:
        if pending:
            lines.append(Text(""))
        lines.append(Text("Done", style="muted"))
        for entry in completed[:3]:
            content = str(entry.get("content", "")).strip()
            if content:
                lines.append(Text.assemble(("  ☑ ", tone), (content, "dim")))
        if len(completed) > 3:
            lines.append(Text(f"  +{len(completed) - 3} more completed", style="muted"))

    return Panel(
        Group(*lines),
        title=Text(title, style=f"bold {tone}"),
        title_align="left",
        border_style=tone,
        box=box.ROUNDED,
        padding=(1, 2),
    )


async def cmd_workboard(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return

    session = ctx.agent.session
    state = session.export_todos_state()
    if not isinstance(state, dict):
        state = {}
    show_planning_todos = bool(session.show_planning_todos)
    scopes = _visible_workboard_scopes(show_planning_todos)
    completed, pending, total = _todo_progress(state, scopes)
    plan_text = (session.current_plan_text() or "").strip()

    summary = Panel(
        Group(
            Text.assemble(
            ("Plan mode: ", "code"),
            ("on", "bold cyan") if session.plan_mode_enabled else ("off", "dim"),
            ("  •  ", "muted"),
            ("Phase: ", "code"),
            (str(session.plan_phase), "bold cyan"),
            ("  •  ", "muted"),
            ("Planning todos: ", "code"),
            ("shown", "bold cyan") if show_planning_todos else ("hidden", "dim"),
            ),
            Text.assemble(
                ("Overall progress: ", "code"),
                (f"{completed}/{total} completed", "bold green") if total else ("0/0 completed", "dim"),
                ("  •  ", "muted"),
                (f"{pending} pending", "yellow") if total else ("0 pending", "dim"),
            ),
        ),
        title=Text("Summary", style="bold cyan"),
        title_align="left",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )

    sections: list[object] = [summary, Rule(style="grey35")]

    rendered_any_scope = False
    for scope in scopes:
        entries = state.get(scope, [])
        if not isinstance(entries, list) or not entries:
            continue
        rendered_any_scope = True
        sections.append(_render_workboard_scope(scope, entries))

    if not rendered_any_scope:
        sections.append(
            Panel(
                Text("No visible todos.", style="muted"),
                title=Text("Checklists", style="bold bright_white"),
                title_align="left",
                border_style="grey35",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    sections.append(Rule(style="grey35"))
    if plan_text:
        sections.append(
            Panel(
                Markdown(plan_text),
                title=Text("Implementation Plan", style="bold bright_white"),
                title_align="left",
                border_style="bright_white",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    else:
        sections.append(
            Panel(
                Text("No current plan saved.", style="muted"),
                title=Text("Implementation Plan", style="bold bright_white"),
                title_align="left",
                border_style="grey35",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    title = Text.assemble(("▣ ", "cyan"), ("Workboard", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            Group(*sections),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


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
        ToolRiskLevel.LOW: ("low", "green"),
        ToolRiskLevel.MEDIUM: ("med", "yellow"),
        ToolRiskLevel.HIGH: ("high", "red"),
    }
    return styles.get(metadata.risk_level, ("med", "yellow"))


def _truncate_tool_desc(tool: Tool, max_chars: int = 72) -> str:
    desc = getattr(tool, "description", "") or ""
    if len(desc) <= max_chars:
        return desc
    return desc[: max_chars - 3].rstrip() + "..."


def _render_tool_section(section_name: str, tools: list[Tool]) -> Panel:
    if section_name == "MCP":
        by_server: dict[str, list[Tool]] = defaultdict(list)
        for tool in tools:
            server, _, _ = tool.name.partition("__")
            by_server[server or "unknown"].append(tool)

        blocks: list[object] = []
        for index, server_name in enumerate(sorted(by_server)):
            if index:
                blocks.append(Rule(style="grey35"))
            blocks.append(_render_mcp_server_block(server_name, by_server[server_name]))
        return Panel(
            Group(*blocks),
            title=Text(f"MCP Tools ({len(tools)})", style="bold cyan"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )

    body = Group(*[_render_tool_line(tool) for tool in sorted(tools, key=lambda item: item.name)])
    return Panel(
        body,
        title=Text.assemble(
            (_section_icon(section_name) + " ", "cyan"),
            (f"{section_name} ", "bold cyan"),
            (f"{len(tools)}", "dim"),
        ),
        title_align="left",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def _render_mcp_server_block(server_name: str, tools: list[Tool]) -> Group:
    summary = Text.assemble(
        ("◦ ", "cyan"),
        (server_name, "bold cyan"),
        ("  ", ""),
        (f"{len(tools)} tools", "dim"),
    )
    lines: list[object] = [summary]
    for tool in sorted(tools, key=lambda item: item.name):
        lines.append(_render_tool_line(tool, display_name=tool.name.partition("__")[2] or tool.name))
    return Group(*lines)


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


def _render_tool_line(tool: Tool, *, display_name: str | None = None) -> Text:
    metadata = tool.get_metadata({})
    risk_label, risk_style = _tool_risk_style(tool)
    access = _tool_access_label(tool).upper()
    desc = _truncate_tool_desc(tool)
    name = display_name or tool.name
    return Text.assemble(
        ("• ", "grey50"),
        (name, "green bold"),
        ("  ", ""),
        ("[", "grey50"),
        (access, "cyan"),
        ("]", "grey50"),
        (" ", ""),
        ("[", "grey50"),
        (risk_label.upper(), risk_style),
        ("]", "grey50"),
        ("  ", ""),
        (desc, "dim"),
    )


async def cmd_mcp(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return

    mcp_mgr = ctx.agent.session.mcp_manager
    subcommand = args[0].lower() if args else "list"

    if subcommand == "start":
        if len(args) < 2:
            ctx.console.print("[error]Usage:[/error] [code]/mcp start <server>[/code]")
            return
        name = args[1]
        seen_updates: set[tuple[str, str | None]] = set()

        ctx.tui.start_spinner("/mcp", f"Starting {name}...")

        async def _status_update(payload: dict[str, str | None]) -> None:
            status = payload.get("status")
            detail = payload.get("detail")
            key = (str(status), detail)
            if key in seen_updates:
                return
            seen_updates.add(key)
            line = _format_mcp_status_line(name, str(status or ""), detail)
            if line:
                ctx.tui.append_line("/mcp", line.plain)

        try:
            await mcp_mgr.connect_server(
                name,
                ctx.agent.session.tool_registry,
                status_callback=_status_update,
            )
        except Exception as exc:
            ctx.tui.append_line("/mcp", f"Failed: {exc}")
        ctx.tui.stop_spinner()
        return

    if subcommand == "stop":
        if len(args) < 2:
            ctx.console.print("[error]Usage:[/error] [code]/mcp stop <server>[/code]")
            return
        name = args[1]
        try:
            removed = await mcp_mgr.disconnect_server(name, ctx.agent.session.tool_registry)
        except Exception as exc:
            ctx.console.print(f"[error]Failed to stop MCP server '{name}':[/error] {exc}")
            return
        ctx.console.print(
            f"[success]Stopped MCP server[/success] [cyan]{name}[/cyan] "
            f"[dim]({removed} tools removed)[/dim]"
        )
        return

    if subcommand == "reset":
        if len(args) < 2:
            ctx.console.print("[error]Usage:[/error] [code]/mcp reset <server>[/code]")
            return
        name = args[1]
        try:
            await mcp_mgr.disconnect_server(name, ctx.agent.session.tool_registry)
        except Exception:
            pass
        token_file = get_data_dir() / "auth" / "mcp_oauth_tokens.json"
        if token_file.exists():
            token_file.unlink()
        clear_mcp_env_vars(name, cwd=ctx.config.cwd)
        invalidate_mcp_keyring_cache()
        _reload_mcp_runtime_config(ctx)
        ctx.console.print(
            f"[success]Reset MCP server[/success] [cyan]{name}[/cyan]"
            f" [dim]— credentials and OAuth tokens cleared, use /mcp start {name} to re-authenticate[/dim]"
        )
        return

    if subcommand == "env":
        await _cmd_mcp_env(ctx, args[1:])
        return

    if subcommand == "add":
        await _cmd_mcp_add(ctx, args[1:])
        return

    if subcommand == "doctor":
        await _cmd_mcp_doctor(ctx, args[1:])
        return

    if subcommand not in {"list"}:
        ctx.console.print(
            "[error]Usage:[/error] [code]/mcp[/code], "
            "[code]/mcp start <server>[/code], "
            "[code]/mcp stop <server>[/code], "
            "[code]/mcp reset <server>[/code], "
            "[code]/mcp env ...[/code], "
            "[code]/mcp doctor <server>[/code]"
        )
        return

    servers = mcp_mgr.get_all_servers()

    # --- color tokens (match /skills palette) ---
    fg = "#edf1f7"
    secondary = "#d7deea"
    muted = "#8c93a1"
    primary = "#b7c8e1"
    success = "#8fc7a2"
    warning = "#d5b07a"
    disabled = "#6f7785"

    connected_count = sum(1 for s in servers if s["status"] == "connected")
    ready_count = sum(1 for s in servers if s["status"] == "ready")
    error_count = sum(1 for s in servers if s["status"] == "error")

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
        ctx.console.print()
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
        ctx.console.print(Group(summary, Text(""), lead, intro, Text(""), start_here, Text(""), config_note))
        return

    table = Table.grid(expand=True)
    table.add_column(ratio=5)
    table.add_column(width=10)
    table.add_column(width=9)
    table.add_column(ratio=6)

    ordered = sorted(
        servers,
        key=lambda s: (
            {"connected": 0, "ready": 1, "error": 2}.get(s["status"], 3),
            s["name"],
        ),
    )

    for i, server in enumerate(ordered):
        status = server["status"]
        name = Text(server["name"], style=f"bold {fg}")

        # detail sub-line (transport, url, error info)
        meta_bits = [server.get("transport", "")]
        if server.get("url"):
            meta_bits.append(server["url"])
        detail_str = str(server.get("detail") or server.get("last_error") or "")
        if detail_str:
            meta_bits.append(detail_str)
        detail = Text(" · ".join(b for b in meta_bits if b), style=muted)

        if status == "connected":
            status_badge = Text("connected", style=f"bold {success}")
        elif status == "ready":
            status_badge = Text("ready", style=f"bold {primary}")
        elif status == "error":
            status_badge = Text("error", style=f"bold {warning}")
        else:
            status_badge = Text(status, style=disabled)

        auto_label = Text("auto", style=warning) if server.get("auto_connect") else Text("manual", style=muted)
        tool_text = Text(f"{server['tools']} tools", style=secondary)

        table.add_row(
            Group(name, detail) if meta_bits else name,
            status_badge,
            auto_label,
            tool_text,
        )
        if i < len(ordered) - 1:
            table.add_row(Text(""), Text(""), Text(""), Text(""))

    transport_counts = Counter(s.get("transport", "") for s in servers)
    footer = Text()
    for i, (t, c) in enumerate(sorted(transport_counts.items())):
        if t:
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
    ctx.console.print()
    ctx.console.print(Group(summary, Text(""), table, Text(""), footer, Text(""), hint))


async def _cmd_mcp_env(ctx: CommandContext, args: list[str]) -> None:
    action = args[0].lower() if args else "list"
    scope, remaining = _extract_scope_flag(args[1:] if args else [])
    scope = scope or "global"

    if action == "list":
        server = remaining[0] if remaining else None
        await _print_mcp_env_listing(ctx, scope=scope, server=server)
        return

    if action == "where":
        if not remaining:
            ctx.console.print("[error]Usage:[/error] [code]/mcp env where <server>[/code]")
            return
        await _print_mcp_env_where(ctx, remaining[0])
        return

    if action == "set":
        if len(remaining) < 3:
            ctx.console.print(
                "[error]Usage:[/error] [code]/mcp env set <server> <KEY> <VALUE> [--scope global|workspace][/code]"
            )
            return
        server, key, value = remaining[0], remaining[1], " ".join(remaining[2:])
        path = save_mcp_env_var(cwd=ctx.config.cwd, scope=scope, server=server, key=key, value=value)
        _reload_mcp_runtime_config(ctx)
        ctx.console.print(
            f"[success]Stored MCP env[/success] [cyan]{server}:{key}[/cyan] "
            f"[dim]in {scope} secrets ({path})[/dim]"
        )
        return

    if action == "import":
        if len(remaining) < 2:
            ctx.console.print(
                "[error]Usage:[/error] [code]/mcp env import <server> <KEY> [PROCESS_ENV_NAME] [--scope global|workspace][/code]"
            )
            return
        server, key = remaining[0], remaining[1]
        process_env_name = remaining[2] if len(remaining) > 2 else key
        import os

        value = os.environ.get(process_env_name)
        if value is None:
            ctx.console.print(
                f"[error]Process env not found:[/error] [code]{process_env_name}[/code]"
            )
            return
        path = save_mcp_env_var(cwd=ctx.config.cwd, scope=scope, server=server, key=key, value=value)
        _reload_mcp_runtime_config(ctx)
        ctx.console.print(
            f"[success]Imported MCP env[/success] [cyan]{server}:{key}[/cyan] "
            f"[dim]from process env {process_env_name} into {scope} secrets ({path})[/dim]"
        )
        return

    if action in {"unset", "remove", "rm"}:
        if len(remaining) < 2:
            ctx.console.print(
                "[error]Usage:[/error] [code]/mcp env unset <server> <KEY> [--scope global|workspace][/code]"
            )
            return
        server, key = remaining[0], remaining[1]
        path = remove_mcp_env_var(cwd=ctx.config.cwd, scope=scope, server=server, key=key)
        _reload_mcp_runtime_config(ctx)
        ctx.console.print(
            f"[success]Removed MCP env[/success] [cyan]{server}:{key}[/cyan] "
            f"[dim]from {scope} secrets ({path})[/dim]"
        )
        return

    ctx.console.print(
        "[error]Usage:[/error] [code]/mcp env list [server][/code], "
        "[code]/mcp env where <server>[/code], "
        "[code]/mcp env set <server> <KEY> <VALUE>[/code], "
        "[code]/mcp env import <server> <KEY> [PROCESS_ENV_NAME][/code], "
        "[code]/mcp env unset <server> <KEY>[/code] "
        "[dim](defaults to --scope global)[/dim]"
    )


async def _cmd_mcp_add(ctx: CommandContext, args: list[str]) -> None:
    scope, remaining = _extract_scope_flag(args)
    scope = scope or "global"
    if not remaining:
        _print_mcp_add_usage(ctx)
        return

    server = remaining[0].strip()
    if not server or len(remaining) > 1:
        _print_mcp_add_usage(ctx)
        return

    source_scope = "workspace" if scope == "global" else "global"
    source_config = load_mcp_server_config(
        cwd=ctx.config.cwd,
        scope=source_scope,
        server=server,
    )
    if source_config is None:
        ctx.console.print(
            f"[error]MCP server not found in {source_scope} config:[/error] [code]{server}[/code]"
        )
        return

    try:
        path = save_mcp_server_config(
            cwd=ctx.config.cwd,
            scope=scope,
            server=server,
            config=source_config,
        )
    except Exception as exc:
        ctx.console.print(f"[error]Failed to copy MCP server:[/error] {exc}")
        return
    _reload_mcp_runtime_config(ctx)
    ctx.console.print(
        f"[success]Copied MCP server[/success] [cyan]{server}[/cyan] "
        f"[dim]from {source_scope} to {scope} config ({path})[/dim]"
    )


def _print_mcp_add_usage(ctx: CommandContext) -> None:
    ctx.console.print(
        "[error]Usage:[/error] "
        "[code]/mcp add <server> [--scope global|workspace][/code] "
        "[dim](copies the server definition from the opposite config scope)[/dim]"
    )


async def _cmd_mcp_doctor(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        ctx.console.print("[error]Usage:[/error] [code]/mcp doctor <server>[/code]")
        return
    server = args[0]
    config = ctx.config.mcp_servers.get(server)
    if config is None:
        ctx.console.print(f"[error]Unknown MCP server:[/error] [code]{server}[/code]")
        return

    global_store = load_mcp_env_store(ctx.config.cwd, "global")
    workspace_store = load_mcp_env_store(ctx.config.cwd, "workspace")
    global_keys = sorted(global_store.get(server, {}).keys())
    workspace_keys = sorted(workspace_store.get(server, {}).keys())
    merged_keys = sorted((config.env or {}).keys())
    missing = config.unresolved_env_vars()

    lines = [
        Text.assemble(("server ", "code"), (server, "bold cyan")),
        Text.assemble(("transport ", "code"), (config.effective_transport, "bold cyan")),
        Text.assemble(("auth ", "code"), (str(config.auth or "none"), "bold cyan")),
        Text.assemble(("startup timeout ", "code"), (f"{config.startup_timeout_sec:g}s", "bold cyan")),
        Text.assemble(("oauth timeout ", "code"), (f"{config.oauth_timeout_sec:g}s", "bold cyan")),
        Text.assemble(("global env ", "code"), (", ".join(global_keys) if global_keys else "none", "bold cyan")),
        Text.assemble(("workspace env ", "code"), (", ".join(workspace_keys) if workspace_keys else "none", "bold cyan")),
        Text.assemble(("effective env ", "code"), (", ".join(merged_keys) if merged_keys else "none", "bold cyan")),
    ]
    if missing:
        lines.append(Text.assemble(("missing env ", "code"), (", ".join(missing), "bold yellow")))
    else:
        lines.append(Text.assemble(("missing env ", "code"), ("none", "bold green")))

    ctx.console.print()
    ctx.console.print(
        Panel(
            Group(*lines),
            title=Text(f"MCP Doctor · {server}", style="bold bright_white"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def _print_mcp_env_listing(
    ctx: CommandContext,
    *,
    scope: str,
    server: str | None,
) -> None:
    if scope == "all":
        stores = {
            "global": load_mcp_env_store(ctx.config.cwd, "global"),
            "workspace": load_mcp_env_store(ctx.config.cwd, "workspace"),
        }
    else:
        stores = {scope: load_mcp_env_store(ctx.config.cwd, scope)}

    blocks: list[object] = []
    for label, store in stores.items():
        if blocks:
            blocks.append(Rule(style="grey35"))
        blocks.append(Text(label, style="bold cyan"))
        rows = []
        server_names = [server] if server else sorted(store.keys())
        for server_name in server_names:
            values = store.get(server_name, {})
            if not values:
                continue
            rows.append(Text.assemble((server_name, "bold bright_white"), ("  "), (f"{len(values)} vars", "dim")))
            for key in sorted(values):
                rows.append(
                    Text.assemble(
                        ("  ", ""),
                        (key, "cyan"),
                        (" = ", "dim"),
                        (_mask_secret(values[key]), "dim"),
                    )
                )
        if rows:
            blocks.extend(rows)
        else:
            blocks.append(Text("No stored MCP env values.", style="dim"))

    ctx.console.print()
    ctx.console.print(
        Panel(
            Group(*blocks),
            title=Text("MCP Env", style="bold bright_white"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def _print_mcp_env_where(ctx: CommandContext, server: str) -> None:
    global_store = load_mcp_env_store(ctx.config.cwd, "global")
    workspace_store = load_mcp_env_store(ctx.config.cwd, "workspace")
    config = ctx.config.mcp_servers.get(server)
    if config is None:
        ctx.console.print(f"[error]Unknown MCP server:[/error] [code]{server}[/code]")
        return

    lines = [
        Text.assemble(("global store ", "code"), (str(get_system_secrets_path()), "bold cyan")),
        Text.assemble(("workspace store ", "code"), (str(get_workspace_secrets_path(ctx.config.cwd)), "bold cyan")),
        Text(""),
        Text.assemble(("global keys ", "code"), (", ".join(sorted(global_store.get(server, {}).keys())) or "none", "bold cyan")),
        Text.assemble(("workspace keys ", "code"), (", ".join(sorted(workspace_store.get(server, {}).keys())) or "none", "bold cyan")),
        Text.assemble(("effective keys ", "code"), (", ".join(sorted((config.env or {}).keys())) or "none", "bold cyan")),
    ]
    ctx.console.print()
    ctx.console.print(
        Panel(
            Group(*lines),
            title=Text(f"MCP Env Where · {server}", style="bold bright_white"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def _extract_scope_flag(args: list[str]) -> tuple[str | None, list[str]]:
    remaining: list[str] = []
    scope: str | None = None
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--scope" and index + 1 < len(args):
            scope = args[index + 1].strip().lower()
            index += 2
            continue
        if item.startswith("--scope="):
            scope = item.split("=", 1)[1].strip().lower()
            index += 1
            continue
        remaining.append(item)
        index += 1
    if scope not in {None, "global", "workspace", "all"}:
        scope = "global"
    return scope, remaining


def _mask_secret(value: str) -> str:
    if not value:
        return "••••"
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * max(4, len(value) - 4) + value[-4:]


def _format_mcp_status_line(name: str, status: str, detail: str | None) -> Text:
    normalized = status.strip().lower()
    if normalized == "connecting":
        line = Text()
        line.append(name, style="#edf1f7")
        line.append("  connecting", style="#8c93a1")
        if detail and detail not in {"Connecting.", "Connecting"}:
            line.append("  ")
            line.append(detail, style="#c9d3e0")
        return line

    if normalized == "connected":
        line = Text()
        line.append("● ", style="bold green")
        line.append(name, style="#edf1f7")
        line.append("  connected", style="#8fc7a2")
        if detail:
            line.append("  ")
            line.append(detail, style="#8c93a1")
        return line

    if normalized == "error":
        line = Text()
        line.append("● ", style="bold yellow")
        line.append(name, style="#edf1f7")
        line.append("  error", style="#d5b07a")
        if detail:
            line.append("  ")
            line.append(detail, style="#c9d3e0")
        return line

    line = Text()
    line.append(name, style="#edf1f7")
    line.append(f"  {normalized or 'status'}", style="#8c93a1")
    if detail:
        line.append("  ")
        line.append(detail, style="#c9d3e0")
    return line


def _reload_mcp_runtime_config(ctx: CommandContext) -> None:
    fresh = load_config(ctx.config.cwd)
    ctx.config.mcp_servers = fresh.mcp_servers
    if not ctx.agent or not ctx.agent.session:
        return
    manager = ctx.agent.session.mcp_manager
    manager_config = getattr(manager, "config", None)
    if manager_config is not None:
        manager_config.mcp_servers = fresh.mcp_servers
    for name, client in getattr(manager, "_clients", {}).items():
        if name in fresh.mcp_servers:
            client.config = fresh.mcp_servers[name]


def _memory_records_table(title: str, records: list[dict], *, tone: str) -> Panel:
    if not records:
        body = Text("No entries.", style="dim")
    else:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan bold", min_width=18)
        table.add_column(style="code")
        for record in records:
            table.add_row(
                str(record.get("key", "")),
                str(record.get("summary") or record.get("value") or ""),
            )
        body = table

    return Panel(
        body,
        title=Text(title, style=f"bold {tone}"),
        title_align="left",
        border_style=tone,
        box=box.ROUNDED,
        padding=(1, 2),
    )


async def cmd_memory(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return

    session = ctx.agent.session
    manager = MemoryManager(ctx.config.cwd, session_id=session.session_id)
    if args and args[0].lower() == "prompt":
        query = " ".join(args[1:]).strip()
        if not query:
            ctx.console.print("[error]Usage: /memory prompt <query>[/error]")
            return
        bundle = manager.debug_prompt_memory(query)
        controls = bundle.get("controls", {}) if isinstance(bundle, dict) else {}
        sections: list[object] = [
            Panel(
                Text.assemble(
                    ("Query: ", "code"),
                    (query, "bold cyan"),
                ),
                title=Text("Prompt Query", style="bold cyan"),
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        ]
        control_lines = []
        visible_controls = {
            key: value for key, value in controls.items() if key != "sources"
        } if isinstance(controls, dict) else {}
        if visible_controls:
            for key, value in visible_controls.items():
                if key == "matched_contexts":
                    continue
                control_lines.append(
                    Text.assemble(
                        (f"{key.replace('_', ' ')}: ", "code"),
                        (str(value), "bold green"),
                    )
                )
            matched_contexts = controls.get("matched_contexts", []) if isinstance(controls, dict) else []
            if matched_contexts:
                control_lines.insert(
                    0,
                    Text.assemble(
                        ("matched contexts: ", "code"),
                        (", ".join(str(item) for item in matched_contexts), "bold green"),
                    ),
                )
        else:
            control_lines.append(Text("No active controls selected.", style="dim"))

        sections.extend(
            [
                Panel(
                    Group(*control_lines),
                    title=Text("Selected Controls", style="bold green"),
                    title_align="left",
                    border_style="green",
                    box=box.ROUNDED,
                    padding=(1, 2),
                ),
                _memory_records_table(
                    "Selected Long-Term Memory",
                    [{"key": k, "summary": v} for k, v in (bundle.get("long_term", {}) or {}).items()],
                    tone="cyan",
                ),
                _memory_records_table(
                    "Selected Workspace Memory",
                    [{"key": k, "summary": v} for k, v in (bundle.get("semantic", {}) or {}).items()],
                    tone="magenta",
                ),
                _memory_records_table(
                    "Selected Session Memory",
                    [{"key": k, "summary": v} for k, v in (bundle.get("short_term", {}) or {}).items()],
                    tone="yellow",
                ),
            ]
        )
        episodes = bundle.get("episodic", []) if isinstance(bundle, dict) else []
        episode_lines = [
            Text.assemble(
                (f"{str(ep.get('timestamp', ''))[:16].replace('T', ' ')}: ", "code"),
                (str(ep.get("summary", "")), "code"),
            )
            for ep in episodes
        ] or [Text("No episodic entries selected.", style="dim")]
        sections.append(
            Panel(
                Group(*episode_lines),
                title=Text("Selected Episodes", style="bold bright_white"),
                title_align="left",
                border_style="bright_white",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        ctx.console.print()
        ctx.console.print(
            Panel(
                Group(*sections),
                title=Text("🧠 Prompt Memory Debug", style="bold bright_white"),
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        return

    controls = manager.load_active_controls()
    long_term = manager.list_entries("long_term")
    semantic = manager.list_entries("semantic")
    short_term = manager.list_entries("short_term")
    episodic = manager.list_episodes()[-5:]

    control_lines: list[Text] = []
    sources = controls.get("sources", {}) if isinstance(controls, dict) else {}
    visible_controls = {
        key: value
        for key, value in controls.items()
        if key != "sources"
    } if isinstance(controls, dict) else {}

    if visible_controls:
        for key, value in visible_controls.items():
            if key == "matched_contexts":
                continue
            source = str(sources.get(key, "")).strip() if isinstance(sources, dict) else ""
            label = key.replace("_", " ")
            control_lines.append(
                Text.assemble(
                    (f"{label}: ", "code"),
                    (str(value), "bold cyan"),
                    (f"  ← {source}", "dim") if source else ("", ""),
                )
            )
        matched_contexts = controls.get("matched_contexts", []) if isinstance(controls, dict) else []
        if matched_contexts:
            control_lines.insert(
                0,
                Text.assemble(
                    ("matched contexts: ", "code"),
                    (", ".join(str(item) for item in matched_contexts), "bold cyan"),
                ),
            )
    else:
        control_lines.append(Text("No active controls.", style="dim"))

    recent_history = []
    for episode in episodic:
        timestamp = str(episode.get("timestamp", ""))[:16].replace("T", " ")
        recent_history.append(
            Text.assemble(
                (f"{timestamp}: ", "code"),
                (str(episode.get("summary", "")), "code"),
            )
        )
    if not recent_history:
        recent_history = [Text("No recent episodes.", style="dim")]

    summary = Panel(
        Group(
            Text.assemble(
                ("Session ID: ", "code"),
                (session.session_id, "bold cyan"),
                ("  •  ", "muted"),
                ("Workspace: ", "code"),
                (str(ctx.config.cwd), "bold cyan"),
            ),
            Text.assemble(
                ("Long-term: ", "code"),
                (str(len(long_term)), "bold cyan"),
                ("  •  ", "muted"),
                ("Semantic: ", "code"),
                (str(len(semantic)), "bold cyan"),
                ("  •  ", "muted"),
                ("Short-term: ", "code"),
                (str(len(short_term)), "bold cyan"),
                ("  •  ", "muted"),
                ("Recent episodes shown: ", "code"),
                (str(len(episodic)), "bold cyan"),
            ),
        ),
        title=Text("Summary", style="bold cyan"),
        title_align="left",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )

    ctx.console.print()
    ctx.console.print(
        Panel(
            Group(
                summary,
                Rule(style="grey35"),
                Panel(
                    Group(*control_lines),
                    title=Text("Active Controls", style="bold green"),
                    title_align="left",
                    border_style="green",
                    box=box.ROUNDED,
                    padding=(1, 2),
                ),
                _memory_records_table("Long-Term Memory", long_term, tone="cyan"),
                _memory_records_table("Workspace Memory", semantic, tone="magenta"),
                _memory_records_table("Session Memory", short_term, tone="yellow"),
                Panel(
                    Group(*recent_history),
                    title=Text("Recent Episodes", style="bold bright_white"),
                    title_align="left",
                    border_style="bright_white",
                    box=box.ROUNDED,
                    padding=(1, 2),
                ),
            ),
            title=Text("🧠 Memory", style="bold bright_white"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def register(registry: CommandRegistry) -> None:
    registry.register(Command(
        name="/stats", description="Show session statistics",
        handler=cmd_stats,
    ))
    registry.register(Command(
        name="/workboard", description="Show current plan and visible todos together",
        handler=cmd_workboard,
    ))
    registry.register(Command(
        name="/tools", description="List available tools",
        handler=cmd_tools,
    ))
    registry.register(Command(
        name="/mcp", description="Show MCP server status",
        handler=cmd_mcp,
    ))
    registry.register(Command(
        name="/memory", description="Inspect active controls and stored memory",
        handler=cmd_memory,
    ))
