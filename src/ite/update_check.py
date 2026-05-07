from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ite import __version__
from ite.cloud.auth import CloudConnectionError, _get_json
from ite.config.config import Config
from ite.config.loader import get_data_dir


@dataclass(frozen=True)
class RuntimeUpdateNotice:
    latest_version: str
    minimum_supported_version: str
    severity: str
    title: str
    message: str
    upgrade_command: str
    release_url: str | None
    update_required: bool

    @property
    def notice_key(self) -> str:
        return "|".join(
            [
                self.latest_version,
                self.minimum_supported_version,
                self.severity,
                self.title,
                self.message,
            ]
        )


def current_runtime_version() -> str:
    try:
        return version("ite-agent")
    except PackageNotFoundError:
        return __version__


def _state_path() -> Path:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "runtime_update_state.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def should_show_update_notice(notice: RuntimeUpdateNotice) -> bool:
    if notice.update_required:
        return True
    state = _load_state()
    return str(state.get("last_notice_key") or "") != notice.notice_key


def mark_update_notice_seen(notice: RuntimeUpdateNotice) -> None:
    if notice.update_required:
        return
    _save_state({"last_notice_key": notice.notice_key})


def _coerce_notice(payload: dict[str, Any]) -> RuntimeUpdateNotice | None:
    if not bool(payload.get("updateAvailable") or payload.get("updateRequired")):
        return None
    latest = str(payload.get("latestVersion") or "").strip()
    minimum = str(payload.get("minimumSupportedVersion") or "").strip()
    severity = str(payload.get("severity") or "info").strip().lower()
    title = str(payload.get("title") or "Update available").strip()
    message = str(payload.get("message") or "").strip()
    upgrade = str(payload.get("upgradeCommand") or "pipx upgrade ite-agent").strip()
    release_url = str(payload.get("releaseUrl") or "").strip() or None
    if not latest and not minimum:
        return None
    if severity not in {"info", "recommended", "required"}:
        severity = "info"
    return RuntimeUpdateNotice(
        latest_version=latest,
        minimum_supported_version=minimum,
        severity=severity,
        title=title or "Update available",
        message=message,
        upgrade_command=upgrade or "pipx upgrade ite-agent",
        release_url=release_url,
        update_required=bool(payload.get("updateRequired")),
    )


def check_runtime_update(config: Config) -> RuntimeUpdateNotice | None:
    base_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if not base_url:
        return None
    current = current_runtime_version()
    query = urlencode({"currentVersion": current})
    try:
        status, payload = _get_json(f"{base_url}/runtime/version-check?{query}")
    except CloudConnectionError:
        return None
    if status != 200 or not payload.get("ok"):
        return None
    return _coerce_notice(payload)
