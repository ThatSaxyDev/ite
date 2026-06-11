from __future__ import annotations

import importlib.util
import json
import platform
import shutil
from base64 import b64encode
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
    budget: int = Field(
        280,
        ge=70,
        le=1120,
        description="Visual token budget for the model. Options: 70, 140, 280, 560, 1120. Higher budget preserves more detail.",
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


def _resize_image_if_needed(image, max_dimension: int = 1024):
    """Resize image to fit within max_dimension while maintaining aspect ratio."""
    from PIL import Image as PILImage
    
    width, height = image.size
    if width <= max_dimension and height <= max_dimension:
        return image

    if width > height:
        new_width = max_dimension
        new_height = int(height * (max_dimension / width))
    else:
        new_height = max_dimension
        new_width = int(width * (max_dimension / height))

    return image.resize((new_width, new_height), PILImage.LANCZOS)


def _get_image_cache_dir() -> Path:
    """Get the image cache directory."""
    cache_dir = Path.home() / ".ite" / "image_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_cache_size_mb(cache_dir: Path) -> float:
    """Get total size of cache directory in MB."""
    total_size = 0
    for file_path in cache_dir.iterdir():
        if file_path.is_file():
            total_size += file_path.stat().st_size
    return total_size / (1024 * 1024)


def _evict_oldest_cache_entries(cache_dir: Path, required_space_mb: float, max_cache_mb: float = 100.0):
    """Evict oldest accessed cache entries until we have enough space."""
    current_size = _get_cache_size_mb(cache_dir)
    
    if current_size + required_space_mb <= max_cache_mb:
        return
    
    # Get all files with their last access time
    files_with_atime = []
    for file_path in cache_dir.iterdir():
        if file_path.is_file():
            stat = file_path.stat()
            files_with_atime.append((file_path, stat.st_atime, stat.st_size))
    
    # Sort by access time (oldest first)
    files_with_atime.sort(key=lambda x: x[1])
    
    # Delete oldest files until we have enough space
    for file_path, _, file_size in files_with_atime:
        if current_size + required_space_mb <= max_cache_mb:
            break
        try:
            file_path.unlink()
            current_size -= file_size / (1024 * 1024)
        except OSError:
            pass


def _cache_image(source_path: Path) -> Path:
    """Copy image to cache and return cached path. Handles LRU eviction."""
    import hashlib
    
    cache_dir = _get_image_cache_dir()
    
    # Generate content-based hash for filename
    with open(source_path, "rb") as f:
        file_hash = hashlib.md5(f.read()).hexdigest()
    
    cached_path = cache_dir / f"{file_hash}_{source_path.name}"
    
    # If already cached, just update access time and return
    if cached_path.exists():
        cached_path.touch()
        return cached_path
    
    # Check file size and evict if needed
    file_size_mb = source_path.stat().st_size / (1024 * 1024)
    _evict_oldest_cache_entries(cache_dir, file_size_mb, max_cache_mb=500.0)
    
    # Copy to cache
    shutil.copy2(source_path, cached_path)
    return cached_path


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


def _image_to_data_url(image_bytes: bytes, fmt: str | None = None) -> str:
    encoded = b64encode(image_bytes).decode("ascii")
    mime = _mime_for_format(fmt)
    return f"data:{mime};base64,{encoded}"


def _mime_for_format(fmt: str | None) -> str:
    mapping = {
        "png": "image/png",
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
    }
    key = (fmt or "").lower()
    return mapping.get(key, "image/png")


def _compact_preview(text: str, *, limit: int = 320) -> str:
    normalized = " ".join((text or "").split())
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


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

        # Skip sandbox check for read_image to allow accessing user images
        # from Desktop, Downloads, etc. This is safe because:
        # 1. It's a read-only operation
        # 2. The user explicitly requested the AI to view this image
        # 3. No file modification occurs

        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            Image = _load_pillow()
            with Image.open(path) as image:
                # Resize image to prevent "Request body too large" (413) errors
                # when sending multimodal content to the cloud API.
                image = _resize_image_if_needed(image)
                width, height = image.size
                mode = image.mode
                image_format = image.format
                info = _json_safe(dict(image.info or {}))
                
                # Convert RGBA to RGB for smaller file size, use JPEG compression
                if image.mode == "RGBA":
                    rgb_image = Image.new("RGB", image.size, (255, 255, 255))
                    rgb_image.paste(image, mask=image.split()[3])  # Use alpha as mask
                    image = rgb_image
                    image_format = "JPEG"
                
                # Save resized image to a temporary file for caching
                temp_path = path.parent / f".resized_{path.name}"
                image.save(temp_path, format=image_format or "JPEG", quality=85, optimize=True)
                
                # Cache the resized image for persistence across sessions
                cached_path = _cache_image(temp_path)
                
                # Clean up temp file
                if temp_path.exists():
                    temp_path.unlink()
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
                # Reload Image here to ensure it's available for OCR
                ImageOCR = _load_pillow()
                with ImageOCR.open(path) as image:
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
            "cached_path": str(cached_path),
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
        ocr_preview = _compact_preview(ocr_text) if params.ocr else ""
        summary = {
            "format": image_format,
            "dimensions": {"width": width, "height": height},
            "mode": mode,
            "ocr_text_preview": ocr_preview,
            "ocr_text_length": len(ocr_text) if params.ocr else 0,
        }
        output, truncated = _truncate_text(json.dumps(summary, indent=2, ensure_ascii=False))

        content_parts = None
        supports_vision = bool(getattr(self.config.model, "supports_vision", True))
        if supports_vision and cached_path.exists():
            try:
                image_bytes = cached_path.read_bytes()
                # Skip if image is too large (>2MB base64 would be ~2.6MB)
                if len(image_bytes) > 2 * 1024 * 1024:
                    output += "\n[Note: Image too large to embed, showing metadata only]"
                else:
                    data_url = _image_to_data_url(image_bytes, image_format)
                    content_parts = [
                        {"type": "text", "text": output},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ]
            except Exception:
                pass

        return ToolResult.success_result(
            output,
            truncated=truncated,
            metadata=metadata,
            content_parts=content_parts,
        )
