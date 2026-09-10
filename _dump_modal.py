import asyncio

from rich.console import Console
from textual.app import App

from ite.ui.reup.modals import ApprovalPickerModal, ThemePickerModal, ThinkingLevelModal


class TApp(App[None]):
    CSS_PATH = "src/ite/ui/reup/reup.tcss"

    def on_mount(self):
        self.push_screen(ThinkingLevelModal("low", model_label="DeepSeek V4 Pro"))


class AApp(App[None]):
    CSS_PATH = "src/ite/ui/reup/reup.tcss"

    def on_mount(self):
        self.push_screen(ApprovalPickerModal("auto"))


class HApp(App[None]):
    CSS_PATH = "src/ite/ui/reup/reup.tcss"

    def on_mount(self):
        self.push_screen(ThemePickerModal("textual-dark"))


async def dump(app, name):
    print(f"===== {name} =====")
    console = Console(width=100, color_system=None)
    console.print(app.screen._compositor)


async def main():
    for cls, name in [
        (TApp, "ThinkingLevelModal"),
        (AApp, "ApprovalPickerModal"),
        (HApp, "ThemePickerModal"),
    ]:
        app = cls()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await dump(app, name)


asyncio.run(main())
