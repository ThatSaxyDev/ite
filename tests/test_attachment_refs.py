import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ite.attachment_refs import (
    discover_attachable_files,
    extract_at_query,
    extract_inline_attachment_refs,
    resolve_inline_attachment_refs,
    suggest_inline_attachment_paths,
)


class AttachmentRefsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)
        (self.cwd / "src").mkdir()
        (self.cwd / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
        (self.cwd / "README.md").write_text("# Hi\n", encoding="utf-8")

    def test_extract_inline_attachment_refs_supports_plain_and_quoted_tokens(self) -> None:
        refs = extract_inline_attachment_refs('check @src/app.py and @"README.md".')

        self.assertEqual([ref.value for ref in refs], ["src/app.py", "README.md"])
        self.assertEqual(refs[1].trailing, "")

    def test_extract_at_query_returns_trailing_query_only(self) -> None:
        self.assertEqual(extract_at_query("inspect @sr"), "sr")
        self.assertEqual(extract_at_query("@"), "")
        self.assertIsNone(extract_at_query("inspect @src/app.py later"))
        self.assertIsNone(extract_at_query("inspect\n@src"))

    def test_suggest_inline_attachment_paths_matches_relative_paths(self) -> None:
        files = discover_attachable_files(self.cwd)
        suggestions = suggest_inline_attachment_paths("src/a", cwd=self.cwd, files=files)

        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0].name, "app.py")

    def test_resolve_inline_attachment_refs_rewrites_message_and_queues_paths(self) -> None:
        result = resolve_inline_attachment_refs(
            "inspect @src/app.py please",
            cwd=self.cwd,
            existing_paths=[],
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.message, "inspect src/app.py please")
        self.assertEqual(len(result.added_paths), 1)
        self.assertTrue(result.queued_paths[0].endswith("src/app.py"))

    def test_resolve_inline_attachment_refs_reports_missing_file(self) -> None:
        result = resolve_inline_attachment_refs(
            "inspect @missing.py",
            cwd=self.cwd,
            existing_paths=[],
        )

        self.assertTrue(result.errors)
        self.assertIn("@missing.py", result.errors[0])

    def test_resolve_inline_attachment_refs_enforces_attachment_limit(self) -> None:
        extra = self.cwd / "notes.txt"
        extra.write_text("notes\n", encoding="utf-8")
        third = self.cwd / "todo.txt"
        third.write_text("todo\n", encoding="utf-8")
        fourth = self.cwd / "more.txt"
        fourth.write_text("more\n", encoding="utf-8")

        result = resolve_inline_attachment_refs(
            "@README.md @notes.txt @todo.txt @more.txt",
            cwd=self.cwd,
            existing_paths=[],
        )

        self.assertTrue(result.errors)
        self.assertIn("Too many attached files referenced with @", result.errors[-1])
