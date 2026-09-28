"""Scan all mixins for tool_views names used but not imported."""
import ast, os, sys

SRC = "src/ite/ui/reup"
MIXINS = ["_cloud", "_panels", "_composer", "_threads", "_turn", "_streaming"]

# Get all public names defined in tool_views.py (functions, classes, module-level assignments)
with open(f"{SRC}/tool_views.py") as f:
    tv_tree = ast.parse(f.read())

tv_names = set()
for node in ast.iter_child_nodes(tv_tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        tv_names.add(node.name)
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                tv_names.add(target.id)

errors = 0
for mixin in MIXINS:
    path = f"{SRC}/{mixin}.py"
    if not os.path.exists(path):
        continue
    with open(path) as f:
        tree = ast.parse(f.read())

    # Find all names used (loaded) anywhere in the file
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)

    # Find what's imported at module level
    imported = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)

    missing = (used & tv_names) - imported
    if missing:
        print(f"❌ {mixin}.py missing from tool_views: {sorted(missing)}")
        errors += 1
    else:
        print(f"✅ {mixin}.py: clean")

sys.exit(errors)
