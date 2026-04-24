from __future__ import annotations

import unittest

from ite.remote.protocol import build_remote_transcript
from ite.remote.protocol import MAX_REMOTE_RECENT_TEXT_CHARS
from ite.remote.protocol import MAX_REMOTE_TEXT_CHARS
from ite.remote.protocol import serialize_plan_question_request
from ite.remote.protocol import serialize_plan_ready_request
from ite.remote.protocol import serialize_transcript_message


class RemoteProtocolTests(unittest.TestCase):
    def test_serialize_transcript_skips_suppressed_malformed_tool_message(self) -> None:
        event = {
            "created_at": "2026-04-23T06:34:00+00:00",
            "message": {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "skills",
                "content": "Invalid parameters: Parameter '': Value error, skill is required for show, activate, and deactivate",
                "tool_ui": {
                    "name": "skills",
                    "success": False,
                    "error": "Invalid parameters: Parameter '': Value error, skill is required for show, activate, and deactivate",
                    "metadata": {"suppressed": True},
                },
            },
        }

        self.assertIsNone(serialize_transcript_message(event))

    def test_serialize_transcript_keeps_real_tool_failure(self) -> None:
        event = {
            "created_at": "2026-04-23T06:34:00+00:00",
            "message": {
                "role": "tool",
                "tool_call_id": "call_2",
                "name": "shell",
                "content": "Error: command exited with status 1",
                "tool_ui": {
                    "name": "shell",
                    "success": False,
                    "error": "Error: command exited with status 1",
                    "metadata": {},
                },
            },
        }

        payload = serialize_transcript_message(event)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["role"], "tool")
        self.assertEqual(payload["name"], "shell")

    def test_serialize_transcript_uses_tool_ui_name_for_historical_tool_cards(self) -> None:
        event = {
            "created_at": "2026-04-23T06:53:00+00:00",
            "message": {
                "role": "tool",
                "tool_call_id": "call_3",
                "content": "from __future__ import annotations",
                "tool_ui": {
                    "name": "read_file",
                    "success": True,
                    "output": "from __future__ import annotations",
                    "metadata": {"path": "src/ite/remote/server.py"},
                },
            },
        }

        payload = serialize_transcript_message(event)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["role"], "tool")
        self.assertEqual(payload["name"], "read_file")

    def test_build_remote_transcript_filters_only_suppressed_tool_noise(self) -> None:
        events = [
            {
                "created_at": "2026-04-23T06:33:00+00:00",
                "message": {"role": "user", "content": "use the release-bump skill"},
            },
            {
                "created_at": "2026-04-23T06:34:00+00:00",
                "message": {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "skills",
                    "content": "Invalid parameters: Parameter '': Value error, skill is required for show, activate, and deactivate",
                    "tool_ui": {
                        "name": "skills",
                        "success": False,
                        "error": "Invalid parameters: Parameter '': Value error, skill is required for show, activate, and deactivate",
                        "metadata": {"suppressed": True},
                    },
                },
            },
            {
                "created_at": "2026-04-23T06:35:00+00:00",
                "message": {
                    "role": "tool",
                    "tool_call_id": "call_2",
                    "name": "shell",
                    "content": "Error: command exited with status 1",
                    "tool_ui": {
                        "name": "shell",
                        "success": False,
                        "error": "Error: command exited with status 1",
                        "metadata": {},
                    },
                },
            },
        ]

        transcript = build_remote_transcript(events)
        self.assertEqual(len(transcript), 2)
        self.assertEqual([item["role"] for item in transcript], ["user", "tool"])
        self.assertEqual(transcript[1]["name"], "shell")

    def test_build_remote_transcript_preserves_recent_message_content(self) -> None:
        older_text = "a" * (MAX_REMOTE_TEXT_CHARS + 200)
        recent_text = "b" * (MAX_REMOTE_TEXT_CHARS + 200)
        events = [
            {
                "created_at": "2026-04-23T06:30:00+00:00",
                "message": {"role": "assistant", "content": older_text},
            },
            {
                "created_at": "2026-04-23T06:31:00+00:00",
                "message": {"role": "assistant", "content": "filler-1"},
            },
            {
                "created_at": "2026-04-23T06:32:00+00:00",
                "message": {"role": "assistant", "content": "filler-2"},
            },
            {
                "created_at": "2026-04-23T06:33:00+00:00",
                "message": {"role": "assistant", "content": "filler-3"},
            },
            {
                "created_at": "2026-04-23T06:34:00+00:00",
                "message": {"role": "assistant", "content": recent_text},
            },
        ]

        transcript = build_remote_transcript(events)

        self.assertEqual(len(transcript[0]["content"]), MAX_REMOTE_TEXT_CHARS)
        self.assertTrue(transcript[0]["content"].endswith("…"))
        self.assertEqual(transcript[-1]["content"], recent_text)
        self.assertLess(len(transcript[-1]["content"]), MAX_REMOTE_RECENT_TEXT_CHARS)

    def test_serialize_plan_question_request_compacts_and_shapes_payload(self) -> None:
        payload = serialize_plan_question_request(
            request_id="req-1",
            session_id="session-1",
            question="Which path should we take?",
            options=["A", "B", "C", "D", "E"],
            recommended_index=1,
            allow_free_text=True,
            question_number=2,
        )

        self.assertEqual(payload["request_id"], "req-1")
        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["options"], ["A", "B", "C", "D"])
        self.assertEqual(payload["recommended_index"], 1)
        self.assertTrue(payload["allow_free_text"])
        self.assertEqual(payload["question_number"], 2)
        self.assertIn("timestamp", payload)

    def test_serialize_plan_ready_request_compacts_and_shapes_payload(self) -> None:
        payload = serialize_plan_ready_request(
            request_id="req-2",
            session_id="session-2",
            plan_text="1. Step one\n2. Step two",
            question_count=3,
        )

        self.assertEqual(payload["request_id"], "req-2")
        self.assertEqual(payload["session_id"], "session-2")
        self.assertEqual(payload["plan_text"], "1. Step one\n2. Step two")
        self.assertEqual(payload["question_count"], 3)
        self.assertIn("timestamp", payload)


if __name__ == "__main__":
    unittest.main()
