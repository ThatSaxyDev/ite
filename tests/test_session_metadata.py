from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from ite.agent.session_manager import SessionManager, SessionSnapshot
from ite.client.response import TokenUsage


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionManager:
    monkeypatch.setattr("ite.agent.session_manager.get_data_dir", lambda: tmp_path)
    return SessionManager()


def legacy_session(manager: SessionManager, name: str = "First name") -> Path:
    path = manager.sessions_dir / "example.json"
    path.write_text(
        json.dumps(
            {
                "session_id": "example",
                "name": name,
                "workspace_path": "/tmp/project",
                "created_at": "2026-10-01",
                "updated_at": "2026-10-01",
                "turn_count": 2,
                "messages": [
                    {"role": "assistant", "content": "large transcript" * 10000}
                ],
            }
        )
    )
    return path


def test_backfill_avoids_reading_transcripts_again(manager: SessionManager) -> None:
    legacy_session(manager)
    load = Mock(wraps=manager._load_session_json)
    manager._load_session_json = load
    assert manager.list_sessions()[0]["name"] == "First name"
    assert load.call_count == 1
    summary = json.loads((manager.metadata_dir / "example.json").read_text())
    assert "messages" not in summary["session"]
    assert (manager.metadata_dir / "example.json").stat().st_size < 500
    assert (
        manager.list_sessions(workspace_path="/tmp/project")[0]["name"] == "First name"
    )
    assert manager.list_workspaces() == [str(Path("/tmp/project").resolve())]
    assert load.call_count == 1
    assert manager.list_sessions(workspace_path="/tmp/elsewhere") == []


def test_external_edit_and_delete_are_detected(manager: SessionManager) -> None:
    path = legacy_session(manager)
    manager.list_sessions()
    legacy_session(manager, name="Renamed by another process")
    assert manager.list_sessions()[0]["name"] == "Renamed by another process"
    path.unlink()
    assert manager.list_sessions() == []


@pytest.mark.parametrize("contents", ["invalid JSON", "[]", "{}"])
def test_invalid_metadata_is_rebuilt(manager: SessionManager, contents: str) -> None:
    legacy_session(manager)
    manager.list_sessions()
    (manager.metadata_dir / "example.json").write_text(contents)
    assert manager.list_sessions()[0]["name"] == "First name"


def test_save_updates_metadata_without_reading_transcript(
    manager: SessionManager,
) -> None:
    snapshot = SessionSnapshot(
        session_id="saved",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        turn_count=1,
        messages=[{"role": "user", "content": "hello"}],
        total_usage=TokenUsage(),
        name="Saved title",
        workspace_path="/tmp/project",
    )
    manager.save_session(snapshot)
    manager._load_session_json = Mock(side_effect=AssertionError("transcript read"))
    assert manager.list_sessions()[0]["name"] == "Saved title"
    snapshot.name = "Renamed title"
    manager.save_session(snapshot)
    assert manager.list_sessions()[0]["name"] == "Renamed title"
    manager.delete_session("saved")
    assert manager.list_sessions() == []
    assert not (manager.metadata_dir / "saved.json").exists()


def test_stale_metadata_falls_back_after_external_corruption(
    manager: SessionManager,
) -> None:
    path = legacy_session(manager)
    manager.list_sessions()
    path.write_text("broken")
    assert manager.list_sessions() == []
    assert not path.exists()
    assert list((manager.sessions_dir / "corrupt").glob("example.*.json"))
