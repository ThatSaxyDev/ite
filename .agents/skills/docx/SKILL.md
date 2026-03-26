---
name: docx
description: Create, inspect, edit, and validate Microsoft Word .docx documents. Use for reading .docx content, generating reports, memos, or letters as Word files, editing existing documents, and converting Word documents into structured text or a new polished .docx.
tags:
  - office
  - documents
  - word
author: ite
argument-hint: "[INPUT=<path>] [OUTPUT=<path>]"
---

# DOCX workflow

Use this skill whenever the user is working with a `.docx` file or explicitly wants a Word document as output.

## Core rules

- Do not use `read_file` directly on `.docx`; it is a packaged binary file.
- Resolve all script paths relative to this skill directory.
- Prefer a workspace-local scratch directory such as `./.ite/tmp/docx/<job-id>/` over `/tmp/`.
- Keep the source document intact unless the user explicitly asks to overwrite it.
- Validate any newly created or repacked `.docx` before presenting it as finished.
- If LibreOffice and Poppler are available, render pages for visual review before final delivery.

## Default workflows

### Inspect or extract text

Use the extractor first when the goal is to read or summarize a document:

```bash
python <skill_dir>/scripts/extract_docx.py input.docx --format markdown --output extracted.md
```

Use `--format text` for a plain transcript or `--format json` for machine-readable sections.

### Unpack for structured editing

```bash
python <skill_dir>/scripts/unpack_docx.py input.docx ./.ite/tmp/docx/job-123/unpacked
```

Edit the unpacked XML only when a simple text replacement is not enough.

### Simple text replacement

For straightforward content changes inside `word/document.xml`, use:

```bash
python <skill_dir>/scripts/replace_text.py input.docx output.docx --replace "Old text" "New text"
```

This is for direct text substitutions, not layout-heavy edits.

### Create a new document

For letters, memos, and simple reports, start from a markdown or text draft:

```bash
python <skill_dir>/scripts/write_docx.py draft.md output.docx --title "Quarterly Update"
```

Templates in `templates/` are starter content, not strict requirements.

### Visual review

When layout matters, render the document to page images:

```bash
python <skill_dir>/scripts/render_docx.py input.docx --output_dir ./.ite/tmp/docx/job-123/rendered
```

If the required system tools are unavailable, say so clearly and call out layout risk.

### Repack and validate

```bash
python <skill_dir>/scripts/pack_docx.py ./.ite/tmp/docx/job-123/unpacked output.docx
python <skill_dir>/scripts/validate_docx.py output.docx
```

Validation is required before presenting the result as complete.

## Choosing the path

- Need to read or summarize a `.docx`: extract text.
- Need a polished new `.docx`: write a new document from structured content.
- Need a small wording change: replace text.
- Need deeper changes: unpack, edit carefully, repack, validate.
- Need to check pagination, tables, or spacing: render the pages and inspect them.

## Output expectations

- Tell the user what file was created or updated.
- Summarize the structural approach used.
- Mention validation status.
- If a limitation blocks the requested formatting, say so explicitly instead of silently improvising.
