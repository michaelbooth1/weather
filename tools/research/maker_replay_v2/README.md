# Maker replay v2 fixtures and fixture measurements

Fictional-only tooling for the [v2 engineering plan](../../../docs/research/maker-replay-v2-engineering-plan-DRAFT.md)
(W0, W2 and the S1/S2/S6 measurements). No captured, calibration, panel or settlement data is read.

- `fixture170.py` (W0): one fictional 88a-shaped UTC day at the real 170-condition daily union, with the
  horizon roll at each market's local midnight, subscription coverage groups, a trade rate, per-capture
  terms with rare body changes and per-condition outcome views. `Day.rows()` yields exporter-ordered v0.1
  rows; `maker_core.replay.v2.compaction.Compactor` turns them into v0.2. It extends #166's
  `tools/research/pull_cap_precheck/fixture.py` without changing that file's outputs.
- `capture170.py` (W2): the exporter's *input* at the same density, a fictional sealed 88a capture day
  written through the production `EvidenceStore` (hourly segments, one discovery and one reward capture per
  minute, book captures of at most 50 bands, per-subscription trade streams with outages) plus per-event
  plugin sources, for the 12 built-in markets. It drives the real exporters end to end.
- `s2.py` (W2): S2 (exporter peak vs output bytes, the v0.2 night exporter or the frozen v0.1 one), with the
  peak per exporter phase and the in-memory accumulators, and the book bytes-per-level sweep.
- `run.py`: the one admitted entry. `s1` (bytes and records per kind, v0.1 vs v0.2, one full day), `s6`
  (two-pass read, v0.2 -> v0.1 expansion compared byte for byte, with and without elidable repeats; crafted
  group mismatch), `s2-input`, `s2` and `books`. One measurement per fresh process, serially, through the
  workstation wrapper:

```powershell
$arguments = @('-m','tools.research.maker_replay_v2.run','s1','--out','<new scratch dir>')
$b64 = [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-Json -Compress $arguments)))
.\scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -PythonPath (Resolve-Path .\venv\Scripts\python.exe) -ArgumentsBase64 $b64 -RepoRoot (Get-Location)
```

S2 is three such runs: `s2-input --out A`, then `s2 --input A\capture --out B` (add `--format v0.1` for the
baseline), each in its own process. numpy's OpenBLAS commits about 47 MiB per thread at import, so set
`OPENBLAS_NUM_THREADS` before the wrapper and read it back from the result.

A full day writes about 1-2 GB under `--out`; delete it afterwards. Results and their commits are in
`docs/roadmap/agent-report-2026-10-03-mrv2-w0-w1.md` (S1, S6) and
`docs/roadmap/agent-report-2026-10-04-mrv2-w2.md` (W2, S1 from the exporter, S2).

W3-W5 (the v2 engine, reference schedule, scorer and report in `src/maker_core/replay/v2/`) add:

- `sources.py`: W0's day at any band count (`ScaledDay`, identical to `Day` at 12 markets, and
  reproducible per `rows()` call), in-memory v0.1/v0.2 day sources, and coverage regrouping.
- `dense.py`: a quoting-dense fictional day (fresh books, agreeing views, frequent prints, events,
  settlements) so differential tests exercise legs, fills and running totals.
- `bench.py`: `s3` (engine runtime per pass vs B; one B per process), `s5` (v2 engine vs reference
  schedule on every pass and clock trial), `s7` (scored report and sidecar bytes per date), `s8`
  (`informed-v0` quoted fraction, v2 schedule vs the frozen loop) and `s9` (exact money on adversarial
  extremes over 16 carried days), reached through `run.py`. Results: `docs/roadmap/agent-report-2026-10-04-mrv2-w3-w5.md`.

Rule 4 = option B (owner, 2026-10-05) adds `rule4.py`: real view cadence on any fictional day (`RealCadence`,
`restamped`: every view re-stamped at each book record, with NBP-like `stdev` drift), and the lazy-delivery
harness behind `tests/maker_core/test_replay_v2_rule4.py`. `s3` and `s5` take `--view-cadence real` to measure
under it.

Engine rulings W1(a), W2(a) and F3 (owner, 2026-10-07; registration C11-C13) add `attribution.py`: it re-runs
the fictional fixtures under the frozen engine and under each ruling alone and together, and attributes every
changed decision to its class (A1-A3, A5, A6) or fails (spec v3.2 §1.4, v3.3 §4.2). `frozen` is pinned to the
pre-fix digests in `tests/maker_core/fixtures/replay_v2_prefix_digests.json`. Since F3, `lockstep.drive` and
`pipeline.run_passes` require `time_zones` (market id to IANA zone). A scored run takes it from
`execution_manifest.market_time_zones`, which reads the bound universe inventory's `local_timezone` (already
checked against each descriptor's close and horizon) and refuses a market whose conditions disagree (owner Gate
Q1, 2026-10-07). That descriptor check is offset-only, so the zone is also checked by name against the caller's
domain registry (`registered=`, required (owner T3(a)); for weather `maker_replay_universe.registered_time_zones()`).
Zone names are strict and zone data is the pinned `tzdata` only (owner T1(a); `bundle.time_zone`: listed verbatim
by the pinned package's `zones` file and loaded from its bytes, never from the platform's TZPATH, else
`unknown_time_zone`). Fictional markets use `sources.FIXTURE_ZONES`. `day_roll.NO_REFRESH` turns the refresh off in
`lockstep.drive` and exists only for that re-run; `pipeline.run_passes` refuses it (`day_roll_refresh_required`).
`run_passes` copies the zone map once at entry and records `Run.binding` (owner T2(a); `pipeline.run_binding`):
the refresh flag, the zone map, its sha and its source (`market_time_zones` or `caller`), the tzdata version with
the sha of each zone file used, and a digest of the run's own days, provenance, input hashes, markets, report
configuration and the zone map it drove with (kept as `Run.time_zones`). `report.build_report` refuses a run
without that binding or with another run's binding (also from a same-input run driven with another map), recomputes
the tzdata block from the zone bytes it loads, and for a non-fixture report requires the full `market_time_zones`
source (builder, `registry_checked`, inventory and registry digests). That stops accidental misuse (a run driven
around `run_passes`, a hand-made map, a reused binding); it is an integrity check, not proof against deliberate
forgery, since a caller can construct a `RegisteredZones` with a made-up source. For
`maker_replay_universe.universe()` inventories the registry check is close to a tautology (both sides read
`BUILTIN_SPECS`); it catches a tampered or hand-built inventory, not a wrong registry entry.
Run it through the workstation queue only: `python -m tools.research.maker_replay_v2.attribution OUT.json`.
