"""Per-family schema records (Data Layer v2 PL-2); roll-free by construction.

One module per capture family, ``<family>.py``, defining ``SCHEMAS`` (a tuple of
``weather.schema_registry_types.SchemaSpec``) and optionally
``EXCLUDED_SCHEMA_LITERALS``. Family modules import only
``weather.schema_registry_types``. No capture loop may import this package or a
module in it: that is what keeps a family schema addition ROLL-FREE under
``scripts/ops/roll_verdict.ps1``. The strict audit (``python -m
weather.schema_registry audit --strict``) discovers and checks every family; a
family that collides with the frozen core or another family fails it.

Family producers resolve their versions with :func:`schema_version` below, which
answers for core and family names alike.
"""

from __future__ import annotations

from weather.schema_registry_families import family_schema_version as schema_version

__all__ = ["schema_version"]
