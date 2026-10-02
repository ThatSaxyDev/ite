"""Bounded cloud status checks and the real header outage/recovery flow."""

from __future__ import annotations

import asyncio
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from textual.widgets import Static, TextArea

from ite.cloud import auth
from ite.cloud.auth import CloudAuthStatus, CloudEntitlementsResult, CloudSessionState
from ite.cloud.request_budget import http_settings, run_status_request
from ite.config.config import Config
from ite.ui.reup.app import ReupApp


class CloudStatusBudgetTests(unittest.IsolatedAsyncioTestCase):
    def test_status_transport_is_fast_and_normal_retry_policy_is_unchanged(self):
        for function, args in (
            (auth._get_json, ("https://offline.example.test",)),
            (auth._post_json, ("https://offline.example.test", {})),
        ):
            with (
                patch(
                    "ite.cloud.auth.urlopen", side_effect=URLError("refused")
                ) as request,
                patch("ite.cloud.auth.time.sleep") as sleep,
            ):
                with self.assertRaises(auth.CloudConnectionError):
                    run_status_request(function, *args)
                self.assertEqual(request.call_count, 1)
                self.assertLessEqual(request.call_args.kwargs["timeout"], 2.0)
                sleep.assert_not_called()
                request.reset_mock()
                with self.assertRaises(auth.CloudConnectionError):
                    function(*args)
                self.assertEqual(request.call_count, 11)
                self.assertEqual(http_settings(10, 10), (10, 10))

    def test_expired_request_budget_prevents_more_transport_calls(self):
        def fetch():
            with patch("ite.cloud.request_budget.time.monotonic", return_value=100):
                return http_settings(10, 10)

        with (
            patch("ite.cloud.request_budget.time.monotonic", return_value=0),
            self.assertRaises(TimeoutError),
        ):
            run_status_request(fetch)
        self.assertEqual(http_settings(10, 10), (10, 10))

    def test_badge_can_reject_cached_metadata_without_affecting_other_consumers(self):
        session = SimpleNamespace(
            api_url="https://offline.example.test", access_token="test"
        )
        valid = CloudAuthStatus(state=CloudSessionState.VALID, session=session)
        with (
            patch("ite.cloud.auth.get_cloud_auth_status", return_value=valid),
            patch(
                "ite.cloud.auth._load_cached_cloud_entitlements",
                return_value={"proAccess": True},
            ),
            patch(
                "ite.cloud.auth._get_json",
                side_effect=auth.CloudConnectionError("offline"),
            ),
        ):
            self.assertTrue(
                auth.get_cloud_entitlements_result(Config()).metadata_available
            )
            self.assertFalse(
                auth.get_cloud_entitlements_result(
                    Config(), allow_cached=False
                ).metadata_available
            )

    async def test_unknown_plan_probes_and_cached_plan_fails_promptly(self):
        app = ReupApp(Config())
        self.assertTrue(app._should_probe_cloud_network_recovery())
        app._account_plan_is_pro = True
        network = CloudEntitlementsResult(
            entitlements={},
            auth=CloudAuthStatus(state=CloudSessionState.NETWORK_ERROR),
            metadata_available=False,
        )
        with (
            patch(
                "ite.ui.reup._cloud.get_cloud_entitlements_result", return_value=network
            ),
            patch.object(app, "refresh_header"),
            patch.object(app, "post_notice"),
        ):
            await app._refresh_account_plan_badge()
        self.assertTrue(app._account_plan_unavailable)
        self.assertIn("Offline", app._plan_badge_renderable().plain)
        self.assertTrue(app._should_probe_cloud_network_recovery())

    async def test_stalled_transport_deadline_and_single_flight(self):
        app = ReupApp(Config())
        gate = threading.Event()
        started = threading.Event()
        network = CloudEntitlementsResult(
            entitlements={},
            auth=CloudAuthStatus(state=CloudSessionState.NETWORK_ERROR),
            metadata_available=False,
        )

        def stalled(*args, **kwargs):
            started.set()
            gate.wait(2)
            return network

        try:
            with (
                patch("ite.ui.reup._cloud.CLOUD_STATUS_TIMEOUT_SEC", 0.03),
                patch(
                    "ite.ui.reup._cloud.get_cloud_entitlements_result",
                    side_effect=stalled,
                ) as fetch,
                patch.object(app, "refresh_header"),
                patch.object(app, "post_notice"),
            ):
                await app._refresh_account_plan_badge()
                self.assertTrue(started.is_set())
                self.assertTrue(app._account_plan_unavailable)
                self.assertIn("plan", app._cloud_status_tasks)
                await app._refresh_account_plan_badge()
                self.assertEqual(fetch.call_count, 1)
                pending = app._cloud_status_tasks["plan"]
                gate.set()
                await pending
                await asyncio.sleep(0)
                self.assertNotIn("plan", app._cloud_status_tasks)
                self.assertTrue(app._account_plan_unavailable)
        finally:
            gate.set()

    async def test_stalled_probe_cannot_start_another_probe(self):
        app = ReupApp(Config())
        gate = threading.Event()

        def stalled(*args, **kwargs):
            gate.wait(2)
            return False

        try:
            with (
                patch("ite.ui.reup._cloud.CLOUD_STATUS_TIMEOUT_SEC", 0.03),
                patch("ite.ui.reup._cloud.is_cloud_api_reachable", side_effect=stalled),
                patch.object(app, "refresh_header"),
                patch.object(app, "post_notice"),
            ):
                await app._probe_cloud_network_recovery()
                self.assertTrue(app._account_plan_unavailable)
                self.assertFalse(app._should_probe_cloud_network_recovery())
                pending = app._cloud_status_tasks["probe"]
                gate.set()
                await pending
                await asyncio.sleep(0)
                self.assertTrue(app._should_probe_cloud_network_recovery())
        finally:
            gate.set()

    async def test_mounted_header_resolves_offline_and_recovers_to_pro(self):
        with TemporaryDirectory() as directory:
            app = ReupApp(Config(cwd=Path(directory)))
            network = CloudEntitlementsResult(
                entitlements={},
                auth=CloudAuthStatus(state=CloudSessionState.NETWORK_ERROR),
                metadata_available=False,
            )
            valid = CloudAuthStatus(
                state=CloudSessionState.VALID, session=SimpleNamespace()
            )
            online = CloudEntitlementsResult(
                entitlements={"proAccess": True}, auth=valid, metadata_available=True
            )

            async def bootstrap():
                app._cloud_bootstrap_busy = False
                app._cloud_auth_busy = False
                app._set_startup_state(False)
                app._set_loading_state("idle", busy=False)
                app.query_one("#prompt", TextArea).focus()

            with (
                patch("ite.ui.reup.settings.SettingsPanel.refresh_cloud_data"),
                patch.object(app, "_bootstrap_after_mount", bootstrap),
                patch.object(app, "_prefetch_cloud_caches") as prefetch,
                patch.object(app, "_apply_cloud_auth_status"),
                patch(
                    "ite.ui.reup._cloud.get_cloud_entitlements_result",
                    return_value=network,
                ) as fetch,
                patch("ite.ui.reup._cloud.get_cloud_auth_status", return_value=valid),
                patch("ite.ui.reup._cloud.is_cloud_api_reachable", return_value=False),
            ):
                async with app.run_test(size=(100, 30)) as pilot:
                    await pilot.pause()
                    await app._refresh_account_plan_badge()
                    await pilot.pause()
                    badge = app.query_one("#plan-badge", Static)
                    self.assertIn("Offline", str(badge.render()))
                    app.save_screenshot("cloud-offline.svg", path="/tmp")
                    await app._probe_cloud_network_recovery()
                    prefetch.assert_called_once()
                    fetch.return_value = online
                    await app._refresh_account_plan_badge()
                    await pilot.pause()
                    self.assertIn("Pro", str(badge.render()))
                    self.assertNotIn("Offline", str(badge.render()))
                    self.assertFalse(app._cloud_network_was_unreachable)
                    self.assertEqual(app._cloud_network_unreachable_probe_count, 0)
                    self.assertEqual(app._cloud_network_recovery_probe_interval(), 30.0)
