"""Archive delivery adapters.

Importing this package only imports inert adapter classes. Provider settings
are read and HTTP clients are called only from an explicit Port method.
"""

from __future__ import annotations

from inc.adapters.archive.gofile import GofileArchiveProvider, GofileSettings
from inc.adapters.archive.openlist import OpenListArchiveProvider, OpenListSettings

__all__ = [
    "GofileArchiveProvider",
    "GofileSettings",
    "OpenListArchiveProvider",
    "OpenListSettings",
]
