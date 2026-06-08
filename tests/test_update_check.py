from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ite.config.config import Config
from ite.update_check import (
    RuntimeUpdateNotice,
    check_runtime_update,
    get_notification_type,
    mark_update_notice_seen,
    should_show_update_notice,
)


def _notice(*, required: bool = False) -> RuntimeUpdateNotice:
    return RuntimeUpdateNotice(
        latest_version="0.0.46",
        title="Update available",
        message="",
        upgrade_command="pipx upgrade ite-agent",
        installer_command="curl -fsSL https://ite.kiishi.space/install.sh | sh",
        release_url=None,
        update_required=required,
        required=required,
    )


class UpdateCheckTests(TestCase):
    def test_info_notice_is_marked_seen(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("ite.update_check.get_data_dir", return_value=Path(temp_dir)):
                notice = _notice()

                self.assertTrue(should_show_update_notice(notice))
                self.assertEqual(get_notification_type(notice), "toast")
                mark_update_notice_seen(notice)
                self.assertTrue(should_show_update_notice(notice))

    def test_soft_notice_moves_to_feed_after_three_seen_counts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("ite.update_check.get_data_dir", return_value=Path(temp_dir)):
                notice = _notice()

                for _ in range(3):
                    self.assertEqual(get_notification_type(notice), "toast")
                    mark_update_notice_seen(notice)
                self.assertEqual(get_notification_type(notice), "feed")

    def test_required_notice_shows_every_launch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("ite.update_check.get_data_dir", return_value=Path(temp_dir)):
                notice = _notice(required=True)

                self.assertTrue(should_show_update_notice(notice))
                self.assertEqual(get_notification_type(notice), "feed")
                mark_update_notice_seen(notice)
                self.assertTrue(should_show_update_notice(notice))

    def test_check_runtime_update_ignores_malformed_json_response(self) -> None:
        config = Config(cloud_api_url="https://example.test")

        with patch("ite.update_check._get_json", side_effect=ValueError("bad json")):
            self.assertIsNone(check_runtime_update(config))

    def test_check_runtime_update_ignores_non_dict_payload(self) -> None:
        config = Config(cloud_api_url="https://example.test")

        with patch("ite.update_check._get_json", return_value=(200, [])):
            self.assertIsNone(check_runtime_update(config))
