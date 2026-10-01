# Maker replay Clarification 3 — reporting and next-step rule, 2026-10-01

**Status: prospective, UNSIGNED DRAFT for owner review. Direction approved by the owner on 2026-10-01; the owner signs
these exact bytes only after reading them.** Owns only the additions below to the
[frozen registration](maker-replay-hurdles-preregistration-2026-09-27.md), the
[frozen execution addendum](maker-replay-execution-addendum-2026-09-27.md),
[Clarification 1](maker-replay-clarification-1-2026-09-27.md) and
[Clarification 2](maker-replay-clarification-2-2026-09-29.md). All four remain unchanged. This is not an execution
approval.

No quote-panel, settlement, wallet, calibration or replay-result data was read to write this. It was drafted from code and
documents only: the exam integration tree at `6e7162e8` and the unsigned second-candidate draft on
`codex/one-sided-edge-20260928`. The first panel dates had not been scored. Every threshold below comes from the
registered design, not from data.

## Scope

Operational and reporting only. This clarification changes no hurdle, estimator, bootstrap setting, policy, pricing,
fill or net-screen semantic, status, reason or decision rule. It does not change the panel, the calibration, the
ceilings rule, look protection or the late-look dates fixed by Clarification 2. Every field below is reported next to
the unchanged registered decision. Tests pin that status, hurdle flags and reasons are byte-identical with and without
these fields.

## (a) Quote presence

For each fill bound, each policy (`informed-v0`, `no_quote`, `blind_re1`, `clock_only`) and each city-market cluster,
plus pooled across cities, report:

- **eligible time**: covered seconds inside declared active intervals. This is after the manifest's exclusions,
  including 05:00–08:00 UTC, coverage gaps and inactive periods. It counts every band-day row, whatever that row's
  status. Exclusions stay exclusions, never zeros.
- **quoted time**: the eligible seconds with at least one of the policy's legs resting. This is the complement of the
  scorer's pulled seconds.
- **quoted fraction**: quoted time divided by eligible time, or null when no time is eligible.

Times are in seconds; band-minutes are seconds divided by 60. `no_quote` is zero by construction. `clock_only` is
exposure-matched to `informed-v0`, so their fractions should be close. The report also gives informed-v0's quoted
fraction on the pull endpoint's common opportunity set: one minus informed pulled minutes over common opportunities.

## (b) Minimum detectable effect of the economic contrast

The registration already requires the bootstrap standard error and the descriptive 80%-power normal-approximation MDE
in the JSON. This clarification makes the MDE part of the stated decision for the four registered economic cells:
strictly_through, `k = 1`, informed-v0 minus `blind_re1` and minus `no_quote`, each under date and crossed date ×
market inference, at the registered 2,000 replicates and seed 20260926 (seed+1 crossed).

- `MDE_80 = (z_0.95 + z_0.80) × bootstrap SE ≈ 2.486 × SE`, in pUSD per complete market/UTC-day. The hurdle needs the
  lower end of a two-sided 90% interval above zero, which is a one-sided 5% test. So this is the true mean paired
  difference the panel would have detected with about 80% probability under the normal approximation.
- For each cell, report the estimate, lower bound, SE and MDE. A cell that is not distinguishable from zero must
  carry this sentence: *not distinguishable from zero; this panel had about 80% power only for a true mean paired
  difference of at least MDE pUSD per complete market/UTC-day.*
- **Binding MDE**: the largest of the four MDEs, because the conjunction needs all four cells. It is null if any cell
  lacks an MDE.

The MDE is descriptive. It is computed from the scored panel's own bootstrap SE and makes no power claim before the
panel. An UNDERPOWERED cell still reports its MDE when one exists.

## (c) Screen-suppression label

The registration spells `REPLAY_HURDLES_NOT_MET` as the status **`HURDLE_NOT_MET`**. When that is the registered status
and informed-v0's pooled strictly_through quoted fraction from (a) is **below 0.5**, the report carries the label
**`NOT_MET_SCREEN_SUPPRESSED`**. The status itself, the hurdle flags and the reasons are unchanged. The label is never
applied to REPLAY_HURDLES_MET, BLOCKED, UNDERPOWERED, UNIDENTIFIED or UNMATCHED.

**Derivation of 0.5 from the design.** On the pull endpoint's common set, let N be the opportunities, L the large moves
and P the minutes informed-v0 is pulled, so its quoted fraction is f = 1 − P/N. The registration matches the clock to
informed-v0's pulled count within one minute, and the clock's schedule uses exposure only, never moves. So the clock's
expected removed moves are L·P/N, and its expected efficiency is L/N. Informed-v0 can remove at most min(L, P) moves,
so its efficiency is at most min(L, P)/P. The expected ratio is therefore at most N / max(L, P) ≤ N/P = 1/(1 − f),
even for a policy that pulls before every large move. The frozen pull hurdle is a point ratio ≥ 2, so it is
unreachable in expectation when 1/(1 − f) < 2, that is when **f < 1 − 1/2 = 0.5**.

Below that fraction, a not-met result says the net screen held the policy out of the market. It does not say the
informed signal failed while quoting. The threshold depends only on the registered ratio 2 and the registered
exposure match.

Two limits are disclosed with the label:

- The ceiling holds in expectation. A clock count that falls short by chance can lift a realized ratio above it.
- The bound is exact on the common set, while the label uses the eligible-time fraction from (a). The two sets differ
  only by minutes without a valid five-minute endpoint. The report shows both fractions and the implied ceiling
  1/(1 − f) on the common set.

## (d) What each combination of verdicts means for the next step

Candidate 1 is informed-v0 (this exam, look from 2026-10-15). Candidate 2 is `one-sided-edge-v0` (its own
registration, look 2026-10-31). Each verdict is one of three classes:

- **MET**: REPLAY_HURDLES_MET.
- **NOT MET**: HURDLE_NOT_MET. Candidate 1's NOT MET is split by the label in (c).
- **NO VERDICT**: BLOCKED, UNDERPOWERED, UNIDENTIFIED or UNMATCHED. This also covers a candidate 2 that is never
  signed or never executed.

Standing rules for every combination:

- **No combination authorizes live trading or promotion.** A MET verdict only qualifies a candidate for the
  registration's remaining prerequisites: the T+1 fair-value reliability table, at least seven days of forward
  shadow/replay agreement, operational drills, accounting reconciliation, and then the owner's separate live decision.
- No verdict reopens, re-scores, extends or re-slices a spent panel.
- A k = 0.5, k = 0.3, at_price or clock contrast never rescues a failed primary result.
- `blind_re1` outperforming a candidate never promotes blind quoting.
- A MET candidate's forward shadow, which is paper only, may start as soon as its own verdict exists. The table below
  decides which candidate continues once both verdicts exist.

| Candidate 1 | Candidate 2 | Next step |
| --- | --- | --- |
| MET | MET | One candidate continues to forward shadow. Candidate 2 continues only if its reported candidate-minus-informed-v0 lower bound (strictly_through, k = 1, both clusters) is strictly above zero, since that contrast is the question it exists to answer. Otherwise informed-v0 continues as the simpler policy, and the one-sided layer stays research. |
| MET | NOT MET or NO VERDICT | Informed-v0 continues to forward shadow. The one-sided layer is not adopted. Candidate 2's panel is not re-run. |
| NOT MET or NO VERDICT | MET | Candidate 2 continues to forward shadow. Its shadow report separates results from one-sided legs and from the inherited symmetric informed-v0 fallback. |
| NOT MET (either label) or NO VERDICT | NOT MET or NO VERDICT | No automated maker candidate continues and no live work follows. The owner chooses between a successor registration on new dates and pausing the automated weather-maker line in favour of the forecast objective. Before any new data is read, a successor names the one element it changes and a reason that does not come from the spent panels' outcomes, and it discloses every prior read. |

The labels decide which successor reasons are admissible when neither candidate is MET:

- **Candidate 1 is `NOT_MET_SCREEN_SUPPRESSED`.** The exam did not test the informed signal in the market, because the
  conservative hazard screen kept it out. A successor may make the screen or hazard recipe its changed element,
  registered prospectively on new calibration and panel dates. It may never take a hazard from a spent panel.
- **Candidate 1 is NOT MET without the label.** Informed-v0 quoted at least half the eligible time and still missed. A
  looser screen is not an admissible successor reason; a successor needs a different signal or policy.
- **Candidate 1 is UNDERPOWERED.** This is not evidence of no edge. A successor may size a longer panel from the
  binding MDE in (b), and it discloses that the MDE was read.
- **Candidate 2.** Its own registration's reasons decide. This label applies to candidate 2 only if its signed
  registration adopts it.

A MET verdict with Clarification 2's `hurdles_met_not_positive_at_measured_k` label still continues to forward shadow.
The shadow's first question is then the realized reward share against the replay's k = 1 assumption.

## Authorization

After the owner signs these exact bytes, production does the following:

1. Record the sign-off in the DECISION_LOG.
2. Replace `CLARIFICATION_3_SHA256` in `src/maker_core/replay/authorization.py` with this file's raw-byte SHA-256,
   through a reviewed commit landed before the execution manifest is built. The manifest binds every
   `src/maker_core` source hash.
3. Append `REVOKE_MAKER_REPLAY` for the authorization then current: `maker-replay-2026-10-15-v2` if its row has been
   written, otherwise `maker-replay-2026-10-15-v1`.
4. Append a new `APPROVE_MAKER_REPLAY` with ID **`maker-replay-2026-10-15-v3`**. It binds the raw-byte SHA-256 of the
   registration, the addendum, Clarification 1, Clarification 2 and this clarification, with scoring date 2026-10-15
   and expiry no later than 2026-11-01T04:00Z.

Manifest build, verification and the scored run then pass `--clarification-3`. Until step 2, a v3 attestation cannot
verify.
