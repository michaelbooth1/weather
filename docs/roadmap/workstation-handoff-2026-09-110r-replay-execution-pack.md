# Workstation handoff 2026-09-110r — replay execution pack and Clarification 1 (panel shift)

Written 2026-09-27 by the production agent. Owner approved on 2026-09-27 (after a Fable review verified by production):
the signed execution addendum's hazard calibration (`maker-replay-execution-addendum-2026-09-27.md` §Conservative
public-trade hazard) is degenerate by construction — window 2026-09-20..26 with a three-date minimum, but 88a capture began
2026-09-25, so every city falls back to `U_m = 1.0`, `hazard_per_minute = 1.0`, the net screen (1.0 × 0.0043 × 20 ≈ 0.086/min)
exceeds any band reward (≤ ~0.069/min), `informed_v0` never quotes and the 10-12 look fails at equality. No calibration data
has been read. The owner chose **option A**: a prospective, dated Clarification before any calibration read.

Base: `origin/codex/integration-91a-110f-20260926` (`f0119b407` or newer) merged with
`origin/codex/replay-hurdles-prereg-20260927` (`bc9fd5b13`); rebase on `origin/master` after the 09-27/28 landing.
Branch `codex/replay-execution-pack-20260927`. **Never edit the two frozen files** (their SHA-256 are bound in DECISION_LOG).

## Part 1 — Clarification 1 (docs, new file, unsigned)

`docs/research/maker-replay-clarification-1-2026-09-27.md`, prospective and dated, disclosing no prior reads:
- Calibration window **2026-09-27..2026-09-29** (three closed UTC 88a dates, three-date minimum unchanged).
- Quote panel **2026-09-30..2026-10-13** (14 closed UTC dates); settlement-only **2026-10-14**; single scored look
  **2026-10-15** America/Toronto. Everything else in the pre-registration and addendum unchanged.
- Sparse fallback: a city failing the sparse thresholds uses the **pooled all-city** Clopper-Pearson bound (same q rule
  over pooled n/x) instead of 1.0; `U_m = 1.0` remains only when the pooled inventory itself is sparse or empty.
  `hazard_per_minute = max_m U_m` over the resulting values.
- Prospective maintenance exclusion: UTC **05:00-08:00** each panel date is declared inactive for every policy (production
  quiet-window merges restart 88a then); exclusions are not zeros.
- T+2 conditions whose target date is after the settlement-only date are excluded from the quote universe.
- New authorization id `maker-replay-2026-10-15-v1`; the production agent records `REVOKE_MAKER_REPLAY` for
  `maker-replay-2026-10-12-v1` and a new `APPROVE_MAKER_REPLAY` binding protocol, addendum **and clarification** hashes
  after the owner signs.

## Part 2 — code (`src/maker_core/replay/`, fixtures only)

1. `calibrate_hazard` CLI implementing the addendum method as clarified (bounded reads of sealed bundles, exact
   Clopper-Pearson via bisection, per-city n/x/dates, pooled fallback, fallback reasons, JSON with source hashes).
2. `manifest build` binding every `ReplayConfig` field, policy/plugin/engine/scorer source hashes, sorted universe inventory,
   declared active intervals (with the maintenance exclusion), bundle/stream hashes, the calibration output and the three
   document hashes; refuses incomplete bindings. `manifest verify` against the DECISION_LOG row.
3. Verifier: add an optional `clarification_sha256` attestation field (additive; rows without it keep verifying) and support
   REVOKE superseding an earlier id.
4. Enrol the registration in `APPROVED_REGISTRATIONS` in its own commit with a test (production pins the final hash).
5. A roll-free `scripts/ops/workstation_heavy.ps1` allow-list entry for `maker_core.replay`.

## Deliverables

Include the repo-wide audits and maker-core boundary tests. Push, draft PR, report
`docs/roadmap/agent-report-2026-09-110r-replay-execution-pack.md`, verdict first, roll classification per file, exact
production commands (calibration on 2026-09-30 after the three dates close; manifest build; scoring on 2026-10-15).
