from __future__ import annotations

from pathlib import Path

from textual import events
from textual.message import Message
from textual.widgets import TextArea

from ite.attachment_refs import extract_inline_attachment_refs, parse_dropped_file_paths
from ite.attachments import queue_attachment_paths


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
            # Copied bubbles include full @paths. Restore their bindings while
            # retaining compact references in the composer, including prose.
            app = self.app
            session = getattr(getattr(app, "agent", None), "session", None)
            formatter = getattr(app, "_attachment_ref_for_path", None)
            if session is None or not callable(formatter):
                return
            refs = extract_inline_attachment_refs(event.text)
            paths = [
                str(Path(ref.value).expanduser().resolve())
                for ref in refs
                if Path(ref.value).expanduser().is_absolute() and Path(ref.value).expanduser().is_file()
            ]
            if not paths:
                return
            pending, accepted, errors = queue_attachment_paths(session.pending_attachment_paths, paths)
            session.pending_attachment_paths = pending
            note = getattr(app, "post_attachment_note", None)
            for error in errors:
                if callable(note):
                    note(error)
            text = event.text
            for ref in reversed(refs):
                path = str(Path(ref.value).expanduser().resolve())
                if path in paths:
                    replacement = formatter(Path(path)) if path in accepted else ""
                    text = text[:ref.start] + replacement + ref.trailing + text[ref.end:]
            event.prevent_default()
            event.stop()
            self.replace(text, *self.selection, maintain_selection_offset=False)
            self.focus()
            return

        event.prevent_default()
        event.stop()

        app = self.app
        session = getattr(getattr(app, "agent", None), "session", None)
        accepted = result.paths
        errors = list(result.errors)
        if session is not None and result.paths:
            pending, accepted, limit_errors = queue_attachment_paths(session.pending_attachment_paths, result.paths)
            session.pending_attachment_paths = pending
            errors.extend(limit_errors)

        insert = getattr(app, "_insert_attachment_refs_into_prompt", None)
        if accepted and callable(insert):
            insert(accepted)

        note = getattr(app, "post_attachment_note", None)
        for error in errors:
            if callable(note):
                note(error)
