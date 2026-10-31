# Master ruling (b): post-look serial-correlation analysis of B

**Master's ruling, verbatim.** Relayed by WS coordinator from master message 2026-10-31T00:23Z. Committed by lane L8
on 2026-10-31 before any post-look code exists. This is a dated research note, not canonical guidance, and not an
owner decision. B stays as bound.

> (b) Master ruling, recorded after (a): after B's look, master runs a separate post-look analysis of B's forward d
> (lag-1 ρ plus an AR(1)-adjusted interval). If that adjusted bound is ≥ 0, a B PASS goes to the owner as "PASS,
> fragile under serial correlation". The verdict stays B's own; its next step is PT-1 on fresh dates either way. A
> FAIL or INCONCLUSIVE is unaffected, since under-coverage only makes PASS easier.

## Context relayed in the same message

- B's interval is the fixed-market, date-clustered percentile (`docs/operations/B_FORWARD_TEST_DESIGN.md` line 148).
- B's PASS is U < 0 (line 160).
- B's false-PASS rate of 0.025 (line 304) assumes independent dates.

The evidence behind the ruling is ledger rows 83-84 (`docs/research/iterate-faster-2026-10-30/b-pair-serial-rho-dev.md`
on `origin/claude/b-pair-serial-rho-20261031` @ `2eeddedfcc83104eb52998c6cd9c08c9e4a594ad`).

## Parameters

The ruling does not fix the estimator, truncation, interval form or label condition. The coordinator has sent
master proposed values for confirmation. Until master confirms them, they are PROPOSED and the post-look module is
not frozen.
