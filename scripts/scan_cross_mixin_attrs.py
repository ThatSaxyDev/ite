"""Scan mixins for self.attr reads that are defined in a different mixin."""
import ast, os, sys

SRC = "src/ite/ui/reup"
MIXINS = ["_cloud", "_panels", "_composer", "_threads", "_turn", "_streaming"]

# Collect all self.attr assignments per mixin
defined = {}
for mixin in MIXINS:
    path = f"{SRC}/{mixin}.py"
    if not os.path.exists(path):
        continue
    with open(path) as f:
        tree = ast.parse(f.read())
    attrs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                    attrs.add(target.attr)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute) and isinstance(node.target.value, ast.Name) and node.target.value.id == "self":
            attrs.add(node.target.attr)
    defined[mixin] = attrs

# Find reads of self.attr that cross mixin boundaries
errors = 0
for mixin in MIXINS:
    path = f"{SRC}/{mixin}.py"
    if not os.path.exists(path):
        continue
    with open(path) as f:
        tree = ast.parse(f.read())
    reads = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            if isinstance(node.ctx, ast.Load):
                reads.add(node.attr)

    own_attrs = defined.get(mixin, set())
    external_reads = reads - own_attrs

    for attr in sorted(external_reads):
        defined_in = [
            other for other in MIXINS
            if other != mixin and attr in defined.get(other, set())
        ]
        if defined_in:
            print(f"  {mixin}.py reads self.{attr} — DEFINED in {', '.join(defined_in)}")
            errors += 1

sys.exit(1 if errors else 0)
