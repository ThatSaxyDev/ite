from ite.ui.reup._composer import ComposerMixin

m = ComposerMixin.__dict__.get('on_prompt_changed')
if m is None:
    print("on_prompt_changed not found in ComposerMixin.__dict__")
else:
    print(f"on_prompt_changed: type={type(m)}")
    for attr in dir(m):
        if not attr.startswith('__'):
            try:
                val = getattr(m, attr)
                if val is not None and not callable(val):
                    print(f"  {attr} = {val}")
            except Exception:
                pass
