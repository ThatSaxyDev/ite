from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ite.config.config import MCPServerConfig
from ite.config.loader import get_data_dir
from ite.utils.atomic_file import atomic_write, locked_file


def launch_fingerprint(name: str, config: MCPServerConfig, cwd: Path) -> str:
    payload = [name, str(cwd.resolve()), config.command, config.args,
               str(config.cwd or cwd), config.inherit_environment]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def local_launch_trusted(name: str, config: MCPServerConfig, cwd: Path) -> bool:
    if not config.command:
        return True
    path = get_data_dir() / "auth" / "mcp_launch_trust.json"
    try:
        return launch_fingerprint(name, config, cwd) in json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return False


def trust_local_launch(name: str, config: MCPServerConfig, cwd: Path) -> None:
    path = get_data_dir() / "auth" / "mcp_launch_trust.json"
    with locked_file(path):
        try:
            records = json.loads(path.read_text())
        except (OSError, ValueError):
            records = []
        records = list(records) if isinstance(records, list) else []
        fingerprint = launch_fingerprint(name, config, cwd)
        if fingerprint not in records:
            records.append(fingerprint)
        atomic_write(path, json.dumps(records))
