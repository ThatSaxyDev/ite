import unittest

from ite.utils.errors import format_provider_error


class ProviderErrorFormattingTests(unittest.TestCase):
    def test_model_not_found_error_is_humanized(self) -> None:
        message = (
            'Error code: 404 - {'
            '"error": {"message": "model \'kimi-k2.5:cloud\' not found", '
            '"type": "api_error", "param": None, "code": None}}'
        )

        rendered = format_provider_error(
            kind="api",
            message=message,
            status_code=404,
        )

        self.assertIn("selected model was not found", rendered.lower())
        self.assertIn("kimi-k2.5:cloud", rendered)
        self.assertIn("check the exact model name", rendered.lower())

    def test_upstream_dns_error_is_humanized(self) -> None:
        message = (
            'Error code: 502 - {"error": '
            '"Post \\"https://ollama.com:443/v1/chat/completions?ts=1773738263\\": '
            'dial tcp: lookup ollama.com: no such host"}'
        )

        rendered = format_provider_error(
            kind="api",
            message=message,
            status_code=502,
        )

        self.assertIn("could not reach its upstream host", rendered.lower())
        self.assertIn("ollama.com", rendered)
        self.assertIn("dns", rendered.lower())

    def test_context_overflow_error_is_humanized(self) -> None:
        message = (
            'Error code: 400 - {"error": {"message": '
            '"prompt too long; exceeded max context length by 1397 tokens"}}'
        )

        rendered = format_provider_error(
            kind="api",
            message=message,
            status_code=400,
        )

        self.assertIn("exceeded the provider's context limit", rendered.lower())
        self.assertIn("1397", rendered)
        self.assertIn("thread history is too large", rendered.lower())


if __name__ == "__main__":
    unittest.main()
