import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.config.config import Config
from ite.prompts.system import _shell_command_available
from ite.prompts.system import get_system_prompt


class SystemPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def test_system_prompt_prefers_grep_when_rg_unavailable_in_shell(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}, clear=False):
            _shell_command_available.cache_clear()
            with patch(
                "ite.prompts.system.subprocess.run",
                return_value=type("Result", (), {"returncode": 1})(),
            ):
                prompt = get_system_prompt(config)

        self.assertIn("prefer `grep` instead", prompt)
        self.assertIn("Otherwise use `grep` and `find` directly", prompt)

    def test_system_prompt_prefers_rg_when_available_in_shell(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}, clear=False):
            _shell_command_available.cache_clear()
            with patch(
                "ite.prompts.system.subprocess.run",
                return_value=type("Result", (), {"returncode": 0})(),
            ):
                prompt = get_system_prompt(config)

        self.assertIn("`rg` is available in the shell", prompt)
        self.assertIn("prefer `rg` / `rg --files` only when the environment says `rg` is available in the shell", prompt)

    def test_system_prompt_blocks_automatic_install_after_verification_failure(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        prompt = get_system_prompt(config)

        self.assertIn("do not automatically install it with `shell`", prompt)
        self.assertIn("ask whether they want you to install it", prompt)

    def test_system_prompt_prefers_deepest_agents_file_for_current_codebase_questions(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        prompt = get_system_prompt(config)

        self.assertIn(
            "ground the answer in the nearest/deepest applicable AGENTS.md file first",
            prompt,
        )
        self.assertIn(
            "Treat parent files as inherited background unless the user asks about the broader repository",
            prompt,
        )

    def test_system_prompt_prefers_json_tools_for_structured_json_tasks(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        prompt = get_system_prompt(config)

        self.assertIn("Prefer `read_json` when the user asks to inspect `package.json`", prompt)
        self.assertIn("Prefer `edit_json` when the user asks to update JSON keys", prompt)
        self.assertIn("Prefer `read_toml` / `write_toml` for `pyproject.toml`", prompt)
        self.assertIn("Prefer `read_yaml` / `write_yaml` for CI workflows", prompt)
        self.assertIn("Prefer `read_env` / `write_env` for environment variable files", prompt)
        self.assertIn("Prefer `read_pdf` for PDFs and `read_image` for screenshots", prompt)
        self.assertIn("Use `read_file` instead of the structured readers only when exact file text", prompt)

    def test_system_prompt_requires_parallel_subagent_fan_out_before_wait(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        prompt = get_system_prompt(config)

        self.assertIn("prefer a single `spawn_subagents` call that contains all targets", prompt)
        self.assertIn("launch one distinct `spawn_subagent` per target before calling `wait_subagent`", prompt)
        self.assertIn("do not wait after only one launch if more independent targets remain", prompt)
        self.assertIn("do not switch to overlapping local investigation", prompt)
        self.assertEqual(prompt.count("- **Sub-Agents:**"), 1)

    def test_system_prompt_includes_skill_catalog_and_active_skill_instructions(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        prompt = get_system_prompt(
            config,
            skill_context={
                "catalog": [
                    {
                        "identifier": "design-review",
                        "name": "Design Review",
                        "description": "Review polished UI",
                        "source": "shared-project",
                        "user_invocable": "true",
                        "argument_hint": "[AREA=<value>]",
                    }
                ],
                "active": [
                    {
                        "identifier": "design-review",
                        "name": "Design Review",
                        "description": "Review polished UI",
                        "source": "shared-project",
                        "argument_hint": "[AREA=<value>]",
                        "directory": "/tmp/skills/design-review",
                        "skill_file": "/tmp/skills/design-review/SKILL.md",
                        "reference_files": ["reference/typography.md"],
                        "instructions": "Use strict visual review standards.",
                    }
                ],
            },
        )

        self.assertIn("`design-review` (Design Review) [shared-project] user-invocable [AREA=<value>]", prompt)
        self.assertIn("## Active Skill: Design Review", prompt)
        self.assertIn("Argument hint: [AREA=<value>]", prompt)
        self.assertIn("Skill directory: /tmp/skills/design-review", prompt)
        self.assertIn("Skill file: /tmp/skills/design-review/SKILL.md", prompt)
        self.assertIn("References: reference/typography.md", prompt)
        self.assertIn("Reference paths above are relative to the skill directory", prompt)
        self.assertIn("Use strict visual review standards.", prompt)
        self.assertIn("use that skill's workflow before falling back to generic tools", prompt)


if __name__ == "__main__":
    unittest.main()
