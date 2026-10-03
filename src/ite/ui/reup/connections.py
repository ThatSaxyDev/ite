from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import (
    Button,
    ContentSwitcher,
    Input,
    OptionList,
    SelectionList,
    Static,
)
from textual.widgets.option_list import Option

from ite.tools.mcp.client import MCPServerStatus
from ite.tools.mcp.mcp_manager import MCPManager
from ite.tools.mcp.service import ConnectionsService, connections_for_session
from ite.tools.mcp.trust import local_launch_trusted
from ite.tools.registry import ToolRegistry

from .connection_modals import ConnectionCredentialsModal, ConnectionSetupModal
from .modals import ConfirmModal
from .widgets.action_button import FlatActionButton

STATUS_LABELS = {"needs_setup": "Needs setup", "needs_approval": "Needs approval",
                 "failed": "Needs attention", "connecting": "Connecting",
                 "connected": "Connected", "disabled": "Disabled",
                 "disconnected": "Disconnected", "error": "Needs attention",
                 "overridden": "Project override"}


def service_for_app(app: Any) -> ConnectionsService:
    session = getattr(getattr(app, "agent", None), "session", None)
    if session is not None:
        return connections_for_session(session)
    service = getattr(app, "_standalone_connections_service", None)
    if service is None or service.config.cwd != app.config.cwd:
        service = ConnectionsService(app.config, MCPManager(app.config), ToolRegistry(app.config))
        app._standalone_connections_service = service
    return service


class ConnectionsPanel(Widget):
    """Settings subpage; no network activity is required to open it."""

    BINDINGS: ClassVar = [("escape", "back", "Back")]
    DEFAULT_CSS = """
    ConnectionsPanel { height: 1fr; width: 100%; background: $background; }
    ConnectionsPanel.connections-detail-active { align-horizontal: center; }
    ConnectionsPanel.connections-detail-active .connections-header,
    ConnectionsPanel.connections-detail-active #connections-pages,
    ConnectionsPanel.connections-detail-active #connections-notice {
        width: 100%; max-width: 200;
    }
    ConnectionsPanel .connections-header { height: 1; min-height: 1; margin: 1 0; }
    ConnectionsPanel .connections-title { width: 1fr; height: 1; content-align: center middle;
        text-style: bold; color: $text-primary; }
    ConnectionsPanel #connections-header-spacer { width: 13; height: 1; display: none; }
    ConnectionsPanel .connections-summary { height: auto; color: $foreground-muted; margin-bottom: 1; }
    ConnectionsPanel ContentSwitcher { height: 1fr; }
    ConnectionsPanel #connections-list { height: 1fr; border: none; background: $background; }
    ConnectionsPanel #connections-filter { margin-bottom: 1; }
    ConnectionsPanel .connections-detail-scroll { height: 1fr; }
    ConnectionsPanel .connections-description { height: auto; color: $foreground-muted; margin: 1 0; }
    ConnectionsPanel .connections-actions { height: auto; layout: grid; grid-size: 3;
        grid-columns: 1fr 1fr 1fr; grid-rows: 2; margin: 1 0; }
    ConnectionsPanel .connections-actions Button { width: 100%; min-width: 8; }
    ConnectionsPanel #connection-tools { height: 12; max-height: 35vh; border: none; background: $surface; }
    ConnectionsPanel .connections-section { height: auto; text-style: bold; margin-top: 1; }
    ConnectionsPanel #connections-notice { height: auto; color: $text-warning; }
    ConnectionsPanel #connection-diagnostics { height: auto; margin: 1 0; }
    ConnectionsPanel #connection-authorization-url { height: auto; color: $foreground-muted; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._service: ConnectionsService | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._keys: list[str] = []
        self._selected: str | None = None
        self._list_signature: tuple[Any, ...] | None = None
        self._tools_signature: tuple[Any, ...] | None = None

    @property
    def service(self) -> ConnectionsService:
        return service_for_app(self.app)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="connections-header"):
            yield FlatActionButton("Back", id="connections-back")
            yield Static("Connections", id="connections-title", classes="connections-title", markup=False)
            yield FlatActionButton("Add connection", variant="primary", id="connections-add")
            yield Static("", id="connections-header-spacer")
        yield Static("", id="connections-summary", classes="connections-summary")
        yield Static("", id="connections-notice", markup=False)
        with ContentSwitcher(initial="connections-overview", id="connections-pages"):
            with Container(id="connections-overview"):
                yield Input(placeholder="Find a connection", id="connections-filter")
                yield OptionList(id="connections-list")
                yield Static("Connect services and tools to iTE. Choose Add connection to get started.",
                             id="connections-empty", classes="connections-description")
            with VerticalScroll(id="connections-detail", classes="connections-detail-scroll"):
                yield Static("", id="connection-detail-status", classes="connections-description", markup=False)
                yield Static("", id="connection-detail-source", classes="connections-description", markup=False)
                with Container(classes="connections-actions"):
                    yield FlatActionButton("Connect", variant="primary", id="connection-connect")
                    yield FlatActionButton("Disconnect", id="connection-disconnect")
                    yield FlatActionButton("Credentials", id="connection-credentials")
                    yield FlatActionButton("Edit", id="connection-edit")
                    yield FlatActionButton("Disable", id="connection-enable")
                    yield FlatActionButton("Sign out", id="connection-signout")
                    yield FlatActionButton("Troubleshoot", id="connection-doctor")
                    yield FlatActionButton("Refresh tools", id="connection-refresh")
                    yield FlatActionButton("Remove", variant="warning", id="connection-remove")
                yield Static("", id="connection-authorization-url", markup=False)
                yield Static("", id="connection-diagnostics", markup=False)
                yield Static("Available tools", classes="connections-section")
                yield Static("Choose which tools the agent can use. Action approval still applies.", classes="connections-description")
                yield SelectionList[str](id="connection-tools")
                yield FlatActionButton("Save tool access", id="connection-save-tools")

    def on_mount(self) -> None:
        self.refresh_connections()

    def on_show(self) -> None:
        self.refresh_connections()

    def on_unmount(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()

    def refresh_connections(self) -> None:
        if not self.is_mounted:
            return
        service = self.service
        if service is not self._service:
            if self._unsubscribe:
                self._unsubscribe()
            self._service = service
            self._unsubscribe = service.subscribe(self.refresh_connections)
            self._selected = None
            self._list_signature = None
        records = service.records()
        snapshots = [service.snapshot(record) for record in records]
        connected = sum(row["status"] == "connected" for row in snapshots)
        attention = sum(row["status"] in {"failed", "error", "needs_setup", "needs_approval"} for row in snapshots)
        self.query_one("#connections-summary", Static).update(f"{connected} connected · {len(records)} configured" + (f" · {attention} need attention" if attention else ""))
        query = self.query_one("#connections-filter", Input).value.casefold()
        snapshots = [row for row in snapshots if query in row["label"].casefold()]
        signature = tuple((row["key"], row["status"], row["label"]) for row in snapshots)
        if signature != self._list_signature:
            options = self.query_one("#connections-list", OptionList)
            old_key = self._keys[options.highlighted] if options.highlighted is not None and options.highlighted < len(self._keys) else None
            options.clear_options()
            self._keys = [row["key"] for row in snapshots]
            for row in snapshots:
                scope = "All projects" if row["scope"] == "global" else "This project"
                options.add_option(Option(Text(f"{row['label']}\n  {STATUS_LABELS.get(row['status'], row['status'])} · {scope}"), id=row["key"]))
            if old_key in self._keys:
                options.highlighted = self._keys.index(old_key)
            self._list_signature = signature
        self.query_one("#connections-empty").display = not records
        if self._selected:
            try:
                self._render_detail()
            except KeyError:
                self._selected = None
                self.query_one("#connections-pages", ContentSwitcher).current = "connections-overview"
        if not self._selected:
            self._render_header()

    def _render_header(self, label: str | None = None) -> None:
        detail = label is not None
        self.set_class(detail, "connections-detail-active")
        self.query_one("#connections-title", Static).update(label if label is not None else "Connections")
        self.query_one("#connections-add").display = not detail
        self.query_one("#connections-summary").display = not detail
        self.query_one("#connections-header-spacer").display = detail

    @on(Input.Changed, "#connections-filter")
    def _filter(self) -> None:
        self.refresh_connections()

    @on(OptionList.OptionSelected, "#connections-list")
    def _select(self, event: OptionList.OptionSelected) -> None:
        self._selected = self._keys[event.option_index]
        self._tools_signature = None
        self._render_detail()
        self.query_one("#connections-pages", ContentSwitcher).current = "connections-detail"
        self.query_one("#connection-connect", Button).focus()

    def _render_detail(self) -> None:
        if not self._selected:
            return
        record = self.service.record(self._selected)
        row = self.service.snapshot(record)
        config = record.config
        self._render_header(record.label)
        self.query_one("#connection-detail-status", Static).update(STATUS_LABELS.get(row["status"], row["status"]) + (f" · {row['detail']}" if row["detail"] else ""))
        location = "Available in all projects" if record.scope == "global" else "Only this project"
        endpoint = config.url if config else None
        self.query_one("#connection-detail-source", Static).update(location + (f"\n{endpoint}" if endpoint else ""))
        busy = row["status"] == "connecting"
        connect = self.query_one("#connection-connect", Button)
        connect.label = "Cancel" if busy else "Sign in" if config and config.auth == "oauth" and row["status"] != "connected" else "Reconnect" if row["status"] == "connected" else "Connect"
        connect.disabled = not config or not row["active"] or not row["enabled"]
        self.query_one("#connection-enable", Button).label = "Disable" if row["enabled"] else "Enable"
        for identifier in ("connection-edit", "connection-enable", "connection-remove", "connection-signout", "connection-credentials", "connection-refresh", "connection-save-tools"):
            self.query_one(f"#{identifier}", Button).disabled = busy or (not config and identifier not in {"connection-edit", "connection-remove"})
        self.query_one("#connection-disconnect", Button).disabled = row["status"] != "connected"
        client = self.service.manager._clients.get(record.name) if row["active"] else None
        self.query_one("#connection-refresh", Button).disabled = not client or client.status != MCPServerStatus.CONNECTED or busy
        url = client.authorization_url if client and busy else None
        self.query_one("#connection-authorization-url", Static).update(f"If your browser did not open, use this sign-in link:\n{url}" if url else "")
        tools = client.tools if client and row["active"] else []
        signature = tuple((tool.name, tool.description) for tool in tools) + (tuple(config.enabled_tools) if config and config.enabled_tools is not None else None,)
        if signature != self._tools_signature:
            selection = self.query_one("#connection-tools", SelectionList)
            selection.clear_options()
            selection.add_options([(tool.title or tool.name, tool.name, config.enabled_tools is None or tool.name in config.enabled_tools) for tool in tools] if config else [])
            self._tools_signature = signature
        self.query_one("#connection-save-tools", Button).disabled = not tools or busy

    @on(Button.Pressed, "#connections-back")
    def action_back(self) -> None:
        if self._selected:
            self._selected = None
            self._render_header()
            self.query_one("#connections-pages", ContentSwitcher).current = "connections-overview"
            self.query_one("#connections-list", OptionList).focus()
        else:
            close = getattr(self.parent, "close_connections", None)
            if callable(close):
                close()

    def _run(self, operation: Awaitable[Any]) -> None:
        self.run_worker(self._guard(operation), exclusive=False, exit_on_error=False)

    async def _guard(self, operation: Awaitable[Any]) -> None:
        try:
            await operation
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - native UI boundary renders recoverable errors
            self.query_one("#connections-notice", Static).update(str(error))
        finally:
            self.refresh_connections()

    @on(Button.Pressed, "#connections-add")
    def open_add(self) -> None:
        self._run(self._setup())

    async def _setup(self, edit: bool = False) -> None:
        record = self.service.record(self._selected) if edit and self._selected else None
        result = await self.app.push_screen_wait(ConnectionSetupModal(record))
        if not result:
            return
        saved = await self.service.save(result["name"], result["scope"], result["config"], replace=edit)
        self._selected = saved.key
        self.query_one("#connections-pages", ContentSwitcher).current = "connections-detail"
        self._tools_signature = None
        if result["credentials_needed"]:
            await self._credentials()
        self.query_one("#connections-notice", Static).update("Saved. Choose Connect or Sign in when ready.")

    @on(Button.Pressed)
    def _action(self, event: Button.Pressed) -> None:
        identifier = event.button.id
        if identifier is None or not identifier.startswith("connection-") or not self._selected:
            return
        key = self._selected
        self.query_one("#connections-notice", Static).update("")
        if identifier == "connection-connect":
            self._run(self._connect())
        elif identifier == "connection-disconnect":
            self._run(self.service.disconnect(key))
        elif identifier == "connection-edit":
            self._run(self._setup(edit=True))
        elif identifier == "connection-credentials":
            self._run(self._credentials())
        elif identifier == "connection-enable":
            record = self.service.record(key)
            self._run(self.service.set_enabled(key, not bool(record.config and record.config.enabled)))
        elif identifier in {"connection-remove", "connection-signout"}:
            self._run(self._remove(sign_out=identifier == "connection-signout"))
        elif identifier == "connection-doctor":
            self._run(self._doctor())
        elif identifier == "connection-save-tools":
            self._run(self.service.select_tools(key, list(self.query_one("#connection-tools", SelectionList).selected)))
        elif identifier == "connection-refresh":
            self._run(self._refresh_tools())

    async def _connect(self) -> None:
        if not self._selected:
            return
        key = self._selected
        record = self.service.record(key)
        snapshot = self.service.snapshot(record)
        if snapshot["status"] == "connecting":
            await self.service.cancel(key)
            return
        approve = bool(record.config and record.config.command and not local_launch_trusted(record.name, record.config, self.service.config.cwd))
        if approve and record.config:
            config = record.config
            body = f"Command: {config.command}\nArguments: {json.dumps(config.args)}\nWorking directory: {config.cwd or self.service.config.cwd}\n\nThis program runs with your account's access. It is not isolated by an OS sandbox."
            approve = await self.app.push_screen_wait(ConfirmModal("Allow local server startup?", body, yes_label="Allow startup", no_label="Cancel", primary="no"))
            if not approve:
                return
        await self.service.connect(key, sign_in=bool(record.config and record.config.auth == "oauth"), approve_local=approve)

    async def _credentials(self) -> None:
        if not self._selected:
            return
        key = self._selected
        record = self.service.record(key)
        if record.config and record.config.auth == "oauth":
            await self.service.connect(key, sign_in=True)
            return
        result = await self.app.push_screen_wait(ConnectionCredentialsModal(record))
        if result:
            await self.service.set_credentials(key, result["values"], remember=result["remember"])

    async def _remove(self, sign_out: bool = False) -> None:
        if not self._selected:
            return
        key = self._selected
        record = self.service.record(key)
        action = "Sign out" if sign_out else "Remove"
        body = "This disconnects the connection and clears its saved credentials. Other connections are unaffected."
        if not sign_out and record.scope == "workspace":
            body += " A global definition with the same name, if present, will become visible but will stay disconnected."
        confirmed = await self.app.push_screen_wait(ConfirmModal(f"{action} {record.label}?", body, yes_label=action, no_label="Cancel", primary="no"))
        if confirmed:
            if sign_out:
                await self.service.sign_out(key)
            else:
                await self.service.remove(key)
                self._selected = None
                self.query_one("#connections-pages", ContentSwitcher).current = "connections-overview"

    async def _doctor(self) -> None:
        if self._selected:
            lines = await self.service.diagnose(self._selected)
            self.query_one("#connection-diagnostics", Static).update("\n".join(lines))

    async def _refresh_tools(self) -> None:
        if not self._selected:
            return
        record = self.service.record(self._selected)
        client = self.service.manager._clients[record.name]
        if client._client:
            await self.service.connect(self._selected)
