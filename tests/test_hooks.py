from __future__ import annotations

import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.config.config import Config, HookConfig, HookTrigger
from ite.hooks.hook_system import HookSystem


def _python_command(source: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


class HookSystemTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_hooks_do_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(
                cwd=Path(tmp),
                hooks_enabled=False,
                hooks=[
                    HookConfig(
                        name="disabled",
                        trigger=HookTrigger.BEFORE_AGENT,
                        command=_python_command("print('should not run')"),
                    )
                ],
            )
            hook_system = HookSystem(config)

            await hook_system.trigger_before_agent("hello")

            self.assertEqual(hook_system.snapshot()["runs"], [])

    async def test_hook_records_successful_run_with_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "hook.txt"
            command = _python_command(
                "import os, pathlib; "
                "pathlib.Path(os.environ['ITE_TEST_OUT']).write_text("
                "os.environ['ITE_TRIGGER'] + '|' + os.environ['ITE_TOOL_NAME']"
                "); print('hook ok')"
            )
            config = Config(
                cwd=Path(tmp),
                hooks_enabled=True,
                hooks=[
                    HookConfig(
                        name="log_tool",
                        trigger=HookTrigger.BEFORE_TOOL,
                        command=command,
                        blocking=True,
                    )
                ],
            )
            hook_system = HookSystem(config)

            with patch.dict("os.environ", {"ITE_TEST_OUT": str(out_path)}):
                await hook_system.trigger_before_tool("read_file", {"path": "x.py"})

            snapshot = hook_system.snapshot()
            self.assertEqual(out_path.read_text(), "before_tool|read_file")
            self.assertEqual(len(snapshot["runs"]), 1)
            run = snapshot["runs"][0]
            self.assertEqual(run["name"], "log_tool")
            self.assertEqual(run["trigger"], "before_tool")
            self.assertEqual(run["tool_name"], "read_file")
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["exit_code"], 0)
            self.assertIn("hook ok", run["stdout"])

    async def test_hook_records_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(
                cwd=Path(tmp),
                hooks_enabled=True,
                hooks=[
                    HookConfig(
                        name="failing",
                        trigger=HookTrigger.AFTER_AGENT,
                        command=_python_command(
                            "import sys; print('bad', file=sys.stderr); sys.exit(7)"
                        ),
                        blocking=True,
                    )
                ],
            )
            hook_system = HookSystem(config)

            await hook_system.trigger_after_agent("hello", None)

            run = hook_system.snapshot()["runs"][0]
            self.assertEqual(run["status"], "failed")
            self.assertEqual(run["exit_code"], 7)
            self.assertIn("Exited with code 7", run["error"])
            self.assertIn("bad", run["stderr"])

    async def test_hook_records_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(
                cwd=Path(tmp),
                hooks_enabled=True,
                hooks=[
                    HookConfig(
                        name="slow",
                        trigger=HookTrigger.BEFORE_AGENT,
                        command=_python_command("import time; time.sleep(5)"),
                        timeout_sec=0.1,
                        blocking=True,
                    )
                ],
            )
            hook_system = HookSystem(config)

            await hook_system.trigger_before_agent("hello")

            run = hook_system.snapshot()["runs"][0]
            self.assertEqual(run["status"], "timed_out")
            self.assertTrue(run["timed_out"])
            self.assertIn("Timed out", run["error"])

    async def test_non_blocking_hook_returns_before_command_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "hook.txt"
            config = Config(
                cwd=Path(tmp),
                hooks_enabled=True,
                hooks=[
                    HookConfig(
                        name="background",
                        trigger=HookTrigger.BEFORE_AGENT,
                        command=_python_command(
                            "import os, pathlib, time; "
                            "time.sleep(0.2); "
                            "pathlib.Path(os.environ['ITE_TEST_OUT']).write_text('done')"
                        ),
                        blocking=False,
                    )
                ],
            )
            hook_system = HookSystem(config)

            with patch.dict("os.environ", {"ITE_TEST_OUT": str(out_path)}):
                await hook_system.trigger_before_agent("hello")

            self.assertFalse(out_path.exists())
            snapshot = hook_system.snapshot()
            self.assertEqual(snapshot["runs"][0]["status"], "running")

            await hook_system.wait_for_background_hooks()

            self.assertEqual(out_path.read_text(), "done")
            self.assertEqual(hook_system.snapshot()["runs"][0]["status"], "completed")
