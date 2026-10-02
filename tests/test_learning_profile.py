"""Profile updates preserve user instructions and reject stale or unsafe saves."""

from pathlib import Path

import pytest

from ite.agent.learning import PROFILE_MAX_BYTES
from ite.agent.learning_profile import (
    END,
    START,
    LearningPreferences,
    build_profile,
    read_setup_profile,
    save_profile,
)


def test_update_preserves_custom_instructions_and_prefills_answers():
    original = "# My style\nUse direct feedback.\n"
    first = build_profile(
        original,
        LearningPreferences(
            "Learn APIs", "Know Python", preferences="Prefer examples in prose"
        ),
    )
    answers = LearningPreferences.from_profile(first)
    assert answers.objective == "Learn APIs"
    assert answers.preferences == "Prefer examples in prose"
    updated = build_profile(
        first + "\nKeep this extra note.\n", LearningPreferences("Learn errors")
    )
    assert updated.startswith(original.rstrip())
    assert updated.endswith("\nKeep this extra note.\n")
    assert "Learn APIs" not in updated
    assert updated.count(START) == updated.count(END) == 1


def test_save_is_exclusive_and_rejects_changes_made_during_setup(tmp_path: Path):
    path = tmp_path / "learn.md"
    save_profile(path, "My preferences.", expected=None)
    with pytest.raises(ValueError, match="changed"):
        save_profile(path, "Overwrite", expected=None)
    path.write_text("Updated in my editor.")
    with pytest.raises(ValueError, match="changed"):
        save_profile(path, "Overwrite", expected="My preferences.")
    assert path.read_text() == "Updated in my editor."
    save_profile(path, "Reviewed update.", expected="Updated in my editor.")
    assert path.read_text() == "Reviewed update."
    assert not list(tmp_path.glob(".learn-*.tmp"))


def test_setup_refuses_symlinks_oversized_and_invalid_utf8(tmp_path: Path):
    path = tmp_path / "learn.md"
    target = tmp_path / "outside.md"
    target.write_text("Keep this.")
    path.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        save_profile(path, "Overwrite", expected="Keep this.")
    assert target.read_text() == "Keep this."
    path.unlink()
    path.write_bytes(b"x" * (PROFILE_MAX_BYTES + 1))
    with pytest.raises(ValueError, match="16 KiB"):
        read_setup_profile(path)
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="UTF-8"):
        read_setup_profile(path)


def test_preview_validation_and_malformed_managed_section(tmp_path: Path):
    path = tmp_path / "learn.md"
    for text in ("", "x" * (PROFILE_MAX_BYTES + 1)):
        with pytest.raises(ValueError):
            save_profile(path, text, expected=None)
    assert not path.exists()
    with pytest.raises(ValueError, match="malformed"):
        build_profile(START + "Missing end", LearningPreferences())
    with pytest.raises(ValueError, match="markers"):
        build_profile(None, LearningPreferences(START))
