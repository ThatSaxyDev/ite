"""Tests for the OpenRouter OAuth secret save/load/merge in config/loader.py."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.config.loader import (
    _merge_openrouter_oauth_secret,
    clear_openrouter_oauth_secret,
    load_openrouter_oauth_secret,
    save_openrouter_oauth_secret,
)


class OpenRouterOAuthSecretTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.system_dir = Path(self._tmp.name)

    def _patch_config_dir(self) -> None:
        patcher = patch(
            "ite.config.loader.get_config_dir", return_value=self.system_dir
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_then_load_round_trips(self) -> None:
        self._patch_config_dir()
        save_openrouter_oauth_secret(
            api_key="sk-or-v1-abc", key_label="iTE CLI (test)"
        )

        loaded = load_openrouter_oauth_secret()
        self.assertIsNotNone(loaded)
        assert loaded is not None  # type narrowing for mypy
        self.assertEqual(loaded["api_key"], "sk-or-v1-abc")
        self.assertEqual(loaded["key_label"], "iTE CLI (test)")
        self.assertIn("created_at", loaded)

    def test_save_chmods_secrets_file(self) -> None:
        self._patch_config_dir()
        save_openrouter_oauth_secret(api_key="sk-or-v1-xyz")

        path = self.system_dir / "secrets.toml"
        mode = path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_save_preserves_existing_other_tables(self) -> None:
        self._patch_config_dir()
        # Pre-populate the file with an unrelated table.
        secrets_path = self.system_dir / "secrets.toml"
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        secrets_path.write_text(
            '[unrelated]\nfoo = "bar"\n',
            encoding="utf-8",
        )
        os.chmod(secrets_path, 0o600)

        save_openrouter_oauth_secret(api_key="sk-or-v1-abc")

        contents = secrets_path.read_text(encoding="utf-8")
        self.assertIn("[unrelated]", contents)
        self.assertIn("foo = \"bar\"", contents)
        self.assertIn("[openrouter]", contents)
        self.assertIn("api_key = \"sk-or-v1-abc\"", contents)

    def test_clear_removes_only_openrouter_table(self) -> None:
        self._patch_config_dir()
        secrets_path = self.system_dir / "secrets.toml"
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        secrets_path.write_text(
            '[unrelated]\nfoo = "bar"\n\n[openrouter]\napi_key = "sk"\n',
            encoding="utf-8",
        )
        os.chmod(secrets_path, 0o600)

        clear_openrouter_oauth_secret()

        contents = secrets_path.read_text(encoding="utf-8")
        self.assertIn("[unrelated]", contents)
        self.assertNotIn("[openrouter]", contents)

    def test_load_returns_none_when_file_missing(self) -> None:
        self._patch_config_dir()
        self.assertIsNone(load_openrouter_oauth_secret())


class MergeOpenRouterOAuthSecretTests(unittest.TestCase):
    def test_injects_key_when_base_url_is_openrouter(self) -> None:
        with patch(
            "ite.config.loader.load_openrouter_oauth_secret",
            return_value={"api_key": "sk-or-v1-abc"},
        ):
            merged = _merge_openrouter_oauth_secret(
                {"base_url": "https://openrouter.ai/api/v1", "api_key": ""}
            )
        self.assertEqual(merged["api_key"], "sk-or-v1-abc")

    def test_does_not_inject_for_other_providers(self) -> None:
        with patch(
            "ite.config.loader.load_openrouter_oauth_secret",
            return_value={"api_key": "sk-or-v1-abc"},
        ):
            merged = _merge_openrouter_oauth_secret(
                {"base_url": "http://localhost:11434/v1"}
            )
        self.assertNotIn("api_key", merged)

    def test_does_not_overwrite_existing_key(self) -> None:
        with patch(
            "ite.config.loader.load_openrouter_oauth_secret",
            return_value={"api_key": "sk-or-v1-from-secret"},
        ):
            merged = _merge_openrouter_oauth_secret(
                {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-v1-from-paste",
                }
            )
        self.assertEqual(merged["api_key"], "sk-or-v1-from-paste")

    def test_noop_when_secret_is_missing(self) -> None:
        with patch(
            "ite.config.loader.load_openrouter_oauth_secret", return_value=None
        ):
            merged = _merge_openrouter_oauth_secret(
                {"base_url": "https://openrouter.ai/api/v1"}
            )
        self.assertNotIn("api_key", merged)

    def test_noop_when_secret_has_empty_key(self) -> None:
        with patch(
            "ite.config.loader.load_openrouter_oauth_secret",
            return_value={"api_key": "   "},
        ):
            merged = _merge_openrouter_oauth_secret(
                {"base_url": "https://openrouter.ai/api/v1"}
            )
        self.assertNotIn("api_key", merged)


if __name__ == "__main__":
    unittest.main()
