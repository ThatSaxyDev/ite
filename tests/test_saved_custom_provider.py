import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.config.loader import load_saved_custom_provider
from ite.config.loader import save_saved_custom_provider
from ite.config.loader import save_system_config


class SavedCustomProviderTests(unittest.TestCase):
    def test_round_trips_saved_custom_provider_profile(self) -> None:
        with tempfile.TemporaryDirectory() as sys_td:
            system_dir = Path(sys_td)
            with patch("ite.config.loader.get_config_dir", return_value=system_dir):
                save_system_config(
                    api_key="runtime-key",
                    base_url="http://localhost:11434/v1",
                    model_name="minimax-m2.7:cloud",
                )
                save_saved_custom_provider(
                    api_key="custom-key",
                    base_url="http://localhost:8080",
                    model_name="unsloth/gemma-4-E4B-it-UD-MLX-4bit",
                )

                profile = load_saved_custom_provider()

                self.assertEqual(
                    profile,
                    {
                        "api_key": "custom-key",
                        "base_url": "http://localhost:8080",
                        "model_name": "unsloth/gemma-4-E4B-it-UD-MLX-4bit",
                    },
                )
                contents = (system_dir / "config.toml").read_text(encoding="utf-8")
                self.assertIn("[saved_custom_provider]", contents)


if __name__ == "__main__":
    unittest.main()
