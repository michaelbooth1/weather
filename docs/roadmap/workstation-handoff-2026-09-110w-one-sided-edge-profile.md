# Workstation handoff 2026-09-110w — one-sided edge maker profile (second candidate)

Written 2026-09-27 by the production agent. Owner thesis (2026-09-27): an informed maker quotes the side it believes in and
welcomes fills there. Three Fable reviews (skeptic, weather-edge evidence, implementation design; recorded in the 09-27 docs
step) found: one-sidedness concentrates informed flow rather than filtering it; the weather model trails the market in every
measured slice (114/114 cells negative), so the model is a veto, not a direction; the only near-certain directional signal is
observation decidedness (a band made impossible by the running observed maximum); one-sided reward score is `S/3` inside a
[0.10, 0.90] mid and zero outside. **Owner approved (2026-09-27):** build the profile as a SECOND candidate with its own later
exam; symmetric `informed-v0` fallback when there is no edge; include T+0; journal the owner's manual one-sided orders (110x).

Base `origin/master` after the 2026-09-27/28 landing; rebase on the replay-harness line where the engine is needed. Branch
`codex/one-sided-edge-20260928`. **Do not touch any `docs/research/maker-replay-*` file or the frozen `informed-v0` semantics.**

## Build

1. `src/maker_core/quoting/one_sided.py`: `EdgeProfile(Profile)` (extra fields live only on the subclass, so `informed-v0`
   `input_hash` bytes stay identical) and `decide_one_sided()`; name `"one-sided-edge-v0"` (hyphens, schema-literal audit).
   `policy.py` gets at most a one-line `isinstance` dispatch.
2. Rule per band per minute: all `informed-v0` safety gates; edge `e = p - m`; margin `mu = z*sigma_eff + a` (a >= 0.0043);
   plausibility cap `|e| <= K*sigma_eff`; side only from **evidence-backed signals**: (i) observation decidedness from the
   plugin clock (band dead → NO side; never YES below the running max; never NO on the open-top band once reached), (ii)
   model-probability side only when a calibration table marks the cell as skilled (none exist yet → off by default);
   `|e| < mu` or no signal → **fall back to the symmetric `informed-v0` decision**; one leg at the tightest reward-eligible
   distance; size within cash and caps; **at most one YES leg per event** (partition); pulls on `pull` hints and on
   `widen` until a fresh view; cancel on side flip; hold to settlement after a fill (`inventory_action` for exit review);
   net screen counts rewards only (no hazard-credited edge); record expected edge separately.
3. Include horizon 0 (T+0) for this profile only, with the plugin's decidedness events.
4. Additive allowlists (replay config/authorization/report/CLI, shadow session policy check); golden test proving
   `informed-v0` and `blind_re1` decisions and input hashes are byte-identical before and after.
5. Tests (fixtures only): side selection at ±mu, decidedness NO, below-floor YES veto, one YES per event, S/3 reward score
   inside [0.10, 0.90] and zero outside, fallback path, pull/side-flip cancel, hold-to-settlement.
6. Draft (unsigned, new dated file) the **second registration**: panel 2026-10-16..10-29, settlement-only 10-30, single look
   2026-10-31; comparators `informed-v0`, `blind_re1`, `no_quote`, `clock_only`; same hazard recipe, fill bounds, k,
   estimand, bootstrap, cluster minimums; plus a fill endpoint (settlement markout per filled share, lower bound > 0). Leave
   z, a and K to be fixed after the 10-15 reliability table with an explicit owner signature step.

Repo-wide audits and maker-core boundary tests in focused runs. Push, draft PR, report
`docs/roadmap/agent-report-2026-09-110w-one-sided-edge.md`, verdict first, roll classification per file.
