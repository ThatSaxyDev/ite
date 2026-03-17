import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ite.config.config import Config
from ite.ui.reup.app import ReupApp


class ReupCommandPaletteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _app(self) -> ReupApp:
        return ReupApp(Config(cwd=self.cwd, api_key="test-key"))

    def test_extract_slash_query_only_when_editing_first_token(self) -> None:
        self.assertEqual(ReupApp._extract_slash_query("/ap"), "/ap")
        self.assertEqual(ReupApp._extract_slash_query("   /ap"), "/ap")
        self.assertIsNone(ReupApp._extract_slash_query("hello"))
        self.assertIsNone(ReupApp._extract_slash_query("/approval auto"))
        self.assertIsNone(ReupApp._extract_slash_query("/approval\nauto"))

    def test_filtered_command_palette_matches_registry_commands(self) -> None:
        app = self._app()

        slash_only = app._filtered_command_palette("/")
        filtered = app._filtered_command_palette("/ap")

        self.assertTrue(slash_only)
        self.assertEqual(slash_only, sorted(slash_only, key=lambda entry: entry.name.lower()))
        self.assertGreater(len(slash_only), 8)
        self.assertEqual(slash_only[0].name, "/approval")
        self.assertEqual([entry.name for entry in filtered], ["/approval"])
        self.assertEqual(filtered[0].description, "Show or change approval mode")

    def test_palette_selection_clamps_at_bounds(self) -> None:
        app = self._app()
        app._filtered_command_palette_options = app._filtered_command_palette("/")
        app._command_palette_index = 0

        app._move_command_palette_selection(-1)
        self.assertEqual(app._command_palette_index, 0)

        app._command_palette_index = len(app._filtered_command_palette_options) - 1
        app._move_command_palette_selection(1)
        self.assertEqual(
            app._command_palette_index,
            len(app._filtered_command_palette_options) - 1,
        )


if __name__ == "__main__":
    unittest.main()
