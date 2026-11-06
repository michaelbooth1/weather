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
