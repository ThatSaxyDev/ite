from platformdirs import user_data_dir
import logging
import os
import json
import re
from typing import Any
import keyring
from ite.utils.errors import ConfigError
from ite.config.config import ApprovalPolicy
import tomli
from ite.config.config import Config, MCPServerConfig
from pathlib import Path
from platformdirs import user_config_dir
from pydantic import ValidationError

CONFIG_FILE_NAME = "config.toml"
SECRETS_FILE_NAME = "secrets.toml"
AGENT_MD_FILE = "AGENT.MD"
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


def _get_agent_md_files(cwd: Path) -> str | None:
    current = cwd.resolve()

    if current.is_dir():
        agent_md_file = current / AGENT_MD_FILE
        if agent_md_file.is_file():
            try:
                content = agent_md_file.read_text(encoding="utf-8")
                return content
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to read {agent_md_file}: {e}")
                return None

    return None


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
            normalized_system_config = _remove_persisted_cloud_api_url(system_config_dict)
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
        _load_mcp_secrets(get_system_secrets_path()),
    )

    config_dict = _merge_mcp_secrets_into_config(
        config_dict,
        _load_mcp_secrets(get_workspace_secrets_path(cwd)),
    )

    # Approval policy is global user preference and should be consistent
    # across projects/sessions.
    if "approval" in system_config_dict:
        config_dict["approval"] = system_config_dict["approval"]

    if "cwd" not in config_dict:
        config_dict["cwd"] = cwd

    if "developer_instructions" not in config_dict:
        agent_md_content = _get_agent_md_files(cwd)
        if agent_md_content:
            config_dict["developer_instructions"] = agent_md_content

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
            logger.warning("Skipping invalid MCP server '%s': entry must be a table", name)
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


def load_saved_custom_provider() -> dict[str, dict[str, str]]:
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
        result[normalized] = {
            "base_url": base_url,
            "api_key": api_key,
            "model_name": normalized,
        }
    return result


def save_saved_custom_provider(
    *,
    api_key: str,
    base_url: str,
    model_name: str,
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
    providers[model_name] = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": model_name,
    }
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

    mcp_servers = config.get("mcp_servers")
    if isinstance(mcp_servers, dict):
        for server, server_config in mcp_servers.items():
            if not isinstance(server_config, dict):
                continue
            if lines:
                lines.append("")
            lines.extend(_render_mcp_server_section(str(server), server_config).splitlines())

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
        if line.strip().startswith("approval") and "=" in line and not line.strip().startswith("#"):
            out_lines.append(f'approval = "{value}"')
            replaced = True
        else:
            out_lines.append(line)

    if not replaced:
        # Keep it top-level and near the top for discoverability.
        insert_at = 0
        while insert_at < len(out_lines) and out_lines[insert_at].strip().startswith("#"):
            insert_at += 1
        out_lines.insert(insert_at, f'approval = "{value}"')

    config_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)
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


def load_mcp_env_store(cwd: Path | None, scope: str = "workspace") -> dict[str, dict[str, str]]:
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


def _load_global_mcp_secrets_from_keyring(path: Path) -> dict[str, dict[str, str]]:
    metadata = _load_mcp_secret_metadata(path)
    result: dict[str, dict[str, str]] = {}
    for server, keys in metadata.items():
        bucket: dict[str, str] = {}
        for key in keys:
            try:
                value = keyring.get_password(_mcp_keyring_service(server), key)
            except Exception as exc:
                logger.warning("Failed to read MCP secret from keyring for %s:%s: %s", server, key, exc)
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


def _write_global_mcp_secret_metadata(path: Path, secrets: dict[str, dict[str, str]]) -> None:
    metadata = {server: sorted(values.keys()) for server, values in secrets.items() if values}
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
