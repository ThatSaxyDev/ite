from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_build_runtime_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_runtime.py"
    spec = importlib.util.spec_from_file_location("build_runtime", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildRuntimeTests(unittest.TestCase):
    def test_removed_ui_packages_are_not_hidden_imports(self) -> None:
        build_runtime = _load_build_runtime_module()

        self.assertNotIn("flet", build_runtime.HIDDEN_IMPORTS)
        self.assertNotIn("flet_core", build_runtime.HIDDEN_IMPORTS)
        self.assertNotIn("prompt_toolkit", build_runtime.HIDDEN_IMPORTS)


if __name__ == "__main__":
    unittest.main()
