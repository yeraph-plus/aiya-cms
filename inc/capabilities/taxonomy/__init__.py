"""Taxonomy capability: flat multi-dimensional labels.

Contract source: context/spec/capabilities/taxonomy.md.

Mark any target type without importing it; dimensions are declared by
features, terms and assignments are maintained here.
"""

from __future__ import annotations

from inc.capabilities.taxonomy.dimensions import DimensionRegistry, DimensionSpec

__all__ = ["DimensionRegistry", "DimensionSpec"]
