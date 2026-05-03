from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

from ite.config.config import Config
from ite.git.working_tree import GitActionResult
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


if __name__ == "__main__":
    unittest.main()
