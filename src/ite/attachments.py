from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import hashlib
import mimetypes
import shutil
import uuid

MAX_ATTACHMENTS = 10
ATTACHMENT_LIMIT_MESSAGE = f"File limit exceeded. You can attach at most {MAX_ATTACHMENTS} files."
MAX_FILE_SIZE_BYTES = 35 * 1024 * 1024  # 35MB max per attachment

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_EXTS = {
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".csv",
    ".log",
    ".ini",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".sh",
}
PDF_EXTS = {".pdf"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def queue_attachment_paths(
    existing_paths: list[str], paths: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Accept files that fit, preserving the draft and rejecting only overflow."""
    pending = list(existing_paths)
    seen = {str(Path(path).expanduser().resolve()) for path in pending}
    accepted: list[str] = []
    rejected: list[str] = []
    for path in paths:
        key = str(Path(path).expanduser().resolve())
        if key in seen:
            accepted.append(path)
        elif len(seen) < MAX_ATTACHMENTS:
            pending.append(path)
            seen.add(key)
            accepted.append(path)
        else:
            rejected.append(path)
    errors = []
    if rejected:
        names = ", ".join(Path(path).name for path in rejected[:3])
        errors.append(f"{ATTACHMENT_LIMIT_MESSAGE} Skipped: {names}")
    return pending, accepted, errors


@dataclass
class Attachment:
    id: str
    original_name: str
    mime_type: str
    size_bytes: int
    source_path: str
    temp_path: str
    kind: str  # image | text | pdf
    metadata: dict | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_name": self.original_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "source_path": self.source_path,
            "temp_path": self.temp_path,
            "kind": self.kind,
            "metadata": self.metadata,
        }


class AttachmentManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.temp_root = self.workspace / ".ite" / "tmp_attachments"
        self.snapshot_root = self.workspace / ".ite" / "attachments"

    def _persist_attachment(self, staged_path: Path, original_name: str) -> Path:
        """Retain the exact attached bytes for later turns and saved threads."""
        with staged_path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        directory = self.snapshot_root / digest
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / original_name
        if not snapshot.is_file():
            partial = directory / f".{uuid.uuid4().hex}.tmp"
            try:
                shutil.copy2(staged_path, partial)
                partial.replace(snapshot)
            finally:
                partial.unlink(missing_ok=True)
        return snapshot

    def stage_paths(self, paths: list[str | Path], turn_id: str) -> tuple[list[Attachment], list[str]]:
        errors: list[str] = []
        unique: list[Path] = []
        seen: set[str] = set()

        for raw in paths:
            p = Path(raw).expanduser().resolve()
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)

        if len(unique) > MAX_ATTACHMENTS:
            errors.append(f"Too many attachments ({len(unique)}). Max is {MAX_ATTACHMENTS}.")
            unique = unique[:MAX_ATTACHMENTS]

        staged: list[Attachment] = []
        turn_dir = self.temp_root / turn_id
        turn_dir.mkdir(parents=True, exist_ok=True)

        for src in unique:
            if not src.exists() or not src.is_file():
                errors.append(f"Attachment not found: {src}")
                continue

            ext = src.suffix.lower()
            if ext in VIDEO_EXTS:
                errors.append(f"Video attachments are not supported in v1: {src.name}")
                continue
            if ext not in IMAGE_EXTS and ext not in TEXT_EXTS and ext not in PDF_EXTS:
                errors.append(f"Unsupported attachment type: {src.name}")
                continue

            size = src.stat().st_size
            if size > MAX_FILE_SIZE_BYTES:
                errors.append(
                    f"Attachment too large: {src.name} ({size / (1024 * 1024):.1f}MB), max 35.0MB"
                )
                continue

            mime = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
            if ext in IMAGE_EXTS:
                kind = "image"
            elif ext in PDF_EXTS:
                kind = "pdf"
            else:
                kind = "text"
            dest = turn_dir / f"{uuid.uuid4().hex}_{src.name}"
            shutil.copy2(src, dest)
            snapshot = self._persist_attachment(dest, src.name)

            staged.append(
                Attachment(
                    id=uuid.uuid4().hex,
                    original_name=src.name,
                    mime_type=mime,
                    size_bytes=size,
                    source_path=str(src),
                    temp_path=str(dest),
                    kind=kind,
                    metadata={"cached_path": str(snapshot)},
                )
            )

        return staged, errors

    def cleanup_turn(self, turn_id: str) -> None:
        target = self.temp_root / turn_id
        if not target.exists():
            return
        shutil.rmtree(target, ignore_errors=True)


def _manifest_lines(attachments: list[Attachment], workspace: Path) -> list[str]:
    def display_path(path_text: str) -> str:
        source = Path(path_text)
        try:
            return str(source.resolve().relative_to(workspace.resolve()))
        except Exception:
            return path_text

    lines = ["Attached files:"]
    for a in attachments:
        source_text = display_path(a.source_path)
        # The manifest survives in model history after turn cleanup. Never
        # advertise temp_path, which is deliberately deleted at that point.
        retained_path = (a.metadata or {}).get("cached_path") or a.source_path
        attached_text = display_path(retained_path)
        line = f"- {a.original_name} ({a.mime_type}, {a.size_bytes} bytes) -> {attached_text}"
        if attached_text != source_text:
            line += f" [source: {source_text}]"
        lines.append(line)
    return lines


def build_user_text_with_manifest(message: str, attachments: list[Attachment], workspace: Path) -> str:
    text = (message or "").strip()
    if not attachments:
        return text
    return f"{text}\n\n" + "\n".join(_manifest_lines(attachments, workspace))


def _resize_image_for_upload(image_path: Path, max_dimension: int = 2048) -> bytes:
    """Resize image and return as bytes, or return original bytes if not an image."""
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            width, height = img.size
            if width <= max_dimension and height <= max_dimension:
                # No resizing needed, return original bytes
                return image_path.read_bytes()
            
            # Resize maintaining aspect ratio
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            
            resized = img.resize((new_width, new_height), Image.LANCZOS)
            
            # Save to bytes
            import io
            format = img.format or "PNG"
            buffer = io.BytesIO()
            resized.save(buffer, format=format)
            return buffer.getvalue()
    except Exception:
        # If resize fails, return original bytes
        return image_path.read_bytes()


def build_user_model_content(
    message: str,
    attachments: list[Attachment],
    workspace: Path,
    *,
    supports_vision: bool = True,
) -> str | list[dict]:
    text = build_user_text_with_manifest(message, attachments, workspace)
    images = [a for a in attachments if a.kind == "image"]
    if not images:
        return text

    if not supports_vision:
        return _build_text_only_content(text, images)

    parts: list[dict] = [{"type": "text", "text": text}]
    for img in images:
        p = Path(img.temp_path)
        # Resize image before encoding to prevent 413 errors
        raw = _resize_image_for_upload(p)
        encoded = base64.b64encode(raw).decode("ascii")
        mime = img.mime_type if "/" in img.mime_type else "image/png"
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
        )
    return parts


def _build_text_only_content(text: str, images: list[Attachment]) -> str:
    """For text-only models: run local image processing and append metadata/OCR as text."""
    parts: list[str] = [text]
    for img in images:
        source_path = Path(img.source_path) if Path(img.source_path).exists() else Path(img.temp_path)
        desc = _describe_image_locally(source_path, img.original_name)
        if desc:
            parts.append(desc)
    return "\n\n".join(parts)


def _describe_image_locally(image_path: Path, name: str) -> str:
    """Extract image metadata and optional OCR text, returning a text description."""
    try:
        from PIL import Image
        with Image.open(image_path) as image:
            width, height = image.size
            mode = image.mode
            fmt = image.format or "unknown"
            file_size = image_path.stat().st_size
    except Exception:
        return f"[Image: {name} — could not read metadata]"

    lines = [
        f"[Image: {name}]",
        f"  Format: {fmt}",
        f"  Dimensions: {width}x{height}",
        f"  Mode: {mode}",
        f"  File size: {_human_size(file_size)}",
    ]

    ocr_available, _ = _ocr_backend_status_local()
    if ocr_available:
        try:
            from PIL import Image as PILImage
            import pytesseract  # noqa: F401
            with PILImage.open(image_path) as img:
                ocr_text = pytesseract.image_to_string(img).strip()
            if ocr_text:
                preview = _compact_preview_local(ocr_text)
                lines.append(f"  OCR text ({len(ocr_text)} chars): {preview}")
        except Exception:
            pass

    return "\n".join(lines)


def _ocr_backend_status_local() -> tuple[bool, str]:
    """Check if OCR (tesseract + pytesseract) is available."""
    try:
        import pytesseract  # noqa: F401
        import shutil
        if shutil.which("tesseract"):
            return True, "tesseract"
    except ImportError:
        pass
    return False, "none"


def _compact_preview_local(text: str, *, limit: int = 320) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "…"


def _human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
