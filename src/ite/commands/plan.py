"""Plan mode commands: /plan, /plan on, /plan off."""

from ite.commands import Command, CommandContext, CommandRegistry
from rich.panel import Panel
from rich.text import Text
from rich import box


def _render_status(ctx: CommandContext) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return

    session = ctx.agent.session
    enabled = "on" if session.plan_mode_enabled else "off"
    title = Text.assemble(("🧭 ", ""), ("Plan Mode", "bold bright_white"))
    body = Text.assemble(
        ("Status: ", "code"),
        (enabled, "bold cyan" if session.plan_mode_enabled else "dim"),
        ("\nPhase: ", "code"),
        (session.plan_phase, "bold cyan"),
        ("\nQuestions asked: ", "code"),
        (str(session.plan_questions_asked), "bold cyan"),
        ("\nQuestion target: ", "code"),
        (str(getattr(session, "plan_target_questions", 3)), "bold cyan"),
        ("\n\nUse ", "code"),
        ("/plan on", "green bold"),
        (" or ", "code"),
        ("/plan off", "green bold"),
        (".", "code"),
    )
    ctx.console.print()
    ctx.console.print(
        Panel(
            body,
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_plan(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return

    session = ctx.agent.session
    if not args:
        _render_status(ctx)
        return

    arg = args[0].lower()
    if arg not in {"on", "off"}:
        ctx.console.print(
            "[error]Invalid usage.[/error] [dim]Use /plan, /plan on, or /plan off[/dim]"
        )
        return

    enable = arg == "on"
    session.set_plan_mode(enable)
    if enable:
        session.set_plan_phase("idle")
    else:
        session.set_plan_phase("idle")

    title = Text.assemble(("🧭 ", ""), ("Plan Mode Updated", "bold bright_white"))
    body = Text.assemble(
        ("Plan mode is now ", "code"),
        ("ON", "bold cyan") if enable else ("OFF", "bold white"),
        (".\n", "code"),
        (
            "Mutating tools are blocked until plan implementation is approved."
            if enable
            else "Normal execution behavior restored.",
            "dim",
        ),
    )
    ctx.console.print()
    ctx.console.print(
        Panel(
            body,
            title=title,
            title_align="left",
            border_style="green" if enable else "cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )



def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/plan",
            description="Show or change plan mode",
            handler=cmd_plan,
        )
    )
