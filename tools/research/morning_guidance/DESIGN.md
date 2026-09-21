# Morning guidance stage — design only, mission 2026-09-81a

Frozen pre-registration SHA-256:
`d9211fc79d2555bf90f87a42b8d02635cf0c5aeac23390bd1441e398777edc79`.
Freeze commit: `e404f7fdc56fa4e780fd2a829054751ac15b1df6`.
This page owns a proposed integration location and its contracts. Nothing here
is serving authority. The development result does not justify activation.

**Location.** A future morning stage would operate once on the complete event
band vector immediately after existing per-band `bin_probability` calls
(including calibration) and before edge, recommendation and snapshot output.
`ModelPresentationMixin.model_market_rows` currently computes display edges;
`SnapshotStore` independently calls `model_bin_probability` to write captured
rows, and replay has another scalar caller. A display-only insertion would
not change the recorded served surface. Introduce one shared vector assembly
interface for all these callers in a separately reviewed implementation.
`bin_probability` is scalar and cannot normalize a whole-vector pool. Inserting
before calibration would change the frozen candidate; inserting after edges
would make the quote and record disagree. Keep the HGB pipeline untouched.

**Weather inputs and floor.** The pure function accepts only bands, the served
vector and captured weather features. It cannot accept market prices, outcome,
tokens or orders. Eligibility and fallback are the frozen rules in the
pre-registration, limited to 06:00–09:59 local by the future caller. The 10–13
read is a diagnostic extension only. Preserve the effective WU print cutoff and
the existing approved observation rescue; never use a post-emission observation
or a pre-07:00 prior-day max. Current development conservatively uses the maximum
captured guidance floor/high-so-far/trusted current max. This is **not proof**
that each historical supporting observation was a settlement-authoritative
floor. Future authority needs the exact captured floor provenance as well.

**Mass.** Require complete, ordered, nonoverlapping bands with both infinite
tails and native-unit half-degree edges. Integrate the frozen quantile CDF,
zero impossible bands, and renormalize. C2 pools exactly 50/50 and reapplies
that mask. Missing guidance/floor or invalid CDF falls back to every captured
served value unchanged. Bad served support fails visibly rather than quietly
repairing the incumbent. Tests cover mass, fallback, translation of native-unit
coordinates, duplicate quantiles, and the stronger trusted floor.

**Train/serve and replay.** No new fitted model input, imputer column, learned
weight or calibration is introduced. One shared pure function must be used by
both serving and captured-input replay; archive pre-stage and post-stage band
vectors, rule version, eligibility/fallback reason, effective floor and cutoff.
Bind the original NBP bytes/hash, station, issue cycle, request/receipt timestamps,
target slot/date and extraction version; reject future, wrong-target or unbound
inputs. The present export cannot prove those identities, so the study does
not claim historical replay equivalence or deployability. Retaining raw
quantiles beside rejected feature fields would improve usable research coverage
without weakening the hard floor, but is a separate capture/schema decision.

**Release binding.** A future immutable release manifest must bind stage code,
candidate choice, exact 0.5 pool constant, input contract, floor rule and band
projection, including the unchanged incumbent artifact/calibration graph.
Missing or mismatched bindings disable the stage or block the release under
its owning contract. Neither this tool's existence nor its pre-registration
selects a candidate for a release. First obtain new independent evidence and
review; no config pointer, artifact or production module changes in this mission.
