# WS-3: MG-2 early-warning kill-only read (pre-registration)

**DRAFT FOR MASTER SIGNATURE, 2026-11-06.** Written on the workstation from docs and code only. Nothing has been run,
fitted or scored, and the module below does not exist yet. No outcome, price, book, label, settlement or model output
for any local target date on or after 2026-09-30 was read to write it. Supersedes the working draft
`C:\t\ws3\WS3_PREREG_DRAFT_20261106.md` (sha256 `9e0f5c2a…0497`, kept), with master's rulings of 2026-11-06 applied.

- **Basis:** a weather kill-only taker read under the 2026-10-30 release of 09-30..10-14 (DECISION_LOG.md:292) plus the
  owner's 2026-11-05 ~21:50 "Allow early warning" (DECISION_LOG.md:325). Line numbers are on the C12 docs head
  `bf5ceca91` unless stated. It is **not** a maker-economics read: no reward, queue, rebate or maker metric is computed
  on these books, and C1/C2 stay closed (STATE_OF_PLAY.md:42).
- **Kill-only.** The read can rule MG-2 out as a T2 taker. It cannot PASS and never supports an edge claim
  (EDGE_TRIAL_CHARTER.md §3.2; MODEL_IMPROVEMENT_METHOD §5 rule 10). It sits **outside the charter's Holm family**
  (charter §3.5), because it cannot PASS; its α is not drawn from that family.

## 1. Arms, population and as-of rules

| Item | Rule |
| --- | --- |
| Arm MG-2 | The raw vector as exported by the bound MG-2 emitter on its **as-of-capture path only** (`mg2_vectors_asof_capture.parquet`; MG-2 rule.md §8 C4/C7, :360-375), at `release-binding.json` (L6 part `07a67425…`, P3d_N state `c6cc39f7…`). No input received after `captured_at_utc(s)` enters. |
| Arm served | The raw served vector of record: the snapshot's captured `model_probability` (`mg2_inputs.py`:533). |
| Markets | B's 10 (B_FORWARD_TEST_DESIGN.md:103-104). Denver and Toronto are excluded. |
| Dates | Local target dates 2026-09-30..2026-10-14; **Austin 2026-10-03 excluded** (DL:292, C7). At most 149 market-days. No local target date ≥ 10-15 (C5). |
| Decision instants | Every captured snapshot s with local hour **07-16** carrying a vector for **both** arms; t = `captured_at_utc(s)`. |
| Books | `order_books_summary.csv(.gz)` of export 2 set D (export2-submanifest §2), whose sources are the host per-event files re-copied as the 11-06 re-copy's events-0930-1014 set; top-of-book columns only: `best_ask`, `ask_size_at_best`, `ask_count`, `min_order_size`, `captured_at_utc`, `book_time_utc`. Receipt bound R = `captured_at_utc` + 15 s (COOL_SEASON_PAPER_TEST_PREREG.md:130, origin/master). |
| Decision book | Per band token and side: the latest row with R ≤ t and `captured_at_utc` ≥ t − 120 s (PT-1:144). |
| Fill book (latency ≥ 30 s) | The earliest row with t + 30 s ≤ `captured_at_utc` ≤ t + 150 s (PT-1:149). **Latency note (master 11-06):** ≥ 30 s stands for this read even if our measured end-to-end p95 is longer (charter §2.2): an assumed latency shorter than the true one favours the arm, which is the conservative direction for a kill-only read. T2, which can PASS, uses max(30 s, measured p95) with a 120 s sensitivity. |
| Settlement | **The venue's actual resolution** (charter §2.6): `polymarket_winning_band` in the per-event `data\snapshots\<slug>\settlement.json` (written by `settlement_ledger.py`:1100-1115), re-copied for B's 10 markets, events 09-29..10-14. **The settlements ledgers (`data\settlements\*\ledger.jsonl`) are never read and never copied to the workstation:** they hold B's rows ≥ 10-29, and B-1 Clarification 8's outcome-blind basis depends on nobody reading them. A market-day with no venue winner is non-countable; it is never filled from a WU or METAR label. |
| Capture-gap rule (charter §2.7) | No decision row: no decision for that token at s. No fill row: no fill. Both are counted, never imputed. A market-day is countable only if both arms have vectors and the outcome-blind checks pass, ≥ 90% of its 07-16 snapshots have a decision row for every band token (PT-1:182-184 pattern), and a venue winner exists. The counts are fixed before any price or settlement value is read. |

## 2. T2's rule (one module)

**T2's rule** is the rule below: master's spec plus PT-1 §3.3. **Module:** `src/weather/backtesting/t2_taker_rule.py`,
tests in `tests/backtesting/test_t2_taker_rule.py`. It holds pure functions (decision, fill, caps, P&L, kill statistic)
and a CLI that takes the window and arms as arguments. It imports no exchange client, SDK, credential or network
library, and an AST-scan test pins that (PT-1:363-365 pattern). **The T2 module reuses it unchanged:** T2 runs the same
sha on its dates. The sha is pinned in this file at signature and never edited.

- **Probability:** q_b = the arm's raw vector as exported. No market blend, no refit.
- **Entry (θ = 0.03; PT-1:148):** BUY Yes if q_b − a − fee(a) − 0.01 ≥ θ. BUY No if (1 − q_b) − a_No − fee(a_No) −
  0.01 ≥ θ. Here a is the decision-book `best_ask`. A band never holds both sides.
- **Fill (top of book only; PT-1:150-151):** at a′ = fill-book `best_ask` if `ask_count` > 0 and a′ ≤ a. Size is
  min(10, `ask_size_at_best`), so it never exceeds displayed depth (charter §2.3). An entry is not taken below
  `min_order_size`, and deeper levels are ignored.
- **Costs:** fee(p) = 0.05·p·(1−p) per share at a′ (PT-1:146), plus slippage 0.01 per share (PT-1:147). The fill never
  goes past the top level, so walking the depth adds nothing beyond the 1 c.
- **PT-1 caps (PT-1:152):**
  - one entry per (date, market, band, side);
  - at most 3 entries per (date, market);
  - notional at most 25 pUSD per (date, market) and 100 pUSD per local target date across all markets, in
    decision-time order;
  - each arm is capped independently.
- **Holding and P&L:** held to settlement (PT-1:153). Net P&L per entry = shares × (payout − a′ − fee(a′) − 0.01)
  (PT-1:155).

## 3. Kill criterion, units, multiplicity, minimum N

- **Unit:** the market-day. Y = net P&L in pUSD per countable market-day, and a market-day with no fill counts as 0.
  M_arm = the equal-weight mean of Y.
- **Bound:** U_arm = the one-sided upper bound at α 0.025. It is the wider (larger) of two bootstraps, both 2,000 draws
  with seed 20260921 (STATE_OF_PLAY.md:60):
  - date-clustered percentile, resampling dates with all their market-days;
  - moving block-3 over consecutive dates.
- **Outcomes, per arm:**
  - **KILL** if and only if U_arm < 0.
  - **NOT KILLED** otherwise.
  - **UNTESTABLE** if the arm has fewer than 12 countable dates, fewer than 100 countable market-days, or fewer than
    30 filled entries.
  - There is no PASS.
- **Multiplicity:** α 0.025 per arm, with no α carried across arms or into the charter family. MG-2 − served (paired
  per market-day, with its interval) is reported descriptively, with no α.
- **Rule 16 (MODEL_IMPROVEMENT_METHOD §5 :200), verbatim:** "A pre-look power projection must apply the statistic's FULL
  population rule (for mr_sweep: covered AND every placebo donor covered under all seeds), computed outcome-free on the
  real layout. Covered counts alone are not a projection. A rehearsal must report the realised population per arm, not
  only the covered count."
- **Dev projection (done and recorded before the read):**
  - It runs this module on dev dates ≤ 09-29.
  - Books come from the dev ≤ 09-29 books after the 11-06/07 host re-copy, or from the 88a books ≤ 09-29 (T1 dev hygiene allows ≤ 10-14; this read's own window 09-30..10-14 is never used for its projection)
    (`C:\archive\inputs\export2-batch1-c3\data\maker_evidence`, files dated ≤ 09-29 only; top-of-book fields only).
  - The served arm uses served vectors. The MG-2 arm uses MG-2's dev control vectors, because C4 forbids the as-of path
    on dev rows.
  - Its SD comes from the same per-market-day contrast (rule 19), with κ in variance units (rule 20).
  - It records the realised population per arm.
  - Any adapter from 88a files to top of book is a separate projection script, with its own sha recorded; the module
    does not change.
- **Edge size for this kill (declared now, master 11-06):** a mean net loss of **5 c per filled share** at this
  prereg's sizing, expressed per market-day as Y_edge = −0.05 × (projected filled shares per countable market-day).
- **Power gate (rule 6, MIM :165-166, "no screen launched below power 0.5"; STATE_OF_PLAY.md:60, "kill-only reads
  need power >= 0.5 at edge size"; both stand, no override):** the dev projection must show **P(KILL) ≥ 0.5 for the
  MG-2 arm at Y_edge on the wider bound**, with the full population rule (rule 16).
  - If it does, the read runs (both arms; the served arm's power is reported).
  - If it does not, **there is no read**: WS-3 closes **UNTESTABLE-by-design**, no 09-30..10-14 book, vector or
    settlement value is opened, and T2 freezes as in the UNTESTABLE row of §6.
  - Descriptive, deciding nothing: P(KILL) at the no-information loss, fee plus slippage of about 2.25 c per share
    (PT-1:243-244).

## 4. Steps (in order, no step skipped)

1. Master signs; module sha and this file's sha recorded; DEV_WINDOW_LEDGER row written before any computation.
2. **Pre-read presence check (names and sha256 only; no file contents):**
   - set D: the re-copy's events-0930-1014 `order_books_summary` files for the 149 market-days, verified against the
     export 2 batch2-rest SHA256SUMS staged in the re-copy's `singles\export2-receipts\` (batch2-rest receipt
     `753c1e421403a91ce6949e83792e72c846a11341fbf8a32444bdac92775ddb73`); for a file gzip-tiered since then, the
     gunzipped bytes are compared;
   - MG-2's inputs: no 09-29 bundle exists in the host's `data\exports\mg2-inputs` (it holds 09-28 and 10-28..11-04),
     so the re-copy carries per-event `snapshots.jsonl`, `replay_inputs.jsonl`, `features_long.csv` and
     `settlement.json` for B's 10 markets, events 09-29..10-14 (09-29 is D−1 for 09-30's L6 previous-day max). If the
     as-of emitter needs any other file, this step names it and master tops it up before the read;
   - the per-event `settlement.json` files (never the settlements ledgers).
3. Claimants (rule 9) cited: row 80's look receipt `C:\archive\ruled-out\row-80-rise-t3r3-replication\outputs\look\receipt.json`,
   sha256 `a91915e52cbbfebf12ab650d4ae07d95082415727c767120f52f757fd4e8feda` (atlas-rebase-rule-2026-10-31.md:66).
   The receipt is re-hashed equal before the read.
4. Dev projection run and recorded (§3). **Power gate:** if P(KILL) < 0.5 for the MG-2 arm at the declared edge size,
   stop here: WS-3 closes UNTESTABLE-by-design and steps 5-6 never run.
5. MG-2 as-of vectors emitted by the bound code; their parquet sha256 is recorded before any join to books or
   settlements.
6. One run of the module, under `workstation_heavy.ps1` if it is heavy. It writes a create-only receipt with a
   single-look marker, and a second run refuses.

## 5. Explicitly NOT read

- Any local target date ≥ 2026-10-15, including MG-1's window and B's and T2's dates.
- Austin 10-03, Denver and Toronto, and hours outside 07-16.
- MG-1 vectors and B scorer outputs.
- Any Brier score or MG-2-vs-market score on these dates.
- From the books: mids, `p_market_yes`, last trade, `buy_vwap_*`, depth bands, and the deeper levels in
  `order_books.jsonl`.
- `execution_tape`, reward files, maker_shadow, and any 88a file other than the dev-projection books ≤ 09-29.
- The settlements ledgers (`data\settlements\*\ledger.jsonl`): never read and never copied to the workstation (they
  hold B's rows ≥ 10-29; B-1 Clarification 8's outcome-blind basis depends on nobody reading them).
- `C:\t\l2\p2`, panel stores, the sealed panel and credentials.
- No per-hour, per-market or θ cut decides anything or tunes T2. Those cuts are reported as descriptive only.

## 6. Outputs and consequences

**Outputs** go to `C:\t\ws3\run\`:
- the input manifest (sha256 per file);
- the trades CSV;
- the per-market-day CSV (both arms);
- `summary.json` (M, U by both methods, counts, fills, fees, realised vs projected population and SD);
- `receipt.json`.

The workstation records its own result (rule 11).

| Result | Consequence |
| --- | --- |
| **MG-2 KILL** | T2 is **not frozen**. EXHAUSTION_REGISTER §6 row, and a copy (never a move) of this prereg, the module sha, raw outputs, receipts and logs to `C:\archive\ruled-out\ws3-mg2-early-warning-20261106\`, with INDEX rebuilt by `build_index.py` (rule 13; charter §3.7). B continues as bound. |
| **MG-2 NOT KILLED, UNTESTABLE, or UNTESTABLE-by-design (power gate)** | T2 freezes with the **same module sha**. Outputs (or, by design, the projection) are kept and reported; nothing is deleted. |
| **Served arm (any result)** | Descriptive only; triggers nothing. |

## Still unresolved

- None. Latency is settled by master's 11-06 note in §1 (≥ 30 s for this read; T2 uses max(30 s, measured p95) with a
  120 s sensitivity).
