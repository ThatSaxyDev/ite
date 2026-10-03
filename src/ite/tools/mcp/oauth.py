from __future__ import annotations

import json
import time
from asyncio import Lock
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastmcp.client.auth import OAuth

from ite.config.config import MCPServerConfig
from ite.config.loader import get_data_dir
from ite.tools.mcp.credentials import CredentialStore
from ite.utils.atomic_file import atomic_write, locked_file

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
            with locked_file(self._path):
                return self._get_locked(key, collection)

    def _get_locked(self, key: str, collection: str | None) -> dict[str, Any] | None:
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
            with locked_file(self._path):
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
            with locked_file(self._path):
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
            with locked_file(self._path):
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
        atomic_write(self._path, json.dumps(payload, indent=2, sort_keys=True))

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and float(expires_at) <= time.time()


class KeyringAsyncKeyValueStore(FileAsyncKeyValueStore):
    """SDK-compatible token store isolated to one connection binding."""

    def __init__(self, reference: str) -> None:
        self._store = CredentialStore(reference)
        super().__init__(self._store.lock_path)

    def _load_payload(self) -> dict[str, Any]:
        return self._store.read("oauth")

    def _save_payload(self, payload: dict[str, Any]) -> None:
        import keyring
        keyring.set_password(self._store.service, "oauth", json.dumps(payload))


class ReportingOAuth(OAuth):
    def __init__(
        self,
        *args: Any,
        progress_reporter: ProgressReporter | None = None,
        allow_browser: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._progress_reporter = progress_reporter
        self._allow_browser = allow_browser

    async def _emit(self, phase: str, detail: str | None = None) -> None:
        if self._progress_reporter is None:
            return
        result = self._progress_reporter(phase, detail)
        if result is not None:
            await result

    async def redirect_handler(self, authorization_url: str) -> None:
        if not self._allow_browser:
            raise RuntimeError("Sign in from Connections to authorize this service.")
        await self._emit("authorization_url", authorization_url)
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
    allow_browser: bool = True,
) -> OAuth:
    store = (KeyringAsyncKeyValueStore(config.credential_ref) if config.credential_ref
             else FileAsyncKeyValueStore(get_data_dir() / "auth" / "mcp_oauth_tokens.json"))
    return ReportingOAuth(
        mcp_url=url,
        scopes=config.oauth_scopes or None,
        client_name=config.oauth_client_name,
        token_storage=store,
        callback_port=config.oauth_callback_port,
        progress_reporter=progress_reporter,
        allow_browser=allow_browser,
    )
