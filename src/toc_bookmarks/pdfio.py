from __future__ import annotations

"""@file
@brief File-backed PDF input helpers built on top of ``pypdf``.

This module is responsible for opening a PDF, extracting plain text, flattening
any existing outline titles, and collecting coarse page-layout lines that later
heuristics use for TOC and heading matching.
"""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .analyzer import analyze_pdf_features
from .models import AnalysisResult, TocLayoutLine


def analyze_pdf_file(pdf_path: str | Path) -> AnalysisResult:
    """@brief Analyze a PDF file directly from disk.

    @param pdf_path Filesystem path to the PDF that should be inspected.
    @return Structured analysis result containing OCR availability, TOC
        candidates, extracted entries, and bookmark coverage.
    """
    reader = _open_pdf_reader(pdf_path)
    page_texts = [page.extract_text() or "" for page in reader.pages]
    bookmark_titles = _collect_outline_titles(getattr(reader, "outline", []))
    page_layouts = _extract_page_layouts(reader, range(len(reader.pages)))
    toc_page_layouts = page_layouts
    return analyze_pdf_features(
        page_texts,
        bookmark_titles,
        toc_page_layouts=toc_page_layouts,
        page_layouts=page_layouts,
    )


def extract_pdf_content(pdf_path: str | Path) -> tuple[List[str], List[str]]:
    """@brief Extract just page text and outline titles from a PDF file.

    @param pdf_path Filesystem path to the PDF.
    @return Tuple of page-text strings and existing bookmark titles.
    """
    reader = _open_pdf_reader(pdf_path)
    page_texts = [page.extract_text() or "" for page in reader.pages]
    bookmark_titles = _collect_outline_titles(getattr(reader, "outline", []))
    return page_texts, bookmark_titles


def _open_pdf_reader(pdf_path: str | Path) -> Any:
    """@brief Construct a ``pypdf.PdfReader`` for the given path."""
    reader_type = _load_pdf_reader()
    path = Path(pdf_path)
    return reader_type(str(path))


def _load_pdf_reader() -> Any:
    """@brief Import and return the ``pypdf`` reader type.

    @return ``PdfReader`` class from ``pypdf``.
    @throw RuntimeError Raised when ``pypdf`` is not installed.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is required for PDF file analysis. Install dependencies first."
        ) from exc
    return PdfReader


def _collect_outline_titles(outline: Iterable[Any]) -> List[str]:
    """@brief Flatten a nested PDF outline tree into a list of bookmark titles.

    @param outline Sequence returned by ``pypdf`` for the document outline.
    @return Depth-first list of non-empty bookmark titles.
    """
    titles: List[str] = []
    for item in outline:
        if isinstance(item, list):
            titles.extend(_collect_outline_titles(item))
            continue
        title = getattr(item, "title", None)
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return titles


def _extract_toc_page_layouts(reader: Any, page_indexes: Iterable[int]) -> Dict[int, List[TocLayoutLine]]:
    """@brief Backward-compatible wrapper for extracting page layout lines."""
    return _extract_page_layouts(reader, page_indexes)


def _extract_page_layouts(reader: Any, page_indexes: Iterable[int]) -> Dict[int, List[TocLayoutLine]]:
    """@brief Extract grouped text-line layout data for the requested pages."""
    layouts: Dict[int, List[TocLayoutLine]] = {}
    for page_index in sorted(set(page_indexes)):
        try:
            layouts[page_index] = _extract_page_layout_lines(reader.pages[page_index])
        except TypeError:
            layouts[page_index] = []
    return layouts


def _extract_page_layout_lines(page: Any) -> List[TocLayoutLine]:
    """@brief Capture text spans from a page and group them into logical lines."""
    spans: List[Dict[str, Any]] = []

    def visitor(text: Any, _cm: Any, tm: Any, font_dict: Any, font_size: Any) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        spans.append(
            {
                "text": text.strip(),
                "x": float(tm[4]),
                "y": float(tm[5]),
                "font_size": float(font_size),
                "font_name": "" if font_dict is None else str(font_dict.get("/BaseFont", "")),
            }
        )

    page.extract_text(visitor_text=visitor)
    return _group_spans_into_lines(spans)


def _group_spans_into_lines(spans: List[Dict[str, Any]], y_tolerance: float = 2.5) -> List[TocLayoutLine]:
    """@brief Merge nearby text spans into top-to-bottom layout lines.

    Spans are grouped by similar Y coordinates and then joined left-to-right so
    later heuristics can reason about headings and TOC rows as line-sized units.

    @param spans Raw text spans captured from ``pypdf``.
    @param y_tolerance Maximum Y-distance for two spans to be treated as the
        same line.
    @return Ordered list of aggregated layout lines.
    """
    if not spans:
        return []
    spans = sorted(spans, key=lambda span: (-span["y"], span["x"]))
    groups: List[List[Dict[str, Any]]] = []
    for span in spans:
        if not groups or abs(groups[-1][0]["y"] - span["y"]) > y_tolerance:
            groups.append([span])
        else:
            groups[-1].append(span)

    lines: List[TocLayoutLine] = []
    for group in groups:
        group.sort(key=lambda span: span["x"])
        texts = [span["text"] for span in group]
        font_names = [span["font_name"] for span in group if span["font_name"]]
        font_sizes = [span["font_size"] for span in group if span["font_size"]]
        lines.append(
            TocLayoutLine(
                text=" ".join(texts),
                x=min(span["x"] for span in group),
                y=max(span["y"] for span in group),
                font_size=max(font_sizes) if font_sizes else 0.0,
                font_name=Counter(font_names).most_common(1)[0][0] if font_names else "",
            )
        )
    return lines
