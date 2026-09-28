import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ite.attachments import Attachment, AttachmentManager, build_user_model_content, build_user_text_with_manifest


class AttachmentManifestTests(unittest.TestCase):
    def test_manifest_uses_source_path_not_temp_path(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            source = cwd / "README.md"
            source.write_text("# hi\n", encoding="utf-8")
            staged = cwd / ".ite" / "tmp_attachments" / "turn1" / "README.md"
            staged.parent.mkdir(parents=True)
            staged.write_text("# hi\n", encoding="utf-8")

            attachment = Attachment(
                id="a1",
                original_name="README.md",
                mime_type="text/markdown",
                size_bytes=5,
                source_path=str(source),
                temp_path=str(staged),
                kind="text",
            )

            rendered = build_user_text_with_manifest(
                "inspect this",
                [attachment],
                cwd,
            )

            self.assertIn("-> README.md", rendered)
            self.assertNotIn("tmp_attachments", rendered)

    def test_manifest_includes_attached_as_path_for_external_pdf(self) -> None:
        with TemporaryDirectory() as tmp, TemporaryDirectory() as external_tmp:
            cwd = Path(tmp)
            external = Path(external_tmp) / "report.pdf"
            external.write_bytes(b"%PDF-1.4")
            staged = cwd / ".ite" / "tmp_attachments" / "turn1" / "report.pdf"
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"%PDF-1.4")

            attachment = Attachment(
                id="a2",
                original_name="report.pdf",
                mime_type="application/pdf",
                size_bytes=8,
                source_path=str(external),
                temp_path=str(staged),
                kind="pdf",
            )

            rendered = build_user_text_with_manifest("inspect this", [attachment], cwd)

            self.assertIn("[attached as .ite/tmp_attachments/turn1/report.pdf]", rendered)

    def test_stage_paths_accepts_pdf_attachments(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            pdf = cwd / "report.pdf"
            pdf.write_bytes(b"%PDF-1.4")

            manager = AttachmentManager(cwd)
            staged, errors = manager.stage_paths([pdf], "turn1")

            self.assertEqual(errors, [])
            self.assertEqual(len(staged), 1)
            self.assertEqual(staged[0].kind, "pdf")
            self.assertIn(".ite/tmp_attachments", staged[0].temp_path)

    def test_build_user_model_content_keeps_pdf_as_manifest_only(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            source = cwd / "report.pdf"
            source.write_bytes(b"%PDF-1.4")
            staged = cwd / ".ite" / "tmp_attachments" / "turn1" / "report.pdf"
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"%PDF-1.4")

            attachment = Attachment(
                id="a3",
                original_name="report.pdf",
                mime_type="application/pdf",
                size_bytes=8,
                source_path=str(source),
                temp_path=str(staged),
                kind="pdf",
            )

            content = build_user_model_content("inspect this", [attachment], cwd)

            self.assertIsInstance(content, str)
            self.assertIn("report.pdf", content)
