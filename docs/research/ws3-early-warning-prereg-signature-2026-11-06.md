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
