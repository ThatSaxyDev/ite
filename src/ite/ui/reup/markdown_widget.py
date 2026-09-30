"""Markdown widget with copyable code blocks for Textual."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.content import Content
from textual.widgets import Button, Markdown, Static
from textual.widgets._markdown import MarkdownBlock, MarkdownFence, MarkdownStream


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
            Button("📋", classes="copy-button", id="copy-btn"),
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

    def notify_style_update(self) -> None:
        """Override to prevent parent from managing #code-content.
        
        Textual 8.2+ expects #code-content to be a Label, but we use Static.
        Do nothing - let Textual handle it without cache clearing overhead.
        """
        pass

    def set_content(self, content: Content) -> None:
        """Update our Static code body when Markdown appends to a fence."""
        self._content = self._highlighted_code = content
        if self.is_mounted:
            self.query_one("#code-content", Static).update(content)

    async def _update_from_block(self, block: MarkdownBlock) -> None:
        if isinstance(block, MarkdownFence):
            # Textual reuses the last fence while streaming. Keep the clipboard
            # source in sync too, rather than copying the first partial chunk.
            self.code = block.code
        await super()._update_from_block(block)

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
        self.notify("Copied to clipboard", timeout=2)


class CopyableMarkdown(Markdown):
    """Markdown widget with copyable code blocks."""

    _stream: MarkdownStream | None = None

    async def stream_fragment(self, fragment: str) -> None:
        """Append in the background, combining bursts when rendering is busy."""
        if self._stream is None:
            self._stream = Markdown.get_stream(self)
        await self._stream.write(fragment)

    async def finish_stream(self) -> None:
        """Flush all queued text before finalization or removal."""
        if self._stream is not None:
            stream, self._stream = self._stream, None
            await stream.stop()

    async def on_unmount(self) -> None:
        await self.finish_stream()

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
