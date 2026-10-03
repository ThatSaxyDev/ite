from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from ite.attachment_refs import resolve_inline_attachment_refs
from ite.attachments import MAX_ATTACHMENTS, AttachmentManager, queue_attachment_paths
from ite.commands.attach import _queue_paths


def make_files(root: Path, count: int) -> list[str]:
    files = []
    for index in range(count):
        path = root / f"file_{index}.json"
        path.write_text("{}")
        files.append(str(path))
    return files


def test_ten_files_resolve_and_stage(tmp_path: Path) -> None:
    paths = make_files(tmp_path, 10)
    result = resolve_inline_attachment_refs(
        " ".join("@" + Path(path).name for path in paths), cwd=tmp_path, files=[],
    )
    assert MAX_ATTACHMENTS == 10
    assert result.errors == []
    assert result.queued_paths == paths
    staged, errors = AttachmentManager(tmp_path).stage_paths(paths, "test")
    assert errors == []
    assert len(staged) == 10


def test_queue_accepts_only_available_slots_and_deduplicates(tmp_path: Path) -> None:
    paths = make_files(tmp_path, 12)
    pending, accepted, errors = queue_attachment_paths(paths[:9], [paths[0], *paths[9:]])
    assert pending == paths[:10]
    assert accepted == [paths[0], paths[9]]
    assert len(errors) == 1
    assert "File limit exceeded" in errors[0]


def test_attach_command_reports_overflow(tmp_path: Path) -> None:
    paths = make_files(tmp_path, 11)
    output = StringIO()
    ctx = SimpleNamespace(
        agent=SimpleNamespace(session=SimpleNamespace(pending_attachment_paths=paths[:9])),
        console=Console(file=output, width=120),
    )
    assert _queue_paths(ctx, paths[9:]) == 1
    assert ctx.agent.session.pending_attachment_paths == paths[:10]
    assert "File limit exceeded" in output.getvalue()
