"""Info commands: /stats, /tools, /mcp, /workboard, /memory."""

from datetime import datetime
from ite.commands import Command, CommandContext, CommandRegistry
from ite.memory import MemoryManager
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
    tools_table = Table.grid(padding=(0, 2))
    tools_table.add_column(style="code", justify="right", min_width=4)
    tools_table.add_column(style="green bold", min_width=20)
    tools_table.add_column(style="code")
    for i, tool in enumerate(tools, 1):
        desc = getattr(tool, "description", "")
        if desc and len(desc) > 60:
            desc = desc[:57] + "..."
        tools_table.add_row(
            Text(str(i), style="code"),
            Text(tool.name, style="cyan bold"),
            Text(desc, style="code"),
        )
    ctx.console.print()
    ctx.console.print(
        Panel(
            tools_table,
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


async def cmd_mcp(ctx: CommandContext, args: list[str]) -> None:
    mcp_mgr = ctx.agent.session.mcp_manager
    servers = mcp_mgr.get_all_servers()
    title = Text.assemble(
        ("🔌 ", ""), (f"MCP Servers ({len(servers)})", "bold bright_white")
    )
    if not servers:
        ctx.console.print()
        ctx.console.print(
            Panel(
                Text.assemble(
                    ("No MCP servers configured", "dim"),
                    ("\n\n", ""),
                    ("Add servers in ", "code"),
                    (".ite/config.toml", "green bold"),
                    (" under ", "code"),
                    ("[mcp_servers]", "green bold"),
                ),
                title=title,
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    else:
        mcp_table = Table.grid(padding=(0, 2))
        mcp_table.add_column(style="cyan bold", min_width=16)
        mcp_table.add_column(min_width=12)
        mcp_table.add_column(style="code")
        for server in servers:
            is_connected = server["status"] == "connected"
            status_style = "green bold" if is_connected else "red bold"
            mcp_table.add_row(
                Text(server["name"], style="cyan bold"),
                Text(f"● {server['status']}", style=status_style),
                Text(f"[{server['tools']} tools]", style="code"),
            )
        ctx.console.print()
        ctx.console.print(
            Panel(
                mcp_table,
                title=title,
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )


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
