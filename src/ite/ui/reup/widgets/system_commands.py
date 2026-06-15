from __future__ import annotations

from textual.command import DiscoveryHit, Hit, Hits, Provider


class ReupSystemCommandsProvider(Provider):
    async def discover(self) -> Hits:
        for command in self.app.get_system_commands(self.screen):
            if command.discover:
                yield DiscoveryHit(
                    command.title,
                    command.callback,
                    help=command.help,
                )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for command in self.app.get_system_commands(self.screen):
            if (match := matcher.match(command.title)) > 0:
                yield Hit(
                    match,
                    matcher.highlight(command.title),
                    command.callback,
                    help=command.help,
                )
