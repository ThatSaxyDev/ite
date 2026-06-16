"""Find self.attr reads where attr is never assigned in any mixin or app.py."""
import ast, sys

SRC = "src/ite/ui/reup"
MIXIN_FILES = [
    "_cloud.py", "_panels.py", "_composer.py",
    "_threads.py", "_turn.py", "_streaming.py",
]
ALL_FILES = MIXIN_FILES + ["app.py"]

# Collect ALL self.attr writes (assignments) across all files
writes = set()
for fname in ALL_FILES:
    path = f"{SRC}/{fname}"
    with open(path) as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                    writes.add(target.attr)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute) and isinstance(node.target.value, ast.Name) and node.target.value.id == "self":
            writes.add(node.target.attr)

# Collect self.attr reads, flag those never written
errors = 0
for fname in MIXIN_FILES:
    path = f"{SRC}/{fname}"
    with open(path) as f:
        tree = ast.parse(f.read())
    reads = set()
    read_lines = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            if isinstance(node.ctx, ast.Load):
                reads.add(node.attr)
                if node.attr not in read_lines:
                    read_lines[node.attr] = []
                read_lines[node.attr].append(node.lineno)

    # Also check for self.attr in function calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
            reads.add(node.func.attr)
            if node.func.attr not in read_lines:
                read_lines[node.func.attr] = []
            read_lines[node.func.attr].append(node.lineno)

    never_written = reads - writes
    # Filter out Textual built-in attrs and common patterns
    known_safe = {
        "query_one", "query", "mount", "remove", "refresh", "refresh_bindings",
        "push_screen", "pop_screen", "switch_screen", "dismiss", "install_screen",
        "run_worker", "workers", "call_from_thread", "call_later", "set_interval",
        "set_timer", "notify", "bell", "exit", "action_", "check_bindings",
        "mount_all", "run_action", "get_child_by_id", "post_message", "log",
        "screen", "app", "id", "name", "classes", "pseudo_classes", "display",
        "visible", "disabled", "styles", "border", "scroll", "focus", "clear",
        "add_class", "remove_class", "toggle_class", "has_class",
        "loading", "update", "sort_children",
        "scroll_to", "scroll_end", "scroll_home",
        "scroll_visible", "virtual_size", "size", "region",
        "scroll_offset", "max_scroll", "can_focus", "has_focus",
        "capture_mouse", "release_mouse", "mouse_over",
        "watch", "compose", "on_mount", "on_unmount",
    }
    never_written = never_written - known_safe

    if never_written:
        print(f"\n{fname} reads self.ATTR but ATTR never assigned anywhere:")
        for attr in sorted(never_written):
            lines = read_lines.get(attr, [])
            print(f"  self.{attr} at lines {lines[:3]}{'...' if len(lines) > 3 else ''}")
        errors += 1

if not errors:
    print("All self.attr reads have matching writes somewhere")

sys.exit(errors)
