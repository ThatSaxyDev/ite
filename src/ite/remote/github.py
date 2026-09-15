from __future__ import annotations

import json
import logging
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import certifi
import yaml

logger = logging.getLogger(__name__)

_GH_HOST = "github.com"
_HTTP_TIMEOUT_SEC = 10
_CMD_TIMEOUT_SEC = 30
_CREDENTIALS_FILE_MODE = 0o600
_CONFIG_FILE_MODE = 0o600
_CONFIG_DIR_MODE = 0o700

# gh prefers these over hosts.yml. The supervisor hands a child the host's whole
# environment, so on a multi-tenant machine an inherited token here would make
# every tenant act as whoever that token belongs to. They are dropped instead.
_ENV_TOKEN_KEYS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
)

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class BrokerError(RuntimeError):
    """A structured error from the cloud token broker.

    The broker answers with `{ok: false, error: {code, message, details}}`, which
    is what lets the runtime tell "you have not linked GitHub" apart from "your
    link is missing scopes" apart from "the request failed".
    """

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any]):
        super().__init__(message or code or f"broker error {status}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details


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


def _gh_config_dir() -> Path:
    """Where gh will read and write its config, honouring its own resolution.

    gh looks in `GH_CONFIG_DIR`, then `$XDG_CONFIG_HOME/gh`, then `~/.config/gh`.
    The supervisor sets `XDG_CONFIG_HOME` per tenant, so the middle case is the
    one that applies on a managed host — reading `~/.config/gh` there would look
    at a directory gh never writes.
    """
    override = str(os.environ.get("GH_CONFIG_DIR") or "").strip()
    if override:
        return Path(override)
    xdg = str(os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "gh"
    return _home() / ".config" / "gh"


def _hosts_path() -> Path:
    return _gh_config_dir() / "hosts.yml"


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in _ENV_TOKEN_KEYS:
        env.pop(key, None)
    return env


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
            env=_subprocess_env(),
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


def _load_hosts() -> dict[str, Any]:
    try:
        text = _hosts_path().read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = yaml.safe_load(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _hosts_entry() -> dict[str, Any]:
    data = _load_hosts()
    entry = data.get(_GH_HOST)
    return entry if isinstance(entry, dict) else {}


def _hosts_login() -> str:
    """The active github.com login recorded in gh's own config file."""
    entry = _hosts_entry()
    login = str(entry.get("user") or "").strip()
    if login:
        return login
    users = entry.get("users")
    if isinstance(users, dict):
        for candidate in users:
            name = str(candidate or "").strip()
            if name:
                return name
    return ""


def _hosts_token(login: str) -> str:
    users = _hosts_entry().get("users")
    if not isinstance(users, dict) or not login:
        return ""
    record = users.get(login)
    if isinstance(record, dict):
        return str(record.get("oauth_token") or "").strip()
    # Legacy flat form: `users: {login: token}`.
    if isinstance(record, str):
        return record.strip()
    return ""


def _write_hosts(login: str, token: str) -> None:
    """Persist a token for `login` the way gh itself stores it without a keyring.

    Writes `users.<login>.oauth_token` and marks that login active, leaving every
    other host entry untouched. Owner-only, atomic replace.
    """
    path = _hosts_path()
    data = _load_hosts()
    entry = data.get(_GH_HOST)
    if not isinstance(entry, dict):
        entry = {}
    users = entry.get("users")
    if not isinstance(users, dict):
        users = {}
    users[login] = {"oauth_token": token}
    entry["users"] = users
    entry["user"] = login
    entry.setdefault("git_protocol", "https")
    data[_GH_HOST] = entry

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, _CONFIG_DIR_MODE)
    except OSError:
        pass
    text = yaml.safe_dump(data, default_flow_style=False, sort_keys=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, _CONFIG_FILE_MODE)
    tmp.replace(path)
    try:
        os.chmod(path, _CONFIG_FILE_MODE)
    except OSError:
        pass


def _clear_hosts() -> None:
    """Forget this tenant's GitHub identity, keeping any other configured host."""
    path = _hosts_path()
    data = _load_hosts()
    if _GH_HOST not in data:
        return
    data.pop(_GH_HOST, None)
    try:
        if not data:
            path.unlink()
            return
        text = yaml.safe_dump(data, default_flow_style=False, sort_keys=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, _CONFIG_FILE_MODE)
        tmp.replace(path)
    except OSError:
        pass


def _gh_active_account() -> str:
    """The login gh itself considers active, or "" when there is none.

    Uses `--json`, which exits 0 even when an account is broken. The plain
    `gh auth status` exits 1 if *any* account on the host has a problem, so a
    stale entry elsewhere would make a healthy tenant look signed out.
    """
    result = _run("gh", "auth", "status", "--json", "hosts", "-h", _GH_HOST)
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout or "{}")
        except ValueError:
            payload = None
        hosts = payload.get("hosts") if isinstance(payload, dict) else None
        entries = hosts.get(_GH_HOST) if isinstance(hosts, dict) else None
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("active"):
                    return str(entry.get("login") or "").strip()
            return ""
    # Older gh, or an unexpected failure: the config file is the fallback.
    return _hosts_login()


def local_gh_state() -> GithubState:
    """Local-only state: is `gh` present and is anyone logged in?"""
    state = GithubState(gh_ready=gh_available())
    if not state.gh_ready:
        state.error = "github_cli_missing"
        return state
    login = _gh_active_account()
    if login:
        state.linked = True
        state.username = login
        return state
    state.error = "github_not_linked"
    return state


def _broker_error(exc: urllib.error.HTTPError) -> BrokerError:
    try:
        body = json.loads(exc.read().decode("utf-8") or "{}")
    except Exception:
        body = {}
    node = body.get("error") if isinstance(body, dict) else None
    code = ""
    message = ""
    details: dict[str, Any] = {}
    if isinstance(node, dict):
        code = str(node.get("code") or "")
        message = str(node.get("message") or "")
        raw = node.get("details")
        if isinstance(raw, dict):
            details = raw
    return BrokerError(exc.code, code, message or str(exc.reason or ""), details)


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
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SEC, context=_SSL_CONTEXT) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise _broker_error(exc) from exc


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
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SEC, context=_SSL_CONTEXT) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise _broker_error(exc) from exc


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


def _install_token(login: str, token: str) -> str:
    """Put the token where gh will actually use it; returns the method used.

    `gh auth login --with-token` is tried first because it lets gh pick its own
    storage backend and bookkeeping. It also enforces a minimum scope set
    (`repo`, `read:org`, `gist`) against the granted scopes verbatim — and GitHub
    normalises scopes, dropping sub-scopes such as `read:org` when a broader
    grant like `admin:org` is present. A perfectly valid token can therefore be
    rejected, so a direct `hosts.yml` write is the fallback that makes
    materialization reliable on a headless host with no keyring.
    """
    result = _run(
        "gh", "auth", "login", "--with-token", "-h", _GH_HOST, input_text=token.strip() + "\n"
    )
    if result.returncode == 0:
        return "gh-auth-login"
    logger.warning(
        "gh auth login failed: %s (falling back to a direct hosts.yml write)",
        result.stderr.strip()[-300:],
    )
    _write_hosts(login, token)
    return "hosts-yml"


def _clear_local_credentials() -> None:
    """Remove this tenant's GitHub credentials from the machine."""
    if gh_available():
        _run("gh", "auth", "logout", "-h", _GH_HOST)
    _clear_hosts()
    _clear_credentials_file()


def _state_from_broker_error(state: GithubState, exc: BrokerError) -> GithubState:
    if exc.code == "github_not_linked":
        state.error = "github_not_linked"
        return state
    if exc.code == "github_scope_insufficient":
        state.missing_scopes = [
            str(scope) for scope in (exc.details.get("missingScopes") or []) if str(scope).strip()
        ]
        state.error = "github_scope_insufficient"
        return state
    logger.warning(
        "GitHub broker token fetch failed: %s (%s)", exc.code or "unknown", exc.status
    )
    state.error = "github_token_fetch_failed"
    return state


def connect(api_url: str, runtime_token: str) -> GithubState:
    """Fetch the broker token and materialize it into the tenant HOME.

    Idempotent: when the tenant already holds the granted token it reports the
    linked state without rewriting anything, so the periodic resync is cheap.
    """
    state = GithubState(gh_ready=gh_available())
    if not state.gh_ready:
        state.error = "github_cli_missing"
        return state
    try:
        payload = broker_token(api_url, runtime_token)
    except BrokerError as exc:
        return _state_from_broker_error(state, exc)
    except Exception as exc:
        logger.warning("GitHub broker token fetch failed: %s", type(exc).__name__)
        state.error = "github_token_fetch_failed"
        return state
    github = payload.get("github") if isinstance(payload, dict) else None
    token = str((github or {}).get("token") or "").strip() if isinstance(github, dict) else ""
    if not token:
        state.error = "github_not_linked"
        return state
    account_id = str((github or {}).get("accountId") or "") if isinstance(github, dict) else ""

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
        username = _hosts_login() or "oauth"

    state.account_id = account_id
    state.username = username
    missing = [
        str(scope) for scope in ((node or {}).get("missingScopes") or []) if str(scope).strip()
    ]
    state.missing_scopes = missing
    state.full_access = not missing

    if _hosts_token(username) == token and _hosts_login() == username:
        # Already materialized: nothing to rewrite.
        state.linked = True
        return state

    method = _install_token(username, token)
    _run("git", "config", "--global", "credential.helper", "store")
    _write_credentials_file(username, token)
    _run("git", "config", "--global", "user.name", name or username)
    # Email default: use the GitHub primary email as-is, no noreply forcing.
    if email:
        _run("git", "config", "--global", "user.email", email)

    # Trust only gh's own view of the account. A written hosts.yml that gh will
    # not read (for example when a keyring is active) would otherwise be
    # reported as linked while every gh command still fails.
    active = _gh_active_account()
    if active:
        state.username = active
        state.linked = True
        return state
    logger.warning("GitHub token was not adopted by gh (method=%s)", method)
    state.error = "github_token_write_failed"
    return state


def disconnect(api_url: str = "", runtime_token: str = "") -> GithubState:
    _clear_local_credentials()
    if api_url and runtime_token:
        try:
            broker_unlink(api_url, runtime_token)
        except Exception as exc:
            logger.warning("GitHub broker unlink failed: %s", type(exc).__name__)
    return local_gh_state()


def sync_if_linked(api_url: str, runtime_token: str) -> GithubState:
    """Converge the tenant HOME on whatever the cloud currently holds.

    Runs on child boot and periodically. It is the recovery path for a link
    created, upgraded, switched to another GitHub account, or revoked while this
    child was stopped, disconnected, or not yet provisioned — so the machine
    always acts as the account the phone is signed in with, and stops acting as
    one the user has disconnected.
    """
    try:
        status = broker_status(api_url, runtime_token)
    except BrokerError as exc:
        return _state_from_broker_error(local_gh_state(), exc)
    except Exception as exc:
        logger.warning("GitHub status check failed: %s", type(exc).__name__)
        return local_gh_state()
    node = status.get("github") if isinstance(status, dict) else {}
    if not isinstance(node, dict) or not node.get("linked"):
        current = local_gh_state()
        if current.linked:
            logger.info("GitHub is no longer linked; clearing local credentials")
            _clear_local_credentials()
            return local_gh_state()
        return current
    if node.get("missingScopes"):
        state = local_gh_state()
        state.missing_scopes = [
            str(scope) for scope in (node.get("missingScopes") or []) if str(scope).strip()
        ]
        state.error = "github_scope_insufficient"
        return state
    return connect(api_url, runtime_token)
