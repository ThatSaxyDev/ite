import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.builtin.archive_tools import ListArchiveTool
from ite.tools.builtin.http_tools import HttpRequestTool
from ite.tools.registry import create_default_registry


class HttpAndArchiveToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_request_formats_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)

            class FakeResponse:
                status_code = 200
                headers = {"content-type": "application/json"}
                content = b'{"ok":true}'
                text = '{"ok":true}'

                def json(self):
                    return {"ok": True}

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

                async def request(self, **kwargs):
                    return FakeResponse()

            tool = HttpRequestTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.http_tools.httpx.AsyncClient", return_value=FakeClient()):
                result = await tool.execute(
                    ToolInvocation(
                        params={"url": "https://example.com/api", "method": "GET"},
                        cwd=cwd,
                    )
                )

            self.assertTrue(result.success, msg=result.error)
            self.assertIn('"ok": true', result.output)
            self.assertEqual(result.metadata.get("status_code"), 200)
            self.assertEqual(result.metadata.get("method"), "GET")

    async def test_http_request_returns_error_result_for_http_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)

            class FakeResponse:
                status_code = 404
                headers = {"content-type": "text/plain"}
                content = b"missing"
                text = "missing"

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

                async def request(self, **kwargs):
                    return FakeResponse()

            tool = HttpRequestTool(Config(cwd=cwd, api_key="test"))
            with patch("ite.tools.builtin.http_tools.httpx.AsyncClient", return_value=FakeClient()):
                result = await tool.execute(
                    ToolInvocation(
                        params={"url": "https://example.com/missing", "method": "GET"},
                        cwd=cwd,
                    )
                )

            self.assertFalse(result.success)
            self.assertEqual(result.metadata.get("status_code"), 404)
            self.assertIn("missing", result.output)

    async def test_list_archive_lists_zip_entries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            archive_path = cwd / "sample.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("folder/data.txt", "hello")
                archive.writestr("README.md", "# demo\n")

            tool = ListArchiveTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={"path": "sample.zip"}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata.get("archive_format"), "zip")
            self.assertEqual(result.metadata.get("entry_count"), 2)
            self.assertIn("folder/data.txt", result.output)

    async def test_list_archive_lists_tar_entries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            archive_path = cwd / "sample.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                data = b"hello"
                info = tarfile.TarInfo("notes.txt")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

            tool = ListArchiveTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={"path": "sample.tar.gz"}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata.get("archive_format"), "tar")
            self.assertIn("notes.txt", result.output)

    async def test_http_and_archive_tools_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            registry = create_default_registry(Config(cwd=cwd, api_key="test"))
            tool_names = {tool.name for tool in registry.get_tools()}

            self.assertTrue({"http_request", "list_archive"}.issubset(tool_names))


if __name__ == "__main__":
    unittest.main()
