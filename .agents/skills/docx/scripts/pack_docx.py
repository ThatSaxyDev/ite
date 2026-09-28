from __future__ import annotations

import argparse
from pathlib import Path

from _docx_core import pack_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack an unpacked OOXML directory into a .docx file.")
    parser.add_argument("input_dir", type=Path, help="Directory containing the unpacked document")
    parser.add_argument("output", type=Path, help="Output .docx file")
    args = parser.parse_args()

    pack_directory(args.input_dir, args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
