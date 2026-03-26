from __future__ import annotations

import argparse
from pathlib import Path

from _pdf_core import extract_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract lightweight text from a simple PDF.")
    parser.add_argument("input", type=Path, help="Source PDF path")
    parser.add_argument("--output", type=Path, help="Optional destination for extracted text")
    args = parser.parse_args()

    content = extract_text(args.input)
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
