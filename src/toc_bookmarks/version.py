"""TocSmith release and build identifiers.

Keep the public release and cumulative build number separate: the release
tracks compatibility while the build records the project's longer lineage.
"""

VERSION_MAJOR = 1
VERSION_MINOR = 1
VERSION_PATCH = 0
BUILD_NUMBER = 348

__version__ = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
VERSION_LABEL = f"{__version__} ({BUILD_NUMBER})"
