from __future__ import annotations

import json
import logging
import os
import shutil
import ssl
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import certifi

logger = logging.getLogger(__name__)

_GH_HOST = "github.com"
_HTTP_TIMEOUT_SEC = 10
_CMD_TIMEOUT_SEC = 30
_CREDENTIALS_FILE_MODE = 0o600

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


@dataclass
class GithubState:
    linked: bool = False
    username: str = ""
    account_id: str = ""
    full_access: bool = False
    gh_ready: bool = False
    missing_scopes: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "linked": self.linked,
            "username": self.username,
            "account_id": self.account_id,
            "full_access": self.full_access,
            "gh_ready": self.gh_ready,
            "missing_scopes": list(self.missing_scopes),
            "error": self.error,
        }


def _home() -> Path:
    # The supervisor redirects HOME per user, so all credential paths below are
    # automatically tenant-scoped. Never resolve another user's directory.
    override = str(os.environ.get("HOME") or "").strip()
    if override:
        return Path(override)
    return Path.home()


def _run(
    *args: str, input_text: str | None = None, timeout: float = _CMD_TIMEOUT_SEC
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            start_new_session=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(list(args), returncode=1, stdout="", stderr="not found")
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            list(args),
            returncode=124,
            stdout=str(exc.stdout or ""),
            stderr="command timed out",
        )


def gh_available() -> bool:
    return shutil.which("gh") is not None


def _gh_login_from_hosts() -> str:
    path = _home() / ".config" / "gh" / "hosts.yml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        if isinstance(data, dict):
            entry = data.get(_GH_HOST)
            if isinstance(entry, dict):
                user = str(entry.get("user") or "").strip()
                if user:
                    return user
    except Exception:
        pass
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("user:"):
            return stripped.split(":", 1)[1].strip().strip("'\"")
    return ""


def local_gh_state() -> GithubState:
    """Local-only state: is `gh` present and is anyone logged in?"""
    state = GithubState(gh_ready=gh_available())
    if not state.gh_ready:
        state.error = "github_cli_missing"
        return state
    result = _run("gh", "auth", "status", "-h", _GH_HOST)
    if result.returncode == 0:
        state.linked = True
        state.username = _gh_login_from_hosts()
        return state
    state.error = "github_not_linked"
    return state


def _broker_request(path: str, api_url: str, runtime_token: str) -> dict[str, Any]:
    base = str(api_url or "").strip().rstrip("/")
    token = str(runtime_token or "").strip()
    if not base or not token:
        raise RuntimeError("GitHub broker needs an API URL and a runtime token.")
    request = urllib.request.Request(
        f"{base}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SEC, context=_SSL_CONTEXT) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def broker_status(api_url: str, runtime_token: str) -> dict[str, Any]:
    return _broker_request("/remote/github/status", api_url, runtime_token)


def broker_token(api_url: str, runtime_token: str) -> dict[str, Any]:
    return _broker_request("/remote/github/token", api_url, runtime_token)


def broker_unlink(api_url: str, runtime_token: str) -> dict[str, Any]:
    base = str(api_url or "").strip().rstrip("/")
    token = str(runtime_token or "").strip()
    request = urllib.request.Request(
        f"{base}/remote/github/link",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="DELETE",
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SEC, context=_SSL_CONTEXT) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _write_credentials_file(username: str, token: str) -> None:
    home = _home()
    path = home / ".git-credentials"
    entry = f"https://{username}:{token}@{_GH_HOST}"
    existing: list[str] = []
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        existing = []
    kept = [line for line in existing if _GH_HOST not in line and line.strip()]
    kept.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.chmod(tmp, _CREDENTIALS_FILE_MODE)
    tmp.replace(path)
    try:
        os.chmod(path, _CREDENTIALS_FILE_MODE)
    except OSError:
        pass


def _clear_credentials_file() -> None:
    path = _home() / ".git-credentials"
    try:
        if not path.exists():
            return
        kept = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if _GH_HOST not in line and line.strip()
        ]
        if kept:
            path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        else:
            path.unlink()
    except OSError:
        pass


def connect(api_url: str, runtime_token: str) -> GithubState:
    """Fetch the broker token and materialize it into the tenant HOME."""
    state = GithubState(gh_ready=gh_available())
    if not state.gh_ready:
        state.error = "github_cli_missing"
        return state
    try:
        payload = broker_token(api_url, runtime_token)
    except Exception as exc:
        logger.warning("GitHub broker token fetch failed: %s", type(exc).__name__)
        state.error = "github_token_fetch_failed"
        return state
    github = payload.get("github") if isinstance(payload, dict) else None
    token = str((github or {}).get("token") or "").strip() if isinstance(github, dict) else ""
    if not token:
        state.error = "github_not_linked"
        return state
    status: dict[str, Any] = {}
    try:
        status = broker_status(api_url, runtime_token)
    except Exception:
        status = {}
    node = status.get("github") if isinstance(status, dict) else {}
    username = str((node or {}).get("username") or "").strip() if isinstance(node, dict) else ""
    email = str((node or {}).get("email") or "").strip() if isinstance(node, dict) else ""
    name = str((node or {}).get("name") or "").strip() if isinstance(node, dict) else ""
    if not username:
        username = _gh_login_from_hosts() or "oauth"
    # Token travels via stdin so it never appears in argv or logs.
    result = _run("gh", "auth", "login", "--with-token", "-h", _GH_HOST, input_text=token.strip() + "\n")
    if result.returncode != 0:
        logger.warning("gh auth login failed: %s", result.stderr.strip()[-300:])
        state.error = "github_token_fetch_failed"
        return state
    _run("git", "config", "--global", "credential.helper", "store")
    _write_credentials_file(username, token)
    _run("git", "config", "--global", "user.name", name or username)
    # Email default: use the GitHub primary email as-is, no noreply forcing.
    if email:
        _run("git", "config", "--global", "user.email", email)
    state.linked = True
    state.username = username or _gh_login_from_hosts()
    state.account_id = str((github or {}).get("accountId") or "") if isinstance(github, dict) else ""
    state.full_access = True
    return state


def disconnect(api_url: str = "", runtime_token: str = "") -> GithubState:
    if gh_available():
        _run("gh", "auth", "logout", "-h", _GH_HOST)
    _clear_credentials_file()
    if api_url and runtime_token:
        try:
            broker_unlink(api_url, runtime_token)
        except Exception as exc:
            logger.warning("GitHub broker unlink failed: %s", type(exc).__name__)
    return local_gh_state()


def sync_if_linked(api_url: str, runtime_token: str) -> GithubState:
    """Re-materialize credentials on child boot when the account is linked."""
    try:
        status = broker_status(api_url, runtime_token)
    except Exception as exc:
        logger.warning("GitHub status check failed: %s", type(exc).__name__)
        return local_gh_state()
    node = status.get("github") if isinstance(status, dict) else {}
    if not isinstance(node, dict) or not node.get("linked"):
        return local_gh_state()
    if node.get("missingScopes"):
        state = local_gh_state()
        state.missing_scopes = list(node.get("missingScopes") or [])
        state.error = "github_scope_insufficient"
        return state
    current = local_gh_state()
    if current.linked:
        current.username = str(node.get("username") or current.username)
        current.full_access = not bool(node.get("missingScopes"))
        return current
    return connect(api_url, runtime_token)
