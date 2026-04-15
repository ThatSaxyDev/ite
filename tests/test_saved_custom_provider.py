import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.config.loader import load_saved_custom_provider
from ite.config.loader import remove_saved_custom_provider
from ite.config.loader import save_saved_custom_provider
from ite.config.loader import save_system_config


class SavedCustomProviderTests(unittest.TestCase):
    def test_saves_multiple_profiles_independently(self) -> None:
        with tempfile.TemporaryDirectory() as sys_td:
            system_dir = Path(sys_td)
            with patch("ite.config.loader.get_config_dir", return_value=system_dir):
                save_saved_custom_provider(
                    api_key="key-one",
                    base_url="http://localhost:11434/v1",
                    model_name="llama-3.1:8b",
                )
                save_saved_custom_provider(
                    api_key="key-two",
                    base_url="http://localhost:8080",
                    model_name="gemma-4:4b",
                )

                profiles = load_saved_custom_provider()

                self.assertEqual(len(profiles), 2)
                self.assertEqual(
                    profiles["llama-3.1:8b"],
                    {
                        "api_key": "key-one",
                        "base_url": "http://localhost:11434/v1",
                        "model_name": "llama-3.1:8b",
                    },
                )
                self.assertEqual(
                    profiles["gemma-4:4b"],
                    {
                        "api_key": "key-two",
                        "base_url": "http://localhost:8080",
                        "model_name": "gemma-4:4b",
                    },
                )
                contents = (system_dir / "config.toml").read_text(encoding="utf-8")
                self.assertIn("[saved_custom_providers]", contents)
                self.assertIn("llama-3.1:8b", contents)
                self.assertIn("gemma-4:4b", contents)

    def test_removing_one_profile_keeps_others(self) -> None:
        with tempfile.TemporaryDirectory() as sys_td:
            system_dir = Path(sys_td)
            with patch("ite.config.loader.get_config_dir", return_value=system_dir):
                save_saved_custom_provider(
                    api_key="key-one",
                    base_url="http://localhost:11434/v1",
                    model_name="llama-3.1:8b",
                )
                save_saved_custom_provider(
                    api_key="key-two",
                    base_url="http://localhost:8080",
                    model_name="gemma-4:4b",
                )
                remove_saved_custom_provider(model_name="llama-3.1:8b")

                profiles = load_saved_custom_provider()

                self.assertEqual(len(profiles), 1)
                self.assertIn("gemma-4:4b", profiles)
                self.assertNotIn("llama-3.1:8b", profiles)

    def test_overwriting_model_preserves_others(self) -> None:
        with tempfile.TemporaryDirectory() as sys_td:
            system_dir = Path(sys_td)
            with patch("ite.config.loader.get_config_dir", return_value=system_dir):
                save_saved_custom_provider(
                    api_key="key-one",
                    base_url="http://localhost:11434/v1",
                    model_name="llama-3.1:8b",
                )
                save_saved_custom_provider(
                    api_key="key-two-updated",
                    base_url="http://localhost:8080",
                    model_name="llama-3.1:8b",
                )

                profiles = load_saved_custom_provider()

                self.assertEqual(len(profiles), 1)
                self.assertEqual(profiles["llama-3.1:8b"]["api_key"], "key-two-updated")


if __name__ == "__main__":
    unittest.main()
