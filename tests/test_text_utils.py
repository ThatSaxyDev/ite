import unittest
from unittest.mock import patch

from ite.utils import text as text_utils


class TextUtilsTests(unittest.TestCase):
    def tearDown(self) -> None:
        text_utils.get_tokenizer.cache_clear()

    def test_count_tokens_falls_back_to_estimate_when_tiktoken_is_unavailable(self) -> None:
        text_utils.get_tokenizer.cache_clear()

        with patch.object(
            text_utils.tiktoken,
            "encoding_for_model",
            side_effect=AttributeError("missing encoding_for_model"),
        ), patch.object(
            text_utils.tiktoken,
            "get_encoding",
            side_effect=RuntimeError("offline tokenizer registry unavailable"),
        ):
            self.assertEqual(text_utils.count_tokens("abcd", model="unknown-model"), 1)
            self.assertEqual(text_utils.count_tokens("abcdefgh", model="unknown-model"), 2)
