import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from io import StringIO
from unittest.mock import patch

from rich.console import Console
from ite.config.config import Config
from ite.skills.installer import install_skills_from_source
from ite.skills.manager import SkillManager
from ite.skills.rendering import build_skill_detail_renderable
from ite.skills.rendering import build_skills_help_renderable
from ite.skills.rendering import build_skills_overview_renderable
from ite.skills.rendering import build_skills_tool_renderable
from ite.skills.trust import SkillTrustManager
from ite.tools.base import ToolInvocation
from ite.tools.builtin.skills import SkillsTool


def _write_skill(root: Path, folder: str, *, name: str, description: str, body: str) -> None:
    skill_dir = root / folder
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(cwd: Path) -> None:
    _run_git(cwd, "init")
    _run_git(cwd, "config", "user.name", "ITE Tests")
    _run_git(cwd, "config", "user.email", "ite-tests@example.com")


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

    def test_skill_parses_invocation_metadata_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            skill_dir = root / "critique"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: critique\n"
                "description: Evaluate design effectiveness.\n"
                "user-invocable: true\n"
                "argument-hint: \"[AREA=<value>]\"\n"
                "aliases:\n"
                "  - review-ui\n"
                "---\n\n"
                "Use the frontend-design skill first.\n",
                encoding="utf-8",
            )
            reference_dir = skill_dir / "reference"
            reference_dir.mkdir(parents=True, exist_ok=True)
            (reference_dir / "typography.md").write_text("Type rules", encoding="utf-8")

            manager = SkillManager(base)
            manager._discovery_roots = lambda: [("shared-project", root)]  # type: ignore[method-assign]
            manager.discover()

            skill = manager.get("review-ui")
            self.assertIsNotNone(skill)
            self.assertTrue(skill.user_invocable)
            self.assertEqual(skill.argument_hint, "[AREA=<value>]")
            self.assertEqual(skill.reference_files, ["reference/typography.md"])

    def test_discovery_roots_include_common_universal_pack_paths(self) -> None:
        manager = SkillManager(Path.cwd())
        labels = [label for label, _ in manager._discovery_roots()]
        self.assertIn("compat-codex-project", labels)
        self.assertIn("compat-cursor-project", labels)
        self.assertIn("compat-gemini-project", labels)
        self.assertIn("compat-opencode-project", labels)

    def test_untrusted_project_skill_is_marked_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            _write_skill(
                root,
                "critique",
                name="critique",
                description="Evaluate interfaces",
                body="See reference/typography.md before proceeding.",
            )
            trust = SkillTrustManager()
            trust._path = base / "trusted.json"  # type: ignore[attr-defined]
            manager = SkillManager(base, trust_manager=trust)
            manager._discovery_roots = lambda: [("shared-project", root)]  # type: ignore[method-assign]
            manager.discover()

            skill = manager.get("critique")
            self.assertIsNotNone(skill)
            self.assertTrue(skill.requires_trust)
            self.assertFalse(skill.trusted)

    def test_reference_context_prefers_explicitly_mentioned_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            skill_dir = root / "frontend-design"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: frontend-design\ndescription: Design UIs\n---\n\nRead reference/typography.md first.\n",
                encoding="utf-8",
            )
            ref_dir = skill_dir / "reference"
            ref_dir.mkdir(parents=True, exist_ok=True)
            (ref_dir / "typography.md").write_text("Typography guidance", encoding="utf-8")
            (ref_dir / "motion.md").write_text("Motion guidance", encoding="utf-8")

            manager = SkillManager(base)
            manager._discovery_roots = lambda: [("shared-global", root)]  # type: ignore[method-assign]
            manager.discover()
            skill = manager.get("frontend-design")
            self.assertIsNotNone(skill)

            refs = manager.load_reference_context(skill, max_chars=2000, max_files=2)
            self.assertEqual(refs[0]["path"], "reference/typography.md")
            self.assertIn("Typography guidance", refs[0]["content"])

    def test_skill_definition_exposes_directory_for_relative_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            _write_skill(
                root,
                "docx",
                name="docx",
                description="Work with docx files",
                body="Run python scripts/office/unpack.py on the file.",
            )

            manager = SkillManager(base)
            manager._discovery_roots = lambda: [("shared-project", root)]  # type: ignore[method-assign]
            manager.discover()

            skill = manager.get("docx")
            self.assertIsNotNone(skill)
            assert skill is not None
            self.assertEqual(skill.directory, root / "docx")
            self.assertEqual(skill.skill_file, root / "docx" / "SKILL.md")

    def test_overview_renderable_shows_state_counts_and_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            _write_skill(
                root,
                "critique",
                name="critique",
                description="Evaluate interfaces",
                body="Be direct.",
            )
            _write_skill(
                root,
                "frontend-design",
                name="frontend-design",
                description="Push stronger frontend direction",
                body="Use reference/typography.md.",
            )
            trust = SkillTrustManager()
            trust._path = base / "trusted.json"  # type: ignore[attr-defined]
            manager = SkillManager(base, trust_manager=trust)
            manager._discovery_roots = lambda: [("shared-project", root)]  # type: ignore[method-assign]
            manager.discover()

            skill = manager.get("critique")
            self.assertIsNotNone(skill)
            renderable = build_skills_overview_renderable(
                manager.list_skills(),
                {skill.identifier},
            )
            console = Console(file=StringIO(), force_terminal=False, width=120)
            console.print(renderable)
            output = console.file.getvalue()
            self.assertIn("2 installed", output)
            self.assertIn("1 active", output)
            self.assertIn("/skills show <name> inspects", output)
            self.assertIn("critique", output)

    def test_overview_renderable_marks_ite_shared_project_skills_as_bundled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            skill_dir = root / "docx"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: docx\n"
                "description: Work with Word docs.\n"
                "author: ite\n"
                "---\n\n"
                "Use helper scripts.\n",
                encoding="utf-8",
            )

            manager = SkillManager(base)
            manager._discovery_roots = lambda: [("shared-project", root)]  # type: ignore[method-assign]
            manager.discover()

            renderable = build_skills_overview_renderable(manager.list_skills(), set())
            console = Console(file=StringIO(), force_terminal=False, width=120)
            console.print(renderable)
            output = console.file.getvalue()
            self.assertIn("ite bundled", output)

    def test_overview_empty_state_explains_skills_and_core_commands(self) -> None:
        renderable = build_skills_overview_renderable([], set())
        console = Console(file=StringIO(), force_terminal=False, width=120)
        console.print(renderable)
        output = console.file.getvalue()
        self.assertIn("No skills discovered yet.", output)
        self.assertIn("Skills are reusable instruction bundles.", output)
        self.assertIn("/skills", output)
        self.assertIn("/skills show <name>", output)
        self.assertIn("/skills use <name>", output)

    def test_help_renderable_explains_show_vs_use(self) -> None:
        renderable = build_skills_help_renderable()
        console = Console(file=StringIO(), force_terminal=False, width=120)
        console.print(renderable)
        output = console.file.getvalue()
        self.assertIn("Skills are optional instruction bundles", output)
        self.assertIn("/skills help", output)
        self.assertIn("Inspect a skill without activating it.", output)
        self.assertIn("Active skills shape the current session", output)

    def test_detail_renderable_includes_metadata_references_and_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            skill_dir = root / "polish"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: polish\n"
                "description: Tighten the finish quality.\n"
                "user-invocable: true\n"
                "argument-hint: \"[AREA=<value>]\"\n"
                "author: Team iTE\n"
                "tags:\n"
                "  - ui\n"
                "  - critique\n"
                "---\n\n"
                "Review spacing and hierarchy.\n",
                encoding="utf-8",
            )
            reference_dir = skill_dir / "reference"
            reference_dir.mkdir(parents=True, exist_ok=True)
            (reference_dir / "typography.md").write_text("Type rules", encoding="utf-8")

            manager = SkillManager(base)
            manager._discovery_roots = lambda: [("shared-global", root)]  # type: ignore[method-assign]
            manager.discover()

            skill = manager.get("polish")
            self.assertIsNotNone(skill)
            renderable = build_skill_detail_renderable(skill, set())
            console = Console(file=StringIO(), force_terminal=False, width=120)
            console.print(renderable)
            output = console.file.getvalue()
            self.assertIn("polish", output)
            self.assertNotIn("arguments", output)
            self.assertNotIn("[AREA=<value>]", output)
            self.assertIn("reference/typography.md", output)
            self.assertIn("Review spacing and hierarchy.", output)

    def test_detail_renderable_marks_ite_shared_project_skills_as_bundled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            skill_dir = root / "pdf"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: pdf\n"
                "description: Work with PDFs.\n"
                "author: ite\n"
                "---\n\n"
                "Render when layout matters.\n",
                encoding="utf-8",
            )

            manager = SkillManager(base)
            manager._discovery_roots = lambda: [("shared-project", root)]  # type: ignore[method-assign]
            manager.discover()

            skill = manager.get("pdf")
            self.assertIsNotNone(skill)
            renderable = build_skill_detail_renderable(skill, set())
            console = Console(file=StringIO(), force_terminal=False, width=120)
            console.print(renderable)
            output = console.file.getvalue()
            self.assertIn("ite bundled", output)

    def test_tool_renderable_clarifies_shown_skill_is_not_the_active_skill(self) -> None:
        payload = {
            "action": "show",
            "available_count": 21,
            "active_skills": ["audit"],
            "skill": "frontend-design",
            "name": "frontend-design",
            "description": "Create distinctive production interfaces.",
            "user_invocable": False,
            "argument_hint": "",
            "reference_files": [
                "reference/color-and-contrast.md",
                "reference/interaction-design.md",
            ],
            "trusted": True,
            "requires_trust": False,
            "instructions": "Use strong hierarchy.\n\nAvoid generic layouts.",
        }

        renderable = build_skills_tool_renderable(payload)
        self.assertIsNotNone(renderable)
        console = Console(file=StringIO(), force_terminal=False, width=120)
        console.print(renderable)
        output = console.file.getvalue()
        self.assertIn("frontend-design", output)
        self.assertIn("inspected", output)
        self.assertNotIn("active skills", output)
        self.assertNotIn("audit", output)
        self.assertNotIn("arguments", output)
        self.assertNotIn("references", output)
        self.assertNotIn("instructions", output)


class SkillInstallerTests(unittest.TestCase):
    def test_install_skills_from_universal_pack_prefers_supported_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            pack = base / "pack"
            source_root = pack / ".agents" / "skills"
            _write_skill(
                source_root,
                "critique",
                name="critique",
                description="Evaluate interfaces",
                body="Be direct.",
            )
            destination = base / "dest"
            result = install_skills_from_source(pack, destination)

            self.assertEqual(result.detected_root, ".agents/skills")
            self.assertEqual(result.installed_skill_names, ["critique"])
            self.assertTrue((destination / "critique" / "SKILL.md").is_file())

    def test_install_skills_from_git_url_clones_repo_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            repo = base / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            _init_repo(repo)
            _write_skill(
                repo / ".agents" / "skills",
                "critique",
                name="critique",
                description="Evaluate interfaces",
                body="Be direct.",
            )
            _run_git(repo, "add", "-A", "--", ".")
            _run_git(repo, "commit", "-m", "add skills")

            destination = base / "dest"
            result = install_skills_from_source(repo.as_uri(), destination)

            self.assertEqual(result.detected_root, ".agents/skills")
            self.assertEqual(result.installed_skill_names, ["critique"])
            self.assertTrue((destination / "critique" / "SKILL.md").is_file())

    def test_install_skills_from_github_shorthand_uses_github_clone_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            destination = base / "dest"

            def fake_run(args, **kwargs):
                clone_target = Path(args[-1])
                _write_skill(
                    clone_target / ".agents" / "skills",
                    "critique",
                    name="critique",
                    description="Evaluate interfaces",
                    body="Be direct.",
                )
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with patch("ite.skills.installer.subprocess.run", side_effect=fake_run) as run:
                result = install_skills_from_source("openai/agent-skills", destination)

            self.assertEqual(result.installed_skill_names, ["critique"])
            self.assertTrue((destination / "critique" / "SKILL.md").is_file())
            run.assert_called_once()
            clone_args = run.call_args.args[0]
            self.assertEqual(clone_args[:4], ["git", "clone", "--depth", "1"])
            self.assertEqual(clone_args[4], "https://github.com/openai/agent-skills.git")


class _FakeSession:
    def __init__(self) -> None:
        self.available = [
            {
                "identifier": "design-review",
                "name": "design-review",
                "description": "Review polished UI",
                "source": "shared-project",
                "user_invocable": "true",
                "argument_hint": "[AREA=<value>]",
                "references": "1",
                "trusted": "true",
                "requires_trust": "false",
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
                "user_invocable": True,
                "argument_hint": "[AREA=<value>]",
                "reference_files": ["reference/typography.md"],
                "metadata": {"user-invocable": True},
            },
        )()
        self.active: list[str] = []
        self.trusted = False

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

    def trust_skill_workspace(self):
        self.trusted = True

    def untrust_skill_workspace(self):
        self.trusted = False
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
        self.assertTrue(payload["user_invocable"])
        self.assertEqual(payload["argument_hint"], "[AREA=<value>]")
        self.assertEqual(payload["reference_files"], ["reference/typography.md"])

    async def test_trust_action_is_supported(self) -> None:
        tool = SkillsTool(Config(cwd=Path.cwd(), api_key="test"))
        session = _FakeSession()
        tool.set_session(session)

        result = await tool.execute(
            ToolInvocation(
                params={"action": "trust"},
                cwd=Path.cwd(),
            )
        )

        self.assertTrue(result.success)
        self.assertTrue(session.trusted)
