# Maker replay v2 fixtures and fixture measurements

Fictional-only tooling for the [v2 engineering plan](../../../docs/research/maker-replay-v2-engineering-plan-DRAFT.md)
(W0 and the S1/S6 measurements). No captured, calibration, panel or settlement data is read.

- `fixture170.py` (W0): one fictional 88a-shaped UTC day at the real 170-condition daily union, with the
  horizon roll at each market's local midnight, subscription coverage groups, a trade rate, per-capture
  terms with rare body changes and per-condition outcome views. `Day.rows()` yields exporter-ordered v0.1
  rows; `maker_core.replay.v2.compaction.Compactor` turns them into v0.2. It extends #166's
  `tools/research/pull_cap_precheck/fixture.py` without changing that file's outputs.
- `run.py`: `s1` (bytes and records per kind, v0.1 vs v0.2, one full day) and `s6` (two-pass read, v0.2 ->
  v0.1 expansion compared byte for byte, with and without elidable repeats; crafted group mismatch). One
  measurement per fresh process, serially, through the workstation wrapper:

```powershell
$arguments = @('-m','tools.research.maker_replay_v2.run','s1','--out','<new scratch dir>')
$b64 = [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-Json -Compress $arguments)))
.\scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -PythonPath (Resolve-Path .\venv\Scripts\python.exe) -ArgumentsBase64 $b64 -RepoRoot (Get-Location)
```

A full day writes about 1 GB of v0.1 and v0.2 files under `--out`; delete it afterwards. Results and their
commit are in `docs/roadmap/agent-report-2026-10-03-mrv2-w0-w1.md`.

W3-W5 (the v2 engine, reference schedule, scorer and report in `src/maker_core/replay/v2/`) add:

- `sources.py`: W0's day at any band count (`ScaledDay`, identical to `Day` at 12 markets, and
  reproducible per `rows()` call), in-memory v0.1/v0.2 day sources, and coverage regrouping.
- `dense.py`: a quoting-dense fictional day (fresh books, agreeing views, frequent prints, events,
  settlements) so differential tests exercise legs, fills and running totals.
- `bench.py`: `s3` (engine runtime per pass vs B; one B per process), `s5` (v2 engine vs reference
  schedule on every pass and clock trial), `s7` (scored report and sidecar bytes per date), `s8`
  (`informed-v0` quoted fraction, v2 schedule vs the frozen loop) and `s9` (exact money on adversarial
  extremes over 16 carried days), reached through `run.py`. Results: `docs/roadmap/agent-report-2026-10-04-mrv2-w3-w5.md`.
