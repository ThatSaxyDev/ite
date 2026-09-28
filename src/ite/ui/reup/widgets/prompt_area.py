from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea

from ite.attachment_refs import parse_dropped_file_paths
from ite.attachments import MAX_ATTACHMENTS


class ReupPromptTextArea(TextArea):
    class Submitted(Message):
        pass

    BINDINGS = list(TextArea.BINDINGS)

    def action_submit(self) -> None:
        self.post_message(self.Submitted())

    def action_newline(self) -> None:
        self.insert("\n")

    def on_key(self, event: events.Key) -> None:
        handler = getattr(self.app, "handle_prompt_palette_key", None)
        if callable(handler) and handler(event):
            event.stop()
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            return
        if event.key in {"shift+enter", "ctrl+j"}:
            event.stop()
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            self.action_newline()
            return
        if event.key == "enter":
            event.stop()
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            self.action_submit()
            return

    async def on_paste(self, event: events.Paste) -> None:
        """Intercept terminal drag-and-drop deliveries sent as bracketed paste.

        Terminals deliver dropped files as pasted text in assorted formats
        (bare/quoted/escaped paths, ``file://`` URIs, newline batches). When
        the payload is purely path-like we stage the valid files as
        attachments and swallow the text; anything containing prose falls
        through so normal clipboard pastes keep working.
        """
        result = parse_dropped_file_paths(event.text or "")
        if result.path_like_count == 0 or result.prose_count > 0:
            return

        event.prevent_default()
        event.stop()

        app = self.app
        session = getattr(getattr(app, "agent", None), "session", None)
        if session is not None and result.paths:
            pending = list(session.pending_attachment_paths)
            for path in result.paths:
                if path not in pending:
                    pending.append(path)
            session.pending_attachment_paths = pending[:MAX_ATTACHMENTS]

        insert = getattr(app, "_insert_attachment_refs_into_prompt", None)
        if result.paths and callable(insert):
            insert(result.paths)

        note = getattr(app, "post_attachment_note", None)
        for error in result.errors:
            if callable(note):
                note(error)
