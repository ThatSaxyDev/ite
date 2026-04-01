from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from ite.config.loader import get_data_dir


class CompactArtifactManager:
    """Persist and load compaction summary artifacts."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id

    def _root(self) -> Path:
        root = get_data_dir() / "compact_artifacts"
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        return root

    def save_summary(self, summary: str) -> str:
        artifact_id = f"{self._session_id}_{uuid4().hex[:12]}"
        path = self._root() / f"{artifact_id}.md"
        path.write_text(summary, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return artifact_id

    def load_summary(self, artifact_id: str | None) -> str | None:
        if not artifact_id:
            return None
        path = self._root() / f"{artifact_id}.md"
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None
