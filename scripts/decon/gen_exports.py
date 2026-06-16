"""Generate re-exports for all @on handlers from mixins."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import all mixins to inspect them
from ite.ui.reup._cloud import CloudMixin
from ite.ui.reup._panels import PanelsMixin  
from ite.ui.reup._composer import ComposerMixin
from ite.ui.reup._threads import ThreadsMixin
from ite.ui.reup._turn import TurnMixin
from ite.ui.reup._streaming import StreamingMixin

mixins = [CloudMixin, PanelsMixin, ComposerMixin, ThreadsMixin, TurnMixin, StreamingMixin]
seen = set()
lines = []

for mixin in mixins:
    for name, method in sorted(mixin.__dict__.items()):
        if hasattr(method, '_textual_on') and name not in seen:
            seen.add(name)
            lines.append(f"    {name} = {mixin.__name__}.{name}")

print("Add these lines inside the ReupApp class body:")
for line in lines:
    print(line)
print(f"\nTotal: {len(lines)} handlers")
