#!/usr/bin/env python3

path = "/Users/kiishidavid/Documents/Dev/Projects/ite/.venv/lib/python3.14/site-packages/idb/cli/main.py"

with open(path, "r") as f:
    lines = f.readlines()

# Current state (lines 352-361) is broken:
# Line 352: def main(...):
# Lines 353-357: try/except block with duplicate line
# Lines 358-360: return/finally incorrectly indented inside except

# Replace lines 353-360 with correct structure
# Note: 0-indexed means lines 352-359
correct_lines = [
    "    try:\n",
    "        loop = asyncio.get_event_loop()\n",
    "    except RuntimeError:\n",
    "        loop = asyncio.new_event_loop()\n",
    "        asyncio.set_event_loop(loop)\n",
    "    try:\n",
    "        return loop.run_until_complete(gen_main(cmd_input))\n",
    "    finally:\n",
    "        loop.close()\n",
]

# Replace lines 353-361 (0-indexed: 352-360)
lines[352:361] = correct_lines

with open(path, "w") as f:
    f.writelines(lines)

# Verify
print("Verification - lines 350-365:")
for i, line in enumerate(lines[349:365], start=350):
    print(f"  {i}: {repr(line)}")