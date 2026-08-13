import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.builtin.media_tools import ReadDocumentTool
from ite.tools.builtin.media_tools import ReadImageTool
from ite.tools.builtin.media_tools import ReadPdfTool
from ite.tools.registry import create_default_registry


class MediaToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_pdf_extracts_selected_pages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            pdf_path = cwd / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            page1 = Mock()
            page1.extract_text.return_value = "First page"
            page2 = Mock()
            page2.extract_text.return_value = "Second page"
            reader = Mock()
            reader.pages = [page1, page2]
            reader.metadata = {"/Title": "Demo"}

            tool = ReadPdfTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_pdf_reader", return_value=lambda _: reader), patch(
                "ite.tools.builtin.media_tools._load_pdf_inspector", return_value=None
            ):
                result = await tool.execute(
                    ToolInvocation(params={"path": "sample.pdf", "pages": [2]}, cwd=cwd)
                )

            self.assertTrue(result.success, msg=result.error)
            self.assertIn("Page 2", result.output)
            self.assertEqual(result.metadata.get("page_count"), 2)
            self.assertEqual(result.metadata.get("selected_pages"), [2])

    async def test_read_pdf_reports_missing_dependency_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            pdf_path = cwd / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            tool = ReadPdfTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_pdf_reader", side_effect=RuntimeError("missing pypdf")), patch(
                "ite.tools.builtin.media_tools._load_pdf_inspector", return_value=None
            ):
                result = await tool.execute(ToolInvocation(params={"path": "sample.pdf"}, cwd=cwd))

            self.assertFalse(result.success)
            self.assertIn("missing pypdf", result.error or "")

    async def test_read_image_returns_metadata_without_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            image_path = cwd / "shot.png"
            image_path.write_bytes(b"fake")

            fake_image = Mock()
            fake_image.size = (1280, 720)
            fake_image.mode = "RGBA"
            fake_image.format = "PNG"
            fake_image.info = {"dpi": (72, 72)}
            fake_image.__enter__ = Mock(return_value=fake_image)
            fake_image.__exit__ = Mock(return_value=False)

            def mock_save(path, format=None):
                Path(path).write_bytes(b"resized")

            fake_image.save = Mock(side_effect=mock_save)
            image_module = Mock()
            image_module.open.return_value = fake_image

            tool = ReadImageTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_pillow", return_value=image_module), patch(
                "ite.tools.builtin.media_tools._module_available", side_effect=lambda name: name == "PIL"
            ), patch("ite.tools.builtin.media_tools._get_image_cache_dir", return_value=cwd):
                result = await tool.execute(ToolInvocation(params={"path": "shot.png"}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertIn('"width": 1280', result.output)
            self.assertIn('"ocr_text_length": 0', result.output)
            self.assertEqual(result.metadata.get("width"), 1280)
            self.assertEqual(result.metadata.get("height"), 720)

    async def test_read_image_runs_ocr_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            image_path = cwd / "receipt.png"
            image_path.write_bytes(b"fake")

            fake_image = Mock()
            fake_image.size = (800, 600)
            fake_image.mode = "RGB"
            fake_image.format = "PNG"
            fake_image.info = {}
            fake_image.__enter__ = Mock(return_value=fake_image)
            fake_image.__exit__ = Mock(return_value=False)

            def mock_save(path, format=None):
                Path(path).write_bytes(b"resized")

            fake_image.save = Mock(side_effect=mock_save)
            image_module = Mock()
            image_module.open.return_value = fake_image
            pytesseract = Mock()
            pytesseract.image_to_string.return_value = "Total: 42"

            tool = ReadImageTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_pillow", return_value=image_module), patch(
                "ite.tools.builtin.media_tools._load_pytesseract", return_value=pytesseract
            ), patch("ite.tools.builtin.media_tools._module_available", return_value=True), patch(
                "ite.tools.builtin.media_tools._get_image_cache_dir", return_value=cwd
            ):
                result = await tool.execute(ToolInvocation(params={"path": "receipt.png", "ocr": True}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertIn('"ocr_text_preview": "Total: 42"', result.output)
            self.assertIn('"ocr_text_length": 9', result.output)
            self.assertEqual(result.metadata.get("ocr_requested"), True)
            self.assertEqual(result.metadata.get("ocr_backend"), "tesseract")

    async def test_read_image_compacts_long_ocr_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            image_path = cwd / "receipt.png"
            image_path.write_bytes(b"fake")

            fake_image = Mock()
            fake_image.size = (800, 600)
            fake_image.mode = "RGB"
            fake_image.format = "PNG"
            fake_image.info = {}
            fake_image.__enter__ = Mock(return_value=fake_image)
            fake_image.__exit__ = Mock(return_value=False)

            def mock_save(path, format=None):
                Path(path).write_bytes(b"resized")

            fake_image.save = Mock(side_effect=mock_save)
            image_module = Mock()
            image_module.open.return_value = fake_image
            pytesseract = Mock()
            pytesseract.image_to_string.return_value = "line " * 200

            tool = ReadImageTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_pillow", return_value=image_module), patch(
                "ite.tools.builtin.media_tools._load_pytesseract", return_value=pytesseract
            ), patch("ite.tools.builtin.media_tools._module_available", return_value=True), patch(
                "ite.tools.builtin.media_tools._get_image_cache_dir", return_value=cwd
            ):
                result = await tool.execute(ToolInvocation(params={"path": "receipt.png", "ocr": True}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertIn('"ocr_text_preview": "', result.output)
            self.assertIn('..."', result.output)
            self.assertNotIn(("line " * 80).strip(), result.output)

    async def test_read_image_returns_structured_recovery_hint_when_ocr_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            image_path = cwd / "receipt.png"
            image_path.write_bytes(b"fake")

            fake_image = Mock()
            fake_image.size = (800, 600)
            fake_image.mode = "RGB"
            fake_image.format = "PNG"
            fake_image.info = {}
            fake_image.__enter__ = Mock(return_value=fake_image)
            fake_image.__exit__ = Mock(return_value=False)

            def mock_save(path, format=None):
                Path(path).write_bytes(b"resized")

            fake_image.save = Mock(side_effect=mock_save)
            image_module = Mock()
            image_module.open.return_value = fake_image

            tool = ReadImageTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_pillow", return_value=image_module), patch(
                "ite.tools.builtin.media_tools._ocr_backend_status", return_value=(False, "none")
            ), patch("ite.tools.builtin.media_tools.platform.system", return_value="Darwin"), patch(
                "ite.tools.builtin.media_tools._get_image_cache_dir", return_value=cwd
            ):
                result = await tool.execute(ToolInvocation(params={"path": "receipt.png", "ocr": True}, cwd=cwd))

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("recoverable"))
            self.assertFalse(result.metadata.get("ocr_available"))
            self.assertEqual(result.metadata.get("ocr_backend"), "none")
            self.assertIn("brew install tesseract", result.metadata.get("recovery_hint", ""))

    async def test_read_image_sanitizes_binary_info_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            image_path = cwd / "shot.png"
            image_path.write_bytes(b"fake")

            fake_image = Mock()
            fake_image.size = (100, 50)
            fake_image.mode = "RGBA"
            fake_image.format = "PNG"
            fake_image.info = {"icc_profile": b"\x00\x01binary", "dpi": (72, 72)}
            fake_image.__enter__ = Mock(return_value=fake_image)
            fake_image.__exit__ = Mock(return_value=False)

            def mock_save(path, format=None):
                Path(path).write_bytes(b"resized")

            fake_image.save = Mock(side_effect=mock_save)
            image_module = Mock()
            image_module.open.return_value = fake_image

            tool = ReadImageTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_pillow", return_value=image_module), patch(
                "ite.tools.builtin.media_tools._module_available", side_effect=lambda name: name == "PIL"
            ), patch("ite.tools.builtin.media_tools._get_image_cache_dir", return_value=cwd):
                result = await tool.execute(ToolInvocation(params={"path": "shot.png"}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertIsInstance(result.metadata["info"]["icc_profile"], str)

    async def test_read_pdf_uses_pdf_inspector_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            pdf_path = cwd / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")

            classification = Mock()
            classification.page_count = 2
            classification.pdf_type = "text_based"
            classification.confidence = 0.95

            page1 = Mock()
            page1.page = 0
            page1.markdown = "# Page one"
            page1.needs_ocr = False
            page2 = Mock()
            page2.page = 1
            page2.markdown = "# Page two"
            page2.needs_ocr = False

            extraction = Mock()
            extraction.pages = [page1, page2]
            extraction.pages_needing_ocr = []
            extraction.pages_with_tables = []
            extraction.pages_with_columns = []
            extraction.is_complex = False

            inspector = Mock()
            inspector.classify_pdf.return_value = classification
            inspector.extract_pages_markdown.return_value = extraction

            tool = ReadPdfTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_pdf_inspector", return_value=inspector):
                result = await tool.execute(
                    ToolInvocation(params={"path": "sample.pdf", "pages": [2]}, cwd=cwd)
                )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata.get("pdf_type"), "text_based")
            self.assertEqual(result.metadata.get("engine"), "pdf_inspector")
            self.assertIn("# Page two", result.output)
            inspector.extract_pages_markdown.assert_called_once_with(str(pdf_path.resolve()), pages=[1])

    async def test_read_document_converts_to_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            doc_path = cwd / "report.docx"
            doc_path.write_bytes(b"fake")

            anydoc = Mock()
            anydoc.to_markdown.return_value = "# Report\n\nHello."

            tool = ReadDocumentTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_anydoc", return_value=anydoc):
                result = await tool.execute(ToolInvocation(params={"path": "report.docx"}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertIn("# Report", result.output)
            self.assertEqual(result.metadata.get("format"), "docx")
            anydoc.to_markdown.assert_called_once_with(str(doc_path.resolve()))

    async def test_read_document_reports_missing_dependency_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            doc_path = cwd / "report.docx"
            doc_path.write_bytes(b"fake")

            tool = ReadDocumentTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.media_tools._load_anydoc", return_value=None):
                result = await tool.execute(ToolInvocation(params={"path": "report.docx"}, cwd=cwd))

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("recoverable"))
            self.assertIn("firecrawl-anydoc", result.error or "")

    async def test_media_tools_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            registry = create_default_registry(Config(cwd=cwd, api_key="test"))
            tool_names = {tool.name for tool in registry.get_tools()}

            self.assertTrue({"read_pdf", "read_image", "read_document"}.issubset(tool_names))


if __name__ == "__main__":
    unittest.main()
