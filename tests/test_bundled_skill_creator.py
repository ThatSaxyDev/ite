from __future__ import annotations

from pathlib import Path
import unittest

from ite.skills.manager import SkillManager


class BundledSkillCreatorTests(unittest.TestCase):
    def test_bundled_skill_creator_is_discoverable_from_project_root(self) -> None:
        manager = SkillManager(Path.cwd())
        manager.discover()
        skill = manager.get("skill-creator")
        self.assertIsNotNone(skill)
        assert skill is not None
        self.assertEqual(skill.source, "shared-project")
        self.assertTrue((skill.directory / "LICENSE.txt").is_file())
        self.assertTrue((skill.directory / "scripts" / "init_skill.py").is_file())
        self.assertTrue((skill.directory / "references" / "openai_yaml.md").is_file())


if __name__ == "__main__":
    unittest.main()
