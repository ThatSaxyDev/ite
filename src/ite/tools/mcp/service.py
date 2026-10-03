from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import tomli

from ite.config.config import Config, MCPServerConfig
from ite.config.loader import (
    _mcp_config_path_for_scope,
    clear_mcp_env_vars,
    get_data_dir,
    load_config,
    load_mcp_server_config,
    remove_mcp_server_config,
    save_mcp_server_config,
)
from ite.tools.mcp.client import MCPClient, MCPServerStatus
from ite.tools.mcp.credentials import CredentialStore, redact_connection_text
from ite.tools.mcp.mcp_manager import MCPManager
from ite.tools.mcp.trust import local_launch_trusted, trust_local_launch
from ite.tools.registry import ToolRegistry
from ite.utils.atomic_file import atomic_write, locked_file


@dataclass(frozen=True)
class ConnectionRecord:
    name: str
    scope: str
    config: MCPServerConfig | None
    error: str | None = None

    @property
    def key(self) -> str:
        return f"{self.scope}:{self.name}"

    @property
    def label(self) -> str:
        return (self.config.display_name if self.config else None) or self.name


class ConnectionsService:
    """One management API for native UI and existing command adapters.

    Definitions remain in the existing TOML files. Transports are session-owned;
    inventory retains invalid, disabled, and inherited definitions.
    """

    def __init__(self, config: Config, manager: MCPManager, registry: ToolRegistry) -> None:
        self.config = config
        self.manager = manager
        self.registry = registry
        self._locks: dict[str, asyncio.Lock] = {}
        self._operations: dict[str, asyncio.Task[Any]] = {}
        self._listeners: set[Callable[[], None]] = set()
        self._session_credentials: dict[str, dict[str, Any]] = {}
        self._errors: dict[str, str] = {}
        self._inventory: list[ConnectionRecord] = []

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def records(self) -> list[ConnectionRecord]:
        records = []
        for scope in ("global", "workspace"):
            path = _mcp_config_path_for_scope(self.config.cwd, scope)
            if not path.exists():
                continue
            try:
                raw = tomli.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                records.append(ConnectionRecord("Configuration file", scope, None,
                                                "The configuration file could not be read. Repair it before saving connections."))
                continue
            entries = raw.get("mcp_servers", {})
            if not isinstance(entries, dict):
                continue
            for name, payload in entries.items():
                try:
                    parsed = MCPServerConfig.model_validate(payload)
                    records.append(ConnectionRecord(name, scope, parsed))
                except (ValueError, TypeError):
                    records.append(ConnectionRecord(name, scope, None,
                                                    "This definition is invalid. Edit the connection settings."))
        known = {record.name for record in records}
        # Programmatically configured sessions also remain inspectable.
        for name, config in self.config.mcp_servers.items():
            if name not in known:
                records.append(ConnectionRecord(name, "session", config))
        self._inventory = sorted(records, key=lambda record: (record.label.casefold(), record.scope))
        return self._inventory

    def record(self, key: str) -> ConnectionRecord:
        for record in self.records():
            if record.key == key:
                return record
        raise KeyError("This connection was removed. Refresh the list.")

    def snapshot(self, record: ConnectionRecord) -> dict[str, Any]:
        config = record.config
        shadowed = record.scope == "global" and any(
            other.name == record.name and other.scope == "workspace" for other in self._inventory)
        client = self.manager._clients.get(record.name) if not shadowed else None
        if record.error:
            status, detail = "needs_setup", record.error
        elif shadowed:
            status, detail = "overridden", "This project uses its own definition."
        elif config and not config.enabled:
            status, detail = "disabled", "Enable this connection to use it."
        elif config and config.command and not local_launch_trusted(record.name, config, self.config.cwd):
            status, detail = "needs_approval", "Review local startup before connecting."
        elif client:
            status = client.status.value
            status = "disconnected" if status == "ready" else status
            detail = client.status_detail or ""
        else:
            status, detail = "disconnected", "Connect to make tools available."
        if record.key in self._errors:
            status, detail = "failed", self._errors[record.key]
        if record.key in self._operations:
            status = "connecting"
        return {"key": record.key, "name": record.name, "label": record.label,
                "scope": record.scope, "status": status,
                "detail": redact_connection_text(detail, config),
                "tools": len(client.tools) if client else 0,
                "active": not shadowed, "enabled": bool(config and config.enabled)}

    def _reference(self, record: ConnectionRecord) -> str:
        if record.config and record.config.credential_ref:
            return record.config.credential_ref
        source = [record.scope, record.name,
                  str(self.config.cwd.resolve()) if record.scope != "global" else ""]
        return hashlib.sha256(json.dumps(source).encode()).hexdigest()

    async def save(self, name: str, scope: str, payload: dict[str, Any],
                   *, replace: bool = False) -> ConnectionRecord:
        if scope not in {"global", "workspace"}:
            raise ValueError("Choose all projects or this project.")
        if not name.strip() or len(name) > 100:
            raise ValueError("Enter a name with at most 100 characters.")
        existing = load_mcp_server_config(cwd=self.config.cwd, scope=scope, server=name)
        if existing and not replace:
            raise ValueError("A connection with this name already exists in that scope.")
        try:
            previous = MCPServerConfig.model_validate(existing) if existing else None
        except ValueError:
            previous = None
        values = dict(payload)
        values.setdefault("connection_id", previous.connection_id if previous else str(uuid.uuid4()))
        if previous and (previous.url, previous.command, previous.args, previous.auth) != (
                values.get("url"), values.get("command"), values.get("args", []), values.get("auth")):
            # Changing endpoint/auth creates a fresh binding; old credentials
            # remain recoverable until an explicit sign-out/removal.
            values["credential_ref"] = str(uuid.uuid4())
        else:
            values.setdefault("credential_ref", (previous.credential_ref or self._reference(ConnectionRecord(name, scope, previous))) if previous else str(uuid.uuid4()))
        secret_values: dict[str, Any] = {}
        if not previous or values.get("env", {}) != previous.env or values.get("headers", {}) != previous.headers:
            for field in ("env", "headers"):
                supplied = values.get(field) or {}
                if supplied:
                    secret_values[field] = supplied
                    values[field] = {}
        for field in ("client_credentials_client_id", "client_credentials_client_secret"):
            if values.get(field):
                secret_values[field] = values.pop(field)
        if values.get("auth") not in {None, "oauth", "client_credentials"}:
            secret_values["auth"] = values.pop("auth")
        parsed = MCPServerConfig.model_validate(values)
        if secret_values:
            store = CredentialStore(values["credential_ref"])
            current = await asyncio.to_thread(store.read)
            current.update(secret_values)
            await asyncio.to_thread(store.write, current)
        await asyncio.to_thread(save_mcp_server_config, cwd=self.config.cwd, scope=scope,
                                server=name, config=parsed.model_dump(exclude_defaults=True))
        await self.reconcile()
        self._notify()
        return self.record(f"{scope}:{name}")

    async def reconcile(self) -> None:
        fresh = await asyncio.to_thread(load_config, self.config.cwd)
        self.config.mcp_servers = fresh.mcp_servers
        self.manager.config.mcp_servers = fresh.mcp_servers
        for name, client in list(self.manager._clients.items()):
            changed = name not in fresh.mcp_servers or (
                client.config.model_dump(exclude={"env", "headers", "client_credentials_client_secret", "client_credentials_client_id"})
                != fresh.mcp_servers[name].model_dump(exclude={"env", "headers", "client_credentials_client_secret", "client_credentials_client_id"}))
            if changed:
                await self.manager.disconnect_server(name, self.registry)
                self.manager._clients.pop(name, None)
        for name, config in fresh.mcp_servers.items():
            if name not in self.manager._clients:
                client = MCPClient(name, config.model_copy(deep=True), self.config.cwd)
                client.status = MCPServerStatus.READY if config.enabled else MCPServerStatus.DISABLED
                self.manager._clients[name] = client
            elif self.manager._clients[name].status != MCPServerStatus.CONNECTED:
                self.manager._clients[name].config = config.model_copy(deep=True)
        self._notify()

    async def set_credentials(self, key: str, values: dict[str, Any], *, remember: bool = True) -> None:
        record = self.record(key)
        reference = self._reference(record)
        if record.config and not record.config.credential_ref:
            values_config = record.config.model_dump(exclude_defaults=True)
            values_config["credential_ref"] = reference
            await self.save(record.name, record.scope, values_config, replace=True)
        if remember:
            await asyncio.to_thread(CredentialStore(reference).write, values)
            self._session_credentials.pop(reference, None)
        else:
            self._session_credentials[reference] = values
        self._errors.pop(key, None)
        await self.disconnect(key)
        self._notify()

    async def connect(self, key: str, *, sign_in: bool = False, approve_local: bool = False) -> None:
        record = self.record(key)
        if not record.config:
            raise ValueError(record.error)
        if not self.snapshot(record)["active"]:
            raise ValueError("Edit or connect the project definition instead.")
        if not record.config.enabled:
            raise ValueError("Enable this connection first.")
        if key in self._operations:
            return
        task = asyncio.current_task()
        if task:
            self._operations[key] = task
        self._errors.pop(key, None)
        self._notify()
        try:
            async with self._locks.setdefault(key, asyncio.Lock()):
                if approve_local:
                    await asyncio.to_thread(trust_local_launch, record.name, record.config, self.config.cwd)
                if record.name not in self.manager._clients:
                    self.manager._clients[record.name] = MCPClient(record.name, record.config, self.config.cwd)
                client = self.manager._clients[record.name]
                if client.status == MCPServerStatus.CONNECTED:
                    await self.manager.disconnect_server(record.name, self.registry)
                effective = self.config.mcp_servers.get(record.name, record.config).model_copy(deep=True)
                reference = self._reference(record)
                credentials = self._session_credentials.get(reference)
                if credentials is None and effective.credential_ref:
                    credentials = await asyncio.to_thread(CredentialStore(reference).read)
                credentials = credentials or {}
                effective.env.update(credentials.get("env", {}))
                effective.headers.update(credentials.get("headers", {}))
                for field in ("auth", "client_credentials_client_id", "client_credentials_client_secret"):
                    if field in credentials:
                        setattr(effective, field, credentials[field])
                client.config = effective
                client.allow_browser = sign_in
                client.status_observer = lambda _: self._notify()
                await self.manager.connect_server(record.name, self.registry,
                                                  status_callback=lambda _: self._notify())
        except asyncio.CancelledError:
            self._errors.pop(key, None)
            raise
        except Exception as error:  # noqa: BLE001 - transport boundary produces sanitized failures
            failed_client = self.manager._clients.get(record.name)
            self._errors[key] = redact_connection_text(str(error), failed_client.config if failed_client else record.config)
            raise RuntimeError(self._errors[key]) from None
        finally:
            self._operations.pop(key, None)
            self._notify()

    async def cancel(self, key: str) -> None:
        task = self._operations.get(key)
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def disconnect(self, key: str) -> None:
        await self.cancel(key)
        record = self.record(key)
        async with self._locks.setdefault(key, asyncio.Lock()):
            if self.snapshot(record)["active"] and record.name in self.manager._clients:
                await self.manager.disconnect_server(record.name, self.registry)
        self._notify()

    async def set_enabled(self, key: str, enabled: bool) -> None:
        record = self.record(key)
        if not record.config:
            raise ValueError(record.error)
        await self.disconnect(key)
        values = record.config.model_dump(exclude_defaults=True)
        values["enabled"] = enabled
        await self.save(record.name, record.scope, values, replace=True)

    async def select_tools(self, key: str, names: list[str]) -> None:
        record = self.record(key)
        if not record.config:
            raise ValueError(record.error)
        config = record.config.model_copy(update={"enabled_tools": names})
        await asyncio.to_thread(save_mcp_server_config, cwd=self.config.cwd, scope=record.scope,
                                server=record.name, config=config.model_dump(exclude_defaults=True))
        self.config.mcp_servers[record.name].enabled_tools = names
        client = self.manager._clients.get(record.name)
        if client:
            client.config.enabled_tools = names
            if client.status == MCPServerStatus.CONNECTED:
                self.manager._register_client_tools(client, self.registry)
        self._notify()

    async def sign_out(self, key: str) -> None:
        record = self.record(key)
        await self.disconnect(key)
        reference = self._reference(record)
        self._session_credentials.pop(reference, None)
        store = CredentialStore(reference)
        await asyncio.to_thread(store.clear)
        await asyncio.to_thread(store.clear, "oauth")
        if record.config:
            if not record.config.credential_ref:
                await asyncio.to_thread(clear_legacy_oauth_tokens, record.config)
            if record.scope in {"global", "workspace"}:
                await asyncio.to_thread(clear_mcp_env_vars, record.name, cwd=self.config.cwd, scope=record.scope)
                values = record.config.model_dump(exclude_defaults=True)
                for field in ("env", "headers", "client_credentials_client_id", "client_credentials_client_secret"):
                    values.pop(field, None)
                if values.get("auth") not in {None, "oauth", "client_credentials"}:
                    values.pop("auth", None)
                await asyncio.to_thread(save_mcp_server_config, cwd=self.config.cwd, scope=record.scope,
                                        server=record.name, config=values)
                await self.reconcile()
        self._errors.pop(key, None)
        self._notify()

    async def remove(self, key: str) -> None:
        record = self.record(key)
        if record.config:
            await self.sign_out(key)
        await asyncio.to_thread(remove_mcp_server_config, cwd=self.config.cwd,
                                scope=record.scope, server=record.name)
        await self.reconcile()

    async def diagnose(self, key: str) -> list[str]:
        record = self.record(key)
        config = record.config
        if not config:
            return [record.error or "Invalid configuration"]
        result = [f"Scope: {record.scope}", f"Transport: {config.effective_transport}",
                  f"Enabled: {'yes' if config.enabled else 'no'}"]
        if config.command:
            executable = await asyncio.to_thread(shutil.which, config.command)
            result.append("Executable: found" if executable else f"Missing executable: {config.command}")
            result.append("Local startup: approved" if local_launch_trusted(record.name, config, self.config.cwd) else "Local startup needs review")
        result.extend([f"Startup timeout: {config.startup_timeout_sec:g}s", f"Call timeout: {config.call_timeout_sec:g}s"])
        result.append(self.snapshot(record)["detail"])
        return result

    @staticmethod
    def import_definitions(text: str) -> dict[str, dict[str, Any]]:
        if len(text) > 1_000_000:
            raise ValueError("Configuration is too large.")
        payload = json.loads(text) if text.lstrip().startswith("{") else tomli.loads(text)
        raw = payload.get("mcp_servers", payload.get("mcpServers", payload.get("servers", {})))
        if not isinstance(raw, dict) or not raw:
            raise ValueError("No MCP connections found in this configuration.")
        result = {}
        for name, values in raw.items():
            values = dict(values)
            transport = values.pop("type", None)
            if transport:
                values["transport"] = "streamable_http" if transport in {"http", "https"} else transport
            values.pop("inputs", None)
            result[str(name)] = MCPServerConfig.model_validate(values).model_dump(exclude_defaults=True)
        return result


def clear_legacy_oauth_tokens(config: MCPServerConfig) -> None:
    """Remove only legacy SDK entries associated with this endpoint."""
    if not config.url:
        return
    path = get_data_dir() / "auth" / "mcp_oauth_tokens.json"
    with locked_file(path):
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        for bucket in payload.values():
            if isinstance(bucket, dict):
                for name in list(bucket):
                    if name in {f"{url}/{suffix}" for url in (config.url, config.url.rstrip("/"))
                                for suffix in ("tokens", "client_info", "token_expiry")}:
                        bucket.pop(name)
        atomic_write(path, json.dumps(payload))


def connections_for_session(session: Any) -> ConnectionsService:
    service = getattr(session, "connections_service", None)
    if service is None:
        service = ConnectionsService(session.config, session.mcp_manager, session.tool_registry)
        session.connections_service = service
    return service
