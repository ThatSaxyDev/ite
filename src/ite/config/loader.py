import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import keyring
import tomli
from platformdirs import user_config_dir, user_data_dir
from pydantic import ValidationError

from ite.config.config import ApprovalPolicy, Config, MCPServerConfig
from ite.utils.errors import ConfigError

CONFIG_FILE_NAME = "config.toml"
SECRETS_FILE_NAME = "secrets.toml"
AGENTS_MD_FILE = "AGENTS.md"
AGENTS_OVERRIDE_FILE = "AGENTS.override.md"

# Fallback filenames to check when AGENTS.md doesn't exist (in order of preference)
AGENTS_FALLBACK_FILENAMES = [
    ".agents.md",
    "CLAUDE.md",
    "claude.md",
    "CURSOR.md",
    "cursor.md",
    "TEAM_GUIDE.md",
    "CONTRIBUTING.md",
]

# Maximum combined size for AGENTS.md files (32 KiB default)
AGENTS_MAX_BYTES = 32 * 1024
AGENTS_STALE_AFTER_DAYS = 15

WORKSPACE_DIR_NAME = ".ite"
SAVED_CUSTOM_PROVIDERS_TABLE = "saved_custom_providers"

# Theme storage
THEME_FILE_NAME = "theme.json"

DEFAULT_PROJECT_CONFIG = """# Workspace-level ITE config
# Add overrides here (model, hooks, mcp servers, etc.)
#
# Hooks are disabled by default for fast/safe baseline behavior.
hooks_enabled = false
#
# Example:
# [model]
# name = "gpt-4o-mini"
"""

DEFAULT_SECURITY_SUBAGENT = """name = "security_auditor"
description = "Audits code for security vulnerabilities"
allowed_tools = ["read_file", "grep", "list_dir"]

goal_prompt = \"\"\"
You are a security auditing expert. Analyze the code for common vulnerabilities
like SQL injection, XSS, and hardcoded secrets.
\"\"\"
"""

logger = logging.getLogger(__name__)
_TOML_TABLE_RE = re.compile(r"^\s*\[(.+?)\]\s*$")
_TOML_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class WorkspaceAgentsRecommendation:
    reason: str
    command: str
    workspace: Path
    file_path: Path | None = None
    age_days: int | None = None

    def notice_title(self) -> str:
        return "Hint"

    def notice_message(self) -> str:
        workspace_name = self.workspace.name or str(self.workspace)
        if self.reason == "missing":
            return (
                f"No workspace instruction file was found for {workspace_name}. "
                f"Run {self.command} to generate one before exploring the repo."
            )
        age = f"{self.age_days} day(s)" if self.age_days is not None else "a while"
        return (
            f"The workspace instruction file for {workspace_name} looks stale "
            f"({age} old). Run {self.command} to regenerate it."
        )


def get_config_dir() -> Path:
    return Path(user_config_dir("ite"))


def get_data_dir() -> Path:
    return Path(user_data_dir("ite"))


def get_system_config_path() -> Path:
    return get_config_dir() / CONFIG_FILE_NAME


def get_system_secrets_path() -> Path:
    return get_config_dir() / SECRETS_FILE_NAME


def get_theme_path() -> Path:
    """Path to the stored theme preference file in data dir."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / THEME_FILE_NAME


def get_workspace_secrets_path(cwd: Path) -> Path:
    return cwd.resolve() / WORKSPACE_DIR_NAME / SECRETS_FILE_NAME


def _parse_toml(path: Path):
    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except tomli.TOMLDecodeError as e:
        raise ConfigError(
            f"Invalid TOML file in {path}: {e}", config_file=str(path)
        ) from e
    except (OSError, IOError) as e:
        raise ConfigError(
            f"Failed to read TOML file in {path}: {e}", config_file=str(path)
        ) from e


def ensure_workspace_layout(cwd: Path | None = None) -> Path:
    """Create a starter .ite workspace folder when missing."""
    workspace = (cwd or Path.cwd()).resolve()
    ite_dir = workspace / WORKSPACE_DIR_NAME
    tools_dir = ite_dir / "tools"
    subagents_dir = ite_dir / "subagents"
    config_file = ite_dir / CONFIG_FILE_NAME
    security_subagent_file = subagents_dir / "security_auditor.toml"

    ite_dir.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)
    subagents_dir.mkdir(parents=True, exist_ok=True)

    if not config_file.exists():
        config_file.write_text(DEFAULT_PROJECT_CONFIG + "\n", encoding="utf-8")

    if not security_subagent_file.exists():
        security_subagent_file.write_text(
            DEFAULT_SECURITY_SUBAGENT + "\n", encoding="utf-8"
        )

    return ite_dir


def _get_project_config(cwd: Path) -> Path | None:
    current = cwd.resolve()
    agent_dir = current / WORKSPACE_DIR_NAME

    if agent_dir.is_dir():
        config_file = agent_dir / CONFIG_FILE_NAME
        if config_file.is_file():
            return config_file

    return None


AGENTS_OVERRIDE_FILE = "AGENTS.override.md"


def _load_agents_file(path: Path) -> tuple[Path, str] | None:
    """Load a single AGENTS.md file, return None if not found/readable."""
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        return (path, content)
    except (OSError, UnicodeDecodeError):
        return None


def _get_agents_md_at_path(path: Path) -> list[tuple[Path, str]]:
    """
    Get AGENTS.md files at a specific path.
    Checks for override first: AGENTS.override.md > AGENTS.md
    """
    files: list[tuple[Path, str]] = []

    # Check for override file first (higher precedence at this level)
    override_file = path / AGENTS_OVERRIDE_FILE
    override_result = _load_agents_file(override_file)
    if override_result:
        files.append(override_result)
        return files  # Override takes precedence, skip regular AGENTS.md

    # Check for regular AGENTS.md
    agents_md_file = path / AGENTS_MD_FILE
    agents_result = _load_agents_file(agents_md_file)
    if agents_result:
        files.append(agents_result)
        return files  # Found main file, skip fallbacks

    # Check fallback filenames (in order, first wins)
    for fallback_name in AGENTS_FALLBACK_FILENAMES:
        fallback_file = path / fallback_name
        fallback_result = _load_agents_file(fallback_file)
        if fallback_result:
            files.append(fallback_result)
            return files  # First fallback found wins

    return files


def get_workspace_agents_recommendation(
    cwd: Path,
    *,
    now: datetime | None = None,
    stale_after_days: int = AGENTS_STALE_AFTER_DAYS,
) -> WorkspaceAgentsRecommendation | None:
    """Return a deterministic /init suggestion for the active workspace."""
    workspace = cwd.resolve()
    workspace_files = _get_agents_md_at_path(workspace)
    if not workspace_files:
        return WorkspaceAgentsRecommendation(
            reason="missing",
            command="/init",
            workspace=workspace,
        )

    file_path, _content = workspace_files[0]
    try:
        modified_at = datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=timezone.utc,
        )
    except OSError:
        return None

    current_time = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    file_age = current_time - modified_at
    if file_age < timedelta(days=max(stale_after_days, 1)):
        return None

    return WorkspaceAgentsRecommendation(
        reason="stale",
        command="/init --force",
        workspace=workspace,
        file_path=file_path,
        age_days=max(file_age.days, 1),
    )


def _get_agents_md_files(cwd: Path) -> list[tuple[Path, str]]:
    """
    Collect all AGENTS.md files from global config, then from root up to cwd.
    Returns list of (path, content) tuples, ordered from global -> root -> cwd
    (least to most specific). Most specific (deepest) files take precedence when merging.

    At each level, AGENTS.override.md takes precedence over AGENTS.md.
    """
    current = cwd.resolve()
    files: list[tuple[Path, str]] = []

    # First: Global AGENTS.md from ~/.config/ite/
    global_path = get_data_dir()
    files.extend(_get_agents_md_at_path(global_path))

    # Also check ~/.agents/ as alternative global location
    home = Path.home()
    alt_global_path = home / ".agents"
    if alt_global_path != global_path:
        alt_files = _get_agents_md_at_path(alt_global_path)
        # Avoid duplicates if same file
        for f in alt_files:
            if f[0] not in [existing[0] for existing in files]:
                files.append(f)

    # Walk from root down to cwd
    paths_to_check: list[Path] = []
    while current != current.parent:
        paths_to_check.append(current)
        current = current.parent
    paths_to_check.append(current)  # Root

    # Reverse so we go root -> ... -> cwd
    for path in reversed(paths_to_check):
        files.extend(_get_agents_md_at_path(path))

    return files


def _merge_agents_md_instructions(files: list[tuple[Path, str]]) -> str | None:
    """
    Merge AGENTS.md content with precedence: most specific (deepest) overrides parent.
    Returns None if no files found.

    Enforces AGENTS_MAX_BYTES (32 KiB) combined size limit - truncates silently when exceeded.
    Later files (cwd files) are preserved when truncating, earlier ones are dropped.
    """
    if not files:
        return None

    header = """[AGENTS.md Instructions]

Precedence: files are listed from most specific to least specific. Use the first applicable file as the primary grounding for questions about the current workspace or codebase. Parent and global files provide inherited constraints and background only; do not summarize them as the main project when a more specific file applies.
"""

    parts: list[str] = [header]
    current_size = len(header.encode("utf-8"))
    truncated_files: list[Path] = []

    # Files are ordered global -> root -> ... -> cwd. Process in reverse so the
    # most specific instructions are both preserved and shown first.
    for index, (file_path, content) in enumerate(reversed(files), start=1):
        separator = f"## Priority {index}: {file_path}\n\n"
        section = separator + content
        section_bytes = len(section.encode("utf-8"))

        if current_size + section_bytes > AGENTS_MAX_BYTES:
            truncated_files.append(file_path)
            continue

        parts.append(section)
        current_size += section_bytes

    if truncated_files:
        logger.warning(
            f"AGENTS.md files exceeded {AGENTS_MAX_BYTES} byte limit. "
            f"Skipped: {[str(f) for f in truncated_files]}"
        )

    return "\n\n".join(parts)


def _merge_dicts(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _remove_persisted_cloud_api_url(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    normalized.pop("cloud_api_url", None)
    return normalized


def load_config(
    cwd: Path | None,
) -> Config:
    cwd = cwd or Path.cwd()

    system_path = get_system_config_path()

    config_dict: dict[str, Any] = {}
    system_config_dict: dict[str, Any] = {}

    if system_path.is_file():
        try:
            system_config_dict = _parse_toml(system_path)
            normalized_system_config = _remove_persisted_cloud_api_url(
                system_config_dict
            )
            if normalized_system_config != system_config_dict:
                system_config_dict = normalized_system_config
                lines = _render_system_config(system_config_dict)
                system_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                os.chmod(system_path, 0o600)
            config_dict = system_config_dict.copy()
        except ConfigError:
            logger.warning(f"Skipping invalid system config: {system_path}")

    project_path = _get_project_config(cwd)

    if project_path:
        try:
            project_config_dict = _parse_toml(project_path)
            project_config_dict = _remove_persisted_cloud_api_url(project_config_dict)
            config_dict = _merge_dicts(config_dict, project_config_dict)
        except ConfigError:
            logger.warning(f"Skipping invalid project config: {project_path}")

    config_dict = _merge_mcp_secrets_into_config(
        config_dict,
        _load_mcp_secrets(get_workspace_secrets_path(cwd)),
    )
    config_dict = _merge_mcp_client_credentials_secrets_into_config(
        config_dict,
        _load_mcp_client_credentials_secrets(get_workspace_secrets_path(cwd)),
    )

    # Approval policy is global user preference and should be consistent
    # across projects/sessions.
    if "approval" in system_config_dict:
        config_dict["approval"] = system_config_dict["approval"]

    if "cwd" not in config_dict:
        config_dict["cwd"] = cwd

    if "developer_instructions" not in config_dict:
        agents_md_files = _get_agents_md_files(cwd)
        merged_instructions = _merge_agents_md_instructions(agents_md_files)
        if merged_instructions:
            config_dict["developer_instructions"] = merged_instructions

    config_dict = _drop_invalid_mcp_servers(config_dict)

    try:
        config = Config(**config_dict)
    except ValidationError as e:
        raise ConfigError(f"Invalid configuration: {e}") from e
    except ConfigError as e:
        raise ConfigError(f"Invalid configuration: {e}") from e

    return config


def _drop_invalid_mcp_servers(config_dict: dict[str, Any]) -> dict[str, Any]:
    raw_servers = config_dict.get("mcp_servers")
    if not isinstance(raw_servers, dict):
        return config_dict

    valid_servers: dict[str, Any] = {}
    for name, raw in raw_servers.items():
        if not isinstance(raw, dict):
            logger.warning(
                "Skipping invalid MCP server '%s': entry must be a table", name
            )
            continue
        try:
            validated = MCPServerConfig(**raw)
        except Exception as exc:
            logger.warning("Skipping invalid MCP server '%s': %s", name, exc)
            continue
        valid_servers[str(name)] = validated.model_dump(exclude_defaults=True)

    result = dict(config_dict)
    result["mcp_servers"] = valid_servers
    return result


def save_system_config(
    api_key: str,
    base_url: str,
    model_name: str,
    *,
    context_window: int | None = None,
    context_window_source: str | None = None,
    source_kind: str | None = None,
    cloud_auth_enabled: bool | None = None,
    cloud_api_url: str | None = None,
    cloud_client_id: str | None = None,
) -> Path:
    """Save credentials, model, and optional cloud settings to the system config."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / CONFIG_FILE_NAME

    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            existing = _parse_toml(config_path)
        except ConfigError:
            existing = {}

    existing["api_key"] = api_key
    existing["base_url"] = base_url
    model_config = dict(existing.get("model", {}) or {})
    model_config["name"] = model_name
    if context_window is not None and context_window > 0:
        model_config["context_window"] = int(context_window)
    else:
        model_config.pop("context_window", None)
    if context_window_source:
        model_config["context_window_source"] = str(context_window_source).strip()
    else:
        model_config.pop("context_window_source", None)
    if source_kind:
        model_config["source_kind"] = str(source_kind).strip()
    else:
        model_config.pop("source_kind", None)
    existing["model"] = model_config

    if cloud_auth_enabled is not None:
        existing["cloud_auth_enabled"] = cloud_auth_enabled
    existing.pop("cloud_api_url", None)
    if cloud_client_id is not None:
        existing["cloud_client_id"] = cloud_client_id

    lines = _render_system_config(existing)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)
    logger.info("Saved system config to %s", config_path)
    return config_path


def load_saved_custom_provider() -> dict[str, dict[str, Any]]:
    """Load all saved BYOK/custom provider profiles. Returns keyed by model_name."""
    config_path = get_system_config_path()
    if not config_path.is_file():
        return {}

    try:
        existing = _parse_toml(config_path)
    except ConfigError:
        return {}

    raw = existing.get(SAVED_CUSTOM_PROVIDERS_TABLE)
    if not isinstance(raw, dict):
        return {}

    result: dict[str, dict[str, str]] = {}
    for model_name, values in raw.items():
        if not isinstance(values, dict):
            continue
        base_url = str(values.get("base_url") or "").strip()
        api_key = str(values.get("api_key") or "").strip()
        normalized = str(model_name or "").strip()
        if not normalized or not base_url or not api_key:
            continue
        context_window = values.get("context_window")
        parsed_context_window = None
        if isinstance(context_window, int) and context_window > 0:
            parsed_context_window = context_window
        elif isinstance(context_window, str) and context_window.strip().isdigit():
            parsed_context_window = int(context_window.strip())
        result[normalized] = {
            "base_url": base_url,
            "api_key": api_key,
            "model_name": normalized,
            "context_window": parsed_context_window,
            "context_window_source": str(values.get("context_window_source") or "").strip()
            or None,
        }
    return result


def save_saved_custom_provider(
    *,
    api_key: str,
    base_url: str,
    model_name: str,
    context_window: int | None = None,
    context_window_source: str | None = None,
) -> Path:
    """Add or update a BYOK/custom provider profile. Others are preserved."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_system_config_path()

    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            existing = _parse_toml(config_path)
        except ConfigError:
            existing = {}

    providers: dict[str, Any] = dict(existing.get(SAVED_CUSTOM_PROVIDERS_TABLE) or {})
    provider_payload: dict[str, Any] = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": model_name,
    }
    if context_window is not None and context_window > 0:
        provider_payload["context_window"] = int(context_window)
    if context_window_source:
        provider_payload["context_window_source"] = str(context_window_source).strip()
    providers[model_name] = provider_payload
    existing[SAVED_CUSTOM_PROVIDERS_TABLE] = providers

    lines = _render_system_config(existing)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)
    logger.info("Saved custom provider profile %s to %s", model_name, config_path)
    return config_path


def remove_saved_custom_provider(*, model_name: str) -> Path:
    """Remove a saved custom provider profile by model name."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_system_config_path()

    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            existing = _parse_toml(config_path)
        except ConfigError:
            existing = {}

    providers: dict[str, Any] = dict(existing.get(SAVED_CUSTOM_PROVIDERS_TABLE) or {})
    removed = providers.pop(model_name, None) is not None
    if not removed:
        return config_path

    existing[SAVED_CUSTOM_PROVIDERS_TABLE] = providers
    lines = _render_system_config(existing)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)
    logger.info("Removed custom provider profile %s from %s", model_name, config_path)
    return config_path


def save_cloud_settings(
    *,
    enabled: bool | None = None,
    api_url: str | None = None,
    client_id: str | None = None,
) -> Path:
    """Persist iTE Cloud settings in the system-level config file."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_system_config_path()

    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            existing = _parse_toml(config_path)
        except ConfigError:
            existing = {}

    if enabled is not None:
        existing["cloud_auth_enabled"] = enabled
    existing.pop("cloud_api_url", None)
    if client_id is not None:
        existing["cloud_client_id"] = client_id

    lines = _render_system_config(existing)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)
    logger.info("Saved iTE Cloud settings to %s", config_path)
    return config_path


def save_onboarding_settings(*, completed: bool) -> Path:
    """Persist first-run onboarding completion in the system config file."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_system_config_path()

    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            existing = _parse_toml(config_path)
        except ConfigError:
            existing = {}

    existing["onboarding_completed"] = completed

    lines = _render_system_config(existing)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)
    logger.info("Saved onboarding settings to %s", config_path)
    return config_path


def save_voice_settings(
    *,
    enabled: bool | None = None,
    groq_api_key: str | None = None,
) -> Path:
    """Persist voice typing settings in the system-level config file."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_system_config_path()

    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            existing = _parse_toml(config_path)
        except ConfigError:
            existing = {}

    voice = dict(existing.get("voice", {}) or {})
    if enabled is not None:
        voice["enabled"] = enabled
    if groq_api_key is not None:
        voice["groq_api_key"] = groq_api_key
    existing["voice"] = voice

    lines = _render_system_config(existing)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)
    logger.info("Saved voice settings to %s", config_path)
    return config_path


def _render_system_config(config: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    top_level_keys = [
        "api_key",
        "base_url",
        "approval",
        "cloud_auth_enabled",
        "cloud_client_id",
        "onboarding_completed",
        "hooks_enabled",
        "max_turns",
        "debug",
    ]
    rendered_keys: set[str] = set()

    for key in top_level_keys:
        if key in config:
            lines.append(f"{key} = {_toml_value(config[key])}")
            rendered_keys.add(key)

    for key, value in config.items():
        if key in rendered_keys or isinstance(value, dict):
            continue
        lines.append(f"{key} = {_toml_value(value)}")

    if "model" in config and isinstance(config["model"], dict):
        if lines:
            lines.append("")
        lines.append("[model]")
        for key, value in config["model"].items():
            lines.append(f"{key} = {_toml_value(value)}")

    saved_custom_providers = config.get(SAVED_CUSTOM_PROVIDERS_TABLE)
    if isinstance(saved_custom_providers, dict):
        lines.append("")
        lines.append(f"[{SAVED_CUSTOM_PROVIDERS_TABLE}]")
        for mname, vals in saved_custom_providers.items():
            if not isinstance(vals, dict):
                continue
            lines.append("")
            lines.append(f"  [{SAVED_CUSTOM_PROVIDERS_TABLE}.{_toml_key(mname)}]")
            for key, value in vals.items():
                lines.append(f"  {key} = {_toml_value(value)}")

    for table_name in ("sandbox", "shell_environment"):
        table = config.get(table_name)
        if isinstance(table, dict):
            if lines:
                lines.append("")
            lines.append(f"[{table_name}]")
            for key, value in table.items():
                lines.append(f"{key} = {_toml_value(value)}")

    voice = config.get("voice")
    if isinstance(voice, dict):
        if lines:
            lines.append("")
        lines.append("[voice]")
        for key, value in voice.items():
            lines.append(f"{key} = {_toml_value(value)}")

    mcp_servers = config.get("mcp_servers")
    if isinstance(mcp_servers, dict):
        for server, server_config in mcp_servers.items():
            if not isinstance(server_config, dict):
                continue
            if lines:
                lines.append("")
            lines.extend(
                _render_mcp_server_section(str(server), server_config).splitlines()
            )

    hooks = config.get("hooks")
    if isinstance(hooks, list):
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            if lines:
                lines.append("")
            lines.append("[[hooks]]")
            for key, value in hook.items():
                lines.append(f"{key} = {_toml_value(value)}")

    return lines


def save_global_approval_mode(mode: ApprovalPolicy | str) -> Path:
    """Persist global approval mode in system config.toml."""
    value = mode.value if isinstance(mode, ApprovalPolicy) else str(mode).strip()
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_system_config_path()

    if not config_path.exists():
        config_path.write_text(f'approval = "{value}"\n', encoding="utf-8")
        os.chmod(config_path, 0o600)
        return config_path

    original = config_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    replaced = False
    out_lines: list[str] = []
    for line in lines:
        if (
            line.strip().startswith("approval")
            and "=" in line
            and not line.strip().startswith("#")
        ):
            out_lines.append(f'approval = "{value}"')
            replaced = True
        else:
            out_lines.append(line)

    if not replaced:
        # Keep it top-level and near the top for discoverability.
        insert_at = 0
        while insert_at < len(out_lines) and out_lines[insert_at].strip().startswith(
            "#"
        ):
            insert_at += 1
        out_lines.insert(insert_at, f'approval = "{value}"')

    config_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)
    return config_path


def save_workspace_hooks_enabled(cwd: Path, enabled: bool) -> Path:
    """Persist hooks_enabled in workspace .ite/config.toml."""
    workspace = cwd.resolve()
    config_path = workspace / WORKSPACE_DIR_NAME / CONFIG_FILE_NAME

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(f"hooks_enabled = {str(enabled).lower()}\n", encoding="utf-8")
        return config_path

    original = config_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    replaced = False
    out_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("hooks_enabled") and "=" in stripped and not stripped.startswith("#"):
            out_lines.append(f"hooks_enabled = {str(enabled).lower()}")
            replaced = True
        else:
            out_lines.append(line)

    if not replaced:
        # Insert after comments at the top for discoverability.
        insert_at = 0
        while insert_at < len(out_lines) and out_lines[insert_at].strip().startswith("#"):
            insert_at += 1
        out_lines.insert(insert_at, f"hooks_enabled = {str(enabled).lower()}")

    config_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return config_path


def save_theme(theme: str) -> Path:
    """Persist the selected UI theme to a JSON file in data dir."""
    theme_path = get_theme_path()
    theme_path.write_text(json.dumps({"theme": theme}), encoding="utf-8")
    return theme_path


def load_theme() -> str | None:
    """Load the saved UI theme from data dir, or None if not set."""
    theme_path = get_theme_path()
    if not theme_path.exists():
        return None
    try:
        data = json.loads(theme_path.read_text(encoding="utf-8"))
        theme = data.get("theme")
        return str(theme) if theme else None
    except Exception:
        return None


def save_mcp_server_config(
    *,
    cwd: Path | None,
    scope: str,
    server: str,
    config: dict[str, Any],
) -> Path:
    normalized = MCPServerConfig(**config).model_dump(exclude_defaults=True)
    for secret_field in (
        "client_credentials_client_id",
        "client_credentials_client_secret",
    ):
        normalized.pop(secret_field, None)
    path = _mcp_config_path_for_scope(cwd, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    table_name = f"mcp_servers.{server}"
    remaining = _remove_toml_table(existing, table_name).rstrip()
    section = _render_mcp_server_section(server, normalized)
    content = f"{remaining}\n\n{section}\n" if remaining else f"{section}\n"
    path.write_text(content, encoding="utf-8")
    if path == get_system_config_path():
        os.chmod(path, 0o600)
    return path


def load_mcp_server_config(
    *,
    cwd: Path | None,
    scope: str,
    server: str,
) -> dict[str, Any] | None:
    path = _mcp_config_path_for_scope(cwd, scope)
    if not path.exists():
        return None
    try:
        raw = _parse_toml(path)
    except ConfigError:
        return None
    mcp_servers = raw.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        return None
    server_cfg = mcp_servers.get(server)
    return dict(server_cfg) if isinstance(server_cfg, dict) else None


def _mcp_config_path_for_scope(cwd: Path | None, scope: str) -> Path:
    normalized = str(scope or "workspace").strip().lower()
    if normalized == "global":
        return get_system_config_path()
    if cwd is None:
        raise ValueError("Workspace cwd is required for workspace-scoped MCP config")
    return ensure_workspace_layout(cwd) / CONFIG_FILE_NAME


def _remove_toml_table(text: str, table_name: str) -> str:
    if not text.strip():
        return ""
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        match = _TOML_TABLE_RE.match(line)
        if match:
            current_name = match.group(1).strip()
            if current_name == table_name:
                skipping = True
                continue
            if skipping:
                skipping = False
        if not skipping:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


def _render_mcp_server_section(server: str, config: dict[str, Any]) -> str:
    lines = [f"[mcp_servers.{server}]"]
    preferred_order = [
        "enabled",
        "auto_connect",
        "startup_timeout_sec",
        "context_resolution",
        "command",
        "args",
        "env",
        "cwd",
        "url",
        "transport",
        "headers",
        "auth",
        "sse_read_timeout_sec",
        "oauth_timeout_sec",
        "oauth_scopes",
        "oauth_client_name",
        "oauth_callback_port",
        "client_credentials_url",
        "client_credentials_client_id",
        "client_credentials_client_secret",
        "client_credentials_scope",
        "client_credentials_refresh_buffer_sec",
    ]
    seen: set[str] = set()
    for key in preferred_order:
        if key in config:
            lines.append(f"{key} = {_toml_value(config[key])}")
            seen.add(key)
    for key, value in config.items():
        if key in seen:
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines)


def _toml_key(key: str) -> str:
    if _TOML_BARE_KEY_RE.match(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        return json.dumps(str(value), ensure_ascii=False)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        body = ", ".join(
            f"{_toml_key(str(key))} = {_toml_value(item)}"
            for key, item in value.items()
        )
        return "{ " + body + " }"
    if value is None:
        return '""'
    return json.dumps(str(value), ensure_ascii=False)


def load_mcp_env_store(
    cwd: Path | None, scope: str = "workspace"
) -> dict[str, dict[str, str]]:
    path = _mcp_secrets_path_for_scope(cwd, scope)
    return _load_mcp_secrets(path)


def save_mcp_env_var(
    *,
    cwd: Path | None,
    scope: str,
    server: str,
    key: str,
    value: str,
) -> Path:
    path = _mcp_secrets_path_for_scope(cwd, scope)
    secrets = _load_mcp_secrets(path)
    bucket = secrets.setdefault(server, {})
    bucket[key] = value
    if str(scope).strip().lower() == "global":
        keyring.set_password(_mcp_keyring_service(server), key, value)
    _write_mcp_secrets(path, secrets)
    return path


def remove_mcp_env_var(
    *,
    cwd: Path | None,
    scope: str,
    server: str,
    key: str,
) -> Path:
    path = _mcp_secrets_path_for_scope(cwd, scope)
    secrets = _load_mcp_secrets(path)
    if str(scope).strip().lower() == "global":
        try:
            keyring.delete_password(_mcp_keyring_service(server), key)
        except Exception:
            pass
    if server in secrets:
        secrets[server].pop(key, None)
        if not secrets[server]:
            secrets.pop(server, None)
    _write_mcp_secrets(path, secrets)
    return path


def clear_mcp_env_vars(server: str, *, cwd: Path | None = None) -> None:
    """Remove all env vars for an MCP server from all storage locations."""
    import keyring as kr

    # Global scope — clear keyring and metadata
    sys_path = get_system_secrets_path()
    sys_secrets = _load_mcp_secrets(sys_path)
    if server in sys_secrets:
        for key in list(sys_secrets[server]):
            try:
                kr.delete_password(_mcp_keyring_service(server), key)
            except Exception:
                pass
        del sys_secrets[server]
    _write_mcp_secrets(sys_path, sys_secrets)

    # Workspace scope — clear from .ite/secrets.toml
    if cwd is not None:
        ws_path = get_workspace_secrets_path(cwd)
        ws_secrets = _load_mcp_secrets(ws_path)
        if server in ws_secrets:
            del ws_secrets[server]
        _write_mcp_secrets(ws_path, ws_secrets)

    # Strip env vars baked into config TOML files
    for scope_name, scope_cwd in (
        ("global", None),
        ("workspace", cwd),
    ):
        try:
            config_path = _mcp_config_path_for_scope(scope_cwd, scope_name)
        except ValueError:
            continue
        if not config_path.exists():
            continue
        cfg = load_config(scope_cwd)
        if server not in cfg.mcp_servers:
            continue
        srv = cfg.mcp_servers[server]
        if not srv.env:
            continue
        srv.env = {}
        save_mcp_server_config(
            cwd=scope_cwd,
            scope=scope_name,
            server=server,
            config=srv.model_dump(exclude_defaults=True),
        )


def _mcp_secrets_path_for_scope(cwd: Path | None, scope: str) -> Path:
    normalized = str(scope or "workspace").strip().lower()
    if normalized == "global":
        return get_system_secrets_path()
    if cwd is None:
        raise ValueError("Workspace cwd is required for workspace-scoped MCP env")
    ensure_workspace_layout(cwd)
    return get_workspace_secrets_path(cwd)


def _load_mcp_secrets(path: Path) -> dict[str, dict[str, str]]:
    if path == get_system_secrets_path():
        return _load_global_mcp_secrets_from_keyring(path)
    if not path.is_file():
        return {}
    raw = _parse_toml(path)
    mcp_env = raw.get("mcp_env", {})
    if not isinstance(mcp_env, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for server, values in mcp_env.items():
        if not isinstance(server, str) or not isinstance(values, dict):
            continue
        bucket: dict[str, str] = {}
        for key, value in values.items():
            if isinstance(key, str) and isinstance(value, str):
                bucket[key] = value
        if bucket:
            result[server] = bucket
    return result


def _merge_mcp_secrets_into_config(
    config_dict: dict[str, Any],
    secrets: dict[str, dict[str, str]],
) -> dict[str, Any]:
    if not secrets:
        return config_dict
    result = config_dict.copy()
    mcp_servers = dict(result.get("mcp_servers", {}) or {})
    for server, values in secrets.items():
        if server not in mcp_servers:
            continue
        server_cfg = dict(mcp_servers.get(server, {}) or {})
        merged_env = dict(server_cfg.get("env", {}) or {})
        merged_env.update(values)
        server_cfg["env"] = merged_env
        mcp_servers[server] = server_cfg
    result["mcp_servers"] = mcp_servers
    return result


def _load_mcp_client_credentials_secrets(path: Path) -> dict[str, dict[str, str]]:
    """Load [mcp_client_credentials.<server>] tables from the secrets file."""
    if not path.is_file():
        return {}
    try:
        raw = _parse_toml(path)
    except ConfigError:
        return {}
    bucket = raw.get("mcp_client_credentials", {})
    if not isinstance(bucket, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for server, values in bucket.items():
        if not isinstance(server, str) or not isinstance(values, dict):
            continue
        items: dict[str, str] = {}
        for key, value in values.items():
            if isinstance(key, str) and isinstance(value, str):
                items[key] = value
        if items:
            result[server] = items
    return result


def _merge_mcp_client_credentials_secrets_into_config(
    config_dict: dict[str, Any],
    secrets: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Inject client_credentials client_id/secret from secrets into MCP config."""
    if not secrets:
        return config_dict
    result = config_dict.copy()
    mcp_servers = dict(result.get("mcp_servers", {}) or {})
    for server, values in secrets.items():
        if server not in mcp_servers:
            continue
        server_cfg = dict(mcp_servers.get(server, {}) or {})
        for key, value in values.items():
            if key in {
                "client_credentials_client_id",
                "client_credentials_client_secret",
            }:
                server_cfg[key] = value
        mcp_servers[server] = server_cfg
    result["mcp_servers"] = mcp_servers
    return result


def _write_mcp_secrets(path: Path, secrets: dict[str, dict[str, str]]) -> None:
    if path == get_system_secrets_path():
        _write_global_mcp_secret_metadata(path, secrets)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# MCP secrets for iTE",
        "# Generated by /mcp env commands.",
        "",
    ]
    for server in sorted(secrets):
        values = secrets[server]
        if not values:
            continue
        lines.append(f"[mcp_env.{server}]")
        for key in sorted(values):
            lines.append(f"{key} = {json.dumps(values[key])}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


_keyring_mcp_secrets_cache: dict[str, dict[str, str]] | None = None


def invalidate_mcp_keyring_cache() -> None:
    """Clear the cached keyring secrets so next read re-queries the keyring."""
    global _keyring_mcp_secrets_cache
    _keyring_mcp_secrets_cache = None


def load_mcp_keyring_env_vars(server: str) -> dict[str, str]:
    """Lazily load keyring secrets for a specific MCP server.

    Reads from the macOS keychain (or equivalent) once and caches for the
    process lifetime. Called on-demand right before a server connects, not
    at config-load time, to avoid triggering keychain password prompts on
    every startup.
    """
    global _keyring_mcp_secrets_cache
    if _keyring_mcp_secrets_cache is None:
        _keyring_mcp_secrets_cache = _load_global_mcp_secrets_from_keyring(
            get_system_secrets_path()
        )
    return dict(_keyring_mcp_secrets_cache.get(server, {}))


def _load_global_mcp_secrets_from_keyring(path: Path) -> dict[str, dict[str, str]]:
    metadata = _load_mcp_secret_metadata(path)
    result: dict[str, dict[str, str]] = {}
    for server, keys in metadata.items():
        bucket: dict[str, str] = {}
        for key in keys:
            try:
                value = keyring.get_password(_mcp_keyring_service(server), key)
            except Exception as exc:
                logger.warning(
                    "Failed to read MCP secret from keyring for %s:%s: %s",
                    server,
                    key,
                    exc,
                )
                continue
            if value is not None:
                bucket[key] = value
        if bucket:
            result[server] = bucket
    return result


def _load_mcp_secret_metadata(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        return {}
    raw = _parse_toml(path)
    mcp_env = raw.get("mcp_env", {})
    if not isinstance(mcp_env, dict):
        return {}
    result: dict[str, list[str]] = {}
    for server, values in mcp_env.items():
        if not isinstance(server, str) or not isinstance(values, dict):
            continue
        keys = values.get("keys", [])
        if isinstance(keys, list):
            result[server] = [str(item) for item in keys if str(item).strip()]
    return result


def _write_global_mcp_secret_metadata(
    path: Path, secrets: dict[str, dict[str, str]]
) -> None:
    metadata = {
        server: sorted(values.keys()) for server, values in secrets.items() if values
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# MCP secret metadata for iTE",
        "# Values are stored in the OS keyring. This file only tracks key names.",
        "",
    ]
    for server in sorted(metadata):
        lines.append(f"[mcp_env.{server}]")
        lines.append(f"keys = {json.dumps(metadata[server])}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _mcp_keyring_service(server: str) -> str:
    return f"ite.mcp.{server}"
