#!/usr/bin/env python3
"""Simulate what iTE does when copying."""
import sys

# Simulate what happens in the app
def copy_to_clipboard(text: str) -> None:
    """Copy text to clipboard - matches the implementation in app.py"""
    if sys.platform == "darwin":
        try:
            import subprocess
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode("utf-8"))
            if proc.returncode == 0:
                print(f"pbcopy succeeded, text: {text!r}")
                return
        except Exception as e:
            print(f"pbcopy failed: {e}")

    try:
        import pyperclip
        pyperclip.copy(text)
        print(f"pyperclip succeeded, text: {text!r}")
        return
    except Exception as e:
        print(f"pyperclip failed: {e}")

    print("All methods failed")

# Test
copy_to_clipboard("def hello():\n    print('world')")

# Also verify pbpaste immediately after
import subprocess
result = subprocess.run(["pbpaste"], capture_output=True, text=True)
print(f"pbpaste immediate result: {result.stdout!r}")