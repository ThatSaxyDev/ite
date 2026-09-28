from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from ite.skills.manager import SkillManager


class BundledPdfSkillTests(unittest.TestCase):
    def test_bundled_pdf_skill_is_discoverable(self) -> None:
        manager = SkillManager(Path.cwd())
        manager.discover()
        skill = manager.get("pdf")
        self.assertIsNotNone(skill)
        assert skill is not None
        self.assertEqual(skill.source, "shared-project")
        self.assertTrue((skill.directory / "scripts" / "write_pdf.py").is_file())
        self.assertTrue((skill.directory / "scripts" / "render_pdf.py").is_file())

    def test_bundled_pdf_scripts_can_create_validate_and_extract(self) -> None:
        skill_dir = Path.cwd() / ".agents" / "skills" / "pdf"
        write_script = skill_dir / "scripts" / "write_pdf.py"
        validate_script = skill_dir / "scripts" / "validate_pdf.py"
        inspect_script = skill_dir / "scripts" / "inspect_pdf.py"
        extract_script = skill_dir / "scripts" / "extract_pdf_text.py"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "draft.txt"
            output = root / "draft.pdf"
            extracted = root / "draft.txt.out"
            source.write_text("Hello PDF\n\nSecond line\n", encoding="utf-8")

            subprocess.run(
                ["python3", str(write_script), str(source), str(output), "--title", "Demo PDF"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["python3", str(validate_script), str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            inspect_result = subprocess.run(
                ["python3", str(inspect_script), str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["python3", str(extract_script), str(output), "--output", str(extracted)],
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(inspect_result.stdout)
            self.assertEqual(payload["page_count"], 1)
            self.assertEqual(payload["validation_errors"], [])
            self.assertIn("Demo PDF", "\n".join(payload["preview"]))
            text = extracted.read_text(encoding="utf-8")
            self.assertIn("Demo PDF", text)
            self.assertIn("Hello PDF", text)

    def test_bundled_pdf_can_span_multiple_pages(self) -> None:
        skill_dir = Path.cwd() / ".agents" / "skills" / "pdf"
        write_script = skill_dir / "scripts" / "write_pdf.py"
        inspect_script = skill_dir / "scripts" / "inspect_pdf.py"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "long.txt"
            output = root / "long.pdf"
            source.write_text("\n".join(f"Line {index}" for index in range(80)), encoding="utf-8")

            subprocess.run(
                ["python3", str(write_script), str(source), str(output), "--title", "Long Report"],
                check=True,
                capture_output=True,
                text=True,
            )
            inspect_result = subprocess.run(
                ["python3", str(inspect_script), str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(inspect_result.stdout)
            self.assertGreaterEqual(payload["page_count"], 2)


if __name__ == "__main__":
    unittest.main()
