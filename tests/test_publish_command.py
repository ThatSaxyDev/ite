import asyncio
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from ite.commands import CommandContext, build_registry
from ite.config.config import Config


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(cwd: Path) -> None:
    _run_git(cwd, "init")
    _run_git(cwd, "config", "user.name", "ITE Tests")
    _run_git(cwd, "config", "user.email", "ite-tests@example.com")


def _commit_file(cwd: Path, path: str, content: str, message: str) -> None:
    file_path = cwd / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    _run_git(cwd, "add", "-A", "--", ".")
    _run_git(cwd, "commit", "-m", message)


class PublishCommandTests(unittest.TestCase):
    def _context(self, cwd: Path, stream: io.StringIO) -> CommandContext:
        return CommandContext(
            config=Config(cwd=cwd, api_key="test"),
            agent=None,
            tui=SimpleNamespace(),
            console=Console(file=stream, force_terminal=False, color_system=None),
        )

    def test_publish_command_is_registered(self) -> None:
        registry = build_registry()
        self.assertIsNotNone(registry.get("/publish"))

    def test_publish_without_remote_shows_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _init_repo(cwd)
            _commit_file(cwd, "app.py", "print('one')\n", "initial commit")
            stream = io.StringIO()
            ctx = self._context(cwd, stream)
            registry = build_registry()

            asyncio.run(registry.dispatch("/publish", [], ctx))

            output = stream.getvalue()
            self.assertIn("No remote configured", output)
            self.assertIn("/publish <remote-url>", output)

    def test_publish_with_url_configures_remote_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            remote = cwd / "remote.git"
            _init_repo(cwd)
            _commit_file(cwd, "app.py", "print('one')\n", "initial commit")
            subprocess.run(["git", "init", "--bare", str(remote)], check=False, capture_output=True, text=True)
            stream = io.StringIO()
            ctx = self._context(cwd, stream)
            registry = build_registry()

            asyncio.run(registry.dispatch("/publish", [str(remote)], ctx))

            output = stream.getvalue()
            self.assertIn("Added remote origin.", output)
            self.assertIn("Published", output)
            upstream = _run_git(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
            self.assertTrue(upstream.stdout.strip().startswith("origin/"))


if __name__ == "__main__":
    unittest.main()
