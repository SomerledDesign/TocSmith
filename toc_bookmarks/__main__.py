from __future__ import annotations

"""@file
@brief Repo-root bootstrap entry point for ``python3 -m toc_bookmarks``.

The file simply executes the real CLI module from ``src/toc_bookmarks`` so the
project can be run from a source checkout.
"""

from pathlib import Path

_SRC_MAIN = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "toc_bookmarks"
    / "__main__.py"
)

__file__ = str(_SRC_MAIN)

with open(__file__, "r", encoding="utf-8") as handle:
    exec(compile(handle.read(), __file__, "exec"))
