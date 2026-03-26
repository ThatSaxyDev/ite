from __future__ import annotations

import argparse
from pathlib import Path

from _docx_core import load_document_tree
from _docx_core import paragraph_texts
from _docx_core import set_paragraphs
from _docx_core import write_document_tree


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply direct string replacements inside a .docx document.")
    parser.add_argument("input", type=Path, help="Source .docx file")
    parser.add_argument("output", type=Path, help="Output .docx file")
    parser.add_argument(
        "--replace",
        nargs=2,
        metavar=("OLD", "NEW"),
        action="append",
        required=True,
        help="Pair of strings to replace in order",
    )
    args = parser.parse_args()

    tree = load_document_tree(args.input)
    paragraphs = paragraph_texts(tree)
    updated = list(paragraphs)
    for old, new in args.replace:
        updated = [paragraph.replace(old, new) for paragraph in updated]
    set_paragraphs(tree, updated)
    write_document_tree(args.input, args.output, tree)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
