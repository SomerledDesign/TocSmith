# TocSmith
I like PDFs to include bookmarks. The problem? When I download a PDF from the web, it often has selectable text and a printed table of contents but no useful sidebar bookmarks.

This project is a Python tool that:
- reads the PDF text layer
- detects likely TOC pages
- extracts TOC entries
- checks existing bookmarks
- resolves TOC entries to likely anchor pages
- writes a new PDF with generated sidebar bookmarks
- emits a human-readable decision log for why entries were written or skipped

> This build is in Python
 
 *** Things to Note ***
  - The number in the TOC is not always the actual page number in the pdf. We therefore prefer matching TOC text to the heading text on the destination page.
  - If the pdf is not OCR, Dont mess with it.  Skip it.
  - The target is a broad-range script, not a set of one-off fixes for the current sample PDFs.
  - Heuristics should generalize to most manuals and books, even though real PDFs will stay messy.
  - TOC text itself being clickable inside the page is a separate feature from sidebar bookmarks.
  - TOC typography and TOC indentation can be captured and analyzed, but they should not override the working text-first hierarchy until they are proven to improve results consistently.

  ## Current State

  ### Working Now
  - Detect OCR / extractable text
  - Detect likely TOC pages
  - Extract TOC entries from noisy TOC lines
  - Compare existing bookmarks to TOC entries
  - Match TOC entries to likely anchor pages
  - Write a new output PDF with generated sidebar bookmarks
  - Write a human-readable `.log.txt` file showing:
    - written vs skipped
    - title
    - level
    - printed page
    - anchor page
    - match score
    - reason for decision
  - Infer Letter or Half Letter finished size from the first clean pages
  - Crop later oversized pages when explicit/vector crop marks confirm the trim
  - Add a configurable footer watermark to every generated page

  ### Current Heuristics
  - Text-first TOC extraction and hierarchy inference
  - Conservative bookmark writing thresholds
  - Slightly looser acceptance for child entries under already-accepted parents
  - TOC peer reconciliation when a suspicious level-3 entry visually aligns with a known level-2 peer on the TOC page
  - Chess-specific readability handling for noisy TOC lines that contain move prefixes

  ### Known Weak Spots
  - Some heading levels are still misclassified
  - Some anchor pages still drift
  - OCR/text-layer artifacts can distort title text
  - Large or noisy TOCs still need tuning
  - TOC page link annotations are not implemented yet
  
  ## Milestones 

  ### Milestone - 1
  - Recognize OCR / Not OCR
  - Recognize likely TOC pages
  - Check whether bookmarks already exist
  - Compare bookmark coverage against TOC coverage
  - Status: complete

  ### Milestone - 2
  - Extract TOC entries from noisy real-world TOCs
  - Match TOC entries to likely destination pages
  - Generate a new PDF with sidebar bookmarks
  - Emit a readable decision log
  - Status: in progress and usable, but still heuristic

  ### Milestone - 3
  - Capture TOC layout metadata:
    - x position
    - y position
    - font face
    - font size
    - bold/italic proxies from font naming
  - Keep this data in an array / structured form for later classification passes
  - Use the captured TOC layout as a secondary classifier, not as a blind override
  - Reconcile sibling levels by comparing:
    - TOC visual peers
    - destination-page heading presentation

  ### Milestone - 4
  - Add clickable TOC text inside the PDF page itself by placing link annotations over the TOC text rectangles
  - Preserve existing good bookmarks and add missing children where possible
  - Improve confidence handling so the script works on the broadest possible range of PDFs

  ### Milestone - 5 
  - Crop pages to layout lines, if larger than standard and crop lines are visible.
  - Add a configurable watermark to the bottom of each page
  - Status: complete

  ### Milestone - 6
  - Package the project for its first public repository as TocSmith
  - Add privacy-safe ignore rules, public documentation, and release/build metadata
  - Preserve `toc-bookmarks` as a compatibility command while making `tocsmith` primary
  - Release: 1.0 (build 345)
  - Status: complete
