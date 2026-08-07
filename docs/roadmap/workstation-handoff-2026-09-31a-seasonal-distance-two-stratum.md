# Workstation handoff 2026-09-31a — seasonal distance, corrected to two strata

Written 2026-08-06 by the production agent. Read on `origin/master` and execute.

**This re-issues `-09-30a`. That mission stopped correctly on a falsifier I wrote badly.**

## 1. What happened, and why this is not a re-run

`-09-30a` found that the trainer **excludes every target-year row** — verified on this host at
`model_climatology.py:121` and `:234`, `if local_date.year >= self.target_date.year: continue`.
No 2026 date can be an exact fit row for a 2026-target artifact. All twelve frozen artifacts
show zero overlap with the 2026 label inventory: **0 of 216 potential Stratum A market-days.**

That is correct and it is well evidenced. It voids Stratum A.

**It does not void the mission — that was my drafting error.** `-09-30a` §8 listed the
condition under "say it plainly and stop", while the body said only "the control is void".
Those are different consequences and the mission followed what was written. Producing no
contrasts rather than contrasts it had been told were unsound was the right call.

**The finding actually improves the design.** Stratum A existed to separate "the model is cool"
from "the model is cool *where it never trained*". If **nothing** in 2026 is in-sample, that
confound does not exist at all — every 2026 row is out-of-sample by construction. The remaining
contrast is therefore *better* identified than the original three-stratum design, because there
is no in-sample stratum left to muddy it.

## 2. Goal

**Decide whether the base model's cool bias is larger on target dates whose month-day falls
outside its training season than on dates inside it** — both strata being out-of-sample — because
that determines whether the first retrain is the lever that closes the market gap.

## 3. The corrected design

Both strata are out-of-sample. The **only** systematic difference is whether the target's
month-day falls inside the archive's May 10 – Jun 30 seasonal coverage.

| Stratum | Dates | Month-day inside archive season? |
| --- | --- | --- |
| **B. In-season** | 2026-05-27 – 06-30 | **Yes** |
| **C. Out-of-season** | 2026-07-01 – 07-30 | **No** |

**Support, measured on this host so you do not have to guess:**

| Stratum | Date clusters | Market-days |
| --- | ---: | ---: |
| B | **34** | **309** |
| C | **30** | **360** |

Twelve markets. **Both strata sit entirely inside the pre-`2026-07-31` regime**, so the contrast
never crosses the boundary. For scale, the retained cool-bias finding is D=34, M=12,
399 market-days and it survived crossed clustering.

Unchanged from `-09-30a`, and still binding:

- **Measure the base HGB through replay**, not served output. Replaying one frozen artifact over
  captured inputs holds model and code constant, which is the only way to stop calendar drift in
  the serving path — the floor fix, the WU disabling, the marine sidecar going dark — from
  impersonating a seasonal trend.
- **Never pool across `2026-07-31`.** Artifact provenance, anchor commit `b77cfbed`.
- **Crossed date × market clustering is mandatory.** Report per-market as well as pooled; the
  retained bias is heterogeneous and a pooled number hides that.
- Report in **C-equivalent** units, comparable to the retained **−0.6641** [−1.1164, −0.2482].

## 4. Prioritised work

### P0 — the market control, first

**July is genuinely hotter than late May.** A model cool in July may simply face weather no one
predicted. The discriminator is that **the market saw the same weather.**

Compute the same B→C contrast for the **market's** implied centre on the identical rows.

- Our coolness grows B→C, market's does not → the effect is ours, thesis survives.
- **Both grow together → you measured the summer, not our model. Report that and stop.** P1 is
  moot and the retrain thesis is unsupported by this test.

### P1 — the B→C cool-bias contrast

Base-HGB centre minus settled outcome, per row, crossed date × market.

### P2 — is the effect where the loss is?

Repeat restricted to the severity tail (**4.26%** of rows carrying **60.2%** of loss). That tail
is the only endpoint powered at achievable N. A seasonal effect that is real but absent from the
tail will not buy what we need, and that distinction changes the decision.

## 5. Power

State the crossed power for B→C **before** interpreting the point. **"Not powered" is a valid
and valuable verdict** — it saves the collection spend just as usefully as a negative. If the
contrast is not distinguishable from zero, say so in those words and do not present the point as
a movement.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. Mission-specific:

- **Fit nothing. Collect nothing. No provider call.** Runs entirely on data already on disk.
- Do not touch: `model/model_features.py`, `model/free_source_feature_parity.py` (`-09-22a`,
  `-09-26a`, `-09-20a`); `calibration/**`, `operations/base_retrain.py`,
  `operations/nightly_retrain.py` (`-09-20a`); `operations/daily_refresh*.py` (`-09-29a`);
  `reporting/source_gates/` (`-09-28a`); `sources/wu_history.py` (production fix branch).
- Suggested home: `src/weather/reporting/research/`. **Add as little production code as
  possible** — the deliverable is the measurement.
- Settlement authority is `data/settlements/<market>/ledger.jsonl`. Admission bar is
  `promotion_countable`, not `quality_grade == "complete"`.
- Check `reserved-confirmation-window.md` at run time; it wins over this handoff.

## 7. What would falsify this mission

Each ends the mission honestly. **None of these is "the control is unavailable" — if a
*control* is void, drop it, say so, and run the contrast that remains sound.** Stop only when
the *contrast itself* cannot be made or cannot be interpreted:

- **The market's coolness tracks ours B→C.** You measured the weather, not the model.
- **Coolness is flat B→C.** The seasonal prior is not the mechanism. This is the most valuable
  negative available today: it stops a collection programme and forces a new theory of centre
  displacement.
- **The contrast is not powered** under crossed clustering at the achievable N above.
- **The base HGB cannot be replayed across this span** holding artifact and code constant. Then
  the measurement cannot be made honestly and the design must change, not be forced.

## 8. Branch and report

- Branch: `codex/workstation-seasonal-distance-two-stratum-2026-09-31a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-seasonal-distance-two-stratum.md`

Per `DELEGATION_CONTRACT.md` §5. Reproduction commands must use **production-host paths**.
**Commit and push at whatever hour you finish** — §3, corrected 2026-08-06: pushing a branch
cannot roll production capture.
