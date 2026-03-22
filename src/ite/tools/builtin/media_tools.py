from __future__ import annotations

import importlib.util
import io
import json
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
            "metadata": dict(getattr(reader, "metadata", {}) or {}),
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
                info = dict(image.info or {})
                raw = io.BytesIO()
                image.save(raw, format=image_format or "PNG")
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to read image file: {exc}",
                metadata={"path": str(path), "parse_error": True},
            )

        ocr_text = ""
        ocr_available = _module_available("pytesseract")
        if params.ocr:
            try:
                pytesseract = _load_pytesseract()
                with Image.open(path) as image:
                    ocr_text = pytesseract.image_to_string(image).strip()
            except Exception as exc:
                return ToolResult.error_result(
                    f"Failed to run OCR: {exc}",
                    metadata={"path": str(path), "ocr_requested": True, "ocr_available": ocr_available},
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
