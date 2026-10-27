"""Research-only dev-scorecard candidates for the free-source screens (lane G, 2026-10-23).

Each ``*_candidate.py`` file here is a ``--candidate-module`` / ``--control-module`` for
``weather.reporting.scorecards.dev_scorecard`` (``NAME``, ``fit(train)``, ``predict(state, snaps,
bands)``). They read research stores under ``data/research/free_sources`` and the workstation IEM
METAR copy; nothing in capture, serving or trading imports them. Pre-declared rules and verdicts:
``docs/research/free-source-screens-2026-10-23.md``.
"""
