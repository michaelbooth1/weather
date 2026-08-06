# Workstation handoff 2026-09-30a — does the cool bias track seasonal distance from training?

Written 2026-08-06 by the production agent. Read on `origin/master` and execute.

## 1. Goal

**Decide whether the base model's cool bias grows with seasonal distance from its training
window** — because that single fact determines whether the first retrain is the lever that
closes the market gap, or an expensive move in the wrong direction.

This is a **measurement mission**. Fit nothing, repair nothing, collect nothing.

## 2. Why this, and why now

We believe the following chain. Every link except the last is established; the last is
**inference and has never been traced**, and it is load-bearing for the whole retrain
programme:

```
centre displacement = 74.97% of oracle excess loss   (width = 10.94%)
   ↑ too-cool HGB puts mass below the floor; truncation yanks centre warm
   ↑ the base HGB is itself cool — root cause recorded as "a stale/cool June prior"
   ↑ every served HGB artifact was fitted 2026-06-10 .. 06-13
   ↑ the forecast archive holds ONLY May 10 – Jun 30, in every year
   ↑ ... therefore the model is cool because it never saw late summer   ← UNTRACED
```

If that last arrow holds, extending the season window (~60 free-tier calls) and retraining is
the highest-value action available. If it does not — if coolness is flat across the season —
then the June prior is not the mechanism, the retrain is a much weaker bet, and we need a new
theory before spending the collection.

**Do not assume the arrow. Measuring it is the mission.**

## 3. Start from this — do not re-derive it

Established. Cite `ESTABLISHED_FINDINGS.md`; do not re-measure.

| Fact | Value |
| --- | --- |
| Gap on the clean regime | **1.24x**, pure **sharpness**, not calibration |
| Skill decomposition | 98.88% resolution / 1.12% reliability — an **information** problem |
| Centre vs width | centre retires **74.97%** of excess loss, width **10.94%** |
| Cool bias | **−0.6641 C-eq**, crossed 95% **[−1.1164, −0.2482]**, D=34, M=12, 399 market-days |
| Severity tail | **4.26%** of rows carry **60.2%** of loss; market's mode wins ~98% vs our ~24% |
| Centre mechanism | too-cool HGB → mass below floor → truncation yanks centre warm. **Trace, don't infer** |
| Blindness as centre cause | **REJECTED** (+0.005453 bands). Do not revisit |
| Free-source parity repair | **NO-GO** — severe SSE 6.7395% [0.5208%, 14.3964%], pooled Brier −0.000721 [−0.032916, +0.030983] |
| 09:00–14:00 | **not** specially cool; it is the objective for other reasons |

**Never weaken the observed-high floor.** It is load-bearing and is the only absorption result
whose interval excludes zero.

## 4. The design is already constrained by the data — use this

I measured the available support on the production host so you do not have to guess:

- **69 distinct settled target dates, 2026-05-27 → 2026-08-04.**
- Days since the fit date (2026-06-13): **−17 to +52.**
- Split at the `2026-07-31` regime boundary: **64 dates before, 5 after.**

Two consequences, and they largely design the mission:

1. **Run the whole test inside the pre-`2026-07-31` regime.** 64 date clusters with a 64-day
   seasonal span is ample; crossing the boundary buys 5 dates and forfeits §5. **Never pool
   across `2026-07-31`** — it is artifact provenance, anchor commit `b77cfbed`, not target-date
   age.
2. **Measure the base HGB through replay, not served output.** Replaying one frozen artifact
   over captured inputs holds model and code constant by construction, which is the only way to
   stop calendar drift in the serving path from impersonating a seasonal trend. The floor fix,
   the WU disabling, and the marine sidecar going dark all sit inside this window.

### The natural experiment — prefer this over a bare regression

The season window gives three ordered strata of increasing seasonal distance:

| Stratum | Dates | Relationship to training |
| --- | --- | --- |
| **A. In-sample** | 2026-05-27 – 06-13 | inside May 10 – Jun 30 **and** before the fit date |
| **B. In-season, out-of-sample** | 2026-06-14 – 06-30 | inside the season window, after the fit |
| **C. Out-of-season** | 2026-07-01 – 07-30 | **outside** the archive's season entirely |

**If the thesis holds, cool bias increases monotonically A → B → C.** Stratum A is the control
that separates "the model is cool" from "the model is cool *where it never trained*". Report the
contrast C−A and C−B with crossed date × market intervals, and report the continuous trend
(residual on days-past-season-end) as a secondary.

## 5. Prioritised work

### P0 — the market control, first, because it can kill the mission cheaply

**August is genuinely hotter than June.** A model that is cool in July may simply be facing
weather no model predicted. The discriminator is that **the market saw the same weather.**

Compute the same stratified contrast for the **market's** implied centre on the identical rows.

- If **our** coolness grows A → C and the **market's** does not, the effect is ours and the
  thesis survives.
- If **both** grow together, you have measured the summer, not our model. **Report that and
  stop** — the retrain thesis is not supported and P1 is moot.

This is the cheapest falsifier and it must run before anything else.

### P1 — the stratified cool-bias contrast

Base-HGB centre minus settled outcome, per row, in **C-equivalent** units so it is comparable to
the retained −0.6641. Crossed date × market clustering is **mandatory**. Report per-market as
well as pooled: the retained bias is heterogeneous across markets and a pooled number hides it.

### P2 — is the effect where the loss is?

Report the same contrast **restricted to the severity tail** (the 4.26% of rows carrying 60.2%
of loss). That tail is the only endpoint we have that is powered at achievable N. If the
seasonal effect is real but absent from the tail, the retrain will not buy what we need, and
that distinction changes the decision.

## 6. Power — report it, and you may conclude "not powered"

- State the crossed date × market power for the C−A contrast **before** interpreting the point.
- **Known:** the primary-slice endpoint needs ~504 dates; the severe-tail endpoint needs ~4.
  The power of *this* trend contrast is **unknown** — establish it.
- If the contrast is not distinguishable from zero, **say so in those words** and do not present
  the point estimate as a movement. A "not powered" verdict here is a legitimate, valuable
  outcome that saves the collection spend.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 applies in full. Mission-specific:

- **Fit nothing. Collect nothing. No provider call.** This mission runs entirely on data already
  on disk. If it appears to need a fetch, stop and report that instead.
- **Do not touch `src/weather/model/model_features.py`** or `free_source_feature_parity.py` —
  held by `-09-22a`/`-09-26a`/`-09-20a`.
- **Do not touch `src/weather/calibration/**` or `operations/base_retrain.py` /
  `nightly_retrain.py`** — held by `-09-20a`.
- **Do not touch `src/weather/operations/daily_refresh*.py`** — `-09-29a` is awaiting merge.
- **Do not touch `src/weather/reporting/source_gates/`** — `-09-28a` is awaiting merge.
- **Do not touch `src/weather/sources/wu_history.py`** — a production fix branch is awaiting merge.
- Suggested home: `src/weather/reporting/research/`, which no in-flight branch holds. **Prefer
  adding as little production code as possible**; the deliverable is the measurement.
- Settlement authority is `data/settlements/<market>/ledger.jsonl`, never
  `market_day_labels.csv`. The admission bar is `promotion_countable`, not
  `quality_grade == "complete"`.
- Check `reserved-confirmation-window.md` at run time. As of writing, **nothing is reserved** —
  but it wins over this handoff if that has changed.

## 8. What would falsify this mission

Any of these is a valid outcome. Say it plainly and stop.

- **The market's coolness tracks ours A → C.** You measured the weather. The retrain thesis is
  unsupported by this test.
- **Coolness is flat across strata.** The June prior is not the mechanism. This is the single
  most valuable negative available today: it stops a collection programme and forces a new
  theory of the centre.
- **The contrast is not powered** at the achievable N, under crossed clustering.
- **The base HGB cannot be replayed over this span** holding artifact and code constant — then
  the measurement cannot be made honestly and the design must change, not be forced.
- **Stratum A is not genuinely in-sample.** If training row selection does not actually include
  those dates, the control is void; check before relying on it rather than assuming from the
  season window.

Write these honestly. Two of today's four missions produced their most valuable output by
falsifying their own premise.

## 9. Branch and report

- Branch: `codex/workstation-does-the-cool-bias-track-seasonal-distance-2026-09-30a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-does-the-cool-bias-track-seasonal-distance.md`

Report per `DELEGATION_CONTRACT.md` §5: verdict first in bold, measured values with support
(date clusters, market clusters, market-days) and interval treatment, per-file roll verdict from
the retained closures, what was NOT done, reproduction commands using **production-host paths**,
and the commit hash and branch.

**Commit and push the branch at whatever hour you finish** — §3 was corrected 2026-08-06:
pushing a branch cannot roll production capture, and merge timing is the production agent's
problem, not yours.
