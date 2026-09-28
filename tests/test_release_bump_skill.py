from __future__ import annotations

from io import StringIO
from pathlib import Path
import unittest

from rich.console import Console

from ite.skills.manager import SkillManager
from ite.skills.rendering import build_skill_detail_renderable


class ReleaseBumpSkillTests(unittest.TestCase):
    def test_release_bump_skill_is_discoverable(self) -> None:
        manager = SkillManager(Path.cwd())
        manager.discover()
        skill = manager.get("release-bump")
        self.assertIsNotNone(skill)
        assert skill is not None
        self.assertEqual(skill.source, "local-project-override")
        self.assertEqual(skill.author, "Kiishi David")
        self.assertIn("references/release-bump-workflow.md", skill.reference_files)

    def test_release_bump_skill_detail_mentions_required_files(self) -> None:
        manager = SkillManager(Path.cwd())
        manager.discover()
        skill = manager.get("release-bump")
        self.assertIsNotNone(skill)
        assert skill is not None
        renderable = build_skill_detail_renderable(skill, set())
        console = Console(file=StringIO(), force_terminal=False, width=120)
        console.print(renderable)
        output = console.file.getvalue()
        self.assertIn("pyproject.toml", output)
        self.assertIn("src/ite/ui/reup/app.py", output)
        self.assertIn("release-bump-workflow.md", output)
        self.assertIn("Kiishi David", output)


if __name__ == "__main__":
    unittest.main()
