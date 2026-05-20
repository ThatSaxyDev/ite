import tempfile
import unittest
from pathlib import Path

from textual.app import App
from textual.widgets import Button
from textual.widgets import Input

from ite.config.config import Config
from ite.ui.reup.modals import AttachPickerModal
from ite.ui.reup.modals import CommitModal
from ite.ui.reup.modals import ThemePickerModal
from ite.ui.reup.modals import VoiceSetupModal
from ite.ui.reup.modals import is_hidden_textual_theme


class AttachPickerModalTests(unittest.TestCase):
    def test_resolve_root_path_uses_current_root_for_relative_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td).resolve()
            docs = cwd / "docs"
            nested = docs / "nested"
            nested.mkdir(parents=True)

            resolved = AttachPickerModal._resolve_root_path(
                "nested",
                cwd=cwd,
                current_root=docs,
            )

            self.assertEqual(resolved, nested)

    def test_resolve_root_path_rejects_missing_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td).resolve()

            with self.assertRaises(ValueError):
                AttachPickerModal._resolve_root_path(
                    "missing-folder",
                    cwd=cwd,
                    current_root=cwd,
                )

    def test_selection_summary_is_compact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td).resolve()
            modal = AttachPickerModal(cwd, [])
            modal._selected_paths = {
                str((cwd / "alpha.txt").resolve()),
                str((cwd / "bravo.txt").resolve()),
                str((cwd / "charlie.txt").resolve()),
                str((cwd / "delta.txt").resolve()),
            }

            summary = modal._selection_summary()

            self.assertIn("alpha.txt", summary)
            self.assertIn("(+1 more)", summary)


class ThemePickerModalTests(unittest.TestCase):
    def test_hidden_textual_theme_names_cover_ansi_variants(self) -> None:
        hidden_names = {
            "textual-ansi",
            "ansi_light",
            "ansi-light",
            "ansi_dark",
            "ansi-dark",
            "textual-ansi-light",
            "textual_ansi_dark",
        }

        self.assertTrue(all(is_hidden_textual_theme(name) for name in hidden_names))
        self.assertFalse(is_hidden_textual_theme("textual-dark"))

    def test_theme_picker_excludes_hidden_ansi_themes(self) -> None:
        modal = ThemePickerModal("textual-dark")

        self.assertNotIn("textual-ansi", modal._theme_names)
        self.assertNotIn("ansi_light", modal._theme_names)
        self.assertNotIn("ansi_dark", modal._theme_names)


class VoiceSetupModalApp(App[None]):
    def on_mount(self) -> None:
        self.dismissed_result: str | None = "not-dismissed"
        self.push_screen(
            VoiceSetupModal(),
            callback=lambda result: setattr(self, "dismissed_result", result),
        )


class VoiceSetupModalTests(unittest.IsolatedAsyncioTestCase):
    async def test_buttons_use_shared_modal_ids_and_cancel_dismisses(self) -> None:
        async with VoiceSetupModalApp().run_test() as pilot:
            await pilot.pause()

            screen = pilot.app.screen
            confirm = screen.query_one("#confirm", Button)
            cancel = screen.query_one("#cancel", Button)

            self.assertEqual(str(confirm.label), "Save")
            self.assertEqual(str(cancel.label), "Cancel")

            api_key = screen.query_one("#voice-groq-api-key", Input)
            await pilot.press("g", "s", "k", "_", "t", "e", "s", "t")
            self.assertEqual(api_key.value, "gsk_test")

            await pilot.press("escape")

            self.assertIsNone(pilot.app.dismissed_result)


class _FakeLLMClient:
    def __init__(
        self,
        result: str | None = None,
        error: Exception | None = None,
        sequence: list[str | Exception] | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self._sequence = list(sequence or [])
        self.closed = False

    async def complete_text(self, messages):
        if self._sequence:
            item = self._sequence.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self._error is not None:
            raise self._error
        return self._result or ""

    async def close(self) -> None:
        self.closed = True


class CommitModalTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _config() -> Config:
        return Config(model={"name": "local-test"})

    def test_idle_status_text_exposes_ai_hint(self) -> None:
        modal = CommitModal(
            config=Config(),
            branch="main",
            file_count=1,
            additions=1,
            deletions=0,
            changed_paths=["src/app.py"],
            diff_context="updated app",
        )
        modal._get_theme_colors = lambda: {  # type: ignore[method-assign]
            "muted": "#8c93a1",
            "primary": "#4edea3",
        }
        text = modal._idle_status_text().plain

        self.assertIn("draft with AI", text)

    def test_commit_modal_exposes_voice_binding(self) -> None:
        bindings = {binding[0] for binding in CommitModal.BINDINGS}

        self.assertIn("f8", bindings)

    def test_loading_copy_rotates_across_multiple_lines(self) -> None:
        modal = CommitModal(
            config=Config(),
            branch="main",
            file_count=2,
            additions=10,
            deletions=2,
            changed_paths=["src/lib/usage.ts", "src/ite/ui/reup/modals.py"],
            diff_context="updated commit modal and usage helpers",
        )

        first = modal._loading_copy(0)
        second = modal._loading_copy(1)

        self.assertNotEqual(first, second)
        self.assertNotIn("Generating commit subject", first)
        self.assertLessEqual(len(first.split()), 3)
        self.assertLessEqual(len(second.split()), 3)

    async def test_generate_commit_message_uses_injected_client(self) -> None:
        client = _FakeLLMClient(result="feat(ui): refine commit flow")
        modal = CommitModal(
            config=self._config(),
            llm_client=client,
            branch="main",
            file_count=1,
            additions=10,
            deletions=2,
            changed_paths=["src/ite/ui/reup/modals.py"],
            diff_context="updated commit modal",
        )

        message = await modal._generate_commit_message()

        self.assertEqual(message, "feat(ui): refine commit flow")
        self.assertFalse(client.closed)

    async def test_generate_commit_message_falls_back_when_client_errors(self) -> None:
        client = _FakeLLMClient(error=RuntimeError("boom"))
        modal = CommitModal(
            config=self._config(),
            llm_client=client,
            branch="main",
            file_count=1,
            additions=10,
            deletions=2,
            changed_paths=["src/ite/git/working_tree.py"],
            diff_context="updated working tree flow",
        )

        message = await modal._generate_commit_message()

        self.assertEqual(message, "feat(git): improve working tree change review")
        self.assertEqual(modal._last_ai_error, "boom")

    async def test_generate_commit_message_records_empty_response_error(self) -> None:
        client = _FakeLLMClient(
            sequence=[
                ValueError("Commit subject generation returned an empty response."),
                "feat(lib): tighten usage helpers",
            ]
        )
        modal = CommitModal(
            config=self._config(),
            llm_client=client,
            branch="main",
            file_count=1,
            additions=10,
            deletions=2,
            changed_paths=["src/lib/usage.ts"],
            diff_context="updated usage helpers",
        )

        message = await modal._generate_commit_message()

        self.assertEqual(message, "feat(lib): tighten usage helpers")
        self.assertEqual(modal._last_ai_error, "Commit subject generation returned an empty response.")

    async def test_generate_commit_message_falls_back_after_both_attempts_fail(self) -> None:
        client = _FakeLLMClient(
            sequence=[
                ValueError("Commit subject generation returned an empty response."),
                RuntimeError("boom"),
                RuntimeError("boom"),
            ]
        )
        modal = CommitModal(
            config=self._config(),
            llm_client=client,
            branch="main",
            file_count=1,
            additions=10,
            deletions=2,
            changed_paths=["src/lib/usage.ts"],
            diff_context="updated usage helpers",
        )

        message = await modal._generate_commit_message()

        self.assertEqual(message, "chore(lib): update usage")
        self.assertEqual(modal._last_ai_error, "boom")


if __name__ == "__main__":
    unittest.main()
