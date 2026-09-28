from __future__ import annotations

from pathlib import Path
import re

PAGE_HEIGHT = 792
TOP_MARGIN = 760
BOTTOM_MARGIN = 72
LINE_HEIGHT = 18
TITLE_GAP = 28


def build_pdf(lines: list[str], title: str | None = None) -> bytes:
    pages: list[list[str]] = [[]]
    y = TOP_MARGIN
    if title:
        pages[-1].append("BT /F1 18 Tf 72 760 Td ({}) Tj ET".format(_escape(title)))
        y = TOP_MARGIN - TITLE_GAP
    for line in lines:
        if y < BOTTOM_MARGIN:
            pages.append([])
            y = TOP_MARGIN
        pages[-1].append(f"BT /F1 12 Tf 72 {y} Td ({_escape(line)}) Tj ET")
        y -= LINE_HEIGHT

    page_count_value = len(pages)
    font_obj = 3 + (page_count_value * 2)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
    ]
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(page_count_value))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count_value} >>".encode("ascii"))
    for index, page_lines in enumerate(pages):
        page_obj_num = 3 + index * 2
        contents_obj_num = page_obj_num + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 {PAGE_HEIGHT}] /Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {contents_obj_num} 0 R >>".encode(
                "ascii"
            )
        )
        stream = "\n".join(page_lines).encode("latin-1", errors="replace")
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    payload = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode("ascii"))
        payload.extend(obj)
        payload.extend(b"\nendobj\n")

    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(payload)


def basic_validate(path: Path) -> list[str]:
    errors: list[str] = []
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        errors.append("missing PDF header")
    if b"%%EOF" not in data[-64:]:
        errors.append("missing EOF marker near file end")
    if b"xref" not in data:
        errors.append("missing xref table")
    if page_count(path) <= 0:
        errors.append("no page objects detected")
    return errors


def extract_text(path: Path) -> str:
    data = path.read_bytes().decode("latin-1", errors="ignore")
    matches = re.findall(r"\((.*?)\)\s*Tj", data, flags=re.DOTALL)
    cleaned = [_unescape(match) for match in matches]
    return "\n".join(item for item in cleaned if item.strip())


def page_count(path: Path) -> int:
    data = path.read_bytes().decode("latin-1", errors="ignore")
    count = len(re.findall(r"/Type /Page\b", data))
    return max(0, count)


def inspect_pdf(path: Path) -> dict[str, object]:
    text_preview = extract_text(path).splitlines()[:5]
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "page_count": page_count(path),
        "validation_errors": basic_validate(path),
        "preview": text_preview,
    }


def _escape(value: str) -> str:
    cleaned = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return cleaned.encode("latin-1", errors="replace").decode("latin-1")


def _unescape(value: str) -> str:
    result = value.replace("\\)", ")").replace("\\(", "(").replace("\\\\", "\\")
    return result
