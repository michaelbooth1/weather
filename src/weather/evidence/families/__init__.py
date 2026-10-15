"""Evidence host recorder families (plan S4). Each module exposes ``build(family_cfg, locations)``
returning the family's :class:`weather.evidence.child.Channel` list. Parsers are pure functions so
tests drive them from fixtures; no test fetches a live endpoint."""
