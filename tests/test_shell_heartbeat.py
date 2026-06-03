from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.config.config import Config
from ite.tools.base import ToolInvocation


def _load_shell_module():
    path = Path(__file__).resolve().parents[1] / "src" / "ite" / "tools" / "builtin" / "shell.py"
    spec = importlib.util.spec_from_file_location("_ite_shell_heartbeat_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load shell module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShellHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_shell_execute_emits_heartbeat_while_quiet(self) -> None:
        shell_module = _load_shell_module()
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool = shell_module.ShellTool(Config(cwd=cwd, api_key="test"))
            updates: list[dict[str, object]] = []

            async def on_progress(update: dict[str, object]) -> None:
                updates.append(update)

            with patch.object(shell_module, "_SHELL_PROGRESS_HEARTBEAT_SECONDS", 0.05):
                result = await asyncio.wait_for(
                    tool.execute(
                        ToolInvocation(
                            params={
                                "command": "python3 -c \"import time; time.sleep(0.12); print('done', flush=True)\""
                            },
                            cwd=cwd,
                            progress_callback=on_progress,
                        )
                    ),
                    timeout=3,
                )

            self.assertTrue(result.success, msg=result.error)
            quiet_updates = []
            for update in updates:
                metadata = update.get("metadata")
                if isinstance(metadata, dict) and metadata.get("has_new_output") is False:
                    quiet_updates.append(metadata)

            self.assertTrue(quiet_updates)
            self.assertTrue(
                all(metadata.get("status") == "command_running" for metadata in quiet_updates)
            )


if __name__ == "__main__":
    unittest.main()
