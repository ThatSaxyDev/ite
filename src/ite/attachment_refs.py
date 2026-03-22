from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from ite.attachments import IMAGE_EXTS, MAX_ATTACHMENTS, PDF_EXTS, TEXT_EXTS


_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    "dist",
    "build",
    "coverage",
    ".idea",
    ".vscode",
}
_TRAILING_PUNCTUATION = ",.;:!?)]}"
_ATTACHMENT_EXTENSIONS = sorted(
    {ext.lstrip(".") for ext in IMAGE_EXTS | TEXT_EXTS | PDF_EXTS},
    key=len,
    reverse=True,
)
_ATTACHMENT_EXTENSIONS_RE = "|".join(re.escape(ext) for ext in _ATTACHMENT_EXTENSIONS)
_INLINE_REF_PATTERN = re.compile(
    rf'(?:(?<=^)|(?<=\s)|(?<=[(\[{{]))@(?P<ref>"[^"\n]+"|\'[^\'\n]+\'|(?:[^\s@][^@\n]*?\.(?:{_ATTACHMENT_EXTENSIONS_RE}))(?![\w.]))',
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class InlineAttachmentRef:
    raw: str
    value: str
    start: int
    end: int
    trailing: str = ""


@dataclass(frozen=True)
class InlineAttachmentResolution:
    message: str
    queued_paths: list[str]
    added_paths: list[str]
    refs: list[InlineAttachmentRef]
    errors: list[str]

    @property
    def had_refs(self) -> bool:
        return bool(self.refs)


def discover_attachable_files(cwd: Path, *, max_files: int = 250) -> list[Path]:
    cwd = cwd.resolve()
    files: list[Path] = []
    temp_root = cwd / ".ite" / "tmp_attachments"
    for root, dirs, filenames in os.walk(cwd):
        dirs[:] = [
            name
            for name in dirs
            if name not in _SKIP_DIRS
            and not str(Path(root, name)).startswith(str(temp_root))
        ]
        root_path = Path(root)
        for filename in filenames:
            if len(files) >= max_files:
                return files
            files.append(root_path / filename)
    return files


def extract_inline_attachment_refs(message: str) -> list[InlineAttachmentRef]:
    refs: list[InlineAttachmentRef] = []
    for match in _INLINE_REF_PATTERN.finditer(message or ""):
        raw = match.group("ref") or ""
        trailing = ""
        value = raw
        if value.startswith(("'", '"')) and value.endswith(value[0]):
            value = value[1:-1]
        else:
            while value and value[-1] in _TRAILING_PUNCTUATION:
                trailing = value[-1] + trailing
                value = value[:-1]
        value = value.strip()
        if not value:
            continue
        refs.append(
            InlineAttachmentRef(
                raw=raw,
                value=value,
                start=match.start(),
                end=match.end(),
                trailing=trailing,
            )
        )
    return refs


def extract_at_query(text: str) -> str | None:
    if "\n" in (text or ""):
        return None
    match = re.search(r"(?:^|[\s(\[{])@([^\n@]*)$", text or "")
    if not match:
        return None
    query = match.group(1)
    if re.search(r"\.[A-Za-z0-9]{1,8}\s+\S", query):
        return None
    return query


def suggest_inline_attachment_paths(
    query: str,
    *,
    cwd: Path,
    files: list[Path] | None = None,
    limit: int = 50,
) -> list[Path]:
    query_text = (query or "").strip().lower()
    candidates = files if files is not None else discover_attachable_files(cwd)
    scored: list[tuple[int, str, Path]] = []
    for path in candidates:
        try:
            rel = str(path.resolve().relative_to(cwd.resolve()))
        except Exception:
            rel = str(path.resolve())
        rel_lower = rel.lower()
        name_lower = path.name.lower()
        if query_text:
            if rel_lower == query_text:
                score = 0
            elif rel_lower.startswith(query_text):
                score = 1
            elif name_lower == query_text:
                score = 2
            elif name_lower.startswith(query_text):
                score = 3
            elif query_text in rel_lower:
                score = 4
            else:
                continue
        else:
            score = 5
        scored.append((score, rel_lower, path))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [path for _, _, path in scored[:limit]]


def _resolve_ref_path(
    ref: str,
    *,
    cwd: Path,
    files: list[Path],
    existing_paths: list[str] | tuple[str, ...] | None = None,
) -> tuple[Path | None, str | None]:
    raw = (ref or "").strip()
    if not raw:
        return None, "Empty file reference."

    direct = Path(raw).expanduser()
    if not direct.is_absolute():
        direct = (cwd / direct).resolve()
    else:
        direct = direct.resolve()
    if direct.exists() and direct.is_file():
        return direct, None

    queued_matches: list[Path] = []
    normalized_raw_name = Path(raw).name.lower()
    for existing in existing_paths or []:
        existing_path = Path(existing).expanduser()
        try:
            resolved_existing = existing_path.resolve()
        except Exception:
            continue
        rel_existing = ""
        try:
            rel_existing = str(resolved_existing.relative_to(cwd.resolve())).replace("\\", "/").lower()
        except Exception:
            rel_existing = str(resolved_existing).replace("\\", "/").lower()
        if rel_existing == raw.replace("\\", "/").lstrip("./").lower():
            queued_matches.append(resolved_existing)
            continue
        if resolved_existing.name.lower() == normalized_raw_name:
            queued_matches.append(resolved_existing)

    if queued_matches:
        unique_queued = sorted({str(path): path for path in queued_matches}.values(), key=lambda p: str(p))
        if len(unique_queued) == 1:
            return unique_queued[0], None
        options = ", ".join(str(path.relative_to(cwd)) for path in unique_queued[:3])
        return None, f"Ambiguous @{raw}. Matches: {options}"

    normalized = raw.replace("\\", "/").lstrip("./").lower()
    rel_matches: list[Path] = []
    base_matches: list[Path] = []
    for path in files:
        try:
            rel = str(path.resolve().relative_to(cwd.resolve())).replace("\\", "/")
        except Exception:
            rel = str(path.resolve()).replace("\\", "/")
        rel_lower = rel.lower()
        if rel_lower == normalized:
            rel_matches.append(path.resolve())
        if path.name.lower() == Path(raw).name.lower():
            base_matches.append(path.resolve())

    matches = rel_matches or base_matches
    if not matches:
        return None, f"File not found for @{raw}"
    unique = sorted({str(path): path for path in matches}.values(), key=lambda p: str(p))
    if len(unique) > 1:
        options = ", ".join(str(path.relative_to(cwd)) for path in unique[:3])
        return None, f"Ambiguous @{raw}. Matches: {options}"
    return unique[0], None


def resolve_inline_attachment_refs(
    message: str,
    *,
    cwd: Path,
    existing_paths: list[str] | tuple[str, ...] | None = None,
    files: list[Path] | None = None,
) -> InlineAttachmentResolution:
    refs = extract_inline_attachment_refs(message)
    if not refs:
        return InlineAttachmentResolution(
            message=(message or "").strip(),
            queued_paths=list(existing_paths or []),
            added_paths=[],
            refs=[],
            errors=[],
        )

    cwd = cwd.resolve()
    existing = [str(Path(path).expanduser().resolve()) for path in (existing_paths or [])]
    unique_existing: list[str] = []
    seen_existing: set[str] = set()
    for path in existing:
        if path in seen_existing:
            continue
        seen_existing.add(path)
        unique_existing.append(path)

    available_files = files if files is not None else discover_attachable_files(cwd, max_files=1000)
    resolved_paths: list[str] = []
    errors: list[str] = []

    rebuilt: list[str] = []
    cursor = 0
    for ref in refs:
        rebuilt.append(message[cursor:ref.start])
        resolved, error = _resolve_ref_path(
            ref.value,
            cwd=cwd,
            files=available_files,
            existing_paths=unique_existing + resolved_paths,
        )
        if error is not None:
            errors.append(error)
            rebuilt.append(message[ref.start:ref.end])
            cursor = ref.end
            continue
        resolved_path = str(resolved)
        if resolved_path not in unique_existing and resolved_path not in resolved_paths:
            resolved_paths.append(resolved_path)
        try:
            replacement = str(resolved.relative_to(cwd))
        except Exception:
            replacement = resolved.name
        rebuilt.append(replacement + ref.trailing)
        cursor = ref.end
    rebuilt.append(message[cursor:])

    if len(unique_existing) + len(resolved_paths) > MAX_ATTACHMENTS:
        available = max(0, MAX_ATTACHMENTS - len(unique_existing))
        errors.append(
            f"Too many attached files referenced with @ ({len(resolved_paths)} new, {len(unique_existing)} already queued). "
            f"Only {available} more allowed."
        )

    if errors:
        return InlineAttachmentResolution(
            message=(message or "").strip(),
            queued_paths=unique_existing,
            added_paths=[],
            refs=refs,
            errors=errors,
        )

    return InlineAttachmentResolution(
        message="".join(rebuilt).strip(),
        queued_paths=unique_existing + resolved_paths,
        added_paths=resolved_paths,
        refs=refs,
        errors=[],
    )
