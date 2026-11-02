# Evening lock-in fix scoring: Clarification 1 (2026-10-31)

> **Status: DRAFT for master's review, before the read.** It binds only once master records it in DECISION_LOG with
> this file's SHA-256. It clarifies how the signed pre-registration
> [`evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md`](evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md)
> is executed after its postponement. It changes no threshold, no estimand, no market set and no window date of the
> signed text, and it is kept in its own file so that the signed file's SHA-256 (the signature) is unchanged.
> Written before any window outcome, score or market price was read; it cites only the signed text and master's
> ruling of 2026-10-31.

## 1. Why the read moved (section 5 record)

The read did not run on 2026-10-29. Reason, verbatim: "the scorer was never landed; it slipped on the night queue"
(prereg line 193). Under section 5 the read is postponed, not cancelled, to the first day after the precondition
lands, and the window is unchanged. The same reason is recorded in
[item 337](../roadmap/items/item-337-no-metar-observed-floor-gap.md).

## 2. Window

- Local target dates **2026-10-16..2026-10-27** only (prereg line 71).
- The outcome-blind extension (prereg line 76) reads countability metadata only and **may add 2026-10-28 only**.
  2026-10-29 is another read's day 0: any label-proxy read for it voids that read, so it is never transferred,
  loaded or labelled. If fewer than 9 qualifying dates exist through 10-28, the run **stops before any label is read**
  and the stop is reported to master; it does not reach for 10-29.
- Countability (prereg line 73) is decided before labels: promotion-countable from the ledger's
  `promotion_countable` field, and both replay arms present on at least 90% of the cell's 17-23 snapshots.

## 3. No market price in Stage 1

Snapshot market prices for the window are not read in Stage 1. The host runs
`weather.backtesting.lockin_anchor_replay --no-market`, which never reads the `market_yes` column, so every band's
`market_yes` is null at source. The scorer runs with `--no-market`: it refuses any row carrying a band price and
computes no market Brier. Price-like keys are dropped from every transferred row before any computation.

## 4. Stage 1: conditions 1-2, HARM, VOID and SAFETY

Computed exactly as signed (US11, 17:00-23:59 local, fixed-market date-clustered bootstrap, 2,000 draws, seed
20261016, one-sided alpha 0.025):

| Stage 1 result | Condition | Final? |
| --- | --- | --- |
| VOID | any section 6.2 validity failure, including fewer than 9 qualifying dates through 10-28 | yes |
| HARM | lower bound of the fixed-market interval > 0 | yes |
| NOT_CONFIRMED | upper bound >= 0, or fewer than 8 of 11 markets negative, and not HARM | yes |
| **CONDITIONS 1-2 MET, condition 3 pending** | upper bound < 0 and at least 8 of 11 markets negative | no: Stage 2 decides |

SAFETY (section 3.1) is counted and reported in Stage 1 whatever the result, as signed. The crossed estimate, the
beside blocks and Toronto are reported as signed. H2 (section 3.2) is computed only when Stage 1 reports
conditions 1-2 met, and it is conditional: it counts only if Stage 2 gives PASS (the fixed sequence is unchanged).

When conditions 1-2 hold, the Stage 1 report says exactly **"CONDITIONS 1-2 MET, condition 3 pending"** and nothing
stronger.

## 5. Stage 2: condition 3 (materiality)

Condition 3 needs the window's OLD-minus-market 17-23 gap. It is read only after MG-1's look receipt exists. Stage 2
applies the signed rule unchanged: PASS if the Stage 1 estimate is at most -5% of that gap, otherwise NOT_CONFIRMED.
A Stage 1 VOID, HARM or NOT_CONFIRMED is final and Stage 2 does not run. The scorer's `stage2_outcome` takes the
Stage 1 result and the gap and returns the final outcome; it refuses without a gap.

## 6. Denver

Denver stays in US11 and in the primary as signed. A **Denver-excluded sensitivity** (the same statistics on the
other 10 markets) is reported beside the primary. It decides nothing.

## 7. Reproduction stop (B2) and the order of reads

1. The host transfers the `--no-market` replay JSONL (one per replay commit) and the whole settlement-ledger rows of
   the window's slugs. Countability metadata is produced first, then the replay, then the per-date L1 check.
2. Pass 1 projects forecast fields only. A row on 10-29 or later, or outside 10-16..10-28, refuses the load.
3. Reproduction (section 6.2): per commit and per date, the share of rows whose NEW arm reproduces the recorded served
   vector within L1 1e-9. The gate is the overall share of a single commit, at least 99% of rows with a recorded
   vector. **If no single commit reaches it, the run stops before any label read** and emits the per-date match table
   with the served model versions and the served commits live at the time.
4. The ledger hash chain of every slug is verified on the whole rows; a break refuses the run.
5. The window is decided from countability metadata (section 2 above).
6. Only then are labels (`settlement_bucket`) opened, with the reproduction receipt, and Stage 1 is scored.

## 8. What this clarification does not do

- It does not change any threshold, margin, seed, market set or window date of the signed text, other than
  removing 10-29 from the extension, which master ruled on 2026-10-31.
- It authorises no read by itself: the read gate of section 5 and the signed hash still apply, and the scorer still
  requires the signed file as `--prereg`.
- It reads no 88a data and no market price in Stage 1.
