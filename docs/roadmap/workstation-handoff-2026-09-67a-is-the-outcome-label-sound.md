# Workstation handoff 2026-09-67a — is the OUTCOME LABEL sound?

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**No α, no candidate, no model change.** The last unaudited input to every number this campaign has.

## 1. Four missions have now cleared the model surface. One input is left.

| Mission | Question | Answer |
| --- | --- | --- |
| `-09-64a` | Does the repair inject realized-band zeros? | **No.** Repaired ≡ control, row-for-row |
| `-09-65a` | Is the panel's floor the served floor? | **In C yes, exactly.** In B, 81% differ |
| `-09-66a` | Does B's wrong floor handicap the incumbent? | **Cosmetic.** 0.5654% of B's gap |

**The instrument is sound and the gap is real.** That is a genuine result and it stands.

**Every one of those numbers is a Brier score against `settlement_high`. Nobody has audited
`settlement_high`.**

> It is **not handed to us by the venue.** 487 of your 524 panel market-days carry
> `settlement_source = daily_summary` — **our own maximum over an observation series** — and 37
> carry `snapshot_high`, a fallback. That series has recorded coverage holes.
>
> **87 of your 524 market-days (16.6%) settled from a series with a material coverage gap of 30
> minutes or more.** On `2026-06-09`, Chicago, Atlanta and San Francisco settled with material gaps
> of **45.736, 45.726 and 45.699 minutes simultaneously** — a fleet-wide stall, not a station fault.
> A gap over the hottest part of the afternoon makes the label an **under-read of the day's true
> maximum**, and a systematic under-read is indistinguishable from a **warm-biased model**.

**I am not asserting the labels are wrong.** For a settled contract the venue's number is
definitionally the outcome. But we are scoring against *our reconstruction* of it, and the
reconstruction has measurable holes. **That is worth knowing before we conclude anything else about
why we lose.**

## 2. What I have shipped you

- `docs/roadmap/settlement-provenance-for-panel-2026-09-67a.csv` — sha256
  `73501415ea8dd31db8816c3fb4b5e8db92eb0d5448b8b5f48e7c57b6c44597cd`, 44,946 bytes, **524 rows**,
  one per panel market-day: `stratum, market_id, target_date, settlement_source, settlement_high,
  max_gap_minutes, material_coverage_max_gap_minutes, daily_max_window`. Manifest and `.sha256`
  beside it. **No model output.** Verify the hash first.
- Still valid from `-09-66a`: `served-floor-for-panel-2026-09-66a.csv`, sha256 `4f9da753…`.

## 3. What to measure

Stratify the panel by label provenance and ask whether **our measured gap lives where the label is
weakest.**

| Readout | Detail |
| --- | --- |
| **Gap by coverage-gap bucket** | incumbent-minus-market on market-days with material gap `0`, `(0,30)`, `[30,∞)`. Report B and C **separately** |
| **Gap by settlement source** | `daily_summary` vs `snapshot_high` (37 market-days) |
| **Does the market's own Brier move with the bucket too?** | **This is the decisive control.** If a bad label hurts both of us equally, it is noise in the outcome, not a model defect. If it hurts only us, it is not the label |
| **Direction of our error on gapped days** | do we run **warm** there — i.e. is our distribution centred above a label that may have under-read? Use the sign, not just the magnitude |
| **Share of the C gap attributable** | if gapped market-days were at the clean-day rate, what would `G = 0.021135322` become? Label it a **diagnostic**, not a corrected result |

Intervals via your existing crossed date × market bootstrap. **These are descriptive; they attach
to no accept rule.**

## 4. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** — `-09-63a` retired it and `-09-66a` confirmed its Gate 3
  stop still fires on 3 surviving zeros. It must not be reassigned.
- **This is descriptive stratification, not a correction and not a candidate.** It licenses no
  re-scoring of any spent decision, no relabelling, and no exclusion rule.
- **Do not propose changing settlement, the daily-max window, or any collection schedule.**
  Diagnosing the capture stall is production work; the data lives here.
- **You may read C**, on the same grounds as the last three: no candidate, no fitted parameter, no
  accept rule. **Say so explicitly.**
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). **Never weaken the serving floor.**
- `DELEGATION_CONTRACT.md` §2 in full.

## 5. Both answers are worth having

- **The gap is flat across coverage buckets** → the labels are not the story, the four-mission audit
  closes completely, and "we trail the market" survives its last denominator check. **Write that
  down with the numbers; it is the more valuable outcome and I expect it.**
- **The gap concentrates on gapped or fallback-sourced days, and the market's Brier does not move
  with it** → then part of what we call model error is label error, and it tells us where to look
  next. That does **not** license excluding those days. Say so.

## 6. Environment, branch and report

Repo venv points at a removed Python 3.11; use the bundled Codex 3.12 runtime. Install nothing.

- Branch: `codex/workstation-is-the-outcome-label-sound-2026-09-67a`
- Report: `docs/roadmap/agent-report-2026-08-22-workstation-outcome-label-audit.md`
- Commit the harness and seed.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
