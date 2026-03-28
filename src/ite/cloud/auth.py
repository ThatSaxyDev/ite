from __future__ import annotations

import json
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rich.console import Console

from ite.config.config import Config
from ite.config.loader import get_data_dir


class CloudAuthError(RuntimeError):
    pass


@dataclass
class CloudSession:
    access_token: str
    refresh_token: str
    access_expires_at: float
    api_url: str
    client_id: str

    @property
    def is_access_valid(self) -> bool:
        return (self.access_expires_at - time.time()) > 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_expires_at": self.access_expires_at,
            "api_url": self.api_url,
            "client_id": self.client_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CloudSession":
        return cls(
            access_token=str(data.get("access_token") or ""),
            refresh_token=str(data.get("refresh_token") or ""),
            access_expires_at=float(data.get("access_expires_at") or 0),
            api_url=str(data.get("api_url") or ""),
            client_id=str(data.get("client_id") or "ite-cli"),
        )


def _cloud_session_path() -> Path:
    path = get_data_dir() / "auth" / "cloud_session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_cloud_session() -> CloudSession | None:
    path = _cloud_session_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        session = CloudSession.from_dict(data)
        if not session.access_token or not session.refresh_token or not session.api_url:
            return None
        return session
    except Exception:
        return None


def _save_cloud_session(session: CloudSession) -> None:
    path = _cloud_session_path()
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")


def clear_cloud_auth(*, revoke_remote: bool = True) -> bool:
    session = _load_cloud_session()
    cleared = False
    if session and revoke_remote:
      try:
          _post_json(
              f"{session.api_url.rstrip('/')}/auth/logout-terminal",
              {},
              access_token=session.access_token,
          )
      except Exception:
          pass
    path = _cloud_session_path()
    if path.exists():
        path.unlink()
        cleared = True
    return cleared


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    access_token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers: dict[str, str] = {"content-type": "application/json"}
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        payload = json.loads(body) if body else {}
        return int(exc.code), payload
    except URLError as exc:
        raise CloudAuthError(f"Could not reach iTE Cloud API: {exc}") from exc


def _get_json(url: str, access_token: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {}
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        payload = json.loads(body) if body else {}
        return int(exc.code), payload
    except URLError as exc:
        raise CloudAuthError(f"Could not reach iTE Cloud API: {exc}") from exc


def _refresh_cloud_session(session: CloudSession) -> CloudSession | None:
    status, payload = _post_json(
        f"{session.api_url.rstrip('/')}/auth/refresh",
        {"refreshToken": session.refresh_token},
    )
    if status != 200 or not payload.get("ok"):
        return None
    refreshed = CloudSession(
        access_token=str(payload.get("accessToken") or ""),
        refresh_token=str(payload.get("refreshToken") or ""),
        access_expires_at=time.time() + int(payload.get("expiresIn") or 0),
        api_url=session.api_url,
        client_id=session.client_id,
    )
    _save_cloud_session(refreshed)
    return refreshed


def _verify_cloud_session(session: CloudSession) -> bool:
    if session.is_access_valid:
        status, payload = _get_json(
            f"{session.api_url.rstrip('/')}/auth/me",
            access_token=session.access_token,
        )
        return status == 200 and bool(payload.get("ok"))
    refreshed = _refresh_cloud_session(session)
    return refreshed is not None


def ensure_cloud_auth(console: Console, config: Config) -> None:
    if not config.cloud_auth_enabled:
        return

    cloud_api_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if not cloud_api_url:
        raise CloudAuthError(
            "Cloud auth is enabled but no cloud endpoint is configured."
        )

    existing = _load_cloud_session()
    if existing and existing.api_url == cloud_api_url and _verify_cloud_session(existing):
        return

    status, payload = _post_json(
        f"{cloud_api_url}/auth/cli/start",
        {
            "clientId": config.cloud_client_id,
            "scope": "openid profile email",
        },
    )
    if status != 200 or not payload.get("ok"):
        raise CloudAuthError(f"Could not start cloud login: {payload}")

    auth_url = str(payload.get("authUrl") or "")
    poll_token = str(payload.get("pollToken") or "")
    expires_in = int(payload.get("expiresIn") or 0)
    interval = int(payload.get("interval") or 5)
    console.print()
    console.print("[bold bright_white]iTE Cloud sign-in required[/bold bright_white]")
    console.print("[dim]Opening your browser to complete sign-in...[/dim]")
    opened = webbrowser.open(auth_url)
    if not opened:
        console.print(f"[dim]Browser did not open automatically. Open:[/dim] {auth_url}")

    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        poll_status, poll_payload = _post_json(
            f"{cloud_api_url}/auth/cli/status",
            {
                "clientId": config.cloud_client_id,
                "pollToken": poll_token,
            },
        )
        if poll_status == 200 and poll_payload.get("ok"):
            session = CloudSession(
                access_token=str(poll_payload.get("accessToken") or ""),
                refresh_token=str(poll_payload.get("refreshToken") or ""),
                access_expires_at=time.time() + int(poll_payload.get("expiresIn") or 0),
                api_url=cloud_api_url,
                client_id=config.cloud_client_id,
            )
            _save_cloud_session(session)
            console.print("[bold green]Cloud sign-in complete.[/bold green]")
            return

        error = poll_payload.get("error") or {}
        code = str(error.get("code") or "")
        if code == "authorization_pending":
            continue
        if code == "slow_down":
            interval = max(interval + 1, int((error.get("details") or {}).get("interval") or interval + 1))
            continue
        if code == "access_denied":
            raise CloudAuthError("Cloud login was denied in the browser.")
        if code == "expired_token":
            raise CloudAuthError("Cloud login expired before completion.")
        raise CloudAuthError(f"Cloud login failed: {poll_payload}")

    raise CloudAuthError("Cloud login timed out.")
