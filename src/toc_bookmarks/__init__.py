"""@file
@brief Public package surface for the TOC bookmark analysis toolkit.

This module re-exports the primary data models and entry points so callers can
import the package without reaching into internal modules.
"""

from .analyzer import analyze_pdf_features
from .models import (
    AnalysisResult,
    BookmarkCoverage,
    BookmarkWriteResult,
    TocLayoutLine,
    TocCandidate,
    TocEntry,
)
from .pdfio import analyze_pdf_file
from .version import BUILD_NUMBER, VERSION_LABEL, __version__
from .writer import write_bookmarks_for_pdf

#: Exported package symbols for analysis and bookmark-writing workflows.
__all__ = [
    "AnalysisResult",
    "BookmarkCoverage",
    "BookmarkWriteResult",
    "TocLayoutLine",
    "TocCandidate",
    "TocEntry",
    "BUILD_NUMBER",
    "VERSION_LABEL",
    "__version__",
    "analyze_pdf_features",
    "analyze_pdf_file",
    "write_bookmarks_for_pdf",
]
