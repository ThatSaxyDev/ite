from __future__ import annotations

from typing import Any

from textual.widgets import Button


class FlatActionButton(Button):
    """Compact action using the existing native modal button treatment."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["compact"] = True
        super().__init__(*args, **kwargs)

    DEFAULT_CSS = """
    FlatActionButton.-style-default {
        height: 1;
        min-height: 1;
        width: auto;
        min-width: 12;
        border: none;
        padding: 0 1;
        margin-left: 1;
        text-style: bold;
        background: $panel;
        color: $foreground;
    }
    FlatActionButton.-style-default:hover { background: $panel-lighten-1; }
    FlatActionButton.-style-default:focus { border: none; text-style: bold underline; }
    FlatActionButton.-style-default.-primary {
        background: $primary; color: $button-color-foreground;
    }
    FlatActionButton.-style-default.-primary:hover { background: $primary-lighten-1; }
    FlatActionButton.-style-default.-success {
        background: $success; color: $button-color-foreground;
    }
    FlatActionButton.-style-default.-success:hover { background: $success-lighten-1; }
    FlatActionButton.-style-default.-warning {
        background: $warning; color: $button-color-foreground;
    }
    FlatActionButton.-style-default.-warning:hover { background: $warning-lighten-1; }
    FlatActionButton.-style-default:disabled {
        background: $panel; color: $foreground-muted; text-style: none;
    }
    """
