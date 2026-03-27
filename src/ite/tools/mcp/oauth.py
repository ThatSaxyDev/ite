from __future__ import annotations

import json
import os
import time
from asyncio import Lock
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastmcp.client.auth import OAuth

from ite.config.config import MCPServerConfig
from ite.config.loader import get_data_dir

ProgressReporter = Callable[[str, str | None], Awaitable[None] | None]


class FileAsyncKeyValueStore:
    """Small file-backed async key-value store for MCP OAuth tokens."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()

    async def get(
        self,
        key: str,
        *,
        collection: str | None = None,
    ) -> dict[str, Any] | None:
        async with self._lock:
            payload = self._load_payload()
            bucket = payload.get(collection or "")
            if not isinstance(bucket, dict):
                return None
            entry = bucket.get(key)
            if not isinstance(entry, dict):
                return None
            if self._is_expired(entry):
                bucket.pop(key, None)
                self._save_payload(payload)
                return None
            value = entry.get("value")
            return value if isinstance(value, dict) else None

    async def get_many(
        self,
        keys: list[str],
        *,
        collection: str | None = None,
    ) -> list[dict[str, Any] | None]:
        return [await self.get(key, collection=collection) for key in keys]

    async def put(
        self,
        key: str,
        value: dict[str, Any],
        *,
        collection: str | None = None,
        ttl: float | None = None,
    ) -> None:
        async with self._lock:
            payload = self._load_payload()
            bucket = payload.setdefault(collection or "", {})
            expires_at = None if ttl is None else time.time() + float(ttl)
            bucket[key] = {"value": value, "expires_at": expires_at}
            self._save_payload(payload)

    async def put_many(
        self,
        keys: list[str],
        values: list[dict[str, Any]],
        *,
        collection: str | None = None,
        ttl: float | None = None,
    ) -> None:
        for key, value in zip(keys, values, strict=False):
            await self.put(key, value, collection=collection, ttl=ttl)

    async def delete(
        self,
        key: str,
        *,
        collection: str | None = None,
    ) -> bool:
        async with self._lock:
            payload = self._load_payload()
            bucket = payload.get(collection or "")
            if not isinstance(bucket, dict) or key not in bucket:
                return False
            del bucket[key]
            self._save_payload(payload)
            return True

    async def delete_many(
        self,
        keys: list[str],
        *,
        collection: str | None = None,
    ) -> int:
        deleted = 0
        for key in keys:
            deleted += int(await self.delete(key, collection=collection))
        return deleted

    async def ttl(
        self,
        key: str,
        *,
        collection: str | None = None,
    ) -> tuple[dict[str, Any] | None, float | None]:
        async with self._lock:
            payload = self._load_payload()
            bucket = payload.get(collection or "")
            if not isinstance(bucket, dict):
                return (None, None)
            entry = bucket.get(key)
            if not isinstance(entry, dict):
                return (None, None)
            if self._is_expired(entry):
                bucket.pop(key, None)
                self._save_payload(payload)
                return (None, None)
            value = entry.get("value")
            expires_at = entry.get("expires_at")
            if not isinstance(value, dict):
                return (None, None)
            ttl = None if expires_at is None else max(0.0, float(expires_at) - time.time())
            return (value, ttl)

    def _load_payload(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_payload(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(self._path)
        os.chmod(self._path, 0o600)

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and float(expires_at) <= time.time()


class ReportingOAuth(OAuth):
    def __init__(
        self,
        *args: Any,
        progress_reporter: ProgressReporter | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._progress_reporter = progress_reporter

    async def _emit(self, phase: str, detail: str | None = None) -> None:
        if self._progress_reporter is None:
            return
        result = self._progress_reporter(phase, detail)
        if result is not None:
            await result

    async def redirect_handler(self, authorization_url: str) -> None:
        await self._emit("auth_required", "Authorization is required.")
        await self._emit("opening_browser", "Opening browser for authorization.")
        await super().redirect_handler(authorization_url)
        await self._emit(
            "waiting_for_callback",
            f"Waiting for OAuth callback on localhost:{self.redirect_port}.",
        )

    async def callback_handler(self) -> tuple[str, str | None]:
        await self._emit(
            "waiting_for_callback",
            f"Waiting for OAuth callback on localhost:{self.redirect_port}.",
        )
        code, state = await super().callback_handler()
        await self._emit("callback_received", "Authorization callback received.")
        await self._emit("exchanging_token", "Exchanging authorization code for tokens.")
        return code, state


def build_oauth_provider(
    config: MCPServerConfig,
    url: str,
    progress_reporter: ProgressReporter | None = None,
) -> OAuth:
    store = FileAsyncKeyValueStore(
        get_data_dir() / "auth" / "mcp_oauth_tokens.json"
    )
    return ReportingOAuth(
        mcp_url=url,
        scopes=config.oauth_scopes or None,
        client_name=config.oauth_client_name,
        token_storage=store,
        callback_port=config.oauth_callback_port,
        progress_reporter=progress_reporter,
    )
