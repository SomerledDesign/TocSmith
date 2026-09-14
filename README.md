# TocSmith

Forge useful navigation into PDFs that shipped without it.

I like PDFs to include bookmarks. The problem is that manuals and books
downloaded from the web often have selectable text and a printed table of
contents, but no usable sidebar outline. TocSmith turns that existing structure
into a finished, navigable copy while leaving the source PDF untouched.

TocSmith can:

- detect an extractable PDF text layer
- locate likely table-of-contents pages
- extract major sections, subsections, and appendices
- resolve printed TOC entries to headings in the document
- generate a nested PDF sidebar outline
- crop oversized pages when credible crop marks identify the intended trim
- normalize rotated pages and add a configurable footer watermark
- write a human-readable decision log explaining every accepted or skipped item

The matching is deliberately conservative. A printed page number is not always
the physical PDF page number, so TocSmith prefers matching TOC text to heading
text on the destination page. If a PDF has no extractable text layer, TocSmith
stops instead of guessing; scan-only documents need OCR first.

## Quick start

TocSmith requires Python 3.9 or newer. On macOS or Linux, the repository
launcher creates a local virtual environment and installs the declared
dependency automatically on its first production run:

```sh
./tocsmith "/path/to/manual.pdf" --write-bookmarks
```

The command creates:

```text
manual.bookmarked.pdf
manual.bookmarked.pdf.log.txt
```

The original PDF is never modified. The first run needs internet access to
install `pypdf`; subsequent runs use the repository-local environment.

To prepare the environment explicitly:

```sh
./tocsmith --setup
```

To choose a footer without storing private tagging information in the source
repository:

```sh
./tocsmith "/path/to/manual.pdf" --write-bookmarks --watermark "My footer"
```

The neutral default watermark is `TocSmith`. Use `--watermark ""` to disable
the footer.

### Windows

From PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\tocsmith "C:\path\to\manual.pdf" --write-bookmarks
```

## Analysis-only mode

Without `--write-bookmarks` or `--output`, TocSmith prints a JSON analysis and
does not create a PDF:

```sh
./tocsmith "/path/to/manual.pdf"
```

Supplying `--output` implies bookmark writing:

```sh
./tocsmith input.pdf --output finished.pdf
```

## Design notes

This is a broad-range heuristic tool, not a collection of fixes tied to one
sample document. Real-world PDFs remain messy: text extraction can damage
ligatures, headings can be repeated, and TOC indentation is not always
reliable. TocSmith therefore records its decisions and skips uncertain entries
instead of knowingly creating misleading links.

The evolving design, completed milestones, and known weak spots live in
[`sketch.md`](sketch.md). Session continuity and verification status live in
[`handoff.md`](handoff.md).

## Versioning

TocSmith keeps a public release version and a separate cumulative build number:

- Release: **1.0**
- Build: **345**
- Display: **TocSmith 1.0 (345)**

The release version communicates compatibility. The build number preserves the
project's longer experimental lineage. Both values have a single source of
truth in `src/toc_bookmarks/version.py` and are available from the CLI:

```sh
./tocsmith --version
```

## Development

Run the complete test suite with:

```sh
.venv/bin/python -m unittest discover -s tests
```

