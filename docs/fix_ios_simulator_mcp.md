# Fix iOS Simulator MCP — Python 3.14 Compatibility

## The Problem

The iOS Simulator MCP (`ios-simulator-mcp`) uses `idb` (Facebook's iOS Dev Tools Bridge) to interact with iOS simulators. When running on Python 3.14, `idb` crashes on launch with:

```
RuntimeError: There is no current event loop in thread 'MainThread'.
```

This happens because Python 3.10+ changed `asyncio.get_event_loop()` to raise a `RuntimeError` on the main thread instead of silently creating a loop. The `idb` CLI wasn't updated to handle this.

## Root Cause

`idb`'s `cli/main.py` calls `asyncio.get_event_loop()` at startup without handling the Python 3.10+ behavior change.

## The Fix

Two copies of `idb` needed patching — one in the system Python and one in the project venv:

### 1. Patch the fix script

```bash
python3 /Users/kiishidavid/Documents/Dev/Projects/ite/fix_idb.py
```

The script (`fix_idb.py`) reads `idb/cli/main.py`, finds the broken `asyncio.get_event_loop()` call, and replaces it with:

```python
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
```

### 2. Patch both locations

The script above patches the **system** `idb` at:
```
/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/site-packages/idb/cli/main.py
```

To also patch the **project venv** `idb`, update the path in the script:
```bash
sed -i '' "s|/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/site-packages/idb|/Users/kiishidavid/Documents/Dev/Projects/ite/.venv/lib/python3.14/site-packages/idb|g" /Users/kiishidavid/Documents/Dev/Projects/ite/fix_idb.py
python3 /Users/kiishidavid/Documents/Dev/Projects/ite/fix_idb.py
```

### 3. Allow sandbox access to idb's path

Add this to `.ite/config.toml`:

```toml
[sandbox]
enabled = true
allowed_paths = ["/Library/Frameworks/Python.framework/Versions/3.14"]
```

Then restart ite.

### 4. Verify

```bash
idb list-targets
```

## What We Did

1. Identified the bug — `sed` mangled an early patch attempt, leaving the file with wrong indentation
2. Wrote a Python script (`fix_idb.py`) to safely patch the file
3. Added the sandbox path to `.ite/config.toml` so ite could access `idb`
4. Patched both system and venv copies of `idb`
5. Verified with `idb list-targets` and successfully used the iOS Simulator MCP tools (tap, ui_describe_all, etc.)