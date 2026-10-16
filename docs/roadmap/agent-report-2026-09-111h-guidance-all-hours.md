# Workstation handback — guidance at all hours, mission 2026-09-111h

**PART 2 VERDICT — THE ALL-HOURS ROUTE IS CLOSED FOR THE US MARKETS UNDER THE CURRENT RULES.**
Pooled US all-hours C1 − served = **−0.000924 [−0.006083, +0.003924]** (626 market-days, 57 dates ×
11 markets). That misses the twice-81a line −0.013344 both descriptively and on the interval. Falsifier 2 fires.
Falsifier 1 fires in **both** afternoon blocks: C1 is *worse* than served at 13-16 (+0.005986
[+0.002282, +0.009941]) and at 17-23 (+0.015495 [+0.010079, +0.020989]). The strata have opposite signs
(before −0.002613, from +0.000057). C2, which does not replace C1 as the primary, is −0.005112
[−0.008164, −0.002370]: also short of the line. The positive control **passed** first (−0.006891, inside 81a's
[−0.011525, −0.002373]), so the v2 tables are not labelled "stack not reconciled". This is a development
reading only: nothing is fitted, no α is spent, nothing is reserved, and no serving change follows.
Part 2 results are in §8 to §13.

Part 1 handback (unchanged below):

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
handoff falsifiers; an 81a positive control run first; and the §10k wrong-period census. Results are in §8 to §13.

## 7. What was NOT done

No production read or write, no registration, no Scheduler change, no restart, no merge, no
candidate fitted, no score, no α, no reservation, no network fetch, no mirror use. No file owned
by another mission was changed.

---

# Part 2 — analysis (workstation, 2026-10-03)

Branch `codex/guidance-all-hours-analysis-20261003`, cut from `origin/codex/guidance-all-hours-20260930`
(`03a028bd8`) with `origin/master` merged in. Every output header binds pre-registration SHA-256
`ffc0491c68dc6fecb8294bbb914941d2602bdffaf5c581ca542b2eff1ea8a382` and freeze commit
`ee10a75ac9901b75b8809678561d581fcd70e8c7`. Before reading any data, each stage re-checked: the
pre-registration bytes, `git show <freeze>:<prereg>`, that the freeze commit is an ancestor of HEAD, and that it is
an ancestor of the live remote `refs/heads/codex/guidance-all-hours-20260930` (`03a028bd8…`). Scored at
HEAD `5e6a3d9c`. Reservation status re-read: **NONE RESERVED**. Population: US only, development reading only.

## 8. Input verification and production facts

- **Input path (workstation):** `C:\Users\Michael\Documents\nbm-guidance-111h`, read in place through an
  explicit `--input`. The workstation `data\` folder refused new directories. Nothing was copied into the
  repository and no row-level data is committed.
- **SHA256SUMS:** all three files match. `guidance_rows.jsonl.gz` `32bc466f…af63`,
  `market_days.jsonl.gz` `82d04f35…fc1c`, `manifest.json` `d092b578…f5d1`.
- **Manifest:** status **COMPLETE**; parser HEAD `2e17ce0eba891b028a968ac45895d3c203ea7dda`;
  **110,807 rows** (all with `v2_status = available`); **626 market-days** admitted of 660 seen (34 not
  promotion-countable); 309 distinct bulletins, all parsed. Started **2026-10-03T05:51:15Z** and finished
  **06:35:31Z**. Arguments: `--from 2026-08-01 --to 2026-09-29`.
- **Known deviation (last + 1 day):** the extractor indexes the day after `--to`, so it opened 2026-09-30
  NBM manifests. **Confirmed harmless for scoring: 0 rows have target date ≥ 2026-09-30** (the replay-exam
  panel). Target dates span 2026-08-01..2026-09-29 (57 dates). The scorer drops and counts any such row
  before scoring; the count is 0, so nothing was excluded or scored from the panel.

## 9. Positive control (run first; output written 2026-10-04T01:30Z, before any v2 score)

81a's exact rule on **captured (v1)** features, rows at 06-09 local with targets 2026-08-01..2026-09-19, US
pooled:

| Stratum | Rows; N; D/M | C1 − served [95%] | MDE80; power@−0.0075 | Reasons (rows) |
| --- | --- | --- | --- | --- |
| before_20260823 | 6,867; 227; 21/11 | −0.007021 [−0.013003, −0.001996] | 0.007792; 0.766 | eligible 3,136; incomplete 3,716; no floor 15 |
| from_20260823 | 8,364; 286; 26/11 | −0.006789 [−0.013345, −0.001555] | 0.008511; 0.678 | eligible 3,895; incomplete 4,458; no floor 11 |
| **pooled** | 15,231; 513; 47/11 | **−0.006891 [−0.011894, −0.002688]** | 0.006541; 0.899 | eligible 7,031; incomplete 8,174; no floor 26 |

**PASS:** −0.006891 lies inside 81a's [−0.011525, −0.002373] (81a: −0.006672 on 458 market-days and 13,584
rows). The population is wider than 79a's (fresh inventory, no 79a exclusions), yet the stack reproduces 81a.
The v2 tables therefore carry no "not reconciled" label.

## 10. EF §10k uncounted-item census

The population is rows at 06-09 local with target ≤ 2026-09-19 (15,231). Of these, **7,031** have a captured NBM set
that is 81a-eligible: complete, ordered, positive stddev, captured valid flag 1, and a finite 81a floor. All
7,031 also return `eligible` from 81a's candidate function.

| Manifest `v1_period` | Rows | Share of eligible | Market-days | Dates | Markets |
| --- | --- | --- | --- | --- | --- |
| **minimum (wrong period, passed the floor)** | **81** | **1.15%** | 8 | 8 | 4: san-francisco 45, chicago 23, nyc 8, denver 5 |
| maximum | 6,950 | 98.85% | 497 | 46 | 11 |
| unknown | 0 | — | 0 | 0 | — |
| no_manifest_row | 0 | — | 0 | 0 | — |

Wrong-period dates: 2026-08-05, 08-08, 08-17, 08-20, 08-26, 09-08, 09-14, 09-16. No eligible row is unavailable.
Across all hours, 47 rows lack a manifest row, but none of them is in this population. This census covers the
table's own population, not the 79a export.

## 11. v2 C1/C2 versus served and versus market — headline cells

Full tables (every block × stratum, ratio to market, absolute Brier, C2 − C1, changed shares, eligibility
reasons, planning) are in §14. Delta = candidate − served Brier, 95% crossed date × market bootstrap,
2,000 draws, seed 20260921.

| Block (pooled strata) | N; D/M | C1 − served [95%] | C2 − served [95%] | C1 changed rows | C1 reasons: eligible / not valid / no floor |
| --- | --- | --- | --- | --- | --- |
| 00-05 | 626; 57/11 | −0.012702 [−0.020714, −0.006106] | −0.012021 [−0.017605, −0.007462] | 95.4% | 25,901 / 687 / 574 |
| 06-09 | 623; 57/11 | −0.013430 [−0.021560, −0.006416] | −0.012971 [−0.018351, −0.008236] | 97.5% | 18,031 / 417 / 39 |
| 10-12 | 626; 57/11 | −0.008044 [−0.013316, −0.003315] | −0.009343 [−0.012863, −0.006249] | 88.5% | 12,876 / 1,653 / 22 |
| 13-16 | 626; 57/11 | **+0.005986 [+0.002282, +0.009941]** | −0.000698 [−0.002679, +0.001138] | 50.5% | 9,393 / 9,184 / 22 |
| 17-23 | 626; 57/11 | **+0.015495 [+0.010079, +0.020989]** | +0.004631 [+0.002470, +0.006648] | 26.4% | 8,440 / 23,495 / 73 |
| **all hours** | 626; 57/11 | **−0.000924 [−0.006083, +0.003924]** | **−0.005112 [−0.008164, −0.002370]** | 67.4% | 74,641 / 35,436 / 730 |

Versus market, every cell is worse than the market. All-hours pooled ratio of mean Brier to market: C1 1.741
[1.584, 1.926] and C2 1.620 [1.469, 1.814]; served's absolute Brier is 0.0610 against market 0.0345. At 17-23
the market Brier is about 0.0008, so ratios there exceed 40.

## 12. Primary decision rule and falsifiers, stated plainly

- **Reaches twice (descriptive):** **NO.** The pooled US all-hours C1 − served of −0.000924 is above −0.013344.
- **Reaches twice (interval):** **NO.** The upper bound +0.003924 is above −0.013344, and the interval includes 0.
- **Strata:** before −0.002613 [−0.010428, +0.004840] and from +0.000057 [−0.005780, +0.006557]. They have opposite signs, but
  the pooled result does not pass, so the pre-registered "pooled pass with opposite-sign strata" caveat does not arise.
- **C2 on the same rule:** −0.005112 [−0.008164, −0.002370], with strata −0.005739 and −0.004748. It does not reach
  twice on either test. C2 does not replace C1.
- **Falsifier 1, stale 07Z adds nothing: FIRES in both blocks.** At 13-16 and at 17-23 the pooled C1 − served
  estimate is ≥ 0, and so are both intervals: the v2 07Z-anchored distribution is measurably *worse* than served
  in the afternoon. The afternoon route is falsified for 13-16 and for 17-23.
- **Falsifier 2, pooled effect stays near 81a: FIRES.** −0.000924 > −0.013344. **The all-hours route is closed
  for the US markets under the current rules.**

Read without the rule: the benefit is concentrated in 00-09, where the v2 C1 morning estimate of −0.013430 sits beside the
captured-v1 control's −0.006891 on a narrower date range. The afternoon harm cancels it. Any hour-gated candidate
built on that observation would be a new, post-hoc hypothesis. It is **not authorized** here and none was
computed. Planning (§14) finds no cell with a finite plug-in date count except C2 at 10-12. Every other beneficial
cell is `MARKET_CLUSTER_FLOOR_LIMITED` or not reached, and every afternoon cell is non-beneficial.

## 13. Run record, roll verdict, reproduction, not done

- **Attempts (all retained in scratch, create-only):** `control` (attempt 1) failed at the first row. The extract's
  bands carry a display `label` that 81a's `Band` rejects, and no score was computed. The fix
  (`5e6a3d9c`) passes only `kind/low/high`. Then came `control-2` (PASS), `census-1` and `score-1` (first v2 score at
  2026-10-04T01:30:52Z), followed by an aggregate-only `publish-1`. Output SHA-256 values: control `5f0f3a3a…3b42`,
  census `5f409244…12e3`, development `10e57e71…889b` (row deltas `98743907…0011`, kept in scratch only).
  The committed aggregate is `tools/research/guidance_all_hours/evidence.json`.
- **Statistics:** 81a's `candidate.py` and `statistics.py` are imported unchanged, with dependency hashes in every header.
  `features.py` replaces only the seven NBM values and recomputes the two flags with the builder's rule (floor =
  captured `guidance_physical_floor`, margin 0.9 °F, representative p90 → mean → p50, partially impossible =
  invalid, no floor = valid).
- **Heavy work:** every test and stage ran through `scripts\ops\workstation_heavy.ps1`. The new module is
  admitted by exact name in `workload_admission.ps1` and in the Codex hook, with tests, following 81a's precedent.
  One stale lease from another session's hung pytest blocked the queue. The owner ended that process tree; the
  wrapper's own stale-marker recovery cleared the lease, and no lease state was edited by hand.
- **Roll verdict:** `roll_verdict.ps1 -Branch codex/guidance-all-hours-analysis-20261003` on the workstation
  returned **UNDECIDABLE — no live closure evidence**, as expected. By construction the result is **ROLL-FREE**: the new
  `tools/research/guidance_all_hours/*` is imported by nothing but its tests, `.ps1` and docs are roll-free,
  and `.codex/hooks/pre_tool_use_host_load.py` is an agent hook outside every loop closure. No `schema_registry*`
  or `src/` file is touched. Production must re-derive the verdict.
- **Reproduction:** on any host, run from a checkout whose root is *not* the extract's parent, because the scorer
  refuses inputs and outputs inside its own repository. Each `run` stage goes through
  `workstation_heavy.ps1 -Kind weather_heavy` with these Python arguments:

  ```text
  -m tools.research.guidance_all_hours.run control --input <extract> --output <new>\control
  -m tools.research.guidance_all_hours.run census  --input <extract> --output <new>\census
  -m tools.research.guidance_all_hours.run score   --input <extract> --output <new>\score --control <new>\control\control.json
  python -m tools.research.guidance_all_hours.publish --control … --census … --development <new>\score\development.json --output <new>\publish
  ```

  On the capture host this is heavy work. It runs only 00:30-09:00 under the shared lease, and the production
  extract `<prod>\data\exports\nbm-guidance-111h` lies outside a `C:\pt\…` worktree.
- **Not done:** no refit, weight search, alternative floor, recency rule, hour-gated candidate, reservation, α,
  serving/config/artifact change, production read or write, registration, Scheduler change, restart or merge.
  No data was committed. The findings digest, established findings and STATE_OF_PLAY were not edited; on acceptance
  they are production's to update (delegation contract §5).

## 14. Result tables (aggregate; generated by `publish.py` from the bound outputs)

Pre-registration SHA-256 `ffc0491c68dc6fecb8294bbb914941d2602bdffaf5c581ca542b2eff1ea8a382`; freeze commit `ee10a75ac9901b75b8809678561d581fcd70e8c7`.

95% crossed date × market bootstrap, 2,000 draws, seed 20260921. N = market-days; D/M = date/market clusters. Delta = candidate − served Brier.

### 14a. v2 C1/C2 versus served and market

| Block / stratum | Rows; N; D/M | Cand. | Delta [95%] | MDE80; power@−0.0075 | Ratio to market [95%] | Ratio MDE80; power@−0.10 | Changed rows (share) | Changed N; D/M |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 00-05 / before_20260823 | 9667; 230; 21/11 | C1 | -0.012318 [-0.024145, -0.002663] | 0.015087; 0.253 | 1.2090 [1.0980, 1.3316] | 0.1638; 0.391 | 9347 (96.69%) | 229; 21/11 |
| 00-05 / before_20260823 | 9667; 230; 21/11 | C2 | -0.012074 [-0.019336, -0.006473] | 0.009216; 0.604 | 1.2134 [1.1057, 1.3557] | 0.1734; 0.374 | 9347 (96.69%) | 229; 21/11 |
| 00-05 / from_20260823 | 17495; 396; 36/11 | C1 | -0.012925 [-0.021408, -0.005349] | 0.011709; 0.410 | 1.2036 [1.1080, 1.3245] | 0.1565; 0.432 | 16554 (94.62%) | 386; 36/11 |
| 00-05 / from_20260823 | 17495; 396; 36/11 | C2 | -0.011990 [-0.017453, -0.007184] | 0.007521; 0.796 | 1.2201 [1.1231, 1.3346] | 0.1496; 0.450 | 16554 (94.62%) | 386; 36/11 |
| 00-05 / pooled | 27162; 626; 57/11 | C1 | -0.012702 [-0.020714, -0.006106] | 0.010439; 0.507 | 1.2055 [1.1324, 1.2859] | 0.1069; 0.751 | 25901 (95.36%) | 615; 57/11 |
| 00-05 / pooled | 27162; 626; 57/11 | C2 | -0.012021 [-0.017605, -0.007462] | 0.007086; 0.843 | 1.2177 [1.1412, 1.3051] | 0.1171; 0.688 | 25901 (95.36%) | 615; 57/11 |
| 06-09 / before_20260823 | 6867; 227; 21/11 | C1 | -0.015458 [-0.026942, -0.005208] | 0.015188; 0.254 | 1.2424 [1.1219, 1.3764] | 0.1788; 0.340 | 6788 (98.85%) | 226; 21/11 |
| 06-09 / before_20260823 | 6867; 227; 21/11 | C2 | -0.014157 [-0.021606, -0.007899] | 0.009704; 0.561 | 1.2673 [1.1408, 1.4237] | 0.2029; 0.287 | 6788 (98.85%) | 226; 21/11 |
| 06-09 / from_20260823 | 11620; 396; 36/11 | C1 | -0.012267 [-0.021034, -0.003982] | 0.012413; 0.378 | 1.2331 [1.1139, 1.3925] | 0.1993; 0.261 | 11243 (96.76%) | 385; 36/11 |
| 06-09 / from_20260823 | 11620; 396; 36/11 | C2 | -0.012292 [-0.017648, -0.007439] | 0.007383; 0.815 | 1.2327 [1.1206, 1.3718] | 0.1789; 0.326 | 11243 (96.76%) | 385; 36/11 |
| 06-09 / pooled | 18487; 623; 57/11 | C1 | -0.013430 [-0.021560, -0.006416] | 0.010527; 0.497 | 1.2364 [1.1461, 1.3354] | 0.1334; 0.564 | 18031 (97.53%) | 611; 57/11 |
| 06-09 / pooled | 18487; 623; 57/11 | C2 | -0.012971 [-0.018351, -0.008236] | 0.007222; 0.833 | 1.2448 [1.1552, 1.3467] | 0.1375; 0.549 | 18031 (97.53%) | 611; 57/11 |
| 10-12 / before_20260823 | 5361; 230; 21/11 | C1 | -0.011328 [-0.019948, -0.003347] | 0.011505; 0.422 | 1.2943 [1.1509, 1.4772] | 0.2251; 0.209 | 4941 (92.17%) | 226; 21/11 |
| 10-12 / before_20260823 | 5361; 230; 21/11 | C2 | -0.011089 [-0.016169, -0.006833] | 0.006612; 0.891 | 1.2992 [1.1490, 1.4914] | 0.2401; 0.203 | 4941 (92.17%) | 226; 21/11 |
| 10-12 / from_20260823 | 9190; 396; 36/11 | C1 | -0.006136 [-0.011797, -0.000348] | 0.008281; 0.719 | 1.3175 [1.1810, 1.4999] | 0.2228; 0.216 | 7935 (86.34%) | 373; 36/11 |
| 10-12 / from_20260823 | 9190; 396; 36/11 | C2 | -0.008328 [-0.011706, -0.005198] | 0.004780; 0.996 | 1.2757 [1.1490, 1.4425] | 0.2015; 0.276 | 7935 (86.34%) | 373; 36/11 |
| 10-12 / pooled | 14551; 626; 57/11 | C1 | -0.008044 [-0.013316, -0.003315] | 0.007221; 0.831 | 1.3093 [1.1979, 1.4350] | 0.1652; 0.389 | 12876 (88.49%) | 599; 57/11 |
| 10-12 / pooled | 14551; 626; 57/11 | C2 | -0.009343 [-0.012863, -0.006249] | 0.004671; 0.995 | 1.2840 [1.1767, 1.4089] | 0.1675; 0.388 | 12876 (88.49%) | 599; 57/11 |
| 13-16 / before_20260823 | 6833; 230; 21/11 | C1 | 0.003528 [-0.003820, 0.011124] | 0.010603; 0.514 | 2.0054 [1.6180, 2.6543] | 0.7731; 0.041 | 3505 (51.30%) | 182; 21/11 |
| 13-16 / before_20260823 | 6833; 230; 21/11 | C2 | -0.001549 [-0.004853, 0.001667] | 0.004693; 0.993 | 1.8242 [1.4805, 2.3918] | 0.6771; 0.041 | 3505 (51.30%) | 182; 21/11 |
| 13-16 / from_20260823 | 11766; 396; 36/11 | C1 | 0.007414 [0.002524, 0.013131] | 0.007565; 0.794 | 2.1082 [1.7862, 2.6032] | 0.5897; 0.057 | 5888 (50.04%) | 291; 36/11 |
| 13-16 / from_20260823 | 11766; 396; 36/11 | C2 | -0.000204 [-0.002495, 0.001945] | 0.003159; 1.000 | 1.8399 [1.5480, 2.3075] | 0.5289; 0.061 | 5888 (50.04%) | 291; 36/11 |
| 13-16 / pooled | 18599; 626; 57/11 | C1 | 0.005986 [0.002282, 0.009941] | 0.005477; 0.960 | 2.0707 [1.7437, 2.5823] | 0.5970; 0.057 | 9393 (50.50%) | 473; 57/11 |
| 13-16 / pooled | 18599; 626; 57/11 | C2 | -0.000698 [-0.002679, 0.001138] | 0.002678; 1.000 | 1.8342 [1.5496, 2.2985] | 0.5294; 0.059 | 9393 (50.50%) | 473; 57/11 |
| 17-23 / before_20260823 | 11813; 230; 21/11 | C1 | 0.012890 [0.005808, 0.020913] | 0.010521; 0.526 | 79.9667 [33.1627, 278.6169] | 207.2426; 0.050 | 2807 (23.76%) | 60; 21/11 |
| 17-23 / before_20260823 | 11813; 230; 21/11 | C2 | 0.004151 [0.001515, 0.007177] | 0.003858; 0.996 | 65.0037 [27.6082, 225.9004] | 163.9003; 0.050 | 2807 (23.76%) | 60; 21/11 |
| 17-23 / from_20260823 | 20195; 396; 36/11 | C1 | 0.017009 [0.010122, 0.025328] | 0.010917; 0.484 | 55.3554 [20.4472, 204.0731] | 161.3164; 0.050 | 5633 (27.89%) | 116; 33/11 |
| 17-23 / from_20260823 | 20195; 396; 36/11 | C2 | 0.004909 [0.002332, 0.007638] | 0.003772; 0.999 | 41.3094 [15.2051, 159.6581] | 125.7586; 0.050 | 5633 (27.89%) | 116; 33/11 |
| 17-23 / pooled | 32008; 626; 57/11 | C1 | 0.015495 [0.010079, 0.020989] | 0.007784; 0.764 | 62.3092 [29.3293, 185.0846] | 127.6554; 0.050 | 8440 (26.37%) | 176; 54/11 |
| 17-23 / pooled | 32008; 626; 57/11 | C2 | 0.004631 [0.002470, 0.006648] | 0.002988; 1.000 | 48.0041 [22.3990, 141.7035] | 99.2951; 0.050 | 8440 (26.37%) | 176; 54/11 |
| all_hours / before_20260823 | 40541; 230; 21/11 | C1 | -0.002613 [-0.010428, 0.004840] | 0.010457; 0.488 | 1.7490 [1.5549, 1.9911] | 0.3074; 0.127 | 27388 (67.56%) | 229; 21/11 |
| all_hours / before_20260823 | 40541; 230; 21/11 | C2 | -0.005739 [-0.010037, -0.001971] | 0.005570; 0.964 | 1.6552 [1.4552, 1.9231] | 0.3279; 0.118 | 27388 (67.56%) | 229; 21/11 |
| all_hours / from_20260823 | 70266; 396; 36/11 | C1 | 0.000057 [-0.005780, 0.006557] | 0.008949; 0.651 | 1.7370 [1.5429, 1.9877] | 0.3179; 0.116 | 47253 (67.25%) | 386; 36/11 |
| all_hours / from_20260823 | 70266; 396; 36/11 | C2 | -0.004748 [-0.007690, -0.001768] | 0.004341; 0.999 | 1.6005 [1.4310, 1.8345] | 0.2761; 0.156 | 47253 (67.25%) | 386; 36/11 |
| all_hours / pooled | 110807; 626; 57/11 | C1 | -0.000924 [-0.006083, 0.003924] | 0.007145; 0.838 | 1.7413 [1.5837, 1.9261] | 0.2413; 0.201 | 74641 (67.36%) | 615; 57/11 |
| all_hours / pooled | 110807; 626; 57/11 | C2 | -0.005112 [-0.008164, -0.002370] | 0.004055; 1.000 | 1.6199 [1.4689, 1.8139] | 0.2406; 0.233 | 74641 (67.36%) | 615; 57/11 |

### 14b. Absolute Brier, C2 − C1 and eligibility reasons

| Block / stratum | Served [95%] | Market [95%] | C1 [95%] | C2 [95%] | C2 − C1 [95%] | Day-weighted changed share C1 [95%] | Eligibility reasons (rows) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 00-05 / before_20260823 | 0.078600 [0.071112, 0.087417] | 0.054826 [0.047698, 0.062346] | 0.066283 [0.058876, 0.073158] | 0.066526 [0.061194, 0.072333] | 0.000244 [-0.004233, 0.005112] | 0.9675 [0.9231, 0.9958] | eligible 9347, missing_captured_floor 225, not_recorded_valid 95 |
| 00-05 / from_20260823 | 0.081005 [0.073112, 0.089470] | 0.056564 [0.051329, 0.061902] | 0.068080 [0.062630, 0.073537] | 0.069015 [0.064200, 0.073833] | 0.000935 [-0.002421, 0.004370] | 0.9470 [0.8925, 0.9877] | eligible 16554, not_recorded_valid 592, missing_captured_floor 349 |
| 00-05 / pooled | 0.080121 [0.073821, 0.087501] | 0.055925 [0.051399, 0.060456] | 0.067419 [0.062846, 0.071765] | 0.068101 [0.064190, 0.072322] | 0.000681 [-0.001740, 0.003543] | 0.9545 [0.9112, 0.9889] | eligible 25901, not_recorded_valid 687, missing_captured_floor 574 |
| 06-09 / before_20260823 | 0.080439 [0.073088, 0.088182] | 0.052302 [0.045161, 0.059841] | 0.064981 [0.057285, 0.072003] | 0.066282 [0.061073, 0.071209] | 0.001301 [-0.003221, 0.005717] | 0.9909 [0.9677, 0.9987] | eligible 6788, not_recorded_valid 63, missing_captured_floor 16 |
| 06-09 / from_20260823 | 0.081377 [0.073824, 0.088762] | 0.056044 [0.050521, 0.061726] | 0.069110 [0.062999, 0.075059] | 0.069085 [0.064448, 0.073510] | -0.000025 [-0.003828, 0.003624] | 0.9673 [0.9259, 0.9924] | eligible 11243, not_recorded_valid 354, missing_captured_floor 23 |
| 06-09 / pooled | 0.081035 [0.075222, 0.087921] | 0.054681 [0.049884, 0.059508] | 0.067606 [0.062735, 0.072129] | 0.068064 [0.064263, 0.071820] | 0.000458 [-0.002173, 0.003335] | 0.9759 [0.9498, 0.9942] | eligible 18031, not_recorded_valid 417, missing_captured_floor 39 |
| 10-12 / before_20260823 | 0.075591 [0.069307, 0.081838] | 0.049649 [0.041985, 0.057873] | 0.064263 [0.057066, 0.071131] | 0.064502 [0.059192, 0.069885] | 0.000240 [-0.004027, 0.004297] | 0.9223 [0.8446, 0.9725] | eligible 4941, not_recorded_valid 406, missing_captured_floor 14 |
| 10-12 / from_20260823 | 0.075156 [0.069008, 0.080842] | 0.052386 [0.046803, 0.057760] | 0.069020 [0.063357, 0.075037] | 0.066827 [0.061983, 0.071386] | -0.002193 [-0.005510, 0.000776] | 0.8625 [0.7586, 0.9502] | eligible 7935, not_recorded_valid 1247, missing_captured_floor 8 |
| 10-12 / pooled | 0.075315 [0.070928, 0.079858] | 0.051381 [0.046409, 0.056657] | 0.067272 [0.062773, 0.071575] | 0.065973 [0.062157, 0.069459] | -0.001299 [-0.003547, 0.000963] | 0.8845 [0.7902, 0.9549] | eligible 12876, not_recorded_valid 1653, missing_captured_floor 22 |
| 13-16 / before_20260823 | 0.052659 [0.043256, 0.061592] | 0.028018 [0.020574, 0.035082] | 0.056187 [0.047369, 0.064788] | 0.051110 [0.042604, 0.058778] | -0.005076 [-0.009902, -0.000920] | 0.5135 [0.4014, 0.6202] | eligible 3505, not_recorded_valid 3316, missing_captured_floor 12 |
| 13-16 / from_20260823 | 0.052456 [0.046195, 0.058720] | 0.028399 [0.022467, 0.034656] | 0.059870 [0.052088, 0.068693] | 0.052252 [0.046070, 0.058450] | -0.007618 [-0.011640, -0.004458] | 0.5004 [0.3849, 0.6204] | eligible 5888, not_recorded_valid 5868, missing_captured_floor 10 |
| 13-16 / pooled | 0.052530 [0.045462, 0.058414] | 0.028259 [0.022165, 0.034225] | 0.058517 [0.051487, 0.064656] | 0.051832 [0.045155, 0.057233] | -0.006684 [-0.009349, -0.004416] | 0.5052 [0.4032, 0.6024] | eligible 9393, not_recorded_valid 9184, missing_captured_floor 22 |
| 17-23 / before_20260823 | 0.033816 [0.023921, 0.044824] | 0.000584 [0.000172, 0.001294] | 0.046707 [0.036592, 0.056784] | 0.037967 [0.028914, 0.047579] | -0.008740 [-0.013951, -0.004334] | 0.2411 [0.1410, 0.3608] | not_recorded_valid 8992, eligible 2807, missing_captured_floor 14 |
| 17-23 / from_20260823 | 0.030675 [0.021411, 0.041174] | 0.000861 [0.000228, 0.002239] | 0.047684 [0.037080, 0.058711] | 0.035584 [0.026561, 0.045009] | -0.012099 [-0.018099, -0.007457] | 0.2777 [0.1997, 0.3760] | not_recorded_valid 14503, eligible 5633, missing_captured_floor 59 |
| 17-23 / pooled | 0.031829 [0.023790, 0.041520] | 0.000760 [0.000259, 0.001575] | 0.047325 [0.038992, 0.055570] | 0.036460 [0.028786, 0.044807] | -0.010865 [-0.014528, -0.007417] | 0.2643 [0.2083, 0.3278] | not_recorded_valid 23495, eligible 8440, missing_captured_floor 73 |
| all_hours / before_20260823 | 0.060927 [0.054328, 0.067830] | 0.033342 [0.028759, 0.038021] | 0.058314 [0.051737, 0.065113] | 0.055188 [0.049594, 0.060599] | -0.003126 [-0.007090, 0.000724] | 0.6750 [0.6233, 0.7275] | eligible 27388, not_recorded_valid 12872, missing_captured_floor 281 |
| all_hours / from_20260823 | 0.061063 [0.054870, 0.067872] | 0.035187 [0.031886, 0.038487] | 0.061120 [0.054664, 0.068157] | 0.056315 [0.050919, 0.061739] | -0.004805 [-0.008899, -0.001480] | 0.6718 [0.6195, 0.7269] | eligible 47253, not_recorded_valid 22564, missing_captured_floor 449 |
| all_hours / pooled | 0.061013 [0.055823, 0.067027] | 0.034509 [0.031650, 0.037428] | 0.060089 [0.054706, 0.065024] | 0.055901 [0.051351, 0.060224] | -0.004188 [-0.006653, -0.001710] | 0.6730 [0.6331, 0.7132] | eligible 74641, not_recorded_valid 35436, missing_captured_floor 730 |

### 14c. Half-development-effect planning (plug-in, not an α spend)

| Block / stratum | C1 | C2 |
| --- | --- | --- |
| 00-05 / before_20260823 | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006159; power@45 0.243) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006037; power@45 0.520) |
| 00-05 / from_20260823 | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006463; power@45 0.266) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.005995; power@45 0.532) |
| 00-05 / pooled | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006351; power@45 0.305) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006010; power@45 0.585) |
| 06-09 / before_20260823 | MARKET_CLUSTER_FLOOR_LIMITED (half 0.007729; power@45 0.345) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.007078; power@45 0.607) |
| 06-09 / from_20260823 | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006134; power@45 0.251) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006146; power@45 0.596) |
| 06-09 / pooled | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006715; power@45 0.354) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.006486; power@45 0.674) |
| 10-12 / before_20260823 | MARKET_CLUSTER_FLOOR_LIMITED (half 0.005664; power@45 0.385) | N = 58 dates (half 0.005544; end 2026-11-26) |
| 10-12 / from_20260823 | MARKET_CLUSTER_FLOOR_LIMITED (half 0.003068; power@45 0.150) | N = 95 dates (half 0.004164; end 2027-01-02) |
| 10-12 / pooled | NOT_REACHED_THROUGH_3650_DATES (half 0.004022; power@45 0.281) | N = 63 dates (half 0.004671; end 2026-12-01) |
| 13-16 / before_20260823 | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.000774; power@45 0.077) |
| 13-16 / from_20260823 | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.000102; power@45 0.032) |
| 13-16 / pooled | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.000349; power@45 0.043) |
| 17-23 / before_20260823 | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) |
| 17-23 / from_20260823 | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) |
| 17-23 / pooled | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) |
| all_hours / before_20260823 | MARKET_CLUSTER_FLOOR_LIMITED (half 0.001307; power@45 0.054) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.002870; power@45 0.365) |
| all_hours / from_20260823 | NONBENEFICIAL_DEVELOPMENT_EFFECT (half 0.000000; power@45 n/a) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.002374; power@45 0.311) |
| all_hours / pooled | MARKET_CLUSTER_FLOOR_LIMITED (half 0.000462; power@45 0.033) | MARKET_CLUSTER_FLOOR_LIMITED (half 0.002556; power@45 0.369) |
