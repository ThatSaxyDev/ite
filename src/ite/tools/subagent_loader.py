"""
Discovers and loads user-defined subagent definitions from TOML files.

Scan order (project-level overrides global):
  1. Global: ~/.config/ite/subagents/*.toml
  2. Project: .ite/subagents/*.toml
"""

import logging
from pathlib import Path

import tomli

from config.loader import get_config_dir
from tools.subagent import SubagentDefinition

logger = logging.getLogger(__name__)


def load_subagent_from_toml(path: Path) -> SubagentDefinition | None:
    """Parse a single TOML file into a SubagentDefinition."""
    try:
        with open(path, "rb") as f:
            data = tomli.load(f)
        return SubagentDefinition.from_dict(data)
    except (tomli.TOMLDecodeError, ValueError) as e:
        logger.warning(f"Skipping invalid subagent file {path}: {e}")
        return None
    except (OSError, IOError) as e:
        logger.warning(f"Failed to read subagent file {path}: {e}")
        return None


def _scan_directory(directory: Path) -> dict[str, SubagentDefinition]:
    """Scan a directory for .toml subagent definitions, keyed by name."""
    results: dict[str, SubagentDefinition] = {}

    if not directory.is_dir():
        return results

    for toml_file in sorted(directory.glob("*.toml")):
        definition = load_subagent_from_toml(toml_file)
        if definition:
            results[definition.name] = definition
            logger.debug(f"Loaded subagent '{definition.name}' from {toml_file}")

    return results


def discover_subagents(cwd: Path) -> list[SubagentDefinition]:
    """
    Discover subagent definitions from global and project directories.
    Project-level definitions override global ones with the same name.
    """
    # 1. Global subagents
    global_dir = get_config_dir() / "subagents"
    definitions = _scan_directory(global_dir)

    # 2. Project subagents (override global by name)
    project_dir = Path(cwd).resolve() / ".ite" / "subagents"
    project_defs = _scan_directory(project_dir)
    definitions.update(project_defs)

    return list(definitions.values())
