"""Transient side-channel command: /aside."""

from __future__ import annotations

from dataclasses import dataclass

from ite.client.response import StreamEventType
from ite.commands import Command, CommandContext, CommandRegistry
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich import box


def is_aside_command_text(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    return lowered == "/aside" or lowered.startswith("/aside ")


@dataclass
class AsideResult:
    question: str
    answer: str
    error: str | None = None


def _build_aside_messages(session, question: str) -> list[dict[str, object]]:
    messages = list(session.context_manager.get_messages())
    plan_text = (session.current_plan_text() or "").strip()
    plan_context = (
        f"Plan mode: {'on' if session.plan_mode_enabled else 'off'}\n"
        f"Plan phase: {session.plan_phase}"
    )
    if plan_text:
        plan_context += f"\nCurrent plan:\n{plan_text}"
    messages.append(
        {
            "role": "user",
            "content": (
                "This is a transient /aside side question. "
                "Answer using the current conversation context and current plan context if relevant. "
                "Do not call tools. Do not treat this as a new task. "
                "Do not assume any plan or session state has changed. "
                "Keep the answer concise unless the user explicitly asks for depth.\n\n"
                f"{plan_context}\n\n"
                f"Aside question: {question.strip()}"
            ),
        }
    )
    return messages


async def execute_aside(session, question: str) -> AsideResult:
    question_text = question.strip()
    if not question_text:
        return AsideResult(question="", answer="", error="Missing aside question.")

    messages = _build_aside_messages(session, question_text)
    response_parts: list[str] = []
    usage = None
    error_text: str | None = None

    async for event in session.client.chat_completion(messages, tools=None, stream=True):
        if event.type == StreamEventType.TEXT_DELTA and event.text_delta:
            if event.text_delta.content:
                response_parts.append(event.text_delta.content)
        elif event.type == StreamEventType.MESSAGE_COMPLETE:
            usage = event.usage
        elif event.type == StreamEventType.ERROR:
            error_text = event.error or "Unknown provider error"
            break

    if usage is not None:
        session.context_manager.set_latest_usage(usage)
        session.context_manager.add_usage(usage)

    if error_text:
        return AsideResult(question=question_text, answer="", error=error_text)

    answer = "".join(response_parts).strip() or "No aside response returned."
    return AsideResult(question=question_text, answer=answer)


async def cmd_aside(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return

    question = " ".join(args).strip()
    if not question:
        ctx.console.print(
            "[error]Missing aside question.[/error] [dim]Use /aside <question>[/dim]"
        )
        return

    session = ctx.agent.session
    result = await execute_aside(session, question)
    if result.error:
        ctx.console.print(
            Panel(
                Text(result.error, style="error"),
                title=Text("/aside", style="bold bright_white"),
                title_align="left",
                border_style="bright_red",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        return

    ctx.console.print()
    ctx.console.print(
        Panel(
            Markdown(result.answer),
            title=Text("/aside", style="bold bright_white"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/aside",
            description="Ask a transient side question without changing the main thread",
            handler=cmd_aside,
        )
    )
