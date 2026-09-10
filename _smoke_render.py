import asyncio

from textual.app import App

from ite.ui.reup.modals import ApprovalPickerModal, ThinkingLevelModal


class TApp(App[None]):
    CSS_PATH = "src/ite/ui/reup/reup.tcss"

    def on_mount(self) -> None:
        self.push_screen(ThinkingLevelModal("low", model_label="DeepSeek V4 Pro"))


class ApprovalApp(App[None]):
    CSS_PATH = "src/ite/ui/reup/reup.tcss"

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


asyncio.run(main())
