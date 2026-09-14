from __future__ import annotations

"""@file
@brief Repo-root bootstrap package that forwards imports into ``src/toc_bookmarks``.

This shim lets ``python3 -m toc_bookmarks`` work directly from a checkout
without requiring callers to preconfigure ``PYTHONPATH``.
"""

from pathlib import Path

_SRC_PACKAGE_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "toc_bookmarks"
)

#: Real package directory used for module resolution during in-place execution.
__path__ = [str(_SRC_PACKAGE_DIR)]
__file__ = str(_SRC_PACKAGE_DIR / "__init__.py")

with open(__file__, "r", encoding="utf-8") as handle:
    exec(compile(handle.read(), __file__, "exec"))
