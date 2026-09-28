from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Static


class RemoteBridgeField(Horizontal):
    def __init__(
        self,
        label: str,
        value: str,
        *,
        copy_value: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self._label = label
        self._value = value
        self._copy_value = copy_value if copy_value is not None else value

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="remote-bridge-field-label")
        yield Static(self._value, classes="remote-bridge-field-value")
        yield Button("Copy", id="copy", classes="remote-bridge-copy", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "copy":
            return
        event.stop()
        value = self._copy_value.strip()
        if not value:
            return
        try:
            self.app.copy_to_clipboard(value)
            self.notify("Copied to clipboard", timeout=2)
        except Exception:
            try:
                import pyperclip

                pyperclip.copy(value)
                self.notify("Copied to clipboard", timeout=2)
            except Exception:
                self.notify(
                    "Failed to copy to clipboard", severity="error", title="Copy Error"
                )


class UpdateCommandBox(Horizontal):
    def __init__(self, command: str = "pipx upgrade ite-agent") -> None:
        super().__init__(id="update-command-box")
        self._command = command

    def compose(self) -> ComposeResult:
        yield Static(self._command, id="update-command-text")
        yield Button("Copy", id="update-command-copy", variant="default")

    def set_command(self, command: str) -> None:
        self._command = command
        try:
            self.query_one("#update-command-text", Static).update(command)
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "update-command-copy":
            return
        event.stop()
        command = self._command.strip()
        if not command:
            return
        try:
            self.app.copy_to_clipboard(command)
            self.notify("Upgrade command copied", timeout=2)
        except Exception:
            try:
                import pyperclip

                pyperclip.copy(command)
                self.notify("Upgrade command copied", timeout=2)
            except Exception:
                self.notify(
                    "Failed to copy command", severity="error", title="Copy Error"
                )


class RemoteBridgeCard(Vertical):
    def __init__(
        self,
        *,
        intro: str,
        runtime_name: str,
        exposure_mode: str,
        host: str,
        port: int | str,
        pair_code: str,
        fingerprint: str,
        connect_uri: str | None = None,
        authenticated_clients: int | None = None,
        trusted_devices: int | None = None,
        footer: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self._intro = intro
        self._runtime_name = str(runtime_name)
        self._exposure_mode = str(exposure_mode)
        self._host = str(host)
        self._port = str(port)
        self._pair_code = str(pair_code)
        self._fingerprint = str(fingerprint)
        self._connect_uri = str(connect_uri or "").strip()
        self._authenticated_clients = authenticated_clients
        self._trusted_devices = trusted_devices
        self._footer = str(footer or "").strip()

    def compose(self) -> ComposeResult:
        yield Static(self._intro, classes="remote-bridge-intro")

        if self._runtime_name:
            yield RemoteBridgeField(
                "Runtime",
                self._runtime_name,
                classes="remote-bridge-field",
            )
        if self._exposure_mode:
            yield RemoteBridgeField(
                "Exposure",
                "LAN" if self._exposure_mode == "lan" else "Local only",
                classes="remote-bridge-field",
            )
        yield RemoteBridgeField("Host", self._host, classes="remote-bridge-field")
        yield RemoteBridgeField("Port", self._port, classes="remote-bridge-field")
        yield RemoteBridgeField(
            "Pair code",
            self._pair_code,
            classes="remote-bridge-field",
        )
        if self._fingerprint:
            yield RemoteBridgeField(
                "Fingerprint",
                self._fingerprint,
                classes="remote-bridge-field wide",
            )
        if self._authenticated_clients is not None:
            yield RemoteBridgeField(
                "Connected phones",
                str(self._authenticated_clients),
                classes="remote-bridge-field",
            )
        if self._trusted_devices is not None:
            yield RemoteBridgeField(
                "Trusted devices",
                str(self._trusted_devices),
                classes="remote-bridge-field",
            )

        if self._connect_uri:
            yield RemoteBridgeField(
                "Secure Connect Link",
                self._connect_uri,
                classes="remote-bridge-field wide emph",
            )

        if self._footer:
            yield Static(self._footer, classes="remote-bridge-footer")
