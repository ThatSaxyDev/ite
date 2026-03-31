import tempfile
import unittest
from pathlib import Path

from ite.client.response import StreamEvent, StreamEventType, TextDelta
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
    def __init__(self, events: list[StreamEvent]) -> None:
        self._events = events
        self.closed = False

    async def chat_completion(self, messages, tools=None, stream=True):
        for event in self._events:
            yield event

    async def close(self) -> None:
        self.closed = True


class CommitModalTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_commit_message_uses_injected_client(self) -> None:
        client = _FakeLLMClient(
            [
                StreamEvent(
                    type=StreamEventType.MESSAGE_COMPLETE,
                    text_delta=TextDelta(content="feat(ui): refine commit flow"),
                )
            ]
        )
        modal = CommitModal(
            config=Config(),
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
        client = _FakeLLMClient([StreamEvent(type=StreamEventType.ERROR, error="boom")])
        modal = CommitModal(
            config=Config(),
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
        client = _FakeLLMClient([StreamEvent(type=StreamEventType.MESSAGE_COMPLETE)])
        modal = CommitModal(
            config=Config(),
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
        self.assertEqual(
            modal._last_ai_error,
            "Commit subject generation returned an empty response.",
        )


if __name__ == "__main__":
    unittest.main()
