# Live Fill-Calibration Panel Clarifications (DRAFT texts for owner signature)

Status: DRAFT, 2026-10-09. Not signed. This file carries the dated
clarification texts that must be signed **before any panel read**. Once
signed, each text is appended to its target document; for the gate spec it
goes into a new dated file. The texts exclude every band-day that carries
live fill-calibration orders. They grant no run, live, merge or handout
authority.

Owns: the wording of the two clarifications the live fill-calibration
campaign needs from overlapping registrations.

Read when: signing or applying them, or when building a panel selector
whose dates overlap 2026-10-15..2026-11-13.

Update when: the owner amends a text before signature. After signature, the
target documents own the texts.

Campaign source:
[live fill-calibration pre-registration](live-fill-calibration-preregistration-2026-10-09.md)
§4 (dates rule and exclusion). Shared definitions, used by both texts:

- **Campaign order:** an order carrying a live fill-calibration script order
  ID, from sessions 1–8 or session 0.
- **Excluded band-day (C′, D):**
  - C′ is any condition in the same event as a condition that carried a
    campaign order, and
  - D is a local quote date on which a campaign order rested.
- **Exclusion file:** `panel_exclusions.jsonl` in the campaign root. Each
  line is written by the session script **before the first post** of its
  session, and its SHA-256 is recorded in the session journal. Panel
  selectors drop excluded rows before any outcome is read. The exclusion does
  not depend on whether the session filled.
- **Earliest-session rule:** no campaign order rests before
  2026-10-15T00:00:00Z. The earliest session is the owner's local afternoon
  of 2026-10-15, for example 13:00–19:00 ET = 17:00–23:00Z, with a hard stop
  at 23:50Z.

---

## A. Clarification 2 to the maker P&L adverse-selection pre-registration

Target: `docs/research/maker-pnl-adverse-selection-preregistration-2026-10-01.md`.
It is on `codex/maker-pnl-adverse-selection-20261001` @ `67e44273b` and is
not on master. The text is to be appended after Clarification 1.

> **Clarification 2 (2026-10-__, before any Part 2 input is transferred or
> read; owner-signed).**
>
> *Data seen: none.* No 88a, panel or settlement row for an event or quote
> date on or after 2026-09-30 has been transferred or read for this study.
>
> *Why.* From 2026-10-15 the owner runs live post-only quotes, RE-1-faithful
> at 40 shares per leg, on T+1/T+2 bands of the built-in markets (the live
> fill-calibration campaign). Those quotes change displayed depth, prints and
> fills on the bands they touch. A band-day carrying our quotes is therefore
> no longer a passive observation of the market this study models.
>
> *Rule.*
> - Part 2 drops every excluded band-day (C′, D) listed in the campaign's
>   `panel_exclusions.jsonl`, under the definition in the source file. It
>   drops them before any Part 2 outcome is read, and whether or not our
>   session filled.
> - The power rule (Clarification 1 §3) is unchanged, because `N_req`
>   comes from the Part 1 pilot only. Each date mean is taken over that
>   date's remaining band-days. A date left with no band-day is a coverage
>   gap, never imputed. The extension branch applies as already registered.
> - Excluded band-days are listed and counted in the report, never scored.
> - Part 1 is unaffected, because its dates precede 2026-10-15.
>
> *Earliest session.* No campaign order rests before 2026-10-15T00:00:00Z.
>
> - On local quote date 2026-10-15, T+1 bands (event 10-16) lie outside the
>   Part 2 panel; T+2 bands (event 10-17) lie inside it and are excluded by
>   this rule. If the owner restricts that session to T+1 only (campaign
>   ruling R4), no 10-15 band-day is removed.
> - Every later session date falls inside the panel and is excluded by this
>   rule.
>
> Owner: ______________________  Date (UTC): ____________

---

## B. Clarification to the maker replay v2 registration and shadow gate spec

Targets:

- the v2 registration draft `docs/research/maker-replay-v2-registration-DRAFT.md`
  on held head `codex/maker-replay-v2-build-20261003`, which agents may not
  push to;
- the gate spec as a new dated file, per the v3.4 "add a new dated file"
  rule. The suggested name is
  `docs/roadmap/maker-replay-v2-shadow-gate-spec-clarification-live-fill-calibration-2026-10-__.md`.

> **Clarification (2026-10-__, before any v2 panel, export or shadow-parity
> outcome is read; owner-signed).**
>
> *Data seen: none.* No v2 quote-panel, settlement-only, export or shadow
> row dated 2026-09-30 or later has been read for this clarification.
>
> *v2 replay panel: no change.*
> - The quote panel is UTC 2026-09-30..10-13. UTC 10-14 and 10-15 are
>   settlement-only, with no active intervals and no date clusters (change
>   C9).
> - No campaign order rests before 2026-10-15T00:00:00Z, so no v2 quote
>   interval can carry one.
> - Campaign quotes on UTC 10-15 cannot alter WU settlement facts, and no
>   markout horizon of a 10-13 interval reaches 10-15.
> - The export gate [2026-09-30, 2026-10-16) is unchanged.
>
> *Shadow gate and later panels: exclusion.*
> - Any shadow-gate outcome panel (fill, markout or P&L) dated 2026-10-15 or
>   later drops every excluded band-day (C′, D) in the campaign's
>   `panel_exclusions.jsonl`. The same applies to any later exam that reuses
>   these dates, such as a deferred candidate-2 exam with panel 10-16..10-29.
>   Rows are dropped before any outcome is read, and are listed and counted.
> - Parity on identical tapes (shadow versus replay on the same captured
>   input) is not an outcome comparison against the market. The owner rules
>   one of:
>   - ☐ (i) parity days still count in full, and only outcome panels
>     exclude; or
>   - ☐ (ii) parity is computed over non-excluded conditions only.
>
>   The default if unmarked is (i).
> - Shadow fills on excluded conditions are reported in a separate table and
>   never pooled.
>
> *First-live cap (OD11).* The campaign quotes one band per session at 40
> shares. Whether that satisfies the pre-decided first-live cap is campaign
> ruling R7. This clarification does not decide OD11.
>
> *Earliest session.* No campaign order rests before 2026-10-15T00:00:00Z.
> The earliest session is local afternoon 2026-10-15 (17:00–23:00Z for ET,
> hard stop 23:50Z).
>
> Owner: ______________________  Date (UTC): ____________
