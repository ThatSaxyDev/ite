from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from ite.agent.agent import Agent
from ite.config.config import Config


class _Bridge:
    enabled = True

    def __init__(self) -> None:
        self.closed = False

    def observe(self, _event: object) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


class AgentOpenIslandToggleTests(IsolatedAsyncioTestCase):
    async def test_disabling_detaches_and_closes_the_live_bridge(self) -> None:
        with TemporaryDirectory() as directory:
            agent = Agent(Config(cwd=Path(directory)))
            bridge = _Bridge()
            agent._open_island_bridge = bridge  # type: ignore[assignment]
            agent._event_observers.append(bridge.observe)

            active = await agent.set_open_island_enabled(False)

            self.assertFalse(active)
            self.assertTrue(bridge.closed)
            self.assertIsNone(agent.open_island_bridge)
            self.assertNotIn(bridge.observe, agent._event_observers)

    async def test_enabling_attaches_a_fresh_bridge_without_restarting(self) -> None:
        with TemporaryDirectory() as directory:
            agent = Agent(Config(cwd=Path(directory)))
            bridge = _Bridge()

            with patch.object(agent, "_build_open_island_bridge", return_value=bridge):
                active = await agent.set_open_island_enabled(True)

            self.assertTrue(active)
            self.assertTrue(agent.config.integrations.open_island.enabled)
            self.assertIs(agent.open_island_bridge, bridge)
