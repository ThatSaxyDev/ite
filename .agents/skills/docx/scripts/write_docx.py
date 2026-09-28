from __future__ import annotations

import argparse
from pathlib import Path

from _docx_core import build_simple_document


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a simple .docx file from text or markdown.")
    parser.add_argument("input", type=Path, nargs="?", help="Source text or markdown file")
    parser.add_argument("output", type=Path, help="Output .docx path")
    parser.add_argument("--title", help="Optional document title inserted as the first paragraph")
    parser.add_argument(
        "--template",
        choices=("memo", "letter"),
        help="Use a bundled starter template when no input file is provided",
    )
    args = parser.parse_args()

    if args.input is None and args.template is None:
        raise SystemExit("provide either an input file or --template")

    source_path = args.input
    if source_path is None:
        source_path = Path(__file__).resolve().parent.parent / "templates" / f"{args.template}.md"

    source = source_path.read_text(encoding="utf-8")
    paragraphs = [line.strip() for line in source.splitlines() if line.strip()]
    if not paragraphs:
        raise SystemExit("input did not contain any non-empty lines")
    payload = build_simple_document(paragraphs, title=args.title)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
