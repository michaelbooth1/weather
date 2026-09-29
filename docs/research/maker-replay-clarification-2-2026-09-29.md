# Maker replay Clarification 2 — operational executability, 2026-09-29

**Status: prospective, UNSIGNED DRAFT for owner review. Direction approved by the owner on 2026-09-29; the owner signs
these exact bytes only after reading them.** Owns only the changes below to the
[frozen registration](maker-replay-hurdles-preregistration-2026-09-27.md), the
[frozen execution addendum](maker-replay-execution-addendum-2026-09-27.md) and
[Clarification 1](maker-replay-clarification-1-2026-09-27.md). All three remain unchanged. This is not an execution
approval.

No quote-panel, settlement, wallet or replay-result data was read to write this. The first panel date (2026-09-30 UTC)
had not closed. The 2026-09-29 deep audit found, from code on the integration branch only, that the exam as frozen
cannot execute: nightly bundles carry a per-condition field the bundle reader refuses; no tool produces the
calibration-only bundles the hazard method requires; the operational ceilings were never measured against real 88a
volume; and a refusal inside scoring consumes the single look. These are structural findings, not data results.

## Changes (operational only)

- **Active intervals.** Quote-panel exclusions (Clarification 1's 05:00–08:00 UTC and any coverage exclusion) are
  supplied only by the execution manifest. Exported bundles carry no per-condition `active_intervals`; the bundle
  reader keeps its exact field set.
- **Calibration bundles.** A dedicated calibration exporter produces, for each calibration date, one directory holding
  only the descriptor, coverage and public-trade records the hazard method reads, for every city in the quote-market
  set below, from the same 88a sources and with the same hashing as panel bundles. Quote-panel bundles likewise use one
  directory per UTC date covering all cities.
- **Quote-market set (rule, fixed now).** The quote markets are exactly the cities with at least one 88a-captured band
  on any calibration date (2026-09-27, 09-28, 09-29), as listed in 88a's sealed per-date inventories. `M` is the count
  of that set. No city is added or removed by judgment.
- **Operational ceilings (rule, fixed now).** Before any panel bundle is read, run one diagnostic-only export and
  engine pass on calibration date 2026-09-27 that records only input bytes, record count, engine events, decision and
  span counts, peak memory and runtime — no score, fill, reward or hurdle value. Each ceiling for the scored run is
  that measurement × 15 (fourteen quote dates plus settlement) × 4, rounded up to the next power of two, and capped by
  the host (16 GB RAM, at most 70% commit, 45 minutes). The derived ceilings are bound in the manifest. If the host
  cap binds below the rule's value, the run is reported as not executable on this host; the panel is not sampled or
  truncated to fit.
- **Look protection.** A scored run refused for an operational reason (ceiling, input, bundle or host limit) before any
  score, fill, reward or hurdle value is computed or written does not consume the look. The attempt record states the
  stage at which it stopped. Any refusal after the first score is computed consumes it. A score-free rehearsal of the
  full pipeline is allowed on calibration dates only, never on panel dates.
- **Enrolment timing.** Calibration may run once the three calibration bundles exist. The manifest is built, verified
  and enrolled after the 2026-10-14 settlement bundle is sealed, on 2026-10-15 America/Toronto, followed by the single
  look. If an operational refusal that does not consume the look prevents the look on 10-15, the look may run on a
  later date up to **2026-10-31** with the same panel, hurdles and ceilings rule; no other change is permitted.
- **Competitor-reaction diagnostic (secondary, not a hurdle).** Reported with the look: the measured decay of our
  reward share after posting, from the RE-1 session journals and matching 88a books, and the lag from
  `wu_history_high_increased` capture to the first 88a mid move on the affected band, from calibration dates only.
  The report states the replay's reward accrual assumes no competitor reaction and quotes the measured decay next to
  any reward-based result. It changes no hurdle, estimator or decision rule.

Everything else remains unchanged, including every hurdle, estimator, bootstrap setting, policy, pricing, fill and
net-screen semantic, the calibration dates and method, the panel dates, and the one-look restriction.

## Authorization

After the owner signs these exact bytes, production appends `REVOKE_MAKER_REPLAY` for `maker-replay-2026-10-15-v1` and
a new `APPROVE_MAKER_REPLAY` with ID **`maker-replay-2026-10-15-v2`** binding the raw-byte SHA-256 of the registration,
the addendum, Clarification 1 and this clarification. The authorization verifier must be extended to bind a second
clarification before that row is written.
