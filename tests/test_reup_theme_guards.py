import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "src" / "ite" / "ui" / "reup" / "app.py",
    ROOT / "src" / "ite" / "ui" / "reup" / "tool_views.py",
]
THEME_LOCALS = {"styles", "palette"}


class _LocalUsageGuard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.failures: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        bound: set[str] = set()

        for arg in (
            list(node.args.posonlyargs)
            + list(node.args.args)
            + list(node.args.kwonlyargs)
        ):
            bound.add(arg.arg)
        if node.args.vararg is not None:
            bound.add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            bound.add(node.args.kwarg.arg)

        loaded: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                if isinstance(child.ctx, ast.Store):
                    bound.add(child.id)
                elif isinstance(child.ctx, ast.Load) and child.id in THEME_LOCALS:
                    loaded.add(child.id)

        for name in sorted(loaded):
            if name not in bound:
                self.failures.append(
                    f"{node.name} uses `{name}` without binding it first"
                )


class ReupThemeGuardTests(unittest.TestCase):
    def test_theme_locals_are_bound_before_use(self) -> None:
        failures: list[str] = []

        for path in TARGETS:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            guard = _LocalUsageGuard()
            guard.visit(tree)
            failures.extend(f"{path.name}: {failure}" for failure in guard.failures)

        self.assertEqual(failures, [], "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
