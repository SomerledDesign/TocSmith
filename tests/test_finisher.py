import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from pypdf import PageObject
from pypdf.generic import DecodedStreamObject

from toc_bookmarks.finisher import finish_pdf_pages


class FinisherTests(unittest.TestCase):
    def test_watermarks_standard_page_without_cropping(self) -> None:
        page = PageObject.create_blank_page(width=612, height=792)
        stats = finish_pdf_pages([page])
        self.assertEqual(stats.cropped_page_count, 0)
        self.assertEqual(stats.watermarked_page_count, 1)
        self.assertIn("TocSmith", page.extract_text())
        self.assertEqual(tuple(float(value) for value in page.cropbox), (0, 0, 612, 792))

    def test_crops_oversized_page_with_four_corner_crop_marks(self) -> None:
        page = self._marked_page(width=648, height=828)
        stats = finish_pdf_pages([page])
        self.assertEqual(stats.cropped_page_count, 1)
        self.assertEqual(stats.watermarked_page_count, 1)
        self.assertEqual(tuple(float(value) for value in page.cropbox), (18, 18, 630, 810))
        self.assertIn("TocSmith", page.extract_text())

    def test_does_not_crop_oversized_page_without_marks(self) -> None:
        page = PageObject.create_blank_page(width=648, height=828)
        stats = finish_pdf_pages([page])
        self.assertEqual(stats.cropped_page_count, 0)
        self.assertEqual(tuple(float(value) for value in page.cropbox), (0, 0, 648, 828))

    def test_does_not_crop_standard_page_even_with_marks(self) -> None:
        page = self._marked_page(width=612, height=792, inset=12)
        stats = finish_pdf_pages([page])
        self.assertEqual(stats.cropped_page_count, 0)
        self.assertEqual(tuple(float(value) for value in page.cropbox), (0, 0, 612, 792))

    def test_first_half_letter_page_sets_target_for_marked_letter_page(self) -> None:
        cover = PageObject.create_blank_page(width=396, height=612)
        marked_letter = self._marked_page(width=612, height=792, inset=0)
        stream = DecodedStreamObject()
        stream.set_data(
            b"36 702 54 0.7 re f*\n108 720 0.7 54 re f*\n"
            b"522 702 54 0.7 re f*\n504 720 0.7 54 re f*\n"
            b"36 90 54 0.7 re f*\n108 18 0.7 54 re f*\n"
            b"522 90 54 0.7 re f*\n504 18 0.7 54 re f*\n"
        )
        marked_letter.replace_contents(stream)
        stats = finish_pdf_pages([cover, marked_letter])
        self.assertEqual(stats.cropped_page_count, 1)
        self.assertEqual(
            tuple(round(float(value), 1) for value in marked_letter.cropbox),
            (108.3, 90.3, 504.4, 702.4),
        )

    def test_rotated_marked_sheet_is_cropped_and_watermarked_at_visual_bottom(self) -> None:
        cover = PageObject.create_blank_page(width=396, height=612)
        sheet = PageObject.create_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(
            b"9 702 54 0.7 re f*\n81 720 0.7 54 re f*\n"
            b"531 702 54 0.7 re f*\n513 720 0.7 54 re f*\n"
            b"9 90 54 0.7 re f*\n81 18 0.7 54 re f*\n"
            b"531 90 54 0.7 re f*\n513 18 0.7 54 re f*\n"
        )
        sheet.replace_contents(stream)
        sheet.rotate(90)
        stats = finish_pdf_pages([cover, sheet])
        self.assertEqual(stats.cropped_page_count, 1)
        self.assertEqual(sheet.rotation, 0)
        self.assertEqual(
            (round(float(sheet.cropbox.width)), round(float(sheet.cropbox.height))),
            (612, 432),
        )
        self.assertIn("TocSmith", sheet.extract_text())

    def test_empty_watermark_disables_footer(self) -> None:
        page = PageObject.create_blank_page(width=612, height=792)
        stats = finish_pdf_pages([page], watermark="")
        self.assertEqual(stats.watermarked_page_count, 0)
        self.assertEqual(page.extract_text(), "")

    @staticmethod
    def _marked_page(width: float, height: float, inset: float = 18) -> PageObject:
        page = PageObject.create_blank_page(width=width, height=height)
        right = width - inset
        top = height - inset
        commands = [
            f"0 {inset} m {inset} {inset} l S",
            f"{right} {inset} m {width} {inset} l S",
            f"0 {top} m {inset} {top} l S",
            f"{right} {top} m {width} {top} l S",
            f"{inset} 0 m {inset} {inset} l S",
            f"{inset} {top} m {inset} {height} l S",
            f"{right} 0 m {right} {inset} l S",
            f"{right} {top} m {right} {height} l S",
        ]
        stream = DecodedStreamObject()
        stream.set_data(("\n".join(commands) + "\n").encode("ascii"))
        page.replace_contents(stream)
        return page
