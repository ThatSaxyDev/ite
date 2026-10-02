"""Native learning mode commands; shared by Reup and the headless runtime."""

from __future__ import annotations

from ite.agent.learning import PROFILE_TEMPLATE
from ite.commands import Command, CommandContext, CommandRegistry
from ite.commands.help_catalog import COMMAND_VARIANTS


async def cmd_learn(ctx: CommandContext, args: list[str]) -> None:
    session = ctx.agent.session if ctx.agent else None
    if session is None:
        ctx.outcome = "failed"
        ctx.result = "No active session."
        ctx.console.print(ctx.result)
        return
    action = args[0].lower() if args else "status"
    try:
        if len(args) > 1:
            raise ValueError(
                "Use /learn [on|off|status|setup|init|reload|hint|review]."
            )
        if action in {"on", "off"}:
            was_enabled = session.learning.enabled
            session.set_learning_mode(action == "on")
            profile_creation_notice = ""
            if action == "on":
                path = session.config.cwd / "learn.md"
                try:
                    with path.open("x", encoding="utf-8") as stream:
                        stream.write(PROFILE_TEMPLATE)
                except FileExistsError:
                    pass
                except OSError:
                    profile_creation_notice = "Could not create learn.md; built-in teaching preferences are active.\n"
                else:
                    session.reload_learning_profile()
                    profile_creation_notice = (
                        f"Created {path} with baseline teaching preferences.\n"
                        "Ready to learn now. Review and personalize it whenever you like; "
                        "use /learn setup for guided setup or /learn reload after editing.\n"
                    )
            ctx.result = (
                "Learning mode ON · You write the code; iTE guides and reviews.\n"
                + profile_creation_notice
                + session.learning.profile_notice
                if action == "on"
                else "Learning mode OFF · Normal agent behavior restored. Suspended goals stay paused."
            )
            if action == "on" and not was_enabled:
                ctx.assistant_message = (
                    "What would you like to build or understand? A short description is enough. "
                    "Use `/learn hint` for a hint or `/learn review` for feedback on your attempt. Personalize your preferences with `/learn setup`, or edit learn.md and run `/learn reload`."
                    if not session.learning.objective
                    else "Continue with your learning request whenever you are ready. Use `/learn hint` for a hint or `/learn review` for feedback on your attempt. Personalize your preferences with `/learn setup`, or edit learn.md and run `/learn reload`."
                )
                session.learning.phase = "awaiting_learner"
                if session.context_manager is not None:
                    session.context_manager.add_assistant_message(ctx.assistant_message)
        elif action == "setup":
            raise ValueError(
                "Guided setup is available in the terminal UI. Open iTE and use /learn setup."
            )
        elif action == "init":
            session.require_learning_idle()
            path = session.config.cwd / "learn.md"
            with path.open("x", encoding="utf-8") as stream:
                stream.write(PROFILE_TEMPLATE)
            session.reload_learning_profile()
            ctx.result = f"Created {path} with baseline teaching preferences. Editing is optional; use /learn reload after changes."
        elif action == "reload":
            session.require_learning_idle()
            session.reload_learning_profile()
            ctx.result = session.learning.profile_notice
        elif action in {"hint", "review"}:
            session.require_learning_idle()
            if not session.learning.enabled:
                raise ValueError("Use /learn on before requesting a hint or review.")
            if action == "hint":
                session.learning.hint_level = min(3, session.learning.hint_level + 1)
                ctx.followup_prompt = (
                    "Give me the next helpful hint for our current learning step. "
                    "Explain the concept or diagnostic without writing the implementation."
                )
            else:
                ctx.followup_prompt = (
                    "Review my current attempt. Inspect my workspace changes and relevant files, "
                    "or ask me to share an attempt if none is available. Explain the most useful "
                    "issue and a next diagnostic step without writing replacement code."
                )
            ctx.result = (
                "Requesting a learning hint."
                if action == "hint"
                else "Reviewing your attempt."
            )
        elif action == "status":
            state = session.learning
            ctx.result = (
                f"Learning mode: {'ON' if state.enabled else 'OFF'} · {state.phase.replace('_', ' ')}\n"
                f"Objective: {state.objective or 'Not set yet'}\n"
                f"Next step: {state.current_step or 'Ask what you want to build or understand'}\n"
                f"Hint level: {state.hint_level}/3\n{state.profile_notice}\n"
                "\nLearning commands:\n"
                + "\n".join(
                    f"/learn {arguments} — {description}"
                    for arguments, description in COMMAND_VARIANTS["/learn"]
                )
            )
        else:
            raise ValueError(
                "Use /learn [on|off|status|setup|init|reload|hint|review]."
            )
    except (ValueError, OSError) as exc:
        ctx.outcome = "failed"
        ctx.result = (
            "learn.md already exists; edit it and use /learn reload."
            if isinstance(exc, FileExistsError)
            else str(exc)
        )
    ctx.console.print(ctx.result, markup=False)


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/learn",
            description="Learn by writing your own code; get hints and review",
            handler=cmd_learn,
        )
    )
