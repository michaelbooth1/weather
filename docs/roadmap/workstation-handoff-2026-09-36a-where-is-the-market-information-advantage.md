# Workstation handoff 2026-09-36a — where is the market's information advantage?

Written 2026-08-06 by the production agent. Read on `origin/master` and execute.
**Long research, run overnight. Nothing else is running; nothing depends on this landing fast.**

## 1. Goal

**Localise the market's resolution advantage** — by hour, market, and regime — so the next piece
of model work aims at where we actually lose instead of at the pooled average.

## 2. Why this, and why now

`-09-34a` closed the question this project has been implicitly assuming away. Served in-season is
**1.4233x [1.2428, 1.6589]** — the interval excludes 1.0. The model is **nearly unbiased**
in-season (−0.1848 C-eq, `-09-31a`) **and still loses**, on a deficit attributed to **resolution**.

So bias and sharpness are separate problems, and every line of work in flight addresses bias:
the retrain fixes a seasonal centre defect, and centre is 74.97% of oracle excess loss. **Nothing
is aimed at resolution**, and §1 already establishes that recalibration cannot supply it — it is
an *information* problem, 98.88% resolution against 1.12% reliability.

**This is now the larger half of the gap and it is unowned.**

## 3. Start from this — do not re-derive it

| Fact | Value |
| --- | --- |
| Skill decomposition | **98.88% resolution / 1.12% reliability** |
| Recalibration | **cannot close it** |
| Blending with the market | **hurts** on clean data |
| Centre vs width | centre **74.97%** of excess loss, width **10.94%**. **Never globally sharpen** |
| Severity tail | **4.26%** of rows carry **60.2%** of loss; market's mode wins ~98% vs our ~24% |
| Severe rows are ex-ante identifiable | at **band** granularity: a ≥30-point model/market gap catches 100% of severe-tail loss at 1.714% band collateral, but touches 40% of snapshots (§4d) |
| Cool bias | seasonal coverage, **not** a general staleness (§2) |

**Do not re-open:** the free-source blindness repair (NO-GO, §4b), whether the cool bias is
seasonal (settled, §2), whether release #1 helps (deferred, and it does not unblock promotion).

## 4. Prioritised work

### P0 — the cheapest falsifier, and it can end the mission decisively

**Is the resolution deficit concentrated, or uniform?**

Decompose the model-vs-market resolution gap across the dimensions we can act on: **cutoff hour,
market, and weather regime** (the chain already carries regime labels — `early_morning`,
`ramp_midday`, `lock_in`, `late_day`).

- **If it is uniform** — we lose about equally everywhere — then there is no localised fix, no
  targeted feature will help, and the honest answer is that we need materially better forecast
  information rather than better use of what we have. **Report that and stop.** It is a complete
  and valuable answer that would redirect the whole programme.
- **If it is concentrated**, P1 characterises where.

### P1 — characterise the concentration

For the slices where the market's advantage is largest: what distinguishes them? Report the
market's own behaviour there too — its entropy, mode confidence, and how early it converges
relative to us. **A slice where the market is confident early and right is a different problem
from one where it is merely less wrong than us**, and they call for different work.

### P2 — is there a captured signal that predicts our resolution failures?

We collect 23 source adapters and the extractor reads 16. **The blindness defect (§4) was exactly
this shape one level down: captured, parsed, and then discarded.** Ask whether any *already
captured* series correlates with the slices found in P1 — NBM probabilistic Tmax, MRMS precip,
marine context, ASOS one-minute, reanalysis synoptic, the multi-model spread.

**This is a search for a lead, not a licence to fit.** Report correlations with their intervals
and leave the modelling to a later, separately commissioned mission.

## 5. Method — binding

- **Crossed date × market clustering.** Report power before interpreting any point.
  **"Not powered" is a valid verdict** and is preferred to a directional story.
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
- **Leakage.** Every signal must carry an explicit information cutoff at or before the row's own
  cutoff. `item-224`'s "win" was leakage. **A signal you cannot date, you cannot use.**
- Ledger rows are **not** market-days — deduplicate to `(market, target_date)`, then apply
  `promotion_countable`. A 2026-08-06 handoff quoted 15,174 "market-days" that were 729
  (`RETRACTED_AND_FALSE_LEADS.md`).
- Prefer reusing `-09-31a`'s corpus and stratification where it fits, so results stay comparable.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. Mission-specific:

- **Fit no model, produce no candidate, collect nothing, make no provider call.** This runs on
  data already on disk.
- **Do not blend model with market** — recorded as harmful on clean data.
- **Do not tune the severe-tail band-suppression lever** (§4d) — it must wait for the retrain.
- Do not touch: `sources/forecast_history.py`, `calibration/**`, `operations/base_retrain.py`,
  `operations/nightly_retrain.py` (`-09-33a`/`-09-20a`); `reporting/casebooks/` (`-09-32a`);
  `reporting/source_gates/`, `operations/daily_refresh*.py`, `sources/wu_history.py`,
  `schema_registry*` (all awaiting merge tonight); `market/**` (held maker stack).
- **Suggested home: `src/weather/reporting/research/`** — free.
- Check `reserved-confirmation-window.md` at run time; it wins over this handoff. Nothing is
  reserved as of writing.

## 7. What would falsify this mission

- **The deficit is uniform** across hour, market and regime. Complete answer — report and stop.
- **Not powered** to decompose at the achievable N. Say so; do not substitute a directional story.
- **Every candidate signal fails the cutoff test.** Then the finding is that our ex-ante
  information surface is genuinely thinner than the market's, which is worth more than a
  correlation table.
- **The market's advantage turns out to be timing rather than information** — it converges earlier
  on the same information. That is a different problem, and naming it is a real result.

## 8. Branch and report

- Branch: `codex/workstation-where-is-the-market-information-advantage-2026-09-36a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-where-is-the-market-information-advantage.md`

Per `DELEGATION_CONTRACT.md` §5, production-host reproduction paths, and a per-file roll verdict
from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand.
**Commit and push at whatever hour you finish**; pushing a branch cannot roll production capture.
