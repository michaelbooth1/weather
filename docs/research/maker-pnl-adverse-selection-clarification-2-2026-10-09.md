# Maker P&L Adverse-Selection Pre-registration: Clarification 2 (2026-10-09)

Status: DRAFT for the owner's signature. It is a dated clarification to
[the pre-registration](maker-pnl-adverse-selection-preregistration-2026-10-01.md),
kept as its own file so the registered text is not rewritten. It binds Part 2
once the owner signs it, and it must be signed before any Part 2 input is
transferred or read. Campaign rulings are marked as owner ruling
2026-10-09 ~15:10, relayed by master-agent. The signature below is still
required, because relayed approvals are not valid for money (DECISION_LOG
10-06).

Source: the live fill-calibration pre-registration §4. It is at
`docs/research/live-fill-calibration-preregistration-2026-10-09.md` on branch
`claude/live-fill-calibration-prereg-20261009`. Clarification A is in
`docs/research/live-fill-calibration-panel-clarifications-2026-10-09.md` on
that branch.

## Definitions

- **Campaign order:** an order carrying a live fill-calibration script order
  ID, from sessions 1–8 or session 0.
- **Excluded band-day (C′, D):**
  - C′ is any condition in the same event as a condition that carried a
    campaign order, and
  - D is a local quote date on which a campaign order rested.
- **Exclusion file:** `panel_exclusions.jsonl` in the campaign root.
  - Each line is written by the session script **before the first post** of
    its session, and its SHA-256 is recorded in the session journal.
  - The exclusion does not depend on whether the session filled.

## Clarification 2 (2026-10-__, before any Part 2 input is transferred or read; owner-signed)

*Data seen: none.* No 88a, panel or settlement row for an event or quote
date on or after 2026-09-30 has been transferred or read for this study.

*Why.* From 2026-10-15 the owner runs live post-only quotes, RE-1-faithful
at 40 shares per leg, on T+1/T+2 bands of the built-in markets (the live
fill-calibration campaign). Those quotes change displayed depth, prints and
fills on the bands they touch. A band-day carrying our quotes is therefore
no longer a passive observation of the market this study models.

*Rule.*

- Part 2 drops every excluded band-day (C′, D) listed in the campaign's
  `panel_exclusions.jsonl`. It drops them before any Part 2 outcome is read,
  and whether or not our session filled.
- The power rule (Clarification 1 §3) is unchanged, because `N_req` comes
  from the Part 1 pilot only.
  - Each date mean is taken over that date's remaining band-days.
  - A date left with no band-day is a coverage gap, never imputed.
  - The extension branch applies as already registered.
- Excluded band-days are listed and counted in the report, never scored.
- Part 1 is unaffected, because its dates precede 2026-10-15.

*Earliest session.* No campaign order rests before 2026-10-15T00:00:00Z.

- On local quote date 2026-10-15, T+1 bands (event 10-16) lie outside the
  Part 2 panel.
- T+2 bands (event 10-17) lie inside it and are excluded by this rule.
  - The 10-15 session is not restricted to T+1 (campaign ruling R4 declined,
    owner ruling 2026-10-09 ~15:10, relayed by master-agent).
  - Its T+2 band-days are excluded mechanically.
- Every later session date falls inside the panel and is excluded by this
  rule.

Owner: ______________________  Date (UTC): ____________
