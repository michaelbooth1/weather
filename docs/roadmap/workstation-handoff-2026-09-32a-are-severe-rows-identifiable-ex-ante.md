# Workstation handoff 2026-09-32a — are the severe-loss rows identifiable before the fact?

Written 2026-08-06 by the production agent. Read on `origin/master` and execute.
**Runs in parallel with `-09-31a` and `-09-33a`. File-disjoint from both.**

## 1. Goal

**Decide whether the rows that carry most of our loss can be recognised at prediction time,
using only information available at the cutoff** — because if they can, we get a defensive lever
that needs no retrain and no better forecast, and if they cannot, the tail is irreducible
without better forecasting and we should stop looking for a cheap fix.

## 2. Why this is worth a mission

**4.26% of rows carry 60.2% of total loss.** On those rows the market's modal band wins roughly
**98%** of the time against our roughly **24%**. That is not a calibration gap, it is a rout, and
it is concentrated enough that acting on it does not require the model to get better.

Everything else in flight tries to make the model *more right*. This asks a different question:
**can we tell, in advance, when it is about to be very wrong?** A model that knows when to stand
down is worth real money in the maker even while it trails the market on average — and the maker
is the end goal.

Nothing else is working on this.

## 3. Start from this — do not re-derive it

| Fact | Value |
| --- | --- |
| Severity tail | **4.26%** of rows carry **60.2%** of loss |
| Market vs us on the tail | market's modal band wins **~98%**, ours **~24%** |
| Gap nature | pure **sharpness**, 98.88% resolution / 1.12% reliability — an information problem |
| Centre vs width | centre retires **74.97%** of excess loss, width **10.94%** |
| Blend with market | **hurts** on clean data |
| Severe-tail endpoint power | needs ~**4** dates — the only endpoint powered at achievable N |
| Available support | ~**2.23M** snapshots across **15,174** settled market-days; a 4.26% tail is ~**94,880** rows |

**Never globally sharpen.** It is the wrong axis and degrades calibration for nothing.

## 4. The trap that will kill this mission if you let it

**Leakage.** `item-224`'s apparent win over the market was leakage, and it is recorded in
`RETRACTED_AND_FALSE_LEADS.md` for exactly this reason.

"Identifiable ex ante" means **using only information timestamped at or before the row's own
cutoff.** Not the settled outcome, not the day's realised high, not a same-day aggregate that
silently includes the future, not a feature whose upstream source was written after the cutoff.

State explicitly, per candidate signal, what its information cutoff is and how you enforced it.
A signal you cannot date is a signal you cannot use. **If in doubt, exclude it and say so.**

## 5. Prioritised work

### P0 — the cheapest falsifier: is there any structure at all?

Before building anything predictive, ask whether severe rows are **non-random** with respect to
observables available at the cutoff. Cross-tabulate the severe set against cheap, clearly
ex-ante dimensions — market, cutoff hour, forecast disagreement, forecast-source count,
model distribution width/entropy, distance between `high_so_far` and `forecast_high`, and the
band structure of the market's own quotes.

**If severe rows look like a random 4.26% draw on every available dimension, report that and
stop.** That is a complete answer: the tail is not ex-ante identifiable, no defensive lever
exists, and the only route is a better forecast. Do not proceed to P1 to salvage the mission.

### P1 — how much of the tail is reachable, and at what cost

If structure exists, characterise it as a **decision rule**, not a model:

- What fraction of severe-tail loss sits inside the flagged set?
- What fraction of *non*-severe rows does the rule also flag? Standing down on quiet days has a
  cost, and a rule that flags 40% of everything to catch the tail is not a lever.
- Report the trade-off curve, not a single operating point. **The operating point is an operator
  decision, not yours.**

### P2 — does it survive the method rules?

Crossed date × market clustering is mandatory for any inferential claim.
**Characterisation is descriptive and needs no interval; a claim that the rule works does.**
Report power. "Not distinguishable from zero" is a valid verdict — say it in those words.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. Mission-specific:

- **Fit no model, produce no candidate, promote nothing.** A decision rule over existing
  features is in scope; a new learned model is not.
- **Do not quote, trade, or touch maker configuration.** This mission produces evidence about a
  possible lever. Wiring it to the maker is a separate, later decision.
- **Never weaken the observed-high floor.**
- Do not touch: `reporting/research/` (`-09-31a`); `sources/forecast_history.py`,
  `calibration/**`, `operations/base_retrain.py`, `operations/nightly_retrain.py`
  (`-09-20a`/`-09-33a`); `model/model_features.py`, `model/free_source_feature_parity.py`
  (`-09-22a`, `-09-26a`); `operations/daily_refresh*.py` (`-09-29a`);
  `reporting/source_gates/` (`-09-28a`); `sources/wu_history.py` (production fix branch);
  `market/**` (held maker stack).
- **Suggested home: `src/weather/reporting/casebooks/`** — verified free of every in-flight branch.
- Settlement authority is `data/settlements/<market>/ledger.jsonl`. Admission bar is
  `promotion_countable`.
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
- Check `reserved-confirmation-window.md` at run time; it wins over this handoff.

## 7. What would falsify this mission

- **Severe rows are indistinguishable from a random draw** on every ex-ante dimension. Complete
  answer, report and stop.
- **Every candidate signal fails the cutoff test.** If the only things that separate severe rows
  are things we learn after the fact, say so — that is the leakage finding, and it is worth more
  than a rule.
- **The rule's collateral flag rate makes it useless** — it catches the tail only by flagging so
  much of the book that standing down costs more than the tail does.
- **Not powered** under crossed clustering.

## 8. Branch and report

- Branch: `codex/workstation-are-severe-rows-identifiable-ex-ante-2026-09-32a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-are-severe-rows-identifiable-ex-ante.md`

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths. **Commit and push at
whatever hour you finish** — §3, corrected 2026-08-06.
