from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    Input,
    Select,
    Static,
    TextArea,
)

from ite.config.config import MCPServerConfig
from ite.tools.mcp.catalog import CONNECTION_CATALOG
from ite.tools.mcp.service import ConnectionRecord, ConnectionsService

from .modals import ConfirmModal
from .widgets.action_button import FlatActionButton


class ConnectionSetupModal(ModalScreen[dict[str, Any] | None]):
    """Native form for catalog, URL, local, and imported connections."""

    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ConnectionSetupModal { align: center middle; background: $background 65%; }
    ConnectionSetupModal .connection-form { width: 72; max-width: 95%; height: 95%;
        max-height: 95%; background: $surface; border: round $border; padding: 1 2; }
    ConnectionSetupModal .connection-form-scroll { height: 1fr; }
    ConnectionSetupModal Input, ConnectionSetupModal Select { margin-bottom: 1; }
    ConnectionSetupModal Static { height: auto; }
    ConnectionSetupModal .connection-form-title { text-style: bold; margin-bottom: 1; }
    ConnectionSetupModal .connection-form-note { color: $foreground-muted; margin-bottom: 1; }
    ConnectionSetupModal .connection-form-error { color: $text-error; }
    ConnectionSetupModal .connection-form-actions { height: 1; min-height: 1; margin-top: 1; align-horizontal: right; }
    ConnectionSetupModal TextArea { height: 8; }
    """

    def __init__(self, record: ConnectionRecord | None = None) -> None:
        super().__init__()
        self.record = record
        self._initial: tuple[Any, ...] | None = None

    def compose(self) -> ComposeResult:
        config = self.record.config if self.record else None
        with Container(classes="connection-form"):
            yield Static("Edit connection" if self.record else "Add connection", classes="connection-form-title")
            with VerticalScroll(classes="connection-form-scroll"):
                yield Select([("GitHub · repositories and issues", "github"),
                              ("Notion · notes and pages", "notion"),
                              ("Custom connection URL", "url"), ("Local server", "local"),
                              ("Import JSON or TOML", "import")],
                             value="local" if config and config.command else "url",
                             allow_blank=False, id="connection-kind", disabled=bool(self.record))
                yield Static("", id="connection-recipe-note", classes="connection-form-note")
                yield Static("Name")
                yield Input(value=(config.display_name or self.record.name) if config and self.record else "",
                            placeholder="A name you will recognize", id="connection-name")
                yield Static("Availability")
                yield Select([("Available in all projects", "global"), ("Only this project", "workspace")],
                             value=self.record.scope if self.record and self.record.scope != "session" else "workspace",
                             allow_blank=False, id="connection-scope", disabled=bool(self.record))
                with Container(id="connection-url-fields"):
                    yield Static("Server URL")
                    yield Input(value=config.url or "" if config else "", placeholder="https://…/mcp", id="connection-url")
                with Container(id="connection-local-fields"):
                    yield Static("Command")
                    yield Input(value=config.command or "" if config else "", placeholder="uvx, npx, or an executable path", id="connection-command")
                    yield Static("Arguments (JSON list)")
                    yield Input(value=json.dumps(config.args) if config else "[]", id="connection-args")
                    yield Static("Working directory (optional)")
                    yield Input(value=str(config.cwd or "") if config else "", id="connection-cwd")
                    yield Static("Local servers run programs on your computer. You will review startup before connecting.",
                                 classes="connection-form-note")
                with Container(id="connection-import-fields"):
                    yield Static("Paste configuration. Review one connection at a time before saving.", classes="connection-form-note")
                    yield TextArea(id="connection-import", language="json", soft_wrap=True)
                    yield Static("Connection name to import (required if the file contains several)")
                    yield Input(id="connection-import-name")
                yield Static("Authentication")
                yield Select([("No sign-in", "none"), ("Sign in with browser", "oauth"),
                              ("API key or token", "token"), ("Client credentials", "client_credentials")],
                             value=(config.auth if config.auth in {"oauth", "client_credentials"} else "token" if config.auth or config.headers else "none") if config else "none",
                             allow_blank=False, id="connection-auth")
                yield Static("Credentials are entered separately after saving; they are never shown in configuration.", classes="connection-form-note")
                with Collapsible(title="Advanced settings", collapsed=True):
                    yield Static("Transport")
                    yield Select([(value.replace("_", " "), value) for value in
                                  ("auto", "stdio", "streamable_http", "sse", "ws")],
                                 value=config.transport if config else "auto", allow_blank=False, id="connection-transport")
                    yield Static("Environment (JSON object; use the Credentials form for secrets)")
                    yield Input(value=json.dumps(config.env) if config else "{}", id="connection-env", password=True)
                    yield Static("Headers (JSON object; use the Credentials form for secret headers)")
                    yield Input(value=json.dumps(config.headers) if config else "{}", id="connection-headers", password=True)
                    yield Static("Startup timeout (seconds)")
                    yield Input(value=str(config.startup_timeout_sec if config else 30), id="connection-startup")
                    yield Static("Tool call timeout (seconds)")
                    yield Input(value=str(config.call_timeout_sec if config else 60), id="connection-timeout")
                    yield Static("OAuth scopes (space separated)")
                    yield Input(value=" ".join(config.oauth_scopes) if config else "", id="connection-scopes")
                    yield Static("OAuth callback port (optional)")
                    yield Input(value=str(config.oauth_callback_port or "") if config else "", id="connection-port")
                    yield Static("Client-credentials token URL")
                    yield Input(value=config.client_credentials_url or "" if config else "", id="connection-token-url")
                    yield Checkbox("Connect automatically using saved credentials", value=config.auto_connect if config else False, id="connection-auto")
                    yield Checkbox("Inherit all process environment variables", value=config.inherit_environment if config else False, id="connection-inherit")
            yield Static("", id="connection-form-error", classes="connection-form-error")
            with Horizontal(classes="modal-actions resume-actions connection-form-actions"):
                yield FlatActionButton("Cancel", id="connection-cancel")
                yield FlatActionButton("Save", variant="primary", id="connection-save")

    def on_mount(self) -> None:
        self._update_kind()
        self._initial = self._form_values()
        self.query_one("#connection-name", Input).focus()

    def _form_values(self) -> tuple[Any, ...]:
        return tuple(widget.value for widget in self.query(Input)) + tuple(widget.value for widget in self.query(Select)) + (self.query_one(TextArea).text,) + tuple(widget.value for widget in self.query(Checkbox))

    @on(Select.Changed, "#connection-kind")
    def _kind_changed(self, event: Select.Changed) -> None:
        if not self.is_mounted:
            return
        kind = str(event.value)
        recipe = CONNECTION_CATALOG.get(kind)
        if recipe:
            self.query_one("#connection-name", Input).value = recipe.name
            self.query_one("#connection-url", Input).value = recipe.url
            self.query_one("#connection-auth", Select).value = recipe.auth
        self._update_kind()

    def _update_kind(self) -> None:
        kind = str(self.query_one("#connection-kind", Select).value)
        self.query_one("#connection-local-fields").display = kind == "local"
        self.query_one("#connection-url-fields").display = kind not in {"local", "import"}
        self.query_one("#connection-import-fields").display = kind == "import"
        recipe = CONNECTION_CATALOG.get(kind)
        self.query_one("#connection-recipe-note", Static).update(recipe.description if recipe else "")

    @on(Button.Pressed, "#connection-save")
    def _save(self) -> None:
        try:
            values = self.record.config.model_dump(exclude_defaults=True) if self.record and self.record.config else {}
            kind = str(self.query_one("#connection-kind", Select).value)
            label = self.query_one("#connection-name", Input).value.strip()
            if not label:
                raise ValueError("Enter a name for this connection.")
            name = self.record.name if self.record else re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-")
            name = name or "connection"
            scope = str(self.query_one("#connection-scope", Select).value)
            if kind == "import":
                imports = ConnectionsService.import_definitions(self.query_one(TextArea).text)
                selection = self.query_one("#connection-import-name", Input).value.strip()
                if len(imports) > 1 and selection not in imports:
                    raise ValueError("Choose a connection to import: " + ", ".join(imports))
                original = selection or next(iter(imports))
                values = imports[original]
                name = original
            else:
                values.pop("command" if kind != "local" else "url", None)
                if kind == "local":
                    values["command"] = self.query_one("#connection-command", Input).value.strip()
                    values["args"] = json.loads(self.query_one("#connection-args", Input).value)
                    values["cwd"] = self.query_one("#connection-cwd", Input).value.strip() or None
                else:
                    values["url"] = self.query_one("#connection-url", Input).value.strip()
                auth = str(self.query_one("#connection-auth", Select).value)
                previous_auth = values.get("auth")
                if auth in {"oauth", "client_credentials"}:
                    values["auth"] = auth
                elif auth == "token" and previous_auth not in {"oauth", "client_credentials"}:
                    values["auth"] = previous_auth
                else:
                    values["auth"] = None
                if auth != "oauth":
                    values.pop("oauth_scopes", None)
                    values.pop("oauth_callback_port", None)
                else:
                    values["oauth_scopes"] = self.query_one("#connection-scopes", Input).value.split()
                    port = self.query_one("#connection-port", Input).value.strip()
                    values["oauth_callback_port"] = int(port) if port else None
                if auth == "client_credentials":
                    values["client_credentials_url"] = self.query_one("#connection-token-url", Input).value.strip()
                else:
                    for field in list(values):
                        if field.startswith("client_credentials_"):
                            values.pop(field)
                values["transport"] = str(self.query_one("#connection-transport", Select).value)
                values["env"] = json.loads(self.query_one("#connection-env", Input).value)
                values["headers"] = json.loads(self.query_one("#connection-headers", Input).value)
                values["auto_connect"] = self.query_one("#connection-auto", Checkbox).value
                values["inherit_environment"] = self.query_one("#connection-inherit", Checkbox).value
                values["startup_timeout_sec"] = float(self.query_one("#connection-startup", Input).value)
                values["call_timeout_sec"] = float(self.query_one("#connection-timeout", Input).value)
                if kind in CONNECTION_CATALOG:
                    values["provider"] = kind
            values["display_name"] = label
            parsed = MCPServerConfig.model_validate(values)
            self.dismiss({"name": name, "scope": scope, "config": parsed.model_dump(exclude_defaults=True),
                          "credentials_needed": kind != "import" and str(self.query_one("#connection-auth", Select).value) in {"token", "client_credentials"}})
        except Exception as error:  # noqa: BLE001 - native UI boundary renders recoverable errors
            # ValidationError includes raw input values, so never render its repr.
            message = str(error) if isinstance(error, ValueError) and error.__class__ is ValueError else "Check the URL, command, authentication, JSON fields, and timeouts."
            self.query_one("#connection-form-error", Static).update(message)

    @on(Button.Pressed, "#connection-cancel")
    def action_cancel(self) -> None:
        self.run_worker(self._cancel(), exclusive=True)

    async def _cancel(self) -> None:
        if self._initial != self._form_values():
            discard = await self.app.push_screen_wait(ConfirmModal("Discard changes?", "Your unsaved connection settings will be discarded.", yes_label="Discard", no_label="Keep editing", primary="no"))
            if not discard:
                return
        self.dismiss(None)


class ConnectionCredentialsModal(ModalScreen[dict[str, Any] | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ConnectionCredentialsModal { align: center middle; background: $background 65%; }
    ConnectionCredentialsModal .credential-form { width: 66; max-width: 95%; height: 85%;
        max-height: 95%; background: $surface; border: round $border; padding: 1 2; }
    ConnectionCredentialsModal .credential-scroll { height: 1fr; }
    ConnectionCredentialsModal Static { height: auto; }
    ConnectionCredentialsModal Input { margin-bottom: 1; }
    ConnectionCredentialsModal .credential-title { text-style: bold; margin-bottom: 1; }
    ConnectionCredentialsModal .credential-note { color: $foreground-muted; margin-bottom: 1; }
    ConnectionCredentialsModal .credential-actions { height: 1; min-height: 1; margin-top: 1; align-horizontal: right; }
    """

    def __init__(self, record: ConnectionRecord) -> None:
        super().__init__()
        self.record = record

    def compose(self) -> ComposeResult:
        config = self.record.config
        with Container(classes="credential-form"):
            yield Static(f"Credentials · {self.record.label}", classes="credential-title", markup=False)
            with VerticalScroll(classes="credential-scroll"):
                yield Static("Saved credentials use your system keyring. Uncheck Remember to use them only in this session.", classes="credential-note")
                if config and config.auth == "client_credentials":
                    yield Static("Client ID")
                    yield Input(id="credential-id")
                    yield Static("Client secret")
                    yield Input(password=True, id="credential-secret")
                elif config and config.command:
                    yield Static("Environment variable name")
                    yield Input(placeholder="SERVICE_API_KEY", id="credential-key")
                    yield Static("Value")
                    yield Input(password=True, id="credential-secret")
                else:
                    yield Static("Header name")
                    yield Input(value="Authorization", id="credential-key")
                    yield Static("API key or token (Bearer is added for Authorization)")
                    yield Input(password=True, id="credential-secret")
                yield Checkbox("Remember in system keyring", value=True, id="credential-remember")
            yield Static("", id="credential-error")
            with Horizontal(classes="modal-actions resume-actions credential-actions"):
                yield FlatActionButton("Cancel", id="credential-cancel")
                yield FlatActionButton("Save credentials", variant="primary", id="credential-save")

    def on_mount(self) -> None:
        self.query_one("#credential-secret", Input).focus()

    @on(Button.Pressed, "#credential-save")
    def _save(self) -> None:
        secret = self.query_one("#credential-secret", Input).value
        if not secret.strip():
            self.query_one("#credential-error", Static).update("Enter a credential value.")
            return
        config = self.record.config
        values: dict[str, Any]
        if config and config.auth == "client_credentials":
            identifier = self.query_one("#credential-id", Input).value.strip()
            if not identifier:
                self.query_one("#credential-error", Static).update("Enter a client ID.")
                return
            values = {"client_credentials_client_id": identifier, "client_credentials_client_secret": secret}
        else:
            key = self.query_one("#credential-key", Input).value.strip()
            if not key or any(ch.isspace() for ch in key):
                self.query_one("#credential-error", Static).update("Enter a valid header or environment variable name.")
                return
            if config and config.command:
                values = {"env": {key: secret}}
            else:
                value = f"Bearer {secret}" if key.lower() == "authorization" and not secret.lower().startswith("bearer ") else secret
                values = {"headers": {key: value}}
        self.query_one("#credential-secret", Input).value = ""
        self.dismiss({"values": values, "remember": self.query_one("#credential-remember", Checkbox).value})

    @on(Button.Pressed, "#credential-cancel")
    def action_cancel(self) -> None:
        self.query_one("#credential-secret", Input).value = ""
        self.dismiss(None)
