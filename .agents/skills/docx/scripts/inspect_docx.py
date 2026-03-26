from __future__ import annotations

import argparse
from pathlib import Path

from _docx_core import inspect_docx
from _docx_core import json_dump


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a .docx file and report basic metadata.")
    parser.add_argument("input", type=Path, help="Path to the source .docx file")
    args = parser.parse_args()

    print(json_dump(inspect_docx(args.input)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
