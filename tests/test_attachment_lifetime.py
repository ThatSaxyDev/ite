from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from ite.attachment_refs import discover_attachable_files
from ite.attachments import AttachmentManager, build_user_text_with_manifest
from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.builtin.media_tools import ReadImageTool
from ite.ui.reup._composer import ComposerMixin
from ite.ui.reup._turn import TurnMixin


def advertised_path(text: str, workspace: Path) -> Path:
    value = text.split(" -> ", 1)[1].split(" [source: ", 1)[0]
    return workspace / value


@pytest.mark.parametrize("suffix", [".png", ".pdf", ".json"])
def test_manifest_path_survives_turn_cleanup_and_original_removal(tmp_path: Path, suffix: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = tmp_path / ("Screenshot with spaces" + suffix)
    if suffix == ".png":
        Image.new("RGB", (8, 8), "red").save(original)
    else:
        original.write_bytes(b"original attached content")
    expected = original.read_bytes()
    manager = AttachmentManager(workspace)
    staged, errors = manager.stage_paths([original], "turn1")
    assert errors == []
    text = build_user_text_with_manifest("inspect this", staged, workspace)
    path = advertised_path(text, workspace)
    assert "tmp_attachments" not in text
    manager.cleanup_turn("turn1")
    original.unlink()
    assert not Path(staged[0].temp_path).exists()
    assert path.read_bytes() == expected
    assert Path(AttachmentManager(workspace).snapshot_root).exists()
    assert path not in discover_attachable_files(workspace)


def test_followup_read_image_uses_manifest_after_actual_turn_cleanup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = tmp_path / "Screenshot 2026-10-03 at 13.46.30.png"
    Image.new("RGB", (8, 8), "red").save(original)
    manager = AttachmentManager(workspace)
    staged, errors = manager.stage_paths([original], "reup_1")
    assert errors == []
    text = build_user_text_with_manifest("read these fields", staged, workspace)
    path = advertised_path(text, workspace)

    async def run(_message, **_kwargs):
        if False:
            yield None
    app = SimpleNamespace(_workspace_for_session_id=lambda _session_id: workspace)
    asyncio.run(TurnMixin._agent_turn(
        app, SimpleNamespace(run=run), "read these fields", "session", 1,
        attachment_turn_id="reup_1",
    ))
    original.unlink()
    cache = tmp_path / "image_cache"
    cache.mkdir()
    with (
        patch("ite.tools.builtin.media_tools._get_image_cache_dir", return_value=cache),
        patch("ite.tools.builtin.media_tools._ocr_backend_status", return_value=(False, "unavailable")),
    ):
        result = asyncio.run(ReadImageTool(Config(cwd=workspace, api_key="test")).execute(ToolInvocation(params={"path": str(path)}, cwd=workspace)))
    assert result.success, result.error
    assert result.metadata["width"] == 8
    assert result.metadata["height"] == 8
    assert result.content_parts is not None


def test_same_turn_number_in_two_chats_has_isolated_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "report.json"
    source.write_text("{}")
    app = SimpleNamespace(post_attachment_note=lambda _message: None)
    prepared = [ComposerMixin._prepare_attachments_for_turn(
        app, message="inspect this", attachments=[str(source)],
        turn_id=1, workspace=tmp_path,
    ) for _ in range(2)]
    assert prepared[0][2] != prepared[1][2]
    manager = AttachmentManager(tmp_path)
    manager.cleanup_turn(prepared[0][2])
    assert Path(prepared[1][3][0].temp_path).exists()
    assert advertised_path(prepared[0][0], tmp_path).exists()


def test_snapshots_deduplicate_but_preserve_changed_file_versions(tmp_path: Path) -> None:
    source = tmp_path / "report.json"
    source.write_text("first")
    manager = AttachmentManager(tmp_path)
    first, _ = manager.stage_paths([source], "one")
    repeated, _ = manager.stage_paths([source], "two")
    assert first[0].metadata == repeated[0].metadata
    source.write_text("second")
    changed, _ = manager.stage_paths([source], "three")
    assert first[0].metadata != changed[0].metadata
    for turn in ["one", "two", "three"]:
        manager.cleanup_turn(turn)
    assert Path(first[0].metadata["cached_path"]).read_text() == "first"
    assert Path(changed[0].metadata["cached_path"]).read_text() == "second"
