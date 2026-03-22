import tempfile
import unittest
from pathlib import Path

from ite.ui.reup.modals import AttachPickerModal


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


if __name__ == "__main__":
    unittest.main()
