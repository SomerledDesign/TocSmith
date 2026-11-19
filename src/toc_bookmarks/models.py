"""@file
@brief Immutable data models shared across analysis and writing stages.

The project passes structured results between modules using frozen dataclasses
so the heuristic pipeline stays explicit and easy to inspect in tests.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class TocEntry:
    """@brief One extracted table-of-contents entry and its resolved metadata.

    The same object carries both the original TOC information and the later
    anchor-matching result used by the bookmark writer.
    """

    title: str
    printed_page: Optional[int] = None
    level: int = 1
    anchor_page_index: Optional[int] = None
    anchor_match_score: float = 0.0
    toc_page_index: Optional[int] = None
    toc_x: Optional[float] = None
    toc_y: Optional[float] = None
    toc_width: Optional[float] = None
    toc_height: Optional[float] = None
    toc_font_name: str = ""
    # Page-space (default user space) bounding box of the TOC row text as
    # (x0, y0, x1, y1), used for link annotations. ``None`` when unknown.
    toc_bbox: Optional[Tuple[float, float, float, float]] = None
    # Printed label as it appears in the contents (``7-4``, ``A-1``, ``iv``).
    # ``printed_page`` stays the integer value when the label is arabic or
    # roman; chapter-page labels have no single integer and leave it empty.
    printed_label: Optional[str] = None
    # PDF page index resolved from a footer or ``/PageLabels`` map. When set,
    # anchor matching keeps this page instead of guessing from heading text.
    resolved_page_index: Optional[int] = None


@dataclass(frozen=True)
class TocCandidate:
    """@brief A page that heuristically looks like part of the TOC."""

    page_index: int
    matched_lines: List[str] = field(default_factory=list)
    score: float = 0.0


@dataclass(frozen=True)
class TocLayoutLine:
    """@brief Extracted text line plus coarse layout/font metadata from a page."""

    text: str
    x: float
    y: float
    font_size: float = 0.0
    font_name: str = ""
    width: Optional[float] = None
    height: Optional[float] = None
    # Page-space bounding box (x0, y0, x1, y1) after applying the text and
    # current transformation matrices. ``x``/``y`` are page space when the
    # extractor could convert them, so a flipped text matrix still sorts
    # top-to-bottom. Callers that build lines directly may leave them in the
    # coordinate system they measured.
    bbox: Optional[Tuple[float, float, float, float]] = None
    # Media box of the source page, when the line came from a PDF. Thresholds
    # that used to assume one scanned manual's text space use these instead.
    page_width: Optional[float] = None
    page_height: Optional[float] = None


@dataclass(frozen=True)
class BookmarkCoverage:
    """@brief Comparison between existing PDF bookmarks and extracted TOC titles."""

    bookmark_titles: List[str]
    missing_titles: List[str]
    matched_titles: List[str]

    @property
    def is_complete(self) -> bool:
        """@brief Report whether every extracted TOC title has a bookmark match."""
        return not self.missing_titles


@dataclass(frozen=True)
class AnalysisResult:
    """@brief Top-level result returned by the PDF analysis pipeline."""

    is_ocr_text_available: bool
    toc_entries: List[TocEntry]
    toc_candidates: List[TocCandidate]
    bookmark_coverage: BookmarkCoverage


@dataclass(frozen=True)
class BookmarkWriteResult:
    """@brief Summary returned after writing a new PDF outline and log file."""

    output_path: str
    written_count: int
    log_path: str
    skipped_titles: List[str] = field(default_factory=list)
    cropped_page_count: int = 0
    watermarked_page_count: int = 0
    link_annotation_count: int = 0
    kept_bookmark_count: int = 0
    outline_mode: str = "replace"
