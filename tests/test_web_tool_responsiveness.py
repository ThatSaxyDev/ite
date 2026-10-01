from __future__ import annotations

import asyncio
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from ite.config.config import ApprovalPolicy, Config
from ite.hooks.hook_system import HookSystem
from ite.safety.approval import ApprovalManager
from ite.tools.base import Tool, ToolInvocation
from ite.tools.builtin.web_fetch import WebFetchTool
from ite.tools.builtin.web_search import WebSearchTool
from ite.tools.registry import ToolRegistry


class WebToolResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def _check_responsiveness(
        self,
        tool: Tool,
        params: dict[str, Any],
        patch_target: str,
        output: Any,
        check_output: Callable[[str], None],
    ) -> None:
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()

        def blocking_work(*args: Any, **kwargs: Any) -> Any:
            loop.call_soon_threadsafe(started.set)
            # Bounded so a regression cannot hang the test suite.
            release.wait(timeout=2)
            return output

        registry = ToolRegistry(tool.config)
        registry.register(tool)
        with patch(patch_target, side_effect=blocking_work):
            task = asyncio.create_task(
                registry.invoke(
                    tool.name,
                    params,
                    tool.config.cwd,
                    HookSystem(tool.config),
                    ApprovalManager(ApprovalPolicy.AUTO, tool.config.cwd),
                )
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                # The event loop must run while the synchronous operation is
                # still waiting, rather than only after it has completed.
                await asyncio.sleep(0)
                self.assertFalse(task.done(), "Blocking web work stalled the event loop")
            finally:
                release.set()
                result = await asyncio.wait_for(task, timeout=5)

        self.assertTrue(result.success, msg=result.error)
        check_output(result.output)

    async def test_search_keeps_event_loop_responsive(self) -> None:
        config = Config(cwd=Path.cwd(), api_key="test", hooks_enabled=False)
        with patch("ite.tools.builtin.web_search.DDGS") as client:
            client.return_value.text.return_value = [
                {"title": "Example", "href": "https://example.com", "body": "Test"}
            ]
            # Exercise client initialization as well as the synchronous search.
            await self._check_responsiveness(
                WebSearchTool(config),
                {"query": "test"},
                "ite.tools.builtin.web_search.DDGS",
                client.return_value,
                lambda output: self.assertIn("Example", output),
            )

    async def test_html_conversion_keeps_event_loop_responsive(self) -> None:
        config = Config(cwd=Path.cwd(), api_key="test", hooks_enabled=False)
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<main><p>Example</p></main>",
            )
        )
        client = httpx.AsyncClient(transport=transport)
        with patch("ite.tools.builtin.web_fetch.httpx.AsyncClient", return_value=client):
            await self._check_responsiveness(
                WebFetchTool(config),
                {"url": "https://example.com"},
                "ite.tools.builtin.web_fetch._html_to_markdown",
                "Example",
                lambda output: self.assertEqual(output, "Example"),
            )

    async def test_search_client_error_returns_tool_error(self) -> None:
        config = Config(cwd=Path.cwd(), api_key="test")
        with patch("ite.tools.builtin.web_search.DDGS", side_effect=RuntimeError("offline")):
            result = await WebSearchTool(config).execute(
                ToolInvocation(params={"query": "test"}, cwd=config.cwd)
            )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Search failed: offline")
