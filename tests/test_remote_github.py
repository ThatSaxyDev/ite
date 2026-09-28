from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.remote import github as github_mod
from ite.remote.github import GithubState


class RemoteGithubLocalTests(unittest.TestCase):
    def test_disconnect_without_gh_returns_unlinked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp}), patch.object(
            github_mod, "gh_available", return_value=False
        ):
            state = github_mod.disconnect()
        self.assertIsInstance(state, GithubState)
        self.assertFalse(state.linked)
        self.assertFalse(state.gh_ready)

    def test_write_and_clear_credentials_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp}):
            github_mod._write_credentials_file("octocat", "secret-token")
            path = Path(tmp) / ".git-credentials"
            self.assertTrue(path.exists())
            self.assertIn("github.com", path.read_text(encoding="utf-8"))
            self.assertNotIn("secret-token\nsecret-token", path.read_text(encoding="utf-8"))
            github_mod._clear_credentials_file()
            self.assertFalse(path.exists())

    def test_connect_requires_gh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp}), patch.object(
            github_mod, "gh_available", return_value=False
        ):
            state = github_mod.connect("https://api.example.com", "token")
        self.assertFalse(state.linked)
        self.assertEqual(state.error, "github_cli_missing")


if __name__ == "__main__":
    unittest.main()
