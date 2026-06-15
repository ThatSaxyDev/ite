from __future__ import annotations

import re
from typing import Any

from rich.console import Group
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Static


class ShellToolCard(Vertical):
    def __init__(
        self,
        *,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self._header = Static(classes="shell-card-header")
        self._body = Static(classes="shell-card-body")

    def compose(self) -> ComposeResult:
        yield self._header
        with VerticalScroll(classes="shell-card-scroll"):
            yield self._body

    def set_shell_content(self, *, header: Any, body: Any) -> None:
        self._header.update(header)
        self._body.update(body)
        if self.is_mounted:
            self.call_after_refresh(self._scroll_terminal_end)

    def _scroll_terminal_end(self) -> None:
        try:
            viewport = self.query_one(".shell-card-scroll", VerticalScroll)
        except NoMatches:
            return
        viewport.scroll_end(animate=False)


class CompactToolCard(Static):
    can_focus = True
    BINDINGS = [
        Binding("enter", "toggle_expanded", "Toggle details", show=False),
        Binding("space", "toggle_expanded", "Toggle details", show=False),
    ]

    def __init__(
        self,
        *,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self.expanded = False
        self.has_completed_content = False
        self._header: Text | None = None
        self._compact_blocks: list[Any] = []
        self._full_blocks: list[Any] = []
        self.stack_key = ""
        self._stack_child_mode = False

    def set_tool_content(
        self,
        *,
        header: Text,
        compact_blocks: list[Any],
        full_blocks: list[Any],
        expanded: bool,
    ) -> None:
        self._header = header
        self._compact_blocks = list(compact_blocks)
        self._full_blocks = list(full_blocks)
        self.expanded = expanded
        self.has_completed_content = True
        self._refresh_content()

    def set_stack_child_mode(self, enabled: bool) -> None:
        if self._stack_child_mode == enabled:
            return
        self._stack_child_mode = enabled
        if self.has_completed_content:
            self._refresh_content()

    def action_toggle_expanded(self) -> None:
        if not self.has_completed_content:
            return
        self.expanded = not self.expanded
        self._refresh_content()

    def on_click(self, event: events.Click) -> None:
        if not self.has_completed_content:
            return
        event.stop()
        self.action_toggle_expanded()

    def _refresh_content(self) -> None:
        header = self._disclosure_header()
        blocks = self._visible_blocks()
        self.update(Group(header, *blocks))

    def _disclosure_header(self) -> Text:
        header = Text()
        header.append("▾ " if self.expanded else "▸ ", style="bold")
        if self._stack_child_mode:
            header.append_text(self.stack_child_header())
            return header
        if self._header is not None:
            header.append_text(self._header.copy())
        return header

    def stack_title(self) -> Text:
        return self._header.copy() if self._header is not None else Text("Tool calls")

    def plural_stack_title(self) -> Text:
        title = self.stack_title()
        plain = title.plain
        pluralized = pluralize_tool_title(plain)
        if pluralized == plain:
            return title
        return _replace_text_plain(title, pluralized)

    def stack_child_header(self) -> Text:
        for block in self._compact_blocks:
            if isinstance(block, Text):
                plain = block.plain.strip()
                if plain:
                    return _strip_repeated_child_prefix(block.copy())
            if isinstance(block, str) and block.strip():
                return Text(block.strip())
        return self.stack_title()

    def _visible_blocks(self) -> list[Any]:
        if not self._stack_child_mode:
            return self._full_blocks if self.expanded else self._compact_blocks
        if not self.expanded:
            return []
        child_header = self.stack_child_header().plain.strip()
        blocks = list(self._full_blocks)
        if (
            blocks
            and isinstance(blocks[0], Text)
            and blocks[0].plain.strip() == child_header
        ):
            return blocks[1:]
        return blocks


def pluralize_tool_title(title: str) -> str:
    text = str(title or "").strip()
    match = re.search(r"[A-Za-z]", text)
    prefix = text[: match.start()] if match else ""
    label = text[match.start() :] if match else text
    custom = {
        "Checked folder": "Checked folders",
        "Saved file": "Saved files",
        "Updated file": "Updated files",
        "Applied patch": "Applied patches",
        "Matched files": "Matched file groups",
        "Fetched page": "Fetched pages",
        "Fetched webpage": "Fetched webpages",
        "PDF loaded": "PDFs loaded",
        "Image loaded": "Images loaded",
        "Commit created": "Commits created",
        "Tool completed": "Tools completed",
    }
    if label in custom:
        return f"{prefix}{custom[label]}"
    if label.endswith(" ready"):
        return text
    words = label.split()
    if len(words) >= 2 and (
        words[0].endswith(("ed", "ing")) or words[-1].endswith("ed")
    ):
        return text
    if not label or label.endswith("s"):
        return text
    if len(words) >= 2:
        last = words[-1]
        if last.endswith("y") and len(last) > 1 and last[-2].lower() not in "aeiou":
            words[-1] = last[:-1] + "ies"
        elif last.endswith(("s", "x", "z", "ch", "sh")):
            words[-1] = last + "es"
        else:
            words[-1] = last + "s"
        return f"{prefix}{' '.join(words)}"
    return f"{prefix}{label}s"


def _replace_text_plain(source: Text, plain: str) -> Text:
    replacement = Text()
    replacement.append(plain, style=source.style)
    return replacement


def _strip_repeated_child_prefix(source: Text) -> Text:
    plain = source.plain.strip()
    for prefix in ("Checked ", "Completed reading ", "Finished searching "):
        if plain.startswith(prefix):
            return _replace_text_plain(source, plain)
    return source


class ToolCardStack(Vertical):
    can_focus = True
    BINDINGS = [
        Binding("enter", "toggle_expanded", "Toggle stack", show=False),
        Binding("space", "toggle_expanded", "Toggle stack", show=False),
    ]

    def __init__(
        self,
        *,
        stack_key: str,
        title: Text,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self.stack_key = stack_key
        self.expanded = False
        self._title = title
        self._header = Static(classes="tool-stack-header")
        self._body = Vertical(classes="tool-stack-body")

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body

    async def add_card(self, card: CompactToolCard) -> None:
        card.set_stack_child_mode(True)
        if card.parent is not self._body:
            try:
                await card.remove()
            except Exception:
                pass
            await self._body.mount(card)
        self._refresh_content()

    def action_toggle_expanded(self) -> None:
        self.expanded = not self.expanded
        self._refresh_content()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.action_toggle_expanded()

    def _refresh_content(self) -> None:
        count = len(self._body.children)
        header = Text()
        header.append("▾ " if self.expanded else "▸ ", style="bold")
        header.append_text(self._title.copy())
        header.append(f"  {count} calls", style="dim")
        self._header.update(header)
        self._body.display = self.expanded

    def refresh_title(self, title: Text) -> None:
        self._title = title
        self._refresh_content()
