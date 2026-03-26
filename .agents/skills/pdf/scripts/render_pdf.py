from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a PDF to page PNGs using pdftoppm.")
    parser.add_argument("input", type=Path, help="Source PDF path")
    parser.add_argument("--output_dir", type=Path, required=True, help="Directory for rendered page images")
    parser.add_argument("--dpi", type=int, default=144, help="Rasterization DPI")
    args = parser.parse_args()

    if shutil.which("pdftoppm") is None:
        raise SystemExit("missing required system tool: pdftoppm")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.output_dir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(args.dpi), str(args.input), str(prefix)],
        check=True,
        capture_output=True,
        text=True,
    )
    for path in sorted(args.output_dir.glob("page-*.png")):
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
