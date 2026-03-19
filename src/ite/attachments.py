from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import mimetypes
import shutil
import uuid
import hashlib
from ite.config.loader import get_data_dir

MAX_ATTACHMENTS = 3
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024

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
    kind: str  # image | text

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_name": self.original_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "source_path": self.source_path,
            "temp_path": self.temp_path,
            "kind": self.kind,
        }


class AttachmentManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        workspace_key = hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:12]
        self.temp_root = get_data_dir() / "tmp_attachments" / workspace_key

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
            if ext in PDF_EXTS:
                errors.append(f"PDF attachments are not supported in v1: {src.name}")
                continue
            if ext not in IMAGE_EXTS and ext not in TEXT_EXTS:
                errors.append(f"Unsupported attachment type: {src.name}")
                continue

            size = src.stat().st_size
            if size > MAX_FILE_SIZE_BYTES:
                errors.append(
                    f"Attachment too large: {src.name} ({size / (1024 * 1024):.1f}MB), max 5.0MB"
                )
                continue

            mime = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
            kind = "image" if ext in IMAGE_EXTS else "text"
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

        return staged, errors

    def cleanup_turn(self, turn_id: str) -> None:
        target = self.temp_root / turn_id
        if not target.exists():
            return
        shutil.rmtree(target, ignore_errors=True)


def _manifest_lines(attachments: list[Attachment], workspace: Path) -> list[str]:
    lines = ["Attached files:"]
    for a in attachments:
        source = Path(a.source_path)
        try:
            rel = source.resolve().relative_to(workspace.resolve())
            rel_text = str(rel)
        except Exception:
            rel_text = a.source_path
        lines.append(
            f"- {a.original_name} ({a.mime_type}, {a.size_bytes} bytes) -> {rel_text}"
        )
    return lines


def build_user_text_with_manifest(message: str, attachments: list[Attachment], workspace: Path) -> str:
    text = (message or "").strip()
    if not attachments:
        return text
    return f"{text}\n\n" + "\n".join(_manifest_lines(attachments, workspace))


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
        raw = p.read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        mime = img.mime_type if "/" in img.mime_type else "image/png"
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
        )
    return parts
