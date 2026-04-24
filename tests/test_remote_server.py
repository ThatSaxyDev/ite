from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import unittest

from ite.remote.server import RemoteRuntimeServer
from ite.remote.server import _PlanQuestionRequest
from ite.remote.server import _PlanReadyRequest


class RemoteRuntimeServerStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_state_payload_includes_pending_plan_prompts(self) -> None:
        server = RemoteRuntimeServer(
            state_provider=lambda: {"current_session": {"session_id": "session-1"}},
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
        )
        loop = asyncio.get_running_loop()
        server._plan_question_requests["pq-1"] = _PlanQuestionRequest(
            future=loop.create_future(),
            created_at=datetime.now(timezone.utc),
            payload={
                "session_id": "session-1",
                "question": "Pick a direction",
                "options": ["A", "B"],
                "recommended_index": 0,
                "allow_free_text": True,
                "question_number": 1,
            },
        )
        server._plan_ready_requests["pr-1"] = _PlanReadyRequest(
            future=loop.create_future(),
            created_at=datetime.now(timezone.utc),
            payload={
                "session_id": "session-1",
                "plan_text": "1. Do it",
                "question_count": 1,
            },
        )

        payload = await server._build_state_payload()

        self.assertEqual(payload["pending_plan_question"]["request_id"], "pq-1")
        self.assertEqual(payload["pending_plan_question"]["question"], "Pick a direction")
        self.assertEqual(payload["pending_plan_ready"]["request_id"], "pr-1")
        self.assertEqual(payload["pending_plan_ready"]["plan_text"], "1. Do it")

    async def test_build_state_payload_preserves_runtime_command_feed(self) -> None:
        server = RemoteRuntimeServer(
            state_provider=lambda: {
                "current_session": {"session_id": "session-1"},
                "command_feed": [
                    {
                        "id": "cmd-1",
                        "session_id": "session-1",
                        "command": "/init --force",
                        "timestamp": "2026-04-23T20:00:00+00:00",
                        "status": "running",
                        "output": "Scanning project structure...",
                        "metadata": {
                            "kind": "generic",
                            "command_name": "/init",
                        },
                    }
                ],
            },
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
        )

        payload = await server._build_state_payload()

        self.assertEqual(len(payload["command_feed"]), 1)
        self.assertEqual(payload["command_feed"][0]["command"], "/init --force")
        self.assertEqual(payload["command_feed"][0]["status"], "running")
        self.assertEqual(payload["command_feed"][0]["metadata"]["kind"], "generic")

    async def test_resolve_plan_question_request_completes_pending_future(self) -> None:
        server = RemoteRuntimeServer(
            state_provider=lambda: {},
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
        )
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        server._plan_question_requests["pq-1"] = _PlanQuestionRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
            payload={"question": "Pick one"},
        )

        resolved = await server.resolve_plan_question_request(
            "pq-1",
            {"selected_option": "A", "free_text": "", "selected_index": 0},
        )

        self.assertTrue(resolved)
        self.assertEqual(future.result()["selected_option"], "A")

    async def test_resolve_plan_ready_request_completes_pending_future(self) -> None:
        server = RemoteRuntimeServer(
            state_provider=lambda: {},
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
        )
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        server._plan_ready_requests["pr-1"] = _PlanReadyRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
            payload={"plan_text": "1. Do it"},
        )

        resolved = await server.resolve_plan_ready_request("pr-1", True)

        self.assertTrue(resolved)
        self.assertTrue(future.result())


if __name__ == "__main__":
    unittest.main()
