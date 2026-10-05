import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import builtins
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from toc_bookmarks.__main__ import main
from toc_bookmarks.pdfio import analyze_pdf_file


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakeOutlineItem:
    def __init__(self, title: str) -> None:
        self.title = title


class _FakeReader:
    def __init__(self, _: object) -> None:
        self.pages = [
            _FakePage("Cover"),
            _FakePage("Contents\nIntro ...... 1\nInstall ...... 3"),
        ]
        self.outline = [_FakeOutlineItem("Intro"), [_FakeOutlineItem("Install")]]


class PdfIoTests(unittest.TestCase):
    def test_analyze_pdf_file_uses_reader_content(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            with mock.patch("toc_bookmarks.pdfio._load_pdf_reader", return_value=_FakeReader):
                result = analyze_pdf_file(handle.name)
        self.assertTrue(result.is_ocr_text_available)
        self.assertEqual([entry.title for entry in result.toc_entries], ["Intro", "Install"])
        self.assertTrue(result.bookmark_coverage.is_complete)

    def test_main_prints_json_summary(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            with mock.patch("toc_bookmarks.pdfio._load_pdf_reader", return_value=_FakeReader):
                with mock.patch("sys.argv", ["toc_bookmarks", handle.name]):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        exit_code = main()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["is_ocr_text_available"])
        self.assertEqual(payload["bookmark_coverage"]["missing_titles"], [])
        self.assertIsNone(payload["toc_entries"][0]["anchor_page_index"])
        self.assertEqual(payload["toc_entries"][0]["anchor_match_score"], 0.0)

    def test_missing_dependency_raises_runtime_error(self) -> None:
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pypdf":
                raise ImportError("missing")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            from toc_bookmarks import pdfio

            with self.assertRaises(RuntimeError):
                pdfio._load_pdf_reader()

    def test_repo_root_module_runs_help(self) -> None:
        project_root = pathlib.Path(__file__).resolve().parents[1]
        command = [sys.executable, "-m", "toc_bookmarks", "--help"]
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Analyze a PDF", completed.stdout)
        self.assertIn("usage: tocsmith", completed.stdout)

    def test_repo_root_script_runs_help(self) -> None:
        project_root = pathlib.Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [str(project_root / "tocsmith"), "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Analyze a PDF", completed.stdout)

    def test_repo_root_script_bootstraps_local_environment(self) -> None:
        project_root = pathlib.Path(__file__).resolve().parents[1]
        script = (project_root / "tocsmith").read_text(encoding="utf-8")
        self.assertIn('venv_dir="${TOCSMITH_VENV:-$script_dir/.venv}"', script)
        self.assertIn('python3 -m venv "$venv_dir"', script)
        self.assertIn('"$venv_python" -m pip install -e .', script)
        self.assertIn("--setup", script)

    def test_repo_root_script_reports_version(self) -> None:
        project_root = pathlib.Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [str(project_root / "tocsmith"), "--version"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "TocSmith 1.1.0 (348)")

    def test_pyproject_declares_console_script(self) -> None:
        project_root = pathlib.Path(__file__).resolve().parents[1]
        pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[project.scripts]", pyproject)
        self.assertIn(
            'tocsmith = "toc_bookmarks.__main__:main"',
            pyproject,
        )

    def test_man_page_documents_the_public_cli(self) -> None:
        project_root = pathlib.Path(__file__).resolve().parents[1]
        man_page = (project_root / "docs" / "tocsmith.1").read_text(encoding="utf-8")
        self.assertIn('.TH TOCSMITH 1', man_page)
        self.assertIn('\\-\\-write-bookmarks', man_page)
        self.assertIn('\\-\\-watermark', man_page)
        self.assertIn('TocSmith 1.1.0 (348)', man_page)

    def test_group_spans_into_lines_estimates_width_and_height(self) -> None:
        from toc_bookmarks.pdfio import _group_spans_into_lines

        lines = _group_spans_into_lines(
            [
                {"text": "Intro", "x": 72.0, "y": 700.0, "font_size": 12.0, "font_name": "/Helv", "width": 30.0},
                {"text": "duction", "x": 102.0, "y": 700.0, "font_size": 12.0, "font_name": "/Helv", "width": 42.0},
            ]
        )
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].text, "Intro duction")
        self.assertEqual(lines[0].x, 72.0)
        self.assertEqual(lines[0].width, 72.0)
        self.assertEqual(lines[0].height, 12.0)

    def test_span_page_bbox_applies_ctm_scale(self) -> None:
        # Scanned page: text drawn at 300 dpi under a 72/300 CTM.
        from toc_bookmarks.pdfio import _span_page_bbox

        bbox = _span_page_bbox("Introduction", 33.6, (1, 0, 0, 1, 220.0, 2133.0), (0.24, 0, 0, 0.24, 0, 0))
        self.assertIsNotNone(bbox)
        x0, y0, x1, y1 = bbox
        self.assertAlmostEqual(x0, 52.8, places=1)
        self.assertAlmostEqual(y1 - y0, 33.6 * 0.24, places=2)
        self.assertTrue(y0 < 511.92 < y1)
        self.assertLess(x1, 464.0)

    def test_span_page_bbox_uses_text_matrix_font_scale(self) -> None:
        # Common producer pattern: Tf 1 with the real size carried in Tm.
        from toc_bookmarks.pdfio import _span_page_bbox

        bbox = _span_page_bbox("Overview", 1.0, (10.06, 0, 0, 10.06, 156.0, 640.8), (1, 0, 0, 1, 0, 0))
        self.assertIsNotNone(bbox)
        self.assertAlmostEqual(bbox[3] - bbox[1], 10.06, places=2)
        self.assertAlmostEqual(bbox[2] - bbox[0], 8 * 10.06 * 0.5, places=2)

    def test_span_page_bbox_skips_rotated_text(self) -> None:
        from toc_bookmarks.pdfio import _span_page_bbox

        self.assertIsNone(_span_page_bbox("Sideways", 10.0, (0, 1, -1, 0, 100.0, 100.0), (1, 0, 0, 1, 0, 0)))

    def test_group_spans_into_lines_unions_page_bboxes(self) -> None:
        from toc_bookmarks.pdfio import _group_spans_into_lines

        lines = _group_spans_into_lines(
            [
                {"text": "Intro", "x": 72.0, "y": 700.0, "font_size": 12.0, "font_name": "/Helv", "width": 30.0, "bbox": (18.0, 167.0, 25.0, 170.0)},
                {"text": "duction", "x": 102.0, "y": 700.0, "font_size": 12.0, "font_name": "/Helv", "width": 42.0, "bbox": (25.0, 166.0, 35.0, 171.0)},
            ]
        )
        self.assertEqual(lines[0].bbox, (18.0, 166.0, 35.0, 171.0))



if __name__ == "__main__":
    unittest.main()

