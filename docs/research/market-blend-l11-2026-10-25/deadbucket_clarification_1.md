# Clarification 1 to rule L11-deadbucket (sha256 a17ed258caaba9a9b0289fe67fbd7d28c83b053f0f33aa9a977093ea401d9663)

Written 2026-10-25, after the rule and BEFORE any stage-C row, any historical rate and any tape row exist.
It changes no stage-C definition, no threshold X, no fee, latency or size; it fixes the stage-A window and
fill source from the coordinator's description of the tapes master will stage (not yet local, not yet read).

## Stage-A inputs (as described; verified against SHA256SUMS when local)

- `order_books_summary.csv`: 11 markets x 2026-08-01..09-29 (660 folders); per REST capture the best bid/ask and
  the depth within 1% and 5% of the touch. Streamed row by row, never loaded whole. No full ladder.
- `execution_tape\trades-*.jsonl`: trade prints from 2026-08-10; none for 08-01..08-09 (no market_ws_events).
- `clob_tokens.csv` (first and last 1 MB): token -> bucket mapping only.

## Window and fills (replaces the "walk the NO asks" step of section 3)

- **Executable items (3) and (4) and the stage-A primary use 2026-08-10..09-29 only.** 08-01..08-09 get a
  book-only treatment, reported separately and never pooled into the primary.
- **Fills come from the trade prints (EF §10o taker fee).** For each dead bucket, at the first book-summary
  capture >= the entry instant (first-dead + 60 s): the limit NO price q* = the NO best ask (direct NO token, else
  1 - YES best bid), entered only if 1 - q* - 0.05 q*(1 - q*) >= 0.005. The filled shares = min(stake / q*,
  touch depth within 1% at that capture, the shares printed on the bucket in [entry, entry + 5 min] that a NO buy
  at <= q* could have taken: NO-token prints at <= q* or YES-token prints at >= 1 - q*). Fill price = q*; fee per
  share 0.05 q*(1 - q*); maker fee 0, no rebate. Sensitivity (reported): depth within 5%.
- Book-only treatment (08-01..08-09, and as a reported sensitivity on 08-10..09-29): the same without the print
  cap (filled = min(stake / q*, depth within 1%)).
- Mispricing duration: from entry to the first capture where the NO ask value 1 - q - fee(q) < 0.005 or no ask
  exists, capped at 16:59 local.
- The primary statistic is unchanged: $25 size, $/day summed over non-excluded markets, mean over the
  2026-08-10..09-29 dates present, date-clustered 95% CI (2,000 draws, seed 20260921).

## Stage C

Unchanged and still over 2026-08-01..09-29 (layout prices, NOT executable). For comparability it is also reported
on 2026-08-10..09-29.
