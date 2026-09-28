import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ite.config.config import Config


class ConfigSetupRequirementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def test_needs_setup_when_api_key_missing(self) -> None:
        config = Config(cwd=self.cwd, base_url="http://localhost:11434/v1")
        self.assertTrue(config.needs_setup)
        self.assertIn("missing_api_key", config.validate())

    def test_needs_setup_when_base_url_missing(self) -> None:
        config = Config(cwd=self.cwd, api_key="test-key")
        self.assertTrue(config.needs_setup)
        self.assertIn("missing_base_url", config.validate())

    def test_needs_setup_when_model_missing(self) -> None:
        config = Config(cwd=self.cwd, api_key="test-key", base_url="http://localhost:11434/v1")
        config.model.name = ""
        self.assertTrue(config.needs_setup)
        self.assertIn("missing_model", config.validate())


if __name__ == "__main__":
    unittest.main()
