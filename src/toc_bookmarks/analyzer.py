"""@file
@brief Heuristic PDF analysis pipeline for TOC detection and bookmark matching.

The analyzer works in several passes:
- detect whether the PDF exposes enough extractable text to operate safely
- identify likely TOC pages from text patterns and optional layout metadata
- extract TOC rows and infer hierarchy levels
- match TOC entries to likely body-page anchors
- compare the extracted TOC against existing PDF bookmarks

The heuristics are intentionally conservative because real-world manuals and
scanned documents are noisy and often contain OCR artifacts.
"""

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import AnalysisResult, BookmarkCoverage, TocCandidate, TocEntry, TocLayoutLine

_DOT_LEADER_PATTERN = re.compile(r"\.{2,}")
_SPACED_DOT_LEADER_PATTERN = re.compile(r"(?:\s*\.\s*){2,}")
_INLINE_SYMBOL_PATTERN = re.compile(r"\s+['\"`~_•·,]+\s*")
_TOC_LINE_PATTERN = re.compile(
    r"^\s*(?P<title>.+?)\s*(?:\.{2,}|\s{2,}|\t)\s*(?:['\"`,;:]+\s*)?(?P<page>\d{1,4}|[ivxlcdmIVXLCDM]+)\s*$"
)
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_HEADING_PREFIX_PATTERN = re.compile(
    r"^(chapter|appendix|section|part)\s+[a-z0-9ivxlcdm.-]+\s+",
    re.IGNORECASE,
)
_STRUCTURAL_PREFIX_PATTERN = re.compile(
    r"^(chapter|appendix|section|part)\b", re.IGNORECASE
)
_CHESS_HEADING_KEYWORDS = (
    "gambit",
    "defense",
    "opening",
    "attack",
    "variation",
    "game",
    "systems",
    "system",
)
_APOSTROPHE_S_PATTERN = re.compile(r"(?i)\b([A-Za-z]+)\s+'\s+s\b")
_READABLE_FRAGMENT_PATTERN = re.compile(
    r"(?:\b\d+\s+)?[A-Z][A-Za-z0-9'&-]*(?:\s+(?:[A-Z][A-Za-z0-9'&-]*|[a-z][A-Za-z0-9'&-]*))*"
)
_MOVE_PREFIX_PATTERN = re.compile(
    r"^(?:(?:\d+\.{0,3}\s*)?(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8]|[a-h][1-8]|O-O(?:-O)?)[+#]?\s*){1,8}"
)


def analyze_pdf_features(
    page_texts: Sequence[str],
    bookmark_titles: Sequence[str],
    toc_page_layouts: Optional[Dict[int, Sequence[TocLayoutLine]]] = None,
    page_layouts: Optional[Dict[int, Sequence[TocLayoutLine]]] = None,
) -> AnalysisResult:
    """@brief Run the full text- and layout-based PDF analysis pipeline.

    @param page_texts Extracted text for each PDF page.
    @param bookmark_titles Existing outline titles already present in the PDF.
    @param toc_page_layouts Optional layout metadata for TOC pages.
    @param page_layouts Optional layout metadata for all pages.
    @return Aggregate analysis result used by the CLI and bookmark writer.
    """
    toc_candidates = detect_toc_pages(page_texts, toc_page_layouts=toc_page_layouts)
    toc_entries = match_toc_entries_to_pages(
        extract_toc_entries(page_texts, toc_candidates, toc_page_layouts=toc_page_layouts),
        page_texts,
        excluded_page_indexes={candidate.page_index for candidate in toc_candidates},
        page_layouts=page_layouts,
    )
    coverage = compare_bookmarks_to_toc(bookmark_titles, toc_entries)
    return AnalysisResult(
        is_ocr_text_available=has_extractable_text(page_texts),
        toc_entries=toc_entries,
        toc_candidates=toc_candidates,
        bookmark_coverage=coverage,
    )


def has_extractable_text(page_texts: Sequence[str], threshold: float = 0.6) -> bool:
    """@brief Decide whether the PDF contains enough text-layer content to use.

    @param page_texts Extracted page-text strings.
    @param threshold Minimum populated-page ratio required to consider the PDF
        text-readable.
    @return ``True`` when enough pages contain non-empty text, else ``False``.
    """
    if not page_texts:
        return False
    populated = sum(1 for text in page_texts if _normalize_space(text))
    return (populated / len(page_texts)) >= threshold


def detect_toc_pages(
    page_texts: Sequence[str],
    toc_page_layouts: Optional[Dict[int, Sequence[TocLayoutLine]]] = None,
) -> List[TocCandidate]:
    """@brief Find pages that likely belong to the table of contents.

    Text-first detection looks for multiple TOC-like lines on the same page.
    When text extraction is too messy, layout metadata is used as a fallback to
    spot title-like rows under a TOC header.

    @param page_texts Extracted text for each page.
    @param toc_page_layouts Optional layout lines keyed by page index.
    @return Ordered list of TOC candidate pages with match scores.
    """
    candidates: List[TocCandidate] = []
    header_pages: List[int] = []
    for page_index, page_text in enumerate(page_texts):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        toc_lines = [line for line in lines if _looks_like_toc_line(line)]
        layout_lines = list((toc_page_layouts or {}).get(page_index, []))
        if len(toc_lines) >= 2:
            score = len(toc_lines) / len(lines)
            if score >= 0.35:
                candidates.append(
                    TocCandidate(
                        page_index=page_index,
                        matched_lines=toc_lines,
                        score=round(score, 2),
                    )
                )
                continue
        if _looks_like_layout_toc_page(page_text, layout_lines):
            header_pages.append(page_index)
            candidate = _layout_toc_candidate(page_index, page_text, layout_lines)
            if candidate is not None:
                candidates.append(candidate)
            continue
        if (
            candidates
            and candidates[-1].page_index == page_index - 1
            and _looks_like_layout_toc_continuation_page(page_text, layout_lines)
        ):
            candidate = _layout_toc_candidate(page_index, page_text, layout_lines)
            if candidate is not None:
                candidates.append(candidate)
            continue
    if header_pages:
        start_page = min(header_pages)
        clustered = [candidate for candidate in candidates if candidate.page_index >= start_page]
        filtered: List[TocCandidate] = []
        previous_page: Optional[int] = None
        for candidate in clustered:
            if not filtered:
                if candidate.page_index == start_page:
                    filtered.append(candidate)
                    previous_page = candidate.page_index
                continue
            if previous_page is None or candidate.page_index - previous_page > 1:
                break
            filtered.append(candidate)
            previous_page = candidate.page_index
        if filtered:
            return filtered
    return candidates


def _layout_toc_candidate(
    page_index: int,
    page_text: str,
    layout_lines: Sequence[TocLayoutLine],
) -> Optional[TocCandidate]:
    """@brief Build a candidate from layout title rows when enough exist."""
    matched_lines = [line.text for line in _layout_toc_title_lines(page_text, layout_lines)]
    if len(matched_lines) < 4:
        return None
    score = min(len(matched_lines) / max(len(layout_lines), 1), 0.95)
    return TocCandidate(
        page_index=page_index,
        matched_lines=matched_lines,
        score=round(score, 2),
    )


def extract_toc_entries(
    page_texts: Sequence[str],
    toc_candidates: Sequence[TocCandidate],
    toc_page_layouts: Optional[Dict[int, Sequence[TocLayoutLine]]] = None,
) -> List[TocEntry]:
    """@brief Extract normalized TOC entries from the detected TOC pages.

    Each row is cleaned, assigned a printed page number, and given an inferred
    outline level based on indentation, numbering, structural headings, and
    optional layout-band hints.

    @param page_texts Extracted text for each page.
    @param toc_candidates Pages previously classified as TOC pages.
    @param toc_page_layouts Optional layout metadata for TOC pages.
    @return Deduplicated TOC entries with inferred hierarchy.
    """
    entries: List[TocEntry] = []
    structural_context_level = 1
    active_level2_page: Optional[int] = None
    layout_bands = _build_layout_bands(toc_page_layouts or {})
    for candidate in toc_candidates:
        page_text = page_texts[candidate.page_index]
        page_layouts = list((toc_page_layouts or {}).get(candidate.page_index, []))
        page_entries = _extract_toc_rows_from_text(page_text, page_layouts)
        layout_entries: List[Tuple[str, str, Optional[int], Optional[TocLayoutLine]]] = []
        if page_layouts:
            layout_entries = _extract_toc_rows_from_layout(
                page_text,
                page_layouts,
                len(page_texts),
            )
        if layout_entries and (
            not page_entries
            or len(layout_entries) >= max(4, len(page_entries) * 2)
        ):
            page_entries = layout_entries
        for raw_line, title, printed_page, layout_line in page_entries:
            level = _infer_level(
                raw_line,
                title,
                printed_page,
                structural_context_level,
                active_level2_page,
                layout_line=layout_line,
                layout_bands=layout_bands,
            )
            if _STRUCTURAL_PREFIX_PATTERN.match(title):
                structural_context_level = 2
                active_level2_page = None
            elif level <= 2:
                active_level2_page = printed_page
            entries.append(
                TocEntry(
                    title=title,
                    printed_page=printed_page,
                    level=level,
                    toc_page_index=candidate.page_index,
                    toc_x=None if layout_line is None else layout_line.x,
                    toc_font_name="" if layout_line is None else layout_line.font_name,
                )
            )
    deduped = _dedupe_entries(entries)
    typographic = _apply_two_tier_typographic_hierarchy(deduped)
    return _reconcile_toc_layout_levels(typographic)


def _extract_toc_rows_from_text(
    page_text: str,
    page_layouts: Sequence[TocLayoutLine],
) -> List[Tuple[str, str, Optional[int], Optional[TocLayoutLine]]]:
    """@brief Parse TOC rows directly from extracted text lines."""
    rows: List[Tuple[str, str, Optional[int], Optional[TocLayoutLine]]] = []
    for raw_line in page_text.splitlines():
        line = _normalize_toc_line(raw_line.strip())
        match = _TOC_LINE_PATTERN.match(line)
        if not match:
            continue
        title = _clean_title(match.group("title"))
        if not title:
            continue
        rows.append(
            (
                raw_line,
                title,
                _parse_page_number(match.group("page")),
                _match_layout_line(line, title, page_layouts),
            )
        )
    return rows


def _extract_toc_rows_from_layout(
    page_text: str,
    page_layouts: Sequence[TocLayoutLine],
    max_page_number: int,
) -> List[Tuple[str, str, Optional[int], Optional[TocLayoutLine]]]:
    """@brief Reconstruct TOC rows from layout lines when raw text is unreliable.

    This pass merges fragmented layout spans, keeps title-like rows, and pairs
    them with sequential page numbers gathered from either layout or text.
    """
    merged_lines = _merge_layout_row_fragments(page_layouts)
    title_lines = _layout_toc_title_lines(page_text, merged_lines)
    if not title_lines:
        return []

    layout_page_numbers = _extract_layout_page_numbers(
        merged_lines,
        max_page_number=max_page_number,
    )
    text_page_numbers = _extract_sequential_page_numbers(
        page_text,
        max_page_number=max_page_number,
    )
    page_numbers = (
        layout_page_numbers
        if len(layout_page_numbers) >= len(text_page_numbers)
        else text_page_numbers
    )
    rows: List[Tuple[str, str, Optional[int], Optional[TocLayoutLine]]] = []
    page_index = 0
    for layout_line in title_lines:
        raw_line = layout_line.text
        title_text, embedded_page = _split_trailing_page_number(raw_line)
        title = _clean_title(title_text)
        if not title:
            continue
        printed_page = embedded_page
        if printed_page is None and page_index < len(page_numbers):
            printed_page = page_numbers[page_index]
        if printed_page is None:
            continue
        if page_index < len(page_numbers) and page_numbers[page_index] == printed_page:
            page_index += 1
        rows.append((raw_line, title, printed_page, layout_line))
    return rows


def compare_bookmarks_to_toc(
    bookmark_titles: Sequence[str], toc_entries: Sequence[TocEntry]
) -> BookmarkCoverage:
    """@brief Compare existing bookmark titles against extracted TOC entries."""
    normalized_bookmarks = {_normalize_title(title): title for title in bookmark_titles}
    missing: List[str] = []
    matched: List[str] = []
    for entry in toc_entries:
        normalized = _normalize_title(entry.title)
        if normalized in normalized_bookmarks:
            matched.append(entry.title)
        else:
            missing.append(entry.title)
    return BookmarkCoverage(
        bookmark_titles=list(bookmark_titles),
        missing_titles=missing,
        matched_titles=matched,
    )


def _looks_like_toc_line(line: str) -> bool:
    """@brief Test whether one text line resembles a TOC row."""
    line = _normalize_toc_line(line)
    if len(line) < 4:
        return False
    if _TOC_LINE_PATTERN.match(line):
        return True
    return bool(_DOT_LEADER_PATTERN.search(line) and re.search(r"\d{1,4}\s*$", line))


def _infer_level(
    raw_line: str,
    title: str,
    printed_page: Optional[int],
    structural_context_level: int = 1,
    active_level2_page: Optional[int] = None,
    layout_line: Optional[TocLayoutLine] = None,
    layout_bands: Optional[List[float]] = None,
) -> int:
    """@brief Infer an outline level for one TOC row.

    The function primarily uses indentation and structural wording, with extra
    contextual adjustments for numbered headings, active chapter sections, and
    nearby level-2 groupings.
    """
    indent = len(raw_line) - len(raw_line.lstrip(" "))
    if _STRUCTURAL_PREFIX_PATTERN.match(title):
        return 1
    if indent >= 8:
        return 3
    if indent >= 3:
        return 2
    numbered_match = re.match(r"^(\d+(?:\.\d+)*)", title)
    if numbered_match:
        return min(numbered_match.group(1).count(".") + 2, 4)
    if structural_context_level >= 2:
        if (
            active_level2_page is not None
            and _looks_like_subtopic(title)
            and printed_page is not None
            and printed_page <= active_level2_page + 2
        ):
            return min(structural_context_level + 1, 3)
        if _looks_like_major_topic(title):
            return 2
        if (
            active_level2_page is not None
            and printed_page is not None
            and printed_page <= active_level2_page + 2
        ):
            return min(structural_context_level + 1, 3)
    return structural_context_level


def _parse_page_number(value: str) -> Optional[int]:
    """@brief Parse either an Arabic or Roman numeral page reference."""
    value = value.strip(" '\"`,;:")
    if value.isdigit():
        return int(value)
    roman = value.lower()
    numerals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    previous = 0
    for char in reversed(roman):
        current = numerals.get(char)
        if current is None:
            return None
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total or None


def _clean_title(title: str) -> str:
    """@brief Remove TOC noise and reduce a raw title to readable heading text."""
    title = _normalize_space(title)
    title = _DOT_LEADER_PATTERN.sub(" ", title)
    title = _INLINE_SYMBOL_PATTERN.sub(" ", title)
    title = _APOSTROPHE_S_PATTERN.sub(r"\1's", title)
    title = _normalize_space(title.strip("-: .,'\"`~_•·"))
    return _extract_reasonable_title(title)


def _normalize_title(title: str) -> str:
    """@brief Normalize a title for case-insensitive heuristic matching."""
    title = _clean_title(title).lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return _normalize_space(title)


def _normalize_space(value: str) -> str:
    """@brief Collapse repeated whitespace into single spaces."""
    return " ".join(value.split())


def _dedupe_entries(entries: Iterable[TocEntry]) -> List[TocEntry]:
    """@brief Remove duplicates without merging separate TOC clusters."""
    seen = set()
    deduped: List[TocEntry] = []
    cluster_id = 0
    previous_toc_page: Optional[int] = None
    for entry in entries:
        if (
            entry.toc_page_index is not None
            and previous_toc_page is not None
            and entry.toc_page_index > previous_toc_page + 1
        ):
            cluster_id += 1
        key = (cluster_id, _normalize_title(entry.title), entry.printed_page)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
        if entry.toc_page_index is not None:
            previous_toc_page = entry.toc_page_index
    return deduped


def _normalize_toc_line(line: str) -> str:
    """@brief Normalize spaced dot leaders into a consistent TOC separator form."""
    return _SPACED_DOT_LEADER_PATTERN.sub(" .. ", line)


def match_toc_entries_to_pages(
    toc_entries: Sequence[TocEntry],
    page_texts: Sequence[str],
    excluded_page_indexes: Optional[Sequence[int]] = None,
    page_layouts: Optional[Dict[int, Sequence[TocLayoutLine]]] = None,
) -> List[TocEntry]:
    """@brief Resolve each TOC entry to a likely destination page in the body.

    TOC pages themselves are excluded from anchor matching so references inside
    the TOC do not become false positives.
    """
    excluded = set(excluded_page_indexes or [])
    matched_entries: List[TocEntry] = []
    offset_observations: List[int] = []
    previous_toc_page: Optional[int] = None
    level_anchor_floors: Dict[int, int] = {}
    for entry in toc_entries:
        if (
            entry.toc_page_index is not None
            and previous_toc_page is not None
            and entry.toc_page_index > previous_toc_page + 1
        ):
            offset_observations = []
            level_anchor_floors = {}
        anchor_offset = _stable_anchor_offset(offset_observations)
        parent_anchor_floor = max(
            (
                anchor
                for level, anchor in level_anchor_floors.items()
                if level < entry.level
            ),
            default=0,
        )
        anchor_page_index, score = _find_anchor_page(
            entry,
            page_texts,
            excluded,
            page_layouts,
            anchor_offset=anchor_offset,
            minimum_page_index=parent_anchor_floor,
        )
        matched_entries.append(
            TocEntry(
                title=entry.title,
                printed_page=entry.printed_page,
                level=entry.level,
                anchor_page_index=anchor_page_index,
                anchor_match_score=score,
                toc_page_index=entry.toc_page_index,
                toc_x=entry.toc_x,
                toc_font_name=entry.toc_font_name,
            )
        )
        if (
            entry.printed_page is not None
            and anchor_page_index is not None
            and score >= 0.95
        ):
            offset_observations.append(anchor_page_index - entry.printed_page)
        if entry.toc_page_index is not None:
            previous_toc_page = entry.toc_page_index
        if anchor_page_index is not None:
            level_anchor_floors[entry.level] = anchor_page_index
            level_anchor_floors = {
                level: anchor
                for level, anchor in level_anchor_floors.items()
                if level <= entry.level
            }
    return _repair_sequence_anchors(matched_entries, len(page_texts), excluded)


def _find_anchor_page(
    entry: TocEntry,
    page_texts: Sequence[str],
    excluded_page_indexes: Sequence[int],
    page_layouts: Optional[Dict[int, Sequence[TocLayoutLine]]] = None,
    anchor_offset: Optional[int] = None,
    minimum_page_index: int = 0,
) -> Tuple[Optional[int], float]:
    """@brief Find the best body-page anchor for one TOC entry."""
    if _STRUCTURAL_PREFIX_PATTERN.match(entry.title):
        anchor_page_index, score = _find_structural_anchor_page(
            entry,
            page_texts,
            excluded_page_indexes,
            anchor_offset=anchor_offset,
            minimum_page_index=minimum_page_index,
        )
        if anchor_page_index is not None:
            return anchor_page_index, score

    query_terms = _title_query_terms(entry.title)
    if not query_terms:
        return None, 0.0

    best_page_index: Optional[int] = None
    best_score = 0.0
    start_index = max(
        _candidate_anchor_start(entry.printed_page, len(page_texts)),
        _entry_anchor_floor(entry, len(page_texts)),
        minimum_page_index,
    )
    if anchor_offset is not None and entry.printed_page is not None:
        start_index = max(
            start_index,
            min(entry.printed_page + anchor_offset - 2, len(page_texts) - 1),
        )
    for page_index in range(start_index, len(page_texts)):
        if page_index in excluded_page_indexes:
            continue
        page_text = page_texts[page_index]
        if not _normalize_space(page_text):
            continue
        score = _page_match_score(
            page_text,
            entry.title,
            query_terms,
            page_layout_lines=None if page_layouts is None else page_layouts.get(page_index),
        )
        score = _apply_anchor_distance_penalty(score, page_index, start_index)
        if score > best_score:
            best_score = score
            best_page_index = page_index
            if score >= 0.999:
                break
    if best_score < 0.55:
        return None, 0.0
    return best_page_index, round(best_score, 2)


def _repair_sequence_anchors(
    entries: Sequence[TocEntry], page_count: int, excluded_page_indexes: Sequence[int]
) -> List[TocEntry]:
    """@brief Repair weak sibling anchors when page-number sequences are coherent.

    If a lower-confidence entry sits cleanly between two strong same-level
    siblings, the function can interpolate a more plausible anchor page.
    """
    repaired = list(entries)
    excluded = set(excluded_page_indexes)
    chapter_start = 0
    for index, entry in enumerate(entries):
        if entry.level == 1:
            chapter_start = index
            continue
        if not _needs_sequence_anchor_repair(entry):
            continue
        chapter_end = _chapter_end_index(entries, index)
        inferred = _infer_anchor_from_siblings(
            entries,
            index,
            chapter_start,
            chapter_end,
            page_count,
            excluded,
        )
        if inferred is None:
            continue
        repaired[index] = TocEntry(
            title=entry.title,
            printed_page=entry.printed_page,
            level=entry.level,
            anchor_page_index=inferred,
            anchor_match_score=0.9,
            toc_page_index=entry.toc_page_index,
            toc_x=entry.toc_x,
            toc_font_name=entry.toc_font_name,
        )
    return repaired


def _needs_sequence_anchor_repair(entry: TocEntry) -> bool:
    """@brief Check whether an entry is a candidate for sibling-based repair."""
    return (
        entry.level >= 2
        and entry.printed_page is not None
        and entry.anchor_page_index is not None
        and (entry.anchor_match_score <= 0.82 or _is_short_heading(entry.title))
        and not _STRUCTURAL_PREFIX_PATTERN.match(entry.title)
    )


def _chapter_end_index(entries: Sequence[TocEntry], start_index: int) -> int:
    """@brief Find the end boundary of the current level-1 chapter group."""
    for index in range(start_index + 1, len(entries)):
        if entries[index].level == 1:
            return index
    return len(entries)


def _infer_anchor_from_siblings(
    entries: Sequence[TocEntry],
    index: int,
    chapter_start: int,
    chapter_end: int,
    page_count: int,
    excluded_page_indexes: Sequence[int],
) -> Optional[int]:
    """@brief Infer an anchor from surrounding strong siblings at the same level."""
    entry = entries[index]
    previous = _nearest_strong_sibling(entries, index, chapter_start, -1, entry.level)
    following = _nearest_strong_sibling(entries, index, chapter_end, 1, entry.level)
    if previous is None or following is None:
        return None
    if previous.printed_page is None or following.printed_page is None:
        return None
    if previous.anchor_page_index is None or following.anchor_page_index is None:
        return None
    if not (previous.printed_page < entry.printed_page < following.printed_page):
        return None
    if not (previous.anchor_page_index < following.anchor_page_index):
        return None
    if previous.anchor_page_index <= entry.anchor_page_index <= following.anchor_page_index:
        if entry.anchor_match_score > 0.82:
            return None

    estimated = previous.anchor_page_index + (entry.printed_page - previous.printed_page)
    if estimated <= previous.anchor_page_index or estimated >= following.anchor_page_index:
        return None
    if estimated < 0 or estimated >= page_count or estimated in excluded_page_indexes:
        return None

    printed_span = following.printed_page - previous.printed_page
    anchor_span = following.anchor_page_index - previous.anchor_page_index
    if printed_span != anchor_span:
        return None
    return estimated


def _nearest_strong_sibling(
    entries: Sequence[TocEntry],
    index: int,
    boundary: int,
    direction: int,
    level: int,
) -> Optional[TocEntry]:
    """@brief Scan backward or forward for a nearby strong sibling anchor."""
    if direction < 0:
        scan = range(index - 1, boundary - 1, -1)
    else:
        scan = range(index + 1, boundary)
    for cursor in scan:
        candidate = entries[cursor]
        if candidate.level < level:
            break
        if candidate.level != level:
            continue
        if candidate.anchor_page_index is None or candidate.anchor_match_score < 0.9:
            continue
        return candidate
    return None


def _find_structural_anchor_page(
    entry: TocEntry,
    page_texts: Sequence[str],
    excluded_page_indexes: Sequence[int],
    anchor_offset: Optional[int] = None,
    minimum_page_index: int = 0,
) -> Tuple[Optional[int], float]:
    """@brief Match chapter-like entries against top-of-page structural headings."""
    anchor_floor = max(
        _entry_anchor_floor(entry, len(page_texts)),
        minimum_page_index,
    )
    expected_start = max(
        _candidate_anchor_start(entry.printed_page, len(page_texts)),
        anchor_floor,
    )
    if anchor_offset is not None and entry.printed_page is not None:
        expected_start = max(
            expected_start,
            min(entry.printed_page + anchor_offset, len(page_texts) - 1),
        )
    search_start = max(anchor_floor, expected_start - 4)
    search_end = min(len(page_texts), search_start + 24)
    title_normalized = _normalize_title(entry.title)
    marker = _structural_marker(entry.title)
    heading_core = " ".join(_title_query_terms(_strip_heading_prefix(entry.title)))
    title_compact = _compact_heading_text(title_normalized)
    marker_compact = _compact_heading_text(marker)
    heading_core_compact = _compact_heading_text(heading_core)
    best_page_index: Optional[int] = None
    best_score = 0.0

    for page_index in range(search_start, search_end):
        if page_index in excluded_page_indexes:
            continue
        top_lines = _page_heading_lines(page_texts[page_index])
        normalized_top = [_normalize_title(line) for line in top_lines]
        top_window = " ".join(filter(None, normalized_top))
        if not top_window:
            continue

        score = 0.0
        compact_lines = [_compact_heading_text(line) for line in top_lines]
        compact_windows = compact_lines + [
            compact_lines[index] + compact_lines[index + 1]
            for index in range(len(compact_lines) - 1)
        ]
        starts_with_marker = bool(
            marker_compact
            and any(window.startswith(marker_compact) for window in compact_windows)
        )
        if title_compact and any(window.startswith(title_compact) for window in compact_windows):
            score = 1.0
        elif starts_with_marker:
            score = 0.88
            if heading_core_compact and any(
                window.startswith(marker_compact) and heading_core_compact in window
                for window in compact_windows
            ):
                score = 0.98
        elif title_normalized and title_normalized in top_window:
            score = 1.0
        elif marker and marker in top_window:
            score = 0.88
            if heading_core and heading_core in top_window:
                score = 0.98
            elif heading_core:
                overlap = _term_overlap_ratio(top_window, heading_core.split())
                score += min(overlap * 0.12, 0.1)
        elif heading_core:
            overlap = _term_overlap_ratio(top_window, heading_core.split())
            if overlap >= 0.75:
                score = 0.78

        if score <= 0:
            continue

        score = _apply_anchor_distance_penalty(score, page_index, expected_start)
        if score > best_score:
            best_score = score
            best_page_index = page_index
            if starts_with_marker or score >= 0.97:
                break

    if best_score >= 0.75 and best_page_index is not None:
        return best_page_index, round(best_score, 2)
    return None, 0.0


def _compact_heading_text(value: str) -> str:
    """@brief Remove separators so collapsed OCR headings remain matchable."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _candidate_anchor_start(printed_page: Optional[int], page_count: int) -> int:
    """@brief Convert a printed page hint into an initial zero-based search index."""
    if not printed_page:
        return 0
    estimated_index = max(0, printed_page - 1)
    return min(estimated_index, max(page_count - 1, 0))


def _entry_anchor_floor(entry: TocEntry, page_count: int) -> int:
    """@brief Keep an entry from matching content before its own TOC cluster."""
    if entry.toc_page_index is None:
        return 0
    return min(entry.toc_page_index + 1, max(page_count - 1, 0))


def _stable_anchor_offset(observations: Sequence[int]) -> Optional[int]:
    """@brief Return a cluster page offset after three strong matches agree."""
    counts: Dict[int, int] = {}
    for offset in observations:
        counts[offset] = counts.get(offset, 0) + 1
    if not counts:
        return None
    offset, count = max(counts.items(), key=lambda item: item[1])
    return offset if count >= 3 else None


def _page_match_score(
    page_text: str,
    title: str,
    query_terms: Sequence[str],
    page_layout_lines: Optional[Sequence[TocLayoutLine]] = None,
) -> float:
    """@brief Score how well a page appears to contain the entry heading.

    Exact and near-exact heading matches in layout windows or top-of-page text
    score highest. Broader term overlap is only used as a weaker fallback.
    """
    if _is_symbolic_command_title(title):
        raw_top_lines = _page_heading_lines(page_text)
        raw_top_window = " ".join(raw_top_lines[:12])
        if title in raw_top_window:
            return 1.0
        for window in _layout_heading_windows(page_layout_lines or []):
            if title in str(window["text"]):
                return 1.0 if window["is_style_consistent"] else 0.97
        return 0.0

    normalized_page = _normalize_title(page_text)
    title_normalized = _normalize_title(title)
    title_compact = _compact_heading_text(title_normalized)
    generic_short_title = _is_generic_short_heading(title)
    top_lines = _page_heading_lines(page_text)
    normalized_top = [_normalize_title(line) for line in top_lines]
    top_window = " ".join(filter(None, normalized_top))

    layout_windows = _layout_heading_windows(page_layout_lines or [])
    if title_normalized:
        for window in layout_windows:
            normalized_window = _normalize_title(window["text"])
            if not normalized_window:
                continue
            if _compact_heading_text(normalized_window) == title_compact:
                return 1.0 if window["is_style_consistent"] else 0.97
            if normalized_window == title_normalized:
                return 1.0 if window["is_style_consistent"] else 0.97
            if normalized_window.startswith(title_normalized) or title_normalized.startswith(normalized_window):
                if generic_short_title:
                    continue
                return 0.98 if window["is_style_consistent"] else 0.94
        if not generic_short_title and any(
            title_normalized in _normalize_title(window["text"]) for window in layout_windows
        ):
            return 0.96

    if title_normalized:
        for index, line in enumerate(normalized_top):
            if not line:
                continue
            if _compact_heading_text(line) == title_compact:
                return 1.0 if index < 6 else 0.94
            if line == title_normalized:
                return 1.0 if index < 6 else 0.94
            if line.startswith(title_normalized):
                if generic_short_title:
                    continue
                return 0.97 if index < 6 else 0.9
        if not generic_short_title and title_normalized in top_window:
            return 0.9

    heading_terms = _title_query_terms(_strip_heading_prefix(title))
    if heading_terms:
        heading_phrase = " ".join(heading_terms)
        if heading_phrase:
            for window in layout_windows:
                normalized_window = _normalize_title(window["text"])
                if normalized_window == heading_phrase:
                    return 0.97 if window["is_style_consistent"] else 0.93
                if normalized_window.startswith(heading_phrase) or heading_phrase in normalized_window:
                    return 0.95 if window["is_style_consistent"] else 0.91
            for index, line in enumerate(normalized_top):
                if line == heading_phrase:
                    return 0.95 if index < 8 else 0.88
                if line.startswith(heading_phrase):
                    return 0.9 if index < 8 else 0.84

    page_words = set(_WORD_PATTERN.findall(top_window))
    overlap = sum(1 for term in query_terms if term in page_words)
    if not query_terms:
        return 0.0
    coverage = overlap / len(query_terms)
    if coverage == 0:
        return 0.0
    line_bonus = 0.1 if normalized_top and normalized_top[0].startswith(query_terms[0]) else 0.0
    return min(coverage + line_bonus, 0.82)


def _apply_anchor_distance_penalty(score: float, page_index: int, start_index: int) -> float:
    """@brief Discount otherwise-good matches that occur far past the expected page."""
    if score <= 0 or page_index <= start_index + 12:
        return score
    distance = page_index - start_index
    penalty = min(max(distance - 12, 0) * 0.005, 0.35)
    return max(0.0, score - penalty)


def _title_query_terms(title: str) -> List[str]:
    """@brief Extract significant query tokens from a normalized title."""
    if _is_symbolic_command_title(title):
        return [title]
    normalized = _normalize_title(title)
    terms = [term for term in _WORD_PATTERN.findall(normalized) if len(term) > 2]
    if len(terms) >= 2:
        return terms
    return _WORD_PATTERN.findall(normalized)


def _strip_heading_prefix(title: str) -> str:
    """@brief Remove leading Chapter/Appendix/Section/Part markers from a title."""
    return _HEADING_PREFIX_PATTERN.sub("", title).strip()


def is_confident_bookmark_candidate(entry: TocEntry, threshold: float = 0.85) -> bool:
    """@brief Decide whether an anchored entry is suitable for bookmark writing.

    Generic or weak single-term titles are filtered out unless they match known
    structural, command-reference, or chess-specific patterns.
    """
    if entry.anchor_page_index is None or entry.anchor_match_score < threshold:
        if not _is_chess_style_heading(entry.title):
            return False
        if entry.anchor_page_index is None or entry.anchor_match_score < 0.72:
            return False
    if (
        entry.level == 1
        and entry.anchor_match_score >= 0.95
        and _normalize_title(entry.title) not in {"index", "glossary", "summary"}
    ):
        return True
    if _is_symbolic_command_title(entry.title) and entry.anchor_match_score >= threshold:
        return True
    if _is_allowed_single_word_heading(entry.title, entry.anchor_match_score):
        return True
    significant_terms = _title_query_terms(entry.title)
    if len(significant_terms) >= 2:
        return True
    if _STRUCTURAL_PREFIX_PATTERN.match(entry.title):
        return True
    if _is_command_reference_heading(entry.title):
        return True
    if _is_chess_style_heading(entry.title):
        return True
    return bool(re.search(r"\d", entry.title) and significant_terms)


def _page_heading_lines(page_text: str, limit: int = 30) -> List[str]:
    """@brief Return the top non-empty lines most likely to contain page headings."""
    return [line.strip() for line in page_text.splitlines() if line.strip()][:limit]


def _layout_heading_windows(
    page_layout_lines: Sequence[TocLayoutLine], limit: int = 40
) -> List[Dict[str, object]]:
    """@brief Build single- and double-line heading windows from page layout data."""
    top_lines = list(page_layout_lines[:limit])
    windows: List[Dict[str, object]] = []
    for index, line in enumerate(top_lines):
        windows.append({"text": line.text, "is_style_consistent": True})
        if index + 1 >= len(top_lines):
            continue
        neighbor = top_lines[index + 1]
        if not _can_merge_heading_lines(line, neighbor):
            continue
        windows.append(
            {
                "text": f"{line.text} {neighbor.text}",
                "is_style_consistent": _share_heading_style(line, neighbor),
            }
        )
    return windows


def _can_merge_heading_lines(first: TocLayoutLine, second: TocLayoutLine) -> bool:
    """@brief Check whether adjacent layout lines look like one wrapped heading."""
    if first.y - second.y > 28:
        return False
    if abs(first.x - second.x) > 14:
        return False
    return _share_heading_style(first, second)


def _share_heading_style(first: TocLayoutLine, second: TocLayoutLine) -> bool:
    """@brief Compare font family, bucket, and size for heading continuity."""
    if _font_bucket(first.font_name) != _font_bucket(second.font_name):
        return False
    if abs(first.font_size - second.font_size) > 0.75:
        return False
    return _font_family(first.font_name) == _font_family(second.font_name)


def _extract_reasonable_title(title: str) -> str:
    """@brief Reduce a noisy title to the most readable fragment available."""
    if not title:
        return title
    if _STRUCTURAL_PREFIX_PATTERN.match(title):
        return title
    title = _trim_leading_move_sequence(title)
    if _is_reasonable_title(title):
        return title

    candidates = []
    for match in _READABLE_FRAGMENT_PATTERN.finditer(title):
        candidate = _normalize_space(match.group(0).strip("-: .,'\"`~_•·"))
        if _is_readable_fragment(candidate):
            candidates.append((candidate, match.start()))

    if not candidates:
        return title

    best_candidate = max(candidates, key=lambda item: (_fragment_score(item[0]), item[1]))
    if _fragment_score(best_candidate[0]) >= 2.0:
        return best_candidate[0]
    return title


def _is_reasonable_title(title: str) -> bool:
    """@brief Decide whether a title already looks readable enough to keep."""
    if _STRUCTURAL_PREFIX_PATTERN.match(title):
        return True
    return _is_readable_fragment(title) and len(title) <= 80


def _is_readable_fragment(value: str) -> bool:
    """@brief Check whether a text fragment looks like a human-readable heading."""
    words = re.findall(r"[A-Za-z][A-Za-z']*", value)
    if len(words) < 2:
        return False
    move_tokens = sum(1 for token in value.split() if _looks_like_move_notation(token))
    symbol_count = sum(1 for char in value if not (char.isalnum() or char.isspace() or char == "'"))
    return move_tokens == 0 and symbol_count <= max(4, len(value) // 6)


def _fragment_score(value: str) -> float:
    """@brief Score candidate title fragments so the cleanest one can be chosen."""
    words = re.findall(r"[A-Za-z][A-Za-z']*", value)
    digit_prefix = 0.4 if re.match(r"^\d+\s+[A-Z]", value) else 0.0
    return len(words) + digit_prefix - sum(1 for token in value.split() if _looks_like_move_notation(token))


def _looks_like_move_notation(token: str) -> bool:
    """@brief Detect chess move notation that should not dominate title cleanup."""
    token = token.strip("()[]{}.,;:'\"")
    return bool(
        re.match(r"^(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8]|[a-h][1-8]|[a-h]x[a-h][1-8]|O-O(?:-O)?)[+#]?$", token)
    )


def _trim_leading_move_sequence(title: str) -> str:
    """@brief Remove leading chess-move prefixes from noisy opening titles."""
    trimmed = _MOVE_PREFIX_PATTERN.sub("", title).strip(" -")
    return _normalize_space(trimmed) or title


def _looks_like_major_topic(title: str) -> bool:
    """@brief Recognize broad headings that should usually behave as level-2 topics."""
    lowered = title.lower()
    if lowered.startswith(("getting ", "setting up ", "how ", "overview ", "overview of ", "summary", "troubleshooting ", "understanding ", "backing ", "changing ", "loading ", "protecting ")):
        return True
    if "config.sys" in lowered or "autoexec.bat" in lowered:
        return True
    return any(
        keyword in lowered
        for keyword in ("tutorial", "overview", "introduction", "information", "basics", "features", "procedures")
    )


def _is_chess_style_heading(title: str) -> bool:
    """@brief Recognize chess-book style section titles with opening terminology."""
    lowered = title.lower()
    if any(keyword in lowered for keyword in _CHESS_HEADING_KEYWORDS):
        return True
    return bool(re.match(r"^[a-f]\.\s", lowered))


def _looks_like_subtopic(title: str) -> bool:
    """@brief Recognize verbs and patterns that usually indicate a child topic."""
    lowered = title.lower()
    return lowered.startswith(
        (
            "editing ",
            "viewing ",
            "creating ",
            "deleting ",
            "running ",
            "using ",
            "configuring ",
            "sample ",
        )
    )


def _structural_marker(title: str) -> str:
    """@brief Extract a normalized structural marker such as ``chapter 3``."""
    match = re.match(r"^(chapter|appendix|section|part)\s+([a-z0-9ivxlcdm.-]+)", title, re.IGNORECASE)
    if not match:
        return ""
    return _normalize_title(match.group(1) + " " + match.group(2))


def _term_overlap_ratio(haystack: str, terms: Sequence[str]) -> float:
    """@brief Measure how many query terms appear inside normalized text."""
    haystack_words = set(_WORD_PATTERN.findall(haystack))
    if not terms:
        return 0.0
    return sum(1 for term in terms if term in haystack_words) / len(terms)


def _match_layout_line(
    raw_line: str,
    title: str,
    page_layouts: Sequence[TocLayoutLine],
) -> Optional[TocLayoutLine]:
    """@brief Find the best matching layout line for a parsed text TOC row."""
    normalized_raw = _normalize_title(raw_line)
    normalized_title = _normalize_title(title)
    best_line: Optional[TocLayoutLine] = None
    best_score = 0.0
    for layout_line in page_layouts:
        normalized_layout = _normalize_title(layout_line.text)
        layout_title, _layout_page = _split_trailing_page_number(layout_line.text)
        normalized_layout_title = _normalize_title(layout_title)
        if not normalized_layout:
            continue
        score = 0.0
        if normalized_raw and normalized_layout == normalized_raw:
            score = 1.0
        elif normalized_title and normalized_layout_title == normalized_title:
            score = 0.98
        elif normalized_raw and normalized_raw in normalized_layout:
            score = 0.95
        elif normalized_title and normalized_title in normalized_layout:
            score = 0.9
        if score > best_score:
            best_score = score
            best_line = layout_line
    if best_score >= 0.85:
        return best_line
    return None


def _merge_layout_row_fragments(
    page_layouts: Sequence[TocLayoutLine],
) -> List[TocLayoutLine]:
    """@brief Merge same-row layout fragments into fuller line records."""
    if not page_layouts:
        return []
    merged: List[TocLayoutLine] = []
    lines = sorted(page_layouts, key=lambda line: (-line.y, line.x))
    index = 0
    while index < len(lines):
        row_group = [lines[index]]
        cursor = index + 1
        while cursor < len(lines) and abs(lines[index].y - lines[cursor].y) <= 6:
            row_group.append(lines[cursor])
            cursor += 1
        row_group.sort(key=lambda line: line.x)
        text_parts = [line.text for line in row_group]
        x = min(line.x for line in row_group)
        y = max(line.y for line in row_group)
        font_name = next((line.font_name for line in row_group if line.font_name), "")
        font_size = max(line.font_size for line in row_group)
        merged.append(
            TocLayoutLine(
                text=_normalize_space(" ".join(text_parts)),
                x=x,
                y=y,
                font_size=font_size,
                font_name=font_name,
            )
        )
        index = cursor
    return merged


def _looks_like_layout_toc_page(
    page_text: str, page_layouts: Sequence[TocLayoutLine]
) -> bool:
    """@brief Decide whether layout metadata indicates a TOC page."""
    has_header = any(
        _normalize_title(line.text) in {"contents", "table of contents"}
        for line in page_layouts[:4]
    )
    first_lines = " ".join(page_text.splitlines()[:3])
    first_text = _normalize_title(first_lines)
    has_text_header = (
        first_text.startswith("contents")
        or first_text.startswith("table of contents")
    )
    if not has_header and not has_text_header:
        return False
    return len(_layout_toc_title_lines(page_text, page_layouts)) >= 4


def _looks_like_layout_toc_continuation_page(
    page_text: str,
    page_layouts: Sequence[TocLayoutLine],
) -> bool:
    """@brief Decide whether a page continues a layout-derived TOC cluster."""
    title_lines = _layout_toc_title_lines(page_text, page_layouts)
    if len(title_lines) < 4:
        return False
    numbered_titles = [
        line for line in title_lines if _split_trailing_page_number(line.text)[1] is not None
    ]
    return len(numbered_titles) >= 4


def _layout_toc_title_lines(
    page_text: str, page_layouts: Sequence[TocLayoutLine]
) -> List[TocLayoutLine]:
    """@brief Keep only layout lines that plausibly represent TOC entry titles."""
    titles: List[TocLayoutLine] = []
    if not page_layouts:
        return titles
    lower_page_text = page_text.lower()
    for line in page_layouts:
        text = _normalize_space(line.text)
        if _is_symbolic_command_title(text):
            titles.append(line)
            continue
        normalized = _normalize_title(text)
        if not normalized:
            continue
        if normalized in {"contents", "table of contents"}:
            continue
        if re.fullmatch(r"(?:contents|table of contents)\s+\d+", normalized):
            continue
        if re.fullmatch(r"\d+\s+[A-Z][A-Z ]{8,}", text):
            continue
        if "reference manual" in normalized or normalized == "1991 jp software inc":
            continue
        if re.fullmatch(r"[0-9\"'` .©*^]+", text):
            continue
        if line.x > 1000:
            continue
        if line.y < 120:
            continue
        if normalized.startswith("chapter ") or normalized.startswith("appendix "):
            titles.append(line)
            continue
        if re.search(r"\b\d{1,4}\s*$", text) and len(normalized) > 3:
            titles.append(line)
            continue
        if _is_reasonable_layout_toc_title(text, lower_page_text):
            titles.append(line)
    return titles


def _is_reasonable_layout_toc_title(text: str, lower_page_text: str) -> bool:
    """@brief Apply lightweight sanity checks to a layout-derived TOC title."""
    if _is_symbolic_command_title(text):
        return True
    normalized = _normalize_title(text)
    if len(normalized) < 4:
        return False
    if len(text) <= 2:
        return False
    if text.count(" ") == 0 and len(text) > 20:
        return False
    words = _WORD_PATTERN.findall(normalized)
    if len(words) < 1:
        return False
    if len(words) == 1:
        return (
            normalized in {"contents", "glossary", "index"}
            or text.isupper()
            or text[:1].isupper()
        )
    if any(char.isdigit() for char in text):
        return True
    if normalized in lower_page_text:
        return True
    return _is_readable_fragment(text)


def _extract_sequential_page_numbers(
    page_text: str,
    max_page_number: Optional[int] = None,
) -> List[int]:
    """@brief Recover a plausible monotonic page-number sequence from page text."""
    tail_numbers = [int(value) for value in re.findall(r"(?<!\d)\d{1,4}(?!\d)", page_text)]
    if max_page_number is not None:
        tail_numbers = [value for value in tail_numbers if 0 < value <= max_page_number]
    if not tail_numbers:
        return []
    best: List[int] = []
    for start in range(len(tail_numbers)):
        seed = tail_numbers[start]
        candidate = [seed]
        previous = seed
        for value in tail_numbers[start + 1 :]:
            if value < previous:
                continue
            if value - previous > 50:
                continue
            candidate.append(value)
            previous = value
        if len(candidate) > len(best):
            best = candidate
    return best or tail_numbers


def _extract_layout_page_numbers(
    page_layouts: Sequence[TocLayoutLine],
    max_page_number: Optional[int] = None,
) -> List[int]:
    """@brief Recover page numbers from right-edge or clustered layout lines."""
    right_edge_values = [
        (line.y, int(text))
        for line in page_layouts
        if (text := _normalize_space(line.text)).isdigit()
        and int(text) > 0
        and (max_page_number is None or int(text) <= max_page_number)
        and line.x > 1200
    ]
    if len(right_edge_values) >= 3:
        return [value for _y, value in sorted(right_edge_values, key=lambda item: -item[0])]

    candidates: List[int] = []
    for line in page_layouts:
        text = _normalize_space(line.text)
        if not re.fullmatch(r"[0-9 ]+", text):
            continue
        values = [
            int(value)
            for value in re.findall(r"\d{1,4}", text)
            if int(value) > 0 and (max_page_number is None or int(value) <= max_page_number)
        ]
        if len(values) >= 3:
            candidates.extend(values)
    return candidates


def _split_trailing_page_number(text: str) -> Tuple[str, Optional[int]]:
    """@brief Split a trailing page number away from a TOC title line."""
    match = re.match(r"^(?P<title>.+?)\s+(?P<page>\d{1,4}|[ivxlcdmIVXLCDM]+)\s*$", text)
    if not match:
        return text, None
    return match.group("title"), _parse_page_number(match.group("page"))


def _build_layout_bands(toc_page_layouts: Dict[int, Sequence[TocLayoutLine]]) -> List[float]:
    """@brief Cluster TOC X positions into indentation bands for level inference."""
    x_values = []
    for lines in toc_page_layouts.values():
        for line in lines:
            normalized = _normalize_title(line.text)
            if normalized and _TOC_LINE_PATTERN.match(_normalize_toc_line(line.text)):
                x_values.append(line.x)
    if not x_values:
        return []
    bands: List[float] = []
    for x in sorted(x_values):
        if not bands or abs(bands[-1] - x) > 6:
            bands.append(x)
        else:
            bands[-1] = (bands[-1] + x) / 2
    return bands


def _level_from_layout(
    layout_line: TocLayoutLine,
    layout_bands: Sequence[float],
    structural_context_level: int,
) -> Optional[int]:
    """@brief Infer a level directly from layout indentation and font emphasis."""
    if not layout_bands:
        return None
    band_index = min(
        range(len(layout_bands)),
        key=lambda index: abs(layout_bands[index] - layout_line.x),
    )
    if "/Bold" in layout_line.font_name and band_index == 0:
        return 1
    if band_index == 0:
        return max(2, structural_context_level)
    return min(max(2, structural_context_level) + band_index, 4)


def _reconcile_toc_layout_levels(entries: Sequence[TocEntry]) -> List[TocEntry]:
    """@brief Normalize suspicious TOC levels using same-page layout peer signals.

    This pass fixes a common failure mode where entries drift between level 2
    and level 3 even though their X position and font treatment show they are
    part of the same TOC band.
    """
    reconciled: List[TocEntry] = []
    level2_peers: List[TocEntry] = []
    current_level2_entry: Optional[TocEntry] = None
    for entry in entries:
        if entry.level == 1:
            level2_peers = []
            current_level2_entry = None
            reconciled.append(entry)
            continue
        if entry.level == 2:
            normalized_level = entry.level
            if _looks_like_child_band_entry(entry, current_level2_entry):
                normalized_level = 3
            reconciled_entry = TocEntry(
                title=entry.title,
                printed_page=entry.printed_page,
                level=normalized_level,
                anchor_page_index=entry.anchor_page_index,
                anchor_match_score=entry.anchor_match_score,
                toc_page_index=entry.toc_page_index,
                toc_x=entry.toc_x,
                toc_font_name=entry.toc_font_name,
            )
            if normalized_level == 2:
                level2_peers.append(reconciled_entry)
                current_level2_entry = reconciled_entry
            reconciled.append(reconciled_entry)
            continue
        normalized_level = entry.level
        if _matches_level2_peer(entry, level2_peers):
            normalized_level = 2
            promoted_entry = TocEntry(
                title=entry.title,
                printed_page=entry.printed_page,
                level=2,
                anchor_page_index=entry.anchor_page_index,
                anchor_match_score=entry.anchor_match_score,
                toc_page_index=entry.toc_page_index,
                toc_x=entry.toc_x,
                toc_font_name=entry.toc_font_name,
            )
            level2_peers.append(promoted_entry)
            current_level2_entry = promoted_entry
        reconciled.append(
            TocEntry(
                title=entry.title,
                printed_page=entry.printed_page,
                level=normalized_level,
                anchor_page_index=entry.anchor_page_index,
                anchor_match_score=entry.anchor_match_score,
                toc_page_index=entry.toc_page_index,
                toc_x=entry.toc_x,
                toc_font_name=entry.toc_font_name,
            )
        )
    return reconciled


def _apply_two_tier_typographic_hierarchy(entries: Sequence[TocEntry]) -> List[TocEntry]:
    """@brief Recover bold-parent/plain-child hierarchy from a flat TOC.

    The pass is deliberately narrow: it only changes a contiguous TOC cluster
    when every extracted row is currently level 1 and multiple bold and plain
    rows demonstrate a consistent indentation relationship on the same page.
    This keeps typography secondary to established text-based hierarchy.
    """
    result: List[TocEntry] = []
    for cluster in _split_toc_entry_clusters(entries):
        if not _is_confident_two_tier_cluster(cluster):
            result.extend(cluster)
            continue
        for entry in cluster:
            result.append(
                TocEntry(
                    title=entry.title,
                    printed_page=entry.printed_page,
                    level=1 if _font_bucket(entry.toc_font_name) == "bold" else 2,
                    anchor_page_index=entry.anchor_page_index,
                    anchor_match_score=entry.anchor_match_score,
                    toc_page_index=entry.toc_page_index,
                    toc_x=entry.toc_x,
                    toc_font_name=entry.toc_font_name,
                )
            )
    return result


def _split_toc_entry_clusters(entries: Sequence[TocEntry]) -> List[List[TocEntry]]:
    """@brief Group entries whose TOC pages form contiguous page runs."""
    clusters: List[List[TocEntry]] = []
    previous_page: Optional[int] = None
    for entry in entries:
        if (
            not clusters
            or (
                entry.toc_page_index is not None
                and previous_page is not None
                and entry.toc_page_index > previous_page + 1
            )
        ):
            clusters.append([])
        clusters[-1].append(entry)
        if entry.toc_page_index is not None:
            previous_page = entry.toc_page_index
    return clusters


def _is_confident_two_tier_cluster(entries: Sequence[TocEntry]) -> bool:
    """@brief Verify that font weight and indentation define exactly two tiers."""
    if len(entries) < 4 or any(entry.level != 1 for entry in entries):
        return False
    bold = [entry for entry in entries if _font_bucket(entry.toc_font_name) == "bold"]
    plain = [entry for entry in entries if _font_bucket(entry.toc_font_name) == "plain"]
    if len(bold) < 2 or len(plain) < 2:
        return False
    if any(entry.toc_x is None or not entry.toc_font_name for entry in entries):
        return False

    comparable_pages = 0
    page_indexes = {entry.toc_page_index for entry in entries}
    for page_index in page_indexes:
        page_bold_x = sorted(
            entry.toc_x
            for entry in bold
            if entry.toc_page_index == page_index and entry.toc_x is not None
        )
        page_plain_x = sorted(
            entry.toc_x
            for entry in plain
            if entry.toc_page_index == page_index and entry.toc_x is not None
        )
        if not page_bold_x or not page_plain_x:
            continue
        offset = _median(page_plain_x) - _median(page_bold_x)
        if not 6 <= offset <= 30:
            return False
        comparable_pages += 1
    return comparable_pages >= 1


def _median(values: Sequence[float]) -> float:
    """@brief Return the median of a non-empty sorted or unsorted sequence."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _matches_level2_peer(entry: TocEntry, peers: Sequence[TocEntry]) -> bool:
    """@brief Check whether an entry visually aligns with known level-2 peers."""
    if entry.toc_page_index is None or entry.toc_x is None:
        return False
    for peer in peers:
        if peer.toc_page_index != entry.toc_page_index:
            continue
        if peer.toc_x is None:
            continue
        if abs(peer.toc_x - entry.toc_x) > 4:
            continue
        if _font_bucket(peer.toc_font_name) != _font_bucket(entry.toc_font_name):
            continue
        return True
    return False


def _looks_like_child_band_entry(
    entry: TocEntry, current_level2_entry: Optional[TocEntry]
) -> bool:
    """@brief Detect a visually indented child that should stay under level 2."""
    if current_level2_entry is None:
        return False
    if entry.toc_page_index != current_level2_entry.toc_page_index:
        return False
    if entry.toc_x is None or current_level2_entry.toc_x is None:
        return False
    if _font_bucket(entry.toc_font_name) != _font_bucket(current_level2_entry.toc_font_name):
        return False
    return entry.toc_x - current_level2_entry.toc_x > 4


def _font_bucket(font_name: str) -> str:
    """@brief Collapse font names into coarse bold/plain style buckets."""
    return "bold" if "Bold" in font_name else "plain"


def _font_family(font_name: str) -> str:
    """@brief Extract a stable font-family token from a PDF font name."""
    family = font_name.rsplit("/", 1)[-1]
    family = family.split("-", 1)[0]
    return family.lower()


def _is_generic_short_heading(title: str) -> bool:
    """@brief Detect short generic headings that frequently overmatch anchors."""
    terms = _title_query_terms(title)
    if len(terms) > 2:
        return False
    lowered = _normalize_title(title)
    return lowered in {
        "keyboard layouts",
        "character set tables",
        "commands",
        "summary",
        "files",
        "directories",
        "drives",
        "procedures",
        "overview",
    }


def _is_command_reference_heading(title: str) -> bool:
    """@brief Detect all-caps command-style headings from reference manuals."""
    if _is_symbolic_command_title(title):
        return True
    compact = title.replace(" ", "")
    if len(compact) > 18:
        return False
    if not re.fullmatch(r"[A-Z0-9?/\-_. ]+", title):
        return False
    alpha_count = sum(1 for char in compact if char.isalpha())
    return alpha_count >= 2


def _is_symbolic_command_title(title: str) -> bool:
    return title.strip() == "?"


def _is_short_heading(title: str) -> bool:
    return len(_title_query_terms(title)) <= 1


def _is_allowed_single_word_heading(title: str, score: float) -> bool:
    terms = _title_query_terms(title)
    if len(terms) != 1 or score < 0.9:
        return False
    lowered = _normalize_title(title)
    if lowered in {
        "index",
        "glossary",
        "summary",
        "hardware",
        "software",
        "memory",
        "video",
        "aliases",
        "conclusion",
        "examples",
    }:
        return False
    return len(terms[0]) >= 5
