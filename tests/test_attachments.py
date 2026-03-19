import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ite.attachments import Attachment, build_user_text_with_manifest


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
