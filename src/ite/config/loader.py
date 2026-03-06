from platformdirs import user_data_dir
import logging
from typing import Any
from ite.utils.errors import ConfigError
from ite.config.config import ApprovalPolicy
import tomli
from ite.config.config import Config
from pathlib import Path
from platformdirs import user_config_dir

CONFIG_FILE_NAME = "config.toml"
AGENT_MD_FILE = "AGENT.MD"
WORKSPACE_DIR_NAME = ".ite"

DEFAULT_PROJECT_CONFIG = """# Workspace-level ITE config
# Add overrides here (model, hooks, mcp servers, etc.)
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


def get_config_dir() -> Path:
    return Path(user_config_dir("ite"))


def get_data_dir() -> Path:
    return Path(user_data_dir("ite"))


def get_system_config_path() -> Path:
    return get_config_dir() / CONFIG_FILE_NAME


def _parse_toml(path: Path):
    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except tomli.TOMLDecodeError as e:
        raise ConfigError(
            "Invalid TOML file in {path}: {e}", config_file=str(path)
        ) from e
    except (OSError, IOError) as e:
        raise ConfigError(
            "Failed to read TOML file in {path}: {e}", config_file=str(path)
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
            config_dict = system_config_dict.copy()
        except ConfigError:
            logger.warning(f"Skipping invalid system config: {system_path}")

    project_path = _get_project_config(cwd)

    if project_path:
        try:
            project_config_dict = _parse_toml(project_path)
            config_dict = _merge_dicts(config_dict, project_config_dict)
        except ConfigError:
            logger.warning(f"Skipping invalid project config: {project_path}")

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

    try:
        config = Config(**config_dict)
    except ConfigError as e:
        raise ConfigError(f"Invalid configuration: {e}") from e

    return config


def save_system_config(
    api_key: str,
    base_url: str,
    model_name: str,
) -> Path:
    """Save credentials and model to the system-level config file."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / CONFIG_FILE_NAME

    # Build TOML content manually (no extra dependency needed)
    lines = []
    lines.append(f'api_key = "{api_key}"')
    lines.append(f'base_url = "{base_url}"')
    lines.append("")
    lines.append("[model]")
    lines.append(f'name = "{model_name}"')
    lines.append("")

    config_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Saved system config to %s", config_path)
    return config_path


def save_global_approval_mode(mode: ApprovalPolicy | str) -> Path:
    """Persist global approval mode in system config.toml."""
    value = mode.value if isinstance(mode, ApprovalPolicy) else str(mode).strip()
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_system_config_path()

    if not config_path.exists():
        config_path.write_text(f'approval = "{value}"\n', encoding="utf-8")
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
    return config_path
