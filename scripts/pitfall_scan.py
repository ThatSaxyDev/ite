"""Comprehensive pitfall scan for Reup mixin refactoring."""
import ast, os, sys
from collections import defaultdict

SRC = "src/ite/ui/reup"
MIXINS = ["_cloud", "_panels", "_composer", "_threads", "_turn", "_streaming"]

def parse_mixin(name):
    path = f"{SRC}/{name}.py"
    with open(path) as f:
        return path, ast.parse(f.read()), f.read()

# ── 1. Duplicate method names across mixins ──
print("=" * 60)
print("1. DUPLICATE METHOD NAMES")
method_files = defaultdict(list)
for mixin in MIXINS:
    path, tree, _ = parse_mixin(mixin)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue  # Private methods can duplicate
            method_files[node.name].append(mixin)

for name, files in sorted(method_files.items()):
    if len(files) > 1:
        print(f"  ⚠️  {name!r} defined in: {', '.join(files)}")

if all(len(f) == 1 for f in method_files.values()):
    print("  ✅ No public duplicate method names")

# ── 2. Textual lifecycle methods in mixins ──
print("\n" + "=" * 60)
print("2. TEXTUAL LIFECYCLE METHODS")
lifecycle = {"on_mount", "on_unmount", "on_load", "compose", "on_compose",
             "on_screen_resume", "on_screen_suspend", "watch_", "validate_"}
found_lifecycle = []
for mixin in MIXINS:
    path, tree, _ = parse_mixin(mixin)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in lifecycle or any(node.name.startswith(p) for p in ["watch_", "validate_"]):
                found_lifecycle.append((mixin, node.name, node.lineno))

if found_lifecycle:
    for mixin, name, line in found_lifecycle:
        print(f"  ⚠️  {mixin}.py:{line}  {name}() — Textual lifecycle in mixin")
else:
    print("  ✅ No Textual lifecycle methods in mixins")

# ── 3. super() usage in mixins ──
print("\n" + "=" * 60)
print("3. super() CALLS IN MIXINS")
for mixin in MIXINS:
    path, tree, _ = parse_mixin(mixin)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call):
                inner = node.func.value
                if isinstance(inner.func, ast.Name) and inner.func.id == "super":
                    print(f"  {mixin}.py:{node.lineno}  super().{node.func.attr}(...)")

print("  (empty = no super() calls — OK for pure mixins)")

# ── 4. Bare calls to methods defined in other mixins ──
print("\n" + "=" * 60)
print("4. BARE FUNCTION CALLS (potential cross-mixin refs)")
# Collect all method names defined in each mixin
mixin_methods = defaultdict(set)
for mixin in MIXINS:
    path, tree, _ = parse_mixin(mixin)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mixin_methods[mixin].add(node.name)

# Find bare calls (not self.xxx()) in each mixin
warnings = 0
for mixin in MIXINS:
    path, tree, source = parse_mixin(mixin)
    own_methods = mixin_methods[mixin]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called = node.func.id
            if called in ("print", "len", "str", "int", "bool", "float", "list", "dict",
                          "set", "tuple", "type", "isinstance", "hasattr", "getattr",
                          "setattr", "enumerate", "zip", "range", "next", "iter", "any",
                          "all", "max", "min", "sum", "sorted", "reversed", "abs",
                          "round", "open", "id", "dir", "vars", "callable", "repr",
                          "ascii", "format", "bytes", "bytearray", "memoryview", "chr",
                          "ord", "hex", "oct", "bin", "pow", "divmod", "input",
                          "staticmethod", "classmethod", "property", "object", "Exception"):
                continue
            if called not in own_methods and not called.startswith("_"):
                # Check if defined in another mixin
                defined_in = [m for m in MIXINS if m != mixin and called in mixin_methods[m]]
                if defined_in:
                    print(f"  ⚠️  {mixin}.py:{node.lineno}  bare call {called}() — defined in {', '.join(defined_in)}")
                    warnings += 1

if warnings == 0:
    print("  ✅ No bare cross-mixin method calls")

# ── 5. self.config, self.agent, self.session init tracking ──
print("\n" + "=" * 60)
print("5. CRITICAL OBJECT INIT TRACKING")
critical = {"config", "agent", "session", "model"}
for attr in critical:
    writes = []
    reads = []
    for mixin in MIXINS:
        path, tree, _ = parse_mixin(mixin)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                if node.attr == attr:
                    if isinstance(node.ctx, ast.Store):
                        writes.append(f"{mixin}.py:{node.lineno}")
                    elif isinstance(node.ctx, ast.Load):
                        reads.append(f"{mixin}.py:{node.lineno}")
    print(f"  self.{attr}:")
    print(f"    Written: {writes[:5]}{' ...' if len(writes) > 5 else ''}")
    print(f"    Read:    {reads[:5]}{' ...' if len(reads) > 5 else ''}")
    if not writes and reads:
        print(f"    ⚠️  NEVER ASSIGNED but READ!")

print()
sys.exit(warnings)
