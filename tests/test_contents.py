"""Contents reading: column layout, chapter-page labels, and the SuperCalc fixture."""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pypdf import PdfReader

from toc_bookmarks.analyzer import analyze_pdf_features
from toc_bookmarks.pdfio import analyze_pdf_file
from toc_bookmarks.writer import write_bookmarks_for_pdf
from test_links import FIXTURE, _SUPERCALC_ROWS, _link_records, _rects_overlap


class ContentsReaderTests(unittest.TestCase):
    def test_page_labels_resolve_chapter_and_roman_pages(self) -> None:
        pages = [
            "Contents\nPreface ...... iii\nStart ...... 1-1",
            "not the preface",
            "Preface\nBody",
            "between",
            "Start\nBody",
        ]
        result = analyze_pdf_features(
            pages,
            [],
            explicit_page_labels=["i", "ii", "iii", "iv", "1-1"],
        )
        self.assertEqual([entry.title for entry in result.toc_entries], ["Preface", "Start"])
        self.assertEqual([entry.anchor_page_index for entry in result.toc_entries], [2, 4])
        self.assertEqual([entry.printed_label for entry in result.toc_entries], ["iii", "1-1"])

    def test_supercalc_contents_are_extracted_in_order(self) -> None:
        result = analyze_pdf_file(FIXTURE)
        self.assertEqual([candidate.page_index for candidate in result.toc_candidates], [2, 3])
        expected = [
            (title, page, 1 if kind == "chapter" else 2)
            for title, page, _toc_page, kind in _SUPERCALC_ROWS
        ]
        actual = [
            (entry.title, entry.anchor_page_index, entry.level) for entry in result.toc_entries
        ]
        self.assertEqual(actual, expected)
        sections = [row for row in _SUPERCALC_ROWS if row[3] == "section"]
        chapters = [row for row in _SUPERCALC_ROWS if row[3] == "chapter"]
        self.assertEqual(len(sections), 51)
        self.assertEqual(len(chapters), 17)

    def test_owner_command_links_the_real_contents(self) -> None:
        """The reported command keeps the outline and links every contents row."""
        source = PdfReader(str(FIXTURE))
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "SCM-writ.pdf"
            result = write_bookmarks_for_pdf(
                FIXTURE,
                output_path=output,
                watermark="Somerled.Design",
            )
            written = PdfReader(str(output))
            self.assertEqual(result.outline_mode, "keep")
            self.assertEqual(result.kept_bookmark_count, 68)
            self.assertEqual(result.written_count, 0)
            self.assertEqual(result.link_annotation_count, 68)
            self.assertLess(output.stat().st_size, FIXTURE.stat().st_size * 1.3)
            self.assertEqual(len(written.named_destinations), len(source.named_destinations))
            analysis = analyze_pdf_file(FIXTURE)
            links = _link_records(written)
            self.assertEqual(len(links), 68)
            for entry in analysis.toc_entries:
                matches = [
                    link
                    for link in links
                    if link[0] == entry.toc_page_index
                    and entry.toc_bbox is not None
                    and _rects_overlap(link[1], entry.toc_bbox)
                ]
                self.assertEqual(len(matches), 1, entry.title)
                self.assertEqual(matches[0][2], entry.anchor_page_index, entry.title)


if __name__ == "__main__":
    unittest.main()
