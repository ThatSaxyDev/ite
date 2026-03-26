from __future__ import annotations

from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
