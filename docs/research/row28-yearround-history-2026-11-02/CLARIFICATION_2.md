# Row 28 — Clarification 2 (2026-11-03, before any control runs)

- **Written:** 2026-11-03T03:46 EST (WS Get-Date), by lane L59, before any row-28 stage or test has run.
- **What it governs:** how the frozen prereg (`prereg_row28.md` sha256 `cb6d4e8d…`, see `FREEZE_RECORD.md`) is
  executed, read together with `CLARIFICATION_1.md`. Neither the prereg nor Clarification 1 is edited. Where this file
  supersedes a line of Clarification 1, it says so.
- **Source:** master's sealed-window rulings 1–2 and master's rulings on the v2 delta review (N1, N2, N5 and the
  accepted fixes N3, N4, N6–N8, LN1), all relayed by the coordinator on 2026-11-03. Quoted text is the relay's wording.
- **Code:** runner `scripts/row28_run_v3.py` and launcher `run_row28_guarded_v3.ps1` (copy in `scripts/`). Each
  ruling is one marked `RULING_*` constant in the runner. The sentinel test is `scripts/test_row28_s7_sentinel_v1.py`.

## 1. Ruling 1 — §7 and the 2026-05 WU hourly file: option (a), skip undecoded

> OPTION (a), skip_undecoded as built. Option (b) is refused because V5.0 starts 2026-05-06.

Conditions, quoted, and how the runner meets them (`RULING_S7_SEALED_LINES = "skip_undecoded"`,
`RULING_C2_S7_RAW_PREFIX = "rb_prefix_before_decode"`):

| Condition | Implementation |
| --- | --- |
| "The date test runs on the RAW line prefix, BEFORE any field split or decode." | The month file is opened `"rb"`. Each raw line is matched against one fixed byte pattern anchored at the line start. No split, decode or JSON parse happens first. |
| "A post-05-26 line is skipped, and nothing from it is parsed, retained or logged except one count." | A line whose prefix date is after 2026-05-26 adds one to `sealed_lines_skipped_undecoded` and is dropped. Nothing else from it is kept, printed or written. |
| "ADD a tiny synthetic test … It runs BEFORE controls." | `scripts/test_row28_s7_sentinel_v1.py` (§6 below). |

**The prefix shape (N3).** It is taken from the WU hourly writer's code, not from data:

- `wu_history.py` line 442 writes every line as `json.dumps(row, sort_keys=True) + "\n"`.
- `row` is `normalize_observation`'s dict (`wu_history.py` 763–812; the dict is at 780–812). Rows without `local_date`
  are dropped before writing (410–413).
- Sorted, the keys before `local_date` are exactly `clouds`, `condition`, `dewpoint_c`, `dewpoint_native`,
  `heat_index_c`, `heat_index_native`, `humidity` and `icon`. `local_time` follows `local_date` directly.
- `json.dumps` uses the `", "` and `": "` separators and `ensure_ascii`, so the shape is fixed: `{` then those eight
  keys, each with one JSON scalar, then `"local_date": "YYYY-MM-DD", "local_time": "HH:MM", `.
- A line without this shape **HALTs** (stage `integrity`, before any label join). The HALT message names the file,
  never the line.
- "Prefix" therefore means the raw bytes from the line start through `local_time`. Those bytes include the dewpoint,
  heat-index and humidity values, because the writer puts them first. The pattern matches over them without
  decoding them. For a sealed line, nothing from the match except the date comparison is used, and the match is
  discarded at once.

## 2. Ruling 2 — `daily_summary.csv` read whole: a disclosure for the bound builder only

> ACCEPTED as a disclosure for the bound-builder path only. The runner's OWN reads (the stage-3 completeness check
> and D's d) must filter by date at load, before any value column is touched.

**The runner's own reads** (`RULING_C2_DAILY_PREFIX = "raw_line_prefix_filter"`, N4):

- The file is read in binary, line by line. The header line gives the `local_date` position. The writer is
  `wu_history.py` `write_daily_summary` (450–486, `csv.DictWriter`), where `local_date` is the second field.
- Each data line's date is tested on its raw prefix (that many unquoted fields, then `YYYY-MM-DD,`) **before any
  split or decode**. A line dated after 2025-12-31 is skipped and only counted. A line without the shape HALTs.
- Only kept lines are decoded and csv-split.
- **Hash (N4(b)).** The integrity report no longer hashes the whole file, because its bytes include sealed rows.
  `wu_daily_kept_lines` records the sha256 over the header and the kept (≤ 2025-12-31) raw lines as read, plus the
  kept and skipped counts.

**The bound-builder path, disclosed.** These load whole files; any 2026 rows stay resident in memory but are never
looked up, because every lookup is keyed by a training or deciding date (≤ 2025-12-31):

- `model_climatology.py` 116 (`daily_summary.csv`, via the bound `extract_market`);
- `marine_water_contrast.load_feature_index` (`marine_water_contrast.py` 443–466) — N4 extension;
- `reanalysis_synoptic.load_reanalysis_synoptic_features` (`reanalysis_synoptic.py` 1176–1194) — N4 extension.

**The output guard** (`RULING_C2_OUTPUT_GUARD = "halt_pre_score"`):

> ADD an output guard at every stage end: scan every output and every log for date strings >= 2026-05-27, and HALT on
> any hit. The only 2026 dates allowed in outputs are §7's own 2026 rows (<= 05-26, inputs only).

- **What is matched.** ISO-extended dates `YYYY-MM-DD`, digit-bounded. A hit is any date on or after **2026-01-01**
  that is not allowlisted. This is stricter than "≥ 2026-05-27": it also enforces "the only 2026 dates allowed are
  §7's". Hits are counted in two classes, on or after 2026-05-27 and earlier in 2026. The matched text is never
  written anywhere.
- **Allowlist (outputs only).**
  - The model's centre labels: the exact strings in `pooled_residual_model`'s `*CENTRES` tuples, plus `2026-12-24`.
    These are calendar positions written with a nominal year 2026, not data dates.
  - §7's own constants: `2026-01-01`, `2026-05-05` and `2026-05-26`. §7 writes aggregates and counts only, never
    per-date rows.
  - Disclosure: an allowlisted label would mask a real data date with the same string. Every frame's target dates are
    separately asserted ≤ 2025 by the stage code.
- **Masked token.** The prereg folder name `row28-yearround-history-2026-11-02` is removed, as an exact token, before
  matching (logs included). It is a path, never data.
- **Run stamps.** Run stamps are real local times in ISO 8601 **basic** format (`20261103T034655.…-0500`), so they
  are not date strings. The same holds for the launcher's receipt stamps.
- **Where it runs.**
  1. **Before each write.** The runner's Writer scans every output (bytes, plus a structural walk of pickled objects:
     DataFrames, datetime64 columns, nested containers) before writing it. Before any score exists, a hit HALTs and
     nothing is written.
  2. **At stage end.** Every new or changed file under `C:\t\L59\row28\run` is scanned, including the bound builder's
     record files, decompressed and unpickled. A `.gz` that cannot be decompressed, or a pickle that cannot be loaded,
     counts as a hit. Every other file is byte-scanned (the stages write only JSON, JSONL, CSV and `.pkl.gz`).
  3. **The report.** It is walked before it is written. A top-level value that holds a hit is replaced by
     `[withheld by output guard]` and the stage HALTs.
  4. **Logs.** The runner wraps stdout and stderr from its first byte. A write holding any date ≥ 2026-01-01 (no
     allowlist) is withheld and counted. After the child exits, launcher v3 re-scans `walker.stdout` and
     `walker.stderr`. It also scans the receipt text before writing it.
- **Junction manifests (N6).** Each manifest row is `[subdirectory, sha256(relative path), size, mtime_ns]`, so no
  sealed-dated path name appears in any output. No exemption from the guard is needed.
- **After a score exists (pending master).** This is `RULING_GUARD_POST_SCORE = "withhold_and_flag"`. N1 forbids a
  HALT once a look or final row exists. In stages look and score, a guard hit after scoring therefore withholds the
  offending output (it is not written) and is recorded as a FLAG for master, not a HALT.

## 3. Definition — the §7 WU observation

> WU obs at 07 local = last hourly obs at or before 07:00 local.

The reader takes, for each date, the line with the latest `local_time` ≤ `07:00` (the writer's `%H:%M` local time on
the writer's `local_date`), and uses its `temp_native` (°F).

## 4. Rulings on the v2 delta review

| Item | Ruling (quoted, abridged) | Constant / implementation |
| --- | --- | --- |
| N1 | "ADOPT. No HALT may fire once a look or final row exists (m8)." | `RULING_N1_NO_HALT_AFTER_SCORE = True`, `RULING_N1_STAGE_END_MANIFEST = "flag_classified"` |
| N2 | "ADOPT, per the frozen §5.2. A drop within the caps restates n." | `RULING_N2_N = "integrity_restated"` |
| N5 | "ACKNOWLEDGED." Operative meaning recorded verbatim below. | `RULING_R11_POOL_NO_NBM = "fill_from_normal"` |

**N1 — what is checked, and when.**

- **Stage start, as HALTs.** The before-manifest and the chain check (unchanged since the previous stage) run at the
  start of every stage.
- **Score.** The n check now runs at the START of score, before `score_folds`. It requires the kept rows to equal the
  integrity-committed date list and the restated n.
- **Look and score, pre-score checks.** Every kept (fold, hour) row set must have exactly its built rows
  (`precheck_folds`). Both stages run this before any fit.
- **After scoring, FLAGs only.** Once scoring is done, every check (date set, folds, keys, realised n per arm) is a
  FLAG in `post_score_flags`. Any exception raised after scoring is reported as ERROR, never as HALT.
- **Stage-end manifest diff in look and score.** It is a FLAG. The runner records `manifest_changed=true`, the diff
  count and the hashed keys. It classifies each differing entry per subdirectory as `added`, `removed`,
  `size_changed` or `mtime_only`. It also records which subdirectories the stage read: a declared set per stage
  (`STAGE_READS`) plus the set `guard_read` observed.
- **Master's rule, pre-stated:**
  - mtime-only changes: noted, and the result stands;
  - a size change, or a file added or removed, in a subdirectory that stage actually read: the arm results are
    labelled **INPUT-CHANGED**, and master rules before any verdict is recorded.
- **Earlier stages.** In controls, build, integrity and labels, any stage-end diff still HALTs (no score exists).

**N2 — restated n.**

- **Integrity, before any score.** Drops within the §5.2 caps restate n. The integrity report recomputes, by the
  frozen formulas only (`restate_power`), §6.3's MDE80 / power / futility table and §8.4's thresholds at the restated
  n and look n. It then commits the kept date list and n.
- **Self-check.** The same formulas at n = 660 / 390 must reproduce the frozen §6.3 table, or the stage HALTs.
- **Superseded.** The hard 660 / 390 equality assert is removed. It is replaced by "kept set == the
  integrity-committed list" in look and score.
- **The look set** is defined by FOLDS 2021–23: the committed kept dates in those folds. Drops inside those folds
  restate the look n the same way.
- **This supersedes** Clarification 1 §3 F1's quoted condition "the look stage asserts that its scored set is
  EXACTLY the first 390 deciding dates". Whether the first 390 equal the look folds is now reported descriptively.
- **Caps.** A drop beyond a cap still HALTs at integrity.

**N5 — operative meaning of R11, recorded verbatim:**

> "A pool row with no posted NBM has no PIT forecast_high, so fill-from-forecast cannot apply. The bound model's
> existing NaN path (prm _anchors 476-477) anchors it on the in-fold training mean y for (station, centre), then
> market mean, then global mean. That is fill-from-normal, training rows only, unchanged bound code, the same path
> market rows with NaN forecast_high take in every arm."

- It counts toward arm C's imputation cap.
- The integrity report gives `fill_from_normal_by_calendar_month`: per calendar month, the count of pool rows and of
  market training rows (hours 13–16) whose fh is NaN.

**N7 — rewording of Clarification 1 §4 ("R6, stage `labels`").** Instead of "nothing HALTs there", read:
"consistency HALTs only; cannot fire unless inputs changed (sha-checked) or a code bug".

**N8 — statements on §7, as computed:**

- The pooled SMD pools the raw per-market values (NBP07 mean − WU obs) across markets. Between-market spread
  therefore counts as within-group variance.
- The 07-local observation has no staleness bound. The last observation at or before 07:00 is used however early it
  is.

**LN1 (launcher v3).** On the success path, the Job is `TerminateAndWait(30000)`-ed before `output.Complete(2000)`.

## 5. Other pre-run notes

- **Config.** `stage1_controls_v2.json` (sha256 `66e4b46e…`) has no runner-version key and is reused unchanged for
  runner v3.
- **Launcher v3** is v2 plus LN1, the log guard (G1) and the basic-format stamps with a guarded receipt (G2), and
  nothing else.
- **Superseded, never run:** runner v2 (`0a74bb3d…`) and launcher v2 (`8bfea248…`) stay in the branch as review
  history.

## 6. The sentinel test (gate before controls)

`scripts/test_row28_s7_sentinel_v1.py` is calendar/synthetic only and reads no real data. It runs runner v3's own
functions, after a sha256 pin check.

1. **Fake month file.** It builds a fake 2026-05 hourly file with six lines a day for 05-01..05-31. The lines are made
   by the writer's own `normalize_observation` and dumped with `sort_keys=True`, as at `wu_history.py` 442.
   - The 05-27..05-31 lines carry the sentinel 999.9 in every temperature, dewpoint, heat-index, wind-chill and
     humidity field, including fields before `local_date`.
   - Asserts:
     - the skip count is exactly 30;
     - the 07-local values for 05-06..05-26 are exact;
     - the sentinel and the sealed date strings appear in no output (written through the guarded Writer and then
       file-scanned), no captured stdout/stderr and no log record.
2. **Prefix-shape HALT.** A line without the writer's prefix shape HALTs, and the message carries no line content.
3. **Daily prefix filter.** The daily filter skips and counts rows after 2025 (sentinel values), and hashes only the
   header and kept lines. A line without the shape HALTs.
4. **Output guard.**
   - It counts without echoing; the centre-label and §7 allowlists and the folder-name mask work.
   - Pickled datetime64 columns are caught.
   - A pre-score Writer hit HALTs with nothing written; a post-score hit is withheld.
   - Log writes with any 2026 date are withheld.

**Route:** `scripts\ops\workstation_heavy.ps1 -Kind pytest -Queue` (the WS's standard pytest route; it needs no new
exception), with an explicit `--basetemp` that is deleted afterwards. It runs only on the coordinator's go.
