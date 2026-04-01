import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.ui.reup.modals import AttachPickerModal
from ite.ui.reup.modals import CommitModal


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
        text = CommitModal._idle_status_text().plain

        self.assertIn("draft with AI", text)

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
