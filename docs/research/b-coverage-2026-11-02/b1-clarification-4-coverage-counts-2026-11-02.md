# Rule B-1 Clarification 4: the §3 market-coverage counts and drop list, 2026-11-02

- **Status:** DRAFT for master's review (lane L36, written 2026-11-01). It becomes ACCEPTED only when master
  accepts it at landing. Numbered 4 by master's conflict ruling C1 (4 = R19 coverage counts; 5 = R11; 6 = the
  look chain; 7 = the S1 MG-1 entry sha). Clarification 3 is
  `docs/research/b-look-s0-s1-2026-11-01/b1-clarification-3-s0-s1-look-wrapper.md`.
- **Authority:** master ruling R19 (2026-11-01, state review D4-4; master's ruling, not an owner decision), with
  conflict rulings C1, C11, C13 and C19.
- **History only:** synthetic fixtures only. No outcome, label, price, market, 88a, panel or settlement row for
  any date was read to write this.
- **What changes:** the vehicle of B-1 §0 ruling (d) and of §3's "B market coverage" counts, the ledger they are
  logged in, and when the drop list is written. Nothing else changes: the estimand, the keep/kill rule, the 10
  markets, the dates, the 0.90 threshold, the 07-16 hours, the bound hashes, the embargo and VOIDs 1-7. No
  B-bound file is edited. This file is filed outside `docs/research/mg2-composite-binding-2026-10-25/` and does
  not edit `docs/operations/B_FORWARD_TEST_DESIGN.md`.

## 1. Why

B-1 §0 (d) says master adds a counts-only market-coverage field to the exporter, and §3 and §9 log it "in the
same ledger" (`input_receipts.jsonl`). That field is not produced: the scheduled export never passes
`--coverage-counts`. It also cannot match `b_scorer`'s VOID 6 recompute (`b_scorer.market_coverage` over
`priced_snapshots`), because it:

- counts snapshots the per-date layout rejects (a D-1 capture, bad bands, invalid served mass);
- buckets by each row's hour instead of the snapshot's local hour;
- treats `inf` as priced;
- sums per market instead of per date.

A drop list built from it could disagree with the look's recompute and fire VOID 6. The exporter, its wrapper
and its registrar stay unchanged until after B.

## 2. The rule as amended

1. **Counts vehicle (replaces §0 (d)'s exporter field).** A host counts-only module,
   `weather.calibration.b_price_coverage`, run by `scripts/ops/b_price_coverage.ps1` under the shared workload
   lease after the date's bundle is published:
   - It reads only D's `snapshots_long.csv` for the 11 markets, through the exporter's bounded reader
     (`Source(coverage_counts=False)`), and keeps only rows at or before `export_cut_utc(D)`.
   - It writes create-only `data\exports\mg2-inputs\_b_coverage\<D>.json` (`b_price_coverage/1`), then
     `<D>.SHA256SUMS` as the published marker.
   - The sidecar holds, per market and snapshot, the integers `[n_rows, n_priced]`, plus the source bytes,
     mtime and unterminated tail, the module sha, and whether its re-projection of the in-cut rows reproduces
     the bundle manifest's `snapshots_long.csv` sha256 (`match`).
   - **No price value travels.**
2. **The price predicate.** A row is priced when `capture_price(market_yes)` is not None. `capture_price(v)` is
   `v` when it is a finite float within [0, 1], else None. This is R-H's dev admission: the layout builder's
   finite check plus the unit interval. The B transfer writer derives `p_market_yes` only through
   `capture_price` and writes NaN everywhere else, so `b_scorer.priced_snapshots` (finite on every band) agrees
   with the counts by construction. The transfer writer's self-check and look-day remedy are master's separate
   T addendum.
3. **Sibling ledger (replaces "logged in the same ledger").** The workstation module
   `weather.calibration.b_drop_list` logs each sidecar in `C:\t\mg2\forward\b_coverage_receipts.jsonl`
   (`b_coverage_receipt/1`), not in `input_receipts.jsonl`.
   - `log` copies the sidecar and its SHA256SUMS from the share and checks the sha256, the schema and that the
     counts are integers.
   - The share root is a parameter (C19): the copy follows R20's address switch, and nothing hard-codes an
     address.
   - A different sha for an already-logged date is refused; master rules on it.
4. **Verdict fixed once.** As soon as D's per-date layout and logged sidecar exist, `b_drop_list verdict`
   applies `b_scorer.market_coverage`:
   - It joins every layout snapshot to its `[n_rows, n_priced]`. A snapshot is priced when
     `n_priced == n_rows`.
   - Scope: the 10 markets (no Denver), local 07-16.
   - D is dropped when its share is below 0.90. A date with no 07-16 snapshot is dropped.
   - It refuses on an unlogged sidecar, `match` false, a sidecar for another bundle, a layout snapshot the
     sidecar lacks, or `n_rows` different from the layout's band count. The band check covers every snapshot,
     Denver and every hour included.
   - The verdict row is appended once and **never recomputed**.
5. **Drop list written before MG-2 score.** At the look:
   - First, the transfer fixes the countable set and the 45-date window layout is concatenated.
   - Then, before MG-2 score, `b_drop_list materialize` writes `b_drop_list/1` create-only. It holds the logged
     verdicts of exactly the window's member dates.
   - It refuses on a member with no verdict, or a member whose layout manifest sha is not the verdict's.
   - A logged date outside the window (not promotion-countable) is left out, so the drop list stays inside the
     look date set and the shift does not fire VOID 6.
   - `b_look_wrapper look` already takes `--drop-list` and passes it unchanged to `b_scorer.look` (verified
     read-only at `d5a254b6c7e023d9b6b46b2c9777bb15f82897a1`; C13). So materialize slots in before the wrapper
     call with no wrapper edit.
   - The look-chain clarification (number 6) names the ordered pre-session steps.
6. **PT-1 (C11).** Nothing here sets or reads `book_coverage`. PT-1 is not runnable (R21), so this
   clarification makes no PT-1 provision.

## 3. Pins

- Code: `src/weather/calibration/b_price_coverage.py`, `src/weather/calibration/b_drop_list.py`,
  `scripts/ops/b_price_coverage.ps1`, and the schema family `src/weather/schema_families/b_coverage.py`.
- Tests: `tests/calibration/test_b_price_coverage.py` covers the predicate parity, the integers-only sidecar, and
  the end-to-end equality with `b_scorer`'s recompute. Its cases are nan, inf, -0.1, 1.2, empty, after-cut rows,
  a D-1 capture, bad bands, Denver, hours 6/7/16/17 and 0.90 kept.
- Tests: `tests/calibration/test_b_drop_list.py` covers log, the verdict refusals, the empty date dropped,
  materialize, and a non-promotion-countable date shifting the look set with no VOID 6.
