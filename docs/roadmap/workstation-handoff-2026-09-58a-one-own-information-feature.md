# Workstation handoff 2026-09-58a — one own-information feature for the disagreement set

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.
**This is the first mission under the central goal (`ESTABLISHED_FINDINGS.md` §0c) and the first
to spend a decision from `CAMPAIGN_LEDGER.md`.**

## 1. Why this is the top item

`-09-56a` decomposed the gap: it is **information, not calibration** — recalibration is bounded at
16.494% of the served gap and is not distinguishable from zero (§1c). `-09-57a` characterised the
instrument: the loss-bearing severity tail **can** be refereed at 3.53% of its gap, but there is a
**hard ~3.2% floor set by the 12 market clusters, not by dates** (§1d).

Cross-referencing the two leaves exactly one live candidate:

> **Every sized candidate on the worklist clears the floor. The only one that would constitute real
> edge — a new point-in-time information feature — is the one with NO SIZE.**

Sizing it is therefore the highest-value work available. **The deliverable is a number where there
is currently `unidentified`.**

## 2. The governing constraint — read this before designing anything

**§0c: better from OUR OWN information, never by consuming the benchmark.**

`-09-56a`'s rank 1 (shrink toward market, 65.111% of the gap) is **not** the target and must not be
built. It is a **diagnostic that localises where our information is missing**. Its 85.632% ceiling
on the disagreement set is an *opportunity bound*, **not** an expected delta for a weather feature —
it measures what the market knows, not what any input of ours supplies.

**The trap, stated explicitly because it is easy to fall into:**

- **Permitted:** using `|model − market| ≥ 0.30` to define the **study population**, i.e. where you
  look for signal.
- **FORBIDDEN:** any market-derived quantity in the served feature, and any serving branch that
  consults the market price to decide behaviour. If the candidate cannot be computed at serve from
  our own inputs alone, it is out of scope no matter how well it scores.

## 3. P0 — the cheap question first: does any own-information signal predict our own error?

**Do not build a feature yet.** Ask whether a mechanism exists, on the **in-season B stratum**
(D=23), which keeps out-of-season C clean for the confirmatory test in P1.

**Estimate the association between candidate own-information signals and our excess loss on the
disagreement rows.** Rank the mechanisms; carry **one** forward. Candidates worth pricing, all
own-information and all with a stated mechanism:

| Candidate | Mechanism | PIT status |
| --- | --- | --- |
| **Forecast run-to-run instability** — how much the forecast for the target high moved across successive issue times | volatility across runs = genuine uncertainty the model cannot currently see | **`open_meteo_previous_runs`, `fixed_lead_day_offset` — genuinely PIT** |
| **Recent forecast-error dispersion for this station** — rolling error over the last N target days | station-specific dispersion estimator | PIT if strictly lagged past settled days |
| **Multi-source spread** — Open-Meteo vs ECCC vs persistence at the cutoff | source disagreement = uncertainty | verify each source's issue-time basis before use |
| **Intraday trajectory residual** — observed path vs forecast path by cutoff | today is already running hot/cold | own captured station rows, cutoff-aligned |

**Prefer a DISPERSION signal over a centre signal.** §1 says the gap is resolution/information;
§4d says the severe tail is ex-ante identifiable at band granularity; §1c says we are *confidently
wrong* on the disagreement set. A feature that knows **when to be less confident** targets exactly
that. This is conditional, not global — **global sharpening stays retired, and the fitted β from
`-09-56a` was below 1.**

**PIT honesty is a hard wall, not a preference (§0a).** Free-tier point-in-time provenance exists
for **temperature only**. `open_meteo_previous_runs` carries `fixed_lead_day_offset` and is genuine;
`open_meteo_historical_forecast` carries `stitched_continuous_archive` and **has no true issue
time**. Building a feature on the stitched rows would re-introduce
`stitched_forecast_high_without_issue_time`, a defect **already declared by name** in
`tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json`. **Check `issue_time_basis` in
the data itself — not the manifest's declaration of what was requested.** That exact error was made
on this project and cost a mission.

**If no candidate has a PIT-honest source, stop and report that.** It is the §0a wall shape and
knowing it early is worth more than a forced answer.

## 4. P1 — build ONE, pre-register it, then test it

**Append your row to `docs/operations/CAMPAIGN_LEDGER.md` BEFORE you score anything on C.** That
file is the control; a decision recorded afterwards is not a decision, it is a description. This is
**decision 8 of 20** and the first real use of the ledger.

- **One feature at a time.** Not a family, not a sweep. State the mechanism *before* the number.
- **Not more input completeness.** `-09-44a` bounded that at **≤0.6% of the distance to parity**.
  A new mechanism is required, not a filled-in existing column.
- Regularized **walk-forward** residual model. No design that sees its own target.
- **Test at α=0.0025 two-sided** (family α 0.05 over 20 decisions). Report selection-adjusted
  evidence, never the raw best.
- Crossed date × market clustering. **Never pool across `2026-07-31`.**

## 5. P2 — size it against the floor, and re-derive the MDE

**Do not reuse `-09-57a`'s MDE.** §1d is explicit that MDE depends on the candidate's **own** date ×
market effect field, and that curve is a proxy built from `-09-44a`'s repair-minus-control field.
**Compute the MDE for the feature you actually built.**

Then place it against the floor and say plainly which case holds:

| Effect | Verdict |
| --- | --- |
| **≥5% of the gap** | individually confirmable; give the post-boundary date from §1d's schedule |
| **~3.2%–5%** | confirmable only late; state the date |
| **≤3.2%** | **NOT individually confirmable at any date count.** Report it, do not ship it alone — **it must be batched** |

**Cite the stratum, always** (§1b.4). And per §0c: **no accuracy gain may be reported as expected
P&L** — a taker pays `5% × (1−p)` and cannot trade at mid.

## 6. What would falsify this mission

- **No PIT-honest own-information source exists** for any mechanism-bearing candidate → the §0a
  wall extends further than temperature, and that closes this route cleanly.
- **No own-information signal predicts our excess loss on the disagreement set** → then the market's
  advantage there is not something our inputs can supply, and the 85.632% ceiling is unreachable by
  construction. **This is the single most valuable thing this mission could discover** — it would
  mean the gap is structural rather than addressable, and would redirect the whole programme.
- **The effect is real but below the floor** → the incremental path must move to batched testing,
  and we should know that before spending more decisions one at a time.

## 7. Context you should not re-derive

- **Recalibration is closed** (§1c). Do not fit a mapping. Scalar isotonic is NO-GO and worsened
  even its own training score.
- **Model-skewed quoting is retired** — `-09-46a`, 114 cells, zero positive.
- **`74.97%` is unciteable** and has no replacement.
- Nothing is reserved; `docs/operations/reserved-confirmation-window.md` wins over every other
  document.
- **Score any fitted thing on its own training set first** (§5) — free, and it localises a broken
  objective instantly.

## 8. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Promote nothing, activate nothing, place no order, enable no
live trading, call no exchange or weather-provider endpoint.** Nothing under production `data/`. No
chain run, settlement, or loop restart. **Never weaken the serving floor.** The production release
store must stay empty. Fitting is authorized to a scratch root, stated explicitly; anything fitted
is a **diagnostic candidate**, never promoted.

**Paid weather-provider access is unsupported.** Do not add credentials, required environment
variables, or any plan that depends on a paid weather source.

## 9. Branch and report

- Branch: `codex/workstation-one-own-information-feature-2026-09-58a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-own-information-feature.md`
- **Also commit your `CAMPAIGN_LEDGER.md` row** — it is part of the deliverable.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
