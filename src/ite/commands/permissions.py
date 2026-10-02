"""Unified permissions command for workspace and tool access."""

from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry
from ite.config.config import PermissionMode
from ite.config.loader import save_global_permission_mode
from ite.safety.permissions import (
    DESCRIPTIONS,
    LABELS,
    MODE_USAGE,
    apply_mode,
    current_mode,
)


async def cmd_permissions(ctx: CommandContext, args: list[str]) -> None:
    if not args or args == ["status"]:
        mode = current_mode(ctx.config)
        ctx.result = f"Permissions: {LABELS[mode] if mode else 'Custom'}\n"
        ctx.result += "\n".join(
            f"/permissions {MODE_USAGE[item]} — {DESCRIPTIONS[item]}"
            for item in PermissionMode
        )
        ctx.console.print(ctx.result, markup=False)
        return
    try:
        if args == ["full", "access"]:
            mode = PermissionMode.FULL
        elif len(args) == 1:
            mode = PermissionMode(args[0])
        else:
            raise ValueError
        session = ctx.agent.session if ctx.agent else None
        if session:
            session.require_learning_idle()
        save_global_permission_mode(mode.value)
        apply_mode(ctx.config, mode)
        if session:
            apply_mode(session.config, mode)
            session.approval_manager.approval_policy = session.config.approval
        ctx.result = f"Permissions: {LABELS[mode]}"
        ctx.console.print(ctx.result, markup=False)
    except (ValueError, OSError) as error:
        ctx.outcome = "failed"
        ctx.result = (
            str(error) or "Usage: /permissions ask|automatic|full access|status"
        )
        ctx.console.print(ctx.result, markup=False)


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/permissions",
            description="Choose permissions for file access, commands, and internet tools",
            handler=cmd_permissions,
            variants=tuple(
                (MODE_USAGE[item], DESCRIPTIONS[item]) for item in PermissionMode
            )
            + (("status", "Show current permissions"),),
        )
    )
