"""Reject malformed AI subjects while leaving the user's commit editor free."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from textual.app import App
from textual.widgets import TextArea

from ite.config.config import Config
from ite.git.commit_messages import validate_commit_message
from ite.ui.reup.modals import CommitModal


def modal(client=None):
    return CommitModal(
        config=Config(),
        llm_client=client,
        branch="main",
        file_count=1,
        additions=1,
        deletions=0,
        changed_paths=["src/app.py"],
        diff_context="Fix the header",
    )


@pytest.mark.parametrize(
    "message", ["Updated files", "fix:", "fix(ui): ", "fix(): change", "fix:change"]
)
def test_invalid_generated_subjects_are_rejected(message):
    with pytest.raises(ValueError, match="Conventional Commit"):
        CommitModal._normalize_commit_message(message)


@pytest.mark.parametrize(
    "message", ["fix: restore header", "feat(ui)!: replace header", "revert: undo header"]
)
def test_valid_generated_subjects_are_accepted(message):
    assert CommitModal._normalize_commit_message(message) == message


def test_invalid_ai_output_retries_and_never_becomes_editor_content():
    import asyncio

    async def run():
        client = AsyncMock()
        client.complete_text.side_effect = ["Updated files", "fix(ui): restore header"]
        result = await modal(client)._generate_commit_message()
        assert result == "fix(ui): restore header"
        assert client.complete_text.await_count == 2
        assert "failed validation" in client.complete_text.call_args.args[0][-1]["content"]

    asyncio.run(run())


def test_repeated_invalid_ai_output_uses_valid_fallback():
    import asyncio

    async def run():
        client = AsyncMock()
        client.complete_text.return_value = "Updated files"
        result = await modal(client)._generate_commit_message()
        assert client.complete_text.await_count == 3
        assert validate_commit_message(result) == result

    asyncio.run(run())


def test_mounted_editor_accepts_users_nonconventional_message():
    import asyncio

    async def run():
        app = App()
        async with app.run_test(size=(100, 30)) as pilot:
            editor_modal = modal()
            results = []
            await app.push_screen(editor_modal, results.append)
            await pilot.pause()
            editor_modal.query_one("#commit-message", TextArea).load_text("My own checkpoint")
            await pilot.pause()
            editor_modal._dismiss_with_action("commit")
            await pilot.pause()
            assert results[0]["message"] == "My own checkpoint"

    asyncio.run(run())
