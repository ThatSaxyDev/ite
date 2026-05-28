from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import PropertyMock
from unittest.mock import patch

from ite.config.config import Config
from ite.git.working_tree import GitActionResult
from ite.ui.reup.app import ChangeReviewSidePanel
from ite.ui.reup.app import ReupApp


class ChangeReviewCommitTests(unittest.IsolatedAsyncioTestCase):
    async def test_commit_actions_hide_panel_before_git_work_starts(self) -> None:
        for action in ("commit", "commit_push"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as td:
                app = ReupApp(Config(cwd=td))
                events: list[str] = []
                push_values: list[bool] = []

                async def hide_panel() -> None:
                    events.append("hide")

                def commit_changes(_cwd: Path, **kwargs) -> GitActionResult:
                    events.append("commit")
                    push_values.append(bool(kwargs.get("push")))
                    return GitActionResult(True, "Committed changes.")

                with (
                    patch.object(
                        app,
                        "_get_change_review_widget",
                        return_value=SimpleNamespace(disabled=False),
                    ),
                    patch.object(
                        app,
                        "_open_commit_modal",
                        new=AsyncMock(
                            return_value={
                                "action": action,
                                "include_unstaged": True,
                                "message": "test commit",
                            }
                        ),
                    ),
                    patch.object(app, "_hide_change_review_panel", side_effect=hide_panel),
                    patch.object(
                        app,
                        "_refresh_change_review_source",
                        new=AsyncMock(),
                    ),
                    patch.object(app, "post_notice"),
                    patch.object(app, "post_system"),
                    patch("ite.ui.reup.app.commit_changes", side_effect=commit_changes),
                ):
                    await app._run_change_review_commit()

                self.assertEqual(events, ["hide", "commit"])
                self.assertEqual(push_values, [action == "commit_push"])


class ChangeReviewResponsiveLayoutTests(unittest.TestCase):
    def test_panel_switches_to_narrow_mode_and_shortens_labels(self) -> None:
        def stateful_label() -> SimpleNamespace:
            widget = SimpleNamespace(value=None)
            widget.update = lambda value: setattr(widget, "value", value)
            return widget

        panel = ChangeReviewSidePanel(id="change-review-panel")
        widgets = {
            "#change-review-close": SimpleNamespace(label="Close"),
            "#change-review-stage-all": stateful_label(),
            "#change-review-discard-all": stateful_label(),
            "#change-review-commit": stateful_label(),
            "#change-review-stage-file": stateful_label(),
            "#change-review-unstage-file": stateful_label(),
            "#change-review-discard-file": stateful_label(),
        }

        with patch.object(
            ChangeReviewSidePanel,
            "size",
            new_callable=PropertyMock,
            return_value=SimpleNamespace(width=42),
        ), patch.object(
            panel, "query_one", side_effect=lambda selector, *_args: widgets[selector]
        ):
            panel._refresh_layout_mode()

        self.assertTrue(panel.has_class("narrow"))
        self.assertFalse(panel.has_class("compact"))
        self.assertEqual(widgets["#change-review-close"].label, "Close")
        self.assertEqual(widgets["#change-review-discard-all"].value, "Discard")
        self.assertEqual(widgets["#change-review-discard-file"].value, "Discard")

    def test_bulk_action_label_tracks_panel_width_mode(self) -> None:
        panel = ChangeReviewSidePanel(id="change-review-panel")
        panel.add_class("wide")
        self.assertEqual(panel.bulk_action_label("stage"), "Stage All")
        self.assertEqual(panel.bulk_action_label("unstage"), "Unstage All")

        panel.remove_class("wide")
        panel.add_class("compact")
        self.assertEqual(panel.bulk_action_label("stage"), "Stage")
        self.assertEqual(panel.bulk_action_label("unstage"), "Unstage")

    def test_commit_click_routes_to_commit_worker(self) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))
        event = SimpleNamespace(stopped=False)
        event.stop = lambda: setattr(event, "stopped", True)

        with patch.object(app, "run_worker") as run_worker, patch.object(
            app, "_run_change_review_commit", return_value=None
        ) as commit:
            app.on_change_review_commit(event)

        commit.assert_called_once_with()
        run_worker.assert_called_once()
        self.assertTrue(event.stopped)

    def test_repeated_layout_refresh_does_not_rewrite_widgets(self) -> None:
        def stateful_label() -> SimpleNamespace:
            widget = SimpleNamespace(value=None, updates=0)

            def update(value: str) -> None:
                widget.value = value
                widget.updates += 1

            widget.update = update
            return widget

        panel = ChangeReviewSidePanel(id="change-review-panel")
        widgets = {
            "#change-review-close": SimpleNamespace(label="Close"),
            "#change-review-stage-all": stateful_label(),
            "#change-review-discard-all": stateful_label(),
            "#change-review-commit": stateful_label(),
            "#change-review-stage-file": stateful_label(),
            "#change-review-unstage-file": stateful_label(),
            "#change-review-discard-file": stateful_label(),
        }

        with patch.object(
            ChangeReviewSidePanel,
            "size",
            new_callable=PropertyMock,
            return_value=SimpleNamespace(width=42),
        ), patch.object(
            panel, "query_one", side_effect=lambda selector, *_args: widgets[selector]
        ):
            panel._refresh_layout_mode()
            panel._refresh_layout_mode()

        self.assertEqual(widgets["#change-review-stage-all"].updates, 1)


if __name__ == "__main__":
    unittest.main()
