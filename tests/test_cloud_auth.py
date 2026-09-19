import json
import os
import stat
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from ite.cloud.auth import (
    CloudSessionState,
    CloudSession,
    CloudCredentialStoreError,
    _CLOUD_ACCESS_TOKEN_CACHE,
    _get_json,
    _load_cloud_session,
    _post_json,
    _refresh_cloud_session,
    _save_cloud_session,
    ensure_cloud_auth,
    get_activity,
    get_bundled_access_status,
    get_bundled_models,
    get_cloud_auth_status,
    get_cloud_entitlements,
    get_cloud_entitlements_result,
    get_remote_companion_access_status,
    get_cloud_session,
    has_stored_cloud_auth,
    has_remote_companion_access,
    is_cloud_api_reachable,
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

    def test_keyring_read_failure_is_reported_as_credential_error(self) -> None:
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
            patch(
                "ite.cloud.auth.keyring.get_password",
                side_effect=Exception("keychain unavailable"),
            ),
        ):
            with self.assertRaises(CloudCredentialStoreError):
                _load_cloud_session()
            status = get_cloud_auth_status(self.config)
            remote_status = get_remote_companion_access_status(self.config)
            has_stored = has_stored_cloud_auth(self.config)

        self.assertTrue(session_path.exists())
        self.assertEqual(status.state, CloudSessionState.CREDENTIAL_ERROR)
        self.assertIn("OS credential store", status.message)
        self.assertEqual(remote_status.state, CloudSessionState.CREDENTIAL_ERROR)
        self.assertTrue(has_stored)

    def test_missing_keyring_refresh_token_is_reported_as_credential_error(self) -> None:
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
            patch("ite.cloud.auth.keyring.get_password", return_value=None),
        ):
            status = get_cloud_auth_status(self.config)
            has_stored = has_stored_cloud_auth(self.config)

        self.assertEqual(status.state, CloudSessionState.CREDENTIAL_ERROR)
        self.assertIn("refresh credential is missing", status.message)
        self.assertTrue(has_stored)

    def test_remote_access_uses_recent_cached_entitlement_on_keyring_failure(self) -> None:
        data_dir = self.base_path / "data"
        session = CloudSession(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            api_url="http://127.0.0.1:4000",
            client_id=self.config.cloud_client_id,
        )

        with (
            patch("ite.cloud.auth.get_data_dir", return_value=data_dir),
            patch("ite.cloud.auth.keyring.set_password"),
            patch("ite.cloud.auth.keyring.get_password", return_value="refresh"),
            patch(
                "ite.cloud.auth._get_json",
                side_effect=[
                    (200, {"ok": True}),
                    (
                        200,
                        {
                            "ok": True,
                            "entitlements": {"remoteCompanion": True},
                        },
                    ),
                ],
            ),
        ):
            _save_cloud_session(session)
            self.assertTrue(has_remote_companion_access(self.config))

        _CLOUD_ACCESS_TOKEN_CACHE.clear()
        with (
            patch("ite.cloud.auth.get_data_dir", return_value=data_dir),
            patch(
                "ite.cloud.auth.keyring.get_password",
                side_effect=Exception("keychain unavailable"),
            ),
        ):
            status = get_remote_companion_access_status(self.config)

        self.assertEqual(status.state, CloudSessionState.VALID)
        self.assertIn("entitlement cache", status.message)

    def test_cloud_accessors_return_empty_when_cloud_auth_errors(self) -> None:
        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session), patch(
            "ite.cloud.auth._get_json",
            side_effect=__import__("ite.cloud.auth", fromlist=["CloudAuthError"]).CloudAuthError("offline"),
        ):
            self.assertIsNone(get_cloud_session(self.config))
            self.assertEqual(get_bundled_models(self.config), [])
            self.assertIsNone(get_usage_summary(self.config))
            self.assertIsNone(get_activity(self.config))

    def test_entitlements_marks_metadata_unavailable_after_second_me_request_fails(self) -> None:
        """A token check succeeding must not make a failed metadata fetch Free."""
        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session), patch(
            "ite.cloud.auth._get_json",
            side_effect=[
                (200, {"ok": True}),
                (503, {"ok": False}),
            ],
        ):
            result = get_cloud_entitlements_result(self.config)

        self.assertTrue(result.auth.is_valid)
        self.assertFalse(result.metadata_available)
        self.assertEqual(result.entitlements, {})

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
            side_effect=[
                (200, {"ok": True}),
                (200, {"ok": True, "entitlements": {"bundledInference": True}}),
                (200, payload),
            ],
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

    def test_bundled_access_status_requires_bundled_entitlement(self) -> None:
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
                            "remoteCompanion": False,
                        },
                    },
                ),
            ],
        ):
            status = get_bundled_access_status(self.config)

        self.assertEqual(status.state, CloudSessionState.NO_ENTITLEMENT)
        self.assertIn("iTE Pro", status.message)

    def test_bundled_models_require_bundled_entitlement_before_listing(self) -> None:
        with patch("ite.cloud.auth._load_cloud_session", return_value=self.session), patch(
            "ite.cloud.auth._get_json",
            side_effect=[
                (200, {"ok": True}),
                (
                    200,
                    {
                        "ok": True,
                        "entitlements": {"bundledInference": False},
                    },
                ),
            ],
        ) as get_json:
            models = get_bundled_models(self.config)

        self.assertEqual(models, [])
        self.assertEqual(get_json.call_count, 2)

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

    def test_cloud_auth_status_treats_forbidden_me_as_signed_in(self) -> None:
        with (
            patch("ite.cloud.auth._load_cloud_session", return_value=self.session),
            patch("ite.cloud.auth._get_json", return_value=(403, {"ok": False})),
        ):
            status = get_cloud_auth_status(self.config)

        self.assertEqual(status.state, CloudSessionState.VALID)
        self.assertIs(status.session, self.session)

    def test_remote_access_reports_forbidden_me_as_no_entitlement(self) -> None:
        with (
            patch("ite.cloud.auth._load_cloud_session", return_value=self.session),
            patch("ite.cloud.auth._get_json", return_value=(403, {"ok": False})),
        ):
            status = get_remote_companion_access_status(self.config)

        self.assertEqual(status.state, CloudSessionState.NO_ENTITLEMENT)
        self.assertIn("403", status.message)

    def test_refresh_preserves_refresh_token_when_response_omits_rotation(self) -> None:
        session = CloudSession(
            access_token="",
            refresh_token="stored-refresh",
            access_expires_at=0,
            api_url="http://127.0.0.1:4000",
            client_id="test-device",
        )
        refresh_payload = {
            "ok": True,
            "accessToken": "new-access",
            "expiresIn": 3600,
        }

        with (
            patch("ite.cloud.auth._load_cloud_session", return_value=session),
            patch("ite.cloud.auth._post_json", return_value=(200, refresh_payload)),
            patch("ite.cloud.auth._save_cloud_session") as save_session,
        ):
            status = get_cloud_auth_status(self.config)

        self.assertEqual(status.state, CloudSessionState.VALID)
        saved_session = save_session.call_args.args[0]
        self.assertEqual(saved_session.refresh_token, "stored-refresh")

    def test_refresh_reuses_newer_session_after_concurrent_rotation(self) -> None:
        stale = CloudSession(
            access_token="",
            refresh_token="old-refresh",
            access_expires_at=0,
            api_url="http://127.0.0.1:4000",
            client_id="test-device",
        )
        current = CloudSession(
            access_token="new-access",
            refresh_token="new-refresh",
            access_expires_at=9999999999,
            api_url="http://127.0.0.1:4000",
            client_id="test-device",
        )

        with (
            patch("ite.cloud.auth._load_cloud_session", return_value=current),
            patch("ite.cloud.auth._post_json") as post_json,
        ):
            refreshed = _refresh_cloud_session(stale)

        self.assertIs(refreshed, current)
        post_json.assert_not_called()

    def test_post_json_handles_non_json_http_error_body(self) -> None:
        error = HTTPError(
            "https://example.test/auth/refresh",
            403,
            "Forbidden",
            {},
            BytesIO(b"<html>Just a moment...</html>"),
        )

        with patch("ite.cloud.auth.urlopen", side_effect=error):
            status, payload = _post_json(
                "https://example.test/auth/refresh",
                {"refreshToken": "refresh"},
            )

        self.assertEqual(status, 403)
        self.assertEqual(payload, {})

    def test_get_json_handles_non_json_http_error_body(self) -> None:
        error = HTTPError(
            "https://example.test/me",
            503,
            "Service Unavailable",
            {},
            BytesIO(b"<!DOCTYPE html><title>Service Suspended</title>"),
        )

        with patch("ite.cloud.auth.urlopen", side_effect=error):
            status, payload = _get_json("https://example.test/me")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {})

    def test_is_cloud_api_reachable_accepts_auth_required_response(self) -> None:
        with patch("ite.cloud.auth._get_json", return_value=(401, {})) as get_json:
            self.assertTrue(is_cloud_api_reachable(self.config))

        get_json.assert_called_once_with("http://127.0.0.1:4000/auth/me")

    def test_is_cloud_api_reachable_rejects_server_error_response(self) -> None:
        with patch("ite.cloud.auth._get_json", return_value=(503, {})):
            self.assertFalse(is_cloud_api_reachable(self.config))
