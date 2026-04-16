from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import mimetypes
import shutil
import uuid

MAX_ATTACHMENTS = 3
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
                # Also cache image to persistent location for survival across restarts
                try:
                    from ite.tools.builtin.media_tools import _cache_image
                    cached_path = _cache_image(src)
                    # Store cached path in metadata for later use
                    cached_path_str = str(cached_path)
                except Exception:
                    cached_path_str = None
            elif ext in PDF_EXTS:
                kind = "pdf"
                cached_path_str = None
            else:
                kind = "text"
                cached_path_str = None
            dest = turn_dir / f"{uuid.uuid4().hex}_{src.name}"
            shutil.copy2(src, dest)

            staged.append(
                Attachment(
                    id=uuid.uuid4().hex,
                    original_name=src.name,
                    mime_type=mime,
                    size_bytes=size,
                    source_path=str(src),
                    temp_path=str(dest),
                    kind=kind,
                )
            )
            # Add cached_path to metadata after creating attachment
            if cached_path_str:
                staged[-1].metadata = {"cached_path": cached_path_str}

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

    def is_in_workspace(path_text: str) -> bool:
        try:
            Path(path_text).resolve().relative_to(workspace.resolve())
            return True
        except Exception:
            return False

    lines = ["Attached files:"]
    for a in attachments:
        source_text = display_path(a.source_path)
        temp_text = display_path(a.temp_path)
        line = f"- {a.original_name} ({a.mime_type}, {a.size_bytes} bytes) -> {source_text}"
        if not is_in_workspace(a.source_path) and temp_text != source_text:
            line += f" [attached as {temp_text}]"
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
) -> str | list[dict]:
    text = build_user_text_with_manifest(message, attachments, workspace)
    images = [a for a in attachments if a.kind == "image"]
    if not images:
        return text

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
