from __future__ import annotations

import getpass

from ite.commands import Command, CommandContext, CommandRegistry
from ite.config.loader import save_voice_settings


async def handle_voice(ctx: CommandContext, args: list[str]) -> bool:
    action = (args[0] if args else "status").strip().lower()

    if action == "status":
        status = "ready" if ctx.config.voice.enabled else "not enabled"
        key_status = (
            "Groq key saved"
            if str(ctx.config.voice.groq_api_key or "").strip()
            else "Groq key missing"
        )
        ctx.console.print(
            f"[bold]Voice typing:[/bold] {status}. [dim]{key_status}.[/dim]"
        )
        ctx.console.print("[dim]Use Ctrl+S in Reup to start/stop voice typing.[/dim]")
        return True

    if action == "setup":
        if len(args) > 1:
            ctx.console.print(
                "[yellow]For security, run /voice setup without pasting the key into the command.[/yellow]"
            )
            return True
        key = getpass.getpass("Groq API key: ").strip()
        if not key:
            ctx.console.print("[yellow]Voice setup cancelled.[/yellow]")
            return True
        save_voice_settings(enabled=True, groq_api_key=key)
        ctx.config.voice.enabled = True
        ctx.config.voice.groq_api_key = key
        ctx.console.print("[green]Voice typing is ready.[/green] Press Ctrl+S in Reup.")
        return True

    if action in {"on", "enable"}:
        save_voice_settings(enabled=True)
        ctx.config.voice.enabled = True
        ctx.console.print("[green]Voice typing is enabled.[/green] Press Ctrl+S in Reup.")
        return True

    if action in {"off", "disable"}:
        save_voice_settings(enabled=False)
        ctx.config.voice.enabled = False
        ctx.console.print("[yellow]Voice typing is disabled.[/yellow]")
        return True

    ctx.console.print(
        "[red]Usage:[/red] /voice status | /voice setup | /voice on | /voice off"
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
