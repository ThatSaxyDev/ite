from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ite.config.loader import get_workspace_agents_recommendation


class WorkspaceAgentsRecommendationTests(unittest.TestCase):
    def test_recommends_init_when_workspace_has_no_local_instruction_file(self) -> None:
        with TemporaryDirectory() as td:
            workspace = Path(td)

            recommendation = get_workspace_agents_recommendation(workspace)

            self.assertIsNotNone(recommendation)
            assert recommendation is not None
            self.assertEqual(recommendation.reason, "missing")
            self.assertEqual(recommendation.command, "/init")

    def test_does_not_recommend_when_local_agents_file_is_fresh(self) -> None:
        with TemporaryDirectory() as td:
            workspace = Path(td)
            agents_md = workspace / "AGENTS.md"
            agents_md.write_text("# AGENTS.md\n", encoding="utf-8")

            recommendation = get_workspace_agents_recommendation(
                workspace,
                now=datetime.now(timezone.utc),
                stale_after_days=30,
            )

            self.assertIsNone(recommendation)

    def test_recommends_init_force_when_local_agents_file_is_stale(self) -> None:
        with TemporaryDirectory() as td:
            workspace = Path(td)
            agents_md = workspace / "AGENTS.md"
            agents_md.write_text("# AGENTS.md\n", encoding="utf-8")
            now = datetime.now(timezone.utc)
            stale_time = now - timedelta(days=45)
            stale_timestamp = stale_time.timestamp()
            agents_md.touch()
            os.utime(str(agents_md), (stale_timestamp, stale_timestamp))

            recommendation = get_workspace_agents_recommendation(
                workspace,
                now=now,
                stale_after_days=30,
            )

            self.assertIsNotNone(recommendation)
            assert recommendation is not None
            self.assertEqual(recommendation.reason, "stale")
            self.assertEqual(recommendation.command, "/init --force")
            self.assertEqual(recommendation.file_path, agents_md.resolve())
            self.assertGreaterEqual(recommendation.age_days or 0, 45)
