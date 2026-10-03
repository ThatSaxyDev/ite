from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

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


def discover_attachable_files(cwd: Path, *, max_files: int = 10000) -> list[Path]:
    cwd = cwd.resolve()
    files: list[Path] = []
    attachment_roots = {cwd / ".ite" / "tmp_attachments", cwd / ".ite" / "attachments"}
    for root, dirs, filenames in os.walk(cwd):
        dirs[:] = [
            name
            for name in dirs
            if name not in _SKIP_DIRS
            and Path(root, name) not in attachment_roots
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
    stripped_query = query.rstrip()
    if stripped_query != query:
        if re.search(r"\.[A-Za-z0-9]{1,8}$", stripped_query):
            return None
        if re.match(r'^(?:"[^"\n]+"|\'[^\'\n]+\')$', stripped_query):
            inner = stripped_query[1:-1]
            if re.search(r"\.[A-Za-z0-9]{1,8}$", inner):
                return None
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
    cwd = cwd.resolve()
    for path in candidates:
        try:
            rel = str(path.relative_to(cwd))
        except ValueError:
            rel = str(path)
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


def format_attachment_ref(value: str) -> str:
    """Keep a reference readable, quoting paths containing whitespace."""
    if any(char.isspace() for char in value):
        return f'@"{value}"'
    return f"@{value}"


def attachment_copy_text(message: str, *, cwd: Path, paths: list[str]) -> str:
    """Serialize attachment locations into plain text that can be sent again.

    Each bubble owns this text, so clearing the draft or attaching another file
    with the same name cannot change what an older bubble copies.
    """
    if not paths:
        return message
    parts: list[str] = []
    used: set[str] = set()
    cursor = 0
    for ref in extract_inline_attachment_refs(message):
        parts.append(message[cursor:ref.start])
        resolved, error = _resolve_ref_path(
            ref.value, cwd=cwd, files=[], existing_paths=paths,
        )
        if error is None and resolved is not None:
            parts.append(format_attachment_ref(str(resolved)) + ref.trailing)
            used.add(str(resolved))
        else:
            parts.append(message[ref.start:ref.end])
        cursor = ref.end
    parts.append(message[cursor:])
    text = "".join(parts)
    remaining = [
        format_attachment_ref(str(Path(path).expanduser().resolve()))
        for path in paths if str(Path(path).expanduser().resolve()) not in used
    ]
    return " ".join([text.rstrip(), *remaining]).strip()


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
    if (Path(raw).is_absolute() or Path(raw).parent != Path(".")) and direct.is_file():
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
        if Path(raw).name == raw and resolved_existing.name.lower() == normalized_raw_name:
            queued_matches.append(resolved_existing)

    if queued_matches:
        unique_queued = sorted({str(path): path for path in queued_matches}.values(), key=lambda p: str(p))
        if len(unique_queued) == 1:
            return unique_queued[0], None
        options = ", ".join(str(path) for path in unique_queued[:3])
        return None, f"Ambiguous @{raw}. Matches: {options}"

    if direct.is_file():
        return direct, None

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


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_FILE_URI_RE = re.compile(r"^file://([^/]*)/(.*)$", re.IGNORECASE)
_BACKSLASH_ESCAPE_RE = re.compile(r"\\(.)")


@dataclass(frozen=True)
class DroppedFilePaths:
    """Parsed result for text that may contain dropped or pasted file paths.

    Terminals deliver drag-and-dropped files as text (bracketed paste or
    typed keystrokes) in a variety of formats: bare paths, quoted paths,
    backslash-escaped paths, ``file://`` URIs, and Windows drive-letter
    paths. This result separates validated files from rejected candidates.
    """

    paths: list[str]
    errors: list[str]
    path_like_count: int
    prose_count: int


def _is_path_like_candidate(candidate: str) -> bool:
    lowered = candidate.lower()
    return (
        candidate.startswith("/")
        or candidate.startswith("~")
        or lowered.startswith("file://")
        or bool(_WINDOWS_DRIVE_RE.match(candidate))
    )


def _path_exists(candidate: str) -> bool:
    try:
        return Path(candidate).expanduser().exists()
    except OSError:
        return False


def _all_existing_paths(tokens: list[str]) -> bool:
    return all(
        _is_path_like_candidate(token) and _path_exists(token) for token in tokens
    )


def _strip_wrapping_quotes(value: str) -> str:
    while len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value


def parse_dropped_file_paths(text: str, *, max_attachments: int | None = MAX_ATTACHMENTS) -> DroppedFilePaths:
    """Parse text that may hold one or more dropped/pasted file paths.

    Handles the formats terminals emit on drag-and-drop: bare absolute
    paths, single/double-quoted paths, POSIX backslash escapes, newline
    separated batches, ``file://`` URIs with percent-encoding, and Windows
    drive-letter paths. Returns only candidates that exist on disk as
    regular files; path-like but unresolvable candidates are reported as
    errors, and prose tokens are counted so callers can leave mixed content
    untouched.
    """
    raw = (text or "").strip()
    if not raw:
        return DroppedFilePaths([], [], 0, 0)

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    windows_style = any(
        _WINDOWS_DRIVE_RE.search(line)
        or _WINDOWS_DRIVE_RE.search(_strip_wrapping_quotes(line))
        for line in lines
    )

    candidates: list[str] = []
    if windows_style:
        for line in lines:
            quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', line)
            if quoted:
                candidates.extend(first or second for first, second in quoted)
            else:
                candidates.append(_strip_wrapping_quotes(line))
    else:
        for line in lines:
            stripped = _strip_wrapping_quotes(line)
            if stripped.lower().startswith("file://"):
                # Keep the whole line intact: terminals emit URIs whose
                # spaces may be literal rather than percent-encoded.
                candidates.append(stripped)
                continue
            try:
                tokens = shlex.split(stripped)
            except ValueError:
                candidates.append(stripped)
                continue
            if len(tokens) > 1 and not _all_existing_paths(tokens):
                # Terminals sometimes insert raw unescaped paths with
                # literal spaces; shlex tears those apart. Prefer the whole
                # line when it resolves as a single path.
                if _is_path_like_candidate(stripped) and _path_exists(stripped):
                    candidates.append(stripped)
                    continue
            candidates.extend(tokens)

    seen: set[str] = set()
    paths: list[str] = []
    errors: list[str] = []
    path_like_count = 0
    prose_count = 0

    for candidate in candidates:
        token = (candidate or "").strip()
        if not token:
            continue

        normalized = token
        uri_match = _FILE_URI_RE.match(token)
        if uri_match:
            host, uri_path = uri_match.group(1), f"/{uri_match.group(2)}"
            if host.lower() not in ("", "localhost"):
                errors.append(f"Cannot attach a file on a remote host: {token}")
                path_like_count += 1
                continue
            normalized = unquote(uri_path).strip()

        variants = [normalized]
        if token != normalized:
            variants.append(token)
        if "%" in normalized and not uri_match and not _WINDOWS_DRIVE_RE.match(normalized):
            decoded = unquote(normalized)
            if decoded != normalized:
                variants.append(decoded)
        if "\\" in normalized and not _WINDOWS_DRIVE_RE.match(normalized) and not uri_match:
            unescaped = _BACKSLASH_ESCAPE_RE.sub(r"\1", normalized)
            if unescaped != normalized:
                variants.append(unescaped)

        probe = variants[0]
        if not (_is_path_like_candidate(probe) or _is_path_like_candidate(token)):
            prose_count += 1
            continue
        path_like_count += 1

        matched: Path | None = None
        error: str | None = None
        for variant in dict.fromkeys(variants):
            expanded = Path(variant).expanduser()
            try:
                exists = expanded.exists()
            except OSError:
                # Tokens longer than NAME_MAX (and other stat failures) raise
                # here; treat them as unresolvable rather than crashing.
                exists = False
            if not exists:
                error = f"File not found: {expanded.name or variant}"
                continue
            try:
                is_file = expanded.is_file()
                is_dir = not is_file and expanded.is_dir()
            except OSError:
                error = f"File not found: {expanded.name or variant}"
                continue
            if not is_file:
                kind = "directory" if is_dir else "file"
                error = f"Cannot attach {kind}: {expanded.name}"
                break
            matched = expanded
            break
        if matched is None:
            errors.append(error or f"File not found: {token}")
            continue

        key = str(matched)
        if key not in seen:
            seen.add(key)
            paths.append(key)

    if max_attachments is not None and len(paths) > max_attachments:
        overflow = paths[max_attachments:]
        del paths[max_attachments:]
        names = ", ".join(Path(p).name for p in overflow[:3])
        more = "" if len(overflow) <= 3 else f" (+{len(overflow) - 3} more)"
        errors.append(
            f"File limit exceeded. Only {max_attachments} attachments allowed; skipped: {names}{more}"
        )

    return DroppedFilePaths(paths, errors, path_like_count, prose_count)
