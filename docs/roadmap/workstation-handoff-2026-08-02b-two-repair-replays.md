# Workstation handoff — 2026-08-02b: the lock window IS clean; now go at the model

## Correcting your verdict — and why your report is what let me correct it

**The lock window is clean.** Your F-family FAIL for `2026-07-31` → `2026-08-03` is an evidence-horizon
artifact of a stale mirror, not a defect.

Checked on the production host: `2026-07-31` has **all 12 markets settled**, F markets included, at
`quality_grade=complete`, `settlement_source=daily_summary`,
`resolution_source_type=wunderground_history`. `build_family_dataset` computes live from settled
market data rather than from a cached corpus, so a date reads "missing" precisely until it settles.
`2026-08-01` was mid-day when you swept, and `08-02`/`08-03` had not happened yet. Your mirror is up
to 24 h stale, which is exactly why the failures start at the horizon and nowhere else.

You had already seen it: *"the finding begins at the mirror's current evidence horizon; it is not a
scattered recurrence among the settled July dates."* That sentence, plus conditioning the verdict on
*"if that state is unchanged at build time"*, is what made this fixable in one query instead of a
day. Reporting `NOT ASSESSABLE` rather than passing absent folders was also right — never soften that.

And the method control — reproducing all seven duplicate dates, both `too_few_replay_inputs` dates,
and all six F-family gaps from June exactly — is what made me trust the checker rather than argue
with it. Keep doing that.

**What genuinely survives, and it matters:** every locked date must be *settled* before the build,
because pooled fitting refuses preselected dates absent from the F-family corpus. The 14th locked day
is `2026-08-03`, which settles on `2026-08-04`. **So the earliest possible build start is 08-04, not
lock day.** That is now in the runbook as §7a-bis. Nobody had written it down.

## Your diagnostic fix is accepted and deliberately held

`b28efa54` is correct and I am not merging it before the lock. You declared the roll footprint
yourself, which is exactly why I can make this call cleanly: a fleet roll on the calibration path, for
a cosmetic message, for a defect that cannot fire on a real non-empty lock, is pure downside two days
out. The runbook documents the symptom, which captures its whole operational value. It merges after
the lock, in a quiet window. Nothing for you to redo.

## Mission: the two repair replays that have sat idle since 2026-06-23

The release path is now as rehearsed as it can be until the lock opens. The best remaining use of your
time is the model itself — and there are two experiments already marked
`READY_FOR_OPERATOR_REVIEW`, `counts_toward_repair_evidence: true`, that nobody has ever run.

From `data/backtest/model_market_disagreement_analysis.md`:

| Review id | Market / band | Direction | Lane | Experiment |
| --- | --- | --- | --- | --- |
| `audit-review-seattle-92631cf037` | seattle 64-65 F | market higher than model | exact-band / winner-centering | `audit_exact_band_winner_centering_replay` |
| `audit-review-seattle-ad4416de86` | seattle 66-67 F | model higher than market | warm-tail dampening | `audit_warm_tail_dampening_replay` |

Expected artifacts: `data/backtest/experiments/audit_<name>.json` (write yours under your run root,
not into `data/`).

Why these two, now: our gap is **98.88% resolution, 1.12% reliability** — information, not
calibration — and the sharpest expression of it is winner-rank top-hit trailing the market by
**0.1698** against a 0.0200 tolerance. Both lanes attack exactly that: one under-allocates on
market-favoured bands, the other over-allocates on market-rejected ones. Recalibration is provably
exhausted; this is the other kind of lever.

Requirements:

- **Replay-only.** `auto_change_allowed` is `false` on both. Do not change serving, promotion, or any
  production artifact. Propose; do not apply.
- **Leakage discipline is the whole game.** This project has been burned twice — item-224's apparent
  win was leakage, and you yourself caught a 31,092-day pool cutoff leak in your own work. State
  explicitly what each variant may see and when, and audit it before you report a number.
- **Do not mix artifacts across the `2026-07-31` `rows[-1]` boundary.** Regenerate both sides or stay
  wholly on one.
- **A null result is a real result.** If a repair does not help, say so plainly and I will retire the
  lane. I would rather retire two lanes on honest evidence than carry them for another two months. Do
  not tune until something clears — report what the first honest run says.

## Not now

MM promotion-gate relaxation, C prelock/fit/replay, cold tier, pointer creation, warm tier, hardening
branch. Disk stays parked by operator decision. Do not attempt anything gated on the real lock.

## Guardrails

Unchanged. `data/` read-only, outputs under one declared run root outside the mirror, topic branches
only, no PR, no merge, no master push, no promotion, no pointer change, no serving change, no
scheduler/capture/mirror/ACL change, never read or expose the sync credential.

**Refresh your mirror before you start** — this sweep's whole false signal came from a stale one, and
model work on stale evidence is worse than none.

## Handback

`docs/roadmap/agent-report-<date>-workstation-repair-replays.md`: per lane, the exact variant, the
leakage audit, the measured effect against both the incumbent and the market, and a plain
keep / retire recommendation. Push before you start and again at handback.
