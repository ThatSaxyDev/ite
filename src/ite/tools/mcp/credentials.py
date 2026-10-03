from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import keyring

from ite.config.config import MCPServerConfig
from ite.config.loader import get_data_dir
from ite.utils.atomic_file import locked_file


class CredentialStore:
    """Connection-scoped keyring values; no implicit plaintext fallback."""

    def __init__(self, reference: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", reference):
            raise ValueError("Invalid connection credential reference")
        self.reference = reference
        self.service = f"ite.connections.{reference}"

    @property
    def lock_path(self) -> Path:
        return get_data_dir() / "auth" / "locks" / f"{self.reference}.json"

    def read(self, kind: str = "credentials") -> dict[str, Any]:
        raw = keyring.get_password(self.service, kind)
        if not raw:
            return {}
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TypeError("The saved connection credentials are invalid. Sign in again.")
        return value

    def write(self, values: dict[str, Any], kind: str = "credentials") -> None:
        with locked_file(self.lock_path):
            keyring.set_password(self.service, kind, json.dumps(values))

    def clear(self, kind: str = "credentials") -> None:
        with locked_file(self.lock_path):
            if keyring.get_password(self.service, kind) is not None:
                keyring.delete_password(self.service, kind)


def redact_connection_text(text: str, config: MCPServerConfig | None = None) -> str:
    """Remove known credential values and common authorization fields."""
    if config:
        values = [config.client_credentials_client_secret, config.auth,
                  *config.env.values(), *config.headers.values()]
        for value in sorted((v for v in values if v and len(v) >= 4), key=len, reverse=True):
            if value not in {"oauth", "client_credentials"}:
                text = text.replace(value, "[redacted]")
    text = re.sub(r"(?i)(bearer\s+)[^\s,;\"']+", r"\1[redacted]", text)
    text = re.sub(r"(?i)((?:access_token|refresh_token|client_secret|api_key|code)=)[^&\s]+", r"\1[redacted]", text)
    return text
