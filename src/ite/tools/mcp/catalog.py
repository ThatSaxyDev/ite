from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionRecipe:
    name: str
    description: str
    url: str
    auth: str


CONNECTION_CATALOG = {
    "github": ConnectionRecipe("GitHub", "Work with repositories and issues.",
                               "https://api.githubcopilot.com/mcp/", "token"),
    "notion": ConnectionRecipe("Notion", "Search and work with your notes and pages.",
                               "https://mcp.notion.com/mcp", "oauth"),
}
