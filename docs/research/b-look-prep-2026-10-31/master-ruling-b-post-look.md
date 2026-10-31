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

## Parameters (master's final ruling, verbatim)

**Master's parameters, verbatim, 10-31.** Relayed by the WS coordinator. They replace the coordinator's earlier
proposal (which used 1.96 and a ρ floor of 0). "Your version" below refers to that coordinator proposal.

> 1. ρ: sample lag-1 autocorrelation in date order, pairing only consecutive calendar dates (agreed), computed on the per-date LINEARISED residual, not the raw date mean. Because B is a mean over equal cells and dates can have unequal cell counts, use e_t = (S_t − Δ·n_t)/n̄, where:
> - S_t = the sum of cell differences on date t;
> - n_t = that date's cell count;
> - n̄ = the mean cell count;
> - Δ = B's own printed point estimate.
>
> This reduces to your version when every date has equal cells. VAR(1) is descriptive only (agreed).
> 2. CHANGE: ρ_used = min(0.9, max(ρ̂, 0.22)). The floor is the dev-measured B-shaped ρ (row 83, 0.219), not 0. A 45-date ρ̂ is biased low (T+1's null sim showed it), and T+1 uses the same floor-at-plan logic.
> 3. CHANGE: U_adj = Δ + t(0.975, n−1) · SD(e)/√n · √VIF, where:
> - VIF = max(1, (1+ρ_used)/(1−ρ_used), block-3 ratio²), with the block-3 ratio computed on e_t and re-centred (row 84's fix);
> - the centre is B's printed Δ;
> - t replaces 1.96 (one-sided 0.025, small-n).
> 4. Agreed, plus one label:
> - "PASS, fragile under serial correlation" iff B PASS AND U_adj ≥ 0;
> - "NOT-WORSE, fragile" iff B's INCONCLUSIVE carries NOT-WORSE AND U_adj ≥ +0.0027;
> - FAIL and other INCONCLUSIVE pass through untouched;
> - B's verdict itself is never altered.
>
> Tests: synthetic iid, AR(1) at 0.22 and 0.5, the row 84 VAR(1) case, and unequal cells per date.

B's NOT-WORSE label is defined at `docs/operations/B_FORWARD_TEST_DESIGN.md` line 162: INCONCLUSIVE "labelled
**NOT-WORSE** when U < +0.0027 (owner Q4)". In `src/weather/calibration/b_scorer.py` (origin/master
`1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`), `decide()` emits it as `verdict == "INCONCLUSIVE"` with
`label == "NOT-WORSE"`, and `MARGIN = 0.0027`.

## Freeze status

The post-look module is NOT yet frozen. Its sha is pinned here only after the coordinator's new-module check and the
queued test run.
