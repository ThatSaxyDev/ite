from __future__ import annotations

import argparse
from pathlib import Path

from _docx_core import validate_docx


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the basic shape of a .docx file.")
    parser.add_argument("input", type=Path, help="Path to the .docx file")
    args = parser.parse_args()

    errors = validate_docx(args.input)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
