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

from .analyzer import _normalize_title, is_confident_bookmark_candidate
from .finisher import DEFAULT_WATERMARK, finish_pdf_pages
from .models import BookmarkWriteResult, TocEntry
from .pdfio import _open_pdf_reader, analyze_pdf_file

#: Outline modes. ``keep`` leaves the source outline untouched, ``merge`` adds
#: only generated entries whose titles are not already present, and ``replace``
#: discards the source outline and writes the generated one.
OUTLINE_MODES = ("keep", "merge", "replace")


def write_bookmarks_for_pdf(
    input_path: str | Path,
    output_path: str | Path | None = None,
    min_match_score: float = 0.85,
    watermark: str = DEFAULT_WATERMARK,
    outline: str | None = None,
    links: bool = True,
) -> BookmarkWriteResult:
    """@brief Analyze a PDF and write a new copy with generated bookmarks.

    When the source already has an outline and ``outline`` is omitted, the
    existing outline is kept. Pass ``replace`` for the previous behavior of
    discarding it, or ``merge`` to add only generated entries that are missing.

    @param input_path Source PDF path.
    @param output_path Optional destination path for the new bookmarked PDF.
    @param min_match_score Minimum score required for a root-level anchor to be
        accepted.
    @param watermark Footer text applied to output pages; an empty value
        disables watermarking.
    @param outline ``keep``, ``merge``, or ``replace``. ``None`` keeps an
        existing outline and generates one when the source has none.
    @param links When true (the default), add TOC link annotations. ``False``
        matches ``--no-links``.
    @return Summary of the created PDF, log file, and skipped titles.
    @throw RuntimeError Raised when the PDF lacks extractable text.
    @throw ValueError Raised when ``outline`` is not a known mode.
    """
    if outline is not None and outline not in OUTLINE_MODES:
        raise ValueError(f"outline must be one of {', '.join(OUTLINE_MODES)}")
    input_file = Path(input_path)
    destination = Path(output_path) if output_path else input_file.with_name(
        input_file.stem + ".bookmarked.pdf"
    )
    log_path = destination.with_suffix(destination.suffix + ".log.txt")

    analysis = analyze_pdf_file(input_file)
    if not analysis.is_ocr_text_available:
        raise RuntimeError("PDF does not appear to contain extractable text. Skipping.")

    reader = _open_pdf_reader(input_file)
    source_outline_count = _count_outline_items(getattr(reader, "outline", None))
    outline_mode = outline or ("keep" if source_outline_count else "replace")
    import_outline = outline_mode in {"keep", "merge"}
    writer = _create_writer()
    writer.append(reader, import_outline=import_outline)
    _copy_document_metadata(reader, writer)
    kept_bookmark_count = (
        _count_outline_items(getattr(writer, "outline", None)) if import_outline else 0
    )
    # A writer double that only records calls has no imported outline. Fall
    # back to the count taken from the reader so the log still reports it.
    if import_outline and kept_bookmark_count == 0:
        kept_bookmark_count = source_outline_count
    existing_outline_items = _index_outline_by_title(writer) if outline_mode == "merge" else {}

    parent_by_level: Dict[int, Any] = {}
    accepted_entry_by_level: Dict[int, TocEntry] = {}
    written_count = 0
    link_annotation_count = 0
    skipped_titles: List[str] = []
    log_lines = [
        f"Input PDF: {input_file}",
        f"Output PDF: {destination}",
        f"Minimum root match score: {min_match_score:.2f}",
        f"Outline mode: {outline_mode}",
        f"Kept existing bookmarks: {kept_bookmark_count}",
        "",
        "Decisions:",
    ]
    if not analysis.toc_entries:
        log_lines.append("No TOC entries detected; output PDF copied without generated bookmarks.")
    elif outline_mode == "keep":
        log_lines.append(
            "Existing outline kept; generated bookmarks were not added."
        )

    for entry in analysis.toc_entries:
        if outline_mode == "keep":
            continue
        if outline_mode == "merge" and _normalize_title(entry.title) in existing_outline_items:
            parent_by_level[entry.level] = existing_outline_items[_normalize_title(entry.title)]
            accepted_entry_by_level[entry.level] = entry
            _clear_deeper_levels(parent_by_level, entry.level)
            _clear_deeper_levels(accepted_entry_by_level, entry.level)
            log_lines.append(
                _format_log_line(
                    entry,
                    {
                        "write": False,
                        "threshold": min_match_score,
                        "reason": "already present in the existing outline",
                    },
                )
            )
            continue
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
        log_lines.append(_format_log_line(entry, decision))

    finish_stats = finish_pdf_pages(writer.pages, watermark=watermark)
    link_log_lines: List[str] = []
    # Links are a separate pass from bookmark generation. A kept outline still
    # gets contents rows linked to the bookmarks that are already there.
    if not links:
        link_log_lines.append("TOC link annotations disabled.")
    else:
        catalog = _destination_catalog(writer)
        for entry in analysis.toc_entries:
            target_page, dest_array, match_reason = _link_target_for_entry(entry, catalog)
            link_decision = _try_add_toc_link_annotation(
                writer,
                entry,
                target_page_index=target_page,
                dest_array=dest_array,
                match_reason=match_reason,
            )
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
    log_lines.extend(_format_finish_issue_lines(finish_stats))
    # Watermarking merges an uncompressed content stream into every page.
    # Reflate after that merge so a footer does not inflate the file.
    _compress_content_streams(writer)
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
        kept_bookmark_count=kept_bookmark_count,
        outline_mode=outline_mode,
    )


def _count_outline_items(outline: Any) -> int:
    """@brief Count bookmark nodes in a pypdf outline tree.

    @param outline Outline sequence, or anything that is not a sequence.
    @return Number of title-bearing outline items. Nested lists are walked.
    """
    if not outline or isinstance(outline, (str, bytes)):
        return 0
    try:
        items = list(outline)
    except TypeError:
        return 0
    count = 0
    for item in items:
        if isinstance(item, list):
            count += _count_outline_items(item)
            continue
        title = getattr(item, "title", None)
        if isinstance(title, str) and title.strip():
            count += 1
        elif isinstance(item, dict) and item.get("title"):
            count += 1
    return count


def _index_outline_by_title(writer: Any) -> Dict[str, Any]:
    """@brief Map a normalized bookmark title to its outline node.

    The first occurrence wins so later duplicates do not steal the parent a
    merged child should hang from.
    """
    indexed: Dict[str, Any] = {}
    outline = getattr(writer, "outline", None)
    if not outline:
        return indexed
    try:
        items = list(outline)
    except TypeError:
        return indexed

    def visit(nodes: List[Any]) -> None:
        for item in nodes:
            if isinstance(item, list):
                visit(item)
                continue
            title = getattr(item, "title", None)
            if isinstance(title, str) and title.strip():
                # ``outline`` yields detached Destination copies. Children have
                # to be attached to the live tree node or they never show up.
                indexed.setdefault(_normalize_title(title), getattr(item, "node", None) or item)

    visit(items)
    return indexed


def _copy_document_metadata(reader: Any, writer: Any) -> None:
    """@brief Copy the info dictionary and catalog ``/Lang`` onto the writer.

    ``append`` copies pages and, when asked, the outline. It does not copy
    ``/Info`` or the catalog language, so Title, Author, and Lang would
    otherwise disappear from the finished file.
    """
    info = getattr(reader, "metadata", None)
    add_metadata = getattr(writer, "add_metadata", None)
    if info is not None and callable(add_metadata):
        payload: Dict[str, str] = {}
        try:
            items = list(info.items())
        except (AttributeError, TypeError):
            items = []
        for key, value in items:
            if value is None:
                continue
            payload[str(key)] = str(value)
        if payload:
            add_metadata(payload)
    lang = _document_language(reader)
    root = getattr(writer, "_root_object", None)
    if lang and root is not None:
        from pypdf.generic import NameObject, TextStringObject

        root[NameObject("/Lang")] = TextStringObject(lang)


def _document_language(reader: Any) -> Optional[str]:
    """@brief Read catalog ``/Lang`` from a reader, if it has one."""
    root = getattr(reader, "root_object", None)
    if root is None:
        trailer = getattr(reader, "trailer", None)
        if trailer is not None:
            try:
                root = trailer.get("/Root")
            except (AttributeError, TypeError):
                root = None
    if root is None:
        return None
    try:
        lang = root.get("/Lang")
    except (AttributeError, TypeError):
        return None
    if lang is None:
        return None
    text = str(lang).strip()
    return text or None


def _compress_content_streams(writer: Any) -> None:
    """@brief Flate-compress each page content stream after finishing.

    Pages that are not attached to a writer (unit-test stand-ins) are skipped.
    A failure to compress one page must not discard the finished document.
    """
    pages = getattr(writer, "pages", None)
    if not pages:
        return
    for page in pages:
        compress = getattr(page, "compress_content_streams", None)
        if not callable(compress):
            continue
        try:
            compress()
        except (AttributeError, TypeError, ValueError):
            continue


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


def _format_finish_issue_lines(finish_stats: Any) -> List[str]:
    """@brief Describe page-box repairs and pages the finisher had to skip.

    @param finish_stats FinishStats from the finishing pass (older test doubles
                        without the new fields are accepted).
    @return Log lines with one-based page numbers; empty when nothing happened.
    """
    lines: List[str] = []
    for index, note in getattr(finish_stats, "box_notes", ()) or ():
        lines.append(f"BOX page {index + 1}: {note}")
    skipped = getattr(finish_stats, "skipped_pages", ()) or ()
    if skipped:
        lines.append(f"Pages left unfinished: {len(skipped)}")
    for index, reason in skipped:
        lines.append(f"SKIP page {index + 1}: {reason}")
    return lines


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

def _try_add_toc_link_annotation(
    writer: Any,
    entry: TocEntry,
    target_page_index: Optional[int] = None,
    dest_array: Any = None,
    match_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """@brief Place one in-page TOC link when the row's geometry is clear.

    ``target_page_index`` overrides the entry's anchor when the row was matched
    to an existing bookmark or named destination. ``dest_array`` is that
    destination's exact view (page plus fit); a bare page index is used when
    the row only resolved to a page.

    An existing link that already covers this rectangle and the same page is
    left in place so repeated runs do not stack duplicates.

    @param writer PDF writer that receives the annotation.
    @param entry TOC row being linked.
    @param target_page_index Destination page. ``None`` uses the entry anchor.
    @param dest_array Optional exact destination array to reuse.
    @param match_reason Why this destination was chosen, for the log.
    @return Decision dictionary with ``linked``, ``reason``, and sometimes ``rect``.
    """
    rect = _toc_link_rectangle(entry)
    if rect is None:
        return {
            "linked": False,
            "reason": "missing or uncertain TOC text rectangle",
        }
    destination_page = entry.anchor_page_index if target_page_index is None else target_page_index
    if entry.toc_page_index is None or destination_page is None:
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
        if not (0 <= destination_page < page_count):
            return {
                "linked": False,
                "reason": f"destination page index {destination_page} out of range",
            }
        fitted = _fit_rect_to_page(rect, pages[entry.toc_page_index])
        if fitted is None:
            return {
                "linked": False,
                "reason": "TOC text rectangle falls outside the TOC page",
            }
        rect = fitted
        if _page_already_links(pages[entry.toc_page_index], rect, destination_page, writer):
            return {
                "linked": False,
                "reason": "existing link already covers this TOC row",
                "rect": rect,
                "target_page": destination_page,
            }
    add_annotation = getattr(writer, "add_annotation", None)
    if not callable(add_annotation):
        return {
            "linked": False,
            "reason": "writer does not support annotations",
        }
    try:
        annotation = _create_internal_link_annotation(
            rect, destination_page, dest_array=dest_array
        )
        add_annotation(entry.toc_page_index, annotation)
    except Exception as exc:  # noqa: BLE001 - keep bookmark writing resilient
        return {
            "linked": False,
            "reason": f"annotation failed: {exc}",
        }
    reason = match_reason or "TOC text rectangle linked to resolved destination"
    return {
        "linked": True,
        "reason": reason,
        "rect": rect,
        "target_page": destination_page,
    }


def _link_target_for_entry(
    entry: TocEntry,
    catalog: Dict[str, Tuple[Optional[int], Any]],
) -> Tuple[Optional[int], Any, str]:
    """@brief Choose the destination a TOC row should link to.

    Title match against an outline item or named destination wins. Otherwise
    the row's resolved printed page, then its anchor page, is used.

    @return ``(page index or None, destination array or None, reason)``.
    """
    found = catalog.get(_normalize_title(entry.title))
    if found is not None and found[0] is not None:
        return found[0], found[1], "matched bookmark or named destination by title"
    resolved = getattr(entry, "resolved_page_index", None)
    if isinstance(resolved, int):
        return resolved, None, "resolved printed page"
    if entry.anchor_page_index is not None:
        return entry.anchor_page_index, None, "resolved page"
    return None, None, "no bookmark, named destination, or resolved page"


def _destination_catalog(writer: Any) -> Dict[str, Tuple[Optional[int], Any]]:
    """@brief Index outline titles and named destinations by normalized title.

    Outline titles are recorded first so a human-readable bookmark beats a
    short named-destination id that happens to normalize the same way.
    """
    catalog: Dict[str, Tuple[Optional[int], Any]] = {}
    for item in _iter_outline_items(getattr(writer, "outline", None)):
        title = getattr(item, "title", None)
        if not isinstance(title, str) or not title.strip():
            continue
        catalog.setdefault(
            _normalize_title(title),
            (_destination_page_index(writer, item), getattr(item, "dest_array", None)),
        )
    named = getattr(writer, "named_destinations", None) or {}
    try:
        pairs = list(named.items())
    except (AttributeError, TypeError):
        pairs = []
    for name, dest in pairs:
        key = _normalize_title(str(name))
        if key in catalog:
            continue
        catalog[key] = (
            _destination_page_index(writer, dest),
            getattr(dest, "dest_array", None),
        )
    return catalog


def _iter_outline_items(outline: Any) -> List[Any]:
    """@brief Flatten an outline tree into destination nodes."""
    if not outline or isinstance(outline, (str, bytes)):
        return []
    try:
        items = list(outline)
    except TypeError:
        return []
    flat: List[Any] = []

    def visit(nodes: List[Any]) -> None:
        for item in nodes:
            if isinstance(item, list):
                visit(item)
                continue
            flat.append(item)

    visit(items)
    return flat


def _destination_page_index(writer: Any, destination: Any) -> Optional[int]:
    """@brief Resolve a destination object to a zero-based page index."""
    getter = getattr(writer, "get_destination_page_number", None)
    if not callable(getter):
        return None
    try:
        page = getter(destination)
    except Exception:  # noqa: BLE001 - unreadable destinations are simply unmatched
        return None
    return page if isinstance(page, int) else None


def _page_already_links(page: Any, rect: Tuple[float, float, float, float], target_page: int, writer: Any) -> bool:
    """@brief Report whether this rectangle already links to ``target_page``.

    Existing annotations are kept. A second link is skipped only when it would
    cover the same row and the same destination.
    """
    annots = getattr(page, "annotations", None)
    if not annots and hasattr(page, "get"):
        try:
            annots = page.get("/Annots")
        except (AttributeError, TypeError):
            annots = None
    if not annots:
        return False
    for annot in annots:
        obj = annot.get_object() if hasattr(annot, "get_object") else annot
        try:
            subtype = str(obj.get("/Subtype"))
        except (AttributeError, TypeError):
            continue
        if subtype != "/Link":
            continue
        existing = obj.get("/Rect")
        if existing is None:
            continue
        try:
            existing_rect = tuple(float(value) for value in existing)
        except (TypeError, ValueError):
            continue
        if len(existing_rect) != 4 or not _rects_overlap(existing_rect, rect):
            continue
        existing_page = _annotation_target_page(writer, obj)
        if existing_page is None or existing_page == target_page:
            return True
    return False


def _annotation_target_page(writer: Any, annotation: Any) -> Optional[int]:
    """@brief Read the page index a link annotation points at, if it can."""
    try:
        dest = annotation.get("/Dest")
        if dest is None and annotation.get("/A") is not None:
            action = annotation["/A"]
            action = action.get_object() if hasattr(action, "get_object") else action
            dest = action.get("/D")
    except (AttributeError, TypeError):
        return None
    if dest is None:
        return None
    if isinstance(dest, dict) and "target_page_index" in dest:
        try:
            return int(dest["target_page_index"])
        except (TypeError, ValueError):
            return None
    return _destination_page_index(writer, dest)


def _rects_overlap(
    first: Tuple[float, float, float, float],
    second: Tuple[float, float, float, float],
    ratio: float = 0.5,
) -> bool:
    """@brief Report whether two rectangles cover enough of each other to be the same row."""
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    if x1 <= x0 or y1 <= y0:
        return False
    intersection = (x1 - x0) * (y1 - y0)
    area = max((second[2] - second[0]) * (second[3] - second[1]), 1.0)
    return intersection / area >= ratio


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
    dest_array: Any = None,
) -> Any:
    """@brief Construct a borderless internal PDF link annotation.

    When ``dest_array`` is the bookmark's own destination, the link uses that
    exact view (page and fit) instead of a generic page fit.
    """
    if dest_array is not None:
        from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, RectangleObject

        cloned = ArrayObject()
        for value in dest_array:
            cloned.append(value)
        annotation = DictionaryObject()
        annotation.update(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): RectangleObject(rect),
                NameObject("/Border"): ArrayObject(
                    [NumberObject(0), NumberObject(0), NumberObject(0)]
                ),
                NameObject("/Dest"): cloned,
            }
        )
        return annotation
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
    target_page = decision.get("target_page", entry.anchor_page_index)
    dest = "?" if target_page is None else str(target_page)
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

