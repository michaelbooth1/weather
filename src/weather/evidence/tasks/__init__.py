"""Evidence light-lane tasks (plan S5). Each module exposes ``run(ctx, days=None) -> dict`` and is
started by :mod:`weather.evidence.batch`. Parsers are pure functions so tests drive them from
fixtures; no test fetches a live endpoint."""
