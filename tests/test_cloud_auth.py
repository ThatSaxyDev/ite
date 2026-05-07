import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.cloud.auth import (
    CloudSessionState,
    CloudSession,
    _CLOUD_ACCESS_TOKEN_CACHE,
    _load_cloud_session,
    _save_cloud_session,
    ensure_cloud_auth,
    get_activity,
    get_bundled_models,
    get_cloud_auth_status,
    get_cloud_entitlements,
    get_cloud_session,
    has_stored_cloud_auth,
    has_remote_companion_access,
    get_usage_summary,
)
from ite.config.config import Config


class CloudAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        _CLOUD_ACCESS_TOKEN_CACHE.clear()
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
            client_id="test-device",
        )

    def test_save_cloud_session_stores_refresh_token_in_keyring_not_json(self) -> None:
        data_dir = self.base_path / "data"

        with (
            patch("ite.cloud.auth.get_data_dir", return_value=data_dir),
            patch("ite.cloud.auth.keyring.set_password") as set_password,
        ):
            _save_cloud_session(self.session)

        session_path = data_dir / "auth" / "cloud_session.json"
        payload = json.loads(session_path.read_text(encoding="utf-8"))

        self.assertNotIn("access_token", payload)
        self.assertNotIn("refresh_token", payload)
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["api_url"], self.session.api_url)
        self.assertEqual(payload["client_id"], self.session.client_id)
        set_password.assert_called_once()
        self.assertEqual(set_password.call_args.args[2], "refresh")

        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(session_path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(session_path.stat().st_mode), 0o600)

    def test_load_cloud_session_rejects_legacy_plaintext_tokens_and_requires_login(self) -> None:
        data_dir = self.base_path / "data"
        session_path = data_dir / "auth" / "cloud_session.json"
        session_path.parent.mkdir(parents=True)
        session_path.write_text(
            json.dumps(
                {
                    "access_token": "legacy-access",
                    "refresh_token": "legacy-refresh",
                    "access_expires_at": 9999999999,
                    "api_url": "http://127.0.0.1:4000",
                    "client_id": "test-device",
                }
            ),
            encoding="utf-8",
        )

        with (
            patch("ite.cloud.auth.get_data_dir", return_value=data_dir),
            patch("ite.cloud.auth.keyring.set_password") as set_password,
            patch("ite.cloud.auth.keyring.delete_password") as delete_password,
        ):
            session = _load_cloud_session()

        self.assertIsNone(session)
        set_password.assert_not_called()
        delete_password.assert_called_once()
        self.assertFalse(session_path.exists())

    def test_load_cloud_session_uses_keyring_refresh_token_without_persisted_access(self) -> None:
        data_dir = self.base_path / "data"
        session_path = data_dir / "auth" / "cloud_session.json"
        session_path.parent.mkdir(parents=True)
        session_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "access_expires_at": 9999999999,
                    "api_url": "http://127.0.0.1:4000",
                    "client_id": "test-device",
                }
            ),
            encoding="utf-8",
        )

        with (
            patch("ite.cloud.auth.get_data_dir", return_value=data_dir),
            patch("ite.cloud.auth.keyring.get_password", return_value="stored-refresh"),
        ):
            session = _load_cloud_session()

        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.access_token, "")
        self.assertEqual(session.access_expires_at, 0)
        self.assertEqual(session.refresh_token, "stored-refresh")

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
                    "modelName": "minimax/minimax-m2.7",
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
        self.assertEqual(models[0]["model_name"], "minimax/minimax-m2.7")
        self.assertFalse(models[0]["available"])
        self.assertEqual(
            models[0]["unavailable_reason"],
            "Local bundled provider returned 500.",
        )

    def test_remote_companion_access_uses_explicit_entitlement(self) -> None:
        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session), patch(
            "ite.cloud.auth._get_json",
            side_effect=[
                (200, {"ok": True}),
                (
                    200,
                    {
                        "ok": True,
                        "entitlements": {
                            "bundledInference": False,
                            "remoteCompanion": True,
                        },
                    },
                ),
            ],
        ):
            self.assertEqual(
                get_cloud_entitlements(self.config)["remoteCompanion"],
                True,
            )

        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session), patch(
            "ite.cloud.auth._get_json",
            side_effect=[
                (200, {"ok": True}),
                (
                    200,
                    {
                        "ok": True,
                        "entitlements": {
                            "bundledInference": False,
                            "remoteCompanion": True,
                        },
                    },
                ),
            ],
        ):
            self.assertTrue(has_remote_companion_access(self.config))

    def test_remote_companion_access_falls_back_to_bundled_entitlement(self) -> None:
        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session), patch(
            "ite.cloud.auth._get_json",
            side_effect=[
                (200, {"ok": True}),
                (
                    200,
                    {
                        "ok": True,
                        "entitlements": {
                            "bundledInference": True,
                        },
                    },
                ),
            ],
        ):
            self.assertTrue(has_remote_companion_access(self.config))

    def test_ensure_cloud_auth_waits_for_browser_ready_signal(self) -> None:
        start_payload = {
            "ok": True,
            "authUrl": "https://example.com/auth",
            "pollToken": "poll-token",
            "expiresIn": 60,
            "interval": 1,
        }
        pending_payload = {
            "ok": True,
            "browserReady": False,
            "accessToken": "too-early",
            "refreshToken": "too-early-refresh",
            "expiresIn": 3600,
        }
        complete_payload = {
            "ok": True,
            "browserReady": True,
            "accessToken": "access",
            "refreshToken": "refresh",
            "expiresIn": 3600,
        }

        with (
            patch("ite.cloud.auth._load_cloud_session", return_value=None),
            patch(
                "ite.cloud.auth._post_json",
                side_effect=[
                    (200, start_payload),
                    (200, pending_payload),
                    (200, complete_payload),
                ],
            ) as post_json,
            patch("ite.cloud.auth.webbrowser.open", return_value=True),
            patch("ite.cloud.auth.time.sleep"),
            patch("ite.cloud.auth._save_cloud_session") as save_session,
        ):
            ensure_cloud_auth(None, self.config)

        self.assertEqual(post_json.call_count, 3)
        saved_session = save_session.call_args.args[0]
        self.assertEqual(saved_session.access_token, "access")
        self.assertEqual(saved_session.refresh_token, "refresh")
        start_call_payload = post_json.call_args_list[0].args[1]
        self.assertIn("deviceName", start_call_payload)
        self.assertIn("deviceLabel", start_call_payload)

    def test_has_stored_cloud_auth_checks_local_session_only(self) -> None:
        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session):
            self.assertTrue(has_stored_cloud_auth(self.config))

    def test_has_stored_cloud_auth_accepts_refresh_token_without_access_token(self) -> None:
        session = CloudSession(
            access_token="",
            refresh_token="stored-refresh",
            access_expires_at=0,
            api_url="http://127.0.0.1:4000",
            client_id="test-device",
        )

        with patch("ite.cloud.auth._load_cloud_session", return_value=session):
            self.assertTrue(has_stored_cloud_auth(self.config))

    def test_cloud_auth_status_refreshes_rejected_access_token_once(self) -> None:
        refresh_payload = {
            "ok": True,
            "accessToken": "new-access",
            "refreshToken": "new-refresh",
            "expiresIn": 3600,
        }
        with (
            patch("ite.cloud.auth._load_cloud_session", return_value=self.session),
            patch("ite.cloud.auth._get_json", return_value=(401, {"ok": False})),
            patch("ite.cloud.auth._post_json", return_value=(200, refresh_payload)),
            patch("ite.cloud.auth._save_cloud_session"),
        ):
            status = get_cloud_auth_status(self.config)

        self.assertEqual(status.state, CloudSessionState.VALID)
