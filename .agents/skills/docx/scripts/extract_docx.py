from __future__ import annotations

import argparse
import json
from pathlib import Path

from _docx_core import load_document_tree
from _docx_core import paragraph_texts


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract readable content from a .docx file.")
    parser.add_argument("input", type=Path, help="Path to the source .docx file")
    parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="Output format",
    )
    parser.add_argument("--output", type=Path, help="Optional file to write extracted content to")
    args = parser.parse_args()

    tree = load_document_tree(args.input)
    paragraphs = paragraph_texts(tree)
    if args.format == "json":
        content = json.dumps({"paragraphs": paragraphs}, indent=2)
    elif args.format == "markdown":
        content = "\n\n".join(paragraphs)
    else:
        content = "\n".join(paragraphs)

    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
