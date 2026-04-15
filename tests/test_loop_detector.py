import unittest
from pathlib import Path

from ite.context.loop_detector import LoopDetector


class LoopDetectorTests(unittest.TestCase):
    def test_normalizes_discovery_tool_paths_against_cwd(self) -> None:
        detector = LoopDetector()
        cwd = Path("/tmp/example-workspace")

        detector.record_action(
            "tool_call",
            tool_name="list_dir",
            args={"path": ".", "include_hidden": False},
            cwd=cwd,
        )
        detector.record_action(
            "tool_call",
            tool_name="list_dir",
            args={"path": str(cwd), "include_hidden": False},
            cwd=cwd,
        )
        detector.record_action(
            "tool_call",
            tool_name="list_dir",
            args={"path": "./", "include_hidden": False},
            cwd=cwd,
        )

        self.assertEqual(
            detector.check_for_loop(),
            "Same action repeated 3 times",
        )

    def test_keeps_non_discovery_tool_args_unchanged(self) -> None:
        detector = LoopDetector()

        detector.record_action(
            "tool_call",
            tool_name="shell",
            args={"command": "pwd"},
            cwd=Path("/tmp/example-workspace"),
        )
        detector.record_action(
            "tool_call",
            tool_name="shell",
            args={"command": "ls"},
            cwd=Path("/tmp/example-workspace"),
        )

        self.assertIsNone(detector.check_for_loop())
