from __future__ import annotations

from pathlib import Path
from typing import cast

from rich.text import Text

from ite.attachments import IMAGE_EXTS

DEFAULT_MAX_COLS = 60
DEFAULT_MAX_ROWS = 30


def is_image_path(path: str | Path) -> bool:
    """Return True if the path has a supported image extension."""
    return Path(path).suffix.lower() in IMAGE_EXTS


def render_image_halfblock(
    path: str | Path,
    *,
    max_cols: int = DEFAULT_MAX_COLS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Text | None:
    """Render an image file as half-block truecolor text.

    Each terminal cell encodes two vertical source pixels: the upper half
    block (``\u2580``) uses the top pixel as foreground and the bottom pixel
    as background. This renders in any truecolor terminal without graphics
    protocol support.
    """
    try:
        from PIL import Image
        from rich.color import Color
        from rich.style import Style
    except ImportError:
        return None

    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            width, height = image.size
            cols = min(max_cols, max(1, width))
            rows = max(1, min(max_rows, round(cols * (height / width) * 0.5)))
            image = image.resize((cols, rows * 2), Image.Resampling.LANCZOS)
            pixels = image.load()
            if pixels is None:
                return None

            text = Text(no_wrap=True)
            for y in range(rows):
                for x in range(cols):
                    top = cast(tuple[int, int, int], pixels[x, y * 2])
                    bottom = cast(tuple[int, int, int], pixels[x, y * 2 + 1])
                    text.append(
                        "\u2580",
                        style=Style(
                            color=Color.from_rgb(top[0], top[1], top[2]),
                            bgcolor=Color.from_rgb(
                                bottom[0], bottom[1], bottom[2]
                            ),
                        ),
                    )
                if y < rows - 1:
                    text.append("\n")
            return text
    except Exception:
        return None
