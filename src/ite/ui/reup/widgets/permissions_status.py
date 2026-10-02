"""Themed permissions summary shared by native command cards."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from ite.config.config import Config, PermissionMode
from ite.safety.permissions import DESCRIPTIONS, LABELS, current_mode


class PermissionsStatusBody(Vertical):
    DEFAULT_CSS = """
    PermissionsStatusBody { height: auto; }
    PermissionsStatusBody Horizontal { height: auto; }
    PermissionsStatusBody Static { height: auto; }
    PermissionsStatusBody .permission-label { width: 12; color: $foreground-muted; }
    PermissionsStatusBody .permission-value { width: 1fr; text-style: bold; color: $text-primary; }
    PermissionsStatusBody .permission-automatic { color: $text-success; }
    PermissionsStatusBody .permission-full { color: $text-warning; }
    PermissionsStatusBody .permission-scope { width: 1fr; color: $foreground-muted; }
    PermissionsStatusBody .permission-options-title { margin-top: 1; margin-bottom: 1; text-style: bold; }
    PermissionsStatusBody .permission-option-label { width: 18; color: $text-primary; text-style: bold; }
    PermissionsStatusBody .permission-option-description { width: 1fr; color: $foreground-muted; }
    PermissionsStatusBody .permission-footer { margin-top: 1; color: $foreground-muted; }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.mode = current_mode(config)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("Access", classes="permission-label")
            yield Static(
                LABELS[self.mode] if self.mode else "Custom",
                classes=f"permission-value permission-{self.mode.value if self.mode else 'custom'}",
            )
        with Horizontal():
            yield Static("Applies to", classes="permission-label")
            yield Static("All workspaces", classes="permission-scope")
        yield Static("Permissions options", classes="permission-options-title")
        for mode in PermissionMode:
            with Horizontal():
                yield Static(LABELS[mode], classes="permission-option-label")
                yield Static(
                    DESCRIPTIONS[mode], classes="permission-option-description"
                )
        yield Static("Use /permissions to change access.", classes="permission-footer")
