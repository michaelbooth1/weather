# Workstation handoff 2026-09-59a — anatomy of the severity tail

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.
**Long-running is fine. This needs no new data, no provider call, and nothing from any other
mission.**

## 1. Why this, now

`-09-58a` asked whether an own-information dispersion signal predicts our excess loss **on the
disagreement set**, and returned a **blind** null — power ~0.11 on 11–14 date clusters, because the
PIT-honest source stops `2026-06-23` (§1e). That route is blocked until a re-fetch runs on
production.

So aim at the other target, which is **better** anyway and needs nothing we do not already hold:

> **§1: 4.387% of band rows carry 64.140% of positive excess loss.** *"Any work that improves the
> pooled average while leaving the tail alone is close to worthless."*

`-09-57a` certified that this endpoint is **measurable** — tail MDE `0.0151764`, **3.53% of its
remaining gap**, the second-sharpest instrument we own. **We have a refereeable endpoint carrying
two-thirds of the loss, and nobody has ever characterised what is IN it.**

## 2. P0 — what distinguishes a tail row?

**Estimand: which ex-ante-identifiable, own-information characteristics separate severity-tail band
rows from the rest, on the current surface?**

Use the frozen current-surface tail definition `-09-57a` already used — **5,930 band rows, 4.3868%
of the panel, D=49 / M=12 / 487 market-days** — so your population is comparable to a certified
measurement rather than a new one.

Characterise along at least these axes, and say which carry signal and which do not:

- **Market.** Is the tail concentrated in a few of the 12? Report the share per market with crossed
  intervals. Remember the F/C split and that F markets legitimately exclude pressure features.
- **Band position.** Where in the distribution — the centre band, the shoulders, the extremes?
  §4d found the tail **ex-ante identifiable at band granularity, not day granularity**; build on
  that rather than re-deriving it.
- **Season / stratum.** In-season vs out-of-season (§1b.4), and whether the concentration itself
  moves.
- **Time of day / cutoff.** Including but not limited to the 09:00–14:00 primary window.
- **Own-information weather state at the cutoff** — temperature level, trajectory, the repaired
  `-09-43a` inputs. **Own-information only (§0c).**

**Then answer the question that decides everything downstream: is tail membership PREDICTABLE
ex ante from own information alone?** Not "is it identifiable in hindsight" — predictable, with a
forward design that cannot see its own target.

## 3. P1 — turn the anatomy into direction

For whatever dominates, say concretely **what a candidate would look like** and what it would need:

- If the tail is **concentrated in a few markets** → is it a data-quality property, a station
  property, or a genuine forecast-difficulty property? The cheapest discriminator?
- If it is **band-positional** → this points at distribution *shape*, which is the axis §1c left
  open after recalibration closed. Note: **never weaken the serving floor**, and **global
  sharpening stays retired** — anything here must be conditional.
- If it is **weather-regime bound** → name the regime and the cheapest own-information proxy.
- If it is **none of these** — diffuse, unpredictable, everywhere — say so plainly. See §5.

**Rank by expected served improvement per unit of effort, with honest error bars on both axes.**

## 4. Method — and one thing NOT to do

- **Crossed date × market clustering; power/MDE before interpretation.** Cite the stratum, always.
- **Never pool across `2026-07-31`.** Use the sealed pre-boundary corpus.
- Forward/walk-forward or replay only. **No design that sees its own target.**
- **Own-information only.** Market price may define a study population (as in `-09-58a`); it may
  never enter a characteristic, a predictor, or anything that would be served (§0c).
- **Do NOT reuse `-09-57a`'s `0.0151764` as this mission's MDE.** That is the MDE for a *paired
  improvement* on the tail. **You are characterising, not improving** — derive whatever precision
  statement your own estimator needs.

**Campaign ledger:** this mission is **characterisation, not an accept/reject test of a candidate**,
so it **spends no decision** and must not score a candidate on C. State that explicitly in your
report, as `-09-58a` did when it closed slot 8 unused. If your work evolves into testing a
candidate, **stop and say so** rather than spending a slot unannounced.

## 5. What would falsify this mission

- **Tail membership is not predictable ex ante from own information.** Then no targeted candidate
  can ever be built for it, the 64.140% concentration is not actionable, and **every future
  "improve the tail" proposal is closed at once.** That is the most valuable outcome available here
  and it must not be worked around.
- **The tail is one or two markets.** Then this is plausibly an operational or station problem, not
  a modelling one — much cheaper than a model change, and it would redirect effort immediately.
- **The concentration is an artifact of the definition** — e.g. it tracks band count or row density
  rather than genuine loss. Say so; the 4.387%/64.140% headline would then need retiring, and four
  headline numbers were already retired in one day on 2026-08-09 for less.

## 6. Context you should not re-derive

- **Recalibration is closed** (§1c) — do not fit a mapping. Scalar isotonic is NO-GO.
- **Input completeness is not the lever** (`-09-44a`, ≤0.6% of the distance to parity).
- **Market-shrinkage controls are diagnostics, never candidates** (§1c, §0c).
- **`74.97%` is unciteable**; model-skewed quoting is retired (`-09-46a`).
- Nothing is reserved; `docs/operations/reserved-confirmation-window.md` wins over every other
  document.
- **Score anything fitted on its own training set first** (§5) — free, and it localises a broken
  objective instantly.

**Environment note:** the repo venv on that host points at a removed Python 3.11. The last two
missions used the bundled Codex 3.12 runtime successfully. Do the same; do not install anything.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Promote nothing, activate nothing, place no order, enable no
live trading, call no exchange or weather-provider endpoint.** Nothing under production `data/`. No
chain run, settlement, or loop restart. **Never weaken the serving floor.** The production release
store must stay empty. Fitting is authorized to a scratch root, stated explicitly; anything fitted
is **diagnostic, never a candidate**.

**Paid weather-provider access is unsupported.** Do not add credentials, required environment
variables, or any plan that depends on a paid weather source.

## 8. Branch and report

- Branch: `codex/workstation-anatomy-of-the-severity-tail-2026-09-59a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-severity-tail-anatomy.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
