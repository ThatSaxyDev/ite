import asyncio
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static
from ite.ui.reup.widgets.message_row import UserMessageRow


class T(App):
    CSS = ""
    def __init__(self, css):
        super().__init__()
        self.CSS = css
    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="conversation")


BASE = """
#conversation { width: 80; height: 40; padding: 0 5 0 5; }
.chat-user-row { width: 100%; height: auto; align-horizontal: right; margin: 0 0 2 0; padding: 0; }
.chat-user-bubble { width: auto; max-width: 92; min-height: 1; margin-left: 8; margin-right: 2; padding: 1 1; background: gray; text-align: right; content-align: right middle; }
.chat-image-preview { width: auto; height: auto; margin-right: 2; margin-bottom: 1; padding: 0; }
"""


async def run(css) -> None:
    app = T(css)
    async with app.run_test(size=(80, 40)) as pilot:
        conv = app.query_one("#conversation", VerticalScroll)
        bubble = Static("hello world", classes="chat-user-bubble")
        row = UserMessageRow(
            bubble, desired_width=12, raw_text="hello world",
            images=["/tmp/ite_test.png"], classes="chat-user-row",
        )
        await conv.mount(row)
        await pilot.pause()
        for w in row.children:
            print("   ", w.classes, "region=", w.region)
    print()


async def main() -> None:
    from PIL import Image
    Image.new("RGB", (80, 40), (120, 60, 200)).save("/tmp/ite_test.png")

    print("== A: explicit preview width via CSS (60) ==")
    a = BASE.replace(
        ".chat-image-preview { width: auto;", ".chat-image-preview { width: 60;"
    )
    await run(a)

    print("== B: preview width 60 + bubble margin-left removed ==")
    b = a.replace("margin-left: 8;", "")
    await run(b)

    print("== C: both explicit width, row uses align-horizontal right ==")
    c = a.replace(".chat-user-bubble { width: auto;", ".chat-user-bubble { width: 12;")
    await run(c)


asyncio.run(main())
