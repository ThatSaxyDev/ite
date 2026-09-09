import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from ite.config.config import Config
from ite.config.config import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    FIXED_PROVIDER_CONTEXT_WINDOW,
    ModelConfig,
)
from ite.ui.reup.modals import (
    RECOMMENDED_OLLAMA_MODELS,
    SETUP_PROVIDER_OLLAMA,
    SETUP_MODEL_OTHER,
    SETUP_MODEL_SELECT,
    SetupModal,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, _url, headers=None, params=None):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def post(self, _url, json=None, headers=None):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SetupModalTests(unittest.IsolatedAsyncioTestCase):
    def test_provider_visibility_hides_base_url_for_ollama(self) -> None:
        modal = SetupModal(Config())
        provider_copy = SimpleNamespace(display=False, renderable="")
        base_url_label = SimpleNamespace(display=True)
        base_url_input = SimpleNamespace(display=True)
        base_url_help = SimpleNamespace(display=True)
        api_key_label = SimpleNamespace(display=True)
        api_key_row = SimpleNamespace(display=True)
        model_label = SimpleNamespace(display=True)
        provider_select = SimpleNamespace(value="ollama")
        model_select = SimpleNamespace(value="kimi-k2.5:cloud", set_options=lambda _opts: None)
        model_select_row = SimpleNamespace(display=True)
        model_input = SimpleNamespace(display=False, value="", focus=lambda: None)
        model_help = SimpleNamespace(display=False)
        load_models_button = SimpleNamespace(display=False)

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-provider-copy": provider_copy,
                "#setup-base-url-label": base_url_label,
                "#setup-base-url": base_url_input,
                "#setup-base-url-help": base_url_help,
                "#setup-api-key-label": api_key_label,
                "#setup-api-key-row": api_key_row,
                "#setup-model-label": model_label,
                "#setup-model-select": model_select,
                "#setup-model-select-row": model_select_row,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
                "#setup-load-models": load_models_button,
                }[selector],
        ):
            modal._apply_provider_visibility("ollama")

        self.assertFalse(base_url_label.display)
        self.assertFalse(base_url_input.display)
        self.assertTrue(base_url_help.display)

    def test_update_model_help_text_shows_resolved_context_window_for_openrouter(self) -> None:
        modal = SetupModal(Config())
        provider_select = SimpleNamespace(value="openrouter")
        model_select = SimpleNamespace(value="google/gemma-4-31b-it:free")
        model_input = SimpleNamespace(value="")
        model_help = SimpleNamespace(update=lambda value: setattr(model_help, "renderable", value))
        model_help.renderable = ""
        modal._openrouter_context_windows = {"google/gemma-4-31b-it:free": 131072}

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-model-select": model_select,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
            }[selector],
        ):
            modal._update_model_help_text("openrouter")

        self.assertIn("Context window: 131K (resolved from OpenRouter)", model_help.renderable)

    def test_update_model_help_text_hides_context_window_for_ollama_model(self) -> None:
        modal = SetupModal(
            Config(
                base_url=DEFAULT_BASE_URL,
                api_key=DEFAULT_API_KEY,
                model=ModelConfig(
                    name="gemma4:e4b",
                    context_window=131072,
                    context_window_source="saved_config",
                ),
            )
        )
        provider_select = SimpleNamespace(value="ollama")
        model_select = SimpleNamespace(value="gemma4:e4b")
        model_input = SimpleNamespace(value="")
        model_help = SimpleNamespace(update=lambda value: setattr(model_help, "renderable", value))
        model_help.renderable = ""

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-model-select": model_select,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
            }[selector],
        ):
            modal._update_model_help_text("ollama")

        self.assertEqual(
            model_help.renderable,
            "Enter the exact model name as Ollama expects it.",
        )

    def test_update_model_help_text_hides_context_window_for_ollama_cloud_route(self) -> None:
        modal = SetupModal(Config())
        provider_select = SimpleNamespace(value="ollama")
        model_select = SimpleNamespace(value="minimax-m2.5:cloud")
        model_input = SimpleNamespace(value="")
        model_help = SimpleNamespace(update=lambda value: setattr(model_help, "renderable", value))
        model_help.renderable = ""

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-model-select": model_select,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
            }[selector],
        ):
            modal._update_model_help_text("ollama")

        self.assertEqual(
            model_help.renderable,
            "Enter the exact model name as Ollama expects it.",
        )

    def test_update_model_help_text_hides_context_window_for_generic_provider(self) -> None:
        modal = SetupModal(Config())
        provider_select = SimpleNamespace(value="generic")
        model_select = SimpleNamespace(value="")
        model_input = SimpleNamespace(value="custom-model")
        model_help = SimpleNamespace(update=lambda value: setattr(model_help, "renderable", value))
        model_help.renderable = ""

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-model-select": model_select,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
            }[selector],
        ):
            modal._update_model_help_text("generic")

        self.assertEqual(
            model_help.renderable,
            "Enter the exact model name your provider expects.",
        )

    def test_update_model_help_text_shows_unknown_until_openrouter_models_loaded(self) -> None:
        modal = SetupModal(Config())
        provider_select = SimpleNamespace(value="openrouter")
        model_select = SimpleNamespace(value=SETUP_MODEL_SELECT)
        model_input = SimpleNamespace(value="")
        model_help = SimpleNamespace(update=lambda value: setattr(model_help, "renderable", value))
        model_help.renderable = ""

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-model-select": model_select,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
            }[selector],
        ):
            modal._update_model_help_text("openrouter")

        self.assertIn(
            "Context window: unknown until models are loaded from the provider.",
            model_help.renderable,
        )

    def test_provider_visibility_hides_base_url_for_openrouter(self) -> None:
        modal = SetupModal(Config())
        provider_copy = SimpleNamespace(display=False, renderable="")
        base_url_label = SimpleNamespace(display=True)
        base_url_input = SimpleNamespace(display=True)
        base_url_help = SimpleNamespace(display=True)
        api_key_label = SimpleNamespace(display=False)
        api_key_row = SimpleNamespace(display=False)
        model_label = SimpleNamespace(display=True)
        provider_select = SimpleNamespace(value="openrouter")
        model_select = SimpleNamespace(value="openai/gpt-4.1-mini", set_options=lambda _opts: None)
        model_select_row = SimpleNamespace(display=True)
        model_input = SimpleNamespace(display=False, value="", focus=lambda: None)
        model_help = SimpleNamespace(display=False)
        load_models_button = SimpleNamespace(display=False)

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-provider-copy": provider_copy,
                "#setup-base-url-label": base_url_label,
                "#setup-base-url": base_url_input,
                "#setup-base-url-help": base_url_help,
                "#setup-api-key-label": api_key_label,
                "#setup-api-key-row": api_key_row,
                "#setup-model-label": model_label,
                "#setup-model-select": model_select,
                "#setup-model-select-row": model_select_row,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
                "#setup-load-models": load_models_button,
            }[selector],
        ):
            modal._apply_provider_visibility("openrouter")

        self.assertFalse(base_url_label.display)
        self.assertFalse(base_url_input.display)
        self.assertTrue(base_url_help.display)
        self.assertFalse(model_label.display)
        self.assertFalse(model_select_row.display)
        self.assertFalse(model_input.display)

    def test_provider_visibility_shows_base_url_for_generic_provider(self) -> None:
        modal = SetupModal(Config())
        provider_copy = SimpleNamespace(display=False, renderable="")
        base_url_label = SimpleNamespace(display=False)
        base_url_input = SimpleNamespace(display=False)
        base_url_help = SimpleNamespace(display=True)
        api_key_label = SimpleNamespace(display=False)
        api_key_row = SimpleNamespace(display=False)
        model_label = SimpleNamespace(display=False)
        provider_select = SimpleNamespace(value="generic")
        model_select = SimpleNamespace(value=SimpleNamespace(), set_options=lambda _opts: None)
        model_select_row = SimpleNamespace(display=False)
        model_input = SimpleNamespace(display=False, value="")
        model_help = SimpleNamespace(display=False)
        load_models_button = SimpleNamespace(display=False)

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-provider-copy": provider_copy,
                "#setup-base-url-label": base_url_label,
                "#setup-base-url": base_url_input,
                "#setup-base-url-help": base_url_help,
                "#setup-api-key-label": api_key_label,
                "#setup-api-key-row": api_key_row,
                "#setup-model-label": model_label,
                "#setup-model-select": model_select,
                "#setup-model-select-row": model_select_row,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
                "#setup-load-models": load_models_button,
            }[selector],
        ):
            modal._apply_provider_visibility("generic")

        self.assertTrue(base_url_label.display)
        self.assertTrue(base_url_input.display)

    def test_provider_visibility_hides_api_key_for_ollama(self) -> None:
        modal = SetupModal(Config())
        provider_copy = SimpleNamespace(display=False, renderable="")
        api_key_label = SimpleNamespace(display=True)
        api_key_row = SimpleNamespace(display=True)
        base_url_label = SimpleNamespace(display=True)
        base_url_input = SimpleNamespace(display=True)
        base_url_help = SimpleNamespace(display=True)
        model_label = SimpleNamespace(display=True)
        provider_select = SimpleNamespace(value="ollama")
        model_select = SimpleNamespace(value="kimi-k2.5:cloud", set_options=lambda _opts: None)
        model_select_row = SimpleNamespace(display=True)
        model_input = SimpleNamespace(display=False, value="")
        model_help = SimpleNamespace(display=False)
        load_models_button = SimpleNamespace(display=False)

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-provider-copy": provider_copy,
                "#setup-base-url-label": base_url_label,
                "#setup-base-url": base_url_input,
                "#setup-base-url-help": base_url_help,
                "#setup-api-key-label": api_key_label,
                "#setup-api-key-row": api_key_row,
                "#setup-model-label": model_label,
                "#setup-model-select": model_select,
                "#setup-model-select-row": model_select_row,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
                "#setup-load-models": load_models_button,
            }[selector],
        ):
            modal._apply_provider_visibility("ollama")

        self.assertFalse(api_key_label.display)
        self.assertFalse(api_key_row.display)

    def test_ollama_custom_model_is_stored_as_manual_and_defaults_select_to_recommended(self) -> None:
        modal = SetupModal(
            Config(
                base_url=DEFAULT_BASE_URL,
                api_key=DEFAULT_API_KEY,
                model=ModelConfig(name="custom-model"),
            )
        )

        self.assertEqual(
            modal._provider_selected_model[SETUP_PROVIDER_OLLAMA],
            RECOMMENDED_OLLAMA_MODELS[0],
        )
        self.assertEqual(
            modal._provider_manual_model[SETUP_PROVIDER_OLLAMA],
            "custom-model",
        )

    def test_provider_visibility_defaults_ollama_to_recommended_model(self) -> None:
        modal = SetupModal(Config(model_name="custom-model"))
        select_options: list[tuple[str, str]] = []

        def _set_options(options):
            select_options[:] = list(options)

        provider_copy = SimpleNamespace(display=False, renderable="")
        base_url_label = SimpleNamespace(display=True)
        base_url_input = SimpleNamespace(display=True)
        base_url_help = SimpleNamespace(display=True)
        api_key_label = SimpleNamespace(display=True)
        api_key_row = SimpleNamespace(display=True)
        model_label = SimpleNamespace(display=True)
        provider_select = SimpleNamespace(value="ollama")
        model_select = SimpleNamespace(value="custom-model", set_options=_set_options)
        model_select_row = SimpleNamespace(display=True)
        model_input = SimpleNamespace(display=False, value="custom-model", focus=lambda: None)
        model_help = SimpleNamespace(display=False)
        load_models_button = SimpleNamespace(display=False)

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-provider-copy": provider_copy,
                "#setup-base-url-label": base_url_label,
                "#setup-base-url": base_url_input,
                "#setup-base-url-help": base_url_help,
                "#setup-api-key-label": api_key_label,
                "#setup-api-key-row": api_key_row,
                "#setup-model-label": model_label,
                "#setup-model-select": model_select,
                "#setup-model-select-row": model_select_row,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
                "#setup-load-models": load_models_button,
            }[selector],
        ):
            modal._apply_provider_visibility("ollama")

        self.assertEqual(model_select.value, RECOMMENDED_OLLAMA_MODELS[0])
        self.assertFalse(model_input.display)
        self.assertIn(("Other", SETUP_MODEL_OTHER), select_options)

    def test_provider_visibility_shows_api_key_for_hosted_provider(self) -> None:
        modal = SetupModal(Config())
        provider_copy = SimpleNamespace(display=False, renderable="")
        api_key_label = SimpleNamespace(display=False)
        api_key_row = SimpleNamespace(display=False)
        base_url_label = SimpleNamespace(display=False)
        base_url_input = SimpleNamespace(display=False)
        base_url_help = SimpleNamespace(display=True)
        model_label = SimpleNamespace(display=True)
        provider_select = SimpleNamespace(value="openrouter")
        model_select = SimpleNamespace(value="openai/gpt-4.1-mini", set_options=lambda _opts: None)
        model_select_row = SimpleNamespace(display=True)
        model_input = SimpleNamespace(display=False, value="")
        model_help = SimpleNamespace(display=False)
        load_models_button = SimpleNamespace(display=False)

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-provider-copy": provider_copy,
                "#setup-base-url-label": base_url_label,
                "#setup-base-url": base_url_input,
                "#setup-base-url-help": base_url_help,
                "#setup-api-key-label": api_key_label,
                "#setup-api-key-row": api_key_row,
                "#setup-model-label": model_label,
                "#setup-model-select": model_select,
                "#setup-model-select-row": model_select_row,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
                "#setup-load-models": load_models_button,
            }[selector],
        ):
            modal._apply_provider_visibility("openrouter")

        self.assertTrue(api_key_label.display)
        self.assertTrue(api_key_row.display)

    def test_openrouter_shows_model_picker_after_models_are_loaded(self) -> None:
        modal = SetupModal(Config())
        modal._openrouter_models = [
            "arcee-ai/trinity-large-preview:free",
            "google/gemma-4-31b-it:free",
        ]
        select_options: list[tuple[str, str]] = []

        def _set_options(options):
            select_options[:] = list(options)

        provider_copy = SimpleNamespace(display=False, renderable="")
        base_url_label = SimpleNamespace(display=True)
        base_url_input = SimpleNamespace(display=True)
        base_url_help = SimpleNamespace(display=True)
        api_key_label = SimpleNamespace(display=False)
        api_key_row = SimpleNamespace(display=False)
        model_label = SimpleNamespace(display=False)
        provider_select = SimpleNamespace(value="openrouter")
        model_select = SimpleNamespace(value="", set_options=_set_options)
        model_select_row = SimpleNamespace(display=False)
        model_input = SimpleNamespace(display=False, value="", focus=lambda: None)
        model_help = SimpleNamespace(display=False)
        load_models_button = SimpleNamespace(display=False)

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-provider-copy": provider_copy,
                "#setup-base-url-label": base_url_label,
                "#setup-base-url": base_url_input,
                "#setup-base-url-help": base_url_help,
                "#setup-api-key-label": api_key_label,
                "#setup-api-key-row": api_key_row,
                "#setup-model-label": model_label,
                "#setup-model-select": model_select,
                "#setup-model-select-row": model_select_row,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
                "#setup-load-models": load_models_button,
            }[selector],
        ):
            modal._apply_provider_visibility("openrouter")

        self.assertTrue(model_label.display)
        self.assertTrue(model_select_row.display)
        self.assertEqual(model_select.value, SETUP_MODEL_SELECT)
        self.assertFalse(model_input.display)
        self.assertIn(("Select a model", SETUP_MODEL_SELECT), select_options)
        self.assertIn(("Other", SETUP_MODEL_OTHER), select_options)

    def test_model_input_only_shows_after_explicit_other_selection(self) -> None:
        modal = SetupModal(Config())
        provider_select = SimpleNamespace(value="ollama")
        model_input = SimpleNamespace(display=False, value="", focus=lambda: None)
        model_help = SimpleNamespace(display=False)

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-model-input": model_input,
                "#setup-model-help": model_help,
            }[selector],
        ):
            modal._apply_model_input_visibility(RECOMMENDED_OLLAMA_MODELS[0])
            self.assertFalse(model_input.display)
            self.assertEqual(model_input.value, "")
            self.assertTrue(model_help.display)
            modal._apply_model_input_visibility(SETUP_MODEL_OTHER)

        self.assertTrue(model_input.display)
        self.assertTrue(model_help.display)

    def test_set_model_options_preserves_saved_ollama_selection(self) -> None:
        modal = SetupModal(Config())
        modal._active_provider = "ollama"
        modal._provider_selected_model["ollama"] = "glm-5:cloud"
        modal._provider_manual_model["ollama"] = ""
        model_select = SimpleNamespace(value="", set_options=lambda _opts: None)
        model_input = SimpleNamespace(value="", display=False)
        provider_select = SimpleNamespace(value="ollama")

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#setup-provider": provider_select,
                "#setup-model-select": model_select,
                "#setup-model-input": model_input,
            }[selector],
        ):
            modal._set_model_options(list(RECOMMENDED_OLLAMA_MODELS), preserve_current=True)

        self.assertEqual(model_select.value, "glm-5:cloud")

    async def test_fetch_openrouter_models_returns_only_free_tool_capable_ids(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [
                    _FakeResponse(200, {"data": {"label": "my-key"}}),
                    _FakeResponse(
                        200,
                        {
                            "data": [
                                {
                                    "id": "google/gemma-4-31b-it:free",
                                    "context_length": 131072,
                                },
                                {
                                    "id": "arcee-ai/trinity-large-preview:free",
                                    "context_length": 65536,
                                },
                                {"id": "anthropic/claude-3.7-sonnet"},
                            ]
                        },
                    )
                ]
            ),
        ):
            models, error = await modal._fetch_openrouter_models(api_key="key")

        self.assertIsNone(error)
        self.assertEqual(
            models,
            [
                {
                    "model_name": "arcee-ai/trinity-large-preview:free",
                    "context_window": 65536,
                },
                {
                    "model_name": "google/gemma-4-31b-it:free",
                    "context_window": 131072,
                },
            ],
        )

    async def test_fetch_openrouter_models_requires_tools_and_prioritizes_ox_alpha(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [
                    _FakeResponse(200, {"data": {"label": "my-key"}}),
                    _FakeResponse(
                        200,
                        {
                            "data": [
                                {
                                    "id": "stealth/ox-alpha",
                                    "context_length": 1048576,
                                    "pricing": {"prompt": "0", "completion": "0"},
                                    "supported_parameters": ["tools", "tool_choice"],
                                },
                                {
                                    "id": "google/gemma-4-31b-it",
                                    "context_length": 131072,
                                    "pricing": {"prompt": "0", "completion": "0"},
                                    "supported_parameters": ["temperature"],
                                },
                                {
                                    "id": "arcee-ai/trinity-large-preview:free",
                                    "context_length": 65536,
                                    "supported_parameters": ["tools"],
                                },
                            ]
                        },
                    ),
                ]
            ),
        ):
            models, error = await modal._fetch_openrouter_models(api_key="key")

        self.assertIsNone(error)
        self.assertEqual(
            models,
            [
                {"model_name": "stealth/ox-alpha", "context_window": 1048576},
                {
                    "model_name": "arcee-ai/trinity-large-preview:free",
                    "context_window": 65536,
                },
            ],
        )

    async def test_fetch_openrouter_models_rejects_invalid_key_before_loading_models(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient([_FakeResponse(401)]),
        ):
            models, error = await modal._fetch_openrouter_models(api_key="bad-key")

        self.assertEqual(models, [])
        self.assertIn("rejected this API key", error or "")

    async def test_submit_async_forces_canonical_ollama_credentials(self) -> None:
        modal = SetupModal(Config())
        provider_select = SimpleNamespace(value="ollama", disabled=False)
        # Simulate stale hidden values left over from a previous OpenRouter setup.
        base_url_input = SimpleNamespace(value="https://openrouter.ai/api/v1", disabled=False)
        api_key_input = SimpleNamespace(value="stale-openrouter-key", disabled=False)
        model_select = SimpleNamespace(value=SETUP_MODEL_OTHER, disabled=False)
        model_input = SimpleNamespace(value="gemma4:e4b", disabled=False)
        continue_button = SimpleNamespace(disabled=False)
        cancel_button = SimpleNamespace(disabled=False)
        toggle_button = SimpleNamespace(disabled=False)
        load_button = SimpleNamespace(disabled=False)
        status = SimpleNamespace(renderable="", update=lambda value: setattr(status, "renderable", value))
        error = SimpleNamespace(renderable="", update=lambda value: setattr(error, "renderable", value))

        with (
            patch.object(
                modal,
                "query_one",
                side_effect=lambda selector, *_args: {
                    "#setup-provider": provider_select,
                    "#setup-base-url": base_url_input,
                    "#setup-api-key": api_key_input,
                    "#setup-model-select": model_select,
                    "#setup-model-input": model_input,
                    "#continue": continue_button,
                    "#cancel": cancel_button,
                    "#setup-toggle-api-key": toggle_button,
                    "#setup-load-models": load_button,
                    "#setup-status": status,
                    "#setup-error": error,
                }[selector],
            ),
            patch.object(
                modal,
                "_validate_provider_connection",
                return_value=(None, FIXED_PROVIDER_CONTEXT_WINDOW),
            ) as validate_connection,
            patch.object(modal, "dismiss") as dismiss,
        ):
            await modal._submit_async()

        validate_connection.assert_awaited_once_with(
            provider="ollama",
            base_url=DEFAULT_BASE_URL,
            api_key=DEFAULT_API_KEY,
            model_name="gemma4:e4b",
        )
        dismiss.assert_called_once()

    async def test_probe_ollama_skips_running_service_check(self) -> None:
        modal = SetupModal(Config())

        message, context_window = await modal._probe_ollama(
            base_url="http://localhost:11434/v1",
            model_name="qwen2.5-coder:7b",
        )

        self.assertIsNone(message)
        self.assertEqual(context_window, FIXED_PROVIDER_CONTEXT_WINDOW)

    async def test_probe_ollama_skips_local_tag_check(self) -> None:
        modal = SetupModal(Config())

        message, context_window = await modal._probe_ollama(
            base_url="http://localhost:11434/v1",
            model_name="qwen2.5-coder:7b",
        )

        self.assertIsNone(message)
        self.assertEqual(context_window, FIXED_PROVIDER_CONTEXT_WINDOW)

    async def test_probe_ollama_allows_cloud_model_without_local_tag(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [_FakeResponse(200, {"models": [{"name": "llama3.2:3b"}]})]
            ),
        ):
            message, context_window = await modal._probe_ollama(
                base_url="http://localhost:11434/v1",
                model_name="glm-5.1:cloud",
            )

        self.assertIsNone(message)
        self.assertEqual(context_window, FIXED_PROVIDER_CONTEXT_WINDOW)

    async def test_probe_ollama_returns_fixed_context_window_for_local_model(self) -> None:
        modal = SetupModal(Config())

        message, context_window = await modal._probe_ollama(
            base_url="http://localhost:11434/v1",
            model_name="gemma4:e4b",
        )

        self.assertIsNone(message)
        self.assertEqual(context_window, FIXED_PROVIDER_CONTEXT_WINDOW)

    async def test_probe_openai_compatible_rejects_invalid_key(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient([_FakeResponse(401)]),
        ):
            message, context_window = await modal._probe_openai_compatible(
                base_url="https://openrouter.ai/api/v1",
                api_key="bad-key",
                model_name="openai/gpt-4.1-mini",
            )

        self.assertIn("rejected this API key", message or "")
        self.assertIsNone(context_window)

    async def test_probe_openai_compatible_requires_model_in_provider_list(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [_FakeResponse(200, {"data": [{"id": "openai/gpt-4.1-mini"}]})]
            ),
        ):
            message, context_window = await modal._probe_openai_compatible(
                base_url="https://openrouter.ai/api/v1",
                api_key="key",
                model_name="anthropic/claude-sonnet-4",
            )

        self.assertIn("not available on this provider", message or "")
        self.assertIsNone(context_window)

    def _openrouter_visibility_stubs(
        self,
        provider: str,
        *,
        signin: SimpleNamespace,
        or_separator: SimpleNamespace,
        auth_label: SimpleNamespace,
        auth_code: SimpleNamespace,
        connected_label: SimpleNamespace,
        actions: SimpleNamespace,
    ) -> dict[str, SimpleNamespace]:
        return {
            "#setup-provider": SimpleNamespace(value=provider),
            "#setup-base-url-label": SimpleNamespace(display=False),
            "#setup-base-url": SimpleNamespace(display=False),
            "#setup-base-url-help": SimpleNamespace(display=False),
            "#setup-api-key-label": SimpleNamespace(display=False),
            "#setup-api-key-row": SimpleNamespace(display=False),
            "#setup-model-label": SimpleNamespace(display=False),
            "#setup-model-select": SimpleNamespace(value="", set_options=lambda _opts: None),
            "#setup-model-select-row": SimpleNamespace(display=False),
            "#setup-model-input": SimpleNamespace(display=False, value=""),
            "#setup-model-help": SimpleNamespace(display=False),
            "#setup-load-models": SimpleNamespace(display=False),
            "#setup-openrouter-signin": signin,
            "#setup-openrouter-or": or_separator,
            "#openrouter-auth-code-label": auth_label,
            "#openrouter-auth-code": auth_code,
            "#openrouter-connected-label": connected_label,
            "#openrouter-actions": actions,
        }

    def test_apply_provider_visibility_shows_signin_for_openrouter(self) -> None:
        modal = SetupModal(Config())
        signin = SimpleNamespace(display=False)
        or_separator = SimpleNamespace(display=False)
        auth_label = SimpleNamespace(display=False)
        auth_code = SimpleNamespace(display=False)
        connected_label = SimpleNamespace(display=False)
        actions = SimpleNamespace(display=False)
        stubs = self._openrouter_visibility_stubs(
            "openrouter",
            signin=signin,
            or_separator=or_separator,
            auth_label=auth_label,
            auth_code=auth_code,
            connected_label=connected_label,
            actions=actions,
        )

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, _cls, *_a: stubs[selector],
        ):
            modal._apply_provider_visibility("openrouter")

        self.assertTrue(signin.display)
        self.assertTrue(or_separator.display)
        self.assertFalse(auth_label.display)
        self.assertFalse(auth_code.display)
        self.assertFalse(connected_label.display)
        self.assertFalse(actions.display)

    def test_apply_provider_visibility_hides_signin_for_ollama(self) -> None:
        modal = SetupModal(Config())
        signin = SimpleNamespace(display=True)
        or_separator = SimpleNamespace(display=True)
        auth_label = SimpleNamespace(display=True)
        auth_code = SimpleNamespace(display=True)
        connected_label = SimpleNamespace(display=True)
        actions = SimpleNamespace(display=True)
        stubs = self._openrouter_visibility_stubs(
            "ollama",
            signin=signin,
            or_separator=or_separator,
            auth_label=auth_label,
            auth_code=auth_code,
            connected_label=connected_label,
            actions=actions,
        )

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, _cls, *_a: stubs[selector],
        ):
            modal._apply_provider_visibility("ollama")

        self.assertFalse(signin.display)
        self.assertFalse(or_separator.display)
        self.assertFalse(auth_label.display)
        self.assertFalse(auth_code.display)
        self.assertFalse(connected_label.display)
        self.assertFalse(actions.display)

    def test_headless_flag_reveals_auth_code_input(self) -> None:
        modal = SetupModal(Config())
        modal._openrouter_headless = True
        signin = SimpleNamespace(display=False)
        or_separator = SimpleNamespace(display=False)
        auth_label = SimpleNamespace(display=False)
        auth_code = SimpleNamespace(display=False)
        connected_label = SimpleNamespace(display=False)
        actions = SimpleNamespace(display=False)
        stubs = self._openrouter_visibility_stubs(
            "openrouter",
            signin=signin,
            or_separator=or_separator,
            auth_label=auth_label,
            auth_code=auth_code,
            connected_label=connected_label,
            actions=actions,
        )

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, _cls, *_a: stubs[selector],
        ):
            modal._apply_provider_visibility("openrouter")

        self.assertTrue(signin.display)
        self.assertTrue(or_separator.display)
        self.assertTrue(auth_label.display)
        self.assertTrue(auth_code.display)
        self.assertFalse(connected_label.display)
        self.assertFalse(actions.display)

    async def test_pkce_signin_populates_api_key_and_saves_secret(self) -> None:
        modal = SetupModal(Config())
        modal._openrouter_signin_in_flight = False
        modal._validating = False

        api_key_input = SimpleNamespace(value="", password=True)
        status = SimpleNamespace(renderable="")
        error = SimpleNamespace(renderable="")

        def _set_status(_msg: str) -> None:
            pass

        def _set_error(_msg: str) -> None:
            pass

        def _set_validating(_busy: bool) -> None:
            pass

        async def _fake_flow(**_kwargs):
            return "sk-or-v1-from-pkce"

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, *_a: {
                "#setup-provider": SimpleNamespace(value="openrouter"),
                "#setup-api-key": api_key_input,
                "#setup-status": status,
                "#setup-error": error,
                "#setup-model-select": SimpleNamespace(value=SETUP_MODEL_SELECT),
                "#setup-model-input": SimpleNamespace(value=""),
            }[selector],
        ), patch.object(
            modal, "_set_status", side_effect=_set_status
        ), patch.object(
            modal, "_set_error", side_effect=_set_error
        ), patch.object(
            modal, "_set_validating", side_effect=_set_validating
        ), patch.object(
            modal, "_load_openrouter_models_for_setup",
            return_value=self.async_value(True),
        ), patch(
            "ite.ui.reup.modals.save_openrouter_oauth_secret"
        ) as save_secret, patch(
            "ite.auth.openrouter_pkce.run_localhost_pkce_flow_async",
            side_effect=_fake_flow,
        ):
            await modal._openrouter_pkce_signin(headless=False)

        self.assertEqual(api_key_input.value, "sk-or-v1-from-pkce")
        self.assertFalse(api_key_input.password)
        save_secret.assert_called_once()

    def test_apply_provider_visibility_hides_help_once_connected(self) -> None:
        """The "Enter your OpenRouter API key…" help must not reappear.

        Regression: `_apply_provider_visibility` used to force
        ``#setup-base-url-help`` always-visible, and it re-runs after the
        model list loads — so the help text leaked back in after the key was
        verified, undoing the connected-state cleanup.
        """
        from textual.widgets import Button, Input, Static

        modal = SetupModal(Config())
        modal._openrouter_signed_in = True

        base_url_help = SimpleNamespace(display=True)
        provider_copy = SimpleNamespace(display=True)
        api_key_label = SimpleNamespace(display=True)
        api_key_row = SimpleNamespace(display=True)
        signin = SimpleNamespace(display=True)
        connected_label = SimpleNamespace(
            display=False, update=lambda _x: None
        )
        actions = SimpleNamespace(display=False)

        class _FakeSelect:
            def __init__(self) -> None:
                self.value = SETUP_MODEL_SELECT
                self.options: list | None = None

            def set_options(self, options) -> None:
                self.options = options

        model_select = _FakeSelect()
        model_input = SimpleNamespace(display=False, value="")
        model_help = SimpleNamespace(display=True)

        stubs = {
            "#setup-provider": SimpleNamespace(value="openrouter"),
            "#setup-model-select": model_select,
            "#setup-model-input": model_input,
            "#setup-model-help": model_help,
            "#setup-base-url-label": SimpleNamespace(display=False),
            "#setup-base-url": SimpleNamespace(display=False),
            "#setup-base-url-help": base_url_help,
            "#setup-provider-copy": provider_copy,
            "#setup-api-key-label": api_key_label,
            "#setup-api-key-row": api_key_row,
            "#setup-model-label": SimpleNamespace(display=False),
            "#setup-model-select-row": SimpleNamespace(display=False),
            "#setup-load-models": SimpleNamespace(display=False),
            "#setup-openrouter-signin": signin,
            "#openrouter-connected-label": connected_label,
            "#openrouter-actions": actions,
        }

        with patch.object(
            modal,
            "query_one",
            side_effect=lambda selector, _cls, *_a: stubs[selector],
        ):
            # Simulate the post-model-load re-apply that used to leak the help.
            modal._apply_provider_visibility("openrouter")

        # Every pre-sign-in text/control stays hidden...
        self.assertFalse(base_url_help.display)
        self.assertFalse(api_key_label.display)
        self.assertFalse(api_key_row.display)
        self.assertFalse(signin.display)
        # ...while the connected status and key-management row stay visible.
        self.assertTrue(connected_label.display)
        self.assertTrue(actions.display)

    def test_existing_key_is_marked_connected(self) -> None:
        """A returning user with an already-saved key sees 'Connected to OpenRouter'.

        Regression: `_openrouter_signed_in` used to only flip on after a fresh
        in-session OAuth round-trip, so a returning pasted-key user never saw
        the connected status. ``on_mount`` calls ``_openrouter_set_connected``
        for that scenario.
        """
        modal = SetupModal(Config())
        modal._openrouter_signed_in = False

        connected_label = SimpleNamespace(
            display=False, update=lambda _x: None
        )
        actions = SimpleNamespace(display=False)
        provider_copy = SimpleNamespace(display=True)
        base_url_help = SimpleNamespace(display=True)
        api_key_label = SimpleNamespace(display=True)
        api_key_row = SimpleNamespace(display=True)
        signin = SimpleNamespace(display=True)
        auth_label = SimpleNamespace(display=True)
        auth_code = SimpleNamespace(display=True)

        stubs = {
            "#openrouter-connected-label": connected_label,
            "#openrouter-actions": actions,
            "#setup-provider-copy": provider_copy,
            "#setup-base-url-help": base_url_help,
            "#setup-api-key-label": api_key_label,
            "#setup-api-key-row": api_key_row,
            "#setup-openrouter-signin": signin,
            "#openrouter-auth-code-label": auth_label,
            "#openrouter-auth-code": auth_code,
        }

        def fake_query(selector, *_a):
            return stubs[selector]

        with patch.object(modal, "query_one", side_effect=fake_query):
            modal._openrouter_set_connected("sk-or-v1-pasted-before")

        # The connected status and key-management buttons are shown...
        self.assertTrue(modal._openrouter_signed_in)
        self.assertTrue(connected_label.display)
        self.assertTrue(actions.display)
        # ...and every other pre-sign-in text/control is hidden.
        self.assertFalse(provider_copy.display)
        self.assertFalse(base_url_help.display)
        self.assertFalse(api_key_label.display)
        self.assertFalse(api_key_row.display)
        self.assertFalse(signin.display)

    def async_value(self, value):
        async def _coro():
            return value

        return _coro()


if __name__ == "__main__":
    unittest.main()
