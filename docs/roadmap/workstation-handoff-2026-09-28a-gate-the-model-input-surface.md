# Workstation handoff 2026-09-28a — gate the model input surface

Written 2026-08-06 by the production agent.

## 1. Goal

**A daily, fleet-wide gate that fails when a feature the serving model was trained on is
not actually arriving at serve** — so that a repeat of the 10-dead-feature defect is caught
by the pipeline on day one instead of by a human reading a feature table five weeks later.

## 2. Start from this — do not re-derive it

All of this is established. Cite `ESTABLISHED_FINDINGS.md` §4; do not re-measure it.

- **10 of 19 base features are 100% empty at every cutoff hour 07:00–20:00, in all 11
  markets measured** (~5,761 rows, Aug 3–5). Exactly zero populated values, not "mostly
  empty".
- The dead set is the entire local-meteorology block: `rise_from_7am`, `warming_rate_2h`,
  `hours_at_peak`, `dewpoint_c`, `humidity`, `pressure`, `pressure_trend_3h`,
  `wind_speed_kmh`, `wind_gust_kmh`, `wind_shift_3h_degrees`.
- **8 of 29 trained features are dead at serve in all 14 hour models** of
  `feature_model_hgb.pkl`.
- **Training was not blind.** The serving artifact's `SimpleImputer` carries a finite,
  physically sensible median for every dead feature. This is pure train/serve skew.
- Per-market artifacts carry medians in **native units** (Denver `pressure` 24.4 inHg,
  Miami `dewpoint_c` 73 °F) while the pooled Toronto model is hPa/Celsius.
- The existing `train_serve_feature_parity.py` on `-09-12a` detected **2 of the 10**. It is
  the closest prior art and should be read before designing this.

**The defect class this gate exists to stop:** the repository has 171 modules emitting
`"BLOCK"` and ~1,348 distinct blocker strings, and not one of them watches whether the
model's inputs arrived. Every gate is on outputs, process, or resources. That is why a
five-week fleet-wide blindness was invisible to a daily pipeline that reported all steps ok.

## 3. Prioritised work

### P0 — the cheapest falsifying test, first

**Before building anything, answer: can a coverage gate be computed from artifacts that
already exist on the production host, without a new capture path?**

Enumerate the trained feature names per hour model from the serving artifact, and the
populated-vs-null counts per feature per market per hour from already-captured live
prediction rows. If either side cannot be obtained from existing artifacts, **stop and
report that** — the mission's premise is that this is a reporting gap, not a capture gap.

### P1 — the gate

A standalone module producing a dated JSON artifact plus a gate verdict:

- Per `(market, cutoff_hour, feature)`: populated fraction over the window.
- Verdict `BLOCK` when a **trained** feature's populated fraction is below a floor, with
  the floor declared in code, not supplied by the thing being judged. **Read
  `ESTABLISHED_FINDINGS.md` §8 before choosing where the threshold lives** — this project
  has already shipped one gate a candidate could shrink from 20,160 cells to 2,520 by
  editing one JSON field. Do not repeat that shape.
- `wind_gust_kmh` is **legitimately absent in calm conditions** and must be allowed to be
  missing without tripping the gate. Handle it explicitly rather than by a blanket
  tolerance.
- Report per-market, not pooled. The blindness was uniform, but a partial regression will
  not be, and a pooled number hides exactly the case this gate exists to catch.

### P2 — positive control

The gate must **reproduce the established finding on current production data**: 10 base
features at 0.0%, the other 9 at 93.6–100%. A gate that cannot reproduce a known-true
defect is not evidence of anything. State the reproduction explicitly in the report.

## 4. Boundaries

`DELEGATION_CONTRACT.md` §2 applies in full and is not restated here. Mission-specific:

- **Do not touch `src/weather/model/model_features.py`.** Three concurrent branches own it:
  `-09-22a`, `-09-26a`, and `-09-20a`. If you need a change there, **report the requirement
  instead of taking the file.**
- **Do not touch `src/weather/model/free_source_feature_parity.py`** — owned by `-09-22a`
  and `-09-26a`.
- **Do not touch any `src/weather/operations/daily_refresh*.py`.** Concurrent mission
  `-09-29a` owns the entire chain orchestration.
- **Do not register this gate as a chain step.** `-09-29a` is restructuring the chain into
  promotion and learning lanes; registration happens after that lands, as a follow-up. Ship
  this as a standalone CLI plus artifact.
- **Do not repair the dead features.** That is `-09-22a`/`-09-26a`. This mission measures
  and gates only. If you find yourself editing an extractor, you are in the wrong mission.
- Suggested home: `src/weather/reporting/source_gates/`, which already owns comparable
  gates and is not held by any in-flight branch.

## 5. What would falsify this mission

State plainly in the report if any of these hold. Any one of them is a valid, valuable
outcome and ends the mission early.

- **The trained feature list cannot be recovered per hour model** from the serving
  artifacts — the gate cannot know what to check for, and the design must change.
- **Populated/null counts are not recoverable from captured rows** without adding a capture
  path — this becomes a capture change, which is out of scope and needs a new decision.
- **A coverage gate cannot distinguish "dead" from "legitimately missing"** at an
  acceptable false-positive rate. If `wind_gust_kmh`-style legitimate absence cannot be
  separated from routing death, say so — a gate that cries wolf daily will be ignored,
  which is worse than no gate. This project already carries known-false daily alarms and
  they measurably train the operator to skim.
- **The gate cannot reproduce the 10-at-0.0% positive control.** Then the measurement stack
  is wrong and the finding is not; report that and stop.

## 6. Branch and report

- Branch: `codex/workstation-gate-the-model-input-surface-2026-09-28a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-gate-the-model-input-surface.md`

Report must satisfy `DELEGATION_CONTRACT.md` §5, including a **per-file roll verdict**
derived from `runtime_identity.source_scope_files` in the capture status files — not from
the `SOURCE_PATTERNS` glob, which over-reports.
