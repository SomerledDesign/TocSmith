from __future__ import annotations

"""@file
@brief Command-line entry point for PDF analysis and bookmark generation.

The CLI exposes two main workflows:
- analyze a PDF and emit JSON describing OCR text, TOC candidates, extracted
  TOC entries, and bookmark coverage
- write a new PDF with conservatively generated outline items
"""

import argparse
import json
from pathlib import Path

from .finisher import DEFAULT_WATERMARK
from .pdfio import analyze_pdf_file
from .version import VERSION_LABEL
from .writer import write_bookmarks_for_pdf


def main() -> int:
    """@brief Parse CLI arguments and run the requested PDF workflow.

    When ``--write-bookmarks`` or ``--output`` is supplied, the command writes
    a new PDF and a decision log. Otherwise it analyzes the PDF and prints a
    JSON summary of the detected structure.

    @return Process exit status code.
    """
    parser = argparse.ArgumentParser(
        prog="tocsmith",
        description=(
            "Analyze a PDF for OCR text, TOC pages, bookmark coverage, "
            "and finished output."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"TocSmith {VERSION_LABEL}",
    )
    parser.add_argument("pdf", type=Path, help="Path to the PDF file")
    parser.add_argument(
        "--write-bookmarks",
        action="store_true",
        help=(
            "Write a new PDF with conservative bookmarks, crop marked "
            "oversized pages, and add the footer watermark."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Output path for bookmark writing. Supplying this implies "
            "--write-bookmarks. Defaults to <input>.bookmarked.pdf."
        ),
    )
    parser.add_argument(
        "--min-match-score",
        type=float,
        default=0.85,
        help="Minimum anchor match score required before writing a bookmark.",
    )
    parser.add_argument(
        "--watermark",
        default=DEFAULT_WATERMARK,
        help=(
            "Footer text added to generated pages. Defaults to 'TocSmith'; "
            "pass an empty string to disable it."
        ),
    )
    args = parser.parse_args()

    if args.write_bookmarks or args.output is not None:
        write_result = write_bookmarks_for_pdf(
            args.pdf,
            output_path=args.output,
            min_match_score=args.min_match_score,
            watermark=args.watermark,
        )
        payload = {
            "pdf": str(args.pdf),
            "output_path": write_result.output_path,
            "log_path": write_result.log_path,
            "written_count": write_result.written_count,
            "skipped_titles": write_result.skipped_titles,
            "cropped_page_count": write_result.cropped_page_count,
            "watermarked_page_count": write_result.watermarked_page_count,
        }
        print(json.dumps(payload, indent=2))
        return 0

    result = analyze_pdf_file(args.pdf)
    payload = {
        "pdf": str(args.pdf),
        "is_ocr_text_available": result.is_ocr_text_available,
        "toc_candidates": [
            {
                "page_index": candidate.page_index,
                "score": candidate.score,
                "matched_lines": candidate.matched_lines,
            }
            for candidate in result.toc_candidates
        ],
        "toc_entries": [
            {
                "title": entry.title,
                "printed_page": entry.printed_page,
                "level": entry.level,
                "anchor_page_index": entry.anchor_page_index,
                "anchor_match_score": entry.anchor_match_score,
            }
            for entry in result.toc_entries
        ],
        "bookmark_coverage": {
            "bookmark_titles": result.bookmark_coverage.bookmark_titles,
            "matched_titles": result.bookmark_coverage.matched_titles,
            "missing_titles": result.bookmark_coverage.missing_titles,
            "is_complete": result.bookmark_coverage.is_complete,
        },
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
