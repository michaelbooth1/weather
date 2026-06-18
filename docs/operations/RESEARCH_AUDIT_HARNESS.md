# Research Audit Harness

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
.\venv\Scripts\python.exe -m weather.reporting.promotion_refresh
.\venv\Scripts\python.exe -m weather.reporting.snapshot_evaluation
.\venv\Scripts\python.exe -m weather.reporting.disagreement_casebook
.\venv\Scripts\python.exe -m weather.reporting.fleet_observability
```

Before adding a new file under `tools/research`, add it to
`SCRIPT_INVENTORY` in `tools/research/research_harness.py` and give it a
network-free smoke mode. Live scripts that require external APIs should stay
`retired` until their durable finding is migrated into a package report,
roadmap item, or fixture-backed test.
