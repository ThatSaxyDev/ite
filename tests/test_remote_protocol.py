from __future__ import annotations

import unittest

from ite.remote.protocol import build_remote_transcript
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


if __name__ == "__main__":
    unittest.main()
