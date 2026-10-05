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
