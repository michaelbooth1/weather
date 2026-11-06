# WS-3 early-warning pre-registration: master signature

Signed by master-agent (production host) on 2026-11-05 at 22:26:56 America/Toronto (host Get-Date), after reviewing the bytes at `claude/ws-docs-head-c13-20261106` @ `05a0c592d4ae81e928ac5cecae5e19fe9c3f3a33`.

- **Signed file:** `docs/research/ws3-early-warning-prereg-2026-11-06.md`, sha256 `1f992edfc0c6ce9451bea27487d9fe0466ff661169045ff48d9358ab34a0a687`.
- **Authority:** the owner's 2026-11-05 ~21:50 "Allow early warning" and ~22:03 "approved full plan" (DECISION_LOG). The file applies these master rulings:
  - T2's rule = master's spec + PT-1 §3.3;
  - hours 07-16;
  - KILL iff U < 0, at α 0.025 per arm;
  - venue settlement from the per-event settlement.json, never the settlements ledgers;
  - a declared edge size of 5 c per filled share, with a P(KILL) ≥ 0.5 power gate on the MG-2 arm (method rule 6 and STATE_OF_PLAY kill scopes, no override);
  - latency ≥ 30 s for this kill-only read.
- **Kill-only:** there is no PASS, it sits outside the edge trial charter's Holm family, and it supports no edge claim.
- **Module pin:** `src/weather/backtesting/t2_taker_rule.py` and its test file do not exist at signature. The workstation builds them to §2-§3 exactly, and master reviews them. Their sha256 values are then recorded in a dated module-pin note appended to this signature file, before step 2. After the pin neither file changes, and T2 reuses the same module sha.
- **Order:** no step runs before the module pin. The step 4 power gate decides whether steps 5-6 run.
- **Not read for this signature:** no outcome, price, book, label, settlement or model output for any local target date ≥ 2026-09-30. Master read only the prereg text, the code it cites and host file names.
- **Changes after signature** are dated, outcome-blind clarifications, never edits of the signed file.

## Module pin note (2026-11-06)

Written by the workstation on 2026-11-06T10:43:45-05:00 (WS Get-Date), from the master pin message at 10:4x ET on 2026-11-06. Master checked all three file shas on the host. Master's merge-tree of the tip against origin/master was clean (tree `05df0fe3`).

- **Tip:** `claude/ws3-t2-taker-rule-20261106` @ `edc11c56b2ace28ccaee5673c1f726732dea022d`.
- **Module** `src/weather/backtesting/t2_taker_rule.py`: sha256 `aaf60a435f1551d1157ccb02790939bb0a0f5e9e6047a1544cd563791f82bdf6`.
- **Schema family** `src/weather/schema_families/t2_taker.py`: sha256 `886f5335582f72013af44cc35a808e009d8dd6f4163d6bcea7a349d93d21bd81`.
- **Tests** `tests/backtesting/test_t2_taker_rule.py`: sha256 `4c10a2737fbd887545bef94c9dade27eee750568b2cbd09df3dd48c67ee6e6dc`.
- **Prereg** `docs/research/ws3-early-warning-prereg-2026-11-06.md`: sha256 `1f992edfc0c6ce9451bea27487d9fe0466ff661169045ff48d9358ab34a0a687`. It is unchanged.

### Rulings (a)-(i), accepted by master

- (a) An entry that does not fill is not an entry. The band may be tried again at a later snapshot, and the caps are not consumed.
- (b) If both sides of one band pass at one snapshot, the side with the larger net edge is taken. A tie goes to Yes.
- (c) A notional cap is never partially filled. An entry that would breach 25 per market-day or 100 per date is skipped and counted.
- (d) The fill window is t+L to t+L+120 s, with L = latency (30 to 150 s for WS-3).
- (e) A book row is unusable if book_time_utc > captured_at_utc + 15 s or any top-of-book field is non-finite. Unusable rows are counted and never selected.
- (f) The coverage denominator is the market-day's 07-16 snapshots that carry a vector for either arm. A snapshot is covered when every Yes and No token of every band in those vectors has a decision row.
- (g) Each bootstrap uses a fresh numpy default_rng(20260921) per method and per arm, with linear-interpolation percentiles. Block-3 draws ceil(n/3) non-circular blocks over the sorted countable dates and truncates to n.
- (h) The UNTESTABLE floors of 12 dates and 100 market-days apply to the shared countable set. The 30-fill floor applies per arm. A countable market-day also needs a venue winner. Master's clarification: a countable date is a local target date with ≥ 1 countable market-day.
- (i) Y counts only fills on countable market-days. Trades on non-countable days are listed in trades.csv with countable=0. Master's clarification: caps consume across ALL market-days in decision-time order, whether countable or not.

### Master review round 3 (R1-R5) and the two accepted additions

- R1: Coverage is counted before any settlement is read, before the marker.
- R2: A book row with a blank book_time_utc is counted (book_time_missing) and skipped, not refused.
- R3: A vector row is scope-checked (B's 10 markets, the window, the exclusions) before the arm filter.
- R4: Two raw labels that clean to one band, in books or vectors, make the event non-countable (label_collision).
- R5: The golden test asserts the module's own M and U from evaluate.
- Addition (1): Out-of-scope settlement files are never opened or hashed. They are counted in settlement_files_skipped_out_of_scope.
- Addition (2): The manifest gains label_collision_events and unusable_vector_bands_total.

### Exact WS-3 command line

Run from a checkout at the tip above, with PYTHONPATH set to its `src` and root:

```
python -m weather.backtesting.t2_taker_rule --vectors C:\t\ws3\inputs\vectors.csv --books-list C:\t\ws3\inputs\books.txt --settlements-list C:\t\ws3\inputs\settlements.txt --outcome-blind-pass C:\t\ws3\inputs\outcome_blind_pass.txt --window-start 2026-09-30 --window-end 2026-10-14 --arms mg2 served --exclude-slug highest-temperature-in-austin-on-october-3-2026 --latency-s 30 --out C:\t\ws3\run
```

- The books and settlement lists are built for events 09-30..10-14 only. 09-29 files are emitter inputs only.
- If unmatched_vector_bands_total, winner_unmatched_total or label_collision_events is > 0 on the dev projection, stop and report to master.
- The module lands on master later, through a night sequencer after a full suite. WS-3 and T2 run this exact sha, and it is never edited.

### Amendment 1 to the pin note (master 10:45 ET, 2026-11-06; append-only)

The exact WS-3 command line above gains one argument, and this line supersedes it:

```
python -m weather.backtesting.t2_taker_rule --vectors C:\t\ws3\inputs\vectors.csv --books-list C:\t\ws3\inputs\books.txt --settlements-list C:\t\ws3\inputs\settlements.txt --outcome-blind-pass C:\t\ws3\inputs\outcome_blind_pass.txt --window-start 2026-09-30 --window-end 2026-10-14 --arms mg2 served --exclude-slug highest-temperature-in-austin-on-october-3-2026 --latency-s 30 --projection-receipt C:\t\ws3\projection\receipt.json --out C:\t\ws3\run
```

- The pinned module already accepts `--projection-receipt`. It records the receipt's path and sha256, and copies the receipt's top-level `projected` object into `summary.json`. This is how prereg §6's "realised vs projected population and SD" is reported. The step 4 projection receipt therefore carries a top-level `projected` object.
- The dev projection uses its own `--out` folder (never `C:\t\ws3\run`) and its own window ≤ 09-29.

### Clarification 1: the parser check in the outcome-blind pass (master ruling 10:59 ET, 2026-11-06; append-only)

Written 2026-11-06T11:00:42 local, before step 5 and before any value for a local target date ≥ 2026-09-30 was read. Only the
prereg, rule.md, code, git history, and column or key **names** of the read-window inputs were used.

- **Why:** rule.md :251 and :271-272 fail the parser check when a layout does not expose the parser version, and
  `mg2_composite.outcome_blind_checks` (:1096, :1118-1122) sets `parser_pass` false when `v2_parser_version` is absent.
  Applied to inputs with no such column, every date would fail, which would make WS-3 UNTESTABLE by construction. The
  check is not waived. It is decided from provenance.
- **Branch applied: (i), the emitter re-parses the raw NBM text.** In the bound path, the MG-2 arm's v2 NBM fields come
  from `mg2_inputs.build`.
  - `bulletin_index` and `parse_bulletins` read the national NBP bulletins from `forecast_payload_cas`
    (binding-plan F5). They parse them through `_PinnedV2`, which wraps
    `guidance_extract_parser.PinnedParser`.
  - That parser declares `parser_version = 2`. `build` refuses any other version and stamps
    `v2_parser_version = 2` on every layout row.
  - `PinnedParser` runs `parse_nbp_station_tmax(..., parser_version=2)` from a detached worktree.
    `verify_pinned_worktree` requires that worktree's HEAD to be `PINNED_PARSER_COMMIT`, which is
    `2e17ce0eba891b028a968ac45895d3c203ea7dda` (2026-09-21T12:58:27-04:00, "Finalize 83b parser verification and
    accepted parity receipt").
  - Pinned files, at origin/master as of this note, last changed in `5ca7ca09a` (2026-10-25T02:12:34-04:00):
    `mg2_inputs.py` sha256 `546fe5d72a3a48115375ff8196846eaf15cc44c68ab20cfb8fa9b5a1314f4d39`, and
    `guidance_extract_parser.py` sha256 `afcbb5d262aa57eea53217aaa064d449a4b99424b0aabbdd48a65ea0aa2b0e06`.
  - **Rule for the read:** a date's parser check PASSES if its MG-2 as-of layout was built by that pinned builder with
    the pinned parser. The layout manifest's `parser.parser_version` must be 2 and its worktree must be at
    `2e17ce0eb`. The rows' `v2_parser_version` must equal 2, which `outcome_blind_checks` then confirms. A date
    whose layout was not built that way FAILS and is non-countable. Branch (ii), production capture time, does not
    apply, because the arm does not use production's parsed NBM fields.
- **Inputs gap, for step 2 (names only):** the read-window re-copy (`ws3-inputs-0929-1014`) holds per-event
  `snapshots.jsonl`, `replay_inputs.jsonl`, `features_long.csv` and `settlement.json`.
  - It holds no `snapshots_long.csv`, no `forecast_payloads.jsonl` and no `forecast_payload_cas` bulletins. Those are
    the builder's `BUILD_READS` and F5 inputs.
  - `replay_inputs.jsonl` carries a key `sources.nbm_probabilistic_tmax.data.raw_station_block`, but that is not the
    national bulletin that the builder parses.
  - Under prereg step 2 ("If the as-of emitter needs any other file, this step names it and master tops it up before
    the read"), these files are named for top-up. Without them, the layout cannot be built by the pinned builder, and
    branch (i) would fail every date.
- **Coverage, PIT and replay** apply exactly as in rule.md.
- **Dev projection (step 4) disclosure:** the dev outcome-blind pass is "vectors for both arms" (SPEC §4). It does not
  re-apply the coverage, PIT and replay checks, so its countable population may run slightly above the real read's.

### Clarification 2: NUL-torn book lines (master rulings 11:06 and 11:08 ET, 2026-11-06; append-only)

Written 2026-11-06T11:12:24 local, before step 5. The only ≥ 09-30 data opened was the book NUL scan, which read bytes and
recorded line counts and file shas only. No field value or price was read.

- **Why:** some captured `order_books_summary.csv` files hold a line with a NUL-filled field, most likely an
  unclean-shutdown preallocation. Python's `csv` refuses a field over 131072 characters, and the pinned module
  (`t2_taker_rule.py` `aaf60a43…`, unchanged) stopped the dev projection on 2026-09-03.
- **Scan:** `C:\t\ws3\scan\book_nul_scan.py` sha256 `481a71cd044d37af3cda41b1f630bd7aa0a6aac1150ea9d5e4ebf0b9c02ca757`,
  output `scan.json` `432f42ac4614ba26c88ba6391a9fd85462fe5cd40a84b2698253a5e95c9880e0`.
  - Dev 08-15..09-29: 460 files. 10 files have one NUL line each, on 09-02 and 09-03. 6 of those lines are over the
    limit. `over_limit_without_nul` = 0.
  - Read 09-30..10-14: 149 files (Austin 10-03 not opened). 0 NUL lines and 0 over-limit lines.
- **Rule:** before the module, every book in the read's `--books-list` passes through the shared filter
  `C:\t\ws3\filter\book_nul_filter.py`, sha256 `d8008f72875219011d024e8a516e49f89c2f2c1ffb5e5a58134aa4b3824ea62a`.
  - It drops a line if and only if the line contains a 0x00 byte. Nothing else is dropped, and kept lines are
    byte-exact.
  - A file with nothing dropped is used in place. A file with something dropped is written once, create-only.
  - The CLI form writes the module's books list and a per-file report with the source sha, the used sha, the dropped
    count and the dropped line numbers. That report's totals and per-file drops go into the read's receipt.
  - The dev projection adapter (`ws3_projection_v2.py`) imports the same file after checking the same sha.
- **Stops:** any other module refusal means stop and report to master. A dropped header line also stops, because the
  module then refuses.
- The pinned module, the command line (Amendment 1) and every other prereg rule are unchanged. Given the scan, the
  rule is expected to drop 0 read-window lines; the receipt records the actual count.

### Step 4 projection result (2026-11-06; append-only)

Run through `workstation_heavy.ps1 -Kind research_script` from the allowlist head `35994a052`. Script
`ws3_projection_v2.py` sha256 `2bc440dabd40716bb28561a94da56fd9d2634ba1072e4ce51b2689712db9bfba`. SPEC
`1e3ca6ed0741dfabcee2806e99d6d83b19e7886362c59330c7a5c59637dc16dd`. Pinned module `aaf60a43…` at `edc11c56b`.

- **Receipt:** `C:\t\ws3\projection\receipt.json`, sha256
  `eae74af8be008b647197abeea5bee3ae6f4fb1cd0cb4d56d5a12b675ca1f591b`. Its top-level `projected` is what the read's
  `--projection-receipt` copies.
- **Dev dates:** 43 run, 08-15..09-29 minus 08-16, 09-01 and 09-02 (no layout vectors). The first run, which stopped
  at 09-03, is kept as evidence in `inputs\` and `run\`.
- **Stop counters, summed over the 43 runs:** `unmatched_vector_bands_total` 0, `winner_unmatched_total` 0,
  `label_collision_events` 0, `unusable_vector_bands_total` 0, `no_venue_winner_total` 0, `book_time_missing` 0.
  `book_rows_unusable` is 918; the module counts these and does not refuse.
- **Book filter (`d8008f72…`):** 430 files, 7 lines dropped, all on 09-03 (atlanta L6976, austin L1432, chicago
  L1718, dallas L1432, houston L1432, miami L6756, nyc L6712).
- **as_served:** true. The captured `model_probability` (09-25..09-29) was compared with the v3layout `p_served`
  on 98,472 rows; maximum absolute difference 0.0.
- **Realised dev population:** 43 countable dates and 430 countable market-days in each arm. MG-2: 1,278 fills,
  11,638.92 filled shares. Served: 1,287 fills, 12,062.70 filled shares.

| Per arm | MG-2 | served |
| --- | --- | --- |
| M, pUSD per market-day | −0.5410 | −1.2296 |
| SD per market-day (rule 19) | 6.7261 | 5.4189 |
| κ, variance units (rule 20) | 0.8448 | 1.2473 |
| Filled shares per countable market-day | 27.067 | 28.053 |
| Y_edge = −0.05 × filled shares per market-day | −1.3534 | −1.4026 |
| At −5 c per share (the edge): P(KILL) / P(UNTESTABLE) / P(NOT_KILLED) | 0.708 / 0.000 / 0.292 | 0.743 / 0.000 / 0.257 |
| Median U at the edge | −0.3119 | −0.4266 |
| At −2.25 c per share (descriptive): P(KILL) / P(UNTESTABLE) / P(NOT_KILLED) | 0.209 / 0.000 / 0.791 | 0.307 / 0.000 / 0.693 |

- **Monte Carlo:** 1,000 draws with seed 20261106. Each draw resamples 15 dates and drops Austin in slot 3. The mean
  realised population per draw is 15.0 dates and 149.0 market-days, with about 443 fills (MG-2) and 446 (served).
  The rule 16 floors are met in every draw.
- **Gate ruling (master, 11:3x ET 2026-11-06):** the power gate PASSES (MG-2 P(KILL) at the edge is 0.708 ≥ 0.5),
  and step 5 is open under master's conditions. Those are: all 16 MG-2 bundles for 09-29..10-14 verified, with an
  unverified date non-countable and never imputed; one reviewed read-input build script; and step 6 as the exact
  Amendment 1 command, run once.
- **Descriptive dev read, not a trial result, not for the digest:** the dev net per filled share is −2.00 c for MG-2
  and −4.38 c for served. These come from dev dates that were already counted in the reuse ledger (row 120). They
  decide nothing and are not evidence for or against an edge.

### Clarification 3: receiving the MG-2 back-export bundles (master ruling (a), 11:4x ET 2026-11-06; append-only)

`mg2_inputs receive` applies B's deadline (00:00 local on D+2) before `verify_bundle`, so every WS-3 back-export
for 09-29..10-14 is late by construction. Master ruled (a): `--now` is never used and B's receiver is not changed.

- **Separate inbox and ledger:** under `C:\t\ws3\mg2in`. B's ledger `C:\t\mg2\forward\input_receipts.jsonl` is
  never written or read for WS-3.
- **Verification:** the bound `verify_bundle`, unchanged. A refused bundle is quarantined the way `receive` does it.
- **Each WS-3 receipt records:**
  - `status` "verified";
  - the real `recorded_at`;
  - `deadline_applied` false, with the reason "WS-3 back-export, not a B forward receipt";
  - the name, sha256 and time of the bundle's own `_runs` export receipt.
- **Build:** from `verified\` only, through the pinned parser at `2e17ce0eb`.
- **Emit inputs:** frozen named artifacts only, each with its path and sha256 in the step 5 SPEC. If any one is
  missing, the build stops. Nothing is substituted or rebuilt.

### Clarification 4: the D0 gate and the leakage audit (master ruling (A), 11:5x ET 2026-11-06; append-only)

The bound forward `emit` refuses `first < d0`, and the rule's `d0` is 2026-10-29. The WS-3 read window is
09-30..10-14. Master ruled (A): a WS-3 adapter may run the forward branch with only that refusal omitted, on
condition that a leakage audit passes. A failed audit closes the MG-2 arm UNTESTABLE-by-construction (B).
Option (C) was rejected.

**Audit rule:** every artifact the forward branch loads must have fit or update data ending on or before 2026-09-29,
with the date's source named. A forward state updated with any date ≥ D0 fails. A release retrained with data
≥ 09-30 fails. An end date that cannot be determined fails.

**Audit result: PASS** (code at the allowlist head `35994a052`; `verify_release` matches 15 of 15 release files).

| Artifact (loader) | sha256 | Data end | Source of the date |
| --- | --- | --- | --- |
| Rule (`read_rule`) | `e761cc4e…` | config only; `d0` 2026-10-29 | the rule block |
| Release binding (`verify_release`) | `4e4dd97d…` | hashes only; built at `a0443c2bf` (2026-10-28) | git |
| L6 coefficients part (`load_part`), file `C:\t\mg2\freeze_cap\mg2_coefficients.json` `4bc51e03…` | part `07a67425…` | 2026-09-29 | the part's `trained_through`; rule.md §L6 stack, "fitted once on every dev snapshot through 2026-09-29" |
| P3d_N state (`load_state`, forward), `C:\t\l2\forward\state\p3d_n_state.pkl` | `c6cc39f7…` | 2025-12-16 (Aug-Dec 2021-25) | the state's provenance and sidecar `f5409444…` (train_years 2021-2025, fit_kind forward, commit `73675b782`); the file bytes equal the bound sha, so the state was never updated forward |
| L6 own state (`load_l6_state`, via the nowcasts manifest), `C:\t\l3\sml6\final\l6_own_state_octdec.pkl` | `800072c7…` | 2025-12-31 | sidecar `497bdfec…` (train 2021-10-01..2025-12-31, months 10-12) |
| L6 station selection and obs (`upstream_obs_screen.load`; only the selection is used) | `a23f4cba…`, `37d97195…` | local 2026-09-29 | the obs manifest window and parquet statistics; not a fit on this path |
| MG-1 base, L6 stack predict, P3d_N `emit_rows`, `compose`, `observed_running_max` | release files; function `8cc4d8ec…` | none | code: zero-parameter or no state change |
| Nowcasts, layout and replay roots | recorded in the step 5 SPEC | inputs, not fits | built from verified bundles and captured replay; the nowcasts are served by the L6 state above |

**Adapter:** `C:\t\ws3\emit\ws3_asof_emit.py`, sha256
`dc08b0e93afbef2e091beb2e4384bf4c8a8acf8bb43abef9e4be36e8882657d2` (the final bytes, after master's review
closed three points on the reviewed draft `acc32925…`).
- It uses the bound functions only, in forward-branch order. It omits only `first < d0`; D0 must still be set.
- It asserts every audited sha before it emits.
- It writes only three files, each create-only, into a new WS-3 folder: `mg2_vectors_asof_capture.parquet`,
  its sha256 file and `mg2_asof_emit_summary.json`.
- `verify_release` is called with its own `root` parameter, set to the pinned worktree.
- The non-as-of `post_records` and `compose` still run, in `emit()`'s order, and are not written. Neither writes
  to disk.
- Its line-by-line diff against `emit()` lines 1002-1090 went to master with the audit.
