"""Tests for the self-contained contributor tour script."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "repository_tour.py"
_MODULE_NAME = "repository_tour"


def _load_tour_module():
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before exec: @dataclass resolves annotations via sys.modules.
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Invoke the script in-process and capture (exit code, stdout, stderr)."""
    tour = _load_tour_module()
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        exit_code = tour.main(argv)
    return exit_code, out.getvalue(), err.getvalue()


class RepositoryTourTextOutputTests(unittest.TestCase):
    def test_text_output_lists_four_stops_with_real_paths(self) -> None:
        exit_code, stdout, _ = _run(["--root", str(REPO_ROOT)])

        self.assertEqual(exit_code, 0)
        self.assertIn("iTE contributor tour", stdout)
        for title in ("Entry point", "Agent and runtime", "Textual UI", "Tests"):
            self.assertIn(f"Stop", stdout)
            self.assertIn(title, stdout)
        self.assertEqual(stdout.count("Look at:"), 4)
        self.assertIn("Every path in this tour exists in this checkout.", stdout)

    def test_every_named_path_exists_in_this_repository(self) -> None:
        # Guards against the tour drifting away from the real tree.
        tour = _load_tour_module()

        self.assertEqual(len(tour.STOPS), 4)
        for stop in tour.STOPS:
            with self.subTest(stop=stop.key):
                self.assertTrue(stop.paths, "each stop must name at least one path")
                self.assertTrue(stop.why.strip(), "each stop must explain why to visit")
                for path in stop.paths:
                    self.assertTrue(
                        (REPO_ROOT / path).exists(),
                        f"{stop.key} references missing path {path}",
                    )

    def test_finds_root_from_a_nested_directory(self) -> None:
        tour = _load_tour_module()

        self.assertEqual(tour.find_repo_root(REPO_ROOT / "src" / "ite"), REPO_ROOT)


class RepositoryTourJsonOutputTests(unittest.TestCase):
    def test_json_output_is_valid_and_contains_four_stops(self) -> None:
        exit_code, stdout, _ = _run(["--root", str(REPO_ROOT), "--format", "json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["stop_count"], 4)
        self.assertEqual(
            [stop["key"] for stop in payload["stops"]],
            ["entry-point", "agent-runtime", "textual-ui", "tests"],
        )
        for stop in payload["stops"]:
            self.assertEqual(stop["missing_paths"], [])
            self.assertTrue(stop["paths"])
            self.assertTrue(stop["why"].strip())


class RepositoryTourFailureTests(unittest.TestCase):
    def test_outside_repository_root_fails_with_helpful_message(self) -> None:
        with TemporaryDirectory() as outside:
            exit_code, stdout, stderr = _run(["--root", outside])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Could not find the iTE repository root", stderr)
        self.assertIn("python scripts/repository_tour.py", stderr)


if __name__ == "__main__":
    unittest.main()
