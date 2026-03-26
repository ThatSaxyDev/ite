from __future__ import annotations

import argparse
from pathlib import Path

from _docx_core import unpack_to_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Unpack a .docx file into a directory.")
    parser.add_argument("input", type=Path, help="Path to the source .docx file")
    parser.add_argument("output_dir", type=Path, help="Directory to receive the unpacked package")
    args = parser.parse_args()

    unpack_to_directory(args.input, args.output_dir)
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
