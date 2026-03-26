from __future__ import annotations

import argparse
from pathlib import Path

from _pdf_core import inspect_pdf
import json


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a PDF and return basic metadata.")
    parser.add_argument("input", type=Path, help="Source PDF path")
    args = parser.parse_args()

    print(json.dumps(inspect_pdf(args.input), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
