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
- **Operational ceilings (rule, fixed now).** Before any panel bundle is read, run a score-free rehearsal of the full
  scored pipeline (every bound, policy, matched-clock trial, bootstrap and report rendering) separately on each
  calibration date 2026-09-27, 09-28 and 09-29. It records only input bytes, records, engine events, decisions plus
  spans, report bytes, runtime, and peak memory above the interpreter's pre-input baseline; no score, fill, reward or
  hurdle value is kept or shown. For each of those quantities, the scored-run ceiling is the largest of the three
  per-date values × 15 (fourteen quote dates plus settlement), rounded up to the next power of two in its natural
  unit (bytes, records, seconds); the rounding supplies up to 2× headroom. With the 4-hour runtime limit (largest power
  of two within it: 8,192 s) this means each calibration date's rehearsal must finish in at most ~546 s; with the
  memory limit (8 GiB power of two) each must peak at most ~546 MiB above the baseline. The memory ceiling is that value plus the measured baseline, which is not
  multiplied. Decisions plus spans get their own ceiling (`max_outputs`), separate from `max_events`. Host limits:
  memory at most 70% of 16 GiB, runtime at most 4 hours inside the 00:30–09:00 admitted window under the shared lease,
  and a pre-reservation refusal while system commit is at or above 70%; input and report bytes are also bounded by
  70% of 16 GiB and every count by the tooling's 2^31 representation limit. The derived ceilings are bound in the
  manifest. If any derived ceiling exceeds its host limit, the exam is reported as not executable on this host; the
  panel is never sampled or truncated to fit.
- **Look protection.** "Operational" means any refusal after the authorization verifies and before the first score,
  fill, reward or hurdle value is computed, from manifest build, verification or the scored run. Such a refusal does
  not consume the look; a refusal record names the stage at which it stopped. A run that never reaches a recorded
  refusal (host loss, process kill, enrolment not yet landed) likewise consumes nothing: the look is consumed only by the
  reservation written immediately before the first policy replay. Any refusal after the first score is
  computed, including a report-size refusal, consumes it; the report ceiling above exists to make that unlikely. A
  score-free rehearsal of the full pipeline is allowed on calibration dates only, never on panel dates.
- **Enrolment timing.** Calibration may run once the three calibration bundles exist. The manifest is built, verified
  and enrolled after the 2026-10-14 settlement bundle is sealed, on or after 2026-10-15 America/Toronto, followed by the
  single look. The look may run on any America/Toronto date from 2026-10-15 to **2026-10-31** inclusive, provided no
  attempt has been reserved; a reservation consumes the look whatever the date. The same panel, hurdles, ceilings rule,
  manifest and authorization apply on every permitted date; the authorization row expires 2026-11-01. No other change
  is permitted. Tooling that produces the universe inventory the manifest build needs is part of the exam
  tooling and must exist before 10-15.
- **Competitor-reaction diagnostic (secondary, not a hurdle).** Reported with the look: the measured decay of our
  reward share after posting, from the RE-1 session journals and matching 88a books, and the lag from
  `wu_history_high_increased` capture to the first 88a mid move on the affected band, from calibration dates only.
  The report states the replay's reward accrual assumes no competitor reaction and quotes the measured decay next to
  any reward-based result. It changes no hurdle, estimator or decision rule.
- **Measured-reaction sensitivity (reported, not a hurdle).** Every reward-based endpoint is also reported at
  **k = 0.3**, the per-session reward multiplier of the three RE-1 sessions that ran about one hour (0.27–0.32),
  from the RE-1 journals' per-minute modelled share samples; the pooled 60-minute k over all nine posting episodes
  is 0.67 (95% interval 0.28–0.81), raised by short sessions that ended before the decay (111f amendment 1, `agent-report-2026-09-111f-reaction-diagnostic-amendment-1.json`
  SHA-256 `30e68a615649430cd3f43e3b06a2efd3440c80c6259243dc9e6182bb4e67be91` at commit `ef6a0a6fcbad7a1bcafc560898bb2f13d72cecf1` (PR #143)), beside the registered k = 1 and k = 0.5. It changes no hurdle, estimator or
  decision rule.
  The report also carries, beside the unchanged status, a flag stating whether the k = 0.3 and k = 0.5 lower bounds
  are positive (strictly_through, both baselines); a REPLAY_HURDLES_MET status with a non-positive k = 0.3 lower bound
  is labelled `hurdles_met_not_positive_at_measured_k`. This label changes no status, hurdle or decision rule.

Everything else remains unchanged, including every hurdle, estimator, bootstrap setting, policy, pricing, fill and
net-screen semantic, the calibration dates and method, the panel dates, and the one-look restriction.

## Authorization

After the owner signs these exact bytes, production appends `REVOKE_MAKER_REPLAY` for `maker-replay-2026-10-15-v1` and
a new `APPROVE_MAKER_REPLAY` with ID **`maker-replay-2026-10-15-v2`** binding the raw-byte SHA-256 of the registration,
the addendum, Clarification 1 and this clarification. The authorization verifier must be extended to bind a second
clarification before that row is written.
