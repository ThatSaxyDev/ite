from __future__ import annotations

import re
from pathlib import Path

LINE_RANGE_RE = re.compile(r"^(\d+)(?:\s*[:-]\s*(\d*))$")


def compact_description(description: str) -> str:
    """Truncate a tool description to its first sentence only."""
    if not description:
        return description
    first_sentence = description.split(". ", 1)[0]
    if first_sentence and not first_sentence.endswith("."):
        first_sentence += "."
    return first_sentence


def resolve_line_range(old_string: str, file_content: str) -> str | None:
    """Expand a line-range pattern like '55-64' to the actual text from file_content.

    Returns None if old_string is not a line-range pattern or if the range is invalid.
    """
    if not old_string.strip():
        return None

    match = LINE_RANGE_RE.match(old_string.strip())
    if not match:
        return None

    lines = file_content.split("\n")
    start_line = int(match.group(1))
    end_str = match.group(2)

    if end_str == "":
        end_line = len(lines)
    elif end_str is not None:
        end_line = int(end_str)
    else:
        end_line = start_line

    if start_line < 1 or end_line > len(lines) or start_line > end_line:
        return None

    return "\n".join(lines[start_line - 1 : end_line])


def compact_line_number_prefix(
    output: str, width: int = 4, sep: str = "|"
) -> str:
    """Reduce line-number prefix width, e.g. '     1|' -> '   1|'."""
    leading_re = re.compile(r"^(\s+)(\d+)\s*\|", re.MULTILINE)
    return leading_re.sub(
        lambda m: f"{int(m.group(2)):>{width}}{sep}", output
    )


def compact_read_header(output: str) -> str:
    """Replace verbose 'Showing lines X to Y of Z' header with a terse form."""
    return re.sub(
        r"Showing lines (\d+) to (\d+) of (\d+) \| {2}\n+",
        r"# \1-\2/\3\n\n",
        output,
    )


def compact_read_output(output: str, file_path: Path, cwd: Path) -> str:
    """Apply all read-output compactions: path relative, header, line numbers."""
    try:
        rel_path = str(file_path.resolve().relative_to(cwd.resolve()))
    except ValueError:
        rel_path = str(file_path)

    lines = output.split("\n", 1)
    if not lines:
        return output

    body = lines[1] if len(lines) > 1 else ""
    header = lines[0]

    if re.match(r"Showing lines", header):
        header = compact_read_header(header)

    body = compact_line_number_prefix(body)

    return f"{header}{body}"
