---
name: pdf
description: Create, inspect, extract, render, and validate PDF files. Use for reading PDFs, generating polished PDF outputs, checking page count or structure, and reviewing rendered pages when layout matters.
tags:
  - pdf
  - documents
  - layout
author: ite
argument-hint: "[INPUT=<path>] [OUTPUT=<path>]"
---

# PDF workflow

Use this skill whenever the user is working with PDF input or explicitly wants a PDF output artifact.

## Core rules

- Prefer rendered page review when layout matters.
- Resolve all script paths relative to this skill directory.
- Prefer a workspace-local scratch directory such as `./.ite/tmp/pdf/<job-id>/`.
- Keep the source PDF unchanged unless the user explicitly asks to overwrite it.
- Validate generated PDFs before presenting them as final.

## Default workflows

### Inspect structure

```bash
python <skill_dir>/scripts/inspect_pdf.py input.pdf
python <skill_dir>/scripts/validate_pdf.py input.pdf
```

### Extract text

```bash
python <skill_dir>/scripts/extract_pdf_text.py input.pdf --output extracted.txt
```

This skill supports lightweight extraction. If the file uses complex embedded fonts or scanned pages, call out the limitation.

### Create a new PDF

```bash
python <skill_dir>/scripts/write_pdf.py draft.txt output.pdf --title "Status Update"
```

Templates in `templates/` are starter content.

If you just need a quick starter document:

```bash
python <skill_dir>/scripts/write_pdf.py <skill_dir>/templates/report.txt output.pdf --title "Status Update"
```

### Render pages for review

```bash
python <skill_dir>/scripts/render_pdf.py input.pdf --output_dir ./.ite/tmp/pdf/job-123/rendered
```

This requires `pdftoppm` from Poppler. If it is missing, say so directly.

## Choosing the path

- Need to read a PDF: inspect, then extract text if useful.
- Need a fresh, simple PDF: write it from structured text.
- Need layout review: render pages and inspect them.
- Need stronger editing than this bundle supports: say so instead of pretending the PDF is easy to modify safely.

## Output expectations

- Tell the user which file was created or inspected.
- Mention whether rendering or validation succeeded.
- Call out any dependency gaps or fidelity limitations.
