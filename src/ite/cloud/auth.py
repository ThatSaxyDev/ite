from __future__ import annotations

import json
import socket
import ssl
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from rich.console import Console

from ite.config.config import Config
from ite.config.config import DEFAULT_CLOUD_CLIENT_ID
from ite.config.loader import get_data_dir


class CloudAuthError(RuntimeError):
    pass


class CloudConnectionError(RuntimeError):
    """Raised when there's a network/connection issue but credentials may still be valid."""
    pass


_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
_CLOUD_HTTP_TIMEOUT_SEC = 10


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
            client_id=str(data.get("client_id") or DEFAULT_CLOUD_CLIENT_ID),
        )


@dataclass(frozen=True)
class CloudAuthStatus:
    state: str
    session: CloudSession | None = None
    message: str = ""

    @property
    def is_valid(self) -> bool:
        return self.state == CloudSessionState.VALID and self.session is not None


@dataclass(frozen=True)
class BundledModelsResult:
    models: list[dict[str, Any]]
    auth: CloudAuthStatus
    message: str = ""


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
        with urlopen(
            request,
            timeout=_CLOUD_HTTP_TIMEOUT_SEC,
            context=_SSL_CONTEXT,
        ) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        payload = json.loads(body) if body else {}
        return int(exc.code), payload
    except (TimeoutError, socket.timeout) as exc:
        raise CloudConnectionError(
            "iTE Cloud API took too long to respond. Check your connection and try again."
        ) from exc
    except URLError as exc:
        raise CloudConnectionError(f"Could not reach iTE Cloud API: {exc}") from exc


def _get_json(url: str, access_token: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {}
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(
            request,
            timeout=_CLOUD_HTTP_TIMEOUT_SEC,
            context=_SSL_CONTEXT,
        ) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        payload = json.loads(body) if body else {}
        return int(exc.code), payload
    except (TimeoutError, socket.timeout) as exc:
        raise CloudConnectionError(
            "iTE Cloud API took too long to respond. Check your connection and try again."
        ) from exc
    except URLError as exc:
        raise CloudConnectionError(f"Could not reach iTE Cloud API: {exc}") from exc


def _refresh_cloud_session(session: CloudSession) -> CloudSession | None:
    status, payload = _post_json(
        f"{session.api_url.rstrip('/')}/auth/refresh",
        {"refreshToken": session.refresh_token},
    )
    if status != 200 or not payload.get("ok"):
        # Server errors (5xx) when server is down/spinning up - raise connection error
        if status >= 500:
            raise CloudConnectionError(f"iTE Cloud API returned server error {status}")
        # Auth errors (401/403) - session expired or revoked
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


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "ready", "complete", "completed"}:
            return True
        if normalized in {"false", "0", "no", "pending", "waiting"}:
            return False
    return None


def _cloud_browser_ready(payload: dict[str, Any]) -> bool:
    readiness_keys = (
        "browserReady",
        "browserAuthenticated",
        "browserSessionReady",
        "webSessionReady",
        "sessionReady",
    )
    containers: list[dict[str, Any]] = [payload]
    for key in ("browser", "status", "details", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            containers.append(nested)

    for container in containers:
        for key in readiness_keys:
            ready = _coerce_optional_bool(container.get(key))
            if ready is None:
                continue
            if not ready:
                return False
    return True


class CloudSessionState:
    """Result of cloud session verification."""

    DISABLED = "disabled"
    SIGNED_OUT = "signed_out"
    VALID = "valid"
    INVALID = "invalid"  # Expired or revoked
    NETWORK_ERROR = "network_error"  # Can't reach API, credentials may still be valid
    NO_ENTITLEMENT = "no_entitlement"  # Signed in, but cloud feature is unavailable


def _verify_cloud_session(session: CloudSession) -> bool:
    """Verify session is valid, refreshing if needed. Returns True if valid.
    
    Raises CloudAuthError for auth failures, CloudConnectionError for network issues.
    """
    if session.is_access_valid:
        status, payload = _get_json(
            f"{session.api_url.rstrip('/')}/auth/me",
            access_token=session.access_token,
        )
        return status == 200 and bool(payload.get("ok"))
    # Try to refresh
    try:
        refreshed = _refresh_cloud_session(session)
        return refreshed is not None
    except CloudConnectionError:
        raise  # Propagate connection errors
    except Exception:
        return False


def check_cloud_session(session: CloudSession) -> str:
    """Check session state without raising on network errors.

    Returns: one of CloudSessionState.VALID, .INVALID, .NETWORK_ERROR
    """
    if session.is_access_valid:
        try:
            status, payload = _get_json(
                f"{session.api_url.rstrip('/')}/auth/me",
                access_token=session.access_token,
            )
            if status == 200 and bool(payload.get("ok")):
                return CloudSessionState.VALID
            # Server errors (5xx) when server is down/spinning up - keep session
            if status >= 500:
                return CloudSessionState.NETWORK_ERROR
            if status == 401:
                refreshed = _refresh_cloud_session(session)
                if refreshed is not None:
                    return CloudSessionState.VALID
                return CloudSessionState.INVALID
            # Remaining auth errors (403, etc.) mean the session is invalid.
            return CloudSessionState.INVALID
        except CloudConnectionError:
            return CloudSessionState.NETWORK_ERROR
        except CloudAuthError:
            return CloudSessionState.INVALID
    # Need to refresh
    try:
        refreshed = _refresh_cloud_session(session)
        if refreshed is not None:
            return CloudSessionState.VALID
        return CloudSessionState.INVALID
    except CloudConnectionError:
        return CloudSessionState.NETWORK_ERROR
    except CloudAuthError:
        return CloudSessionState.INVALID


def get_cloud_auth_status(config: Config) -> CloudAuthStatus:
    if not config.cloud_auth_enabled:
        return CloudAuthStatus(
            state=CloudSessionState.DISABLED,
            message="iTE Cloud auth is disabled.",
        )
    cloud_api_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if not cloud_api_url:
        return CloudAuthStatus(
            state=CloudSessionState.SIGNED_OUT,
            message="Cloud auth is enabled but no cloud endpoint is configured.",
        )
    existing = _load_cloud_session()
    if existing is None or existing.api_url != cloud_api_url:
        return CloudAuthStatus(
            state=CloudSessionState.SIGNED_OUT,
            message="No local iTE Cloud session is stored.",
        )
    state = check_cloud_session(existing)
    if state == CloudSessionState.VALID:
        refreshed = _load_cloud_session()
        session = (
            refreshed
            if refreshed is not None and refreshed.api_url == cloud_api_url
            else existing
        )
        return CloudAuthStatus(
            state=CloudSessionState.VALID,
            session=session,
            message="iTE Cloud session is active.",
        )
    if state == CloudSessionState.NETWORK_ERROR:
        return CloudAuthStatus(
            state=CloudSessionState.NETWORK_ERROR,
            session=existing,
            message="Stored iTE Cloud session found, but the API is unreachable.",
        )
    return CloudAuthStatus(
        state=CloudSessionState.INVALID,
        session=existing,
        message="Stored iTE Cloud session is expired or revoked.",
    )


def has_valid_cloud_auth(config: Config) -> bool:
    if not config.cloud_auth_enabled:
        return True
    cloud_api_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if not cloud_api_url:
        return False
    existing = _load_cloud_session()
    if existing is None or existing.api_url != cloud_api_url:
        return False
    try:
        return _verify_cloud_session(existing)
    except (CloudAuthError, CloudConnectionError):
        return False


def has_stored_cloud_auth(config: Config) -> bool:
    if not config.cloud_auth_enabled:
        return True
    cloud_api_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if not cloud_api_url:
        return False
    existing = _load_cloud_session()
    if existing is None or existing.api_url != cloud_api_url:
        return False
    return bool(existing.access_token and existing.refresh_token)


def get_cloud_session(config: Config) -> CloudSession | None:
    if not config.cloud_auth_enabled:
        return None

    cloud_api_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if not cloud_api_url:
        return None

    existing = _load_cloud_session()
    if existing is None or existing.api_url != cloud_api_url:
        return None

    try:
        if existing.is_access_valid:
            status, payload = _get_json(
                f"{existing.api_url.rstrip('/')}/auth/me",
                access_token=existing.access_token,
            )
            if status == 200 and bool(payload.get("ok")):
                return existing

        refreshed = _refresh_cloud_session(existing)
        return refreshed
    except (CloudAuthError, CloudConnectionError):
        return None


def _parse_bundled_models(payload: dict[str, Any]) -> list[dict[str, Any]]:
    models = payload.get("models")
    if not isinstance(models, list):
        return []


    bundled: list[dict[str, Any]] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_name = str(item.get("modelName") or "").strip()
        label = str(item.get("label") or model_name).strip()
        available = bool(item.get("available", True))
        unavailable_reason = str(item.get("unavailableReason") or "").strip()
        context_window_raw = item.get("contextWindow", item.get("context_window"))
        context_window = (
            int(context_window_raw)
            if isinstance(context_window_raw, int) and context_window_raw > 0
            else None
        )
        if not model_name:
            continue
        bundled.append(
            {
                "model_name": model_name,
                "label": label,
                "provider": "Bundled",
                "context_window": context_window,
                "context_window_source": "bundled_provider_api" if context_window else None,
                "available": available,
                "unavailable_reason": unavailable_reason,
            }
        )
    return bundled


def _cloud_payload_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("message", "detail", "code"):
            value = str(error.get(key) or "").strip()
            if value:
                return value
    for key in ("message", "detail", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def get_bundled_models_result(config: Config) -> BundledModelsResult:
    auth = get_cloud_auth_status(config)
    if not auth.is_valid:
        return BundledModelsResult(models=[], auth=auth, message=auth.message)

    session = auth.session
    assert session is not None
    try:
        status, payload = _get_json(
            f"{session.api_url.rstrip('/')}/models/bundled",
            access_token=session.access_token,
        )
        if status == 401:
            refreshed = _refresh_cloud_session(session)
            if refreshed is None:
                invalid = CloudAuthStatus(
                    state=CloudSessionState.INVALID,
                    session=session,
                    message="Stored iTE Cloud session is expired or revoked.",
                )
                return BundledModelsResult(models=[], auth=invalid, message=invalid.message)
            status, payload = _get_json(
                f"{refreshed.api_url.rstrip('/')}/models/bundled",
                access_token=refreshed.access_token,
            )
            auth = CloudAuthStatus(
                state=CloudSessionState.VALID,
                session=refreshed,
                message="iTE Cloud session is active.",
            )
    except CloudConnectionError as exc:
        network = CloudAuthStatus(
            state=CloudSessionState.NETWORK_ERROR,
            session=session,
            message=str(exc),
        )
        return BundledModelsResult(models=[], auth=network, message=str(exc))
    except CloudAuthError as exc:
        invalid = CloudAuthStatus(
            state=CloudSessionState.INVALID,
            session=session,
            message=str(exc) or "Stored iTE Cloud session is expired or revoked.",
        )
        return BundledModelsResult(models=[], auth=invalid, message=invalid.message)

    if status != 200 or not payload.get("ok"):
        message = _cloud_payload_message(payload) or f"iTE Cloud returned {status}."
        state = (
            CloudSessionState.INVALID
            if status == 401
            else CloudSessionState.NO_ENTITLEMENT
            if status == 403
            else CloudSessionState.NETWORK_ERROR
            if status >= 500
            else CloudSessionState.VALID
        )
        result_auth = CloudAuthStatus(state=state, session=session, message=message)
        return BundledModelsResult(models=[], auth=result_auth, message=message)

    return BundledModelsResult(
        models=_parse_bundled_models(payload),
        auth=auth,
        message="",
    )


def get_bundled_models(config: Config) -> list[dict[str, Any]]:
    return get_bundled_models_result(config).models


def get_cloud_entitlements(config: Config) -> dict[str, Any]:
    try:
        session = get_cloud_session(config)
        if session is None:
            return {}

        status, payload = _get_json(
            f"{session.api_url.rstrip('/')}/auth/me",
            access_token=session.access_token,
        )
    except (CloudAuthError, CloudConnectionError):
        return {}
    if status != 200 or not payload.get("ok"):
        return {}
    entitlements = payload.get("entitlements")
    return entitlements if isinstance(entitlements, dict) else {}


def has_remote_companion_access(config: Config) -> bool:
    entitlements = get_cloud_entitlements(config)
    if "remoteCompanion" in entitlements:
        return bool(entitlements.get("remoteCompanion"))
    return bool(entitlements.get("bundledInference"))


def get_usage_summary(config: Config) -> dict[str, Any] | None:
    try:
        session = get_cloud_session(config)
        if session is None:
            return None

        status, payload = _get_json(
            f"{session.api_url.rstrip('/')}/usage/summary",
            access_token=session.access_token,
        )
    except CloudAuthError:
        return None
    if status != 200 or not payload.get("ok"):
        return None
    return payload


def get_activity(config: Config) -> dict[str, Any] | None:
    try:
        session = get_cloud_session(config)
        if session is None:
            return None

        status, payload = _get_json(
            f"{session.api_url.rstrip('/')}/activity",
            access_token=session.access_token,
        )
    except CloudAuthError:
        return None
    if status != 200 or not payload.get("ok"):
        return None
    return payload


def ensure_cloud_auth(console: Console | None, config: Config) -> None:
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
            "deviceName": str(config.cloud_device_name or "").strip(),
            "deviceLabel": str(config.cloud_device_name or "").strip(),
            "scope": "openid profile email",
        },
    )
    if status != 200 or not payload.get("ok"):
        raise CloudAuthError(f"Could not start cloud login: {payload}")

    auth_url = str(payload.get("authUrl") or "")
    poll_token = str(payload.get("pollToken") or "")
    expires_in = int(payload.get("expiresIn") or 0)
    interval = int(payload.get("interval") or 5)
    if console is not None:
        console.print()
        console.print("[bold bright_white]iTE Cloud sign-in required[/bold bright_white]")
        console.print("[dim]Opening your browser to complete sign-in...[/dim]")
    opened = webbrowser.open(auth_url)
    if not opened and console is not None:
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
            if not _cloud_browser_ready(poll_payload):
                continue
            session = CloudSession(
                access_token=str(poll_payload.get("accessToken") or ""),
                refresh_token=str(poll_payload.get("refreshToken") or ""),
                access_expires_at=time.time() + int(poll_payload.get("expiresIn") or 0),
                api_url=cloud_api_url,
                client_id=config.cloud_client_id,
            )
            _save_cloud_session(session)
            if console is not None:
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
