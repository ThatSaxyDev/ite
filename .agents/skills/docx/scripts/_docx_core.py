from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED
from zipfile import ZipFile
import shutil
import tempfile
import xml.etree.ElementTree as ET
import json

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
ET.register_namespace("w", W_NS)

REQUIRED_MEMBERS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
}


def load_document_tree(docx_path: Path) -> ET.ElementTree:
    with ZipFile(docx_path) as archive:
        with archive.open("word/document.xml") as handle:
            return ET.parse(handle)


def write_document_tree(source_docx: Path, output_docx: Path, tree: ET.ElementTree) -> None:
    with tempfile.TemporaryDirectory(prefix="ite-docx-") as temp_dir:
        temp_root = Path(temp_dir)
        unpack_to_directory(source_docx, temp_root)
        document_path = temp_root / "word" / "document.xml"
        tree.write(document_path, encoding="utf-8", xml_declaration=True)
        pack_directory(temp_root, output_docx)


def unpack_to_directory(docx_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(docx_path) as archive:
        archive.extractall(output_dir)


def pack_directory(source_dir: Path, output_docx: Path) -> None:
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_docx.with_suffix(output_docx.suffix + ".tmp")
    if temp_output.exists():
        temp_output.unlink()
    with ZipFile(temp_output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            archive.write(path, path.relative_to(source_dir).as_posix())
    shutil.move(str(temp_output), str(output_docx))


def paragraph_texts(tree: ET.ElementTree) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in tree.findall(".//w:body/w:p", NS):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", NS)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return paragraphs


def inspect_docx(path: Path) -> dict[str, object]:
    tree = load_document_tree(path)
    paragraphs = paragraph_texts(tree)
    preview = paragraphs[:5]
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "paragraph_count": len(paragraphs),
        "preview": preview,
        "validation_errors": validate_docx(path),
    }


def set_paragraphs(tree: ET.ElementTree, paragraphs: list[str]) -> ET.ElementTree:
    root = tree.getroot()
    body = root.find("w:body", NS)
    if body is None:
        raise ValueError("word/document.xml does not contain w:body")

    sect_pr = body.find("w:sectPr", NS)
    for child in list(body):
        body.remove(child)

    for text in paragraphs:
        body.append(_paragraph_element(text))

    if sect_pr is not None:
        body.append(sect_pr)
    return tree


def replace_in_paragraphs(
    paragraphs: list[str],
    replacements: list[tuple[str, str]],
) -> tuple[list[str], int]:
    updated = list(paragraphs)
    total_replacements = 0
    for old, new in replacements:
        next_paragraphs: list[str] = []
        for paragraph in updated:
            occurrences = paragraph.count(old)
            if occurrences:
                total_replacements += occurrences
            next_paragraphs.append(paragraph.replace(old, new))
        updated = next_paragraphs
    return updated, total_replacements


def json_dump(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2)


def build_simple_document(paragraphs: list[str], title: str | None = None) -> bytes:
    document = ET.Element(f"{{{W_NS}}}document")
    body = ET.SubElement(document, f"{{{W_NS}}}body")
    all_paragraphs = list(paragraphs)
    if title:
        all_paragraphs.insert(0, title.strip())
    for paragraph in all_paragraphs:
        body.append(_paragraph_element(paragraph))
    sect_pr = ET.SubElement(body, f"{{{W_NS}}}sectPr")
    pg_sz = ET.SubElement(sect_pr, f"{{{W_NS}}}pgSz")
    pg_sz.set(f"{{{W_NS}}}w", "12240")
    pg_sz.set(f"{{{W_NS}}}h", "15840")
    pg_mar = ET.SubElement(sect_pr, f"{{{W_NS}}}pgMar")
    for key, value in {
        "top": "1440",
        "right": "1440",
        "bottom": "1440",
        "left": "1440",
        "header": "720",
        "footer": "720",
        "gutter": "0",
    }.items():
        pg_mar.set(f"{{{W_NS}}}{key}", value)

    document_xml = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    return _package_document_xml(document_xml)


def _package_document_xml(document_xml: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="ite-docx-build-") as temp_dir:
        root = Path(temp_dir)
        (root / "_rels").mkdir(parents=True, exist_ok=True)
        (root / "word").mkdir(parents=True, exist_ok=True)
        (root / "[Content_Types].xml").write_text(
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
""",
            encoding="utf-8",
        )
        (root / "_rels" / ".rels").write_text(
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
""",
            encoding="utf-8",
        )
        (root / "word" / "document.xml").write_bytes(document_xml)
        (root / "docProps").mkdir(parents=True, exist_ok=True)
        (root / "docProps" / "core.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>ite document</dc:title>
  <dc:creator>ite</dc:creator>
</cp:coreProperties>
""",
            encoding="utf-8",
        )
        (root / "docProps" / "app.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>ite</Application>
</Properties>
""",
            encoding="utf-8",
        )
        output = root / "out.docx"
        pack_directory(root, output)
        return output.read_bytes()


def validate_docx(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with ZipFile(path) as archive:
            members = set(archive.namelist())
            missing = REQUIRED_MEMBERS - members
            if missing:
                errors.append(f"missing required members: {', '.join(sorted(missing))}")
            for member in sorted(REQUIRED_MEMBERS & members):
                with archive.open(member) as handle:
                    try:
                        ET.parse(handle)
                    except ET.ParseError as exc:
                        errors.append(f"{member}: invalid XML ({exc})")
    except Exception as exc:
        errors.append(str(exc))
    return errors


def _paragraph_element(text: str) -> ET.Element:
    paragraph = ET.Element(f"{{{W_NS}}}p")
    run = ET.SubElement(paragraph, f"{{{W_NS}}}r")
    text_node = ET.SubElement(run, f"{{{W_NS}}}t")
    if text.startswith(" ") or text.endswith(" "):
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_node.text = text
    return paragraph
