"""Markdown widget with copyable code blocks for Textual."""

from textual.widgets import Markdown
from textual.widgets._markdown import MarkdownFence, MarkdownBlock
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Static, Button
from textual.app import ComposeResult


class CopyableCodeBlock(MarkdownFence):
    """A code block with a copy button in the top-right corner."""

    DEFAULT_CSS = """
    CopyableCodeBlock {
        layout: vertical;
        width: 1fr;
        height: auto;
        padding: 0;
        margin: 1 0;
        overflow: scroll hidden;
        scrollbar-size-horizontal: 0;
        scrollbar-size-vertical: 0;
        color: rgb(210,210,210);
        background: black 10%;
        &:light {
            background: white 30%;
        }
    }

    CopyableCodeBlock > .code-header {
        dock: top;
        height: 1;
        width: 1fr;
        align-horizontal: right;
        background: $surface;
        padding: 0 1;
    }

    CopyableCodeBlock > .code-content {
        padding: 0 1;
    }

    CopyableCodeBlock > .code-header > .copy-button {
        min-width: 0;
        height: 1;
        padding: 0 1;
        background: transparent;
        color: $text-muted;
        border: none;
    }

    CopyableCodeBlock > .code-header > .copy-button:hover {
        background: $surface-lighten-1;
        color: $text;
    }

    CopyableCodeBlock > .code-header > .copy-button:focus {
        background: $surface-lighten-2;
        color: $text;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("c", "copy_code", "Copy", show=True),
    ]

    def compose(self) -> ComposeResult:
        """Compose the code block with a copy button."""
        yield Horizontal(
            Button("⏻", classes="copy-button", id="copy-btn"),
            classes="code-header",
        )
        yield Static(self._highlighted_code, id="code-content", classes="code-content")

    def on_mount(self) -> None:
        """Set up the widget after mounting."""
        # Apply the highlighted code content
        try:
            code_widget = self.query_one("#code-content", Static)
            code_widget.update(self._highlighted_code)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle copy button press."""
        if event.button.id == "copy-btn":
            self.action_copy_code()
            event.stop()

    def action_copy_code(self) -> None:
        """Copy the code to clipboard."""
        code_text = self.code
        if not code_text:
            return

        try:
            # Try Textual's built-in clipboard (OSC 52)
            self.app.copy_to_clipboard(code_text)
            self._notify_copied()
        except Exception:
            # Fallback to pyperclip
            try:
                import pyperclip
                pyperclip.copy(code_text)
                self._notify_copied()
            except Exception:
                self.notify("Failed to copy to clipboard", severity="error", title="Copy Error")

    def _notify_copied(self) -> None:
        """Show a notification that code was copied."""
        lines = len(self.code.splitlines()) if self.code else 0
        self.notify(
            f"Copied {lines} line{'s' if lines != 1 else ''} to clipboard",
            title="Copied",
            timeout=2,
        )


class CopyableMarkdown(Markdown):
    """Markdown widget with copyable code blocks."""

    BLOCKS = {
        **Markdown.BLOCKS,
        "fence": CopyableCodeBlock,
        "code_block": CopyableCodeBlock,
    }
    """Mapping of block names to widget classes."""

    DEFAULT_CSS = """
    CopyableMarkdown {
        layout: stream;
        background: transparent;
    }

    CopyableMarkdown MarkdownFence {
        background: #0e0e10;
        border: round #303236;
        padding: 0 1;
    }
    """