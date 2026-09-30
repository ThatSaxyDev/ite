from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, patch

from textual.app import App
from textual.widgets import Input, Select

from ite.agent.session import Session
from ite.config.config import DEFAULT_API_KEY, DEFAULT_BASE_URL, Config
from ite.config.loader import load_config, load_saved_custom_provider
from ite.context.manager import ContextManager
from ite.ui.reup import modals
from ite.ui.reup.app import ReupApp
from ite.ui.reup.modals import SETUP_MODEL_OTHER, SetupModal


class SetupContextWindowTests(unittest.IsolatedAsyncioTestCase):
    def _widgets(self, provider: str, context_window: str) -> dict:
        return {
            "#setup-provider": SimpleNamespace(value=provider, disabled=False),
            "#setup-base-url": SimpleNamespace(
                value="https://example.test/v1", disabled=False
            ),
            "#setup-api-key": SimpleNamespace(value="test-key", disabled=False),
            "#setup-model-select": SimpleNamespace(
                value=SETUP_MODEL_OTHER, disabled=False
            ),
            "#setup-model-input": SimpleNamespace(
                value="million-token-model", disabled=False
            ),
            "#setup-context-window": SimpleNamespace(
                value=context_window, disabled=False, focus=lambda: None
            ),
            **{
                selector: SimpleNamespace(disabled=False)
                for selector in (
                    "#continue",
                    "#cancel",
                    "#setup-toggle-api-key",
                    "#setup-load-models",
                )
            },
        }

    async def test_submit_preserves_entered_limit_over_provider_detection(self) -> None:
        for provider in ("generic", "ollama"):
            with self.subTest(provider=provider):
                modal = SetupModal(Config())
                widgets = self._widgets(provider, "1000000")
                with (
                    patch.object(
                        modal,
                        "query_one",
                        side_effect=lambda selector, *_, widgets=widgets: widgets[
                            selector
                        ],
                    ),
                    patch.object(modal, "_set_error"),
                    patch.object(modal, "_set_status"),
                    patch.object(
                        modal,
                        "_validate_provider_connection",
                        new=AsyncMock(return_value=(None, 200000)),
                    ),
                    patch.object(modal, "dismiss") as dismiss,
                ):
                    await modal._submit_async()
                result = dismiss.call_args.args[0]
                self.assertEqual(result["context_window"], 1000000)
                self.assertEqual(result["context_window_source"], "user_configured")
                if provider == "ollama":
                    self.assertEqual(result["base_url"], DEFAULT_BASE_URL)
                    self.assertEqual(result["api_key"], DEFAULT_API_KEY)

    async def test_invalid_limit_is_rejected_before_connecting(self) -> None:
        for provider in ("generic", "ollama"):
            for value in ("", "0", "-1", "1.5", "1m", "NaN"):
                with self.subTest(provider=provider, value=value):
                    modal = SetupModal(Config())
                    widgets = self._widgets(provider, value)
                    with (
                        patch.object(
                            modal,
                            "query_one",
                            side_effect=lambda selector, *_, widgets=widgets: widgets[
                                selector
                            ],
                        ),
                        patch.object(modal, "_set_error") as error,
                        patch.object(
                            modal, "_validate_provider_connection", new=AsyncMock()
                        ) as connection,
                        patch.object(modal, "dismiss") as dismiss,
                    ):
                        await modal._submit_async()
                    connection.assert_not_awaited()
                    dismiss.assert_not_called()
                    self.assertIn("positive whole number", error.call_args.args[0])

    async def test_generic_requires_model_instead_of_using_current_model(self) -> None:
        modal = SetupModal(Config(model={"name": "stealth/space-bunny-alpha"}))
        widgets = self._widgets("generic", "1000000")
        widgets["#setup-model-input"].value = ""
        with (
            patch.object(
                modal,
                "query_one",
                side_effect=lambda selector, *_: widgets[selector],
            ),
            patch.object(modal, "_set_error") as error,
            patch.object(modal, "_validate_provider_connection", new=AsyncMock())
            as connection,
            patch.object(modal, "dismiss") as dismiss,
        ):
            await modal._submit_async()
        error.assert_called_once_with("Model name is required.")
        connection.assert_not_awaited()
        dismiss.assert_not_called()

    async def test_openrouter_retains_automatic_limit(self) -> None:
        modal = SetupModal(Config())
        modal._openrouter_models = ["million-token-model"]
        modal._openrouter_context_windows = {"million-token-model": 1048576}
        widgets = self._widgets("openrouter", "invalid hidden value")
        with (
            patch.object(
                modal,
                "query_one",
                side_effect=lambda selector, *_, widgets=widgets: widgets[selector],
            ),
            patch.object(modal, "_set_error"),
            patch.object(modal, "_set_status"),
            patch.object(
                modal,
                "_validate_provider_connection",
                new=AsyncMock(return_value=(None, None)),
            ),
            patch.object(modal, "dismiss") as dismiss,
        ):
            await modal._submit_async()
        self.assertEqual(dismiss.call_args.args[0]["context_window"], 1048576)
        self.assertEqual(
            dismiss.call_args.args[0]["context_window_source"], "openrouter_models_api"
        )

    async def test_setup_limit_reaches_saved_config_active_session_and_meter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = Config(
                cwd=root, api_key="test", base_url="https://example.test/v1"
            )
            app = ReupApp(config)
            session_config = Config(
                cwd=root,
                api_key="test",
                model={"name": "previous-model", "context_window": 200000},
            )
            context = ContextManager(session_config)
            with patch("ite.config.loader.get_data_dir", return_value=root / "data"):
                session = Session(session_config)
            session.context_manager = context
            session.client.close = AsyncMock()
            app.agent = SimpleNamespace(session=session)
            result = {
                "base_url": "https://example.test/v1",
                "api_key": "test",
                "model_name": "million-token-model",
                "context_window": 1000000,
                "context_window_source": "user_configured",
                "approval": config.approval.value,
            }
            with (
                patch("ite.config.loader.get_config_dir", return_value=root / "config"),
                patch.object(app, "refresh_header"),
                patch.object(app, "post_notice"),
            ):
                await app._apply_setup_result(result)
                saved = load_saved_custom_provider()["million-token-model"]
                restored = load_config(cwd=root)
            self.assertEqual(app.config.model.context_window, 1000000)
            self.assertEqual(session_config.model.context_window, 1000000)
            self.assertEqual(saved["context_window"], 1000000)
            self.assertEqual(saved["context_window_source"], "user_configured")
            self.assertEqual(restored.model.context_window, 1000000)
            self.assertEqual(restored.model.context_window_source, "user_configured")
            self.assertEqual(context.get_compaction_status()["trigger_at"], 850000)
            stats = session.get_stats()
            self.assertEqual(stats["context_window"], 1000000)
            self.assertAlmostEqual(
                stats["context_used_pct"],
                round(context.estimate_current_context_tokens() / 1000000 * 100, 1),
            )
            self.assertEqual(
                SetupModal(restored)._provider_context_window["generic"], "1000000"
            )
            self.assertEqual(
                SetupModal(restored)._provider_defaults("generic")[2],
                "million-token-model",
            )

    async def test_mounted_form_preserves_drafts_and_fits_small_terminal(self) -> None:
        class Host(App):
            CSS_PATH: ClassVar[list[Path]] = [
                Path(modals.__file__).parent / "styles" / name
                for name in ("modals.tcss", "modal_details.tcss")
            ]

        modal = SetupModal(Config(model={"name": "stealth/space-bunny-alpha"}))
        app = Host()
        with (
            patch.object(modal, "_load_openrouter_models", new=AsyncMock()),
            patch.object(modal, "_probe_ollama", new=AsyncMock(return_value=(None, None))),
        ):
            async with app.run_test(size=(80, 24)) as pilot:
                await app.push_screen(modal)
                await pilot.pause()
                field = modal.query_one("#setup-context-window", Input)
                provider = modal.query_one("#setup-provider", Select)
                self.assertTrue(field.display)
                self.assertEqual(field.value, "")
                modal.query_one("#setup-model-select", Select).value = SETUP_MODEL_OTHER
                await pilot.pause()
                field.value = "131072"
                await pilot.pause()
                provider.value = "generic"
                await pilot.pause()
                self.assertTrue(field.display)
                self.assertEqual(field.value, "")
                model_input = modal.query_one("#setup-model-input", Input)
                self.assertEqual(model_input.value, "")
                model_input.value = "my-provider-model"
                field.value = "1000000"
                provider.value = "openrouter"
                await pilot.pause()
                self.assertFalse(field.display)
                provider.value = "generic"
                await pilot.pause()
                self.assertTrue(field.display)
                self.assertEqual(field.value, "1000000")
                self.assertEqual(model_input.value, "my-provider-model")
                provider.value = "ollama"
                await pilot.pause()
                modal.query_one("#setup-model-select", Select).value = SETUP_MODEL_OTHER
                await pilot.pause()
                self.assertEqual(field.value, "131072")
                field.focus()
                await pilot.pause(0.3)
                container = modal.query_one(".setup-modal")
                self.assertLessEqual(container.region.height, 24)
                self.assertGreaterEqual(field.region.y, 0)
                self.assertLessEqual(field.region.bottom, 24)

    async def test_listed_ollama_saves_discovered_context_over_stale_input(self) -> None:
        modal = SetupModal(Config())
        model = modals.RECOMMENDED_OLLAMA_MODELS[0]
        widgets = self._widgets("ollama", "4096")
        widgets["#setup-model-select"].value = model
        with (
            patch.object(modal, "query_one", side_effect=lambda selector, *_: widgets[selector]),
            patch.object(modal, "_set_error"),
            patch.object(modal, "_set_status"),
            patch.object(modal, "_probe_ollama", new=AsyncMock(return_value=(None, 262144))) as probe,
            patch.object(modal, "dismiss") as dismiss,
        ):
            await modal._submit_async()
        result = dismiss.call_args.args[0]
        self.assertEqual(result["context_window"], 262144)
        self.assertEqual(result["context_window_source"], "ollama_model_api")
        self.assertEqual(result["model_name"], model)
        probe.assert_awaited_once()

    async def test_mounted_list_detection_other_and_failed_lookup(self) -> None:
        modal = SetupModal(Config())
        app = App()
        first, second = modals.RECOMMENDED_OLLAMA_MODELS[:2]
        async def probe(*, base_url: str, model_name: str):
            return None, 262144 if model_name == first else None
        with patch.object(modal, "_probe_ollama", side_effect=probe):
            async with app.run_test(size=(100, 50)) as pilot:
                await app.push_screen(modal)
                await pilot.pause()
                field = modal.query_one("#setup-context-window", Input)
                select = modal.query_one("#setup-model-select", Select)
                self.assertEqual(field.value, "262144")
                self.assertTrue(field.disabled)
                select.value = SETUP_MODEL_OTHER
                await pilot.pause()
                self.assertFalse(field.disabled)
                self.assertEqual(field.value, "")
                field.value = "65536"
                await pilot.pause()
                select.value = second
                await pilot.pause()
                self.assertFalse(field.disabled)
                self.assertEqual(field.value, "")
                field.value = "131072"
                await pilot.pause()
                select.value = first
                await pilot.pause()
                self.assertTrue(field.disabled)
                self.assertEqual(field.value, "262144")
                select.value = second
                await pilot.pause()
                self.assertFalse(field.disabled)
                self.assertEqual(field.value, "131072")
                select.value = SETUP_MODEL_OTHER
                await pilot.pause()
                self.assertFalse(field.disabled)
                self.assertEqual(field.value, "65536")

    def test_old_guessed_limit_is_not_presented_as_user_confirmed(self) -> None:
        config = Config(
            model={
                "context_window": 200000,
                "context_window_source": "provider_fixed_default",
            }
        )
        self.assertEqual(SetupModal(config)._provider_context_window["ollama"], "")
