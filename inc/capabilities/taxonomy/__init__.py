"""Taxonomy capability: flat multi-dimensional labels.

Contract source: context/spec/capabilities/taxonomy.md.

Public surface for the composition root: dimension declarations, queries,
diagnostics and the command context.
"""

from __future__ import annotations

from inc.capabilities.taxonomy.commands import CommandContext
from inc.capabilities.taxonomy.diagnostics import TaxonomyDiagnostics
from inc.capabilities.taxonomy.dimensions import DimensionRegistry, DimensionSpec
from inc.capabilities.taxonomy.queries import TaxonomyQueries

__all__ = [
    "CommandContext",
    "DimensionRegistry",
    "DimensionSpec",
    "TaxonomyDiagnostics",
    "TaxonomyQueries",
]
