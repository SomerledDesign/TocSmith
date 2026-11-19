"""@file
@brief Regression tests for indirect, inherited and malformed page boxes.

TocSmith 1.1.0 crashed with ``AttributeError: 'NoneType' object has no
attribute 'get_object'`` when a source page stored its /MediaBox as an
indirect object: pypdf 6.18.1 resolves such boxes through ``page.pdf``, which
is ``None`` on pages copied into a ``PdfWriter``.
"""

import io
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject, RectangleObject

from toc_bookmarks import finisher
from toc_bookmarks.finisher import FinishStats, finish_pdf_pages, normalize_page_boxes
from toc_bookmarks.models import AnalysisResult, BookmarkCoverage
from toc_bookmarks.writer import _format_finish_issue_lines, write_bookmarks_for_pdf


def _indirect_box_pdf_bytes() -> bytes:
    """@brief Build a three-page PDF with indirect and inherited media boxes.

    Page 1 is Half Letter with a direct /MediaBox, page 2 is Letter with an
    indirect /MediaBox (like the LaserJet 6P service supplement), and page 3
    has no /MediaBox of its own and inherits an indirect Letter box from the
    /Pages root.
    """
    writer = PdfWriter()
    writer.add_blank_page(width=396, height=612)
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    pages = writer.pages
    pages[1][NameObject("/MediaBox")] = writer._add_object(
        RectangleObject((0, 0, 612, 792))
    )
    del pages[2][NameObject("/MediaBox")]
    root = writer._root_object["/Pages"].get_object()
    root[NameObject("/MediaBox")] = writer._add_object(RectangleObject((0, 0, 612, 792)))
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _copied_writer(data: bytes) -> PdfWriter:
    """@brief Copy a PDF into a fresh writer the same way writer.py does."""
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(data)), import_outline=False)
    return writer


class PageBoxTests(unittest.TestCase):
    def test_fixture_really_has_indirect_boxes(self) -> None:
        reader = PdfReader(io.BytesIO(_indirect_box_pdf_bytes()))
        raw = [dict.get(page, "/MediaBox") for page in reader.pages]
        self.assertEqual(type(raw[0]).__name__, "ArrayObject")
        self.assertEqual(type(raw[1]).__name__, "IndirectObject")
        # Page 3 inherits its box from /Pages; pypdf flattens it onto the page.
        self.assertEqual(tuple(float(v) for v in reader.pages[2].mediabox), (0, 0, 612, 792))

    def test_finishes_writer_pages_with_indirect_and_inherited_media_boxes(self) -> None:
        writer = _copied_writer(_indirect_box_pdf_bytes())
        stats = finish_pdf_pages(writer.pages, watermark="Somerled.Design")
        self.assertEqual(stats.skipped_pages, ())
        self.assertEqual(stats.box_notes, ())
        self.assertEqual(stats.watermarked_page_count, 3)
        self.assertEqual(stats.cropped_page_count, 0)

        buffer = io.BytesIO()
        writer.write(buffer)
        reread = PdfReader(io.BytesIO(buffer.getvalue()))
        self.assertEqual(len(reread.pages), 3)
        sizes = [tuple(float(v) for v in page.mediabox) for page in reread.pages]
        self.assertEqual(sizes, [(0, 0, 396, 612), (0, 0, 612, 792), (0, 0, 612, 792)])
        for page in reread.pages:
            self.assertIn("Somerled.Design", page.extract_text())

    def test_normalize_rewrites_indirect_box_as_direct_rectangle(self) -> None:
        writer = _copied_writer(_indirect_box_pdf_bytes())
        page = writer.pages[1]
        self.assertEqual(type(dict.get(page, "/MediaBox")).__name__, "IndirectObject")
        self.assertEqual(normalize_page_boxes(page), [])
        self.assertIsInstance(dict.get(page, "/MediaBox"), RectangleObject)
        self.assertEqual(tuple(float(v) for v in page.mediabox), (0, 0, 612, 792))

    def test_inherits_media_box_from_parent_when_page_has_none(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        page = writer.pages[0]
        del page[NameObject("/MediaBox")]
        root = writer._root_object["/Pages"].get_object()
        root[NameObject("/MediaBox")] = writer._add_object(RectangleObject((0, 0, 396, 612)))
        self.assertEqual(normalize_page_boxes(page), [])
        self.assertEqual(tuple(float(v) for v in page.mediabox), (0, 0, 396, 612))

    def test_missing_or_malformed_media_box_falls_back_to_letter(self) -> None:
        missing = PageObject.create_blank_page(width=200, height=200)
        del missing[NameObject("/MediaBox")]
        malformed = PageObject.create_blank_page(width=200, height=200)
        malformed[NameObject("/MediaBox")] = ArrayObject([FloatObject(0), FloatObject(0), FloatObject(10)])
        stats = finish_pdf_pages([missing, malformed])
        self.assertEqual(stats.skipped_pages, ())
        self.assertEqual(
            stats.box_notes,
            (
                (0, "missing /MediaBox; assumed US Letter"),
                (1, "invalid /MediaBox; assumed US Letter"),
            ),
        )
        for page in (missing, malformed):
            self.assertEqual(tuple(float(v) for v in page.mediabox), (0, 0, 612, 792))
            self.assertIn("TocSmith", page.extract_text())

    def test_invalid_optional_box_is_removed(self) -> None:
        page = PageObject.create_blank_page(width=612, height=792)
        page[NameObject("/CropBox")] = ArrayObject([FloatObject(5), FloatObject(5), FloatObject(5), FloatObject(5)])
        self.assertEqual(normalize_page_boxes(page), ["invalid /CropBox removed"])
        self.assertNotIn("/CropBox", page)
        self.assertEqual(tuple(float(v) for v in page.cropbox), (0, 0, 612, 792))

    def test_one_bad_page_is_skipped_with_a_warning(self) -> None:
        pages = [PageObject.create_blank_page(width=612, height=792) for _ in range(3)]
        real_watermark = finisher._add_footer_watermark

        def flaky(page, watermark):
            if page is pages[1]:
                raise AttributeError("'NoneType' object has no attribute 'get_object'")
            real_watermark(page, watermark)

        with mock.patch.object(finisher, "_add_footer_watermark", side_effect=flaky):
            with self.assertLogs("toc_bookmarks.finisher", level="WARNING") as logs:
                stats = finish_pdf_pages(pages)
        self.assertEqual(stats.watermarked_page_count, 2)
        self.assertEqual(
            stats.skipped_pages,
            ((1, "AttributeError: 'NoneType' object has no attribute 'get_object'"),),
        )
        self.assertIn("page 2", logs.output[0])
        self.assertIn("TocSmith", pages[0].extract_text())
        self.assertIn("TocSmith", pages[2].extract_text())

    def test_write_bookmarks_end_to_end_with_indirect_media_boxes(self) -> None:
        analysis = AnalysisResult(
            is_ocr_text_available=True,
            toc_entries=[],
            toc_candidates=[],
            bookmark_coverage=BookmarkCoverage([], [], []),
        )
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / "indirect.pdf"
            source.write_bytes(_indirect_box_pdf_bytes())
            output = pathlib.Path(folder) / "indirect-writ.pdf"
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                result = write_bookmarks_for_pdf(
                    source, output_path=output, watermark="Somerled.Design"
                )
            self.assertEqual(result.watermarked_page_count, 3)
            reread = PdfReader(str(output))
            self.assertEqual(len(reread.pages), 3)
            log_text = pathlib.Path(result.log_path).read_text(encoding="utf-8")
            self.assertNotIn("SKIP page", log_text)

    def test_finish_issue_log_lines(self) -> None:
        stats = FinishStats(1, 2, ((4, "ValueError: bad"),), ((0, "missing /MediaBox; assumed US Letter"),))
        self.assertEqual(
            _format_finish_issue_lines(stats),
            [
                "BOX page 1: missing /MediaBox; assumed US Letter",
                "Pages left unfinished: 1",
                "SKIP page 5: ValueError: bad",
            ],
        )
        self.assertEqual(_format_finish_issue_lines(FinishStats(0, 0)), [])


if __name__ == "__main__":
    unittest.main()
