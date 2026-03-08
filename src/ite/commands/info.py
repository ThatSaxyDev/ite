"""Info commands: /stats, /tools, /mcp."""

from datetime import datetime
from ite.commands import Command, CommandContext, CommandRegistry
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
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


def register(registry: CommandRegistry) -> None:
    registry.register(Command(
        name="/stats", description="Show session statistics",
        handler=cmd_stats,
    ))
    registry.register(Command(
        name="/tools", description="List available tools",
        handler=cmd_tools,
    ))
    registry.register(Command(
        name="/mcp", description="Show MCP server status",
        handler=cmd_mcp,
    ))
