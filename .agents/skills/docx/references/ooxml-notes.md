# OOXML notes

A `.docx` file is a ZIP package. The most important members for this skill are:

- `[Content_Types].xml`
- `_rels/.rels`
- `word/document.xml`

The first-party `ite` docx skill only guarantees safe handling of plain paragraph content in `word/document.xml`.
If the user needs advanced layout, section, comment, or tracked-change behavior, say that the request exceeds the current bundled workflow and avoid fabricating support.
