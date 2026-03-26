from __future__ import annotations

import argparse
from pathlib import Path

from _pdf_core import basic_validate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the basic structure of a PDF.")
    parser.add_argument("input", type=Path, help="Path to the PDF file")
    args = parser.parse_args()

    errors = basic_validate(args.input)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
