from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ite.config.config import MCPServerConfig


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float
    lock: asyncio.Lock


class ClientCredentialsAuth(httpx.Auth):
    """httpx.Auth that auto-refreshes a Bearer token via OAuth 2.0 client_credentials."""

    def __init__(
        self,
        config: MCPServerConfig,
        *,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._config = config
        self._cached: _CachedToken | None = None
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=30.0)
        )

    async def _fetch_token(self) -> tuple[str, int]:
        url = self._config.client_credentials_url
        client_id = self._config.client_credentials_client_id
        client_secret = self._config.client_credentials_client_secret
        if not url or not client_id or not client_secret:
            raise RuntimeError(
                "client_credentials auth requires client_credentials_url, "
                "client_credentials_client_id, and client_credentials_client_secret"
            )

        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        scope = self._config.client_credentials_scope
        if scope:
            data["scope"] = scope

        client = self._http_client_factory()
        try:
            response = await client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        finally:
            await client.aclose()

        if response.status_code >= 400:
            raise RuntimeError(
                f"client_credentials token request failed: {response.status_code} "
                f"{response.text[:200]}"
            )

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"client_credentials token response was not a JSON object: {payload!r}"
            )
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError(
                f"client_credentials token response missing access_token: {payload!r}"
            )
        expires_in = int(payload.get("expires_in", 3600))
        return access_token, expires_in

    async def _get_token(self) -> str:
        cached = self._cached
        if cached is not None and time.time() < cached.expires_at:
            return cached.access_token

        lock = cached.lock if cached is not None else asyncio.Lock()
        if cached is None:
            self._cached = _CachedToken("", 0.0, lock)
        async with lock:
            if self._cached is not None and time.time() < self._cached.expires_at:
                return self._cached.access_token

            access_token, expires_in = await self._fetch_token()
            buffer = self._config.client_credentials_refresh_buffer_sec
            self._cached = _CachedToken(
                access_token=access_token,
                expires_at=time.time() + max(expires_in - buffer, 1),
                lock=lock,
            )
            return access_token

    async def async_auth_flow(self, request: httpx.Request):
        token = await self._get_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if (
            response is not None
            and response.status_code in (401, 403)
            and self._cached is not None
            and time.time() >= self._cached.expires_at
        ):
            token = await self._get_token()
            request.headers["Authorization"] = f"Bearer {token}"
            yield request

    def auth_flow(self, request: httpx.Request):  # pragma: no cover - sync fallback unused
        raise RuntimeError(
            "ClientCredentialsAuth must be used with httpx.AsyncClient; "
            "sync client support is not implemented."
        )


def build_client_credentials_auth(config: MCPServerConfig) -> httpx.Auth:
    return ClientCredentialsAuth(config)


def client_credentials_http_client_factory(
    config: MCPServerConfig,
) -> Callable[..., httpx.AsyncClient]:
    auth = ClientCredentialsAuth(config)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("auth", None)
        return httpx.AsyncClient(auth=auth, **kwargs)

    return factory
