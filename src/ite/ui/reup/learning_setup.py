"""A native, keyboard-accessible learning profile interview and review."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, ContentSwitcher, Label, Select, Static, TextArea

from ite.agent.learning_profile import (
    PACES,
    LearningPreferences,
    build_profile,
    save_profile,
)


class LearningSetupModal(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+enter", "next", "Next / save"),
    ]
    DEFAULT_CSS = """
    LearningSetupModal { align: center middle; background: $background 70%; }
    LearningSetupModal .learning-setup-shell {
        width: 74; max-width: 95%; height: 27; max-height: 95%;
        padding: 1 2; border: round $border; background: $surface;
    }
    LearningSetupModal.reviewing .learning-setup-shell { height: 95%; max-height: 100%; }
    LearningSetupModal .learning-setup-title { height: 1; text-style: bold; }
    LearningSetupModal #learn-setup-help { height: 2; color: $foreground-muted; margin-bottom: 1; }
    LearningSetupModal ContentSwitcher { height: 1fr; }
    LearningSetupModal VerticalScroll { height: 1fr; }
    LearningSetupModal .learning-question { height: auto; margin-bottom: 1; }
    LearningSetupModal TextArea { height: 6; background: $panel; }
    LearningSetupModal #learn-profile-preview { height: 1fr; }
    LearningSetupModal Select { margin-bottom: 1; }
    LearningSetupModal #learn-setup-error { height: auto; max-height: 3; color: $text-error; }
    LearningSetupModal .learning-actions { height: 3; margin-top: 1; align-horizontal: right; }
    LearningSetupModal Button { min-width: 10; margin-left: 1; }
    """

    def __init__(
        self, path: Path, original: str | None, *, require_idle: Callable[[], None]
    ) -> None:
        super().__init__()
        self.path = path
        self.original = original
        self.require_idle = require_idle
        self.preferences = LearningPreferences.from_profile(original or "")
        self.step = 0

    def compose(self) -> ComposeResult:
        with Container(classes="learning-setup-shell"):
            yield Label(
                "Set up learning · 1 of 3",
                id="learn-setup-title",
                classes="learning-setup-title",
            )
            yield Static(
                "A few short answers, then review before saving. Esc cancels without changes.",
                id="learn-setup-help",
            )
            with ContentSwitcher(initial="learn-goal-page", id="learn-setup-pages"):
                with VerticalScroll(id="learn-goal-page"):
                    yield Static(
                        "What do you want to build or understand?",
                        classes="learning-question",
                    )
                    yield TextArea(
                        self.preferences.objective,
                        id="learn-setup-goal",
                        soft_wrap=True,
                    )
                    yield Static(
                        "Optional. You can discover your goal in the conversation.",
                        classes="learning-question",
                    )
                with VerticalScroll(id="learn-experience-page"):
                    yield Static(
                        "What do you already know, and what feels unfamiliar?",
                        classes="learning-question",
                    )
                    yield TextArea(
                        self.preferences.starting_point,
                        id="learn-setup-experience",
                        soft_wrap=True,
                    )
                    yield Static(
                        "A sentence is enough. Leave blank if you are unsure.",
                        classes="learning-question",
                    )
                with VerticalScroll(id="learn-style-page"):
                    yield Static(
                        "How should iTE guide you?", classes="learning-question"
                    )
                    yield Select(
                        [(pace, pace) for pace in PACES],
                        value=self.preferences.pace
                        if self.preferences.pace in PACES
                        else PACES[0],
                        allow_blank=False,
                        id="learn-setup-pace",
                    )
                    yield Static(
                        "Anything else? Language, feedback style, or accessibility needs.",
                        classes="learning-question",
                    )
                    yield TextArea(
                        self.preferences.preferences,
                        id="learn-setup-preferences",
                        soft_wrap=True,
                    )
                with Container(id="learn-review-page"):
                    yield TextArea("", id="learn-profile-preview", soft_wrap=True)
            yield Static("", id="learn-setup-error", markup=False)
            with Horizontal(classes="learning-actions"):
                yield Button("Cancel", id="learn-setup-cancel")
                yield Button("Back", id="learn-setup-back", disabled=True)
                yield Button("Next", id="learn-setup-next", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#learn-setup-goal", TextArea).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "learn-setup-cancel":
            self.action_cancel()
        elif event.button.id == "learn-setup-back":
            self.step = max(0, self.step - 1)
            self._show_step()
        elif event.button.id == "learn-setup-next":
            self.action_next()

    def action_next(self) -> None:
        self.query_one("#learn-setup-error", Static).update("")
        try:
            if self.step == 3:
                self.require_idle()
                save_profile(
                    self.path,
                    self.query_one("#learn-profile-preview", TextArea).text,
                    expected=self.original,
                )
                self.dismiss(True)
                return
            if self.step == 2:
                self.preferences = LearningPreferences(
                    objective=self.query_one("#learn-setup-goal", TextArea).text,
                    starting_point=self.query_one(
                        "#learn-setup-experience", TextArea
                    ).text,
                    pace=str(self.query_one("#learn-setup-pace", Select).value),
                    preferences=self.query_one(
                        "#learn-setup-preferences", TextArea
                    ).text,
                )
                self.query_one("#learn-profile-preview", TextArea).load_text(
                    build_profile(self.original, self.preferences)
                )
            self.step += 1
            self._show_step()
        except (OSError, ValueError) as exc:
            self.query_one("#learn-setup-error", Static).update(str(exc))

    def _show_step(self) -> None:
        self.set_class(self.step == 3, "reviewing")
        pages = (
            "learn-goal-page",
            "learn-experience-page",
            "learn-style-page",
            "learn-review-page",
        )
        focus = (
            "learn-setup-goal",
            "learn-setup-experience",
            "learn-setup-pace",
            "learn-profile-preview",
        )
        self.query_one("#learn-setup-pages", ContentSwitcher).current = pages[self.step]
        self.query_one("#learn-setup-title", Label).update(
            "Review learn.md"
            if self.step == 3
            else f"Set up learning · {self.step + 1} of 3"
        )
        self.query_one("#learn-setup-help", Static).update(
            "Existing instructions are preserved. Review or edit the full file below; Save applies it now."
            if self.step == 3
            else "A few short answers, then review before saving. Esc cancels without changes."
        )
        self.query_one("#learn-setup-back", Button).disabled = self.step == 0
        self.query_one("#learn-setup-next", Button).label = (
            "Save" if self.step == 3 else "Next"
        )
        self.query_one(f"#{focus[self.step]}").focus()
