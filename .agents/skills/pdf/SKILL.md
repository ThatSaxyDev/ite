---
name: pdf
description: Use when tasks involve reading, creating, or reviewing PDF files where rendering and layout matter; prefer visual checks by rendering pages and use the bundled helper scripts for generation, extraction, and inspection.
tags:
  - pdf
  - documents
  - layout
author: ite
argument-hint: "[INPUT=<path>] [OUTPUT=<path>]"
---

[//]: # (Modified from the Apache-licensed openai/skills pdf skill for iTE.)
[//]: # (Changes: workspace-local temp guidance plus bundled iTE helper scripts.)

# iTE PDF workflow

Use this skill whenever the user is working with PDF input or explicitly wants a PDF output artifact.

## Default workflows

### Inspect structure

```bash
python <skill_dir>/scripts/inspect_pdf.py input.pdf
python <skill_dir>/scripts/validate_pdf.py input.pdf
```

Prefer this before any deeper work so you know page count, file size, preview text, and basic structural status.

### Extract text

```bash
python <skill_dir>/scripts/extract_pdf_text.py input.pdf --output extracted.txt
```

This skill supports lightweight extraction. If the file uses complex embedded fonts, image-only pages, or scanned content, call out the limitation instead of pretending extraction is complete.

### Create a new PDF

```bash
python <skill_dir>/scripts/write_pdf.py draft.txt output.pdf --title "Status Update"
```

Templates in `templates/` are starter content. Use workspace-local drafts and outputs unless the user requests a different destination.

If you just need a quick starter document:

```bash
python <skill_dir>/scripts/write_pdf.py <skill_dir>/templates/report.txt output.pdf --title "Status Update"
```

### Render pages for review

```bash
python <skill_dir>/scripts/render_pdf.py input.pdf --output_dir ./.ite/tmp/pdf/job-123/rendered
```

This requires `pdftoppm` from Poppler. If it is missing, say so directly.

## Temp and output conventions

- Prefer a workspace-local scratch directory such as `./.ite/tmp/pdf/<job-id>/`.
- Keep the source PDF unchanged unless the user explicitly asks to overwrite it.
- Validate generated PDFs before presenting them as final.
- Resolve all script paths relative to this skill directory.

## Choosing the path

- Need to read a PDF: inspect, then extract text if useful.
- Need a fresh, simple PDF: write it from structured text.
- Need layout review: render pages and inspect them.
- Need stronger editing than this bundle supports: say so instead of pretending the PDF is easy to modify safely.

## Output expectations

- Tell the user which file was created or inspected.
- Mention whether rendering or validation succeeded.
- Call out any dependency gaps or fidelity limitations.
