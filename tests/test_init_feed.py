from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from ite.commands import CommandContext
from ite.commands import init as init_command
from ite.config.config import Config
from ite.ui.reup._streaming import StreamingMixin
from ite.ui.reup.adapters.tui_adapter import ReupTUIAdapter


class InitFeedApp(StreamingMixin, App):
    # Exercise the real command card structure, renderers and targeted TCSS.
    CSS = """
    #conversation { width: 1fr; height: 1fr; }
    .block.workboard { height: auto; padding: 1 2; margin: 0 2 1 0; }
    .command-title-row { height: 1; }
    .command-kicker { width: 8; }
    .command-name { width: 1fr; }
    .command-card-scroll { height: auto; max-height: 20; min-height: 2; }
    .command-body { height: auto; width: 1fr; }
    .block.workboard.init-card .command-card-scroll {
        overflow-x: hidden;
        scrollbar-size-horizontal: 0;
    }
    """

    def __init__(self):
        super().__init__()
        self._streaming_cards_lock = asyncio.Lock()
        self._streaming_command_cards = {}
        self._message_count = 0
        self._top_spinner_frames = ["◌", "○"]
        self._top_spinner_index = 0

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="conversation")

    def _style(self, name):
        return {
            "fg": "white",
            "secondary": "grey70",
            "muted": "grey50",
            "primary": "cyan",
        }.get(name, "white")

    def _render_styles(self):
        return {}

    async def _pin_activity_indicator_to_end(self):
        pass

    def _refresh_empty_state(self):
        pass


@pytest.mark.parametrize("width", [38, 80])
@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_init_card_finishes_without_duplicate_or_orphan_spinner(width, status):
    async def work():
        app = InitFeedApp()
        adapter = ReupTUIAdapter(app)
        async with app.run_test(size=(width, 24)) as pilot:
            await adapter.begin_command_progress("/init", "Inspecting project guidance")
            await adapter.update_command_progress(
                "/init", "Reading a/very/long/repository/path/README.md"
            )
            await pilot.pause()
            assert len(app.query(".block.workboard.init-card")) == 1
            assert not app.query(".command-kicker")
            card, body, _, _, _, _ = app._streaming_command_cards["/init"]
            message = (
                f"Initialization {status}\n"
                + "a/very/long/repository/" * 6
                + "AGENTS.md"
            )
            await adapter.finish_command_progress("/init", message, status=status)
            await pilot.pause()
            assert not app._streaming_command_cards
            assert len(app.query(".block.workboard.init-card")) == 1
            assert card.has_class("command-error") == (status == "failed")
            scroll = card.query_one(VerticalScroll)
            assert not scroll.show_horizontal_scrollbar
            assert body.size.height > 2  # Long path wraps onto multiple visible rows.
            rendered = Console(width=width - 6).render_lines(body.content)
            actual = "\n".join(
                "".join(segment.text for segment in line) for line in rendered
            )
            assert "◌" not in actual
            assert "AGENTS.md" in actual

    asyncio.run(work())


def test_init_failure_status_survives_generic_command_dispatch(tmp_path: Path):
    # Dispatch integration is covered by the app's command tests; this verifies
    # the context carries the native card result for the remote feed as well.
    async def work():
        app = InitFeedApp()
        async with app.run_test(size=(42, 24)):
            ctx = CommandContext(
                Config(cwd=tmp_path),
                SimpleNamespace(session=SimpleNamespace()),
                ReupTUIAdapter(app),
                Console(),
            )
            with (
                patch.object(
                    init_command,
                    "_run_init_investigator",
                    AsyncMock(side_effect=RuntimeError("provider unavailable")),
                ),
                patch.object(init_command, "_get_agents_md_files", return_value=[]),
            ):
                await init_command.cmd_init(ctx, [])
            assert ctx.outcome == "failed"
            assert "provider unavailable" in ctx.result
            assert len(app.query(".command-error")) == 1
            assert not app._streaming_command_cards

    asyncio.run(work())


def test_generic_dispatch_does_not_duplicate_native_init_result(tmp_path: Path):
    from ite.commands import Command, CommandRegistry
    from ite.ui.reup.app import ReupApp

    async def work():
        app = ReupApp(Config(cwd=tmp_path, api_key="test"))
        app.agent = SimpleNamespace(session=SimpleNamespace())
        registry = CommandRegistry()

        async def handler(ctx, args):
            ctx.outcome = "failed"
            ctx.result = "Initialization failed: provider unavailable"

        registry.register(Command("/init", "Initialize", handler))
        app._command_registry = registry
        with (
            patch.object(app, "ensure_agent", AsyncMock()),
            patch.object(app, "_ensure_command_registry", AsyncMock()),
            patch.object(app, "_start_remote_command_feed_entry", return_value="feed"),
            patch.object(app, "_finish_remote_command_feed_entry") as finish,
            patch.object(app, "finalize_streaming_command_result") as finalize,
            patch.object(app, "post_command_result") as duplicate,
        ):
            await app._run_command_inline("/init")
        finish.assert_called_once()
        assert finish.call_args.kwargs["status"] == "failed"
        assert (
            finish.call_args.kwargs["output"]
            == "Initialization failed: provider unavailable"
        )
        duplicate.assert_not_called()
        finalize.assert_called_once_with("/init")

    asyncio.run(work())


@pytest.mark.parametrize("theme", ["flexoki", "textual-light"])
def test_full_app_init_card_fits_narrow_terminal(tmp_path: Path, theme):
    from ite.ui.reup.app import ReupApp

    async def work():
        app = ReupApp(Config(cwd=tmp_path, api_key="test"))
        with (
            patch.object(app, "_bootstrap_after_mount", AsyncMock()),
            patch.object(
                app,
                "_refresh_session_tabs",
                Mock(side_effect=lambda: asyncio.create_task(asyncio.sleep(0))),
            ),
        ):
            async with app.run_test(size=(42, 32)) as pilot:
                app.theme = theme
                await app.add_assistant_card(
                    "Workboard", "Reference card", css_class="workboard"
                )
                reference = app.query_one(".workboard")
                adapter = ReupTUIAdapter(app)
                await adapter.begin_command_progress("/init", "Reading README.md")
                message = "Created AGENTS.md\n18 files checked · 7.2 KiB\nActive in this chat\n/workspaces/example-project/AGENTS.md"
                await adapter.finish_command_progress(
                    "/init", message, status="completed"
                )
                await pilot.pause()
                card = next(iter(app.query(".init-card")))
                assert card.styles.background == reference.styles.background
                assert card.styles.border == reference.styles.border
                assert card.styles.padding == reference.styles.padding
                assert not card.query(".command-kicker")
                body = card.query_one(".command-body")
                assert body.region.right <= app.screen.size.width
                assert body.size.height > 3  # Actual styles wrap every long result row.
                assert not card.query_one(VerticalScroll).show_horizontal_scrollbar
                assert len(app.query(".init-card")) == 1

    asyncio.run(work())


@pytest.mark.parametrize("interrupt", ["keyboard", "signal"])
def test_ctrl_c_cancels_init_worker_and_investigator(tmp_path: Path, interrupt):
    import signal

    from ite.commands import Command, CommandRegistry
    from ite.ui.reup.app import ReupApp

    async def work():
        app = ReupApp(Config(cwd=tmp_path, api_key="test"))
        started = asyncio.Event()
        run = SimpleNamespace(run_id="init-run")

        async def wait(**kwargs):
            started.set()
            await asyncio.Event().wait()

        runtime = SimpleNamespace(
            spawn=AsyncMock(return_value=(run, False)), wait=wait, cancel=AsyncMock()
        )
        session = SimpleNamespace(
            subagent_runtime=runtime,
            context_manager=SimpleNamespace(add_system_message=Mock()),
        )
        ctx = CommandContext(
            app.config, SimpleNamespace(session=session), ReupTUIAdapter(app), Console()
        )
        registry = CommandRegistry()
        registry.register(Command("/init", "Initialize", init_command.cmd_init))
        app._command_registry = registry
        with (
            patch.object(app, "_bootstrap_after_mount", AsyncMock()),
            patch.object(
                app,
                "_refresh_session_tabs",
                Mock(side_effect=lambda: asyncio.create_task(asyncio.sleep(0))),
            ),
            patch.object(app, "ensure_agent", AsyncMock()),
            patch.object(app, "_ensure_command_registry", AsyncMock()),
            patch.object(init_command, "_get_agents_md_files", return_value=[]),
            patch("ite.ui.reup._turn.build_command_context", return_value=ctx),
            patch.object(app, "post_notice") as notice,
        ):
            async with app.run_test(size=(80, 36)) as pilot:
                # App timers see no active agent session; the command context has
                # its own real cancellation lifecycle above.
                app.agent = SimpleNamespace(session=None)
                await app.run_command("/init")
                await asyncio.wait_for(started.wait(), 2)
                worker = app._init_command_worker
                assert worker is not None
                assert not app._is_turn_running
                if interrupt == "keyboard":
                    await pilot.press("ctrl+c")
                else:
                    signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
                for _ in range(20):
                    await pilot.pause(0.05)
                    if app._init_command_worker is None:
                        break
                runtime.cancel.assert_awaited_once_with(run_ids=["init-run"])
                assert app._init_command_worker is None
                assert ctx.outcome == "cancelled"
                assert not app._streaming_command_cards
                assert not (tmp_path / "AGENTS.md").exists()
                assert len(app.query(".init-card")) == 1
                assert app._remote_command_feed[-1]["status"] == "cancelled"
                assert all(call.args[0] != "Exit" for call in notice.call_args_list)

    asyncio.run(work())


def test_ctrl_c_can_cancel_before_agent_startup_finishes(tmp_path: Path):
    from ite.ui.reup.app import ReupApp

    async def work():
        app = ReupApp(Config(cwd=tmp_path, api_key="test"))
        started = asyncio.Event()

        async def initialize():
            started.set()
            await asyncio.Event().wait()

        with (
            patch.object(app, "_bootstrap_after_mount", AsyncMock()),
            patch.object(
                app,
                "_refresh_session_tabs",
                Mock(side_effect=lambda: asyncio.create_task(asyncio.sleep(0))),
            ),
            patch.object(app, "ensure_agent", initialize),
        ):
            async with app.run_test(size=(80, 36)) as pilot:
                await app.run_command("/init")
                await asyncio.wait_for(started.wait(), 2)
                await pilot.press("ctrl+c")
                for _ in range(20):
                    await pilot.pause(0.05)
                    if app._init_command_worker is None:
                        break
                assert app._init_command_worker is None
                assert app._remote_command_feed[-1]["status"] == "cancelled"
                assert not (tmp_path / "AGENTS.md").exists()

    asyncio.run(work())
