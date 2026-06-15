from __future__ import annotations

import shlex
from pathlib import Path

from textual import events
from textual.message import Message
from textual.widgets import TextArea

from ite.attachments import MAX_ATTACHMENTS

_MAX_PATH_LENGTH = 255  # macOS filename component limit — guard against paste-as-path


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
        """Handle paste events to intercept file paths and stage them as attachments.

        When a user drags a file into the terminal (or pastes a file path),
        the terminal may send the file path as text in the paste event.
        We detect valid file paths, stage them, and insert attachment refs.
        """
        app = self.app
        raw = (event.text or "").strip()
        if not raw:
            return

        candidates: list[str]
        if "\n" in raw:
            candidates = [
                line.strip().strip('"').strip("'")
                for line in raw.splitlines()
                if line.strip()
            ]
        else:
            try:
                candidates = shlex.split(raw)
            except ValueError:
                candidates = [raw.strip().strip('"').strip("'")]

        if not candidates or len(candidates) > MAX_ATTACHMENTS:
            return

        paths: list[str] = []
        for candidate in candidates:
            if not any(
                sep in candidate for sep in ("/", "\\")
            ) and not candidate.startswith("~"):
                continue
            if len(candidate) > _MAX_PATH_LENGTH:
                continue
            path = Path(candidate).expanduser()
            if not path.exists() or not path.is_file():
                continue
            paths.append(str(path))

        if not paths:
            return

        if app.agent and app.agent.session:
            pending = list(app.agent.session.pending_attachment_paths)
            for p in paths:
                if p not in pending:
                    pending.append(p)
            app.agent.session.pending_attachment_paths = pending[:MAX_ATTACHMENTS]

        app._insert_attachment_refs_into_prompt(paths)

        event.prevent_default()
        event.stop()
