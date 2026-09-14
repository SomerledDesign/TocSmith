import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from toc_bookmarks.analyzer import analyze_pdf_features, is_confident_bookmark_candidate
from toc_bookmarks.models import TocEntry, TocLayoutLine


class AnalyzerTests(unittest.TestCase):
    def test_marks_pdf_without_text_as_not_ocr_ready(self) -> None:
        result = analyze_pdf_features(["", "   ", "\n"], [])
        self.assertFalse(result.is_ocr_text_available)
        self.assertEqual(result.toc_candidates, [])

    def test_detects_toc_page_and_extracts_entries(self) -> None:
        pages = [
            "Cover page",
            "\n".join(
                [
                    "Table of Contents",
                    "Introduction .......... 1",
                    "Installation .......... 3",
                    "   2.1 Command Line .......... 5",
                ]
            ),
            "Introduction\nBody text here",
            "Installation\nSetup details",
            "2.1 Command Line\nCLI details",
        ]
        result = analyze_pdf_features(pages, ["Introduction"])
        self.assertTrue(result.is_ocr_text_available)
        self.assertEqual([candidate.page_index for candidate in result.toc_candidates], [1])
        self.assertEqual([entry.title for entry in result.toc_entries], ["Introduction", "Installation", "2.1 Command Line"])
        self.assertEqual(result.bookmark_coverage.missing_titles, ["Installation", "2.1 Command Line"])
        self.assertEqual([entry.anchor_page_index for entry in result.toc_entries], [2, 3, 4])

    def test_layout_first_toc_extraction_handles_collapsed_contents_pages(self) -> None:
        pages = [
            "CONTENTSIntroduction 1HowtoUseThisManual 2TechnicalSupport 7Chapter1/Features 9",
            "Introduction\nWelcome",
            "How to Use This Manual\nUsage details",
            "Technical Support\nSupport details",
            "Filler",
            "Filler",
            "Filler",
            "Filler",
            "Filler",
            "Chapter 1\nFeatures",
        ]
        toc_page_layouts = {
            0: [
                TocLayoutLine("CONTENTS", x=222.0, y=2227.0, font_name="/Courier"),
                TocLayoutLine("Introduction", x=220.0, y=2133.0, font_name="/Courier"),
                TocLayoutLine("How to Use This Manual", x=337.0, y=2084.0, font_name="/Courier"),
                TocLayoutLine("Technical Support", x=336.0, y=1984.0, font_name="/Courier"),
                TocLayoutLine("Chapter 1 / Features", x=220.0, y=1916.0, font_name="/Courier"),
                TocLayoutLine("4DOS Reference Manual", x=221.0, y=149.0, font_name="/Courier"),
                TocLayoutLine("1 2 7 9", x=0.0, y=0.0, font_name="/Courier"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual([candidate.page_index for candidate in result.toc_candidates], [0])
        self.assertEqual(
            [entry.title for entry in result.toc_entries],
            ["Introduction", "How to Use This Manual", "Technical Support", "Chapter 1 / Features"],
        )
        self.assertEqual([entry.printed_page for entry in result.toc_entries], [1, 2, 7, 9])

    def test_body_mention_of_table_of_contents_does_not_replace_real_toc(self) -> None:
        pages = [
            "Contents\nIntroduction ...... 1\nInstalling ...... 3",
            "\n".join(
                [
                    "Welcome",
                    "This guide has a detailed table of contents and index.",
                    "Use the table of contents to find common tasks.",
                    "Introduction",
                    "Documentation",
                    "Conventions",
                    "More Help",
                ]
            ),
            "Introduction\nBody",
            "Installing\nBody",
        ]
        toc_page_layouts = {
            1: [
                TocLayoutLine("Welcome", x=50.0, y=700.0),
                TocLayoutLine("This guide has a detailed table of contents and index.", x=50.0, y=680.0),
                TocLayoutLine("Use the table of contents to find common tasks.", x=50.0, y=660.0),
                TocLayoutLine("Introduction", x=50.0, y=620.0),
                TocLayoutLine("Documentation", x=50.0, y=600.0),
                TocLayoutLine("Conventions", x=50.0, y=580.0),
                TocLayoutLine("More Help", x=50.0, y=560.0),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual([candidate.page_index for candidate in result.toc_candidates], [0])
        self.assertEqual([entry.title for entry in result.toc_entries], ["Introduction", "Installing"])

    def test_chess_contents_prefers_layout_rows_over_notation_false_positives(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Symbols",
                    "General Introduction",
                    "1 Introduction to the English Opening",
                    "The Bishop Sortie 2 ... i.b4",
                    "Reversed Dragon: 4 ... d5",
                ]
            ),
            "\n".join(
                [
                    "4 MASTERING THE CHESS OPENINGS",
                    "6 Three Knights and Closed English",
                    "Three Knights Variation",
                    "The Independent 3 ... f5",
                    "Introduction to the Closed English",
                ]
            ),
            *["Filler"] * 20,
            "General Introduction\nBody",
            "Introduction to the English Opening\nBody",
        ]
        toc_page_layouts = {
            0: [
                TocLayoutLine("Contents", x=50.0, y=720.0),
                TocLayoutLine("Symbols 6", x=70.0, y=700.0),
                TocLayoutLine("General Introduction 9", x=70.0, y=680.0),
                TocLayoutLine("1 Introduction to the English Opening 11", x=70.0, y=660.0),
                TocLayoutLine("2 Reversing the Sicilian: 2nd Moves 14", x=70.0, y=640.0),
            ],
            1: [
                TocLayoutLine("4 MASTERING THE CHESS OPENINGS", x=50.0, y=720.0),
                TocLayoutLine("6 Three Knights and Closed English 139", x=70.0, y=700.0),
                TocLayoutLine("Three Knights Variation 139", x=90.0, y=680.0),
                TocLayoutLine("The Independent 3 ... f5 141", x=90.0, y=660.0),
                TocLayoutLine("Introduction to the Closed English 144", x=90.0, y=640.0),
            ],
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual([candidate.page_index for candidate in result.toc_candidates], [0, 1])
        self.assertEqual(
            [entry.title for entry in result.toc_entries[:5]],
            [
                "Symbols",
                "General Introduction",
                "1 Introduction to the English Opening",
                "2 Reversing the Sicilian: 2nd Moves",
                "6 Three Knights and Closed English",
            ],
        )
        self.assertNotIn(
            "4 MASTERING THE CHESS OPENINGS",
            [entry.title for entry in result.toc_entries],
        )

    def test_layout_first_toc_extraction_prefers_monotonic_text_page_stream(self) -> None:
        pages = [
            "CONTENTSColorDirectives4AdvancedDirectives0PrimaryFeatures60SecondaryFeatures62SupportSoftware1444",
            "Filler",
            "Filler",
            "Filler",
            "Color Directives\nBody",
            *["Filler"] * 55,
            "Primary Features\nBody",
            "Secondary Features\nBody",
        ]
        toc_page_layouts = {
            0: [
                TocLayoutLine("CONTENTS", x=222.0, y=2227.0, font_name="/Courier"),
                TocLayoutLine("Color Directives", x=220.0, y=2133.0, font_name="/Courier"),
                TocLayoutLine("Advanced Directives", x=220.0, y=2084.0, font_name="/Courier"),
                TocLayoutLine("Primary Features", x=220.0, y=2035.0, font_name="/Courier"),
                TocLayoutLine("Secondary Features", x=220.0, y=1986.0, font_name="/Courier"),
                TocLayoutLine("4 0 60 62 1444", x=0.0, y=0.0, font_name="/Courier"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual(
            [entry.printed_page for entry in result.toc_entries],
            [4, 60, 62],
        )
        self.assertEqual(
            [entry.title for entry in result.toc_entries],
            ["Color Directives", "Advanced Directives", "Primary Features"],
        )

    def test_cleans_noisy_toc_titles_and_matches_heading_pages(self) -> None:
        pages = [
            "Cover",
            "\n".join(
                [
                    "Contents",
                    "Chapter 1 Getting Started .. . . . . . . . . . . . . . . 1",
                    "Using MS-DOS Help ...................................... 30",
                ]
            ),
            "Chapter 1 Getting Started\nWelcome to setup",
            "Filler",
            "Using MS-DOS Help\nHow to use help",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual(
            [entry.title for entry in result.toc_entries],
            ["Chapter 1 Getting Started", "Using MS-DOS Help"],
        )
        self.assertEqual(
            [entry.anchor_page_index for entry in result.toc_entries],
            [2, 4],
        )

    def test_prefers_top_of_page_heading_over_body_reference(self) -> None:
        pages = [
            "Contents\nChapter 1 Getting Started ...... 1\nRunning Setup ...... 2",
            "Welcome\nIf this version is not yet set up, see the chapter Getting Started for setup.",
            "CHAPTER 1\nGetting Started\nRun Setup first.",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual(result.toc_entries[0].anchor_page_index, 2)
        self.assertGreaterEqual(result.toc_entries[0].anchor_match_score, 0.9)

    def test_uses_style_consistent_split_heading_as_anchor_match(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Using CONFIG.SYS Commands to Configure Your System ...... 82",
                    "Editing Your CONFIG.SYS File ...... 82",
                ]
            ),
            "Filler",
            "\n".join(
                [
                    "82 Microsoft MS-DOS User's Guide",
                    "Intro body line",
                    "Using CONFIG.SYS Commands to Configure",
                    "Your System",
                    "Body text starts here",
                ]
            ),
        ]
        page_layouts = {
            2: [
                TocLayoutLine("82 Microsoft MS-DOS User's Guide", x=41.0, y=574.0, font_size=1.0, font_name="/Helvetica-Bold"),
                TocLayoutLine("Intro body line", x=108.0, y=416.0, font_size=1.0, font_name="/Times-Roman"),
                TocLayoutLine("Using CONFIG.SYS Commands to Configure", x=42.0, y=370.0, font_size=1.0, font_name="/Helvetica-Bold"),
                TocLayoutLine("Your System", x=41.0, y=350.0, font_size=1.0, font_name="/Helvetica-Bold"),
                TocLayoutLine("Body text starts here", x=108.0, y=333.0, font_size=1.0, font_name="/Times-Roman"),
            ]
        }
        result = analyze_pdf_features(pages, [], page_layouts=page_layouts)
        self.assertEqual(result.toc_entries[0].anchor_page_index, 2)
        self.assertGreaterEqual(result.toc_entries[0].anchor_match_score, 0.95)

    def test_keeps_searching_past_098_when_a_later_exact_heading_exists(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Keyboard Layouts for Single-Handed Users ...... 4",
                    "Other Entry ...... 5",
                ]
            ),
            "Filler",
            "Keyboard layouts are designed for people who type with only one hand.",
            "More filler",
            "Keyboard Layouts for Single-Handed Users\nBody",
        ]
        page_layouts = {
            2: [
                TocLayoutLine(
                    "Keyboard layouts are designed for people who type with only one hand.",
                    x=117.0,
                    y=340.0,
                    font_size=1.0,
                    font_name="/Times-Roman",
                )
            ],
            4: [
                TocLayoutLine(
                    "Keyboard Layouts for Single-Handed Users",
                    x=50.0,
                    y=396.0,
                    font_size=1.0,
                    font_name="/Helvetica-Bold",
                )
            ],
        }
        result = analyze_pdf_features(pages, [], page_layouts=page_layouts)
        self.assertEqual(result.toc_entries[0].anchor_page_index, 4)
        self.assertEqual(result.toc_entries[0].anchor_match_score, 1.0)

    def test_distance_penalty_prefers_local_heading_over_far_index_hit(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Filename Completion ...... 60",
                    "Other Entry ...... 61",
                ]
            ),
            *["Filler"] * 58,
            "Filename Completion\nBody text here",
            "Another local page",
            *["Filler"] * 289,
            "Index\nFilename Completion, 60",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual(result.toc_entries[0].anchor_page_index, 59)
        self.assertGreaterEqual(result.toc_entries[0].anchor_match_score, 0.85)

    def test_symbolic_command_entry_can_be_extracted_and_matched(self) -> None:
        pages = [
            "Contents\n? ...... 5\nALIAS ...... 6",
            "Filler",
            "Filler",
            "Filler",
            "? (New)\nPurpose: Display a list of commands.",
            "ALIAS\nBody",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual([entry.title for entry in result.toc_entries], ["?", "ALIAS"])
        self.assertEqual(result.toc_entries[0].anchor_page_index, 4)

    def test_layout_only_symbolic_command_entry_survives_title_filter(self) -> None:
        pages = [
            "CONTENTS4D0SCommands 4HowtoUseTheCommandDescriptions 5? 6ALIAS 7",
            "Filler",
            "Filler",
            "Filler",
            "? (New)\nPurpose: Display a list of commands.",
            "ALIAS\nBody",
        ]
        toc_page_layouts = {
            0: [
                TocLayoutLine("CONTENTS", x=220.0, y=2227.0, font_name="/Courier"),
                TocLayoutLine("4D0S Commands", x=328.0, y=1158.0, font_name="/Courier"),
                TocLayoutLine("How to Use the Command Descriptions 5", x=328.0, y=1111.0, font_name="/Courier"),
                TocLayoutLine("?", x=328.0, y=1056.0, font_name="/Courier"),
                TocLayoutLine("ALIAS", x=327.0, y=1008.0, font_name="/Courier"),
                TocLayoutLine("4 5 6 7", x=0.0, y=0.0, font_name="/Courier"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual([entry.title for entry in result.toc_entries], ["4D0S Commands", "How to Use the Command Descriptions", "?", "ALIAS"])

    def test_finds_heading_that_starts_below_large_nonheading_block(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Documentation on Audio Cassettes and Floppy Disks ...... 4",
                    "Other Entry ...... 5",
                ]
            ),
            "Filler",
            "Documentation on audio cassettes and floppy disks is available through this appendix overview.",
            "More filler",
            "\n".join(
                [f"diagram line {i}" for i in range(27)]
                + [
                    "Documentation on Audio Cassettes and Floppy Disks",
                    "Body starts here",
                ]
            ),
        ]
        page_layouts = {
            2: [
                TocLayoutLine(
                    "Documentation on audio cassettes and floppy disks is available through this appendix overview.",
                    x=117.0,
                    y=340.0,
                    font_size=1.0,
                    font_name="/Times-Roman",
                )
            ],
            4: [
                *[
                    TocLayoutLine(
                        f"diagram line {i}",
                        x=220.0,
                        y=560.0 - i * 8,
                        font_size=1.0,
                        font_name="/Helvetica",
                    )
                    for i in range(27)
                ],
                TocLayoutLine(
                    "Documentation on Audio Cassettes and Floppy Disks",
                    x=38.0,
                    y=320.0,
                    font_size=1.0,
                    font_name="/Helvetica-Bold",
                ),
                TocLayoutLine(
                    "Body starts here",
                    x=117.0,
                    y=304.0,
                    font_size=1.0,
                    font_name="/Times-Roman",
                ),
            ],
        }
        result = analyze_pdf_features(pages, [], page_layouts=page_layouts)
        self.assertEqual(result.toc_entries[0].anchor_page_index, 4)
        self.assertEqual(result.toc_entries[0].anchor_match_score, 1.0)

    def test_generic_short_heading_requires_exact_heading_not_intro_mentions(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Keyboard Layouts ...... 4",
                    "Other Entry ...... 5",
                ]
            ),
            "Filler",
            "Commands Used to Change International Settings\ncountry codes, keyboard layouts, and character sets",
            "Filler two",
            "APPENDIX C\nKeyboard Layouts and Character Sets\nKeyboard Layouts\nBody",
        ]
        page_layouts = {
            2: [
                TocLayoutLine(
                    "Commands Used to Change International Settings",
                    x=39.0,
                    y=540.0,
                    font_size=1.0,
                    font_name="/Helvetica-Bold",
                ),
                TocLayoutLine(
                    "country codes, keyboard layouts, and character sets",
                    x=106.0,
                    y=510.0,
                    font_size=1.0,
                    font_name="/Times-Roman",
                ),
            ],
            4: [
                TocLayoutLine("APPENDIX C", x=47.0, y=548.0, font_size=1.0, font_name="/Times-Roman"),
                TocLayoutLine("Keyboard Layouts and Character Sets", x=47.0, y=512.0, font_size=1.0, font_name="/Helvetica-Bold"),
                TocLayoutLine("Keyboard Layouts", x=47.0, y=251.0, font_size=1.0, font_name="/Helvetica-Bold"),
            ],
        }
        result = analyze_pdf_features(pages, [], page_layouts=page_layouts)
        self.assertEqual(result.toc_entries[0].anchor_page_index, 4)
        self.assertEqual(result.toc_entries[0].anchor_match_score, 1.0)

    def test_repairs_headingless_section_from_strong_sibling_sequence(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Chapter 6 Making More Memory Available ...... 1",
                    "Freeing Extended Memory ...... 2",
                    "Freeing Expanded Memory ...... 3",
                    "Using MS-DOS Memory Managers ...... 4",
                ]
            ),
            "CHAPTER 6\nMaking More Memory Available",
            "Freeing Extended Memory\nHow to free extended memory.",
            "Expanded memory requires EMM386 and related setup.\nThis section continues without a repeated heading.",
            "Using MS-DOS Memory Managers\nMemory manager details.",
        ]
        toc_page_layouts = {
            0: [
                TocLayoutLine("Chapter 6 Making More Memory Available ...... 1", x=119.0, y=360.0, font_name="/Helvetica-Bold"),
                TocLayoutLine("Freeing Extended Memory ...... 2", x=119.0, y=347.0, font_name="/Times-Roman"),
                TocLayoutLine("Freeing Expanded Memory ...... 3", x=119.0, y=334.0, font_name="/Times-Roman"),
                TocLayoutLine("Using MS-DOS Memory Managers ...... 4", x=119.0, y=321.0, font_name="/Times-Roman"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual(
            [entry.anchor_page_index for entry in result.toc_entries],
            [1, 2, 3, 4],
        )
        self.assertGreaterEqual(result.toc_entries[2].anchor_match_score, 0.9)

    def test_structural_entries_make_following_entries_children(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Chapter 1 Getting Started ...... 1",
                    "Running Setup ...... 2",
                    "   Advanced Setup ...... 3",
                    "Chapter 2 Next Steps ...... 4",
                ]
            ),
            "CHAPTER 1\nGetting Started",
            "Running Setup",
            "Advanced Setup",
            "CHAPTER 2\nNext Steps",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual([entry.level for entry in result.toc_entries], [1, 2, 2, 1])

    def test_extracts_toc_line_with_ocr_junk_before_page_number(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Chapter 1 Getting Started .. . . . . . . . . . . . . . . 1",
                    "Running Setup ..................................................... \" 1",
                ]
            ),
            "CHAPTER 1\nGetting Started",
            "Running Setup\nUse setup to install MS-DOS.",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual(
            [entry.title for entry in result.toc_entries],
            ["Chapter 1 Getting Started", "Running Setup"],
        )
        self.assertEqual(result.toc_entries[1].anchor_page_index, 2)

    def test_prefers_structural_chapter_opener_over_later_internal_heading(self) -> None:
        pages = [
            "Contents\nChapter 2 MS-DOS Basics ...... 3\nLearning MS-DOS Basics-A Tutorial ...... 3",
            "Preface mentioning MS-DOS Basics",
            "CHAPTER 2\nMS-DOS Basics\nThis chapter explains the basics of using MS-DOS.",
            "Learning MS-DOS Basics-A Tutorial\nThis tutorial gives you an opportunity...",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual(result.toc_entries[0].title, "Chapter 2 MS-DOS Basics")
        self.assertEqual(result.toc_entries[0].anchor_page_index, 2)

    def test_collapsed_structural_heading_beats_earlier_overview_mention(self) -> None:
        pages = [
            "Contents\nIntroduction ...... 1\nChapter 2 / Installation ...... 13",
            *(["Front matter"] * 11),
            (
                "HowtoUseThisManualChapter2/InstallationEveryoneShouldReadThis"
                "ShortChapterChapter3/AGuidedTour"
            ),
            *(["Chapter 1 running text"] * 9),
            "AutomatedInstallation\nCHAPTER2/INSTALLATION\nInstallation details",
            "CHAPTER 2 / INSTALLATION\nRepeated running header",
        ]
        result = analyze_pdf_features(pages, [])
        chapter = next(entry for entry in result.toc_entries if entry.title.startswith("Chapter 2"))
        self.assertEqual(chapter.anchor_page_index, 22)
        self.assertGreaterEqual(chapter.anchor_match_score, 0.85)

    def test_reduces_noisy_chess_line_to_readable_title(self) -> None:
        pages = [
            "Contents\n2 f4 ------------------------- 1 King's Gambit .......................... 3\nFrench Defense ...... 10",
            "1 King's Gambit\nMain line",
            "French Defense\nMain line",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual([entry.title for entry in result.toc_entries], ["1 King's Gambit", "French Defense"])

    def test_keeps_structural_context_across_toc_pages(self) -> None:
        pages = [
            "Cover",
            "\n".join(
                [
                    "Contents",
                    "Chapter 2 MS-DOS Basics ...... 3",
                    "Learning MS-DOS Basics-A Tutorial ...... 3",
                ]
            ),
            "\n".join(
                [
                    "Contents",
                    "Getting Help ...... 29",
                    "Using MS-DOS Help ...... 30",
                ]
            ),
            "CHAPTER 2\nMS-DOS Basics",
            "Learning MS-DOS Basics-A Tutorial",
            "Getting Help",
            "Using MS-DOS Help",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual([entry.level for entry in result.toc_entries], [1, 2, 2, 3])

    def test_separate_toc_clusters_preserve_duplicates_and_match_forward(self) -> None:
        pages = [
            "Contents\nOverview ...... 1\nSetup ...... 2",
            "Overview\nFirst manual",
            "Setup\nFirst manual",
            "Separator",
            "Contents\nOverview ...... 1\nSetup ...... 2",
            "Overview\nSecond manual",
            "Setup\nSecond manual",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual([entry.title for entry in result.toc_entries], ["Overview", "Setup"] * 2)
        self.assertEqual(
            [entry.anchor_page_index for entry in result.toc_entries],
            [1, 2, 5, 6],
        )

    def test_stable_cluster_offset_avoids_earlier_repeated_heading(self) -> None:
        pages = ["Front matter"] * 10 + [
            "Contents\nAlpha ...... 1\nBeta ...... 2\nGamma ...... 3\nRepeated ...... 4",
            "Alpha\nRepeated",
            "Beta",
            "Gamma",
            "Repeated\nCorrect destination",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual(
            [entry.anchor_page_index for entry in result.toc_entries],
            [11, 12, 13, 14],
        )

    def test_child_anchor_does_not_precede_parent(self) -> None:
        pages = [
            "Contents\nProduct Specifications ...... 5\nHP LaserJet 5P/5MP ...... 5\nMaintenance ...... 6\nTools ...... 7",
            "Filler",
            "Filler",
            "Filler",
            "HP LaserJet 5P/5MP\nEarlier model mention",
            "Product Specifications\nHP LaserJet 5P/5MP",
            "Maintenance",
            "Tools",
        ]
        toc_layouts = {
            0: [
                TocLayoutLine("Contents", x=48, y=700, font_name="/Book-Bold"),
                TocLayoutLine("Product Specifications ...... 5", x=48, y=680, font_name="/Book-Bold"),
                TocLayoutLine("HP LaserJet 5P/5MP ...... 5", x=60, y=660, font_name="/Book-Roman"),
                TocLayoutLine("Maintenance ...... 6", x=48, y=640, font_name="/Book-Bold"),
                TocLayoutLine("Tools ...... 7", x=60, y=620, font_name="/Book-Roman"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_layouts)
        self.assertEqual(result.toc_entries[0].anchor_page_index, 5)
        self.assertEqual(result.toc_entries[1].anchor_page_index, 5)

    def test_matches_heading_with_split_ocr_letters(self) -> None:
        pages = [
            "Contents\nTroubleshooting IR Printing Problems ...... 2\nUsing the Infrared Test Tool ...... 3",
            "Filler",
            "T roubleshooting IR Printing Problems\nDetails",
            "Using the Infrared T est T ool\nDetails",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual(
            [entry.anchor_page_index for entry in result.toc_entries],
            [2, 3],
        )
        self.assertEqual(
            [entry.anchor_match_score for entry in result.toc_entries],
            [1.0, 1.0],
        )

    def test_flat_toc_uses_consistent_bold_and_indent_as_two_tiers(self) -> None:
        pages = [
            "Contents\nOverview ...... 1\nI/O Buffering ...... 2\nMaintenance ...... 3\nTools ...... 4",
            "Overview",
            "I/O Buffering",
            "Maintenance",
            "Tools",
        ]
        toc_layouts = {
            0: [
                TocLayoutLine("Contents", x=48, y=700, font_name="/Book-Bold"),
                TocLayoutLine("Overview ...... 1", x=48, y=680, font_name="/Book-Bold"),
                TocLayoutLine(
                    "I/O Buffering  .  .  .  .  .  .  .  .  .  .  .  .  2",
                    x=60,
                    y=660,
                    font_name="/Book-Roman",
                ),
                TocLayoutLine("Maintenance ...... 3", x=48, y=640, font_name="/Book-Bold"),
                TocLayoutLine("Tools ...... 4", x=60, y=620, font_name="/Book-Roman"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_layouts)
        self.assertEqual([entry.level for entry in result.toc_entries], [1, 2, 1, 2])

    def test_sequences_subtopics_under_recent_major_topic(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Chapter 2 MS-DOS Basics ...... 3",
                    "Learning MS-DOS Basics-A Tutorial ...... 3",
                    "The Command Prompt ...... 4",
                    "Typing a Command ...... 4",
                ]
            ),
            "CHAPTER 2\nMS-DOS Basics",
            "Learning MS-DOS Basics-A Tutorial",
            "The Command Prompt",
            "Typing a Command",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual([entry.level for entry in result.toc_entries], [1, 2, 3, 3])

    def test_config_sys_topics_count_as_major_topics(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Chapter 4 Configuring Your System ...... 81",
                    "Using CONFIG.SYS Commands to Configure Your System ...... 82",
                    "Editing Your CONFIG.SYS File ...... 82",
                    "CONFIG.SYS Commands ...... 83",
                ]
            ),
            "CHAPTER 4\nConfiguring Your System",
            "Using CONFIG.SYS Commands to Configure Your System",
            "Editing Your CONFIG.SYS File",
            "CONFIG.SYS Commands",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual([entry.level for entry in result.toc_entries], [1, 2, 3, 2])

    def test_setting_up_section_becomes_major_topic_under_appendix(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Appendix E Freeing Disk Space by Using DriveSpace ...... 227",
                    "Getting Help ...... 227",
                    "Setting Up DriveSpace ...... 228",
                    "Using Express Setup ...... 228",
                    "Using Custom Setup ...... 230",
                ]
            ),
            "Appendix E\nFreeing Disk Space by Using DriveSpace",
            "Getting Help",
            "Setting Up DriveSpace",
            "Using Express Setup",
            "Using Custom Setup",
        ]
        result = analyze_pdf_features(pages, [])
        self.assertEqual([entry.level for entry in result.toc_entries], [1, 2, 2, 3, 3])

    def test_layout_indent_data_can_be_supplied_without_breaking_analysis(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Chapter 2 MS-DOS Basics ...... 3",
                    "Learning MS-DOS Basics-A Tutorial ...... 3",
                    "The Command Prompt ...... 4",
                    "Typing a Command ...... 4",
                ]
            ),
            "CHAPTER 2\nMS-DOS Basics",
            "Learning MS-DOS Basics-A Tutorial",
            "The Command Prompt",
            "Typing a Command",
        ]
        toc_page_layouts = {
            0: [
                TocLayoutLine("Chapter 2 MS-DOS Basics ...... 3", x=119.0, y=360.0, font_name="/Helvetica-Bold"),
                TocLayoutLine("Learning MS-DOS Basics-A Tutorial ...... 3", x=119.0, y=347.0, font_name="/Times-Roman"),
                TocLayoutLine("The Command Prompt ...... 4", x=129.0, y=334.0, font_name="/Times-Roman"),
                TocLayoutLine("Typing a Command ...... 4", x=129.0, y=321.0, font_name="/Times-Roman"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual([entry.level for entry in result.toc_entries], [1, 2, 3, 3])

    def test_layout_reconciliation_can_promote_peer_back_to_level_two(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Chapter 1 Getting Started ...... 1",
                    "Running Setup ...... 1",
                    "Configuring Anti-Virus, Backup, and Undelete for Windows ...... 2",
                ]
            ),
            "CHAPTER 1\nGetting Started",
            "Running Setup",
            "Configuring Anti-Virus, Backup, and Undelete for Windows",
        ]
        toc_page_layouts = {
            0: [
                TocLayoutLine("Chapter 1 Getting Started ...... 1", x=119.0, y=410.0, font_name="/Helvetica-Bold"),
                TocLayoutLine("Running Setup ...... 1", x=119.0, y=398.0, font_name="/Times-Roman"),
                TocLayoutLine("Configuring Anti-Virus, Backup, and Undelete for Windows ...... 2", x=119.0, y=386.0, font_name="/Times-Roman"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual([entry.level for entry in result.toc_entries], [1, 2, 2])

    def test_layout_reconciliation_keeps_child_band_entries_under_tutorial_at_level_three(self) -> None:
        pages = [
            "\n".join(
                [
                    "Contents",
                    "Chapter 2 MS-DOS Basics ...... 3",
                    "Learning MS-DOS Basics-A Tutorial ...... 3",
                    "The Command Prompt ...... 4",
                    "Typing a Command ...... 4",
                    "Viewing the Contents of a Directory ...... 5",
                    "Changing Directories ...... 6",
                    "How MS-DOS Organizes Information ...... 23",
                ]
            ),
            "CHAPTER 2\nMS-DOS Basics",
            "Learning MS-DOS Basics-A Tutorial",
            "The Command Prompt",
            "Changing Directories",
            "How MS-DOS Organizes Information",
        ]
        toc_page_layouts = {
            0: [
                TocLayoutLine("Chapter 2 MS-DOS Basics ...... 3", x=119.0, y=360.0, font_name="/Helvetica-Bold"),
                TocLayoutLine("Learning MS-DOS Basics-A Tutorial ...... 3", x=119.0, y=347.0, font_name="/Times-Roman"),
                TocLayoutLine("The Command Prompt ...... 4", x=129.0, y=334.0, font_name="/Times-Roman"),
                TocLayoutLine("Typing a Command ...... 4", x=129.0, y=321.0, font_name="/Times-Roman"),
                TocLayoutLine("Viewing the Contents of a Directory ...... 5", x=129.0, y=308.0, font_name="/Times-Roman"),
                TocLayoutLine("Changing Directories ...... 6", x=129.0, y=295.0, font_name="/Times-Roman"),
                TocLayoutLine("How MS-DOS Organizes Information ...... 23", x=119.0, y=282.0, font_name="/Times-Roman"),
            ]
        }
        result = analyze_pdf_features(pages, [], toc_page_layouts=toc_page_layouts)
        self.assertEqual(
            [entry.level for entry in result.toc_entries],
            [1, 2, 3, 3, 3, 3, 2],
        )

    def test_marks_complete_bookmarks_when_all_toc_entries_exist(self) -> None:
        pages = [
            "Contents\nChapter One ...... 1\nChapter Two ...... 5",
            "Chapter one body",
        ]
        result = analyze_pdf_features(pages, ["Chapter One", "Chapter Two"])
        self.assertTrue(result.bookmark_coverage.is_complete)
        self.assertEqual(result.bookmark_coverage.missing_titles, [])

    def test_roman_numerals_are_parsed(self) -> None:
        pages = ["Contents\nPreface ...... iv\nChapter One ...... 1"]
        result = analyze_pdf_features(pages, ["Preface"])
        self.assertEqual([entry.printed_page for entry in result.toc_entries], [4, 1])

    def test_confident_bookmark_candidate_rejects_generic_short_titles(self) -> None:
        self.assertFalse(
            is_confident_bookmark_candidate(
                TocEntry(title="Index", anchor_page_index=10, anchor_match_score=1.0)
            )
        )
        self.assertTrue(
            is_confident_bookmark_candidate(
                TocEntry(
                    title="Chapter 1 Getting Started",
                    anchor_page_index=10,
                    anchor_match_score=0.95,
                )
            )
        )
        self.assertTrue(
            is_confident_bookmark_candidate(
                TocEntry(
                    title="French Defense",
                    anchor_page_index=10,
                    anchor_match_score=0.74,
                )
            )
        )
        self.assertTrue(
            is_confident_bookmark_candidate(
                TocEntry(
                    title="Introduction",
                    level=1,
                    anchor_page_index=10,
                    anchor_match_score=1.0,
                )
            )
        )
        self.assertTrue(
            is_confident_bookmark_candidate(
                TocEntry(
                    title="Redirection",
                    level=2,
                    anchor_page_index=10,
                    anchor_match_score=0.98,
                )
            )
        )
        self.assertTrue(
            is_confident_bookmark_candidate(
                TocEntry(
                    title="?",
                    level=2,
                    anchor_page_index=10,
                    anchor_match_score=1.0,
                )
            )
        )
        self.assertTrue(
            is_confident_bookmark_candidate(
                TocEntry(
                    title="ALIAS",
                    anchor_page_index=10,
                    anchor_match_score=0.91,
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
