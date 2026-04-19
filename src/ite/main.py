from ite.config.config import Config
from pathlib import Path
from typing import Any
from ite.config.loader import load_config, ensure_workspace_layout
from ite.cloud import ensure_cloud_auth, CloudAuthError
import logging
import sys
import re
import shlex
import select

# termios is POSIX-only (Unix/Linux/macOS). Windows does not have this module.
try:
    import termios
except ImportError:
    termios = None  # type: ignore
from ite.ui.tui import TUI, get_console
from ite.agent.events import AgentEventType
from ite.agent.agent import Agent
from ite.agent.session_manager import SessionSnapshot, SessionManager
from ite.attachment_refs import resolve_inline_attachment_refs
from ite.attachments import (
    AttachmentManager,
    MAX_ATTACHMENTS,
    build_user_model_content,
    build_user_text_with_manifest,
)
import click
import asyncio
import signal
from rich.panel import Panel
from rich.text import Text
from rich import box
from ite.ui.tool_narrative import progress_label
from dataclasses import dataclass
from ite.config.loader import save_mcp_server_config

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
except ImportError:
    PromptSession = None  # type: ignore[assignment]
    Completer = object  # type: ignore[assignment]
    Completion = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
console = get_console()


class _HintingMixin:
    _hint_map = {
        "c": "Use `ite` for reup. Use `ite -l` for legacy or `ite -d` for desktop.",
        "chat": "Use `ite` for reup. Use `ite -l` for legacy or `ite -d` for desktop.",
        "tui": "Use `ite --legacy` or `ite -l` for the legacy terminal UI.",
        "gui": "Use `ite --desktop` or `ite -d` for the desktop app.",
    }

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except click.NoSuchOption as exc:
            option_name = str(exc.option_name or "").strip()
            hint = self._hint_map.get(option_name)
            if hint:
                rendered = f"-{option_name}" if len(option_name) == 1 else f"--{option_name}"
                raise click.UsageError(f"No such option '{rendered}'. {hint}") from None
            raise


class IteCommand(_HintingMixin, click.Command):
    pass


class IteGroup(_HintingMixin, click.Group):
    pass


@dataclass(frozen=True)
class CommandPromptEntry:
    name: str
    description: str


class CLI:
    def __init__(self, config: Config):
        self.config = config
        self.agent: Agent | None = None
        self.tui = TUI(config=config, console=console)
        self._command_registry = None
        self._command_prompt_session = None
        self._last_dispatched_message: str | None = None
        self._last_user_message_for_retry: str | None = None
        self._pending_recoverable_tool_failures: list[dict[str, Any]] = []
        self._session_name_task: asyncio.Task | None = None

    def _get_command_registry(self):
        if self._command_registry is None:
            from ite.commands import build_registry

            self._command_registry = build_registry()
        return self._command_registry

    def _command_entries(self) -> list[CommandPromptEntry]:
        registry = self._get_command_registry()
        descriptions: dict[str, str] = {}
        for command in registry.all_commands():
            descriptions[command.name] = command.description
            for alias in command.aliases:
                descriptions[alias] = command.description
        return [
            CommandPromptEntry(name=name, description=descriptions[name])
            for name in sorted(descriptions)
        ]

    def _command_names(self) -> list[str]:
        return [entry.name for entry in self._command_entries()]

    def _get_prompt_session(self):
        if PromptSession is None or Completion is None:
            return None
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return None
        if self._command_prompt_session is not None:
            return self._command_prompt_session

        class SlashCommandCompleter(Completer):
            def __init__(self, commands: list[CommandPromptEntry]) -> None:
                self._commands = commands

            def get_completions(self, document, complete_event):
                text = document.text_before_cursor.lstrip()
                if not text.startswith("/"):
                    return
                current = text.split(maxsplit=1)[0].lower()
                for command in self._commands:
                    if current and not command.name.lower().startswith(current):
                        continue
                    yield Completion(
                        command.name,
                        start_position=-len(current),
                        display=command.name,
                        display_meta=command.description,
                    )

        self._command_prompt_session = PromptSession(
            completer=SlashCommandCompleter(self._command_entries()),
        )
        return self._command_prompt_session

    def _is_recoverable_sandbox_read_failure(
        self,
        *,
        tool_name: str,
        success: bool,
        error: str | None,
    ) -> bool:
        if success:
            return False
        if tool_name not in {"list_dir", "glob", "grep", "read_file"}:
            return False
        message = str(error or "")
        return "outside the project sandbox" in message.lower()

    def _flush_pending_tool_failures(self) -> None:
        while self._pending_recoverable_tool_failures:
            pending = self._pending_recoverable_tool_failures.pop(0)
            tool_kind = self._get_tool_kind(pending.get("name", ""))
            self.tui.tool_call_complete(
                call_id=pending.get("call_id", ""),
                name=pending.get("name", ""),
                tool_kind=tool_kind,
                success=pending.get("success", False),
                output=pending.get("output", ""),
                error=pending.get("error"),
                metadata=pending.get("metadata"),
                diff=pending.get("diff"),
                truncated=pending.get("truncated", False),
                exit_code=pending.get("exit_code"),
            )

    def _mark_pending_tool_failures_recovered(self) -> None:
        while self._pending_recoverable_tool_failures:
            pending = self._pending_recoverable_tool_failures.pop(0)
            self.tui.recoverable_sandbox_note(
                pending.get("name", "tool"),
                str(pending.get("error") or ""),
            )

    def _queue_attachment_paths(self, paths: list[str]) -> int:
        if not self.agent or not self.agent.session:
            return 0
        queue = self.agent.session.pending_attachment_paths
        added = 0
        for raw in paths:
            path = str(Path(raw).expanduser().resolve())
            if path in queue:
                continue
            if len(queue) >= MAX_ATTACHMENTS:
                break
            queue.append(path)
            added += 1
        return added

    def _render_attachment_queue(self) -> None:
        if not self.agent or not self.agent.session:
            return
        queue = self.agent.session.pending_attachment_paths
        if not queue:
            console.print("[dim]No queued attachments.[/dim]")
            return
        lines = [
            f"{idx}. {Path(path).name}  [dim]{path}[/dim]"
            for idx, path in enumerate(queue, start=1)
        ]
        console.print(
            Panel(
                "\n".join(lines),
                title=Text("Queued Attachments", style="bold cyan"),
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    def _consume_dropped_path_text(self, message: str) -> bool:
        if not self.agent or not self.agent.session:
            return False
        raw = (message or "").strip()
        if not raw:
            return False

        candidates: list[str]
        if "\n" in raw:
            candidates = [
                line.strip().strip('"').strip("'")
                for line in raw.splitlines()
                if line.strip()
            ]
        else:
            try:
                candidates = shlex.split(raw)
            except ValueError:
                candidates = [raw.strip().strip('"').strip("'")]

        if not candidates or len(candidates) > MAX_ATTACHMENTS:
            return False

        paths: list[str] = []
        for candidate in candidates:
            if not any(sep in candidate for sep in ("/", "\\")) and not candidate.startswith("~"):
                return False
            path = Path(candidate).expanduser()
            if not path.exists() or not path.is_file():
                return False
            paths.append(str(path))

        added = self._queue_attachment_paths(paths)
        if added <= 0:
            console.print("[dim]No new files queued.[/dim]")
        else:
            console.print(f"[dim]Queued {added} attachment(s).[/dim]")
        self._render_attachment_queue()
        return True

    async def _read_user_message(self) -> str:
        session = self._get_prompt_session()
        if session is not None:
            try:
                return (await session.prompt_async("\n> ", complete_while_typing=True)).strip()
            except KeyboardInterrupt:
                raise
            except EOFError:
                raise
            except Exception:
                # Fall back to the legacy reader if prompt_toolkit can't initialize.
                pass

        try:
            first_line = input("\n> ")
        except Exception:
            return ""

        lines = [first_line.rstrip("\n")]
        # If more input arrives immediately after the first line, treat it as paste
        # and collect until stdin is quiet.
        try:
            poll_s = 0.01
            settle_s = 0.35
            # First, wait briefly for follow-up lines to appear.
            saw_more = False
            for _ in range(20):  # ~200ms
                try:
                    readable, _, _ = select.select([sys.stdin], [], [], poll_s)
                except OSError:
                    # select.select doesn't work with stdin on Windows
                    break
                if readable:
                    saw_more = True
                    break
            if not saw_more:
                return lines[0].strip()

            quiet_for = 0.0
            while quiet_for < settle_s and len(lines) < 2048:
                try:
                    readable, _, _ = select.select([sys.stdin], [], [], poll_s)
                except OSError:
                    # select.select doesn't work with stdin on Windows
                    break
                if not readable:
                    quiet_for += poll_s
                    continue
                quiet_for = 0.0
                line = sys.stdin.readline()
                if line == "":
                    break
                lines.append(line.rstrip("\n"))
        except Exception:
            pass

        return "\n".join(lines).strip()

    def _confirm_before_send(self, message: str) -> bool:
        looks_pasted = "\n" in message or len(message) >= 220
        if not looks_pasted:
            return True

        console.print("\n[dim]Pasted input ready. Enter = Send, c = Cancel.[/dim]")

        # Drop any spillover from large multiline paste before reading choice.
        self._flush_stdin_input_queue()
        self._drain_stdin_buffer()
        try:
            choice = click.getchar()
        except KeyboardInterrupt:
            console.print()
            return False
        except Exception:
            return True

        if choice in {"\r", "\n"}:
            return True
        if str(choice).lower() == "c":
            return False
        return True

    def _drain_stdin_buffer(self, settle_ms: int = 120) -> None:
        """Drop buffered stdin lines and wait briefly for quiet."""
        quiet_for = 0.0
        settle_s = max(settle_ms, 0) / 1000.0
        poll_s = 0.01
        try:
            while quiet_for < settle_s:
                try:
                    readable, _, _ = select.select([sys.stdin], [], [], poll_s)
                except OSError:
                    # select.select doesn't work with stdin on Windows
                    break
                if not readable:
                    quiet_for += poll_s
                    continue
                quiet_for = 0.0
                chunk = sys.stdin.readline()
                if chunk == "":
                    break
        except Exception:
            pass

    def _flush_stdin_input_queue(self) -> None:
        """Force-clear unread terminal input bytes when possible (POSIX)."""
        try:
            if termios is None:
                return
            if not sys.stdin or not sys.stdin.isatty():
                return
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except Exception:
            pass


    async def run_interactive(self) -> str | None:
        self.tui.print_welcome(
            model=self.config.model_name,
            cwd=self.config.cwd,
            commands=self._command_names(),
        )
        async with Agent(
            config=self.config,
            confirmation_callback=self.tui.handle_confirmation,
            plan_question_callback=self._plan_question_callback,
        ) as agent:
            self.agent = agent

            try:
                while True:
                    try:
                        user_input = await self._read_user_message()
                        if not user_input:
                            continue
                        if self._consume_dropped_path_text(user_input):
                            continue
                        if self.agent and self.agent.session and not user_input.startswith("/"):
                            resolution = resolve_inline_attachment_refs(
                                user_input,
                                cwd=self.config.cwd,
                                existing_paths=self.agent.session.pending_attachment_paths,
                            )
                            if resolution.errors:
                                for error in resolution.errors:
                                    console.print(f"[warning]{error}[/warning]")
                                continue
                            self.agent.session.pending_attachment_paths = resolution.queued_paths
                            user_input = resolution.message
                        if not self._confirm_before_send(user_input):
                            continue

                        if await self._handle_command(user_input):
                            continue

                        normalized = self._normalize_plan_execution_request(user_input)
                        if normalized is None:
                            continue
                        user_input = normalized

                        intercepted = self._apply_tui_intent_assist(user_input)
                        if intercepted is None:
                            continue
                        user_input = intercepted
                        self._last_dispatched_message = user_input
                        self._last_user_message_for_retry = user_input

                        user_model_content = None
                        attachment_turn_id: str | None = None
                        if self.agent and self.agent.session and self.agent.session.pending_attachment_paths:
                            manager = AttachmentManager(self.config.cwd)
                            attachment_turn_id = f"tui_{self.agent.session.session_id}_{self.agent.session.turn_count + 1}"
                            staged, errors = manager.stage_paths(
                                self.agent.session.pending_attachment_paths,
                                attachment_turn_id,
                            )
                            if errors:
                                for err in errors:
                                    console.print(f"[warning]{err}[/warning]")
                            if staged:
                                user_model_content = build_user_model_content(
                                    user_input,
                                    staged,
                                    self.config.cwd,
                                )
                                user_input = build_user_text_with_manifest(
                                    user_input,
                                    staged,
                                    self.config.cwd,
                                )
                            self.agent.session.pending_attachment_paths = []

                        # Run agent in a cancellable task with SIGINT → cancel
                        response_task = asyncio.create_task(
                            self._process_message(
                                user_input,
                                user_model_content=user_model_content,
                                attachment_turn_id=attachment_turn_id,
                            )
                        )

                        loop = asyncio.get_running_loop()
                        loop.add_signal_handler(signal.SIGINT, response_task.cancel)

                        was_interrupted = False
                        try:
                            await response_task
                        except asyncio.CancelledError:
                            was_interrupted = True
                            self.tui.stop_spinner()
                            self.tui.end_assistant()
                            console.print("\n[grey50]⏹ Response interrupted[/grey50]")
                            await self._auto_save()
                        finally:
                            # Restore default so Ctrl+C works at the prompt
                            loop.remove_signal_handler(signal.SIGINT)

                        # ── Flight recorder: auto-save after every exchange ──
                        if not was_interrupted:
                            await self._auto_save()

                    except KeyboardInterrupt:
                        console.print()  # clean line after ^C at prompt
                    except EOFError:
                        break
            finally:
                # Crash safety: save on any unexpected exit
                self._auto_save_sync()

        console.print("\n[dim]Bye![/dim]")

    def _normalize_plan_execution_request(self, message: str) -> str | None:
        raw = message.strip()
        lowered = raw.lower()
        if lowered not in {
            "implement plan",
            "implement the plan",
            "go ahead and implement",
            "execute plan",
            "approve plan",
            "yes, implement plan",
        }:
            return raw

        if not self.agent or not self.agent.session:
            return raw

        session = self.agent.session
        if (
            session.plan_mode_enabled
            and session.plan_phase == "awaiting_implementation_confirmation"
        ):
            session.promote_pending_plan_to_active()
            session.set_plan_mode(False)
            session.set_plan_phase("idle")
            return Agent.PLAN_EXECUTE_PROMPT

        console.print(
            "[dim]No pending plan is awaiting approval. Ask for a plan first.[/dim]"
        )
        return None

    def _build_recovery_followup_prompt(self) -> str:
        return (
            "Continue from the last successful step only. "
            "Do not repeat completed work. "
            "Fix the remaining failure, run one final verification, and summarize changed files."
        )

    async def _run_tui_recovery_flow(self, reason: str) -> bool:
        console.print(f"[bold bright_white]Recovery:[/bold bright_white] [dim]{reason}[/dim]")
        choice = Prompt.ask(
            "1) Continue from last step  2) Retry last prompt  3) Stop",
            choices=["1", "2", "3"],
            default="1",
            show_choices=False,
        )
        if choice == "3":
            return False

        next_message = self._build_recovery_followup_prompt()
        if choice == "2":
            retry = (self._last_user_message_for_retry or "").strip()
            if not retry:
                console.print("[dim]No previous prompt to retry; using continue prompt instead.[/dim]")
            else:
                next_message = retry

        self._last_dispatched_message = next_message
        await self._process_message(next_message)
        return True

    def _should_suppress_intent_detection(self, message: str, *, plan_enabled: bool) -> bool:
        text = (message or "").strip()
        min_len = 7 if plan_enabled else 12
        if len(text) < min_len:
            return True
        if len(text.split()) < 3:
            if not (plan_enabled and re.search(r"\b(let'?s|lets|let us)\b", text.lower())):
                return True
        if message == Agent.PLAN_EXECUTE_PROMPT:
            return True
        return False

    def _detect_plan_intent(self, message: str) -> bool:
        text = (message or "").strip().lower()
        strong_phrases = (
            "make a plan",
            "implementation plan",
            "before coding",
            "steps to build",
            "plan this",
            "create a plan",
            "draft a plan",
            "what is the plan",
            "outline the plan",
        )
        if any(p in text for p in strong_phrases):
            return True

        # Treat collaborative "let's build/create/design ..." asks as planning-first.
        if bool(re.search(r"\b(let'?s|lets|let us)\s+(build|create|design|architect)\b", text)):
            return True

        build_intent_markers = (
            "i want to build",
            "i want to create",
            "help me build",
            "help me create",
            "how should i build",
            "how do i build",
            "design a",
            "build a",
            "create a",
            "architect a",
        )
        product_targets = (
            "app",
            "game",
            "website",
            "web app",
            "tool",
            "platform",
            "system",
            "project",
            "feature",
            "api",
            "dashboard",
        )
        if any(m in text for m in build_intent_markers) and any(t in text for t in product_targets):
            return True

        return bool(re.search(r"\b(plan|roadmap|steps)\b", text) and "implement" not in text)

    def _detect_execution_intent(self, message: str) -> bool:
        text = (message or "").strip().lower()
        phrases = (
            "implement now",
            "go ahead and build",
            "apply the changes",
            "start coding",
            "execute this",
            "ship it",
            "go implement",
            "build it now",
            "start implementation",
            "let's build",
            "lets build",
            "let's implement",
            "lets implement",
            "let us build",
            "let us implement",
            "build then",
            "implement then",
            "lets built",
            "let's built",
        )
        if any(p in text for p in phrases):
            return True
        if bool(re.search(r"\b(let'?s|lets|let us)\s+(build|built|implement|code|execute)\b", text)):
            return True
        if bool(re.search(r"\b(build|implement|start coding|execute)\b", text) and re.search(r"\b(then|next)\b", text)):
            return True
        return bool(
            re.search(r"\b(implement|build|built|code|execute|apply)\b", text)
            and re.search(r"\b(now|this|it|changes)\b", text)
        )

    def _prompt_intent_choice(
        self,
        prompt: str,
        *,
        default: str,
        option1_aliases: tuple[str, ...],
        option2_aliases: tuple[str, ...],
    ) -> str | None:
        while True:
            try:
                raw = console.input(f"{prompt} ({default}): ")
            except KeyboardInterrupt:
                console.print()
                return None

            value = (raw or "").strip().lower()
            if not value:
                return default
            if value == "1" or value in option1_aliases:
                return "1"
            if value == "2" or value in option2_aliases:
                return "2"
            console.print("[error]Please enter 1 or 2.[/error]")

    def _apply_tui_intent_assist(self, message: str) -> str | None:
        if not self.agent or not self.agent.session:
            return message
        if message.startswith("/"):
            return message

        session = self.agent.session
        plan_enabled = bool(session.plan_mode_enabled)
        if self._should_suppress_intent_detection(message, plan_enabled=plan_enabled):
            return message

        if not plan_enabled and self._detect_plan_intent(message):
            console.print(
                "\n[bold bright_white]Plan suggestion:[/bold bright_white] "
                "[dim]This looks like a planning request.[/dim]"
            )
            choice = self._prompt_intent_choice(
                "1) Enable Plan mode and continue  2) Send normally",
                default="1",
                option1_aliases=("enable", "plan", "yes", "y", "on"),
                option2_aliases=("send", "normal", "no", "n", "off"),
            )
            if choice is None:
                return None
            if choice == "1":
                session.set_plan_mode(True)
                session.set_plan_phase("idle")
                console.print("[dim]Plan mode enabled.[/dim]")
            return message

        if plan_enabled and self._detect_execution_intent(message):
            console.print(
                "\n[bold bright_white]Execution suggestion:[/bold bright_white] "
                "[dim]This looks like execution while Plan mode is ON. "
                "Choose option 1 below or type /plan off to leave Plan mode.[/dim]"
            )
            choice = self._prompt_intent_choice(
                "1) Turn Plan mode off and continue  2) Stay in Plan mode",
                default="1",
                option1_aliases=("turn off", "off", "disable", "yes", "y"),
                option2_aliases=("stay", "keep", "plan", "no", "n"),
            )
            if choice is None:
                return None
            if choice == "1":
                session.set_plan_mode(False)
                session.set_plan_phase("idle")
                console.print("[dim]Plan mode disabled. You can also do this manually with /plan off.[/dim]")
                return message
            console.print(
                "[dim]Staying in plan mode; will continue with planning flow. "
                "Type /plan off whenever you want to start execution instead.[/dim]"
            )
            return (
                f"{message}\n\n"
                "Stay in plan mode. Do not execute changes yet. "
                "Ask clarifying questions first, then provide an implementation plan."
            )

        return message

    async def _handle_command(self, user_input: str) -> bool:
        """Handle CLI commands. Returns True if handled, False if it should be sent to agent."""
        if self._consume_dropped_path_text(user_input):
            return True
        if not user_input.startswith("/"):
            return False

        parts = user_input.split()
        command = parts[0].lower()
        args = parts[1:]

        from ite.commands import CommandContext

        registry = self._get_command_registry()
        ctx = CommandContext(
            config=self.config,
            agent=self.agent,
            tui=self.tui,
            console=console,
        )
        return await registry.dispatch(command, args, ctx)

    async def _auto_save(self) -> None:
        """Flight recorder: silently save session state after every exchange."""
        if not self.agent or not self.agent.session:
            return
        if self.agent.session.turn_count == 0:
            return  # Don't save empty sessions

        try:
            session = self.agent.session
            session_manager = SessionManager()

            # Generate smart name on first exchange
            if session.name is None and session.turn_count > 0:
                self._maybe_start_session_name_task(session)
            elif session.should_refresh_auto_name():
                self._maybe_start_session_name_task(session)

            snapshot = SessionSnapshot(
                **session.snapshot_kwargs(workspace_path=str(self.config.cwd.resolve()))
            )
            session_manager.save_session(snapshot)
            # console.print(
            #     f"[dim]  💾 Session auto-saved · {session.turn_count} turns · {session.name or session.session_id[:8]}[/dim]"
            # )

            # Auto-checkpoint every 5 turns
            if session.turn_count > 0 and session.turn_count % 5 == 0:
                cp_id = session_manager.save_checkpoint(snapshot)
                if self.config.debug:
                    console.print(f"[dim]  📌 Auto-checkpoint · {cp_id[:20]}…[/dim]")

        except Exception as e:
            logger.warning("Auto-save failed: %s", e)

    def _maybe_start_session_name_task(self, session) -> None:
        if session.name is not None or session.turn_count <= 0:
            return
        if self._session_name_task is not None and not self._session_name_task.done():
            return
        self._session_name_task = asyncio.create_task(
            self._finalize_session_name_in_background(session)
        )

    async def _finalize_session_name_in_background(self, session) -> None:
        try:
            if session.name is not None and not session.should_refresh_auto_name():
                return
            generated = await self._generate_session_name(session)
            generated = generated.strip()
            if not generated:
                return
            session.set_auto_name(generated)
            session_manager = SessionManager()
            snapshot = SessionSnapshot(
                **session.snapshot_kwargs(workspace_path=str(session.config.cwd.resolve()))
            )
            session_manager.save_session(snapshot)
        except Exception as e:
            logger.warning("Background session naming failed: %s", e)
        finally:
            current = asyncio.current_task()
            if self._session_name_task is current:
                self._session_name_task = None

    def _auto_save_sync(self) -> None:
        """Synchronous fallback for auto-save in finally blocks."""
        if not self.agent or not self.agent.session:
            return
        if self.agent.session.turn_count == 0:
            return  # Don't save empty sessions

        try:
            session = self.agent.session
            session_manager = SessionManager()
            snapshot = SessionSnapshot(
                **session.snapshot_kwargs(workspace_path=str(self.config.cwd.resolve()))
            )
            session_manager.save_session(snapshot)
        except Exception:
            pass

    async def _plan_question_callback(self, payload: dict) -> dict:
        question = str(payload.get("question", "")).strip()
        options = [str(o) for o in payload.get("options", []) if str(o).strip()]
        recommended_index = payload.get("recommended_index")
        allow_free_text = bool(payload.get("allow_free_text", True))
        question_number = 1
        if self.agent and self.agent.session:
            question_number = max(1, self.agent.session.plan_questions_asked + 1)

        return self.tui.prompt_plan_question(
            question=question,
            options=options,
            question_number=question_number,
            recommended_index=recommended_index,
            allow_free_text=allow_free_text,
        )

    async def _generate_session_name(self, session) -> str:
        """Use the LLM to generate a concise session title from the first exchange."""
        first_user = ""
        try:
            context = session.name_generation_context()
            first_user = context.get("first_user", "")
            first_assistant = context.get("first_assistant", "")
            latest_user = context.get("latest_user", "")
            focus_hint = context.get("focus_hint", "")

            if not first_user:
                return "New thread"

            naming_messages = [
                {
                    "role": "user",
                    "content": (
                        "Generate a concise 3-6 word title for this conversation. "
                        "Prefer the current active work focus over the initial exploratory question if they differ. "
                        "Reply with ONLY the title text, nothing else. No quotes, no punctuation at the end.\n\n"
                        f"Initial user: {first_user}\n"
                        + (f"Initial assistant: {first_assistant}\n" if first_assistant else "")
                        + (f"Latest user: {latest_user}\n" if latest_user else "")
                        + (f"Active focus: {focus_hint}" if focus_hint else "")
                    ),
                }
            ]

            title = ""
            async for event in session.client.chat_completion(
                naming_messages, tools=None, stream=False
            ):
                if event.text_delta and event.text_delta.content:
                    title += event.text_delta.content

            title = title.strip()[:60]
            if title:
                return title

        except Exception as e:
            logger.warning("Session naming failed: %s", e)

        # Fallback: first sentence of user message, max 60 chars
        first_sentence = first_user.split(".")[0].split("?")[0].split("!")[0][:60]
        return first_sentence.strip() or "New thread"

    def _get_tool_kind(self, tool_name: str) -> str | None:
        tool = self.agent.session.tool_registry.get(tool_name)
        if not tool:
            return None
        return tool.kind.value

    def _resolve_todo_scope(
        self,
        *,
        arguments: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if metadata and isinstance(metadata.get("scope"), str):
            return str(metadata["scope"]).strip().lower()
        if arguments and isinstance(arguments.get("scope"), str):
            return str(arguments["scope"]).strip().lower()
        if (
            self.agent
            and self.agent.session
            and self.agent.session.plan_mode_enabled
            and self.agent.session.plan_phase != "executing"
        ):
            return "planning"
        return "execution"

    def _should_hide_planning_todos(self, scope: str) -> bool:
        if scope != "planning":
            return False
        if not self.agent or not self.agent.session:
            return True
        return not bool(self.agent.session.show_planning_todos)

    async def _process_message(
        self,
        message: str,
        user_model_content: str | list[dict] | None = None,
        attachment_turn_id: str | None = None,
    ) -> str | None:
        if not self.agent:
            return None

        assistant_streaming = False
        final_response: str | None = None
        self._pending_recoverable_tool_failures = []

        # Start spinner while waiting for LLM
        self.tui.start_spinner(
            progress_label(
                plan_mode=bool(self.agent and self.agent.session and self.agent.session.plan_mode_enabled)
            )
        )
        try:
            async for event in self.agent.run(message, user_model_content=user_model_content):
                if event.type == AgentEventType.TEXT_DELTA:
                    content = event.data.get("content", "")
                    if not assistant_streaming:
                        self.tui.stop_spinner()
                        self.tui.begin_assistant()
                        assistant_streaming = True
                    self.tui.stream_assistant_delta(content)

                elif event.type == AgentEventType.TEXT_COMPLETE:
                    content = event.data.get("content")
                    is_final_text = bool(event.data.get("final", True))
                    if is_final_text:
                        final_response = content
                    self.tui.stop_spinner()
                    if content:
                        self._mark_pending_tool_failures_recovered()
                    if assistant_streaming:
                        self.tui.end_assistant(content)
                        assistant_streaming = False
                    elif content:
                        # Plan mode may suppress text deltas before final output.
                        # Render complete assistant output in one shot.
                        self.tui.begin_assistant()
                        self.tui.stream_assistant_delta(content)
                        self.tui.end_assistant()

                elif event.type == AgentEventType.AGENT_ERROR:
                    self.tui.stop_spinner()
                    self._flush_pending_tool_failures()
                    error = event.data.get("error", "Unknown error")
                    if "Maximum turns" in str(error):
                        console.print("\n[warning]Turn limit reached before completion.[/warning]")
                        handled = await self._run_tui_recovery_flow(
                            reason="Maximum turns reached.",
                        )
                        if handled:
                            await self._auto_save()
                    else:
                        console.print(f"\n[error]Error: {error}[/error]")

                elif event.type == AgentEventType.TOOL_CALL_START:
                    self.tui.stop_spinner()
                    tool_name = event.data.get("name", "Unknown tool")
                    plan_only_phase = bool(
                        self.agent
                        and self.agent.session
                        and self.agent.session.plan_mode_enabled
                        and self.agent.session.plan_phase != "executing"
                    )
                    if tool_name == "todos":
                        scope = self._resolve_todo_scope(arguments=event.data.get("arguments", {}))
                        if self._should_hide_planning_todos(scope):
                            self.tui.start_spinner(
                                progress_label(
                                    tool_name=tool_name,
                                    arguments=event.data.get("arguments", {}),
                                    plan_mode=plan_only_phase,
                                )
                            )
                            continue
                    if tool_name in {"memory", "plan_question"} or (
                        plan_only_phase and tool_name not in {"todos", "web_search", "web_fetch"}
                    ):
                        self.tui.start_spinner(
                            progress_label(
                                tool_name=tool_name,
                                arguments=event.data.get("arguments", {}),
                                plan_mode=plan_only_phase,
                            )
                        )
                        continue
                    tool_kind = self._get_tool_kind(tool_name)
                    self.tui.tool_call_start(
                        event.data.get("call_id", ""),
                        tool_name,
                        tool_kind,
                        event.data.get("arguments", {}),
                    )
                    self.tui.start_spinner(
                        progress_label(
                            tool_name=tool_name,
                            arguments=event.data.get("arguments", {}),
                            plan_mode=plan_only_phase,
                        )
                    )

                elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                    self.tui.stop_spinner()
                    tool_name = event.data.get("name", "Unknown tool")
                    plan_only_phase = bool(
                        self.agent
                        and self.agent.session
                        and self.agent.session.plan_mode_enabled
                        and self.agent.session.plan_phase != "executing"
                    )
                    if tool_name == "todos":
                        scope = self._resolve_todo_scope(metadata=event.data.get("metadata"))
                        if self._should_hide_planning_todos(scope):
                            self.tui.start_spinner(
                                progress_label(
                                    tool_name=tool_name,
                                    metadata=event.data.get("metadata"),
                                    phase="post_tool",
                                    plan_mode=plan_only_phase,
                                )
                            )
                            continue
                    if tool_name in {"memory", "plan_question"}:
                        self.tui.start_spinner(
                            progress_label(
                                tool_name=tool_name,
                                metadata=event.data.get("metadata"),
                                phase="post_tool",
                                plan_mode=plan_only_phase,
                            )
                        )
                        continue
                    if (
                        plan_only_phase
                        and tool_name not in {"web_search", "web_fetch"}
                        and not event.data.get("success", False)
                        and str(event.data.get("error") or "").startswith("Invalid parameters:")
                    ):
                        # In planning phase, model may probe tool schemas with partial calls.
                        # Keep this out of user transcript to reduce noise.
                        self.tui.start_spinner(
                            progress_label(
                                tool_name=tool_name,
                                metadata=event.data.get("metadata"),
                                phase="post_tool",
                                plan_mode=plan_only_phase,
                            )
                        )
                        continue
                    if (
                        plan_only_phase
                        and tool_name not in {"todos", "web_search", "web_fetch"}
                        and event.data.get("success", False)
                    ):
                        self._mark_pending_tool_failures_recovered()
                        self.tui.start_spinner(
                            progress_label(
                                tool_name=tool_name,
                                metadata=event.data.get("metadata"),
                                phase="post_tool",
                                plan_mode=plan_only_phase,
                            )
                        )
                        continue
                    if self._is_recoverable_sandbox_read_failure(
                        tool_name=tool_name,
                        success=event.data.get("success", False),
                        error=event.data.get("error"),
                    ):
                        self._pending_recoverable_tool_failures.append(dict(event.data))
                        self.tui.start_spinner(
                            progress_label(
                                tool_name=tool_name,
                                metadata=event.data.get("metadata"),
                                phase="post_tool",
                                plan_mode=plan_only_phase,
                            )
                        )
                        continue
                    if event.data.get("success", False):
                        self._mark_pending_tool_failures_recovered()
                    else:
                        self._flush_pending_tool_failures()
                    tool_kind = self._get_tool_kind(tool_name)
                    self.tui.tool_call_complete(
                        call_id=event.data.get("call_id", ""),
                        name=tool_name,
                        tool_kind=tool_kind,
                        success=event.data.get("success", False),
                        output=event.data.get("output", ""),
                        error=event.data.get("error"),
                        metadata=event.data.get("metadata"),
                        diff=event.data.get("diff"),
                        truncated=event.data.get("truncated", False),
                        exit_code=event.data.get("exit_code"),
                    )
                    # Restart spinner while LLM processes tool results
                    self.tui.start_spinner(
                        progress_label(
                            tool_name=tool_name,
                            metadata=event.data.get("metadata"),
                            phase="post_tool",
                            plan_mode=plan_only_phase,
                        )
                    )

                elif event.type == AgentEventType.LOOP_DETECTED:
                    self.tui.stop_spinner()
                    self.tui.start_spinner("Recovering...")

                elif event.type == AgentEventType.CONTEXT_COMPACTING:
                    self.tui.stop_spinner()
                    self.tui.start_spinner("Automatically compacting context...")

                elif event.type == AgentEventType.CONTEXT_COMPACTED:
                    self.tui.stop_spinner()
                    console.print("[dim]Context compacted.[/dim]")
                    self.tui.start_spinner(progress_label(plan_mode=plan_only_phase))

                elif event.type == AgentEventType.PLAN_READY:
                    self.tui.stop_spinner()
                    plan_text = event.data.get("plan_text", "")
                    if not isinstance(plan_text, str) or not plan_text.strip():
                        if self.agent and self.agent.session:
                            self.agent.session.set_plan_phase("writing_plan")
                        await self._process_message(
                            "Write the complete final implementation plan now before asking for implementation approval."
                        )
                        continue
                    asked = (
                        self.agent.session.plan_questions_asked
                        if self.agent and self.agent.session
                        else 0
                    )
                    approved = self.tui.prompt_plan_implementation(asked_questions=asked)
                    if approved and self.agent and self.agent.session:
                        self.agent.session.seed_execution_todos_from_plan(
                            self.agent.session.pending_plan_text
                        )
                        self.agent.session.promote_pending_plan_to_active()
                        self.agent.session.set_plan_phase("executing")
                        console.print("[dim]Plan approved · starting implementation[/dim]")
                        await self._process_message(
                            Agent.PLAN_EXECUTE_PROMPT
                        )
                    elif self.agent and self.agent.session:
                        self.agent.session.set_plan_phase(
                            "awaiting_implementation_confirmation"
                        )
                        console.print(
                            "[dim]Plan mode remains enabled. Next: send follow-up guidance to refine this plan, "
                            "type 'implement plan' later, or type /plan off to leave Plan mode manually.[/dim]"
                        )

            if self.agent and self.agent.session:
                self.tui.render_change_summary(
                    self.agent.session.change_history.last_turn_change_set,
                    self.config.cwd,
                )

            return final_response
        finally:
            self._flush_pending_tool_failures()
            self.tui.stop_spinner()
            if attachment_turn_id:
                AttachmentManager(self.config.cwd).cleanup_turn(attachment_turn_id)


def _load_runtime_config(
    *,
    workspace_dir: Path,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
) -> Config:
    ensure_workspace_layout(workspace_dir)
    try:
        config = load_config(cwd=workspace_dir)
    except Exception as e:
        console.print(f"[error]Configuration error: {e}[/error]")
        sys.exit(1)

    if api_key:
        config.api_key = api_key
    if base_url:
        config.base_url = base_url
    if model:
        config.model.name = model
    return config


def _run_main_app(
    *,
    workspace_dir: Path,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    desktop: bool,
    legacy: bool,
) -> None:
    config = _load_runtime_config(
        workspace_dir=workspace_dir,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    if desktop or legacy:
        try:
            ensure_cloud_auth(console, config)
        except CloudAuthError as exc:
            console.print(f"[error]Cloud auth error: {exc}[/error]")
            sys.exit(1)

    # Setup routing:
    # - Legacy TUI: keep terminal wizard behavior.
    # - GUI: launch GUI setup view instead of forcing terminal wizard first.
    # - Reup (default): owns its own signed-out/setup states.
    if legacy and config.needs_setup:
        from ite.config.setup import run_setup_wizard

        config = run_setup_wizard(console, config)

    errors = config.validate()
    if errors:
        setup_missing_errors = {"missing_api_key", "missing_base_url", "missing_model"}
        real_errors = [e for e in errors if e not in setup_missing_errors]
        if real_errors:
            for error in real_errors:
                console.print(f"[error]{error}[/error]")
            sys.exit(1)

    if desktop:
        from ite.ui.gui import run_gui
        run_gui(config)
    elif legacy:
        cli = CLI(config)
        asyncio.run(cli.run_interactive())
    else:
        from ite.ui.reup import run_reup

        run_reup(config)


@click.group(cls=IteGroup, invoke_without_command=True)
@click.version_option(version="0.0.26", prog_name="ite")
@click.option(
    "--cwd",
    "-w",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Current working directory",
)
@click.option("--model", "-m", help="Model name to use")
@click.option("--api-key", "-k", help="API key for the LLM provider")
@click.option("--base-url", "-u", help="Base URL for the OpenAI-compatible API")
@click.option(
    "--desktop",
    "-d",
    is_flag=True,
    help="Launch the desktop app",
)
@click.option(
    "--legacy",
    "-l",
    is_flag=True,
    help="Launch the legacy terminal UI",
)
@click.pass_context
def main(
    ctx: click.Context,
    cwd: Path | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    desktop: bool = False,
    legacy: bool = False,
):
    workspace_dir = cwd or Path.cwd()
    ctx.ensure_object(dict)
    ctx.obj["workspace_dir"] = workspace_dir
    ctx.obj["model"] = model
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url
    if ctx.invoked_subcommand is None:
        _run_main_app(
            workspace_dir=workspace_dir,
            model=model,
            api_key=api_key,
            base_url=base_url,
            desktop=desktop,
            legacy=legacy,
        )


@main.group("mcp")
def mcp_group() -> None:
    """Manage persisted MCP server definitions."""


@mcp_group.command("add", context_settings={"ignore_unknown_options": True})
@click.argument("server")
@click.argument("target", required=False)
@click.argument("target_args", nargs=-1, type=str)
@click.option("--url", "url_value", help="Remote MCP server URL.")
@click.option("--command", "command_value", help="stdio command to launch the MCP server.")
@click.option("--transport", help="Explicit MCP transport override.")
@click.option("--arg", "command_args", multiple=True, help="Repeatable stdio argument.")
@click.option(
    "--scope",
    type=click.Choice(["global", "workspace", "user", "local", "project"]),
    default="global",
    show_default=True,
)
@click.pass_context
def mcp_add(
    ctx: click.Context,
    server: str,
    target: str | None,
    target_args: tuple[str, ...],
    url_value: str | None,
    command_value: str | None,
    transport: str | None,
    command_args: tuple[str, ...],
    scope: str,
) -> None:
    workspace_dir = Path(ctx.obj.get("workspace_dir") or Path.cwd())
    ensure_workspace_layout(workspace_dir)
    normalized_scope = _normalize_mcp_scope(scope)

    payload: dict[str, Any] = {}
    inferred_args = list(command_args or ())

    if url_value and command_value:
        raise click.ClickException("Use either --url or --command, not both.")

    if url_value:
        payload["url"] = url_value
    elif command_value:
        payload["command"] = command_value
    elif target:
        if target.startswith(("http://", "https://")):
            payload["url"] = target
        else:
            payload["command"] = target
            inferred_args.extend(target_args)
    else:
        raise click.ClickException("Provide a URL or command. Example: `ite mcp add figma https://mcp.figma.com/mcp`")

    if "url" in payload and target_args:
        raise click.ClickException("Unexpected extra arguments after URL target.")
    if "command" in payload and inferred_args:
        payload["args"] = inferred_args
    if transport:
        payload["transport"] = _normalize_mcp_transport(transport)

    try:
        path = save_mcp_server_config(
            cwd=workspace_dir,
            scope=normalized_scope,
            server=server,
            config=payload,
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to save MCP server '{server}': {exc}") from exc
    console.print(
        f"[success]Saved MCP server[/success] [cyan]{server}[/cyan] "
        f"[dim]to {normalized_scope} config ({path})[/dim]"
    )


def _normalize_mcp_transport(value: str) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "http": "streamable_http",
        "https": "streamable_http",
        "streamable-http": "streamable_http",
        "streamable_http": "streamable_http",
        "stdio": "stdio",
        "sse": "sse",
        "ws": "ws",
        "websocket": "ws",
    }
    return aliases.get(normalized, normalized)


def _normalize_mcp_scope(value: str) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "user": "global",
        "global": "global",
        "workspace": "workspace",
        "local": "workspace",
        "project": "workspace",
    }
    return aliases.get(normalized, normalized)


if __name__ == "__main__":
    main()
