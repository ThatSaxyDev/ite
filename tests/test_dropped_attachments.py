from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ite.attachment_refs import parse_dropped_file_paths
from ite.attachments import MAX_ATTACHMENTS


class ParseDroppedFilePathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.plain = base / "a.png"
        self.spaced = base / "my file.png"
        self.second = base / "b.png"
        for file_path in (self.plain, self.spaced, self.second):
            file_path.write_bytes(b"x")

    def test_plain_absolute_path(self) -> None:
        result = parse_dropped_file_paths(f"{self.plain}")
        self.assertEqual(result.paths, [str(self.plain)])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.path_like_count, 1)
        self.assertEqual(result.prose_count, 0)

    def test_single_quoted_path_with_spaces(self) -> None:
        result = parse_dropped_file_paths(f"'{self.spaced}'")
        self.assertEqual(result.paths, [str(self.spaced)])

    def test_double_quoted_path_with_spaces(self) -> None:
        result = parse_dropped_file_paths(f'"{self.spaced}"')
        self.assertEqual(result.paths, [str(self.spaced)])

    def test_backslash_escaped_path_with_spaces(self) -> None:
        escaped = str(self.spaced).replace(" ", "\\ ")
        result = parse_dropped_file_paths(escaped)
        self.assertEqual(result.paths, [str(self.spaced)])

    def test_file_uri_with_percent_encoding(self) -> None:
        from urllib.parse import quote

        uri = f"file://{quote(str(self.spaced))}"
        result = parse_dropped_file_paths(uri)
        self.assertEqual(result.paths, [str(self.spaced)])

    def test_file_uri_localhost(self) -> None:
        result = parse_dropped_file_paths(f"file://localhost{self.plain}")
        self.assertEqual(result.paths, [str(self.plain)])

    def test_file_uri_remote_host_reports_error(self) -> None:
        result = parse_dropped_file_paths(f"file://otherhost{self.plain}")
        self.assertEqual(result.paths, [])
        self.assertEqual(result.path_like_count, 1)
        self.assertTrue(result.errors)

    def test_newline_separated_batch(self) -> None:
        result = parse_dropped_file_paths(f"{self.plain}\n{self.second}")
        self.assertEqual(result.paths, [str(self.plain), str(self.second)])

    def test_newline_batch_with_quoted_spaces(self) -> None:
        result = parse_dropped_file_paths(f"{self.plain}\n'{self.spaced}'")
        self.assertEqual(result.paths, [str(self.plain), str(self.spaced)])

    def test_newline_batch_with_backslash_escapes(self) -> None:
        escaped = str(self.spaced).replace(" ", "\\ ")
        result = parse_dropped_file_paths(f"{self.plain}\n{escaped}")
        self.assertEqual(result.paths, [str(self.plain), str(self.spaced)])

    def test_space_separated_single_line_batch(self) -> None:
        result = parse_dropped_file_paths(f"{self.plain} {self.second}")
        self.assertEqual(result.paths, [str(self.plain), str(self.second)])

    def test_duplicates_are_removed(self) -> None:
        result = parse_dropped_file_paths(f"{self.plain}\n{self.plain}")
        self.assertEqual(result.paths, [str(self.plain)])

    def test_missing_file_reports_error(self) -> None:
        ghost = Path(self._tmp.name) / "ghost.png"
        result = parse_dropped_file_paths(str(ghost))
        self.assertEqual(result.paths, [])
        self.assertEqual(result.path_like_count, 1)
        self.assertIn("File not found", result.errors[0])

    def test_directory_reports_error(self) -> None:
        result = parse_dropped_file_paths(str(Path(self._tmp.name)))
        self.assertEqual(result.paths, [])
        self.assertEqual(result.path_like_count, 1)
        self.assertIn("directory", result.errors[0])

    def test_prose_only_text_is_not_intercepted(self) -> None:
        result = parse_dropped_file_paths("just some regular pasted prose")
        self.assertEqual(result.paths, [])
        self.assertEqual(result.path_like_count, 0)
        self.assertGreaterEqual(result.prose_count, 1)

    def test_relative_filename_is_treated_as_prose(self) -> None:
        result = parse_dropped_file_paths("report.md")
        self.assertEqual(result.path_like_count, 0)

    def test_mixed_prose_and_path_is_flagged(self) -> None:
        result = parse_dropped_file_paths(f"please look at {self.plain}")
        self.assertGreaterEqual(result.prose_count, 1)
        self.assertEqual(result.path_like_count, 1)

    def test_empty_and_whitespace_inputs(self) -> None:
        for text in ("", "   ", "\n\n"):
            result = parse_dropped_file_paths(text)
            self.assertEqual(result.paths, [])
            self.assertEqual(result.path_like_count, 0)

    def test_more_than_max_attachments_is_capped(self) -> None:
        extras = []
        try:
            for index in range(MAX_ATTACHMENTS + 2):
                extra = Path(self._tmp.name) / f"extra_{index}.png"
                extra.write_bytes(b"x")
                extras.append(extra)
            text = "\n".join(str(path) for path in extras)
            result = parse_dropped_file_paths(text)
            self.assertEqual(len(result.paths), MAX_ATTACHMENTS)
            self.assertTrue(any("attachments allowed" in e for e in result.errors))
        finally:
            for extra in extras:
                extra.unlink(missing_ok=True)

    @unittest.skipIf(os.name == "nt", "drive-letter paths resolve on Windows")
    def test_windows_drive_path_is_path_like_but_unresolved_on_posix(self) -> None:
        result = parse_dropped_file_paths('"C:\\Users\\kd\\Pictures\\shot.png"')
        self.assertEqual(result.paths, [])
        self.assertEqual(result.path_like_count, 1)
        self.assertTrue(result.errors)

    def test_overlong_path_is_reported_not_raised(self) -> None:
        # An unmatched apostrophe defeats shlex, so the whole line reaches the
        # stat() path. Over NAME_MAX this used to raise ENAMETOOLONG.
        long_prose = (
            "/chat " + "some context about the session. " * 12
            + "Don't just start writing code."
        )
        result = parse_dropped_file_paths(long_prose)
        self.assertEqual(result.paths, [])
        self.assertEqual(result.path_like_count, 1)
        self.assertTrue(result.errors)


class PromptAreaPasteInterceptionTests(unittest.TestCase):
    def _run_paste(self, text: str):
        from textual import events
        from textual.app import App

        from ite.ui.reup.widgets.prompt_area import ReupPromptTextArea

        class T(App):
            def compose(self):
                yield ReupPromptTextArea(id="prompt")

        async def scenario():
            staged: list[list[str]] = []
            notes: list[str] = []
            app = T()
            app.agent = SimpleNamespace(
                session=SimpleNamespace(pending_attachment_paths=[])
            )
            app.post_attachment_note = notes.append
            async with app.run_test(size=(100, 30)) as pilot:
                area = app.query_one("#prompt", ReupPromptTextArea)
                area.focus()
                app._insert_attachment_refs_into_prompt = (
                    lambda paths: staged.append(list(paths)) or 1
                )
                app.post_message(events.Paste(text))
                await pilot.pause()
                await pilot.pause()
            return staged, notes, area.text

        return asyncio.run(scenario())

    def test_drop_via_bracketed_paste_stages_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "photo.png"
            sample.write_bytes(b"x")
            staged, notes, composer = self._run_paste(f"file://{sample}")
            self.assertEqual(staged, [[str(sample)]])
            self.assertEqual(notes, [])
            self.assertEqual(composer, "")
            self.assertEqual(staged and [str(sample)], [str(sample)])

    def test_prose_paste_falls_through_untouched(self) -> None:
        staged, notes, composer = self._run_paste("plain pasted sentence")
        self.assertEqual(staged, [])
        self.assertEqual(notes, [])
        self.assertEqual(composer, "plain pasted sentence")


class NormalizeDroppedPathMessageTests(unittest.TestCase):
    def _make_app(self):
        app = SimpleNamespace(config=SimpleNamespace(cwd=Path.cwd()))
        app.agent = SimpleNamespace(
            session=SimpleNamespace(pending_attachment_paths=[])
        )
        app.notes: list[str] = []

        from ite.ui.reup._composer import ComposerMixin

        app.post_attachment_note = app.notes.append
        app._attachment_ref_for_path = lambda path: ComposerMixin._attachment_ref_for_path(
            app, path
        )
        app.normalize = lambda message: ComposerMixin._normalize_dropped_path_message(
            app, message
        )
        return app

    def test_file_uri_message_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "shot.png"
            sample.write_bytes(b"x")
            app = self._make_app()
            normalized = app.normalize(f"file://{sample}")
            self.assertEqual(normalized, "@shot.png")
            self.assertEqual(app.agent.session.pending_attachment_paths, [str(sample)])

    def test_prose_message_is_not_normalized(self) -> None:
        app = self._make_app()
        self.assertEqual(app.normalize("tell me about testing"), "tell me about testing")
        self.assertEqual(app.agent.session.pending_attachment_paths, [])

    def test_invalid_path_consumed_with_note(self) -> None:
        app = self._make_app()
        normalized = app.normalize("~/nonexistent/path/ghost.png")
        self.assertIsNone(normalized)
        self.assertTrue(app.notes)

    def test_slash_command_is_left_untouched(self) -> None:
        app = self._make_app()
        normalized = app.normalize("/plan")
        self.assertEqual(normalized, "/plan")
        self.assertEqual(app.agent.session.pending_attachment_paths, [])
        self.assertEqual(app.notes, [])


class RewriteTrailingDroppedPathTests(unittest.TestCase):
    def _make_app(self):
        app = SimpleNamespace(config=SimpleNamespace(cwd=Path.cwd()))
        app.agent = SimpleNamespace(
            session=SimpleNamespace(pending_attachment_paths=[])
        )
        from ite.ui.reup._composer import ComposerMixin

        app._attachment_ref_for_path = lambda path: ComposerMixin._attachment_ref_for_path(
            app, path
        )
        app._is_path_like_probe = (
            lambda candidate: ComposerMixin._is_path_like_probe(candidate)
        )
        app._drop_candidate_starts = (
            lambda tail: ComposerMixin._drop_candidate_starts(tail)
        )
        app.rewrite = lambda text: ComposerMixin._rewrite_trailing_dropped_path(
            app, text
        )
        return app

    def test_trailing_absolute_path_becomes_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "fix.png"
            sample.write_bytes(b"x")
            app = self._make_app()
            rewrite = app.rewrite(str(sample))
            self.assertIsNotNone(rewrite)
            updated, paths = rewrite
            self.assertEqual(updated, "@fix.png")
            self.assertEqual(paths, [str(sample)])

    def test_spaced_filename_is_quoted_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "my shot.png"
            sample.write_bytes(b"x")
            app = self._make_app()
            updated, paths = app.rewrite(str(sample))
            self.assertEqual(updated, '@"my shot.png"')
            self.assertEqual(paths, [str(sample)])

    def test_prose_before_path_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "fix.png"
            sample.write_bytes(b"x")
            app = self._make_app()
            updated, _ = app.rewrite(f"look at this {sample}")
            self.assertEqual(updated, "look at this @fix.png")

    def test_path_glued_to_previous_word_gets_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "fix.png"
            sample.write_bytes(b"x")
            app = self._make_app()
            updated, paths = app.rewrite(f"i see this{sample}")
            self.assertEqual(updated, "i see this @fix.png")
            self.assertEqual(paths, [str(sample)])

    def test_glued_path_with_spaces_still_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "my shot.png"
            sample.write_bytes(b"x")
            app = self._make_app()
            updated, _ = app.rewrite(f"look{sample}")
            self.assertEqual(updated, 'look @"my shot.png"')

    def test_partial_path_is_left_alone(self) -> None:
        app = self._make_app()
        self.assertIsNone(app.rewrite("/Users/kiishidavid/Desktop/fi"))

    def test_slash_command_is_left_alone(self) -> None:
        app = self._make_app()
        self.assertIsNone(app.rewrite("/help"))

    def test_long_slash_prose_is_left_alone(self) -> None:
        app = self._make_app()
        message = (
            "/chat " + "some context about the session. " * 12
            + "Don't just start writing code."
        )
        self.assertIsNone(app.rewrite(message))


if __name__ == "__main__":
    unittest.main()
