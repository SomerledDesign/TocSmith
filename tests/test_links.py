"""TOC link pass: rows link to existing bookmarks without replacing the outline."""

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link

from toc_bookmarks.analyzer import _normalize_title
from toc_bookmarks.models import AnalysisResult, BookmarkCoverage, TocCandidate, TocEntry
from toc_bookmarks.writer import write_bookmarks_for_pdf


FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "SuperCalc_Manual.pdf"

# Contents rows in reading order. ``page`` is the PDF page of the matching
# bookmark (chapter rows use the chapter-opening bookmark when the printed
# title is shorter than the outline title). ``toc`` is the contents page.
_SUPERCALC_ROWS = [
    ("Introduction", 4, 2, "chapter"),
    ("About SuperCalc", 4, 2, "section"),
    ("Conventions Used in This Manual", 5, 2, "section"),
    ("Chapter 1: Getting Started", 7, 2, "chapter"),
    ("Starting SuperCalc", 7, 2, "section"),
    ("The Screen", 8, 2, "section"),
    ("Your First Calculation", 8, 2, "section"),
    ("Correcting Entries", 9, 2, "section"),
    ("Leaving SuperCalc", 9, 2, "section"),
    ("Display Format", 10, 2, "section"),
    ("Chapter 2: Basic Operations", 11, 2, "chapter"),
    ("Arithmetic", 11, 2, "section"),
    ("Functions and Constants", 12, 2, "section"),
    ("Working in Degrees", 13, 2, "section"),
    ("Entering Numbers in Scientific Notation", 13, 2, "section"),
    ("Everyday Examples", 14, 2, "section"),
    ("Chapter 3: RPN and the Stack", 15, 2, "chapter"),
    ("RPN Entry", 15, 2, "section"),
    ("Stack Words", 16, 2, "section"),
    ("Statistics on a List", 17, 2, "section"),
    ("Chapter 4: Memory and Programs", 18, 2, "chapter"),
    ("Storing and Recalling Values", 18, 2, "section"),
    ("Short Programs", 19, 2, "section"),
    ("Finding a Root Numerically", 19, 2, "section"),
    ("Chapter 5: Graphing", 21, 2, "chapter"),
    ("Drawing a Graph", 21, 2, "section"),
    ("Reading the Plot Screen", 22, 2, "section"),
    ("Plot Examples", 23, 2, "section"),
    ("Chapter 6: 12C Mode", 24, 2, "chapter"),
    ("Opening 12C Mode", 24, 2, "section"),
    ("How the Story Sheets Work", 25, 2, "section"),
    ("Cash Flow Signs", 26, 2, "section"),
    ("Chapter 7: TVM and Savings", 27, 2, "chapter"),
    ("The TVM Sheet", 27, 2, "section"),
    ("TVM Example 1: A Loan Payment", 28, 2, "section"),
    ("TVM Example 2: Future Value", 29, 2, "section"),
    ("TVM Example 3: Rate and Term", 29, 2, "section"),
    ("The Savings Goal Sheet", 30, 2, "section"),
    ("Chapter 8: Loans and Mortgages", 31, 3, "chapter"),
    ("The Mortgage Sheet", 31, 3, "section"),
    ("The Amortization Table", 32, 3, "section"),
    ("The Loan Payoff Sheet", 33, 3, "section"),
    ("Chapter 9: Investments and Dates", 34, 3, "chapter"),
    ("The NPV / IRR Sheet", 34, 3, "section"),
    ("The Percent / APR Sheet", 35, 3, "section"),
    ("The Date Math Sheet", 36, 3, "section"),
    ("Chapter 10: Options", 37, 3, "chapter"),
    ("The Options Sheet", 37, 3, "section"),
    ("The Greeks", 38, 3, "section"),
    ("Implied Volatility", 39, 3, "section"),
    ("Using the Model Wisely", 39, 3, "section"),
    ("Chapter 11: Algebra (CAS)", 40, 3, "chapter"),
    ("About the Algebra Commands", 40, 3, "section"),
    ("Simplify, Expand and Factor", 41, 3, "section"),
    ("Derivatives and Integrals", 42, 3, "section"),
    ("Solving Equations", 43, 3, "section"),
    ("Series and Raw Eigenmath", 44, 3, "section"),
    ("Appendix A: Error Messages", 45, 3, "chapter"),
    ("Error Messages", 45, 3, "section"),
    ("Appendix B: Specifications", 48, 3, "chapter"),
    ("Specifications", 48, 3, "section"),
    ("About Precision", 49, 3, "section"),
    ("Appendix C: Troubleshooting", 50, 3, "chapter"),
    ("Troubleshooting", 50, 3, "section"),
    ("Appendix D: Command Summary", 52, 3, "chapter"),
    ("Command Summary", 52, 3, "section"),
    ("Index", 53, 3, "chapter"),
    ("Index", 53, 3, "section"),
]


def _analysis_for_rows() -> AnalysisResult:
    """Build TOC entries for the SuperCalc contents, one non-overlapping rect each."""
    slot = {2: 0, 3: 0}
    entries = []
    for title, page, toc_page, kind in _SUPERCALC_ROWS:
        index = slot[toc_page]
        slot[toc_page] += 1
        y = 530.0 - (index * 8.0)
        x = 36.0 if kind == "chapter" else 140.0
        entries.append(
            TocEntry(
                title=title,
                level=1 if kind == "chapter" else 2,
                anchor_page_index=page,
                anchor_match_score=1.0,
                toc_page_index=toc_page,
                toc_x=x,
                toc_y=y + 6.0,
                toc_width=90.0,
                toc_height=6.0,
                toc_bbox=(x, y, x + 90.0, y + 6.0),
            )
        )
    return AnalysisResult(
        is_ocr_text_available=True,
        toc_entries=entries,
        toc_candidates=[TocCandidate(page_index=2), TocCandidate(page_index=3)],
        bookmark_coverage=BookmarkCoverage([], [], []),
    )


def _outline_pages(reader: PdfReader):
    pages = {}

    def walk(items) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            pages.setdefault(_normalize_title(item.title), reader.get_destination_page_number(item))

    walk(reader.outline)
    return pages


def _link_records(reader: PdfReader):
    records = []
    for page_index, page in enumerate(reader.pages):
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if str(obj.get("/Subtype")) != "/Link":
                continue
            rect = tuple(float(value) for value in obj["/Rect"])
            records.append((page_index, rect, _link_target_page(reader, obj)))
    return records


def _link_target_page(reader: PdfReader, annotation) -> int:
    dest = annotation.get("/Dest")
    if dest is None and annotation.get("/A") is not None:
        action = annotation["/A"].get_object()
        dest = action.get("/D")
    dest = dest.get_object() if hasattr(dest, "get_object") else dest
    if isinstance(dest, str):
        named = reader.named_destinations[dest]
        return reader.get_destination_page_number(named)
    page_ref = dest[0]
    if hasattr(page_ref, "get_object"):
        page_ref = page_ref
    for index, page in enumerate(reader.pages):
        reference = page.indirect_reference
        if reference == page_ref or reference == getattr(page_ref, "indirect_reference", None):
            return index
    raise AssertionError(f"link destination {dest!r} did not match a page")


def _rects_overlap(first, second) -> bool:
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    return x1 > x0 and y1 > y0


class TocLinkTests(unittest.TestCase):
    def test_supercalc_links_every_section_and_chapter_row(self) -> None:
        sections = [row for row in _SUPERCALC_ROWS if row[3] == "section"]
        chapters = [row for row in _SUPERCALC_ROWS if row[3] == "chapter"]
        self.assertEqual(len(sections), 51)
        self.assertEqual(len(chapters), 17)
        source = PdfReader(str(FIXTURE))
        bookmark_pages = _outline_pages(source)
        analysis = _analysis_for_rows()
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "linked.pdf"
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                result = write_bookmarks_for_pdf(
                    FIXTURE,
                    output_path=output,
                    watermark="",
                )
            self.assertEqual(result.written_count, 0)
            self.assertEqual(result.kept_bookmark_count, 68)
            self.assertEqual(result.link_annotation_count, len(_SUPERCALC_ROWS))
            written = PdfReader(str(output))
            links = _link_records(written)
            self.assertEqual(len(links), len(_SUPERCALC_ROWS))
            for entry, row in zip(analysis.toc_entries, _SUPERCALC_ROWS):
                title, expected_page, toc_page, _kind = row
                matches = [
                    link
                    for link in links
                    if link[0] == toc_page and _rects_overlap(link[1], entry.toc_bbox)
                ]
                self.assertEqual(len(matches), 1, title)
                target = matches[0][2]
                bookmark_page = bookmark_pages.get(_normalize_title(title))
                if bookmark_page is not None:
                    self.assertEqual(target, bookmark_page, title)
                self.assertEqual(target, expected_page, title)

    def test_existing_link_is_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "linked.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            writer.add_blank_page(width=612, height=792)
            writer.add_outline_item("Introduction", 1)
            writer.add_annotation(
                0,
                Link(rect=(72, 700, 180, 712), target_page_index=1, border=[0, 0, 0]),
            )
            with source.open("wb") as handle:
                writer.write(handle)
            analysis = AnalysisResult(
                is_ocr_text_available=True,
                toc_entries=[
                    TocEntry(
                        title="Introduction",
                        level=1,
                        anchor_page_index=1,
                        anchor_match_score=1.0,
                        toc_page_index=0,
                        toc_bbox=(72, 700, 180, 712),
                    )
                ],
                toc_candidates=[TocCandidate(page_index=0)],
                bookmark_coverage=BookmarkCoverage([], [], []),
            )
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                result = write_bookmarks_for_pdf(
                    source,
                    output_path=pathlib.Path(tmp) / "out.pdf",
                    watermark="",
                )
            self.assertEqual(result.link_annotation_count, 0)
            links = _link_records(PdfReader(str(result.output_path)))
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0][2], 1)
            log_text = pathlib.Path(result.log_path).read_text(encoding="utf-8")
            self.assertIn("existing link already covers this TOC row", log_text)

    def test_no_links_flag_skips_annotations(self) -> None:
        analysis = _analysis_for_rows()
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "nolinks.pdf"
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                result = write_bookmarks_for_pdf(
                    FIXTURE,
                    output_path=output,
                    watermark="",
                    links=False,
                )
            self.assertEqual(result.link_annotation_count, 0)
            self.assertEqual(_link_records(PdfReader(str(output))), [])
            log_text = pathlib.Path(result.log_path).read_text(encoding="utf-8")
            self.assertIn("TOC link annotations disabled.", log_text)


if __name__ == "__main__":
    unittest.main()
