"""Explicit migration manifest.

Contract source: context/spec/kernel/database.md §6/§7.

Maps every shipped table owner to the model module that registers its
tables on the kernel Base metadata. ``alembic/env.py`` imports exactly these
modules; directory scanning is forbidden. Owners are ``kernel:<component>``
or ``capability:<name>``.

During the rebuild the manifest is empty: kernel models land in R3,
capability models land with their own phases, and everything is squashed
into a single ``0001_initial`` revision at R9.
"""

from __future__ import annotations

MIGRATION_OWNER_MODULES: dict[str, str] = {}
