from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ite.update_check import (
    RuntimeUpdateNotice,
    mark_update_notice_seen,
    should_show_update_notice,
)


def _notice(*, severity: str = "info", required: bool = False) -> RuntimeUpdateNotice:
    return RuntimeUpdateNotice(
        latest_version="0.0.46",
        minimum_supported_version="0.0.45",
        severity=severity,
        title="Update available",
        message="",
        upgrade_command="pipx upgrade ite-agent",
        release_url=None,
        update_required=required,
    )


class UpdateCheckTests(TestCase):
    def test_info_notice_is_marked_seen(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("ite.update_check.get_data_dir", return_value=Path(temp_dir)):
                notice = _notice(severity="info")

                self.assertTrue(should_show_update_notice(notice))
                mark_update_notice_seen(notice)
                self.assertFalse(should_show_update_notice(notice))

    def test_recommended_notice_shows_every_launch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("ite.update_check.get_data_dir", return_value=Path(temp_dir)):
                notice = _notice(severity="recommended")

                self.assertTrue(should_show_update_notice(notice))
                mark_update_notice_seen(notice)
                self.assertTrue(should_show_update_notice(notice))

    def test_required_notice_shows_every_launch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("ite.update_check.get_data_dir", return_value=Path(temp_dir)):
                notice = _notice(severity="required", required=True)

                self.assertTrue(should_show_update_notice(notice))
                mark_update_notice_seen(notice)
                self.assertTrue(should_show_update_notice(notice))
