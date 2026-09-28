from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from textual.css.query import NoMatches

from ite.config.config import Config
from ite.ui.reup._turn import TurnMixin


class _LiveAgent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = type("Session", (), {"config": config})()
        self.calls: list[bool] = []

    async def set_open_island_enabled(self, enabled: bool) -> bool:
        self.calls.append(enabled)
        return enabled


class _TurnHarness(TurnMixin):
    def __init__(self, config: Config, agents: list[_LiveAgent]) -> None:
        self.config = config
        self.agent = agents[0]
        self._session_agents = {
            f"session-{index}": agent for index, agent in enumerate(agents)
        }

    def query_one(self, _selector: str):
        raise NoMatches("settings panel is not mounted")


class ReupOpenIslandTests(IsolatedAsyncioTestCase):
    async def test_toggle_updates_every_open_session_immediately(self) -> None:
        with TemporaryDirectory() as directory:
            primary = _LiveAgent(Config(cwd=Path(directory)))
            secondary = _LiveAgent(Config(cwd=Path(directory)))
            app = _TurnHarness(primary.config, [primary, secondary])

            with patch("ite.ui.reup._turn.save_open_island_settings") as save:
                await app._set_open_island_enabled(True)

            save.assert_called_once_with(enabled=True)
            self.assertTrue(app.config.integrations.open_island.enabled)
            self.assertTrue(primary.config.integrations.open_island.enabled)
            self.assertTrue(secondary.config.integrations.open_island.enabled)
            self.assertEqual(primary.calls, [True])
            self.assertEqual(secondary.calls, [True])
