import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ite.agent.session_manager import SessionManager, SessionSnapshot
from ite.client.response import TokenUsage


class SessionManagerCorruptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)

        patcher = patch("ite.agent.session_manager.get_data_dir", return_value=self.base_path)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.manager = SessionManager()

    def _write_valid_session(self, session_id: str) -> Path:
        file_path = self.manager.sessions_dir / f"{session_id}.json"
        payload = {
            "session_id": session_id,
            "name": "Building Games with Three.js",
            "created_at": "2026-03-04T11:46:07.637365",
            "updated_at": "2026-03-04T11:46:52.384048",
            "turn_count": 3,
            "messages": [{"role": "user", "content": "hello"}],
            "total_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cached_tokens": 0,
            },
        }
        file_path.write_text(json.dumps(payload), encoding="utf-8")
        return file_path

    def test_list_sessions_skips_and_quarantines_invalid_json(self) -> None:
        self._write_valid_session("valid-session")
        bad_file = self.manager.sessions_dir / "broken.json"
        bad_file.write_text("", encoding="utf-8")

        sessions = self.manager.list_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], "valid-session")
        self.assertFalse(bad_file.exists())

        corrupt_dir = self.manager.sessions_dir / "corrupt"
        quarantined = list(corrupt_dir.glob("broken.*.json"))
        self.assertTrue(quarantined)

    def test_list_sessions_skips_and_quarantines_missing_required_fields(self) -> None:
        missing_fields_file = self.manager.sessions_dir / "missing-fields.json"
        missing_fields_file.write_text(
            json.dumps({"session_id": "x", "updated_at": "2026-03-04T11:46:52.384048"}),
            encoding="utf-8",
        )

        sessions = self.manager.list_sessions()

        self.assertEqual(sessions, [])
        self.assertFalse(missing_fields_file.exists())
        quarantined = list((self.manager.sessions_dir / "corrupt").glob("missing-fields.*.json"))
        self.assertTrue(quarantined)

    def test_load_session_returns_none_for_corrupt_json(self) -> None:
        corrupt_file = self.manager.sessions_dir / "corrupt-session.json"
        corrupt_file.write_text("{", encoding="utf-8")

        loaded = self.manager.load_session("corrupt-session")

        self.assertIsNone(loaded)
        self.assertFalse(corrupt_file.exists())
        quarantined = list((self.manager.sessions_dir / "corrupt").glob("corrupt-session.*.json"))
        self.assertTrue(quarantined)

    def test_save_session_writes_valid_json(self) -> None:
        snapshot = SessionSnapshot(
            session_id="save-check",
            name="Test Session",
            created_at=datetime(2026, 3, 4, 11, 46, 7, 637365),
            updated_at=datetime(2026, 3, 4, 11, 46, 52, 384048),
            turn_count=1,
            messages=[{"role": "user", "content": "hello"}],
            total_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            pending_plan_text="## Plan\n- step one",
            todos_state={
                "version": 1,
                "planning": [{"id": "p1", "content": "clarify", "completed": False}],
                "execution": [{"id": "e1", "content": "implement", "completed": False}],
            },
            show_planning_todos=True,
        )

        self.manager.save_session(snapshot)
        file_path = self.manager.sessions_dir / "save-check.json"

        self.assertTrue(file_path.exists())
        loaded = json.loads(file_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["session_id"], "save-check")
        self.assertEqual(loaded["total_usage"]["total_tokens"], 2)
        self.assertIn("pending_plan_text", loaded)
        self.assertIn("step one", loaded["pending_plan_text"])
        self.assertTrue(loaded["show_planning_todos"])
        self.assertIn("todos_state", loaded)

    def test_save_session_compacts_older_tool_payloads(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "Calling tool",
                "tool_calls": [
                    {
                        "id": "call-old",
                        "type": "function",
                        "function": {
                            "name": "shell",
                            "arguments": "{\"command\":\"" + ("x" * 1200) + "\"}",
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-old", "content": "A" * 4000},
        ]
        for i in range(14):
            call_id = f"call-{i}"
            messages.append(
                {
                    "role": "assistant",
                    "content": f"Assistant {i}",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "shell",
                                "arguments": "{\"command\":\"echo ok\"}",
                            },
                        }
                    ],
                }
            )
            messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": f"tool output {i}"}
            )

        snapshot = SessionSnapshot(
            session_id="compact-check",
            name="Compact Session",
            created_at=datetime(2026, 3, 4, 11, 46, 7, 637365),
            updated_at=datetime(2026, 3, 4, 11, 46, 52, 384048),
            turn_count=1,
            messages=messages,
            total_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

        self.manager.save_session(snapshot)
        file_path = self.manager.sessions_dir / "compact-check.json"
        loaded = json.loads(file_path.read_text(encoding="utf-8"))

        old_assistant = loaded["messages"][0]
        old_tool = loaded["messages"][1]
        recent_tool = loaded["messages"][-1]

        self.assertLess(len(old_assistant["tool_calls"][0]["function"]["arguments"]), 500)
        self.assertIn("trimmed in saved session", old_tool["content"])
        self.assertEqual(recent_tool["content"], "tool output 13")


if __name__ == "__main__":
    unittest.main()
