import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.hooks.hook_system import HookSystem
from ite.tools.builtin.apply_patch import ApplyPatchParams
from ite.tools.builtin.edit_file import EditParams
from ite.tools.builtin.shell import ShellParams
from ite.tools.registry import create_default_registry


class ToolParamNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tempdir)
        self.cwd = Path(self.temp_dir.name)
        self.config = Config(cwd=self.cwd, api_key="test")
        self.registry = create_default_registry(self.config)
        self.hook_system = HookSystem(self.config)

    async def _cleanup_tempdir(self) -> None:
        self.temp_dir.cleanup()

    async def test_grep_accepts_query_alias_for_pattern(self) -> None:
        target = self.cwd / "sample.txt"
        target.write_text("release bump workflow\n", encoding="utf-8")

        result = await self.registry.invoke(
            "grep",
            {"query": "release", "file": "sample.txt"},
            self.cwd,
            self.hook_system,
        )

        self.assertTrue(result.success, msg=result.error)
        self.assertIn("sample.txt", result.output)

    async def test_shell_accepts_cmd_alias_and_sanitizes_devnull_redirection(self) -> None:
        result = await self.registry.invoke(
            "shell",
            {"cmd": "printf 'ok' 2>/dev/null"},
            self.cwd,
            self.hook_system,
        )

        self.assertTrue(result.success, msg=result.error)
        self.assertEqual(result.output.strip(), "ok")

    async def test_edit_accepts_common_aliases(self) -> None:
        target = self.cwd / "sample.txt"
        target.write_text("temperature = 1\n", encoding="utf-8")

        result = await self.registry.invoke(
            "edit",
            {
                "file_path": "sample.txt",
                "oldText": "temperature = 1",
                "newText": "temperature = 0.3",
            },
            self.cwd,
            self.hook_system,
        )

        self.assertTrue(result.success, msg=result.error)
        self.assertIn("Edited", result.output)
        self.assertIn("0.3", target.read_text(encoding="utf-8"))

    async def test_apply_patch_accepts_patch_text_alias(self) -> None:
        target = self.cwd / "sample.txt"
        target.write_text("hello\n", encoding="utf-8")

        patch_text = "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: sample.txt",
                "@@",
                "-hello",
                "+world",
                "*** End Patch",
            ]
        )

        result = await self.registry.invoke(
            "apply_patch",
            {"patch_text": patch_text},
            self.cwd,
            self.hook_system,
        )

        self.assertTrue(result.success, msg=result.error)
        self.assertEqual(target.read_text(encoding="utf-8"), "world\n")

    def test_shell_schema_accepts_cmd_alias_during_validation(self) -> None:
        params = ShellParams(cmd="printf 'ok'")
        self.assertEqual(params.command, "printf 'ok'")

    def test_edit_schema_accepts_common_aliases_during_validation(self) -> None:
        params = EditParams(
            file_path="sample.txt",
            oldText="before",
            newText="after",
        )
        self.assertEqual(params.path, "sample.txt")
        self.assertEqual(params.old_string, "before")
        self.assertEqual(params.new_string, "after")

    def test_apply_patch_schema_accepts_patch_text_alias_during_validation(self) -> None:
        params = ApplyPatchParams(
            patch_text="*** Begin Patch\n*** End Patch",
        )
        self.assertEqual(params.patch, "*** Begin Patch\n*** End Patch")
