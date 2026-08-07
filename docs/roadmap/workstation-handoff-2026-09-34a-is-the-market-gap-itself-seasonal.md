# Workstation handoff 2026-09-34a — is the market gap itself seasonal?

Written 2026-08-06 by the production agent. Read on `origin/master` and execute.
**Runs beside `-09-32a` and `-09-33a`. File-disjoint from both.**

## 1. Goal

**Decide whether we lose to the market in-season as badly as out-of-season** — because that
determines whether the retrain is the whole answer to objective #2 or merely a precondition for
it.

## 2. Why this is the question, and why it is not answered by `-09-31a`

`-09-31a` established that the model's **centre bias** is seasonal: in-season it is very nearly
unbiased at **−0.1848 C-eq**, out-of-season it is a full degree cool at **−1.0193**, contrast
**−0.8346 [−1.4378, −0.2159]**, power 83.17%, with the market's own contrast **flat** at
−0.0057 [−0.1643, +0.1520].

**Bias is not the gap.** The gap is recorded as **pure sharpness**: skill decomposes
**98.88% resolution / 1.12% reliability**, and **recalibration cannot close it** — it is an
*information* problem. A model can be unbiased and still lose, by being reliably vague.

So there are two worlds and we do not know which we are in:

| | If true | Consequence |
| --- | --- | --- |
| **A. The gap collapses in-season** | our loss is mostly the seasonal defect | the retrain is the answer, and we should expect to close most of the gap |
| **B. The gap persists in-season** | the seasonal defect sits *on top of* a sharpness deficit | the retrain is **necessary but not sufficient**, and a second, independent line of work is required |

**We are currently sequencing the entire programme as if A were true, without having tested it.**
That is the same shape of unexamined assumption `-09-31a` was commissioned to close, and this is
the next one down the chain.

## 3. Start from this — do not re-derive it

| Fact | Value |
| --- | --- |
| Gap on the clean regime | **1.24x**, pure sharpness, not calibration |
| Skill decomposition | **98.88% resolution / 1.12% reliability** |
| Blending model with market | **hurts** on clean data |
| Centre vs width | centre retires **74.97%** of excess loss, width **10.94%** |
| Severity tail | **4.26%** of rows carry **60.2%** of loss; market's mode wins ~98% vs our ~24% |
| Seasonal centre contrast | above, `-09-31a` |
| Severity-tail seasonal contrast | **underpowered — 47.65%, interval crosses zero.** No loss-lever claim is authorised |

**Never globally sharpen.** Wrong axis, degrades calibration for nothing.

## 4. The design is mostly handed to you

**Reuse `-09-31a`'s corpus and stratification exactly.** Its evidence manifest is
`b65810a907ed9ab0dcbff553d4b12557fcd84e5c325afedaf484c5b6247fe576`; population 12,289 hourly
snapshots on **D=50, M=12, 524 market-days**, B = D=23/MD=204/H=4,636, C = D=27/MD=320/H=7,653.
Reusing it means this result is directly comparable to the bias result and does not re-litigate
scope. **If you must deviate, say exactly how and why.**

What changes is only the **endpoint**:

1. **Model-vs-market Brier, stratified B and C**, and the **ratio** in each stratum. This is the
   quantity objective #2 is defined on.
2. **The skill decomposition in each stratum** — resolution and reliability separately. This is
   what distinguishes the two worlds: if the in-season resolution deficit closes, that is World A;
   if it persists while only reliability moves, that is World B.

**Measure both the base HGB and the served output, and report them side by side.**

- **Base is the retrain counterfactual** — it is what a retrain actually changes.
- **Served is the tradable gap** — it is what we lose money on.
- The divergence between them is itself a finding. `ESTABLISHED_FINDINGS.md` §3 records that only
  about **2.2%** of the shipped floor-fix improvement landed in the primary window; if base gains
  do not survive the serving stack, a better base model does not automatically become a better
  business.

**Both strata sit before `2026-07-31`, so the floor fix does not confound the comparison** —
stratum C ends 07-30. Do not pool across that boundary regardless (anchor `b77cfbed`).

## 5. Power

Crossed date × market, mandatory. **State the power before interpreting any point.** The
severity-tail version of the seasonal contrast came back at 47.65% and was correctly refused —
expect this endpoint to be no easier, and **"not powered" is a valid and valuable verdict.** Do
not produce a directional story to fill the space where an interval should be.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. Mission-specific:

- **Fit nothing. Collect nothing. No provider call. Produce no candidate.**
- **Do not blend model with market**, even to explore. It is recorded as harmful on clean data and
  is not what this measures.
- Do not touch: `reporting/casebooks/` (`-09-32a`); `sources/forecast_history.py`,
  `calibration/**`, `operations/base_retrain.py`, `operations/nightly_retrain.py`
  (`-09-33a`/`-09-20a`); `model/model_features.py`, `model/free_source_feature_parity.py`
  (`-09-22a`, `-09-26a`); `operations/daily_refresh*.py`, `reporting/source_gates/`,
  `sources/wu_history.py` (all awaiting merge); `market/**` (held maker stack).
- **Suggested home: `src/weather/reporting/research/`** — free again now that `-09-31a` has
  returned.
- Settlement authority is `data/settlements/<market>/ledger.jsonl`; admission bar is
  `promotion_countable`.
- Check `reserved-confirmation-window.md` at run time; it wins over this handoff.

## 7. What would falsify this mission

Each is a complete outcome. **A void control means drop it and run what remains sound; stop only
when the contrast itself cannot be made or interpreted.**

- **The gap is flat across strata.** World B. The retrain fixes bias and not the gap, and the
  programme needs a second line of work aimed at sharpness. **This is the most valuable negative
  available today** — it would stop us expecting the retrain to do something it cannot.
- **The gap collapses in-season.** World A, and the retrain is the answer. Say how much of the
  1.24x is seasonal and how much residual remains.
- **Not powered** under crossed clustering.
- **Base and served diverge so far that the base contrast says nothing about the tradable gap.**
  Then the finding is the absorption problem, and it outranks the seasonal question.

## 8. Branch and report

- Branch: `codex/workstation-is-the-market-gap-seasonal-2026-09-34a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-is-the-market-gap-seasonal.md`

Per `DELEGATION_CONTRACT.md` §5, production-host reproduction paths, per-file roll verdict from
`scripts\ops\roll_verdict.ps1`. **Commit and push at whatever hour you finish.**
