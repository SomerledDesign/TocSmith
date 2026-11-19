"""Regression tests for keeping an existing outline, metadata, and file size."""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

from toc_bookmarks.models import AnalysisResult, BookmarkCoverage, TocCandidate, TocEntry
from toc_bookmarks.writer import write_bookmarks_for_pdf


FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "SuperCalc_Manual.pdf"


def _outline_rows(reader: PdfReader):
    """Flatten an outline to (depth, title, page index) rows."""
    rows = []

    def walk(items, depth: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
                continue
            rows.append((depth, item.title, reader.get_destination_page_number(item)))

    walk(reader.outline, 0)
    return rows


def _tiny_outlined_pdf(path: pathlib.Path) -> None:
    """Write a two-page PDF with one bookmark and document info."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Tiny Manual", "/Author": "Tester"})
    writer._root_object[NameObject("/Lang")] = TextStringObject("en")
    writer.add_outline_item("Introduction", 0, is_open=True)
    with path.open("wb") as handle:
        writer.write(handle)


class OutlinePreservationTests(unittest.TestCase):
    def test_keep_merge_and_replace_on_a_pdf_that_already_has_bookmarks(self) -> None:
        analysis = AnalysisResult(
            is_ocr_text_available=True,
            toc_entries=[
                TocEntry(
                    title="Introduction",
                    level=1,
                    anchor_page_index=0,
                    anchor_match_score=1.0,
                ),
                TocEntry(
                    title="Installing the Tool",
                    level=2,
                    anchor_page_index=1,
                    anchor_match_score=0.95,
                ),
            ],
            toc_candidates=[TocCandidate(page_index=0)],
            bookmark_coverage=BookmarkCoverage([], [], []),
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "tiny.pdf"
            _tiny_outlined_pdf(source)
            from unittest import mock

            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                kept = write_bookmarks_for_pdf(
                    source,
                    output_path=pathlib.Path(tmp) / "kept.pdf",
                    watermark="",
                )
                merged = write_bookmarks_for_pdf(
                    source,
                    output_path=pathlib.Path(tmp) / "merged.pdf",
                    watermark="",
                    outline="merge",
                )
                replaced = write_bookmarks_for_pdf(
                    source,
                    output_path=pathlib.Path(tmp) / "replaced.pdf",
                    watermark="",
                    outline="replace",
                )

            kept_reader = PdfReader(kept.output_path)
            self.assertEqual(kept.outline_mode, "keep")
            self.assertEqual(kept.kept_bookmark_count, 1)
            self.assertEqual(kept.written_count, 0)
            self.assertEqual(
                [(depth, title) for depth, title, _page in _outline_rows(kept_reader)],
                [(0, "Introduction")],
            )
            self.assertEqual(kept_reader.metadata["/Title"], "Tiny Manual")
            self.assertEqual(kept_reader.metadata["/Author"], "Tester")
            self.assertEqual(str(kept_reader.root_object["/Lang"]), "en")
            kept_log = pathlib.Path(kept.log_path).read_text(encoding="utf-8")
            self.assertIn("Kept existing bookmarks: 1", kept_log)
            self.assertIn("Outline mode: keep", kept_log)

            merged_rows = _outline_rows(PdfReader(merged.output_path))
            self.assertEqual(
                [title for _depth, title, _page in merged_rows],
                ["Introduction", "Installing the Tool"],
            )
            self.assertEqual(merged.written_count, 1)
            self.assertEqual(merged_rows[1][0], 1)
            self.assertEqual(merged_rows[1][2], 1)

            replaced_rows = _outline_rows(PdfReader(replaced.output_path))
            self.assertEqual(
                [title for _depth, title, _page in replaced_rows],
                ["Introduction", "Installing the Tool"],
            )
            self.assertEqual(replaced.written_count, 2)
            self.assertEqual(replaced.kept_bookmark_count, 0)

    def test_supercalc_outline_metadata_and_watermark_size(self) -> None:
        """The owner's command must not replace the manual's outline or metadata."""
        self.assertTrue(FIXTURE.is_file(), f"missing fixture {FIXTURE}")
        source = PdfReader(str(FIXTURE))
        source_rows = _outline_rows(source)
        self.assertEqual(len(source_rows), 68)
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
            self.assertEqual(_outline_rows(written), source_rows)
            self.assertEqual(written.metadata["/Title"], source.metadata["/Title"])
            self.assertEqual(written.metadata["/Author"], source.metadata["/Author"])
            self.assertEqual(str(written.root_object["/Lang"]), str(source.root_object["/Lang"]))
            self.assertLess(output.stat().st_size, FIXTURE.stat().st_size * 1.3)
            log_text = pathlib.Path(result.log_path).read_text(encoding="utf-8")
            self.assertIn("Kept existing bookmarks: 68", log_text)
            self.assertIn("Somerled.Design", written.pages[0].extract_text() or "")


if __name__ == "__main__":
    unittest.main()
