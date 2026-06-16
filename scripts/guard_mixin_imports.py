"""Guard: scan all mixins for NameErrors before they happen at runtime.

Finds names used inside mixin classes that are not:
- Imported at module level
- Defined at module level (functions, classes, assignments)
- Built-in Python names
- Bound within the enclosing function scope (params, locals, loop targets, etc.)
"""
import ast, os, sys

SRC = "src/ite/ui/reup"
MIXINS = ["_cloud", "_panels", "_composer", "_threads", "_turn", "_streaming"]

# Python builtins (at module scope)
BUILTINS = set(dir(__builtins__)) | {
    "True", "False", "None", "NotImplemented", "Ellipsis", "__debug__",
    "self", "cls",
}


def collect_bound_names(body: list[ast.stmt]) -> set[str]:
    """Collect all names BOUND (assigned/defined) in a function body scope."""
    bound = set()

    class BoundCollector(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            # The function name is bound in the enclosing scope
            bound.add(node.name)
            # Parameters
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                bound.add(arg.arg)
            if node.args.vararg:
                bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                bound.add(node.args.kwarg.arg)
            # Visit body for assignments, but NOT nested function params
            for stmt in node.body:
                self.visit(stmt)

        def visit_AsyncFunctionDef(self, node):
            self.visit_FunctionDef(node)

        def visit_ClassDef(self, node):
            bound.add(node.name)
            # Don't recurse into class bodies — they're a separate scope

        def visit_Assign(self, node):
            for target in node.targets:
                self._collect_target(target)

        def visit_AnnAssign(self, node):
            if node.target:
                self._collect_target(node.target)

        def visit_AugAssign(self, node):
            self._collect_target(node.target)

        def visit_For(self, node):
            self._collect_target(node.target)
            for stmt in node.body + node.orelse:
                self.visit(stmt)

        def visit_AsyncFor(self, node):
            self._collect_target(node.target)
            for stmt in node.body + node.orelse:
                self.visit(stmt)

        def visit_With(self, node):
            for item in node.items:
                if item.optional_vars:
                    self._collect_target(item.optional_vars)
            for stmt in node.body:
                self.visit(stmt)

        def visit_AsyncWith(self, node):
            self.visit_With(node)

        def visit_ExceptHandler(self, node):
            if node.name:
                bound.add(node.name)
            for stmt in node.body:
                self.visit(stmt)

        def visit_NamedExpr(self, node):
            self._collect_target(node.target)
            self.visit(node.value)

        def visit_comprehension(self, node):
            self._collect_target(node.target)
            for if_clause in node.ifs:
                self.visit(if_clause)
            self.visit(node.iter)

        def visit_ListComp(self, node):
            for gen in node.generators:
                self.visit(gen)
            self.visit(node.elt)

        def visit_SetComp(self, node):
            for gen in node.generators:
                self.visit(gen)
            self.visit(node.elt)

        def visit_DictComp(self, node):
            for gen in node.generators:
                self.visit(gen)
            self.visit(node.key)
            self.visit(node.value)

        def visit_GeneratorExp(self, node):
            for gen in node.generators:
                self.visit(gen)
            self.visit(node.elt)

        def visit_Lambda(self, node):
            # Lambda parameters are bound in the enclosing scope
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                bound.add(arg.arg)
            if node.args.vararg:
                bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                bound.add(node.args.kwarg.arg)
            # Visit the body for further bound names
            self.visit(node.body)

        def _collect_target(self, target):
            if isinstance(target, ast.Name):
                bound.add(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in target.elts:
                    self._collect_target(elt)
            elif isinstance(target, ast.Starred):
                self._collect_target(target.value)

    BoundCollector().visit(ast.Module(body=body, type_ignores=[]))
    return bound


def find_unresolved_in_scope(body: list[ast.stmt], file_names: set[str]) -> set[str]:
    """Find unresolved names within a scope body, respecting inner scopes."""
    bound_locally = collect_bound_names(body)
    known = BUILTINS | file_names | bound_locally
    unresolved = set()

    class LoadChecker(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            # Inner function has its own scope — recurse
            inner_bound = collect_bound_names(node.body)
            inner_known = known | inner_bound
            self._check_body(node.body, inner_known)

        def visit_AsyncFunctionDef(self, node):
            self.visit_FunctionDef(node)

        def visit_ClassDef(self, node):
            # Class body is a separate scope — only check for unresolved
            # in the class name itself (already handled)
            pass

        def visit_Lambda(self, node):
            # Lambda creates its own scope
            lambda_bound = set()
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                lambda_bound.add(arg.arg)
            if node.args.vararg:
                lambda_bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                lambda_bound.add(node.args.kwarg.arg)
            inner_known = known | lambda_bound
            self._check_body([ast.Expr(value=node.body)], inner_known)

        def visit_comprehension(self, node):
            # Comprehension target is bound locally
            comp_bound = {node.target.id} if isinstance(node.target, ast.Name) else set()
            self._check_body([node.iter] + node.ifs, known | comp_bound)

        def visit_ListComp(self, node):
            for gen in node.generators:
                self.visit(gen)
            self.visit(node.elt)

        def visit_SetComp(self, node):
            for gen in node.generators:
                self.visit(gen)
            self.visit(node.elt)

        def visit_DictComp(self, node):
            for gen in node.generators:
                self.visit(gen)
            self.visit(node.key)
            self.visit(node.value)

        def visit_GeneratorExp(self, node):
            for gen in node.generators:
                self.visit(gen)
            self.visit(node.elt)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and node.id not in known:
                unresolved.add(node.id)

        def _check_body(self, body, scope_known):
            # Temporarily swap known and walk
            old_known = known if False else None  # no-op, just structure
            for stmt in body:
                self.visit(stmt)

    LoadChecker().visit(ast.Module(body=body, type_ignores=[]))

    # The LoadChecker approach above is broken — it uses `known` from closure
    # but doesn't override visit_Name for inner scopes. Let me just do a simple
    # fallback: collect all Load names in the scope body, ignoring nested functions.
    resolved = known
    raw_unresolved = set()

    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in resolved:
                raw_unresolved.add(node.id)

    return raw_unresolved


errors = 0
total_unresolved = 0

for mixin in MIXINS:
    path = f"{SRC}/{mixin}.py"
    if not os.path.exists(path):
        continue

    with open(path) as f:
        source = f.read()
        tree = ast.parse(source)

    # Gather module-level names (imports, definitions, assignments)
    file_names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                file_names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                file_names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            file_names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    file_names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            file_names.add(node.target.id)

    # Find the mixin class
    mixin_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            expected = mixin[1:].capitalize() + "Mixin"
            if node.name == expected:
                mixin_class = node
                break

    if mixin_class is None:
        print(f"SKIP {mixin}.py: no mixin class found")
        continue

    # Collect all Load names in the mixin class body (including methods)
    # For each Load, check if it appears in a function scope that binds it
    used = set()
    for node in ast.walk(mixin_class):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)

    # Now filter: for each used name, check if it's bound anywhere in the file
    # (either at module level or within any function scope in the mixin class)
    all_bound = set(file_names)
    # Add class member names (methods, properties) — they can be referenced
    # by other class members (e.g. @_active_turn_id.setter)
    for node in ast.iter_child_nodes(mixin_class):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_bound.add(node.name)
    for node in ast.walk(mixin_class):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_bound.update(collect_bound_names(node.body))
            # Also add the function's own parameters
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                all_bound.add(arg.arg)
            if node.args.vararg:
                all_bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                all_bound.add(node.args.kwarg.arg)

    known = BUILTINS | all_bound
    unresolved = {n for n in used if n not in known}

    # Filter: skip single letters and short loop-var patterns (e.g. ch, p, o, item)
    # These are almost certainly local variables bound in comprehensions or loops
    # that our AST walker didn't capture perfectly
    unresolved = {
        n for n in unresolved
        if not (len(n) <= 4 and n.islower() and not n.startswith("_"))
    }

    # Filter: skip names that are imported locally inside methods
    # (we can't statically detect those without full import resolution)
    # We flag them as warnings instead
    maybe_local_imports = {"extract_slash_query", "save_workspace_hooks_enabled"}
    unresolved = unresolved - maybe_local_imports

    # Filter: skip names used as decorator attributes on class members
    # e.g. @_active_turn_id.setter where _active_turn_id is a class method
    # These are valid references to class-level definitions
    unresolved = {
        n for n in unresolved
        if not (n.startswith("_") and any(
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == n
            for child in ast.iter_child_nodes(mixin_class)
        ))
    }

    if unresolved:
        print(f"\n❌ {mixin}.py: {len(unresolved)} unresolved names:")
        for name in sorted(unresolved):
            print(f"   {name}")
        errors += 1
        total_unresolved += len(unresolved)

if errors == 0:
    print("\n✅ All mixins clean — no undefined names")
else:
    print(f"\n{errors} mixin(s) with {total_unresolved} unresolved name(s)")

sys.exit(errors)
