"""Learning command output with a native, keyboard-accessible profile link."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Link, Static


class LearningStatusBody(Vertical):
    DEFAULT_CSS = """
    LearningStatusBody { height: auto; }
    LearningStatusBody Horizontal { height: auto; }
    LearningStatusBody Static { height: auto; }
    LearningStatusBody .learning-profile-line { height: 1; margin-top: 1; }
    LearningStatusBody .learning-profile-prefix { width: auto; color: $foreground-muted; }
    LearningStatusBody Link { width: auto; color: $primary; text-style: underline; }
    LearningStatusBody .learning-status-label { width: 12; color: $foreground-muted; }
    LearningStatusBody .learning-status-value { width: 1fr; }
    LearningStatusBody .learning-enabled { color: $text-success; text-style: bold; }
    LearningStatusBody .learning-disabled { color: $foreground-muted; text-style: bold; }
    LearningStatusBody .learning-commands-title { margin-top: 1; margin-bottom: 1; text-style: bold; }
    LearningStatusBody .learning-command-name { width: 16; color: $text-primary; text-style: bold; }
    LearningStatusBody .learning-command-description { width: 1fr; color: $foreground-muted; }
    """

    def __init__(self, text: str, path: Path) -> None:
        super().__init__()
        self.text = text
        self.path = path.resolve()

    def compose(self) -> ComposeResult:
        for line in self.text.splitlines():
            if line == "Loaded learn.md.":
                with Horizontal(classes="learning-profile-line"):
                    yield Static("Loaded ", classes="learning-profile-prefix")
                    yield Link("learn.md", url=self.path.as_uri())
            elif line == "Learning commands:":
                yield Static("Learning commands", classes="learning-commands-title")
            elif line.startswith("/learn ") and " — " in line:
                usage, description = line.split(" — ", 1)
                with Horizontal():
                    yield Static(usage, classes="learning-command-name", markup=False)
                    yield Static(description, classes="learning-command-description", markup=False)
            elif line.startswith(("Learning mode:", "Objective:", "Next step:", "Hint level:")):
                label, value = line.split(":", 1)
                classes = "learning-status-value"
                if label == "Learning mode":
                    classes += " learning-enabled" if value.strip().startswith("ON") else " learning-disabled"
                with Horizontal():
                    yield Static(label, classes="learning-status-label", markup=False)
                    yield Static(value.strip(), classes=classes, markup=False)
            elif line.strip():
                yield Static(line, markup=False)
