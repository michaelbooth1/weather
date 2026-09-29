# Workstation handoff 2026-09-110s — nightly sealed replay-bundle export

Written 2026-09-27 by the production agent (owner-approved plan). The replay panel (2026-09-30..10-13 per Clarification 1,
handoff 110r) and its calibration days (09-27..09-29) need one sealed bundle per closed UTC day for every city; the 110l
exporter works per named market/day and has never been run in production. Branch `codex/nightly-bundle-export-20260927`,
base `origin/codex/maker-replay-harness-20260926` (rebase on master after its landing).

## Build

- `python -B -m weather.market.maker_plugin.replay_export night --day <UTC> --data-root <path> --out <dir>`: exports every
  discovered city for one closed UTC day using the 110l exporter; per-market 64 MiB caps; refuses (never truncates) an
  over-cap day; sealed segments only; open-read-close; writes only under `--out`.
- Receipt per run: free bytes before/after, per-bundle hashes, exclusions and gaps (88a restarts, maintenance window),
  appended to an append-only `panel-ledger.jsonl` (day, cities, hashes, gaps, restart events). Re-running a sealed day refuses.
- Declared active intervals honour a prospective maintenance exclusion argument (`--exclude-utc 05:00-08:00`).
- A roll-free lease-held wrapper `scripts/ops/replay_bundle_export_nightly.ps1` for the 00:30-09:00 lane (time-gated,
  kill-on-close job, releases the lease before 04:55) and a registrar with `-WhatIf` and hash pins, following existing
  registrar patterns. Also include the 88a v2 fields the T+1 scorer (110u) needs, such as `release_calibration_method`
  (additive).
- State expected bytes per day from fixtures and mark production size as unmeasured.

## Deliverables

Fixtures only; no production data or credentials. Repo-wide audits in focused runs. Push, draft PR, report
`docs/roadmap/agent-report-2026-09-110s-nightly-bundle-export.md`, verdict first, exact production registration commands.
