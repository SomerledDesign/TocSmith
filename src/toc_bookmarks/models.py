"""@file
@brief Immutable data models shared across analysis and writing stages.

The project passes structured results between modules using frozen dataclasses
so the heuristic pipeline stays explicit and easy to inspect in tests.
"""

from dataclasses import dataclass, field
from typing import List, Optional


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
    toc_font_name: str = ""


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
