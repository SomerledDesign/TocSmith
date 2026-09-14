from __future__ import annotations

"""@file
@brief Conservative page cropping and watermark finishing for generated PDFs.

Oversized pages are cropped only when their PDF boxes or stroked vector crop
marks provide a credible inner page rectangle. Every page receives a small,
centered footer watermark inside its final visible box.
"""

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple


_TARGET_PAGE_SIZES = ((396.0, 612.0), (612.0, 792.0))
_STANDARD_TOLERANCE = 6.0
_MAX_CROP_MARGIN = 144.0
_MIN_CROP_MARGIN = 3.0
DEFAULT_WATERMARK = "TocSmith"


@dataclass(frozen=True)
class FinishStats:
    """@brief Counts produced by the PDF finishing pass."""

    cropped_page_count: int = 0
    watermarked_page_count: int = 0


def finish_pdf_pages(
    pages: Iterable[Any], watermark: str = DEFAULT_WATERMARK
) -> FinishStats:
    """@brief Crop credibly marked oversized pages and watermark every page."""
    page_list = list(pages)
    target_size = _infer_target_page_size(page_list)
    cropped = 0
    watermarked = 0
    for page in page_list:
        crop_box = _detect_crop_box(page, target_size)
        if crop_box is not None:
            _apply_crop_box(page, crop_box)
            cropped += 1
        if getattr(page, "rotation", 0):
            page.transfer_rotation_to_content()
        if watermark:
            _add_footer_watermark(page, watermark)
            watermarked += 1
    return FinishStats(cropped, watermarked)


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
