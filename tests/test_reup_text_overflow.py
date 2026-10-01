from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, TextArea

from ite.config.config import Config
from ite.ui.reup._composer import ComposerMixin
from ite.ui.reup._helpers import insert_voice_text_into_widget
from ite.ui.reup.app import ReupApp
from ite.ui.reup.modals import CommitModal


class OverflowApp(App[None]):
    CSS_PATH: ClassVar[list[Path]] = [
        Path(__file__).parents[1] / "src/ite/ui/reup" / path
        for path in ReupApp.CSS_PATH
    ]
    _present_plan_question_card = ComposerMixin._present_plan_question_card
    _resolve_plan_question_choice = ComposerMixin._resolve_plan_question_choice
    _reset_plan_question_state = ComposerMixin._reset_plan_question_state
    on_plan_question_button_pressed = ComposerMixin.on_plan_question_button_pressed
    _message_count = 0

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="conversation")

    def _refresh_empty_state(self) -> None:
        pass

    async def _pin_activity_indicator_to_end(self) -> None:
        pass


def commit_modal() -> CommitModal:
    return CommitModal(
        config=Config(),
        branch="main",
        file_count=2,
        additions=20,
        deletions=4,
        changed_paths=["src/ite/ui/reup/modals.py"],
        diff_context="updated UI",
    )


@pytest.mark.parametrize("width", [60, 100])
def test_question_options_wrap_and_remain_selectable(width: int) -> None:
    async def run() -> None:
        app = OverflowApp()
        async with app.run_test(size=(width, 40)) as pilot:
            option = (
                "Keep the existing workflow and explain its implementation tradeoffs. "
                * 3
            )
            task = asyncio.create_task(
                app._present_plan_question_card(
                    question_number=1,
                    question="Which approach should we use?",
                    options=[option, "Use the alternative"],
                    recommended_index=0,
                    allow_free_text=True,
                )
            )
            await pilot.pause()
            button = app.query_one("#pq-opt-0", Button)
            assert button.region.width <= button.parent.content_size.width
            assert button.content_size.height > 1
            await pilot.resize_terminal(50, 40)
            await pilot.pause()
            assert button.region.width <= button.parent.content_size.width
            await pilot.press("enter")
            result = await asyncio.wait_for(task, timeout=2)
            assert result["selected_option"] == option
            assert result["selected_index"] == 0
            assert button.disabled
            assert button.has_class("selected")

    asyncio.run(run())


@pytest.mark.parametrize("width", [60, 100])
def test_commit_editor_grows_wraps_and_scrolls(width: int) -> None:
    async def run() -> None:
        app = OverflowApp()
        async with app.run_test(size=(width, 30)) as pilot:
            modal = commit_modal()
            results = []
            await app.push_screen(modal, results.append)
            await pilot.pause()
            editor = modal.query_one("#commit-message", TextArea)
            assert editor.content_size.height == 3
            assert modal.query_one("#commit-confirm", Button).disabled
            editor.load_text("fix: improve message readability " * 30)
            await pilot.pause()
            assert editor.content_size.height == 6
            assert editor.max_scroll_y > 0
            assert editor.max_scroll_x == 0
            assert editor.styles.scrollbar_size_horizontal == 0
            actions = modal.query_one(".commit-actions")
            assert actions.region.bottom <= app.screen.size.height
            assert not modal.query_one("#commit-confirm", Button).disabled
            await pilot.resize_terminal(50, 24)
            await pilot.pause()
            assert editor.max_scroll_x == 0
            assert actions.region.bottom <= app.screen.size.height
            editor.load_text("fix: readable messages\n\nPreserve the commit body.")
            await pilot.pause()
            assert editor.content_size.height == 3
            assert insert_voice_text_into_widget(editor, "Voice text ")
            await pilot.pause()
            expected = editor.text.strip()
            modal._dismiss_with_action("commit")
            await pilot.pause()
            assert results[0]["message"] == expected
            assert "\n\nPreserve the commit body." in expected

    asyncio.run(run())


def test_ai_fill_updates_commit_textarea() -> None:
    async def run() -> None:
        app = OverflowApp()
        async with app.run_test(size=(100, 30)) as pilot:
            modal = commit_modal()
            await app.push_screen(modal)
            await pilot.pause()

            async def generate() -> str:
                return "fix: keep commit messages readable"

            modal._generate_commit_message = generate
            await modal._fill_commit_message_from_ai()
            await pilot.pause()
            assert modal.query_one("#commit-message", TextArea).text == await generate()
            assert not modal.query_one("#commit-confirm", Button).disabled

    asyncio.run(run())
