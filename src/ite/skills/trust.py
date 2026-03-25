from __future__ import annotations

import json
from pathlib import Path

from ite.config.loader import get_config_dir

TRUST_FILE_NAME = "trusted_skill_workspaces.json"


class SkillTrustManager:
    def __init__(self) -> None:
        self._path = get_config_dir() / TRUST_FILE_NAME

    def is_workspace_trusted(self, workspace: Path) -> bool:
        entries = self._load_entries()
        return str(Path(workspace).resolve()) in entries

    def trust_workspace(self, workspace: Path) -> Path:
        entries = self._load_entries()
        entries.add(str(Path(workspace).resolve()))
        self._save_entries(entries)
        return self._path

    def untrust_workspace(self, workspace: Path) -> Path:
        entries = self._load_entries()
        entries.discard(str(Path(workspace).resolve()))
        self._save_entries(entries)
        return self._path

    def _load_entries(self) -> set[str]:
        if not self._path.exists():
            return set()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(data, list):
            return set()
        return {str(Path(item).resolve()) for item in data if str(item).strip()}

    def _save_entries(self, entries: set[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(sorted(entries), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
