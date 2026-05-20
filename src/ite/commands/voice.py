from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry
from ite.config.loader import save_voice_settings


def _mask_secret(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "not set"
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * max(4, len(text) - 4) + text[-4:]


async def handle_voice(ctx: CommandContext, args: list[str]) -> bool:
    action = (args[0] if args else "status").strip().lower()

    if action == "status":
        enabled = "on" if ctx.config.voice.enabled else "off"
        ctx.console.print(
            f"[bold]Voice:[/bold] {enabled}  "
            f"[dim]Groq key: {_mask_secret(ctx.config.voice.groq_api_key)}[/dim]"
        )
        ctx.console.print("[dim]Use F8 in Reup to start/stop voice typing.[/dim]")
        return True

    if action == "setup":
        if len(args) < 2 or not args[1].strip():
            ctx.console.print("[red]Usage:[/red] /voice setup <groq-api-key>")
            return True
        key = args[1].strip()
        save_voice_settings(enabled=True, groq_api_key=key)
        ctx.config.voice.enabled = True
        ctx.config.voice.groq_api_key = key
        ctx.console.print("[green]Voice typing enabled.[/green] Press F8 in Reup.")
        return True

    if action in {"on", "enable"}:
        save_voice_settings(enabled=True)
        ctx.config.voice.enabled = True
        ctx.console.print("[green]Voice typing enabled.[/green] Press F8 in Reup.")
        return True

    if action in {"off", "disable"}:
        save_voice_settings(enabled=False)
        ctx.config.voice.enabled = False
        ctx.console.print("[yellow]Voice typing disabled.[/yellow]")
        return True

    ctx.console.print(
        "[red]Usage:[/red] /voice status | /voice setup <groq-api-key> | /voice on | /voice off"
    )
    return True


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/voice",
            description="Configure voice typing",
            handler=handle_voice,
        )
    )
