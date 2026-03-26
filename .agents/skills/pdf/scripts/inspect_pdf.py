from __future__ import annotations

import argparse
import json
from pathlib import Path

from _pdf_core import basic_validate
from _pdf_core import page_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a PDF and return basic metadata.")
    parser.add_argument("input", type=Path, help="Source PDF path")
    args = parser.parse_args()

    payload = {
        "path": str(args.input.resolve()),
        "size_bytes": args.input.stat().st_size,
        "page_count": page_count(args.input),
        "validation_errors": basic_validate(args.input),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
