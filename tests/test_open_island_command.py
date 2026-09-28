from __future__ import annotations

import asyncio
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from rich.console import Console

from ite.commands import CommandContext, build_registry
from ite.config.config import Config
from ite.config.loader import save_open_island_settings
from ite.ui.reup.composer_views import build_command_palette_options


class _Agent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = SimpleNamespace(config=config)
        self.open_island_bridge = None
        self.enabled: list[bool] = []

    async def set_open_island_enabled(self, enabled: bool) -> bool:
        self.enabled.append(enabled)
        self.config.integrations.open_island.enabled = enabled
        return enabled


class OpenIslandCommandTests(TestCase):
    def _context(
        self, config: Config, stream: io.StringIO, agent: _Agent | None = None
    ) -> CommandContext:
        return CommandContext(
            config=config,
            agent=agent,
            tui=SimpleNamespace(),
            console=Console(file=stream, force_terminal=False, color_system=None),
        )

    def test_command_is_registered_for_help_and_composer_surfaces(self) -> None:
        registry = build_registry()
        command = registry.get("/oi")

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.description, "Show or toggle Open Island notifications")
        self.assertIn(
            "/oi",
            [option.name for option in build_command_palette_options(registry)],
        )

    def test_on_persists_and_refreshes_the_live_agent(self) -> None:
        with TemporaryDirectory() as directory:
            config = Config(cwd=Path(directory))
            agent = _Agent(config)
            stream = io.StringIO()
            context = self._context(config, stream, agent)

            with patch("ite.commands.open_island.save_open_island_settings") as save:
                asyncio.run(build_registry().dispatch("/oi", ["on"], context))

            save.assert_called_once_with(enabled=True)
            self.assertTrue(config.integrations.open_island.enabled)
            self.assertEqual(agent.enabled, [True])
            self.assertIn("enabled", stream.getvalue().lower())

    def test_system_config_persists_socket_override_when_toggled(self) -> None:
        with TemporaryDirectory() as directory:
            config_dir = Path(directory)
            config_path = config_dir / "config.toml"
            config_path.write_text(
                "[integrations.open_island]\n"
                "enabled = false\n"
                'socket_path = "/tmp/open-island.sock"\n',
                encoding="utf-8",
            )

            with (
                patch("ite.config.loader.get_config_dir", return_value=config_dir),
                patch(
                    "ite.config.loader.get_system_config_path",
                    return_value=config_path,
                ),
            ):
                save_open_island_settings(enabled=True)

            rendered = config_path.read_text(encoding="utf-8")
            self.assertIn("[integrations.open_island]", rendered)
            self.assertIn("enabled = true", rendered)
            self.assertIn('socket_path = "/tmp/open-island.sock"', rendered)
