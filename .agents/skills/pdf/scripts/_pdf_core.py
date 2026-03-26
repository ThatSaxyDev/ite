from __future__ import annotations

from pathlib import Path
import re


def build_pdf(lines: list[str], title: str | None = None) -> bytes:
    content_lines = []
    y = 760
    if title:
        content_lines.append("BT /F1 18 Tf 72 760 Td ({}) Tj ET".format(_escape(title)))
        y = 732
    for line in lines:
        content_lines.append(f"BT /F1 12 Tf 72 {y} Td ({_escape(line)}) Tj ET")
        y -= 18
        if y < 72:
            break
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]

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


def _escape(value: str) -> str:
    cleaned = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return cleaned.encode("latin-1", errors="replace").decode("latin-1")


def _unescape(value: str) -> str:
    result = value.replace("\\)", ")").replace("\\(", "(").replace("\\\\", "\\")
    return result
