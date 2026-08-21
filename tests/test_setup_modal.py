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
    OPENROUTER_DEBUG_API_KEY,
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

        self.assertIn("Context window: 128K (resolved from OpenRouter)", model_help.renderable)

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

    async def test_load_openrouter_models_for_setup_resolves_debug_api_key_alias(self) -> None:
        modal = SetupModal(Config())
        provider_select = SimpleNamespace(value="openrouter")
        api_key_input = SimpleNamespace(value="slethware")
        model_select = SimpleNamespace(value="", set_options=lambda _opts: None)
        model_input = SimpleNamespace(value="", display=False, focus=lambda: None)
        model_help = SimpleNamespace(display=False, update=lambda _value: None)
        continue_button = SimpleNamespace(disabled=False)
        cancel_button = SimpleNamespace(disabled=False)
        base_url_input = SimpleNamespace(disabled=False)
        toggle_button = SimpleNamespace(disabled=False)
        load_button = SimpleNamespace(disabled=False)
        provider_widget = SimpleNamespace(disabled=False)
        status = SimpleNamespace(update=lambda _value: None)
        error = SimpleNamespace(update=lambda _value: None)
        model_label = SimpleNamespace(display=False)
        model_select_row = SimpleNamespace(display=False)
        api_key_label = SimpleNamespace(display=False)
        api_key_row = SimpleNamespace(display=False)
        base_url_label = SimpleNamespace(display=False)
        base_url_help = SimpleNamespace(display=True)

        with (
            patch.object(
                modal,
                "query_one",
                side_effect=lambda selector, *_args: {
                    "#setup-provider": provider_select,
                    "#setup-api-key": api_key_input,
                    "#setup-model-select": model_select,
                    "#setup-model-input": model_input,
                    "#setup-model-help": model_help,
                    "#continue": continue_button,
                    "#cancel": cancel_button,
                    "#setup-base-url": base_url_input,
                    "#setup-toggle-api-key": toggle_button,
                    "#setup-load-models": load_button,
                    "#setup-status": status,
                    "#setup-error": error,
                    "#setup-model-label": model_label,
                    "#setup-model-select-row": model_select_row,
                    "#setup-api-key-label": api_key_label,
                    "#setup-api-key-row": api_key_row,
                    "#setup-base-url-label": base_url_label,
                    "#setup-base-url-help": base_url_help,
                }[selector],
            ),
            patch.object(
                modal,
                "_fetch_openrouter_models",
                return_value=(
                    [{"model_name": "google/gemma-4-31b-it:free", "context_window": 131072}],
                    None,
                ),
            ) as fetch_models,
        ):
            loaded = await modal._load_openrouter_models_for_setup()

        self.assertTrue(loaded)
        fetch_models.assert_awaited_once_with(api_key=OPENROUTER_DEBUG_API_KEY)

    async def test_submit_async_resolves_openrouter_debug_api_key_alias(self) -> None:
        modal = SetupModal(Config())
        modal._openrouter_models = ["google/gemma-4-31b-it:free"]
        modal._openrouter_context_windows = {"google/gemma-4-31b-it:free": 131072}
        provider_select = SimpleNamespace(value="openrouter", disabled=False)
        base_url_input = SimpleNamespace(value="", disabled=False)
        api_key_input = SimpleNamespace(value="slethware", disabled=False)
        model_select = SimpleNamespace(value="google/gemma-4-31b-it:free", disabled=False)
        model_input = SimpleNamespace(value="", disabled=False)
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
                return_value=(None, 131072),
            ) as validate_connection,
            patch.object(modal, "dismiss") as dismiss,
        ):
            await modal._submit_async()

        validate_connection.assert_awaited_once_with(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_DEBUG_API_KEY,
            model_name="google/gemma-4-31b-it:free",
        )
        dismiss.assert_called_once()

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


if __name__ == "__main__":
    unittest.main()
