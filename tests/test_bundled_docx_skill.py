from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from ite.skills.manager import SkillManager


class BundledDocxSkillTests(unittest.TestCase):
    def test_bundled_docx_skill_is_discoverable(self) -> None:
        manager = SkillManager(Path.cwd())
        manager.discover()
        skill = manager.get("docx")
        self.assertIsNotNone(skill)
        assert skill is not None
        self.assertEqual(skill.source, "shared-project")
        self.assertTrue((skill.directory / "scripts" / "extract_docx.py").is_file())
        self.assertTrue((skill.directory / "scripts" / "inspect_docx.py").is_file())
        self.assertTrue((skill.directory / "scripts" / "write_docx.py").is_file())
        self.assertTrue((skill.directory / "scripts" / "render_docx.py").is_file())
        self.assertTrue((skill.directory / "references" / "document-recipes.md").is_file())

    def test_bundled_docx_scripts_can_create_and_extract(self) -> None:
        skill_dir = Path.cwd() / ".agents" / "skills" / "docx"
        write_script = skill_dir / "scripts" / "write_docx.py"
        validate_script = skill_dir / "scripts" / "validate_docx.py"
        extract_script = skill_dir / "scripts" / "extract_docx.py"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "draft.md"
            output = root / "draft.docx"
            extracted = root / "draft.txt"
            source.write_text("Hello world\n\nSecond paragraph\n", encoding="utf-8")

            for command in (
                ["python3", str(write_script), str(source), str(output), "--title", "Demo"],
                ["python3", str(validate_script), str(output)],
                ["python3", str(extract_script), str(output), "--format", "text", "--output", str(extracted)],
            ):
                subprocess.run(command, check=True, capture_output=True, text=True)

            text = extracted.read_text(encoding="utf-8")
            self.assertIn("Demo", text)
            self.assertIn("Hello world", text)
            self.assertIn("Second paragraph", text)

    def test_bundled_docx_scripts_can_inspect_replace_and_use_template(self) -> None:
        skill_dir = Path.cwd() / ".agents" / "skills" / "docx"
        write_script = skill_dir / "scripts" / "write_docx.py"
        inspect_script = skill_dir / "scripts" / "inspect_docx.py"
        replace_script = skill_dir / "scripts" / "replace_text.py"
        extract_script = skill_dir / "scripts" / "extract_docx.py"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "template.docx"
            replaced = root / "template-updated.docx"
            extracted = root / "template.txt"

            subprocess.run(
                ["python3", str(write_script), str(source), "--template", "memo", "--title", "Team Update"],
                check=True,
                capture_output=True,
                text=True,
            )
            inspect_result = subprocess.run(
                ["python3", str(inspect_script), str(source)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "python3",
                    str(replace_script),
                    str(source),
                    str(replaced),
                    "--replace",
                    "Summary",
                    "Executive Summary",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["python3", str(extract_script), str(replaced), "--output", str(extracted)],
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(inspect_result.stdout)
            self.assertEqual(payload["validation_errors"], [])
            self.assertGreater(payload["paragraph_count"], 0)
            self.assertIn("Team Update", "\n".join(payload["preview"]))
            text = extracted.read_text(encoding="utf-8")
            self.assertIn("Executive Summary", text)


if __name__ == "__main__":
    unittest.main()
