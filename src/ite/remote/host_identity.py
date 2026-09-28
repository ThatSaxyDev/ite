from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from .security import remote_storage_dir, runtime_label

_HOST_FILE = "host.json"


@dataclass(frozen=True)
class HostIdentity:
    """The machine's long-lived cloud identity.

    This is deliberately separate from a user's ``cloud_session.json``: the host
    authenticates as the machine, never as a person. Per the build contract the
    signed-in user's token must never be stored on the VPS.
    """

    host_id: str
    host_token: str
    api_url: str
    name: str
    platform: str


def host_identity_path() -> Path:
    return remote_storage_dir() / _HOST_FILE


def platform_label() -> str:
    return f"{sys.platform}-{platform.machine()}".strip("-")


def load_host_identity() -> HostIdentity | None:
    path = host_identity_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    host_id = str(data.get("host_id") or "").strip()
    host_token = str(data.get("host_token") or "").strip()
    api_url = str(data.get("api_url") or "").strip().rstrip("/")
    if not host_id or not host_token or not api_url:
        return None
    return HostIdentity(
        host_id=host_id,
        host_token=host_token,
        api_url=api_url,
        name=str(data.get("name") or runtime_label()),
        platform=str(data.get("platform") or platform_label()),
    )


def save_host_identity(identity: HostIdentity) -> None:
    path = host_identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "host_id": identity.host_id,
            "host_token": identity.host_token,
            "api_url": identity.api_url,
            "name": identity.name,
            "platform": identity.platform,
        },
        indent=2,
    )
    # Write owner-only, then replace atomically so a crash cannot leave a partial
    # credential file behind.
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)


def clear_host_identity() -> None:
    path = host_identity_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
