"""Thread-scoped Goal mode slash commands."""

from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry


def _status_text(ctx: CommandContext) -> str:
    session = ctx.agent.session
    goal = session.goal_state
    if goal is None:
        return "No goal is active. Use /goal <objective> to start one."
    elapsed = int(goal.active_elapsed_seconds())
    minutes, seconds = divmod(elapsed, 60)
    lines = [
        f"Goal: {goal.objective}",
        f"Status: {goal.status.value.replace('_', ' ')}",
        f"Elapsed: {minutes}m {seconds:02d}s",
    ]
    if goal.milestones:
        lines.append("Plan:")
        lines.extend(
            f"{'✓' if item.completed else '•'} {item.title}"
            for item in goal.milestones
        )
    else:
        lines.append("Plan: iTE has not recorded milestones yet.")
    if goal.proofs:
        lines.append("Proof:")
        lines.extend(
            f"{'✓' if item.status == 'passed' else '•'} {item.label}"
            for item in goal.proofs[-5:]
        )
    if goal.blocker:
        lines.append(f"Blocker: {goal.blocker}")
    if goal.latest_evidence:
        lines.append(f"Latest evidence: {goal.latest_evidence}")
    return "\n".join(lines)


async def cmd_goal(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return
    session = ctx.agent.session
    if not args:
        ctx.console.print(_status_text(ctx))
        return

    action = args[0].lower()
    try:
        if action == "pause" and len(args) == 1:
            session.pause_goal()
            ctx.console.print("[dim]Goal paused.[/dim]")
            return
        if action == "resume" and len(args) == 1:
            session.resume_goal()
            ctx.console.print("[green]Goal resumed.[/green]")
            return
        if action == "clear" and len(args) == 1:
            session.clear_goal()
            ctx.console.print("[dim]Goal cleared; its history was retained.[/dim]")
            return
        if action == "edit":
            objective = " ".join(args[1:]).strip()
            if not objective:
                ctx.console.print("[error]Usage:[/error] /goal edit <objective>")
                return
            if session.goal_state and session.goal_state.status.value == "active":
                session.pause_goal(reason="Paused to edit the goal.")
            session.edit_goal(objective)
            ctx.console.print(
                "[dim]Goal updated and left paused. "
                "Use /goal resume to continue.[/dim]"
            )
            return

        if session.goal_state is not None:
            ctx.console.print(
                "[error]A goal already exists.[/error] Use /goal edit or /goal clear."
            )
            return
        session.create_goal(" ".join(args))
        ctx.console.print("[green]Goal created.[/green]")
    except ValueError as exc:
        ctx.console.print(f"[error]{exc}[/error]")


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/goal",
            description="Create, inspect, pause, resume, edit, or clear a durable goal",
            handler=cmd_goal,
        )
    )
