from __future__ import annotations

import argparse
from pathlib import Path

from _pdf_core import build_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a simple PDF from a text or markdown file.")
    parser.add_argument("input", type=Path, help="Source text file")
    parser.add_argument("output", type=Path, help="Output PDF path")
    parser.add_argument("--title", help="Optional title placed at the top of the first page")
    args = parser.parse_args()

    lines = [line.strip() for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise SystemExit("input did not contain any non-empty lines")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(build_pdf(lines, title=args.title))
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
