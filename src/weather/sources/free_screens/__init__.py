"""Research-only free-source screens (lane G, 2026-10-23).

Fetchers and parsers for free public sources screened on the development scorecard
(``weather.reporting.scorecards.dev_scorecard``). Nothing here is imported by capture, serving,
training or trading code; the screens and their verdicts live in
``docs/research/free-source-screens-2026-10-23.md``.

Every fetch is serial, rate-limited and resumable; every stored file is recorded with its sha256 in
an append-only receipt log next to it (``<root>/<source>/receipts.jsonl``). No fetch requests a date
after 2026-09-29 (station-local) for observation sources.
"""
