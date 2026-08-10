# Workstation handoff 2026-09-63a — run decision 10's B-only screen

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**This is a real GO/NO-GO on the last remaining lever, and it spends NO α.**

## 1. Everything is now in place except the answer

| | |
| --- | --- |
| Protocol | `docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json`, SHA-256 `336150be…` — **frozen, do not edit** |
| Amendment | `…-amendment-A1.json`, SHA-256 `549e26a3…` — quantile `3.0233414 → 3.1098893`. **Irrelevant to this mission**; it governs the C interval you will not build |
| **Features** | **`docs/roadmap/pit-lead1-daily-features-2026-09-61a.csv`, SHA-256 `60b450f1dd1ee575acde86607d179ae0cae68ddee541feef664923bd62b71ac8`** |
| Coverage | `-09-62a`: C primary calibrated, thin tail short, B conservative |

**The features are in the repo because they had to be.** The staged corpus is 1,645,056 rows across
two roots on the production host, `data/` is gitignored, and you hold no copy. The protocol uses one
lead and one daily window, so the whole feature set is **58 dates × 12 markets × 12 fields = 8,352
numbers**. `tools/research/build_pit_feature_extract_09_61a.py` collapsed it, and the gate it
enforces passed: **116,928 hourly values consumed, 0 missing, 0 duplicate, 0 non-finite, 0
provenance violations**, every row `fixed_lead_day_offset` / `open_meteo_previous_runs`.

**Verify the hash before you use it.** The repo pins `eol=lf`, so it reproduces byte-for-byte.

### Two things about that file that will bite you if you skip them

1. **It is NOT standardized, deliberately.** The protocol requires B-only within-market scaling
   **recomputed inside every chronological fit and bootstrap refit**. Precomputing it would leak C
   into the scaling and silently break the design. Scale it yourself, from B only, every time.
2. **`temperature_2m` is fahrenheit in 11 markets and celsius in Toronto.** Within-market
   standardization makes that harmless *for the fit*, and the protocol's Celsius-equivalent
   conversion is therefore cosmetic here — but **pooling raw temperature across markets would be
   catastrophic**. Every other field is Open-Meteo `native` and uniform. Per-market units are in
   `…-manifest.json`; unit consistency across both staging segments was verified (0 violations).

## 2. Your job: the B-only screen, exactly as frozen

Execute `B_only_screen_before_C_is_accessible` from the protocol, unchanged:

- Fit the 12-coefficient exponential tilt `q[b] ∝ p[b]·exp(r[b]·η)` on **in-season B only**,
  `λ=0.01`, no intercept, one deterministic run from the zero vector, market-day-equal weights.
- **Gate 1:** full-B fitted candidate beats the incumbent on **total B Brier**.
- **Gate 2:** the **13-date expanding window** — fit on the first 10 of B's 23 sorted dates, score
  the 11th, expand by one, through date 23 — beats the incumbent on **exactly the same OOF rows**,
  recomputing B-only scaling and β at every step.
- **Gate 3:** provenance, feature coverage, convergence (`‖∇‖∞ ≤ 1e-8`), mass within `1e-12`,
  incumbent-zero bands stay exactly zero, serving floor untouched.

**Failure of any gate closes decision 10 unused.** Report the failed gate and **stop**. Do not tune
λ, swap a feature family, add a lead, or retry from a different start. `-09-60a` is the precedent
and it is the behaviour that makes this campaign worth anything.

## 3. THE LINE YOU MUST NOT CROSS

**Filter to stratum B before you materialize anything.** The paired band file carries both strata.
`-09-62a` showed the discipline: it read only the columns it needed and said so.

> **Do not read C outcomes, C market probabilities, or C candidate probabilities. Do not compute a
> C endpoint, a C MDE, a bootstrap draw, or the clone control.** The first computation combining
> candidate-dependent C state with any C outcome or market price **spends decision 10 — including a
> failed or partial attempt.** This mission must end with decision 10 still unspent, whichever way
> the gates fall.

Fitting on B, scaling on B, and the B-only screen are explicitly α-free. Nothing else here is.

## 4. What a good report says

- Both Brier comparisons, with support, **and the incumbent's own numbers beside them** — not just
  a delta.
- **The fitted β vector, and what it says about the mechanism.** The hypothesis is that a scalar
  daily-high forecast omits whether target-day heating is radiative, cloud-limited, ventilated,
  convective, precipitating, or evaporation-limited. **If the coefficients contradict that story
  while still improving Brier, say so** — that is the difference between a result and a fluke.
- The expanding-window curve date by date, not just its total. A single date carrying the win is
  something we need to see.
- Convergence diagnostics and every safety check, stated as numbers.

**If the screen passes, do not celebrate it as an improvement.** B is the training stratum; §1d
puts its MDE at ~1% of gap and `-09-62a` measured its intervals as *conservative*, not sharp. A B
pass earns exactly one thing: the right to open C under decision 10, later, deliberately.

## 5. What would falsify this mission

- **Gate 1 fails** → the mechanism does not exist even on its own training data. `-09-60a` died
  here, for free, and that was the campaign working.
- **Gate 1 passes, gate 2 fails** → in-sample fit only. Report it as such; it is not a partial win.
- The feature extract's hash does not reproduce → **stop and say so**, do not proceed on a file you
  cannot verify.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Never pool across `2026-07-31`** (anchor `b77cfbed`) — the
extract already ends `2026-07-30`, keep it that way. Promote nothing, activate nothing, place no
order, enable no live trading, call no exchange or weather-provider endpoint. Nothing under
production `data/`. No chain run, settlement, or loop restart. **Never weaken the serving floor.**
Paid weather-provider access is unsupported. These fields are **own information** under §0c —
third-party forecast output, never the benchmark.

**α accounting must be unchanged on return: 7 of 20 spent, 13 available, decision 10 allocated and
UNSPENT.** State that explicitly in the report.

**Environment:** the repo venv on that host points at a removed Python 3.11; use the bundled Codex
3.12 runtime. Install nothing.

## 7. Branch and report

- Branch: `codex/workstation-run-the-b-only-screen-2026-09-63a`
- Report: `docs/roadmap/agent-report-2026-08-19-workstation-b-only-screen.md`
- Commit your fitting script and seed so the numbers reproduce.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
