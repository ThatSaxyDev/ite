from __future__ import annotations

import asyncio
import contextlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock, patch

from textual import on
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Static

from ite.ui.reup._panels import PanelsMixin
from ite.ui.reup._threads import ThreadsMixin
from ite.ui.reup.app import ReupApp
from ite.ui.reup.widgets.thread_switcher import (
    ThreadSwitcherRow,
    ThreadSwitcherSidePanel,
)


class ThreadPanelApp(ThreadsMixin, App[None]):
    on_threads_toggle_pressed = PanelsMixin.on_threads_toggle_pressed
    CSS_PATH: ClassVar[list[Path]] = [
        Path(__file__).parents[1] / "src/ite/ui/reup" / p for p in ReupApp.CSS_PATH
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(cwd=Path("/tmp/project"))
        self._thread_switcher_sync_lock = asyncio.Lock()
        self._thread_switcher_panel = None
        self._thread_switcher_mount = None
        self._thread_switcher_dismissed_count = 1
        self._open_session_order = ["current"]
        self._open_sessions = {
            "current": SimpleNamespace(name="Current thread", turn_count=1)
        }
        self._thread_nav_order = []
        self._thread_history_cache = {}
        self._thread_history_refreshed_at = {}
        self._thread_history_errors = {}
        self._thread_history_worker = None
        self._thread_history_workspace = None
        self._cloud_signed_out = False
        self._shutdown_started = False
        self._cloud_user_email = ""
        self._cloud_user_image = None
        self.selected = None

    def compose(self) -> ComposeResult:
        yield Button("≡", id="threads-toggle")
        yield Static("Conversation", id="feed")

    def _active_session_id(self) -> str:
        return "current"

    def _run_state(self, _sid: str) -> SimpleNamespace:
        return SimpleNamespace(is_turn_running=False)

    def _commands_panel_is_open(self) -> bool:
        return False

    def _maybe_focus_prompt(self) -> None:
        pass

    @on(ThreadSwitcherRow.Selected)
    def selected_row(self, event: ThreadSwitcherRow.Selected) -> None:
        event.stop()
        self.selected = event.session_id

    def on_mount(self) -> None:
        self._apply_thread_switcher_button_state()

    async def on_unmount(self) -> None:
        self._clear_thread_history_cache()


async def finish_history(app: ThreadPanelApp) -> None:
    await app._thread_history_worker.wait()


def test_open_and_reopen_do_not_wait_for_disk_and_preserve_rows() -> None:
    async def run() -> None:
        release = threading.Event()
        entered = threading.Event()
        thread_ids = []

        def load(**_kwargs):
            thread_ids.append(threading.get_ident())
            entered.set()
            release.wait(timeout=3)
            return [{"session_id": "saved", "name": "Saved thread", "turn_count": 1}]

        manager = SimpleNamespace(list_sessions=Mock(side_effect=load))
        with patch("ite.ui.reup._threads.SessionManager", return_value=manager):
            app = ThreadPanelApp()
            try:
                async with app.run_test(size=(100, 40)) as pilot:
                    await pilot.click("#threads-toggle")
                    await pilot.pause()
                    assert entered.is_set()
                    assert app._thread_switcher_panel_is_open()
                    assert not release.is_set()
                    assert not app._thread_history_worker.is_finished
                    panel = app._thread_switcher_panel
                    current = panel._row_widgets["current"]
                    await app._hide_thread_switcher_panel()
                    await pilot.pause()
                    assert panel.is_mounted
                    assert not panel.display
                    assert app.query_one("#feed").region.x == 0
                    await app._toggle_thread_switcher_panel()
                    assert app._thread_switcher_panel is panel
                    assert panel._row_widgets["current"] is current
                    assert manager.list_sessions.call_count == 1
                    release.set()
                    await finish_history(app)
                    await pilot.pause()
                    assert thread_ids[0] != threading.get_ident()
                    assert panel._row_widgets["current"] is current
                    assert "saved" in panel._row_widgets
                    await pilot.click("#thread-switcher-row-saved")
                    assert app.selected == "saved"
            finally:
                release.set()

    asyncio.run(run())


def test_workspace_changes_and_closed_refresh_do_not_reopen_panel() -> None:
    async def run() -> None:
        def load(*, workspace_path, **_kwargs):
            return [
                {
                    "session_id": Path(workspace_path).name,
                    "name": workspace_path,
                    "turn_count": 1,
                }
            ]

        manager = SimpleNamespace(list_sessions=Mock(side_effect=load))
        with patch("ite.ui.reup._threads.SessionManager", return_value=manager):
            app = ThreadPanelApp()
            async with app.run_test(size=(100, 40)) as pilot:
                await app._toggle_thread_switcher_panel()
                await finish_history(app)
                panel = app._thread_switcher_panel
                assert "project" in panel._row_widgets
                await app._sync_thread_switcher_panel()
                assert manager.list_sessions.call_count == 1
                await app._hide_thread_switcher_panel()
                app.config.cwd = Path("/tmp/other")
                await app._toggle_thread_switcher_panel()
                await finish_history(app)
                assert "project" not in panel._row_widgets
                assert "other" in panel._row_widgets
                await app._hide_thread_switcher_panel()
                app._queue_thread_history_refresh(force=True)
                await finish_history(app)
                assert not app._thread_switcher_panel_is_open()
                app._cloud_signed_out = True
                await app._sync_thread_switcher_panel()
                assert app._thread_switcher_panel is None
                await pilot.pause()

    asyncio.run(run())


def test_row_reconciliation_preserves_widgets_order_state_and_scroll() -> None:
    async def run() -> None:
        app = ThreadPanelApp()
        async with app.run_test(size=(100, 20)) as pilot:
            rows = [(f"t{i}", f"Thread {i}", "saved", "saved") for i in range(100)]
            panel = ThreadSwitcherSidePanel(threads=rows, id="thread-switcher-panel")
            await app.screen.mount(panel)
            await pilot.pause()
            preserved = panel._row_widgets["t20"]
            thread_list = panel.query_one("#thread-switcher-list", VerticalScroll)
            thread_list.scroll_to(y=20, animate=False)
            await pilot.pause()
            new_rows = [("new", "New thread", "current", "open"), *rows[1:]]
            new_rows[20] = ("t20", "Renamed thread", "running", "open")
            await panel.refresh_threads(new_rows)
            await pilot.pause()
            assert panel._row_widgets["t20"] is preserved
            assert preserved.has_class("live")
            assert not preserved.has_class("saved")
            assert "t0" not in panel._row_widgets
            assert [row.session_id for row in thread_list.children] == [
                row[0] for row in new_rows
            ]
            assert thread_list.scroll_y == 20

    asyncio.run(run())


def test_failed_history_refresh_can_be_retried() -> None:
    async def run() -> None:
        manager = SimpleNamespace(
            list_sessions=Mock(side_effect=[OSError("disk unavailable"), []])
        )
        with patch("ite.ui.reup._threads.SessionManager", return_value=manager):
            app = ThreadPanelApp()
            async with app.run_test(size=(100, 40)) as pilot:
                await app._toggle_thread_switcher_panel()
                await finish_history(app)
                panel = app._thread_switcher_panel
                assert panel.query_one("#thread-switcher-history-status").display
                assert app._thread_switcher_panel_is_open()
                await app._hide_thread_switcher_panel()
                await app._toggle_thread_switcher_panel()
                await finish_history(app)
                await pilot.pause()
                assert not panel.query_one("#thread-switcher-history-status").display
                assert manager.list_sessions.call_count == 2

    asyncio.run(run())


def test_deleted_thread_cannot_return_from_inflight_refresh() -> None:
    async def run() -> None:
        release = threading.Event()
        deleted = {"session_id": "deleted", "name": "Deleted thread", "turn_count": 1}

        def load(**_kwargs):
            release.wait(timeout=3)
            return [deleted]

        with patch(
            "ite.ui.reup._threads.SessionManager",
            return_value=SimpleNamespace(list_sessions=load),
        ):
            app = ThreadPanelApp()
            app._thread_history_cache[str(app.config.cwd.resolve())] = [deleted]
            try:
                async with app.run_test(size=(100, 40)) as pilot:
                    await app._toggle_thread_switcher_panel()
                    panel = app._thread_switcher_panel
                    assert "deleted" in panel._row_widgets
                    app._forget_saved_thread("deleted")
                    await app._sync_thread_switcher_panel(refresh_history=False)
                    release.set()
                    await pilot.pause()
                    assert "deleted" not in panel._row_widgets
                    assert not app._thread_history_cache[str(app.config.cwd.resolve())]
            finally:
                release.set()

    asyncio.run(run())


def test_new_and_renamed_threads_keep_stable_order() -> None:
    async def run() -> None:
        with patch(
            "ite.ui.reup._threads.SessionManager",
            return_value=SimpleNamespace(list_sessions=lambda **kw: []),
        ):
            app = ThreadPanelApp()
            async with app.run_test(size=(100, 40)) as pilot:
                app._open_session_order.append("new")
                app._open_sessions["new"] = SimpleNamespace(name="", turn_count=0)
                await app._toggle_thread_switcher_panel()
                await finish_history(app)
                panel = app._thread_switcher_panel
                assert "new" not in panel._row_widgets
                app._open_sessions["new"].turn_count = 1
                app._open_sessions["new"].name = "First turn"
                app._insert_thread_nav_session_at_top("new")
                await app._sync_thread_switcher_panel()
                row = panel._row_widgets["new"]
                assert [entry[0] for entry in panel._row_snapshot] == ["new", "current"]
                app._open_sessions["new"].name = "Renamed thread"
                await app._sync_thread_switcher_panel()
                await pilot.pause()
                assert panel._row_widgets["new"] is row
                assert [entry[0] for entry in panel._row_snapshot] == ["new", "current"]
                assert "Renamed thread" in str(row.render())

    asyncio.run(run())


def test_cancelled_open_does_not_create_duplicate_panel() -> None:
    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        original_mount = ThreadSwitcherSidePanel.on_mount

        async def delayed_mount(panel):
            started.set()
            await release.wait()
            await original_mount(panel)

        with (
            patch(
                "ite.ui.reup._threads.SessionManager",
                return_value=SimpleNamespace(list_sessions=lambda **kw: []),
            ),
            patch.object(ThreadSwitcherSidePanel, "on_mount", delayed_mount),
        ):
            app = ThreadPanelApp()
            async with app.run_test(size=(100, 40)) as pilot:
                opening = asyncio.create_task(app._toggle_thread_switcher_panel())
                await asyncio.wait_for(started.wait(), timeout=2)
                opening.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await opening
                reopening = asyncio.create_task(
                    app._sync_thread_switcher_panel(force_open=True)
                )
                release.set()
                await asyncio.wait_for(reopening, timeout=2)
                await pilot.pause()
                assert len(app.query(ThreadSwitcherSidePanel)) == 1
                assert app._thread_switcher_panel_is_open()

    asyncio.run(run())
