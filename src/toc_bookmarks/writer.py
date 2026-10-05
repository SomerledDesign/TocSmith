from __future__ import annotations

"""@file
@brief Conservative PDF bookmark writer built on top of analysis results.

The writer only emits outline items for TOC entries whose anchors and titles
pass confidence checks. It then applies the page finishing pass and writes a
human-readable log describing bookmark and finishing decisions.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .analyzer import is_confident_bookmark_candidate
from .finisher import DEFAULT_WATERMARK, finish_pdf_pages
from .models import BookmarkWriteResult, TocEntry
from .pdfio import _open_pdf_reader, analyze_pdf_file


def write_bookmarks_for_pdf(
    input_path: str | Path,
    output_path: str | Path | None = None,
    min_match_score: float = 0.85,
    watermark: str = DEFAULT_WATERMARK,
) -> BookmarkWriteResult:
    """@brief Analyze a PDF and write a new copy with generated bookmarks.

    @param input_path Source PDF path.
    @param output_path Optional destination path for the new bookmarked PDF.
    @param min_match_score Minimum score required for a root-level anchor to be
        accepted.
    @param watermark Footer text applied to output pages; an empty value
        disables watermarking.
    @return Summary of the created PDF, log file, and skipped titles.
    @throw RuntimeError Raised when the PDF lacks extractable text.
    """
    input_file = Path(input_path)
    destination = Path(output_path) if output_path else input_file.with_name(
        input_file.stem + ".bookmarked.pdf"
    )
    log_path = destination.with_suffix(destination.suffix + ".log.txt")

    analysis = analyze_pdf_file(input_file)
    if not analysis.is_ocr_text_available:
        raise RuntimeError("PDF does not appear to contain extractable text. Skipping.")

    reader = _open_pdf_reader(input_file)
    writer = _create_writer()
    writer.append(reader, import_outline=False)

    parent_by_level: Dict[int, Any] = {}
    accepted_entry_by_level: Dict[int, TocEntry] = {}
    written_count = 0
    link_annotation_count = 0
    skipped_titles: List[str] = []
    pending_link_entries: List[TocEntry] = []
    log_lines = [
        f"Input PDF: {input_file}",
        f"Output PDF: {destination}",
        f"Minimum root match score: {min_match_score:.2f}",
        "",
        "Decisions:",
    ]
    if not analysis.toc_entries:
        log_lines.append("No TOC entries detected; output PDF copied without generated bookmarks.")

    for entry in analysis.toc_entries:
        decision = _evaluate_entry(
            analysis.toc_entries,
            entry,
            min_match_score,
            accepted_entry_by_level,
        )
        if not decision["write"]:
            skipped_titles.append(entry.title)
            log_lines.append(_format_log_line(entry, decision))
            continue
        parent = _nearest_parent(parent_by_level, entry.level)
        outline_item = writer.add_outline_item(
            entry.title,
            entry.anchor_page_index,
            parent=parent,
            is_open=True,
        )
        parent_by_level[entry.level] = outline_item
        accepted_entry_by_level[entry.level] = entry
        _clear_deeper_levels(parent_by_level, entry.level)
        _clear_deeper_levels(accepted_entry_by_level, entry.level)
        written_count += 1
        pending_link_entries.append(entry)
        log_lines.append(_format_log_line(entry, decision))

    finish_stats = finish_pdf_pages(writer.pages, watermark=watermark)
    link_log_lines: List[str] = []
    for entry in pending_link_entries:
        link_decision = _try_add_toc_link_annotation(writer, entry)
        if link_decision["linked"]:
            link_annotation_count += 1
        link_log_lines.append(_format_link_log_line(entry, link_decision))

    log_lines.extend(["", "TOC link annotations:"])
    if link_log_lines:
        log_lines.extend(link_log_lines)
    else:
        log_lines.append("No bookmark entries were eligible for TOC link annotations.")
    log_lines.extend(
        [
            "",
            "Finishing:",
            f"Cropped oversized pages: {finish_stats.cropped_page_count}",
            f"Watermarked pages: {finish_stats.watermarked_page_count}",
            f"TOC link annotations: {link_annotation_count}",
        ]
    )
    with destination.open("wb") as handle:
        writer.write(handle)
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    return BookmarkWriteResult(
        output_path=str(destination),
        written_count=written_count,
        log_path=str(log_path),
        skipped_titles=skipped_titles,
        cropped_page_count=finish_stats.cropped_page_count,
        watermarked_page_count=finish_stats.watermarked_page_count,
        link_annotation_count=link_annotation_count,
    )


def _evaluate_entry(
    toc_entries: List[TocEntry],
    entry: TocEntry,
    min_match_score: float,
    accepted_entry_by_level: Dict[int, TocEntry],
) -> Dict[str, Any]:
    """@brief Decide whether a TOC entry is safe enough to write as a bookmark.

    The decision combines anchor confidence, title readability, and limited
    structural preservation for parent nodes that hold valid descendants.
    """
    threshold = min_match_score
    reason = "root threshold"
    if entry.level >= 3 and accepted_entry_by_level.get(entry.level - 1):
        threshold = max(0.8, min_match_score - 0.05)
        reason = "child threshold under accepted parent"
    if entry.anchor_page_index is None:
        return {
            "write": False,
            "threshold": threshold,
            "reason": "missing anchor page",
        }
    if entry.anchor_match_score < threshold:
        return {
            "write": False,
            "threshold": threshold,
            "reason": f"match score {entry.anchor_match_score:.2f} below threshold via {reason}",
        }
    if not is_confident_bookmark_candidate(entry, threshold=threshold):
        if _is_layout_verified_single_word_entry(entry, accepted_entry_by_level):
            return {
                "write": True,
                "threshold": threshold,
                "reason": "accepted as layout-verified exact heading",
            }
        if _should_preserve_parent_entry(toc_entries, entry, threshold):
            return {
                "write": True,
                "threshold": threshold,
                "reason": "accepted as structural parent for valid descendants",
            }
        return {
            "write": False,
            "threshold": threshold,
            "reason": "title failed confidence/readability checks",
        }
    return {
        "write": True,
        "threshold": threshold,
        "reason": f"accepted via {reason}",
    }


def _is_layout_verified_single_word_entry(
    entry: TocEntry,
    accepted_entry_by_level: Dict[int, TocEntry],
) -> bool:
    """@brief Accept an exact one-word heading when TOC structure confirms it."""
    words = re.findall(r"[A-Za-z0-9]+", entry.title)
    if len(words) != 1 or entry.anchor_match_score < 0.98:
        return False
    if entry.toc_page_index is None or entry.toc_x is None or not entry.toc_font_name:
        return False
    is_bold = "Bold" in entry.toc_font_name
    if entry.level == 1:
        return is_bold
    return not is_bold and entry.level - 1 in accepted_entry_by_level


def _nearest_parent(parent_by_level: Dict[int, Any], level: int) -> Any:
    """@brief Return the deepest accepted outline item shallower than ``level``.

    TOC levels can skip (for example a chapter at level 1 followed directly
    by level-3 sections when the layout pass assigns an indentation band), so
    looking only at ``level - 1`` would detach those children to the root and
    flatten the outline. Walking up to the nearest shallower ancestor keeps the
    hierarchy intact.
    """
    shallower = [key for key in parent_by_level if key < level]
    if not shallower:
        return None
    return parent_by_level[max(shallower)]


def _clear_deeper_levels(level_map: Dict[int, Any], level: int) -> None:
    """@brief Drop cached parent state deeper than the current outline level."""
    for key in list(level_map):
        if key > level:
            del level_map[key]


def _should_preserve_parent_entry(
    toc_entries: List[TocEntry],
    entry: TocEntry,
    threshold: float,
) -> bool:
    """@brief Keep a generic parent entry when it anchors accepted children.

    @param toc_entries Full ordered TOC entry list.
    @param entry Candidate parent entry being evaluated.
    @param threshold Required anchor threshold for this entry.
    @return ``True`` when the entry should be written to preserve a valid
        subtree, otherwise ``False``.
    """
    if entry.anchor_page_index is None or entry.anchor_match_score < threshold:
        return False
    if entry.level < 2:
        return False
    try:
        index = toc_entries.index(entry)
    except ValueError:
        return False
    for candidate in toc_entries[index + 1 :]:
        if candidate.level <= entry.level:
            break
        child_threshold = threshold
        if candidate.level >= 3:
            child_threshold = max(0.8, threshold - 0.05)
        if candidate.anchor_page_index is None or candidate.anchor_match_score < child_threshold:
            continue
        if is_confident_bookmark_candidate(candidate, threshold=child_threshold):
            return True
    return False


def _create_writer() -> Any:
    """@brief Import and instantiate ``pypdf.PdfWriter``."""
    try:
        from pypdf import PdfWriter
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is required for PDF bookmark writing. Install dependencies first."
        ) from exc
    return PdfWriter()


def _format_log_line(entry: TocEntry, decision: Dict[str, Any]) -> str:
    """@brief Format one human-readable log line for a write/skip decision."""
    outcome = "WRITE" if decision["write"] else "SKIP "
    printed = "?" if entry.printed_page is None else str(entry.printed_page)
    anchor = "?" if entry.anchor_page_index is None else str(entry.anchor_page_index)
    return (
        f"{outcome} | L{entry.level} | printed={printed} | anchor={anchor} | "
        f"score={entry.anchor_match_score:.2f} | threshold={decision['threshold']:.2f} | "
        f"{entry.title} | {decision['reason']}"
    )

def _try_add_toc_link_annotation(writer: Any, entry: TocEntry) -> Dict[str, Any]:
    """@brief Place a conservative in-page TOC link annotation when geometry is clear.

    Uncertain cases are skipped: missing TOC page/rectangle, missing destination,
    out-of-range page indexes, or a writer that cannot accept annotations.
    """
    rect = _toc_link_rectangle(entry)
    if rect is None:
        return {
            "linked": False,
            "reason": "missing or uncertain TOC text rectangle",
        }
    if entry.toc_page_index is None or entry.anchor_page_index is None:
        return {
            "linked": False,
            "reason": "missing TOC page or destination",
        }
    pages = getattr(writer, "pages", None)
    page_count = len(pages) if pages is not None else 0
    if page_count:
        if not (0 <= entry.toc_page_index < page_count):
            return {
                "linked": False,
                "reason": f"TOC page index {entry.toc_page_index} out of range",
            }
        if not (0 <= entry.anchor_page_index < page_count):
            return {
                "linked": False,
                "reason": f"destination page index {entry.anchor_page_index} out of range",
            }
        fitted = _fit_rect_to_page(rect, pages[entry.toc_page_index])
        if fitted is None:
            return {
                "linked": False,
                "reason": "TOC text rectangle falls outside the TOC page",
            }
        rect = fitted
    add_annotation = getattr(writer, "add_annotation", None)
    if not callable(add_annotation):
        return {
            "linked": False,
            "reason": "writer does not support annotations",
        }
    try:
        annotation = _create_internal_link_annotation(rect, entry.anchor_page_index)
        add_annotation(entry.toc_page_index, annotation)
    except Exception as exc:  # noqa: BLE001 - keep bookmark writing resilient
        return {
            "linked": False,
            "reason": f"annotation failed: {exc}",
        }
    return {
        "linked": True,
        "reason": "TOC text rectangle linked to resolved destination",
        "rect": rect,
    }


def _toc_link_rectangle(entry: TocEntry) -> Optional[Tuple[float, float, float, float]]:
    """@brief Build a PDF link rectangle over confident TOC entry text bounds.

    Prefers the page-space ``toc_bbox`` captured during extraction (text and
    CTM matrices applied). The raw ``toc_x``/``toc_y`` fallback is only valid
    when text space equals page space, so it is kept for callers that build
    entries without a bbox.
    """
    if entry.toc_bbox is not None:
        return _rectangle_from_bbox(entry.title, entry.toc_bbox)
    if (
        entry.toc_x is None
        or entry.toc_y is None
        or entry.toc_width is None
        or entry.toc_height is None
    ):
        return None
    if entry.toc_width < 8.0 or entry.toc_height < 4.0:
        return None
    height = entry.toc_height
    title_estimate = max(len(entry.title), 1) * max(height / 1.2, 1.0) * 0.55
    width = entry.toc_width
    if entry.toc_width > title_estimate * 1.5:
        width = min(entry.toc_width, max(title_estimate, height * 3.0))
    if width < 8.0:
        return None
    x0 = entry.toc_x
    x1 = entry.toc_x + width
    y0 = entry.toc_y - (0.25 * height)
    y1 = entry.toc_y + (0.85 * height)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _rectangle_from_bbox(
    title: str,
    bbox: Tuple[float, float, float, float],
) -> Optional[Tuple[float, float, float, float]]:
    """@brief Trim a page-space TOC row box to the title text.

    A TOC row often includes dot leaders and the page number; when the row is
    much wider than the title alone, keep the link over the title.
    """
    x0, y0, x1, y1 = bbox
    height = y1 - y0
    width = x1 - x0
    if height < 4.0 or width < 8.0:
        return None
    title_estimate = max(len(title), 1) * height * 0.5
    if width > title_estimate * 1.5:
        width = min(width, max(title_estimate, height * 3.0))
    return (x0, y0, x0 + width, y1)


def _fit_rect_to_page(
    rect: Tuple[float, float, float, float],
    page: Any,
) -> Optional[Tuple[float, float, float, float]]:
    """@brief Keep a link rectangle on the visible page, or reject it.

    Text widths are estimated, so a long row (title, leaders and page number)
    can overshoot the right edge; the right edge is clamped to the page. A
    rectangle whose left, top or bottom edge is off the page indicates bad
    geometry and is rejected (``None``).
    """
    # The crop box is the visible area (the finisher crops oversized pages);
    # pypdf defaults it to the media box when absent.
    box = getattr(page, "cropbox", None) or getattr(page, "mediabox", None)
    if box is None:
        return rect
    try:
        left, bottom, right, top = (float(value) for value in (box.left, box.bottom, box.right, box.top))
    except (AttributeError, TypeError, ValueError):
        return rect
    x0, y0, x1, y1 = rect
    if not (left - 1 <= x0 < right and bottom - 1 <= y0 and y1 <= top + 1):
        return None
    x1 = min(x1, right)
    if x1 - x0 < 8.0:
        return None
    return (x0, y0, x1, y1)


def _create_internal_link_annotation(
    rect: Tuple[float, float, float, float],
    target_page_index: int,
) -> Any:
    """@brief Construct a borderless internal PDF link annotation."""
    try:
        from pypdf.annotations import Link
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is required for TOC link annotations. Install dependencies first."
        ) from exc
    return Link(
        rect=rect,
        target_page_index=target_page_index,
        border=[0, 0, 0],
    )


def _format_link_log_line(entry: TocEntry, decision: Dict[str, Any]) -> str:
    """@brief Format one human-readable TOC link annotation decision."""
    outcome = "LINK " if decision["linked"] else "SKIP "
    toc_page = "?" if entry.toc_page_index is None else str(entry.toc_page_index)
    dest = "?" if entry.anchor_page_index is None else str(entry.anchor_page_index)
    rect = decision.get("rect")
    rect_text = (
        f"({rect[0]:.1f},{rect[1]:.1f},{rect[2]:.1f},{rect[3]:.1f})"
        if isinstance(rect, tuple) and len(rect) == 4
        else "n/a"
    )
    return (
        f"{outcome} | toc_page={toc_page} | dest={dest} | rect={rect_text} | "
        f"{entry.title} | {decision['reason']}"
    )

