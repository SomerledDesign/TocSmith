from __future__ import annotations

"""@file
@brief Conservative page cropping and watermark finishing for generated PDFs.

Oversized pages are cropped only when their PDF boxes or stroked vector crop
marks provide a credible inner page rectangle. Every page receives a small,
centered footer watermark inside its final visible box.
"""

import logging
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple


_TARGET_PAGE_SIZES = ((396.0, 612.0), (612.0, 792.0))
_STANDARD_TOLERANCE = 6.0
_MAX_CROP_MARGIN = 144.0
_MIN_CROP_MARGIN = 3.0
DEFAULT_WATERMARK = "TocSmith"
## @brief Page boundary boxes rewritten as direct rectangles before finishing.
_PAGE_BOX_KEYS = ("/MediaBox", "/CropBox", "/BleedBox", "/TrimBox", "/ArtBox")
## @brief Boxes a page may inherit from an ancestor /Pages node (PDF 1.7, 7.7.3.4).
_INHERITABLE_BOX_KEYS = ("/MediaBox", "/CropBox")
## @brief Media box assumed when a page has no usable one (US Letter, portrait).
_FALLBACK_MEDIA_BOX = (0.0, 0.0, 612.0, 792.0)
## @brief Guard against cyclic or absurdly deep /Parent chains.
_MAX_PARENT_DEPTH = 64

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinishStats:
    """@brief Counts produced by the PDF finishing pass."""

    cropped_page_count: int = 0
    watermarked_page_count: int = 0
    ## @brief Zero-based page indexes left unfinished, each with the reason.
    skipped_pages: Tuple[Tuple[int, str], ...] = ()
    ## @brief Box repairs made before finishing (for example, an assumed Letter
    #  media box), each as a zero-based page index and a short description.
    box_notes: Tuple[Tuple[int, str], ...] = ()


def finish_pdf_pages(
    pages: Iterable[Any], watermark: str = DEFAULT_WATERMARK
) -> FinishStats:
    """@brief Crop credibly marked oversized pages and watermark every page.

    Page boxes are first rewritten as direct rectangles (see
    normalize_page_boxes()), so indirect or inherited boxes on writer pages
    cannot crash pypdf. A page that still fails is left unfinished, recorded in
    FinishStats.skipped_pages and logged as a warning; the other pages are
    finished as usual.

    @param pages     Writable pypdf pages, normally ``PdfWriter.pages``.
    @param watermark Footer text; an empty string disables watermarking.
    @return Counts of cropped and watermarked pages, plus skipped pages and box
            repairs.
    """
    page_list = list(pages)
    box_notes: List[Tuple[int, str]] = []
    skipped: List[Tuple[int, str]] = []
    unusable = set()
    for index, page in enumerate(page_list):
        try:
            box_notes.extend((index, note) for note in normalize_page_boxes(page))
        except Exception as exc:
            unusable.add(index)
            skipped.append((index, f"page boxes unreadable: {_describe(exc)}"))

    usable_pages = [page for index, page in enumerate(page_list) if index not in unusable]
    try:
        target_size = _infer_target_page_size(usable_pages)
    except Exception as exc:
        _LOGGER.warning(
            "TocSmith: could not infer the page format (%s); assuming US Letter.",
            _describe(exc),
        )
        target_size = (612.0, 792.0)

    cropped = 0
    watermarked = 0
    for index, page in enumerate(page_list):
        if index in unusable:
            continue
        try:
            crop_box = _detect_crop_box(page, target_size)
            if crop_box is not None:
                _apply_crop_box(page, crop_box)
            if getattr(page, "rotation", 0):
                page.transfer_rotation_to_content()
            if watermark:
                _add_footer_watermark(page, watermark)
        except Exception as exc:
            skipped.append((index, _describe(exc)))
            continue
        if crop_box is not None:
            cropped += 1
        if watermark:
            watermarked += 1

    skipped.sort()
    for index, reason in skipped:
        _LOGGER.warning(
            "TocSmith: finishing failed on page %d, left without a watermark: %s",
            index + 1,
            reason,
        )
    return FinishStats(cropped, watermarked, tuple(skipped), tuple(box_notes))


def normalize_page_boxes(page: Any) -> List[str]:
    """@brief Rewrite a page's boundary boxes as direct, resolved rectangles.

    pypdf 6.18.1 resolves an indirect box through ``page.pdf``, which is
    ``None`` for pages copied into a ``PdfWriter``, so reading ``mediabox`` on
    such a page raises ``AttributeError``. This resolves each box through its
    own reference (or an ancestor /Pages node for /MediaBox and /CropBox),
    validates it, and stores a direct rectangle on the page, so later pypdf
    calls (``cropbox``, ``merge_page``, rotation transfer) see plain arrays.

    A missing or invalid /MediaBox becomes US Letter; an invalid optional box
    is removed, which makes viewers fall back to the media or crop box as the
    PDF specification requires.

    @param page A writable pypdf page dictionary.
    @return Human-readable notes for every repair made (empty when the page was
            already well formed apart from indirect references).
    """
    from pypdf.generic import NameObject, RectangleObject

    notes: List[str] = []
    for key in _PAGE_BOX_KEYS:
        present, raw = _lookup_page_box(page, key, key in _INHERITABLE_BOX_KEYS)
        box = _coerce_box(raw) if present else None
        if box is None:
            if key == "/MediaBox":
                box = _FALLBACK_MEDIA_BOX
                notes.append(
                    "missing /MediaBox; assumed US Letter"
                    if not present
                    else "invalid /MediaBox; assumed US Letter"
                )
            else:
                if present:
                    notes.append(f"invalid {key} removed")
                    if key in page:
                        del page[NameObject(key)]
                continue
        page[NameObject(key)] = RectangleObject(box)
    return notes


def _lookup_page_box(page: Any, key: str, inherit: bool) -> Tuple[bool, Any]:
    """@brief Find a usable box entry on the page or, if inheritable, an ancestor.

    The page's own value wins when it is usable. When it is missing, broken or
    malformed and the key is inheritable, the nearest ancestor /Pages node with
    a usable value supplies it.

    @param page    Page dictionary to start from.
    @param key     Box name such as ``/MediaBox``.
    @param inherit Whether to walk the /Parent chain.
    @return ``(present, raw_value)``. ``present`` is true when the page or an
            ancestor names the key at all; ``raw_value`` is unresolved and is
            the page's own (possibly unusable) value when nothing usable exists.
    """
    own = _raw_get(page, key)
    present = own is not None
    node: Any = page
    seen = set()
    for _depth in range(_MAX_PARENT_DEPTH):
        if node is None or id(node) in seen:
            break
        seen.add(id(node))
        raw = _raw_get(node, key)
        if raw is not None:
            present = True
            if _coerce_box(raw) is not None:
                return True, raw
        if not inherit:
            break
        node = _resolve(_raw_get(node, "/Parent"))
    return present, own


def _raw_get(node: Any, key: str) -> Any:
    """@brief Read a dictionary entry without letting pypdf resolve it."""
    try:
        return dict.get(node, key)
    except TypeError:
        getter = getattr(node, "get", None)
        return getter(key) if getter is not None else None


def _resolve(value: Any) -> Any:
    """@brief Follow indirect references through the document that owns them.

    @return The direct object, or ``None`` when the reference is broken or
            points at the PDF null object.
    """
    from pypdf.generic import IndirectObject, NullObject

    for _step in range(_MAX_PARENT_DEPTH):
        if not isinstance(value, IndirectObject):
            break
        try:
            value = value.get_object()
        except Exception:
            return None
    if isinstance(value, (IndirectObject, NullObject)):
        return None
    return value


def _coerce_box(raw: Any) -> Optional[Tuple[float, float, float, float]]:
    """@brief Turn a raw box value into ``(left, bottom, right, top)``.

    Corner order is normalized and every number may itself be indirect.
    Arrays longer than four values keep their first four, matching pypdf.

    @return The rectangle, or ``None`` if the value is not a usable box.
    """
    value = _resolve(raw)
    if value is None or isinstance(value, (str, bytes)):
        return None
    try:
        numbers = [float(_resolve(item)) for item in list(value)[:4]]
    except (TypeError, ValueError):
        return None
    if len(numbers) != 4:
        return None
    x1, y1, x2, y2 = numbers
    box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    if _box_area(box) <= 0:
        return None
    return box


def _describe(exc: BaseException) -> str:
    """@brief Format an exception as ``Type: message`` for logs."""
    message = str(exc)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _detect_crop_box(
    page: Any, target_size: Tuple[float, float]
) -> Optional[Tuple[float, float, float, float]]:
    """@brief Return a credible crop rectangle for an oversized page, if any."""
    media = _box_tuple(page.mediabox)
    if not _is_larger_than_target(media, target_size):
        return None

    explicit_candidates: List[Tuple[float, float, float, float]] = []
    for key in ("/TrimBox", "/CropBox"):
        raw_box = page.get(key)
        if raw_box is None:
            continue
        candidate = _box_tuple(raw_box.get_object())
        if _is_credible_inner_box(candidate, media, target_size):
            explicit_candidates.append(candidate)
    if explicit_candidates:
        return min(explicit_candidates, key=_box_area)

    return _detect_vector_crop_box(page, media, target_size)


def _is_larger_than_target(
    box: Sequence[float], target_size: Tuple[float, float]
) -> bool:
    """@brief Check whether a page exceeds the inferred document format."""
    width = box[2] - box[0]
    height = box[3] - box[1]
    target_width, target_height = _orient_size(target_size, width, height)
    return (
        width > target_width + _STANDARD_TOLERANCE
        or height > target_height + _STANDARD_TOLERANCE
    )


def _detect_vector_crop_box(
    page: Any,
    media: Sequence[float],
    target_size: Tuple[float, float],
) -> Optional[Tuple[float, float, float, float]]:
    """@brief Infer trim bounds from stroked rectangles or corner crop marks."""
    segments, rectangles = _stroked_vector_geometry(page)
    rectangle_candidates = [
        rectangle
        for rectangle in rectangles
        if _is_credible_inner_box(rectangle, media, target_size)
    ]
    if rectangle_candidates:
        return max(rectangle_candidates, key=_box_area)

    left, bottom, right, top = media
    vertical: List[Tuple[float, float, float]] = []
    horizontal: List[Tuple[float, float, float]] = []
    for x1, y1, x2, y2 in segments:
        if abs(x1 - x2) <= 1.5:
            length = abs(y2 - y1)
            if _MIN_CROP_MARGIN <= length <= _MAX_CROP_MARGIN and (
                max(y1, y2) <= bottom + _MAX_CROP_MARGIN
                or min(y1, y2) >= top - _MAX_CROP_MARGIN
            ):
                vertical.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2)))
        elif abs(y1 - y2) <= 1.5:
            length = abs(x2 - x1)
            if _MIN_CROP_MARGIN <= length <= _MAX_CROP_MARGIN and (
                max(x1, x2) <= left + _MAX_CROP_MARGIN
                or min(x1, x2) >= right - _MAX_CROP_MARGIN
            ):
                horizontal.append(((y1 + y2) / 2, min(x1, x2), max(x1, x2)))

    crop_left = _supported_coordinate(
        [x for x, _y1, _y2 in vertical if left + _MIN_CROP_MARGIN <= x <= left + _MAX_CROP_MARGIN]
    )
    crop_right = _supported_coordinate(
        [x for x, _y1, _y2 in vertical if right - _MAX_CROP_MARGIN <= x <= right - _MIN_CROP_MARGIN]
    )
    crop_bottom = _supported_coordinate(
        [y for y, _x1, _x2 in horizontal if bottom + _MIN_CROP_MARGIN <= y <= bottom + _MAX_CROP_MARGIN]
    )
    crop_top = _supported_coordinate(
        [y for y, _x1, _x2 in horizontal if top - _MAX_CROP_MARGIN <= y <= top - _MIN_CROP_MARGIN]
    )
    if None in (crop_left, crop_bottom, crop_right, crop_top):
        return None
    candidate = (crop_left, crop_bottom, crop_right, crop_top)
    return candidate if _is_credible_inner_box(candidate, media, target_size) else None


def _stroked_vector_geometry(
    page: Any,
) -> Tuple[List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]:
    """@brief Extract simple stroked line segments and rectangles from content."""
    try:
        content = page.get_contents()
    except (AttributeError, TypeError, ValueError):
        return [], []
    if content is None:
        return [], []

    segments: List[Tuple[float, float, float, float]] = []
    rectangles: List[Tuple[float, float, float, float]] = []
    pending_segments: List[Tuple[float, float, float, float]] = []
    pending_rectangles: List[Tuple[float, float, float, float]] = []
    current_point: Optional[Tuple[float, float]] = None
    for operands, operator in content.operations:
        if operator == b"m" and len(operands) >= 2:
            current_point = (float(operands[0]), float(operands[1]))
        elif operator == b"l" and len(operands) >= 2 and current_point is not None:
            next_point = (float(operands[0]), float(operands[1]))
            pending_segments.append((*current_point, *next_point))
            current_point = next_point
        elif operator == b"re" and len(operands) >= 4:
            x, y, width, height = (float(value) for value in operands[:4])
            pending_rectangles.append(
                (min(x, x + width), min(y, y + height), max(x, x + width), max(y, y + height))
            )
        elif operator in {b"S", b"s", b"B", b"B*"}:
            segments.extend(pending_segments)
            rectangles.extend(pending_rectangles)
            pending_segments = []
            pending_rectangles = []
            current_point = None
        elif operator in {b"f", b"f*", b"F"}:
            for rectangle in pending_rectangles:
                pending_segments.extend(_thin_rectangle_segments(rectangle))
            segments.extend(pending_segments)
            pending_segments = []
            pending_rectangles = []
            current_point = None
        elif operator == b"n":
            pending_segments = []
            pending_rectangles = []
            current_point = None
    return segments, rectangles


def _thin_rectangle_segments(
    rectangle: Sequence[float],
) -> List[Tuple[float, float, float, float]]:
    """@brief Convert a thin filled crop-mark rectangle to its center line."""
    left, bottom, right, top = rectangle
    width = right - left
    height = top - bottom
    if width <= 1.5 and _MIN_CROP_MARGIN <= height <= _MAX_CROP_MARGIN:
        x = (left + right) / 2
        return [(x, bottom, x, top)]
    if height <= 1.5 and _MIN_CROP_MARGIN <= width <= _MAX_CROP_MARGIN:
        y = (bottom + top) / 2
        return [(left, y, right, y)]
    return []


def _supported_coordinate(values: Sequence[float], tolerance: float = 2.0) -> Optional[float]:
    """@brief Return a coordinate supported by marks at two opposing corners."""
    groups: List[List[float]] = []
    for value in sorted(values):
        if not groups or abs(groups[-1][-1] - value) > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    supported = [group for group in groups if len(group) >= 2]
    if not supported:
        return None
    best = max(supported, key=len)
    return sum(best) / len(best)


def _is_credible_inner_box(
    candidate: Sequence[float],
    media: Sequence[float],
    target_size: Tuple[float, float],
) -> bool:
    """@brief Ensure a proposed crop matches the inferred finished format."""
    left, bottom, right, top = candidate
    media_left, media_bottom, media_right, media_top = media
    if not (
        media_left <= left < right <= media_right
        and media_bottom <= bottom < top <= media_top
    ):
        return False
    margins = (
        left - media_left,
        bottom - media_bottom,
        media_right - right,
        media_top - top,
    )
    if max(margins) < _MIN_CROP_MARGIN:
        return False
    if any(margin < 0 or margin > _MAX_CROP_MARGIN for margin in margins):
        return False
    if _box_area(candidate) < _box_area(media) * 0.45:
        return False
    width = right - left
    height = top - bottom
    target_width, target_height = _orient_size(target_size, width, height)
    width_tolerance = max(_STANDARD_TOLERANCE, target_width * 0.1)
    height_tolerance = max(_STANDARD_TOLERANCE, target_height * 0.1)
    return (
        abs(width - target_width) <= width_tolerance
        and abs(height - target_height) <= height_tolerance
    )


def _infer_target_page_size(pages: Sequence[Any]) -> Tuple[float, float]:
    """@brief Infer Letter or Half Letter from the first two clean pages."""
    if not pages:
        return 612.0, 792.0
    inspected = pages[:2]
    for page in inspected:
        media = _box_tuple(page.mediabox)
        width = media[2] - media[0]
        height = media[3] - media[1]
        for target in _TARGET_PAGE_SIZES:
            oriented = _orient_size(target, width, height)
            if (
                abs(width - oriented[0]) <= _STANDARD_TOLERANCE
                and abs(height - oriented[1]) <= _STANDARD_TOLERANCE
            ):
                return oriented

    first_media = _box_tuple(inspected[0].mediabox)
    first_width = first_media[2] - first_media[0]
    first_height = first_media[3] - first_media[1]
    candidates = [
        _orient_size(target, first_width, first_height)
        for target in _TARGET_PAGE_SIZES
    ]
    return min(
        candidates,
        key=lambda size: abs(first_width - size[0]) + abs(first_height - size[1]),
    )


def _orient_size(
    size: Tuple[float, float], reference_width: float, reference_height: float
) -> Tuple[float, float]:
    """@brief Orient a standard size to match a portrait or landscape page."""
    width, height = size
    if (reference_width > reference_height) != (width > height):
        return height, width
    return width, height


def _apply_crop_box(page: Any, crop_box: Sequence[float]) -> None:
    """@brief Apply the inferred visible and trim boxes without deleting content."""
    from pypdf.generic import RectangleObject

    rectangle = RectangleObject(crop_box)
    page.cropbox = rectangle
    page.trimbox = RectangleObject(crop_box)


def _add_footer_watermark(page: Any, watermark: str) -> None:
    """@brief Merge a subtle centered footer watermark into one page."""
    from pypdf import PageObject
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    media = _box_tuple(page.mediabox)
    visible = _box_tuple(page.cropbox)
    media_width = media[2] - media[0]
    media_height = media[3] - media[1]
    font_size = 7.0
    estimated_width = len(watermark) * font_size * 0.48
    x = visible[0] + max(((visible[2] - visible[0]) - estimated_width) / 2, 4.0)
    y = visible[1] + 5.0

    overlay = PageObject.create_blank_page(width=media_width, height=media_height)
    overlay[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/TOCBWM"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                        }
                    )
                }
            )
        }
    )
    escaped = _escape_pdf_text(watermark)
    stream = DecodedStreamObject()
    stream.set_data(
        (
            "q\nBT\n/TOCBWM 7 Tf\n0.55 g\n"
            f"1 0 0 1 {x:.2f} {y:.2f} Tm\n"
            f"({escaped}) Tj\nET\nQ\n"
        ).encode("latin-1")
    )
    overlay.replace_contents(stream)
    page.merge_page(overlay, expand=False, over=True)


def _escape_pdf_text(value: str) -> str:
    """@brief Escape a Latin-1 string for use in a PDF literal string."""
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _box_tuple(box: Any) -> Tuple[float, float, float, float]:
    """@brief Convert a pypdf rectangle-like object to numeric coordinates."""
    return tuple(float(value) for value in box[:4])  # type: ignore[return-value]


def _box_area(box: Sequence[float]) -> float:
    """@brief Return rectangle area."""
    return max(box[2] - box[0], 0) * max(box[3] - box[1], 0)
