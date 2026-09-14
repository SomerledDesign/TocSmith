from __future__ import annotations

"""@file
@brief Conservative PDF bookmark writer built on top of analysis results.

The writer only emits outline items for TOC entries whose anchors and titles
pass confidence checks. It then applies the page finishing pass and writes a
human-readable log describing bookmark and finishing decisions.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    skipped_titles: List[str] = []
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
        parent = parent_by_level.get(max(0, entry.level - 1))
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
        log_lines.append(_format_log_line(entry, decision))

    finish_stats = finish_pdf_pages(writer.pages, watermark=watermark)
    log_lines.extend(
        [
            "",
            "Finishing:",
            f"Cropped oversized pages: {finish_stats.cropped_page_count}",
            f"Watermarked pages: {finish_stats.watermarked_page_count}",
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
