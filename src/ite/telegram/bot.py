"""Telegram bot service that runs as an asyncio task inside the iTE TUI.

Directly calls the Agent API — no TLS, no remote protocol. The TUI owns the
Agent and delegates confirmations/plan questions to this service when active.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from ite.telegram._approval import (
    approval_keyboard,
    plan_question_keyboard,
    plan_ready_keyboard,
)
from ite.telegram._render import (
    escape_md,
    format_agent_event,
    format_turn_boundary,
    truncate,
)

logger = logging.getLogger("ite.telegram")

# Hardcoded default bot token. Override with ITE_TELEGRAM_BOT_TOKEN env var.
# Replace with your bot's token from @BotFather.
_DEFAULT_TELEGRAM_BOT_TOKEN = "8693627145:AAESj90ijegdDbroh72tf4xfG6Ev8KyXD9c"


class TelegramBotService:
    """Background service that bridges iTE Agent ↔ Telegram chat.

    The TUI creates one instance and calls:
      - start(bot_token) → /telegram on
      - handle_agent_event(...) → streams events to Telegram
      - request_confirmation(...) → shows inline keyboard, returns Future[bool]
      - request_plan_question(...) → shows inline keyboard, returns Future[dict]
      - request_plan_ready(...) → shows inline keyboard, returns Future[bool]
      - submit_prompt(text) → receives text from Telegram, forwarded to TUI's _submit_prompt
    """

    def __init__(
        self,
        *,
        on_submit_prompt: Any = None,
        on_cancel_turn: Any = None,
    ) -> None:
        self._bot_token: str = ""
        self._chat_id: int | None = None
        self._app: Any = None
        self._app_task: asyncio.Task[Any] | None = None
        self._running = False
        self._last_turn_id: int | None = None
        self._streaming_message_id: int | None = None
        self._streaming_text: str = ""
        self._last_edit_time: float = 0.0

        # Serialize agent events to prevent concurrent streaming
        self._agent_event_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._agent_event_consumer: asyncio.Task[Any] | None = None

        # Called when user sends a message from Telegram
        self._on_submit_prompt = on_submit_prompt
        self._on_cancel_turn = on_cancel_turn

        # Pending approval / plan question futures
        self._approval_futures: dict[str, asyncio.Future[bool]] = {}
        self._plan_question_futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._plan_ready_futures: dict[str, asyncio.Future[bool]] = {}
        self._pq_free_pending: str | None = None

    @property
    def running(self) -> bool:
        return self._running

    async def start(self, *, bot_token: str) -> None:
        if self._running:
            return
        self._bot_token = bot_token
        self._running = True
        self._app_task = asyncio.create_task(self._run_polling())
        self._agent_event_consumer = asyncio.create_task(self._consume_agent_events())

    async def stop(self) -> None:
        self._running = False
        # Let _consume_agent_events exit naturally via the while loop
        if self._agent_event_consumer and not self._agent_event_consumer.done():
            try:
                await asyncio.wait_for(self._agent_event_consumer, timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._agent_event_consumer = None
        # Let _run_polling exit naturally (while loop checks _running)
        if self._app_task and not self._app_task.done():
            try:
                await asyncio.wait_for(self._app_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._app_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._app_task
            self._app_task = None
        self._resolve_all_pending(None)

    # ── Agent event → Telegram ──────────────────────────────────────

    def handle_agent_event(self, event: Any, session_id: str, turn_id: int) -> None:
        """Receive an agent event from the TUI and queue it for Telegram rendering."""
        if not self._running:
            return
        self._agent_event_queue.put_nowait((event, session_id, turn_id))

    async def _consume_agent_events(self) -> None:
        """Sequential consumer — processes one event at a time to prevent races."""
        while self._running:
            try:
                item = await asyncio.wait_for(self._agent_event_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            event, session_id, turn_id = item
            await self._render_agent_event(event, session_id, turn_id)

    async def _render_agent_event(
        self, event: Any, session_id: str, turn_id: int
    ) -> None:
        from ite.agent.events import AgentEvent, AgentEventType

        event_type = (
            event.type
            if isinstance(event, AgentEvent)
            else getattr(event, "type", None)
        )
        data = (
            event.data
            if isinstance(event, AgentEvent)
            else getattr(event, "data", None) or {}
        )

        if format_turn_boundary(self._last_turn_id, turn_id):
            await self._send_telegram("▬▬▬▬▬▬▬▬▬▬")
            self._streaming_message_id = None
            self._streaming_text = ""
        self._last_turn_id = turn_id

        if event_type == AgentEventType.TEXT_DELTA:
            content = str(data.get("content", ""))
            self._streaming_text += content
            if self._streaming_message_id is not None:
                await self._edit_streaming_message()
            else:
                self._streaming_message_id = await self._send_telegram_streaming()
            return

        if event_type == AgentEventType.TEXT_COMPLETE:
            if self._streaming_message_id is not None and self._streaming_text.strip():
                await self._finalize_streaming_message()
            elif self._streaming_text.strip():
                await self._send_telegram(escape_md(self._streaming_text))
            self._streaming_message_id = None
            self._streaming_text = ""
            return

        # Delegate to the shared formatter (treat AgentEvent like a frame)
        frame = {
            "event": {
                "type": event_type.value
                if hasattr(event_type, "value")
                else str(event_type),
                "data": data,
            },
        }
        formatted = format_agent_event(frame)
        if formatted:
            await self._send_telegram(formatted)

    # ── Confirmations & plan questions ──────────────────────────────

    async def request_confirmation(self, confirmation: Any) -> bool:
        """Show an approval request in Telegram and wait for a response."""
        if not self._running or self._chat_id is None:
            raise RuntimeError("Telegram bot not connected")

        request_id = str(id(confirmation))
        future: asyncio.Future[bool] = asyncio.Future()
        self._approval_futures[request_id] = future

        tool = getattr(confirmation, "tool_name", "tool")
        desc = getattr(confirmation, "description", "")
        cmd = getattr(confirmation, "command", None)
        diff = getattr(getattr(confirmation, "diff", None), "to_diff", lambda: "")()

        parts = [f"🔐 *Approval needed:* {escape_md(str(tool))}"]
        if desc:
            parts.append(escape_md(truncate(str(desc), 2000)))
        if cmd:
            parts.append(f"```\n{truncate(str(cmd), 1500)}\n```")
        if diff:
            parts.append(f"```diff\n{truncate(str(diff), 2500)}\n```")

        await self._send_telegram(
            "\n".join(parts), reply_markup=approval_keyboard(request_id)
        )

        try:
            return await asyncio.wait_for(future, timeout=120.0)
        except asyncio.TimeoutError:
            self._approval_futures.pop(request_id, None)
            raise
        finally:
            self._approval_futures.pop(request_id, None)

    async def request_plan_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Show a plan question in Telegram and wait for a response."""
        if not self._running or self._chat_id is None:
            raise RuntimeError("Telegram bot not connected")

        request_id = str(payload.get("question_number", id(payload)))
        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self._plan_question_futures[request_id] = future

        question = str(payload.get("question", ""))
        options = [str(o) for o in payload.get("options", []) if str(o).strip()]
        recommended_index = payload.get("recommended_index")
        allow_free_text = bool(payload.get("allow_free_text", True))

        parts = [f"📋 *Plan question:*\n{escape_md(truncate(question, 2000))}"]
        await self._send_telegram(
            "\n".join(parts),
            reply_markup=plan_question_keyboard(
                request_id, options, recommended_index, allow_free_text
            ),
        )

        try:
            return await asyncio.wait_for(future, timeout=120.0)
        except asyncio.TimeoutError:
            self._plan_question_futures.pop(request_id, None)
            raise
        finally:
            self._plan_question_futures.pop(request_id, None)

    async def request_plan_ready(
        self, *, request_id: str, plan_text: str, question_count: int
    ) -> bool:
        """Show plan ready prompt in Telegram and wait for response."""
        if not self._running or self._chat_id is None:
            raise RuntimeError("Telegram bot not connected")

        future: asyncio.Future[bool] = asyncio.Future()
        self._plan_ready_futures[request_id] = future

        parts = []
        if plan_text:
            parts.append(f"📝 *Plan ready*\n{escape_md(truncate(plan_text, 3000))}")
        else:
            parts.append(f"📝 *Plan ready* ({question_count} questions answered)")
        parts.append("_Proceed with implementation?_")
        await self._send_telegram(
            "\n".join(parts), reply_markup=plan_ready_keyboard(request_id)
        )

        try:
            return await asyncio.wait_for(future, timeout=120.0)
        except asyncio.TimeoutError:
            self._plan_ready_futures.pop(request_id, None)
            raise
        finally:
            self._plan_ready_futures.pop(request_id, None)

    # ── Telegram polling ────────────────────────────────────────────

    async def _run_polling(self) -> None:
        from telegram import Update
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            MessageHandler,
            filters,
        )

        self._app = Application.builder().token(self._bot_token).build()
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("status", self._handle_status))
        self._app.add_handler(CommandHandler("cancel", self._handle_cancel))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        logger.info("Telegram bot polling started")
        try:
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            while self._running:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Telegram bot polling crashed")
        finally:
            self._running = False
            with contextlib.suppress(Exception):
                await self._app.updater.stop()
            with contextlib.suppress(Exception):
                await self._app.stop()
            with contextlib.suppress(Exception):
                await self._app.shutdown()

    # ── Telegram handlers ───────────────────────────────────────────

    async def _handle_start(self, update: Any, context: Any) -> None:
        self._chat_id = update.effective_chat.id if update.effective_chat else None
        await update.message.reply_text(
            "🤖 *iTE Telegram Bot* connected\\.\n\n"
            "Send me a message and I'll forward it to your running iTE session\\.\n\n"
            "_Commands:_\n"
            "/status — current session info\n"
            "/cancel — stop the running turn",
            parse_mode="MarkdownV2",
        )

    async def _handle_status(self, update: Any, context: Any) -> None:
        await update.message.reply_text(
            "📡 Connected to iTE runtime\n_Send a message to start a turn\\._",
            parse_mode="MarkdownV2",
        )

    async def _handle_cancel(self, update: Any, context: Any) -> None:
        if self._on_cancel_turn:
            await self._on_cancel_turn()
            await update.message.reply_text("⏹ Turn cancelled\\.")
        else:
            await update.message.reply_text("⚠️ No active session\\.")

    async def _handle_message(self, update: Any, context: Any) -> None:
        if not update.message or not update.message.text:
            return
        self._chat_id = update.effective_chat.id if update.effective_chat else None
        text = update.message.text.strip()
        if not text:
            return

        # Handle free-text plan question response
        if self._pq_free_pending:
            request_id = self._pq_free_pending
            self._pq_free_pending = None
            future = self._plan_question_futures.get(request_id)
            if future and not future.done():
                future.set_result(
                    {
                        "selected_option": "",
                        "free_text": text,
                        "selected_index": None,
                    }
                )
            return

        if self._on_submit_prompt:
            await self._on_submit_prompt(text)
        else:
            await update.message.reply_text("⚠️ No active iTE session\\.")

    async def _handle_callback(self, update: Any, context: Any) -> None:
        if not update.callback_query:
            return
        query = update.callback_query
        data = str(query.data or "")
        await query.answer()

        # Approval responses
        if data.startswith("approve:"):
            request_id = data.removeprefix("approve:")
            future = self._approval_futures.get(request_id)
            if future and not future.done():
                future.set_result(True)
            await query.edit_message_text("✅ Approved")
            return

        if data.startswith("deny:"):
            request_id = data.removeprefix("deny:")
            future = self._approval_futures.get(request_id)
            if future and not future.done():
                future.set_result(False)
            await query.edit_message_text("❌ Denied")
            return

        # Plan question responses
        if data.startswith("pq:"):
            parts = data.split(":", 2)
            if len(parts) >= 3:
                request_id = parts[2]
                try:
                    selected_index = int(parts[1])
                except ValueError:
                    selected_index = 0
                future = self._plan_question_futures.get(request_id)
                if future and not future.done():
                    future.set_result(
                        {
                            "selected_option": str(selected_index),
                            "free_text": "",
                            "selected_index": selected_index,
                        }
                    )
                await query.edit_message_text(
                    f"✅ Option {selected_index + 1} selected"
                )
            return

        if data.startswith("pq_free:"):
            request_id = data.removeprefix("pq_free:")
            # Free-text answers are harder inline — reply with prompt
            future = self._plan_question_futures.get(request_id)
            await query.edit_message_text(
                "💬 Send your free-text answer as a regular message:"
            )
            # Store the request_id so the next text message is treated as the answer
            self._pq_free_pending = request_id
            return

        # Plan ready responses
        if data.startswith("pr_yes:"):
            request_id = data.removeprefix("pr_yes:")
            future = self._plan_ready_futures.get(request_id)
            if future and not future.done():
                future.set_result(True)
            await query.edit_message_text("🚀 Implementing plan…")
            return

        if data.startswith("pr_no:"):
            request_id = data.removeprefix("pr_no:")
            future = self._plan_ready_futures.get(request_id)
            if future and not future.done():
                future.set_result(False)
            await query.edit_message_text("📝 Continuing to plan…")
            return

    # ── Message sending helpers ─────────────────────────────────────

    async def _send_telegram(
        self,
        text: str,
        *,
        reply_markup: Any = None,
    ) -> int | None:
        if self._chat_id is None:
            return None
        try:
            from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

            bot = Bot(token=self._bot_token)
            kb = None
            if reply_markup and isinstance(reply_markup, dict):
                inline_keyboard = reply_markup.get("inline_keyboard", [])
                kb = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton(**btn) for btn in row]
                        for row in inline_keyboard
                    ]
                )
            msg = await bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="MarkdownV2",
                reply_markup=kb,
            )
            return msg.message_id
        except Exception as e:
            logger.warning("Failed to send Telegram message: %s", e)
            return None

    async def _send_telegram_streaming(self) -> int | None:
        if self._chat_id is None:
            return None
        try:
            from telegram import Bot

            bot = Bot(token=self._bot_token)
            text = escape_md(self._streaming_text) + "▌"
            msg = await bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="MarkdownV2",
            )
            return msg.message_id
        except Exception:
            try:
                from telegram import Bot

                bot = Bot(token=self._bot_token)
                msg = await bot.send_message(
                    chat_id=self._chat_id,
                    text=self._streaming_text + "▌",
                )
                return msg.message_id
            except Exception as e:
                logger.warning("Failed to send streaming message: %s", e)
                return None

    async def _edit_streaming_message(self) -> None:
        if self._streaming_message_id is None or self._chat_id is None:
            return
        # Throttle to ~4 edits/sec to stay under Telegram rate limits
        now = asyncio.get_event_loop().time()
        if now - self._last_edit_time < 0.2:
            return
        try:
            from telegram import Bot

            bot = Bot(token=self._bot_token)
            text = escape_md(self._streaming_text) + "▌"
            await bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._streaming_message_id,
                text=text,
                parse_mode="MarkdownV2",
            )
            self._last_edit_time = now
        except Exception:
            pass

    async def _finalize_streaming_message(self) -> None:
        if self._streaming_message_id is None or self._chat_id is None:
            return
        try:
            from telegram import Bot

            bot = Bot(token=self._bot_token)
            text = escape_md(self._streaming_text)
            await bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._streaming_message_id,
                text=text,
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            logger.warning("Failed to finalize streaming message: %s", e)
        self._streaming_message_id = None

    # ── Cleanup ─────────────────────────────────────────────────────

    def _resolve_all_pending(self, value: Any) -> None:
        for future in self._approval_futures.values():
            if not future.done():
                future.set_result(False)
        for future in self._plan_question_futures.values():
            if not future.done():
                future.set_result(
                    {"selected_option": "", "free_text": "", "selected_index": None}
                )
        for future in self._plan_ready_futures.values():
            if not future.done():
                future.set_result(False)
        self._approval_futures.clear()
        self._plan_question_futures.clear()
        self._plan_ready_futures.clear()
