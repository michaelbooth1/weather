# Toronto NBM sprint: clarification 2, the P0 market price source and L3's placebo sha (lane L8, 2026-10-30)

Applies to `rule_toronto_nbm.md` §4 and to `clarification_toronto_mr.md`, both committed at `06d8df66c`. It
was written before any Toronto outcome, price or label read under the sprint. Only manifests, headers and
timestamp columns were inspected, and no price column was read. It is committed on top: no recorded tip
moves.

## 1. Capture-time Toronto price source (P0 is testable on dev)

L3's dev layout `C:/swarm/v3layout` has no Toronto prices. The source that L14's rule named (L14 rule sha256
`a3899507…1af6`, §Inputs; L14's results not opened) is used instead.

- **Tapes:** `data/inbox/tapes-toronto-0801-0929`.
  - SHA256SUMS sha256 `a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0` (CRLF; every
    entry verified with `tr -d '\r' | sha256sum -c`).
  - 60 event directories, 2026-08-01..09-29, none later. Each holds `order_books_summary.csv` and
    `clob_tokens.{head,tail}1MiB.csv`.
  - Each day spans 04:00Z on D to 03:59Z on D+1, which is the Toronto local day.
- **Snapshots and capture instants:**
  `data/inbox/replay-inputs-le0929/snapshots/highest-temperature-in-toronto-on-*/replay_inputs.jsonl`.
  - SHA256SUMS sha256 `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82`.
  - The `july-31-2026` directory is out of window and ignored.
  - Only snapshots whose `captured_at_local` date equals the target date are used.
- **Market vector m for snapshot s.** Take the latest book capture group (`captured_at_utc`) that is at or
  before s's `captured_at_utc` and no more than 10 minutes older. Bins, partition checks, the YES/NO
  convention and the displayed-price rule (midpoint when spread <= 0.10, else `last_trade_price`, else the
  midpoint) are exactly as in L14's rule §Inputs "Market".
- **Capture-time tightening** (this lane's addition; not in L14's rule):
  - A book row is used only if its `book_time_utc` is also at or before s's `captured_at_utc`.
  - The timestamp audit found the following:
    - 185,243 of 4,931,168 book rows have `book_time_utc` after their own group `captured_at_utc`. The
      maximum gap is 170.3 s, and 474 rows have gaps over 5 s. The book is fetched after the group's start
      stamp.
    - Receipt: `C:\t\l8tor\tape_ts_check.txt`, sha256
      `f456b312e67a8dadc4265fc6b30bdabb37674512b45bccdefbc1de1fc56d8d87`.
  - If any bin of the chosen group fails this check, the next earlier group is tried, still within the
    10-minute limit. If no group passes, s is dropped.
  - The count of dropped snapshots is reported. Prices are never read past the capture instant.
- **m in the P0 statistic and the placebo** is this vector, renormalised to 1 only where the base rule
  37cb46be requires it. The as-captured sum is kept for the placebo's sum(m) renormalisation.

## 2. L3's sha for the calibration-matched placebo

L3's rule is `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md` §5, sha256
`85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`, on `claude/mr-sweep-20261030` @
`d43d90a4a8cac0c5bd79f2da849eb98f8cac56de`. Its code (`mr_gate.py`) has not landed yet.

The construction is the same: derange the disagreement s = c − m within hour and add the recipient's m.
Implementation details differ from `clarification_toronto_mr.md` §2–3:

| Detail | clarification_toronto_mr (06d8df66c) | L3 §5 (d43d90a4a) |
| --- | --- | --- |
| Seeds | 20261030..20261049 | 20260921 + j, j = 0..19 |
| Bootstrap draws | 2,000 | 10,000 |
| Derangements per draw | mean of all 20 seeds per draw | draw b uses seed j_b = b mod 20 |
| Snapshot alignment | nearest earlier snapshot of the donor | donor snapshot min(k, n−1) |
| Band mismatch | missing band takes s = 0 | refuses |
| Derangement dates | scored dates | fit table (burn-in + scored), then restrict |

**Pending a ruling. Until then the 06d8df66c text governs.** This lane proposes adopting L3 §5 exactly,
so that one definition and one implementation (`mr_gate.py`) serve both lanes. Neither version has been
computed. P0 runs only after S2, and only after the ruling.
