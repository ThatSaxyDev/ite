"""Inspect modal layout with python scripts/_smoke_render.py."""

import asyncio
import sys
from pathlib import Path
from typing import ClassVar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from textual.app import App

from ite.ui.reup.app import ReupApp
from ite.ui.reup.modals import ApprovalPickerModal, ThinkingLevelModal


class TApp(App[None]):
    CSS_PATH: ClassVar[list[str]] = [
        str(PROJECT_ROOT / "src/ite/ui/reup" / path)
        for path in ReupApp.CSS_PATH
    ]

    def on_mount(self) -> None:
        self.push_screen(ThinkingLevelModal("low", model_label="DeepSeek V4 Pro"))


class ApprovalApp(App[None]):
    CSS_PATH = TApp.CSS_PATH

    def on_mount(self) -> None:
        self.push_screen(ApprovalPickerModal("auto"))


async def dump(app, name):
    screen = app.screen
    print(f"=== {name} ===")
    btn = screen.query_one("#select")
    s = btn.styles
    print("  region:", btn.region)
    print("  height:", s.height, "min_height:", s.min_height)
    print("  border_top:", s.border_top, "border_bottom:", s.border_bottom)
    actions = screen.query_one(".modal-actions")
    print("  actions region:", actions.region, "height:", actions.styles.height)
    modal = screen.query_one(".modal")
    print("  modal region:", modal.region, "height:", modal.styles.height)


async def main() -> None:
    app = TApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await dump(app, "ThinkingLevelModal")

    app2 = ApprovalApp()
    async with app2.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await dump(app2, "ApprovalPickerModal")


if __name__ == "__main__":
    asyncio.run(main())
