# Workstation handback — guidance at all hours, mission 2026-09-111h

**PART 1 BUILT AND FIXTURE-VERIFIED; PART 2 PRE-REGISTRATION FROZEN (`ee10a75a`) AND PUSHED BEFORE
ANY EXTRACT OR SCORE. NO SCORE YET: Part 2 waits for production's extract and the owner's transfer.**
The all-hours question is unanswered; nothing here is evidence for or against it.

Branch `codex/guidance-all-hours-20260930`, base `origin/master` `b0032a90`. Handoff:
`docs/roadmap/workstation-handoff-2026-09-111h-corrected-guidance-all-hours.md` on
`codex/exam-fixes-handoffs-20260929`. Reservation status re-read: **NONE RESERVED**. Open questions
served: none named by the handoff.

## 1. Production extractor command (run this; paths are production paths)

Run in the 00:30-09:00 window. The wrapper refuses outside it, below 50 GiB free, on stale or
≥ 70% memory-commit evidence, on a busy shared lease, off the assigned capture host, on a source
tip other than the one given, or on a dirty source or parser tree. It holds the shared lease, runs
the child in a kill-on-close job, and ends by 09:00 or after 2 h, whichever is first.

```powershell
$prod = 'C:\Users\micha\Desktop\github\weather'
$env:GIT_LFS_SKIP_SMUDGE = '1'
git -C $prod fetch origin codex/guidance-all-hours-20260930 codex/nbm-target-fix-20260921
$tip = (git -C $prod rev-parse origin/codex/guidance-all-hours-20260930).Trim()   # must equal the reviewed head
git -C $prod worktree add --detach C:\pt\w111h $tip
git -C $prod worktree add --detach C:\pt\w111h-parser 2e17ce0eb
powershell -NoProfile -ExecutionPolicy Bypass -File C:\pt\w111h\scripts\ops\guidance_extract_run.ps1 `
  -ProductionRepoRoot $prod -ExpectedSourceTip $tip -ParserWorktree C:\pt\w111h-parser `
  -OutputRoot "$prod\data\exports\nbm-guidance-111h" -From 2026-08-01 -To 2026-09-29
```

The wrapper runs, with the production interpreter under `-P -B` and `PYTHONPATH=C:\pt\w111h\src`
after a probe proves the module resolves under that tree:

```text
python -P -B -m weather.reporting.research.guidance_extract --data-root <prod>\data
  --out <prod>\data\exports\nbm-guidance-111h --from 2026-08-01 --to 2026-09-29
  --parser-worktree C:\pt\w111h-parser --parser-python <prod>\venv\Scripts\python.exe
  --max-input-bytes 171798691840 --max-file-bytes 4294967296 --max-runtime-seconds <≤ 7170>
```

Output (create-only directory): `guidance_rows.jsonl.gz` (one row per admitted snapshot),
`market_days.jsonl.gz` (every in-range US market-day with its admission reason), `manifest.json`
(status, row counts, bulletin status counts, bytes and files read per source, files over the cap,
parser worktree HEAD and module SHA-256, extractor SHA-256, output SHA-256) and `SHA256SUMS`.
Exit 0 = `COMPLETE`; exit 3 = `INCOMPLETE_BUDGET_EXCEEDED` (input budget or deadline), recorded
in the manifest; any other failure writes no success line. After the run the two worktrees can be
removed with `git worktree remove`. Production writes nothing else; the only write is the new
export directory the handoff names.

## 2. What the extractor does

- **Population:** `data\snapshots\<slug>` folders of the 11 US markets (`display_unit == "F"`),
  target dates in range, label from `settlement_io.resolve_market_day_label` (ledger row, sidecar
  fallback; the authority status is kept per market-day), `promotion_countable is True`. Snapshot
  admission is 79a's: local capture date = target date, complete non-overlapping band support,
  finite served and market probabilities, served mass within 0.005 of 1, unique winner. Every
  exclusion is counted by reason.
- **Parser v2 at capture time:** every NBM manifest row of every US folder (targets ±1 day) indexes
  the retained national bulletins by payload SHA-256. A bulletin's availability time is its
  earliest `response_received_at` (then `fetched_at`, `first_seen_at`, capture time). Each bulletin
  is read once from `data\forecast_payload_cas`, hash-checked, and parsed by v2 for every US
  station and target dates issue-date −1..+1. For a snapshot at time T the row takes the newest
  bulletin (by issue time from the bytes) that was available at or before T, issued at or before
  T and at most 24 h old (production's cycle look-back) and whose v2 parse is available. A
  bulletin first on the host after T is excluded and counted (`v2_skipped.after_capture`); a
  referenced bulletin whose bytes are gone is skipped (`bytes_missing`). The row also records the
  newest candidate's cycle and its v2 reason (e.g. `target_max_not_in_cycle` for 13Z/19Z), age in
  hours, issue and valid times, and the number of candidates.
- **Isolation:** parser v2 is imported only in a child `python -P -B` with
  `PYTHONPATH=<pinned>\src`; a probe must resolve the module under that tree with a trailing
  separator, HEAD must be `2e17ce0eb…` and tracked files unmodified. Production code is unchanged.
  (The `manual_order_journal.ps1` pattern this copies has `TrimEnd('')`/`+ ''` with empty strings
  on branch `codex/manual-order-journal-20260928`, so its prefix test accepts a sibling such as
  `src2`; this wrapper uses `'\'`. Reported, not fixed: that file belongs to another mission.)
- **Captured v1 read:** the snapshot's own NBM manifest row (`cycle_key`, `provider_update_time`)
  gives `v1_period` = `maximum` (00Z token) / `minimum` (12Z token) / `unknown` / `no_manifest_row`,
  beside the captured `nbm_prob_tmax_*` features, validity flags, `guidance_impossible_features`,
  `guidance_physical_floor`, `high_so_far` and `trusted_current_max`.
- **Point guidance:** from `replay_inputs.jsonl`, the HRRR high (`open_meteo_multimodel`
  `day_model_highs.ncep_hrrr_conus`) and the raw NWS-grid day maximum with `generatedAt` /
  `updateTime`; a value fetched or issued after capture is dropped (`after_capture`). HRRR has no
  issue time: Open-Meteo does not expose the model run (`hrrr_issue_status`).
- **Market:** `p_market_yes` (81a's market vector) plus Gamma `best_bid`/`best_ask` and their mid.
- **Bounds:** streamed line reads; every file charged whole before it is read; per-file cap
  (default 4 GiB, over-cap files skipped and listed); total input budget (default 160 GiB) and
  wall-clock deadline both end the run as `INCOMPLETE`. Gzip siblings of tiered families are read.
  Retained per-snapshot state is five manifest fields.

## 3. Deviations from the handoff, and why

- **Module path `weather.reporting.research.guidance_extract`, not `weather.research...`.**
  Research modules already live in `weather.reporting.research`; `weather.research` would be a new
  package outside the `PACKAGE_ROOTS` ratchet in `tests/operations/test_import_architecture.py`,
  which would need a boundary-doc and ratchet change in files other missions own.
- **Output schema ids (`guidance-extract-rows/1`) are not in the schema registry.** Registering a
  `*_vN` name edits the `schema_registry*` family, which is in all four capture closures; during the
  exam period that would make this research branch roll-sensitive. The ids deliberately avoid the
  audited `name_vN` pattern.
- **Not verified on real production folders.** Layout facts (manifest columns, CAS paths, replay
  inputs, ledger fallback) come from the writers' code; the extractor records missing or tiered
  files per market-day instead of failing. The manifest's `market_days` reasons are the check.

## 4. Verification

- `tests/reporting/test_guidance_extract.py`, 11 tests, pass. Fixtures are written by the
  production writers (`SnapshotStore.append_csv`/`append_jsonl`/`write_forecast_payloads` with
  master's v1 parse, `SharedForecastPayloadCAS`, `write_folder_label`) from the real NOAA blocks
  retained by 82a, and parser v2 runs from a real detached worktree of `2e17ce0eb` (CI checks out
  full history). They cover: a 07Z morning maximum (KATL p50 91 °F; v1 read 72 °F, the next
  morning's minimum, from the 13Z bulletin); a 13Z bulletin rejected as `target_max_not_in_cycle`
  with fallback to 07Z (age 8 h); a 19Z bulletin fetched after capture excluded; a missing 07Z blob
  skipped with fallback to 01Z; NWS grid after capture dropped; non-countable and Toronto days
  excluded; manifest and `SHA256SUMS` hashes; budget exhaustion reported; unpinned parser refused.
- Repo audits: import architecture, schema registry (`--strict`, 0 unregistered), module size,
  agent docs, path policy, ops-script ratchets — all pass locally. GitHub CI: see the PR.

## 5. Per-file roll verdict

`scripts\ops\roll_verdict.ps1 -Branch codex/guidance-all-hours-20260930` on the workstation:
**UNDECIDABLE — no live closure evidence** (the four status files exist only on production). By
construction: the two `.py` files are new modules imported by nothing but their test, so they can
enter no loaded-module closure; `.ps1`, `docs/` and `tests/` are roll-free. Expected **ROLL-FREE**;
production must re-derive it with the tool. No `schema_registry*` file is touched.

| File | Closures entered |
| --- | --- |
| `src/weather/reporting/research/guidance_extract.py` (new) | none (not imported by any loop) |
| `src/weather/reporting/research/guidance_extract_parser.py` (new) | none |
| `scripts/ops/guidance_extract_run.ps1` (new) | none (`.ps1`) |
| `tests/reporting/test_guidance_extract.py`, `docs/…` | none |

## 6. Part 2 — frozen, not scored

[Pre-registration](../research/guidance-all-hours-preregistration-2026-09-29.md), SHA-256
`ffc0491c68dc6fecb8294bbb914941d2602bdffaf5c581ca542b2eff1ea8a382`, freeze commit
`ee10a75ac9901b75b8809678561d581fcd70e8c7`, verified on `refs/heads/codex/guidance-all-hours-20260930`
before any extract exists. It fixes: 81a's candidate function unchanged with v2 values and the
builder's floor-validity rule recomputed on them; hour blocks 00-05/06-09/10-12/13-16/17-23 and all
hours; strata split at 2026-08-23 plus 81a's declared pooled summary; 81a's crossed bootstrap
(2,000 draws, seed 20260921), power, MDE and planning; the twice-81a line −0.013344; the two
handoff falsifiers; an 81a positive control run first; and the §10k wrong-period census. Results
will be appended here after the transfer.

## 7. What was NOT done

No production read or write, no registration, no Scheduler change, no restart, no merge, no
candidate fitted, no score, no α, no reservation, no network fetch, no mirror use. No file owned
by another mission was changed.
