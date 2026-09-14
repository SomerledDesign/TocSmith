import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from toc_bookmarks.__main__ import main
from toc_bookmarks.models import AnalysisResult, BookmarkCoverage, TocCandidate, TocEntry
from toc_bookmarks.writer import write_bookmarks_for_pdf


class _FakeWriter:
    def __init__(self) -> None:
        self.append_calls = []
        self.outlines = []
        self.pages = []
        self.written = False

    def append(self, reader, import_outline=False):
        self.append_calls.append((reader, import_outline))

    def add_outline_item(self, title, page_number, parent=None, is_open=True):
        item = {
            "title": title,
            "page_number": page_number,
            "parent": parent,
            "is_open": is_open,
        }
        self.outlines.append(item)
        return item

    def write(self, handle):
        handle.write(b"%PDF-FAKE")
        self.written = True


class WriterTests(unittest.TestCase):
    def test_write_bookmarks_only_writes_confident_entries(self) -> None:
        analysis = AnalysisResult(
            is_ocr_text_available=True,
            toc_entries=[
                TocEntry(
                    title="Chapter 1 Getting Started",
                    level=1,
                    anchor_page_index=2,
                    anchor_match_score=0.95,
                ),
                TocEntry(
                    title="Index",
                    level=1,
                    anchor_page_index=10,
                    anchor_match_score=1.0,
                ),
                TocEntry(
                    title="Installing the Tool",
                    level=2,
                    anchor_page_index=5,
                    anchor_match_score=0.91,
                ),
            ],
            toc_candidates=[TocCandidate(page_index=1)],
            bookmark_coverage=BookmarkCoverage([], [], []),
        )
        fake_writer = _FakeWriter()
        with tempfile.NamedTemporaryFile(suffix=".pdf") as src:
            output_path = pathlib.Path(src.name).with_suffix(".bookmarked.pdf")
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                with mock.patch("toc_bookmarks.writer._open_pdf_reader", return_value=object()):
                    with mock.patch("toc_bookmarks.writer._create_writer", return_value=fake_writer):
                        result = write_bookmarks_for_pdf(src.name, output_path=output_path)

        self.assertEqual(result.written_count, 2)
        self.assertTrue(result.log_path.endswith(".log.txt"))
        self.assertEqual(result.skipped_titles, ["Index"])
        self.assertEqual([item["title"] for item in fake_writer.outlines], ["Chapter 1 Getting Started", "Installing the Tool"])
        self.assertIsNone(fake_writer.outlines[0]["parent"])
        self.assertEqual(fake_writer.outlines[1]["parent"]["title"], "Chapter 1 Getting Started")
        log_text = output_path.with_suffix(output_path.suffix + ".log.txt").read_text(encoding="utf-8")
        self.assertIn("WRITE | L1", log_text)
        self.assertIn("SKIP  | L1", log_text)
        self.assertIn("title failed confidence/readability checks", log_text)

    def test_child_entry_can_use_slightly_lower_threshold_under_accepted_parent(self) -> None:
        analysis = AnalysisResult(
            is_ocr_text_available=True,
            toc_entries=[
                TocEntry(
                    title="Setting Up DriveSpace",
                    level=2,
                    anchor_page_index=10,
                    anchor_match_score=1.0,
                ),
                TocEntry(
                    title="Using Express Setup",
                    level=3,
                    anchor_page_index=11,
                    anchor_match_score=0.82,
                ),
            ],
            toc_candidates=[TocCandidate(page_index=1)],
            bookmark_coverage=BookmarkCoverage([], [], []),
        )
        fake_writer = _FakeWriter()
        with tempfile.NamedTemporaryFile(suffix=".pdf") as src:
            output_path = pathlib.Path(src.name).with_suffix(".bookmarked.pdf")
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                with mock.patch("toc_bookmarks.writer._open_pdf_reader", return_value=object()):
                    with mock.patch("toc_bookmarks.writer._create_writer", return_value=fake_writer):
                        result = write_bookmarks_for_pdf(src.name, output_path=output_path)

        self.assertEqual(result.written_count, 2)
        self.assertEqual([item["title"] for item in fake_writer.outlines], ["Setting Up DriveSpace", "Using Express Setup"])
        log_text = output_path.with_suffix(output_path.suffix + ".log.txt").read_text(encoding="utf-8")
        self.assertIn("accepted via child threshold under accepted parent", log_text)

    def test_generic_parent_is_preserved_when_valid_children_depend_on_it(self) -> None:
        analysis = AnalysisResult(
            is_ocr_text_available=True,
            toc_entries=[
                TocEntry(
                    title="Chapter 7 / Hardware and Software",
                    level=1,
                    anchor_page_index=20,
                    anchor_match_score=0.96,
                ),
                TocEntry(
                    title="Hardware",
                    level=2,
                    anchor_page_index=21,
                    anchor_match_score=1.0,
                ),
                TocEntry(
                    title="The CPU",
                    level=3,
                    anchor_page_index=22,
                    anchor_match_score=1.0,
                ),
            ],
            toc_candidates=[TocCandidate(page_index=1)],
            bookmark_coverage=BookmarkCoverage([], [], []),
        )
        fake_writer = _FakeWriter()
        with tempfile.NamedTemporaryFile(suffix=".pdf") as src:
            output_path = pathlib.Path(src.name).with_suffix(".bookmarked.pdf")
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                with mock.patch("toc_bookmarks.writer._open_pdf_reader", return_value=object()):
                    with mock.patch("toc_bookmarks.writer._create_writer", return_value=fake_writer):
                        result = write_bookmarks_for_pdf(src.name, output_path=output_path)

        self.assertEqual(result.written_count, 3)
        self.assertEqual([item["title"] for item in fake_writer.outlines], ["Chapter 7 / Hardware and Software", "Hardware", "The CPU"])
        self.assertEqual(fake_writer.outlines[1]["parent"]["title"], "Chapter 7 / Hardware and Software")
        self.assertEqual(fake_writer.outlines[2]["parent"]["title"], "Hardware")
        log_text = output_path.with_suffix(output_path.suffix + ".log.txt").read_text(encoding="utf-8")
        self.assertIn("accepted as structural parent for valid descendants", log_text)

    def test_layout_verified_single_word_headings_are_written(self) -> None:
        analysis = AnalysisResult(
            is_ocr_text_available=True,
            toc_entries=[
                TocEntry(
                    title="Documentation and Software",
                    level=1,
                    anchor_page_index=10,
                    anchor_match_score=1.0,
                    toc_page_index=2,
                    toc_x=48,
                    toc_font_name="/Book-Bold",
                ),
                TocEntry(
                    title="Software",
                    level=2,
                    anchor_page_index=11,
                    anchor_match_score=1.0,
                    toc_page_index=2,
                    toc_x=60,
                    toc_font_name="/Book-Roman",
                ),
                TocEntry(
                    title="Index",
                    level=1,
                    anchor_page_index=20,
                    anchor_match_score=1.0,
                    toc_page_index=2,
                    toc_x=48,
                    toc_font_name="/Book-Bold",
                ),
            ],
            toc_candidates=[TocCandidate(page_index=2)],
            bookmark_coverage=BookmarkCoverage([], [], []),
        )
        fake_writer = _FakeWriter()
        with tempfile.NamedTemporaryFile(suffix=".pdf") as src:
            output_path = pathlib.Path(src.name).with_suffix(".bookmarked.pdf")
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                with mock.patch("toc_bookmarks.writer._open_pdf_reader", return_value=object()):
                    with mock.patch("toc_bookmarks.writer._create_writer", return_value=fake_writer):
                        result = write_bookmarks_for_pdf(src.name, output_path=output_path)

        self.assertEqual(result.written_count, 3)
        self.assertEqual(result.skipped_titles, [])
        self.assertEqual(
            [item["title"] for item in fake_writer.outlines],
            ["Documentation and Software", "Software", "Index"],
        )
        self.assertEqual(
            fake_writer.outlines[1]["parent"]["title"],
            "Documentation and Software",
        )

    def test_main_can_write_bookmarks(self) -> None:
        write_result = mock.Mock(
            output_path="/tmp/out.pdf",
            log_path="/tmp/out.pdf.log.txt",
            written_count=3,
            skipped_titles=["Index"],
            cropped_page_count=0,
            watermarked_page_count=10,
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            with mock.patch("toc_bookmarks.__main__.write_bookmarks_for_pdf", return_value=write_result):
                with mock.patch("sys.argv", ["toc_bookmarks", handle.name, "--write-bookmarks"]):
                    with mock.patch("sys.stdout.write") as stdout_write:
                        exit_code = main()

        payload = json.loads("".join(call.args[0] for call in stdout_write.call_args_list))
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["written_count"], 3)
        self.assertEqual(payload["log_path"], "/tmp/out.pdf.log.txt")
        self.assertEqual(payload["skipped_titles"], ["Index"])

    def test_main_output_path_implies_bookmark_writing(self) -> None:
        write_result = mock.Mock(
            output_path="/tmp/out.pdf",
            log_path="/tmp/out.pdf.log.txt",
            written_count=2,
            skipped_titles=[],
            cropped_page_count=0,
            watermarked_page_count=10,
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            with mock.patch("toc_bookmarks.__main__.write_bookmarks_for_pdf", return_value=write_result) as write_mock:
                with mock.patch("toc_bookmarks.__main__.analyze_pdf_file") as analyze_mock:
                    with mock.patch("sys.argv", ["toc_bookmarks", handle.name, "--output", "/tmp/out.pdf"]):
                        with mock.patch("sys.stdout.write") as stdout_write:
                            exit_code = main()

        payload = json.loads("".join(call.args[0] for call in stdout_write.call_args_list))
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["output_path"], "/tmp/out.pdf")
        self.assertEqual(payload["written_count"], 2)
        analyze_mock.assert_not_called()
        write_mock.assert_called_once()
        self.assertEqual(write_mock.call_args.kwargs["output_path"], pathlib.Path("/tmp/out.pdf"))

    def test_main_forwards_custom_watermark(self) -> None:
        write_result = mock.Mock(
            output_path="/tmp/out.pdf",
            log_path="/tmp/out.pdf.log.txt",
            written_count=1,
            skipped_titles=[],
            cropped_page_count=0,
            watermarked_page_count=1,
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            with mock.patch(
                "toc_bookmarks.__main__.write_bookmarks_for_pdf",
                return_value=write_result,
            ) as write_mock:
                with mock.patch(
                    "sys.argv",
                    ["tocsmith", handle.name, "--write-bookmarks", "--watermark", "Private footer"],
                ):
                    with mock.patch("sys.stdout.write"):
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(write_mock.call_args.kwargs["watermark"], "Private footer")

    def test_write_bookmarks_logs_when_no_toc_entries_are_detected(self) -> None:
        analysis = AnalysisResult(
            is_ocr_text_available=True,
            toc_entries=[],
            toc_candidates=[],
            bookmark_coverage=BookmarkCoverage([], [], []),
        )
        fake_writer = _FakeWriter()
        with tempfile.NamedTemporaryFile(suffix=".pdf") as src:
            output_path = pathlib.Path(src.name).with_suffix(".bookmarked.pdf")
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                with mock.patch("toc_bookmarks.writer._open_pdf_reader", return_value=object()):
                    with mock.patch("toc_bookmarks.writer._create_writer", return_value=fake_writer):
                        result = write_bookmarks_for_pdf(src.name, output_path=output_path)

        self.assertEqual(result.written_count, 0)
        log_text = output_path.with_suffix(output_path.suffix + ".log.txt").read_text(encoding="utf-8")
        self.assertIn("No TOC entries detected", log_text)

    def test_write_bookmarks_rejects_non_ocr_pdf(self) -> None:
        analysis = AnalysisResult(
            is_ocr_text_available=False,
            toc_entries=[],
            toc_candidates=[],
            bookmark_coverage=BookmarkCoverage([], [], []),
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf") as src:
            with mock.patch("toc_bookmarks.writer.analyze_pdf_file", return_value=analysis):
                with self.assertRaises(RuntimeError):
                    write_bookmarks_for_pdf(src.name)


if __name__ == "__main__":
    unittest.main()
