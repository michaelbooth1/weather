# Toronto NBM sprint: clarification 6, the "last trade" column of the price rule (lane L8, 2026-10-30)

This is committed **before any Toronto dev outcome or label is read**, and before P0's score stage. It
amends only how clarification 5 §4 and clarification 2 §1 implement "last trade price" in the YES displayed
price. It was found on inputs alone: tapes and served vectors, with no label and no statistic.

## Finding

The displayed-price rule (the midpoint when both sides exist and spread <= 0.10, else the last trade, else
the tape midpoint) means the **YES** last trade. The tape column `last_trade_price` is not that:

- It is the CLOB last trade of the market in either token, and it is written identically on the YES and NO
  rows.
  - Example: 2026-08-02 13:19Z, bin 22 C. The YES row shows `last_trade_price` 0.999 against a YES ask of
    0.001 with no bid.
  - Example: bin 27 C shows 0.991 on both rows, where gamma gives 0.009.
- A four-day tape sample (08-02, 08-19, 09-11, 09-27) compared it with `gamma_last_trade_price`:
  - equal on 100,405 rows (within 0.005);
  - equal to the complement (1 − x) on 59,885 rows;
  - neither on 75,936 rows;
  - gamma missing on 37,476 rows.
- `gamma_last_trade_price` is identical on the YES and NO rows of every bin, in every group, so it is the
  market-level YES last trade. Every group has a YES row for every bin.
- Effect on the as-built m: with the CLOB column, the median sum of m over a snapshot was 3.03, against
  about 1 for a partition. Seven whole dates dropped because one-sided YES books (ask 0.001, no bid) had no
  CLOB trade.

## Amendment

- **"Last trade" = `gamma_last_trade_price`**, read as the YES price on either row. It is captured with the
  tape group, so it is available at the group's `captured_at`.
- Everything else in clarification 5 §4 stands unchanged:
  - the YES midpoint when both sides exist and spread <= 0.10;
  - else the gamma last trade;
  - else the tape midpoint;
  - the book_time <= t_c group rule and 10-minute fallback;
  - the partition check;
  - no renormalisation.
- A NO-row fallback is never reached, because every bin has a YES row. If it were reached, the midpoint
  branch uses 1 − the NO midpoint, and the gamma branch uses gamma as is.
- **Superseded by 6b below:** this section first left out L14 clarification 1's convention (a missing CLOB side at its bound).
- **Not changed:** this does not alter the run-once rule. P0's score stage had not run when this was found.

## Amendment 6b: a one-sided book (still before any outcome read)

**Why it was needed:**
- After the gamma fix, m was a partition again: the median sum over a snapshot was 1.044, with the 1st-99th
  percentiles at 0.84-1.54.
- But 33 of 60 dates still had no price for some bin for the whole day. These are dead tail bins with a
  YES ask of 0.001, no bid, no gamma trade and no tape midpoint. Example: 2026-09-20, bins 12 C or below
  to 15 C, on all 3,741 groups.
- Dropping those dates would keep only days without a never-traded tail, which selects the population on
  the shape of the market.

**Amendment:**
- A missing CLOB side counts as its bound (bid 0, ask 1) when the spread and the midpoint are computed, as
  in L14 clarification 1's convention.
- Example: YES ask 0.001 with no bid gives spread 0.001 and midpoint 0.0005.
- If both sides are missing, the spread is 1. The price then falls to the gamma last trade, then the tape
  midpoint; otherwise the snapshot drops.
- Nothing else changes.
