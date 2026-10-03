from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from textual import events
from textual.app import App
from textual.containers import VerticalScroll

from ite.attachment_refs import attachment_copy_text, resolve_inline_attachment_refs
from ite.ui.reup._composer import ComposerMixin
from ite.ui.reup._streaming import StreamingMixin
from ite.ui.reup.widgets.message_row import UserMessageRow
from ite.ui.reup.widgets.prompt_area import ReupPromptTextArea


class AttachmentApp(ComposerMixin, StreamingMixin, App):
    on_prompt_changed = ComposerMixin.on_prompt_changed

    def on_key(self, event) -> None:
        pass

    def handle_prompt_palette_key(self, event) -> bool:
        return False

    def _render_user_message(self, message):
        return message

    def __init__(self, cwd: Path) -> None:
        super().__init__()
        self.config = SimpleNamespace(cwd=cwd)
        self.agent = SimpleNamespace(session=SimpleNamespace(pending_attachment_paths=[]))
        self._suppress_history_reset_once = False
        self._composer_history_index = None
        self._applying_history_nav = False
        self._rewriting_dropped_path = False
        self._hydrating_from_snapshot = False
        self._message_count = 0
        self._attachable_files_cache = []
        self._attachable_files_cache_cwd = cwd.resolve()
        self.palette = []

    def compose(self):
        yield VerticalScroll(id="conversation")
        yield ReupPromptTextArea(id="prompt")

    def _sync_command_palette(self, text: str) -> None:
        self.palette = self._filtered_attachment_palette(text)

    def _clear_command_palette(self) -> None:
        self.palette = []

    def _resize_composer_for_prompt(self) -> None:
        pass

    def _refresh_empty_state(self) -> None:
        pass

    async def _pin_activity_indicator_to_end(self) -> None:
        pass


@pytest.mark.parametrize("initial", ["", "look at this", "first line\nlook at this"])
def test_drop_spacing_cursor_and_continued_typing(tmp_path: Path, initial: str) -> None:
    import asyncio

    sample = tmp_path / "my image.png"
    sample.touch()

    async def scenario():
        app = AttachmentApp(tmp_path)
        async with app.run_test() as pilot:
            area = app.query_one(ReupPromptTextArea)
            area.load_text(initial)
            area.move_cursor((area.text.count("\n"), len(area.text.split("\n")[-1])))
            area.focus()
            await pilot.pause()
            with patch.object(app, "_discover_attachable_files", side_effect=AssertionError("drop scanned workspace")):
                app.post_message(events.Paste(str(sample)))
                await pilot.pause()
                expected = (initial + " " if initial else "") + '@"my image.png" '
                assert area.text == expected
                assert area.cursor_location == (expected.count("\n"), len(expected.split("\n")[-1]))
                await pilot.press("o", "k")
                assert area.text == expected + "ok"
                assert app.agent.session.pending_attachment_paths == [str(sample)]
    asyncio.run(scenario())


@pytest.mark.parametrize("suffix", [".png", ".pdf", ".json"])
def test_copied_external_attachment_rebinds_after_send(tmp_path: Path, suffix: str) -> None:
    import asyncio

    cwd = tmp_path / "workspace"
    cwd.mkdir()
    sample = tmp_path / ("my file" + suffix)
    sample.touch()

    async def scenario():
        app = AttachmentApp(cwd)
        async with app.run_test() as pilot:
            app.agent.session.pending_attachment_paths = [str(sample)]
            message = 'look at @"' + sample.name + '"'
            await app.add_user_message(message)
            row = app.query_one(UserMessageRow)
            with patch.object(app, "copy_to_clipboard") as clipboard:
                row.on_click()
            copied = clipboard.call_args.args[0]
            assert str(sample.resolve()) in copied
            app.agent.session.pending_attachment_paths = []
            area = app.query_one(ReupPromptTextArea)
            area.focus()
            app.post_message(events.Paste(copied))
            await pilot.pause()
            assert area.text == message
            payload, errors = app._resolve_inline_attachment_payload(
                message=area.text, attachments=app.agent.session.pending_attachment_paths,
            )
            assert errors == []
            assert payload["attachments"] == [str(sample.resolve())]
            assert area.cursor_location == (0, len(message))
    asyncio.run(scenario())


def test_modal_insert_uses_same_spacing_and_cursor(tmp_path: Path) -> None:
    import asyncio

    sample = tmp_path / "report.pdf"
    sample.touch()

    async def scenario():
        app = AttachmentApp(tmp_path)
        async with app.run_test() as pilot:
            area = app.query_one(ReupPromptTextArea)
            area.load_text("hello\nreview")
            area.move_cursor((area.text.count("\n"), len(area.text.split("\n")[-1])))
            app.ensure_agent = lambda: asyncio.sleep(0)
            async def select(_modal):
                return [str(sample)]
            app._open_modal = select
            from ite.ui.reup._panels import PanelsMixin
            await PanelsMixin._open_attach_picker_from_meta(app)
            await pilot.pause()
            assert area.text == "hello\nreview @report.pdf "
            assert area.cursor_location == (1, len("review @report.pdf "))
            assert app.agent.session.pending_attachment_paths == [str(sample)]
    asyncio.run(scenario())


def test_typed_drop_adds_trailing_space(tmp_path: Path) -> None:
    import asyncio

    sample = tmp_path / "photo.png"
    sample.touch()

    async def scenario():
        app = AttachmentApp(tmp_path)
        async with app.run_test() as pilot:
            area = app.query_one(ReupPromptTextArea)
            area.focus()
            area.insert("look" + str(sample))
            await pilot.pause()
            assert area.text == "look @photo.png "
            assert area.cursor_location == (0, len(area.text))
            await pilot.press("o", "k")
            assert area.text == "look @photo.png ok"
    asyncio.run(scenario())


def test_copy_keeps_each_same_name_attachment_location(tmp_path: Path) -> None:
    paths = []
    for name in ["one", "two"]:
        folder = tmp_path / name
        folder.mkdir()
        sample = folder / "same.json"
        sample.touch()
        paths.append(str(sample))
    texts = [attachment_copy_text("@same.json", cwd=tmp_path, paths=[path]) for path in paths]
    for text, path in zip(texts, paths):
        result = resolve_inline_attachment_refs(text, cwd=tmp_path, files=[])
        assert result.errors == []
        assert result.queued_paths == [str(Path(path).resolve())]


def test_pending_external_file_wins_over_workspace_basename(tmp_path: Path) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    (cwd / "same.json").touch()
    external = tmp_path / "same.json"
    external.touch()
    result = resolve_inline_attachment_refs("@same.json", cwd=cwd, existing_paths=[str(external)], files=[])
    assert result.errors == []
    assert result.queued_paths == [str(external.resolve())]


def test_palette_does_not_discard_selected_directory(tmp_path: Path) -> None:
    app = AttachmentApp(tmp_path)
    for folder in ["one", "two"]:
        directory = tmp_path / folder
        directory.mkdir()
        (directory / "same.json").touch()
    app._attachable_files_cache_cwd = None
    options = app._filtered_attachment_palette("@one/s")
    assert options[0].insert_text == "@one/same.json"
    result = resolve_inline_attachment_refs(options[0].insert_text, cwd=tmp_path, files=[])
    assert result.queued_paths == [str((tmp_path / "one/same.json").resolve())]


def test_dropping_two_external_files_with_same_name_keeps_both(tmp_path: Path) -> None:
    import asyncio

    cwd = tmp_path / "workspace"
    cwd.mkdir()
    paths = []
    for name in ["one", "two"]:
        folder = tmp_path / name
        folder.mkdir()
        sample = folder / "same.json"
        sample.touch()
        paths.append(str(sample))

    async def scenario():
        app = AttachmentApp(cwd)
        async with app.run_test() as pilot:
            area = app.query_one(ReupPromptTextArea)
            area.focus()
            for path in paths:
                app.post_message(events.Paste(path))
                await pilot.pause()
            payload, errors = app._resolve_inline_attachment_payload(
                message=area.text, attachments=app.agent.session.pending_attachment_paths,
            )
            assert errors == []
            assert set(payload["attachments"]) == set(paths)
            assert area.cursor_location == (0, len(area.text))
    asyncio.run(scenario())


def test_workspace_index_does_not_block_a_drop(tmp_path: Path) -> None:
    import asyncio
    import threading

    sample = tmp_path / "photo.png"
    sample.touch()
    started = threading.Event()
    release = threading.Event()

    def discover(_cwd):
        started.set()
        release.wait(timeout=5)
        return [sample]

    async def scenario():
        app = AttachmentApp(tmp_path)
        app._attachable_files_cache_cwd = None
        async with app.run_test() as pilot:
            area = app.query_one(ReupPromptTextArea)
            area.focus()
            with patch("ite.ui.reup._composer.discover_attachable_files", side_effect=discover):
                try:
                    area.load_text("@")
                    assert await asyncio.to_thread(started.wait, 1)
                    area.load_text("")
                    await pilot.pause()
                    app.post_message(events.Paste(str(sample)))
                    await pilot.pause()
                    assert not release.is_set()
                    assert area.text == "@photo.png "
                    assert area.cursor_location == (0, len(area.text))
                finally:
                    release.set()
                await pilot.pause()
    asyncio.run(scenario())
