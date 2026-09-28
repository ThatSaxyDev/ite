"""Parse @on handlers from mixin files and print re-exports for app.py."""
import re, os

SRC = "src/ite/ui/reup"
mixins = ["_cloud", "_panels", "_composer", "_threads", "_turn", "_streaming"]
seen = set()
lines = []

for m in mixins:
    with open(f"{SRC}/{m}.py") as f:
        content = f.read()
    
    # Find @on(...) followed by def method_name
    for match in re.finditer(r'@on\([^)]+\)\s*\n\s+def (\w+)', content):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            cn = f"{m[1:].capitalize()}Mixin"
            lines.append(f"    {name} = {cn}.{name}")
    
    # Also find @on(...) with no selector or unnamed
    for match in re.finditer(r'@on\([^)]+\)\s*\n\s+async def (\w+)', content):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            cn = f"{m[1:].capitalize()}Mixin"
            lines.append(f"    {name} = {cn}.{name}")

for line in sorted(lines):
    print(line)
print(f"\nTotal: {len(lines)} handlers")
