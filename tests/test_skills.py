import json
import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.skills.manager import SkillManager
from ite.tools.base import ToolInvocation
from ite.tools.builtin.skills import SkillsTool


def _write_skill(root: Path, folder: str, *, name: str, description: str, body: str) -> None:
    skill_dir = root / folder
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


class SkillManagerTests(unittest.TestCase):
    def test_discovery_prefers_later_roots_for_same_skill_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            low = base / "low"
            high = base / "high"
            _write_skill(
                low,
                "reviewer",
                name="code-review",
                description="Low priority copy",
                body="Low instructions.",
            )
            _write_skill(
                high,
                "reviewer",
                name="code-review",
                description="High priority copy",
                body="High instructions.",
            )

            manager = SkillManager(base)
            manager._discovery_roots = lambda: [("low", low), ("high", high)]  # type: ignore[method-assign]
            manager.discover()

            skill = manager.get("code-review")
            self.assertIsNotNone(skill)
            self.assertEqual(skill.description, "High priority copy")
            self.assertEqual(skill.source, "high")

    def test_skill_lookup_supports_folder_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            _write_skill(
                root,
                "impeccable",
                name="design-review",
                description="Review polished UI",
                body="Use strict visual review standards.",
            )

            manager = SkillManager(base)
            manager._discovery_roots = lambda: [("shared-project", root)]  # type: ignore[method-assign]
            manager.discover()

            self.assertIsNotNone(manager.get("impeccable"))
            self.assertIsNotNone(manager.get("design-review"))


class _FakeSession:
    def __init__(self) -> None:
        self.available = [
            {
                "identifier": "design-review",
                "name": "design-review",
                "description": "Review polished UI",
                "source": "shared-project",
            }
        ]
        self.skill = type(
            "Skill",
            (),
            {
                "identifier": "design-review",
                "name": "design-review",
                "description": "Review polished UI",
                "instructions": "Use strict visual review standards.",
                "source": "shared-project",
            },
        )()
        self.active: list[str] = []

    def list_available_skills(self):
        return self.available

    def get_active_skills(self):
        return [self.skill] if self.active else []

    def resolve_skill(self, reference: str):
        return self.skill if reference in {"design-review", "impeccable"} else None

    def activate_skill(self, reference: str):
        if self.resolve_skill(reference) is None:
            return None
        if self.skill.identifier not in self.active:
            self.active.append(self.skill.identifier)
        return self.skill

    def deactivate_skill(self, reference: str):
        if self.resolve_skill(reference) is None or self.skill.identifier not in self.active:
            return None
        self.active = []
        return self.skill

    def clear_active_skills(self):
        self.active = []


class SkillsToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_activate_returns_instructions_and_marks_skill_active(self) -> None:
        tool = SkillsTool(Config(cwd=Path.cwd(), api_key="test"))
        session = _FakeSession()
        tool.set_session(session)

        result = await tool.execute(
            ToolInvocation(
                params={"action": "activate", "skill": "impeccable"},
                cwd=Path.cwd(),
            )
        )

        self.assertTrue(result.success)
        payload = json.loads(result.output)
        self.assertEqual(payload["skill"], "design-review")
        self.assertIn("Use strict visual review standards.", payload["instructions"])
        self.assertEqual(payload["active_skills"], ["design-review"])
