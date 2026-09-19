# Research Audit Harness

- **Owns:** the rules for `tools/research/` scripts (`SCRIPT_INVENTORY`, status
  meanings, naming) and which package reports replace scratch probes.
- **Read when:** adding, running or retiring an ad-hoc research script.
- **Do not use for:** research conclusions (`ESTABLISHED_FINDINGS.md`,
  `RETRACTED_AND_FALSE_LEADS.md`) or mission dispatch
  ([DELEGATION_CONTRACT.md](DELEGATION_CONTRACT.md)).
- **Verify with:** `SCRIPT_INVENTORY` in `tools/research/research_harness.py`.

> **Host and scope:** new model-alpha research is paused (`STATE_OF_PLAY.md`).
> The report modules below read large local evidence; on the capture host run
> them only inside an admitted window ([HOST_LOAD_POLICY.md](HOST_LOAD_POLICY.md)),
> otherwise use the workstation.

The supported entrypoint for ad-hoc research scripts is:

```powershell
.\venv\Scripts\python.exe tools\research\research_harness.py --validate --smoke
```

Use `--list` to inspect script status. Status meanings:

- `supported`: maintained script with a network-free `--help` smoke.
- `fixture-only`: local-data or historical fixture script; compile-smoked only.
- `retired`: one-off live probe or stale helper. Do not use for current model
  claims.

Live same-day investigations should start from maintained package reports:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.promotion.promotion_refresh
.\venv\Scripts\python.exe -m weather.reporting.scorecards.snapshot_evaluation
.\venv\Scripts\python.exe -m weather.reporting.casebooks.disagreement_casebook
.\venv\Scripts\python.exe -m weather.reporting.fleet.fleet_observability
```

No-market extra-location transfer experiments should use the package harness
instead of scratch scripts:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.location_analysis.extra_location_registry
.\venv\Scripts\python.exe -m weather.reporting.location_analysis.no_market_location_transfer observations.csv --target-markets nyc --extra-locations boston,philadelphia --holdout-years 2025 --cutoff-regimes early --scoring-backend fast_residual
```

The transfer harness is price-free by design: it scores target-only,
target-plus-extra, extra-only, and similarity-weighted candidates on held-out
target labels, then emits JSON, CSV, and Markdown under `data/backtest/`.

Before adding a new file under `tools/research`, add it to
`SCRIPT_INVENTORY` in `tools/research/research_harness.py` and give it a
network-free smoke mode. Live scripts that require external APIs should stay
`retired` until their durable finding is migrated into a package report,
roadmap item, or fixture-backed test.

Do not add `test_*.py` files under `tools/research`. Retired probes should use
`retired_*.py` names, and executable checks belong under `tests/`.

## Update this file when

Update when the harness flags, status vocabulary, `tools/research` naming
rules, or the recommended package report entrypoints change.
