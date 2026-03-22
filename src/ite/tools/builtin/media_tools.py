from __future__ import annotations

import importlib.util
import json
import platform
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from ite.utils.paths import resolve_path


class ReadPdfParams(BaseModel):
    path: str = Field(..., description="Path to the PDF file to inspect.")
    pages: list[int] | None = Field(
        None,
        description="Optional 1-based page numbers to extract. Omit to read from the start of the document.",
    )
    max_pages: int = Field(
        5,
        ge=1,
        le=50,
        description="Maximum number of pages to extract when pages is omitted.",
    )


class ReadImageParams(BaseModel):
    path: str = Field(..., description="Path to the image file to inspect.")
    ocr: bool = Field(
        False,
        description="Attempt OCR text extraction when supported.",
    )


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _load_pdf_reader():
    if _module_available("pypdf"):
        from pypdf import PdfReader

        return PdfReader
    if _module_available("PyPDF2"):
        from PyPDF2 import PdfReader

        return PdfReader
    raise RuntimeError("PDF support is unavailable. Install `pypdf` to use read_pdf.")


def _load_pillow():
    if not _module_available("PIL"):
        raise RuntimeError("Image support is unavailable. Install `Pillow` to use read_image.")
    from PIL import Image

    return Image


def _load_pytesseract():
    if not _module_available("pytesseract"):
        raise RuntimeError("OCR support is unavailable. Install `pytesseract` to enable OCR.")
    import pytesseract

    return pytesseract


def _ocr_recovery_hint() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "OCR requires the `tesseract` binary. Install it with `brew install tesseract`."
    if system == "linux":
        return (
            "OCR requires the `tesseract` binary. Install it with "
            "`sudo apt install tesseract-ocr` on Debian/Ubuntu or `sudo dnf install tesseract` on Fedora."
        )
    if system == "windows":
        return "OCR requires the `tesseract` binary. Install Tesseract for Windows and add it to PATH."
    return "OCR requires the `tesseract` binary to be installed and available on PATH."


def _ocr_backend_status() -> tuple[bool, str]:
    if not _module_available("pytesseract"):
        return False, "none"
    if shutil.which("tesseract"):
        return True, "tesseract"
    return False, "none"


def _normalize_page_numbers(total_pages: int, pages: list[int] | None, max_pages: int) -> list[int]:
    if pages:
        selected: list[int] = []
        for page in pages:
            if page < 1 or page > total_pages:
                raise ValueError(f"Requested page {page} is out of range for a {total_pages}-page PDF.")
            if page not in selected:
                selected.append(page)
        return selected
    return list(range(1, min(total_pages, max_pages) + 1))


def _truncate_text(text: str, limit: int = 60 * 1024) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n... [truncated]", True


def _json_safe(value: Any, *, max_text: int = 2048) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str) and len(value) > max_text:
            return value[:max_text] + "..."
        return value
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
        if len(text) > max_text:
            text = text[:max_text] + "..."
        return text
    if isinstance(value, dict):
        return {str(key): _json_safe(item, max_text=max_text) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, max_text=max_text) for item in value]
    return _json_safe(str(value), max_text=max_text)


class ReadPdfTool(Tool):
    name = "read_pdf"
    description = "Read a PDF document and return metadata plus extracted text by page."
    kind = ToolKind.READ
    schema = ReadPdfParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ReadPdfParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        sandbox_error = self._sandbox_check(path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            PdfReader = _load_pdf_reader()
            reader = PdfReader(str(path))
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to read PDF file: {exc}",
                metadata={"path": str(path), "parse_error": True},
            )

        total_pages = len(getattr(reader, "pages", []))
        if total_pages == 0:
            return ToolResult.success_result(
                "PDF contains no pages.",
                metadata={"path": str(path), "page_count": 0, "pages": []},
            )

        try:
            selected_pages = _normalize_page_numbers(total_pages, params.pages, params.max_pages)
        except ValueError as exc:
            return ToolResult.error_result(str(exc), metadata={"path": str(path), "page_count": total_pages})

        page_entries: list[dict[str, Any]] = []
        output_lines: list[str] = []
        total_chars = 0
        for page_number in selected_pages:
            page = reader.pages[page_number - 1]
            page_text = ""
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            text_length = len(page_text)
            total_chars += text_length
            page_entries.append(
                {
                    "page": page_number,
                    "text_length": text_length,
                    "has_text": bool(page_text.strip()),
                }
            )
            output_lines.append(f"--- Page {page_number} ---")
            output_lines.append(page_text.strip() or "[No extractable text]")
            output_lines.append("")

        output, truncated = _truncate_text("\n".join(output_lines).rstrip())
        metadata = {
            "path": str(path),
            "page_count": total_pages,
            "pages": page_entries,
            "selected_pages": selected_pages,
            "metadata": _json_safe(dict(getattr(reader, "metadata", {}) or {})),
            "text_extraction_quality": "text" if total_chars > 0 else "none",
        }
        return ToolResult.success_result(output or "[No extractable text]", truncated=truncated, metadata=metadata)


class ReadImageTool(Tool):
    name = "read_image"
    description = "Read image metadata and optionally extract text with OCR when available."
    kind = ToolKind.READ
    schema = ReadImageParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ReadImageParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        sandbox_error = self._sandbox_check(path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            Image = _load_pillow()
            with Image.open(path) as image:
                width, height = image.size
                mode = image.mode
                image_format = image.format
                info = _json_safe(dict(image.info or {}))
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to read image file: {exc}",
                metadata={"path": str(path), "parse_error": True},
            )

        ocr_text = ""
        ocr_available, ocr_backend = _ocr_backend_status()
        if params.ocr:
            if not ocr_available:
                return ToolResult.error_result(
                    "OCR is unavailable in this environment.",
                    metadata={
                        "path": str(path),
                        "ocr_requested": True,
                        "ocr_available": False,
                        "ocr_backend": ocr_backend,
                        "recoverable": True,
                        "recovery_hint": _ocr_recovery_hint(),
                    },
                )
            try:
                pytesseract = _load_pytesseract()
                with Image.open(path) as image:
                    ocr_text = pytesseract.image_to_string(image).strip()
            except Exception as exc:
                return ToolResult.error_result(
                    f"Failed to run OCR: {exc}",
                    metadata={
                        "path": str(path),
                        "ocr_requested": True,
                        "ocr_available": ocr_available,
                        "ocr_backend": ocr_backend,
                    },
                )

        metadata = {
            "path": str(path),
            "width": width,
            "height": height,
            "mode": mode,
            "format": image_format,
            "file_size": path.stat().st_size,
            "ocr_requested": params.ocr,
            "ocr_available": ocr_available,
            "ocr_backend": ocr_backend,
            "info": info,
        }
        summary = {
            "format": image_format,
            "dimensions": {"width": width, "height": height},
            "mode": mode,
            "ocr_text": ocr_text if params.ocr else "",
        }
        output, truncated = _truncate_text(json.dumps(summary, indent=2, ensure_ascii=False))
        return ToolResult.success_result(output, truncated=truncated, metadata=metadata)
