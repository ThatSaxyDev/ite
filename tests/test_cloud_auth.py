import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.cloud.auth import CloudSession, get_activity, get_bundled_models, get_cloud_session, get_usage_summary
from ite.config.config import Config


class CloudAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)
        self.config = Config(
            cwd=self.base_path,
            api_key="test",
            cloud_auth_enabled=True,
            cloud_api_url="http://127.0.0.1:4000",
        )
        self.session = CloudSession(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            api_url="http://127.0.0.1:4000",
            client_id="ite-cli",
        )

    def test_cloud_accessors_return_empty_when_cloud_auth_errors(self) -> None:
        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session), patch(
            "ite.cloud.auth._get_json",
            side_effect=__import__("ite.cloud.auth", fromlist=["CloudAuthError"]).CloudAuthError("offline"),
        ):
            self.assertIsNone(get_cloud_session(self.config))
            self.assertEqual(get_bundled_models(self.config), [])
            self.assertIsNone(get_usage_summary(self.config))
            self.assertIsNone(get_activity(self.config))

    def test_get_bundled_models_preserves_availability_metadata(self) -> None:
        payload = {
            "ok": True,
            "models": [
                {
                    "modelName": "minimax-m2.7:cloud",
                    "label": "MiniMax M2.7",
                    "provider": "Bundled",
                    "available": False,
                    "unavailableReason": "Local bundled provider returned 500.",
                }
            ],
        }

        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session), patch(
            "ite.cloud.auth._get_json",
            side_effect=[(200, {"ok": True}), (200, payload)],
        ):
            models = get_bundled_models(self.config)

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["model_name"], "minimax-m2.7:cloud")
        self.assertFalse(models[0]["available"])
        self.assertEqual(
            models[0]["unavailable_reason"],
            "Local bundled provider returned 500.",
        )
