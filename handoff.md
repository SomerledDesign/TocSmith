# Handoff

Current milestone: Milestone 6 TocSmith 1.0 repository preparation complete

Completed work:
- Branded the public project and primary command as TocSmith while retaining
  `toc-bookmarks` as a compatibility console-script alias.
- Set the first public release to version 1.0, cumulative build 345, with a
  single source of truth in `src/toc_bookmarks/version.py` and CLI reporting
  through `tocsmith --version`.
- Added a public README based on the opening project sketch, with quick-start,
  Windows, analysis-only, design, versioning, and development instructions.
- Added privacy-oriented ignore rules for PDFs, generated logs, virtual
  environments, credentials, local configuration, editor state, and operating
  system metadata.
- Replaced the personal hard-coded footer with a neutral `TocSmith` default and
  added `--watermark` so private footer text can remain outside version control;
  an empty value disables watermarking.
- Initialized the repository on `main` and configured
  `git@github.com:SomerledDesign/TocSmith.git` as its authenticated GitHub
  origin.
- Implemented a dependency-free PDF finishing pass that infers Letter or Half
  Letter format from the first two pages, crops only larger pages with credible
  PDF box or visible crop-mark evidence, and watermarks output pages.
- Added detection for crop marks represented as thin filled rectangles as well
  as stroked line segments, including modest per-page trim-size variations.
- Normalized rotated pages into their content before watermarking so the footer
  remains horizontal at the visual bottom in portrait and landscape output.
- Added six finishing tests covering watermark text, positive and negative crop
  detection, first-page Half Letter inference, and rotated marked sheets.
- Regenerated `pdfs/LASERJET6P_6MPServiceManual.bookmarked.pdf`: 98 marked pages
  cropped, 214 pages watermarked, 101 bookmarks preserved, no skipped entries,
  and no invalid outline destinations. Visual checks passed on title, TOC,
  portrait comment-sheet, and landscape comment-sheet pages.
- Backed up `pdfs/LASERJET6P_6MPServiceManual.pdf` as
  `pdfs/LASERJET6P_6MPServiceManual.original-backup.pdf`; both retain SHA-256
  `9d10bb3985ad0ba0b5ddab6c06ea8e0ceae42d093dbfc81e782c7c7149236a80`.
- Fixed combined-document analysis so duplicate entries are preserved across
  separate TOC clusters and entries cannot match pages before their own TOC.
- Added a guarded two-tier TOC classifier that uses bold/plain font treatment
  only when it agrees with consistent indentation across an otherwise-flat
  TOC cluster.
- Added cluster-local printed-to-PDF page-offset locking after three strong
  matches agree, preventing page-number restarts and repeated headings from
  cross-linking concatenated manuals.
- Prevented child anchors from preceding their active parent and added compact
  heading comparison for split-letter OCR such as `T roubleshooting` and
  `T est`.
- Added layout-title reconciliation that strips dot leaders/page numbers before
  matching, plus a writer exception for exact layout-verified one-word entries.
- Added six regression tests for combined TOC clusters, typographic hierarchy,
  stable offset matching, parent ordering, split-letter OCR, and verified
  single-word bookmark writing.
- Generated `pdfs/LASERJET6P_6MPServiceManual.bookmarked.pdf` with all 101 TOC
  entries: 24 major sections and 77 nested subsections, zero skips, and zero
  invalid destinations across all 214 pages.
- Fixed structural anchor matching on collapsed OCR text so line-leading
  `Chapter`/`Appendix` markers beat earlier prose or overview mentions.
- Made structural matching combine adjacent heading lines and preserve the
  first matching structural marker, preventing cleaner later running headers
  from stealing the anchor.
- Added a regression for an overview mention followed by a collapsed chapter
  opener and a cleaner repeated running header.
- Regenerated `pdfs/4DOS_Reference_Manual.pdf` as
  `/tmp/4DOS_Reference_Manual.structural-fix.bookmarked.pdf`; it writes 154
  bookmarks, with Chapter 2, Chapter 5, Chapter 7, and Appendix C now anchored
  at PDF page indexes 22, 64, 144, and 329 respectively.
- Added a Python project scaffold for TOC and bookmark analysis.
- Implemented heuristic OCR text detection based on extractable page text.
- Implemented TOC page detection and TOC entry extraction from dot-leader style lines.
- Implemented bookmark-vs-TOC coverage comparison.
- Added unit tests for OCR detection, TOC extraction, bookmark completeness, and Roman numeral parsing.
- Added a file-backed PDF adapter with guarded `pypdf` loading.
- Added a simple CLI that prints JSON analysis for a PDF path.
- Added tests for file-backed analysis and CLI output using fake readers.
- Added a repo-root bootstrap package so `python3 -m toc_bookmarks ...` works from checkout without setting `PYTHONPATH`.
- Added a repo-root `toc-bookmarks` launcher script so the project can run directly from checkout.
- Declared the installable `toc-bookmarks` console command in `pyproject.toml`.
- Updated CLI help output to show `toc-bookmarks` as the program name.
- Added regression tests for the launcher script and console-script package metadata.
- Updated the `toc-bookmarks` launcher to create/use a repo-local `.venv`, install project dependencies with `pip install -e .`, and expose a `--setup` command for explicit dependency setup.
- Tightened layout-only TOC detection so a body-page mention of "table of contents" no longer overrides earlier real TOC pages.
- Added regressions for local launcher bootstrapping and the body-page TOC mention false positive.
- Verified `./toc-bookmarks --setup`, `./toc-bookmarks --help`, and bookmark writing against `pdfs/DOS_6.22_Users_Manual_1994.pdf`; the smoke output wrote 166 bookmarks to `/tmp/toc-bookmarks-dos-smoke.bookmarked.pdf`.
- Changed the CLI so `--output <path>` implies bookmark writing, instead of being silently ignored during analysis mode.
- Updated help text to state that `--output` implies `--write-bookmarks`.
- Added regression coverage for `--output`-only writer invocation and explicit no-TOC logging.
- Verified the reported command now creates `/tmp/toc-bookmarks-Mastering-the-Chess-Openings-Wats-Volume-3.pdf`; that PDF currently gets zero generated bookmarks because no TOC entries are detected.
- Fixed Watson chess-book TOC detection by allowing weak text matches to fall back to richer layout rows.
- Added detection for adjacent layout-heavy TOC continuation pages after a real contents header.
- Filtered obvious running headers such as `CONTENTS 5` and all-caps page headers from layout-derived TOC rows.
- Added a regression for chess notation false positives on contents pages.
- Re-ran `pdfs/Mastering-the-Chess-Openings-Watson-Volume-3.pdf`; TOC candidates are now page indexes 3, 4, and 5, yielding 62 extracted TOC entries and 47 written bookmarks.
- Fixed a `PdfReader` file-handle lifetime bug by opening PDFs by path instead of a closed handle.
- Installed `pypdf` in the local user environment so real PDF analysis can run.
- Improved TOC title cleanup for noisy dot-leader layouts.
- Added heuristic anchor-page matching from TOC entries to body-page headings.
- Exposed anchor page indexes and match scores through the JSON CLI.
- Verified the new anchor fields against the DOS 6.22 manual.
- Added a conservative bookmark writer that outputs a new PDF and skips low-confidence entries.
- Added CLI support for `--write-bookmarks`, `--output`, and `--min-match-score`.
- Verified bookmark writing end-to-end on the DOS 6.22 manual; output PDF contained 142 outline items.
- Tightened anchor matching to prefer top-of-page headings over body-text references.
- Made TOC hierarchy more contextual so chapter-style entries become parents by default.
- Re-ran the DOS manual with the stricter matcher; the writer produced 114 bookmarks and skipped more weak targets instead of writing them incorrectly.
- Relaxed TOC line parsing so OCR junk before page numbers no longer drops valid entries like `Running Setup`.
- Verified `Running Setup` now appears as a level-2 TOC entry with a resolved anchor in the DOS manual analysis.
- Added a structural-entry matcher so `Chapter`/`Appendix` style titles are biased toward chapter-opening pages rather than later body mentions.
- Added a readable-title reducer to trim noisy TOC lines down to human-usable headings such as chess opening names.
- Adjusted structural hierarchy rules so `CONFIG.SYS`/`AUTOEXEC.BAT` topics can behave as major topics while local edit/sample lines remain children.
- Relaxed confidence gating for chess-style headings, which raised the Modern Chess output from 20 written bookmarks to 50 in the latest run.
- Added a human-readable writer decision log so each TOC entry records whether it was written or skipped and why.
- Added TOC layout capture plumbing (x/y/font data) but rolled back using it directly for hierarchy after it worsened the DOS output.
- Restored the earlier text-first hierarchy behavior and regenerated DOS output from that baseline.
- Tightened TOC layout reconciliation so deeper child-band entries on the same TOC page are normalized back to level 3 under the current level-2 parent instead of drifting up to level 2.
- Added a regression test covering the DOS Chapter 2 tutorial run so entries like `Changing Directories` stay under `Learning MS-DOS Basics-A Tutorial`.
- Regenerated the DOS manual output as `/tmp/DOS_6.22_Users_Manual_1994.v14.bookmarked.pdf`; the write log now shows the tutorial run staying at level 3 until the next level-2 heading (`How MS-DOS Organizes Information`).
- Added page-heading layout extraction for anchor matching across the full PDF, not just TOC pages.
- Improved anchor matching so adjacent heading-region lines with common font face/size/style are merged into a single heading window before falling back to overlap scoring.
- Added a regression test for split bold headings such as `Using CONFIG.SYS Commands to Configure` + `Your System`.
- Regenerated the DOS manual output as `/tmp/DOS_6.22_Users_Manual_1994.v15.bookmarked.pdf`; Chapter 4 parents like `Using CONFIG.SYS Commands to Configure Your System` now score above the prior `0.82` cap and write into the Chapter 4 subtree.
- Added a chapter-local sibling interpolation fallback for weak non-structural anchors, so heading-less sections can inherit the correct page when strong same-level neighbors bracket them cleanly.
- Added a regression test covering a heading-less middle section between two strong sibling headings.
- Regenerated the DOS manual output as `/tmp/DOS_6.22_Users_Manual_1994.v16.bookmarked.pdf`; `Freeing Expanded Memory` now writes as a level-2 entry at anchor page 153 with score 0.90 instead of being skipped at 0.82.
- Relaxed the early-exit rule in anchor search so a later exact heading can beat an earlier near-match.
- Widened plain-text and layout heading-region scans so real headings lower on the page can still win over appendix/chapter overview mentions.
- Added regressions for a later exact heading beating an earlier 0.98 near-match and for headings that begin below a large non-heading block.
- Regenerated the DOS manual output as `/tmp/DOS_6.22_Users_Manual_1994.v18.bookmarked.pdf`; `Keyboard Layouts for Single-Handed Users` now lands on page index 219, `Documentation on Audio Cassettes and Floppy Disks` on 220, and `Sample AUTOEXEC.BAT Files` is no longer skipped.
- Tightened generic short-heading matching so ambiguous titles like `Keyboard Layouts` require an exact standalone heading instead of attaching to earlier overview mentions.
- Added a regression for a generic short heading whose exact target appears later than an earlier broad mention.
- Regenerated the DOS manual output as `/tmp/DOS_6.22_Users_Manual_1994.v19.bookmarked.pdf`; `Keyboard Layouts` now lands inside Appendix C at page index 223, and the Appendix B/C cluster is currently the best approval candidate.
- Added a layout-first TOC fallback for collapsed OCR contents pages that uses positioned layout rows as titles and harvests page numbers from dedicated number lines when possible.
- Tightened TOC candidate selection so a front `CONTENTS` header cluster is preferred over later false positives.
- Added a regression for collapsed layout-only contents extraction.
- Baseline-tested the new path on `pdfs/4DOS_Reference_Manual.pdf`. It improved from `0` extracted TOC entries / `0` written bookmarks to `150` extracted TOC entries and `74` written bookmarks, but the result is not yet approval-ready because page-number alignment on the middle TOC pages is still noisy and the command-reference section is underbookmarked by the current readability filter.
- Tightened collapsed-TOC page-number recovery by filtering both layout-derived and text-derived number streams against the PDF page count and preferring the richer sane stream.
- Relaxed bookmark confidence gating for legitimate command-reference headings such as `ALIAS`, `ATTRIB`, and `DATE`.
- Added regressions for monotonic collapsed-TOC page-number recovery and all-caps command-reference headings.
- Re-ran `pdfs/4DOS_Reference_Manual.pdf` and improved it to `167` extracted TOC entries and `150` written bookmarks in `/tmp/4DOS_Reference_Manual.v3.bookmarked.pdf`.
- Added a distance penalty to non-structural anchor matching so far-away exact hits in indexes no longer beat nearer section headings by default.
- Updated the writer to preserve generic level-2 parent headings when they have valid accepted descendants, which fixes orphaned subtrees like `Hardware` and `Software`.
- Added regressions for local-heading preference over far index hits and for preserving generic parent nodes that carry valid children.
- Re-ran `pdfs/4DOS_Reference_Manual.pdf` as `/tmp/4DOS_Reference_Manual.v4.bookmarked.pdf`. Chapter 7 now keeps `Hardware` and `Software` as parents, and bad long-range hits like `Filename Completion -> Index` are gone.
- Added confidence exceptions for obvious top-level entries and strong single-word headings, while keeping `Index`/`Glossary`/`Summary` blocked.
- Extended sequence repair to short headings so out-of-order anchors like `Redirection` can be pulled back into their sibling range.
- Fixed layout-only TOC extraction so symbolic command titles like `?` are no longer dropped before matching.
- Added regressions for symbolic command extraction/matching and the updated confidence rules.
- Re-ran `pdfs/4DOS_Reference_Manual.pdf` as `/tmp/4DOS_Reference_Manual.v6.bookmarked.pdf`. `Introduction`, `Redirection`, `Piping`, `Keystack`, and `?` are now all written into the outline.
- Added Doxygen-compatible module, class, and function comments across the Python source files and bootstrap entry points.

Remaining tasks:
- Resume Milestone 2 heuristic work after the documentation pass.
- Improve TOC detection for more layouts and multi-page TOCs.
- Reduce false positives for short or generic headings during anchor matching.
- Tune the conservative bookmark-writing thresholds on real PDFs.
- Use captured TOC layout/font data in a later pass as an offline classification aid rather than directly overriding the working hierarchy heuristic.
- Tighten remaining same-page hierarchy misses like Appendix/Getting Help/DriveSpace cases by extending the TOC-side peer normalization rules without making them document-specific.
- Add actual clickable TOC-page link annotations by locating TOC text rectangles and placing PDF link annotations over them.
- Decide how to preserve existing good outline items while adding missing TOC-derived children.
- Decide whether the current JSON CLI is the final output format.
- Audit remaining anchor outliers that still land on the wrong nearby page even after the heading-window matcher, especially repeated CONFIG/AUTOEXEC-style sections.
- Finish the 4DOS layout-first TOC work by reducing remaining mistargets in weak-OCR headings such as `Filename Completion`, `Multiple Commands`, and some directive subsections where the heading text is not recoverable cleanly from the page text.
- Decide whether low-signal section titles like `Configuration Directives`, `Color Directives`, and `Batch File Variables` should use chapter-local sequence interpolation or remain conservatively skipped when OCR does not expose a reliable page heading.
- Tighten the remaining 4DOS middle-section misses, especially `Configuration Directives`, `Color Directives`, `Batch File Variables`, and `Multitasking and Disk Swapping`.

Known constraints:
- Anchor matching is heuristic and can overmatch generic titles like `Files`, `Index`, or `Getting Help`.
- Text-layer extraction/OCR artifacts can still distort titles, such as umlauts or ligatures rendered incorrectly.
- Full-book analysis runs are becoming expensive enough that large PDFs may need more targeted verification while heuristics are still evolving.
- The repo-root `toc-bookmarks` launcher now installs declared dependencies into `.venv`; direct `python3 -m toc_bookmarks` still depends on the active Python environment already having `pypdf`.
- Bookmark writing currently creates a new output PDF; it does not merge with or preserve existing bookmark trees intentionally.

Active Mode: General Systems Mode
Last successful build command: .venv/bin/python -m unittest discover -s tests
Outstanding blockers:
- None for the TocSmith 1.0 repository preparation; packaging installation,
  the primary launcher, version reporting, privacy scan, and all 60 tests pass.
- None for Milestone 5; crop inference, mark detection, rotation normalization,
  watermark placement, real-document serialization, and visual spot checks pass.
- None for the LaserJet combined-service-manual pass; the 51-test suite passes,
  all 101 detected TOC entries were written, and the serialized outline audit
  found no invalid destinations.
- None for the Watson chess contents-detection change set; the test suite passed and the reported command wrote 47 bookmarks.
- Bookmark generation works, but quality tuning is still needed before treating it as safe by default for arbitrary manuals, especially on noisier TOCs like Modern Chess Openings.
- `pdfs/Mastering-the-Chess-Openings-Watson-Volume-3.pdf` now detects the Contents pages and writes bookmarks, but some titles remain skipped or noisy due to OCR/chess-symbol extraction artifacts and low anchor scores.
- The 4DOS manual is now partially successful, but still not approval-ready because some section anchors drift badly when OCR loses the heading text entirely, and some generic parent headings are still skipped even when they are structurally necessary.
- The 4DOS manual `v4` is materially better than `v3`, but a few weak-OCR middle-section headings still either drift to nearby neighbors or get skipped conservatively.
- The 4DOS manual `v6` is the current best candidate. The remaining misses are concentrated in a small set of weak-OCR middle sections rather than broad outline failures.
- The structural-fix 4DOS output supersedes `v6` as the current best candidate;
  the remaining misses are still concentrated in weak-OCR middle sections.
