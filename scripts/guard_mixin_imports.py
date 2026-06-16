"""Guard: scan all mixins for NameErrors before they happen at runtime.
Finds names used inside mixin classes that aren't imported or defined locally.
"""
import ast, os, sys

SRC = "src/ite/ui/reup"
MIXINS = ["_cloud", "_panels", "_composer", "_threads", "_turn", "_streaming"]

# Names defined in the original app.py at module level that mixins might need
# (gathered from app.py.backup)
with open(f"{SRC}/app.py.backup") as f:
    orig_tree = ast.parse(f.read())

orig_module_names = set()
orig_assignments = {}
for node in ast.iter_child_nodes(orig_tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                orig_module_names.add(target.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        orig_module_names.add(node.target.id)
    elif isinstance(node, ast.FunctionDef):
        orig_module_names.add(node.name)
    elif isinstance(node, ast.ClassDef):
        orig_module_names.add(node.name)

errors = 0
for mixin in MIXINS:
    path = f"{SRC}/{mixin}.py"
    if not os.path.exists(path):
        continue
    
    with open(path) as f:
        tree = ast.parse(f.read())
    
    # Gather imports and top-level definitions in this file
    file_names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                file_names.add(alias.asname or alias.name)
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
    
    # Find all name loads inside the mixin class
    mixin_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == f"{mixin[1:].capitalize()}Mixin":
            mixin_class = node
            break
    
    if mixin_class is None:
        print(f"SKIP {mixin}.py: no mixin class found")
        continue
    
    class NameCollector(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                used.add(node.id)
            self.generic_visit(node)
    
    used = set()
    NameCollector().visit(mixin_class)
    
    # Resolve names: builtins + file_names + 'self' + parameters are OK
    builtins = set(dir(__builtins__))
    unresolved = used - file_names - builtins - {"self", "True", "False", "None", "NotImplemented", "Ellipsis", "__debug__"}
    
    # Filter out names that are obviously local variables (lowercase) 
    # Only flag names that look like they could be module-level constants/imports
    suspicious = {n for n in unresolved if n[0].isupper() or n.startswith("_") and n[1].isupper()}
    
    if suspicious:
        print(f"\n❌ {mixin}.py: missing {len(suspicious)} names:")
        for name in sorted(suspicious):
            # Check if it's in the original file
            in_orig = name in orig_module_names
            marker = " (was in app.py)" if in_orig else ""
            print(f"   {name}{marker}")
        errors += 1
    
if errors == 0:
    print("\n✅ All mixins clean — no undefined top-level names")
else:
    print(f"\n{errors} mixin(s) have unresolved names")

sys.exit(errors)
