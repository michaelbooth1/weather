# 110o part 8 — 95d market universe without its bulk data on master (owner decision 8, D4-5) [DONE]

**Verdict: DONE, roll-free. Branch `codex/110o-market-universe-hashes-20260929` brings the 95d report, tool, tests and
small evidence files to master; the four bulk files (26.9 MB, including the 24 MB `markets.csv`) stay only on
`codex/weather-market-universe-20260924` at `8c683766`, bound by the unchanged `SHA256SUMS.txt` on master and a new
`fetch-evidence` command that restores and hash-checks them into the data root.** No size-budget exemption was
needed: no file this branch adds exceeds 250,000 bytes (largest: `families.md`, 74,028).

Handoff [workstation-handoff-2026-09-110o](workstation-handoff-2026-09-110o-repo-health-owner-decisions.md) part 8;
audit row D4-5 ([D4](audits/repo-health-audit-2026-09-26/dimensions/D4.md)).

## Deviation from the handoff wording, and why

The handoff says "rebase `codex/weather-market-universe-20260924`". That branch is pushed, and the session boundary
forbids rebasing a pushed branch or rewriting history. Instead the master-bound content was taken, by path, from its
tip `8c683766` onto a fresh branch from `origin/master`; the 95d branch is left untouched as the raw-data carrier.
The result is what the decision asks for: raw data off master, hashes and a fetch/rebuild note on master.

## What changed

| File | Roll | Change |
| --- | --- | --- |
| `docs/roadmap/agent-report-2026-09-95d-weather-market-universe.md` | roll-free | 95d report; its one link to the off-master `families.json` now points to `FETCH.md`. |
| `docs/roadmap/weather-market-universe-20260924/` (`README.md`, `SHA256SUMS.txt`, `summary.json`, `families.md`, `excluded.csv`, `proposals.json`, `forecast_probes.json`, `source-read-notes.json`, `roll-verdict.txt`) | roll-free | Byte-identical to `8c683766`; `SHA256SUMS.txt` still hashes all twelve evidence files. |
| `docs/roadmap/weather-market-universe-20260924/FETCH.md` | roll-free | Where the bulk files live, their sizes, the fetch/verify commands. |
| `tools/weather_market_universe.py` | roll-free (tool; imported by nothing) | Pins `EVIDENCE_COMMIT`/`EVIDENCE_BRANCH`; new `fetch-evidence`; `--output` defaults to `data/research/weather-market-universe-20260924/` so `rebuild` never re-adds bulk files under `docs/`. |
| `tests/reporting/test_weather_market_universe_tool.py` | roll-free | The 95d tests, moved from `tools/` (pytest collects only `tests/`, so CI never ran them) plus a fixture-repo test: tracked + pinned assembly, hash mismatch, missing commit. |

Kept off master: `markets.csv` 23,867,601 B, `events.csv` 2,001,359 B, `families.json` 611,023 B, `book_samples.json`
522,030 B. `families.json` and `book_samples.json` are under 1 MiB but over the 250,000-byte roadmap-data rule of the
pending ratchet (PR #106) without a mission id in their names, so keeping them off master avoids adding any exemption.

## Verification

- `python tools\weather_market_universe.py fetch-evidence --output <scratch>` on this clone: `PASS: 12 files ... match
  SHA256SUMS.txt (bulk files from 8c683766d26f)`; then `verify --output <scratch>`: `PASS: 5492 distinct events, 60347
  distinct Gamma markets, 60303 distinct conditions, 44 un-deployed/unidentified markets excluded from rewards; every
  family and pool total reconciles.` (positive control: the 95d report's own counts).
- `tests/reporting/test_weather_market_universe_tool.py` 9 passed; repo-wide audits in the PR description run.

## What was NOT done

No registration, no production write, no restart, no merge. The 95d branch was not rebased, force-pushed or deleted.
No venue or network call (fetch-evidence reads the local git object store only).

## Production steps

1. CI green; `roll_verdict.ps1 -Branch codex/110o-market-universe-hashes-20260929` roll-free; land on the roll-free
   light path when the exam-period merge policy allows.
2. Keep `codex/weather-market-universe-20260924` permanently: under the part-7 lifecycle rule it is unmerged, so any
   future retirement must first push `archive/weather-market-universe-20260924` at `8c683766` (then `FETCH.md`'s
   `git fetch` line becomes `git fetch origin tag archive/weather-market-universe-20260924`). Close no PR for it (it has none).
3. Anyone needing the bulk files: the three commands in `FETCH.md`.
