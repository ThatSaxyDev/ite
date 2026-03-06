from .app import GUIApp, create_gui_app, run_gui

# Backward-compat alias
GUI = GUIApp

__all__ = ["GUIApp", "GUI", "create_gui_app", "run_gui"]
