from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ite.cloud.auth import CloudConnectionError, _get_json
from ite.config.config import Config
from ite.config.loader import get_data_dir


def _normalize_version(value: str) -> str:
    return value.strip().lstrip("vV")


def _version_parts(value: str) -> list[int]:
    normalized = _normalize_version(value)
    return [
        int(part) if part.isdigit() else 0
        for part in re.split(r"[-.+]", normalized)
        if part
    ]


def _compare_versions(left: str, right: str) -> int:
    """Compare two version strings. Returns -1 if left < right, 0 if equal, 1 if left > right."""
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    max_len = max(len(left_parts), len(right_parts), 3)
    for i in range(max_len):
        left_value = left_parts[i] if i < len(left_parts) else 0
        right_value = right_parts[i] if i < len(right_parts) else 0
        if left_value < right_value:
            return -1
        if left_value > right_value:
            return 1
    return 0


@dataclass(frozen=True)
class RuntimeUpdateNotice:
    latest_version: str
    required: bool
    title: str
    message: str
    upgrade_command: str
    installer_command: str
    release_url: str | None
    update_required: bool
    current_version: str = ""

    @property
    def notice_key(self) -> str:
        return "|".join(
            [
                self.latest_version,
                str(self.required),
                self.title,
                self.message,
            ]
        )


def current_runtime_version() -> str:
    # Prefer source version (from ite.__version__) over package version
    # This ensures development runs use the correct version
    from ite import __version__
    source_version = __version__.strip().lstrip("vV")
    if source_version:
        return source_version
    # Fallback to package version if source version is empty
    try:
        return version("ite-agent")
    except PackageNotFoundError:
        return source_version or "0.0.0"


def detect_install_method() -> str:
    """Return the install method: 'installer' if installed via curl install.sh, 'pipx' otherwise.
    Defaults to 'installer' when resolution fails — the one-shot installer is the safer fallback."""
    try:
        import ite
        package_path = Path(ite.__file__).resolve()
        managed_root = Path.home() / ".ite"
        if str(package_path).startswith(str(managed_root)):
            return "installer"
        return "pipx"
    except Exception:
        return "installer"


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
    # Always show forced updates
    if notice.update_required:
        return True
    # Soft notifications: always show (decision happens in UI layer)
    return True


def mark_update_notice_seen(notice: RuntimeUpdateNotice) -> None:
    """Track soft notification count for chat feed vs toast decision."""
    if notice.update_required:
        return
    state = _load_state()
    current_key = notice.notice_key
    # Increment the count for this specific notice
    key_count = int(state.get(f"count_{current_key}", 0)) + 1
    state[f"count_{current_key}"] = key_count
    _save_state(state)


def get_notification_type(notice: RuntimeUpdateNotice) -> str:
    """Determine notification type: 'toast' or 'feed' based on count."""
    if notice.update_required:
        return "feed"  # Forced updates use the full screen
    state = _load_state()
    current_key = notice.notice_key
    count = int(state.get(f"count_{current_key}", 0))
    # 1-3 times: toast, 4+ times: chat feed
    return "toast" if count < 3 else "feed"


def _coerce_notice(payload: dict[str, Any], local_version: str) -> RuntimeUpdateNotice | None:
    # Check if updates are enabled
    enabled = payload.get("enabled", False)
    if not enabled:
        return None

    latest = str(payload.get("latestVersion") or "").strip()

    # No latest version defined - nothing to do
    if not latest:
        return None

    # Compare local version with latest
    if _compare_versions(local_version, latest) >= 0:
        # We have latest or newer version, no update needed
        return None

    # Get required flag from backend (true = force update, false = soft notification)
    required = payload.get("updateRequired", False)

    title = str(payload.get("title") or "Update available").strip() or "Update available"
    message = str(payload.get("message") or "").strip()
    upgrade = str(payload.get("upgradeCommand") or "pipx upgrade ite-agent").strip()
    installer = str(payload.get("installerCommand") or "curl -fsSL https://ite.kiishi.space/install.sh | sh").strip()
    release_url = str(payload.get("releaseUrl") or "").strip() or None

    return RuntimeUpdateNotice(
        latest_version=latest,
        required=required,
        title=title,
        message=message,
        upgrade_command=upgrade or "pipx upgrade ite-agent",
        installer_command=installer or "curl -fsSL https://ite.kiishi.space/install.sh | sh",
        release_url=release_url,
        update_required=required,
        current_version=local_version,
    )


def check_runtime_update(config: Config) -> RuntimeUpdateNotice | None:
    base_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if not base_url:
        return None
    local_version = current_runtime_version()
    query = urlencode({"currentVersion": local_version})
    try:
        status, payload = _get_json(f"{base_url}/runtime/version-check?{query}")
    except (CloudConnectionError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if status != 200 or not payload.get("ok"):
        return None
    return _coerce_notice(payload, local_version)
