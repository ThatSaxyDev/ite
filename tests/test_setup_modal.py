import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from ite.config.config import Config
from ite.ui.reup.modals import (
    RECOMMENDED_OLLAMA_MODELS,
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
            modal._apply_model_input_visibility(SETUP_MODEL_OTHER)

        self.assertTrue(model_input.display)

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
                                {"id": "google/gemma-4-31b-it:free"},
                                {"id": "arcee-ai/trinity-large-preview:free"},
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
                "arcee-ai/trinity-large-preview:free",
                "google/gemma-4-31b-it:free",
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

    async def test_probe_ollama_requires_running_service(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient([httpx.ConnectError("connection refused")]),
        ):
            message = await modal._probe_ollama(
                base_url="http://localhost:11434/v1",
                model_name="qwen2.5-coder:7b",
            )

        self.assertIn("Start Ollama first", message or "")

    async def test_probe_ollama_requires_selected_model(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [_FakeResponse(200, {"models": [{"name": "llama3.2:3b"}]})]
            ),
        ):
            message = await modal._probe_ollama(
                base_url="http://localhost:11434/v1",
                model_name="qwen2.5-coder:7b",
            )

        self.assertIn("ollama pull qwen2.5-coder:7b", message or "")

    async def test_probe_ollama_allows_cloud_model_without_local_tag(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [_FakeResponse(200, {"models": [{"name": "llama3.2:3b"}]})]
            ),
        ):
            message = await modal._probe_ollama(
                base_url="http://localhost:11434/v1",
                model_name="glm-5.1:cloud",
            )

        self.assertIsNone(message)

    async def test_probe_openai_compatible_rejects_invalid_key(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient([_FakeResponse(401)]),
        ):
            message = await modal._probe_openai_compatible(
                base_url="https://openrouter.ai/api/v1",
                api_key="bad-key",
                model_name="openai/gpt-4.1-mini",
            )

        self.assertIn("rejected this API key", message or "")

    async def test_probe_openai_compatible_requires_model_in_provider_list(self) -> None:
        modal = SetupModal(Config())

        with patch(
            "ite.ui.reup.modals.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [_FakeResponse(200, {"data": [{"id": "openai/gpt-4.1-mini"}]})]
            ),
        ):
            message = await modal._probe_openai_compatible(
                base_url="https://openrouter.ai/api/v1",
                api_key="key",
                model_name="anthropic/claude-sonnet-4",
            )

        self.assertIn("not available on this provider", message or "")


if __name__ == "__main__":
    unittest.main()
