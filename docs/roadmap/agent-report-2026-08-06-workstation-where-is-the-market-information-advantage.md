# Workstation market-information-advantage localisation — 2026-08-06

## Verdict

**CONCENTRATED, but no captured-signal lead: the market's resolution advantage is
detectably larger in Los Angeles, not at a common cutoff hour or weather regime.
The Los Angeles market is confident early and right, reaching a persistently correct
mode about nine hours before the served model. None of the already-captured,
cutoff-eligible signal families has a familywise-supported correlation with the
resolution failures. Aim the next investigation at Los Angeles-specific information
and market timing/provenance; do not globally sharpen, recalibrate, blend, or fit a
candidate from this result.**

Power precedes point interpretation. The selected Los Angeles-versus-complement
contrast has **99.23% power** at the predeclared retained full-resolution effect
`0.02441017232`, using the exact 2,000-replicate crossed refit sensitivity and the
12-market Bonferroni-t familywise critical value. Its exact interval remains wholly
positive: `+0.014034` `[+0.000736, +0.027333]`. The P0 not-powered stop therefore
does not fire for the selected slice.

No cutoff hour or canonical regime qualifies. Denver's fixed-map screen also has a
positive simultaneous interval, but its `+0.009442` point is below the predeclared
practical concentration margin `0.012205`; it was not selected or exact-refit and is
not a second finding.

No model was fit, no candidate was produced, no source was collected, and no provider
or market endpoint was called.

## Population, authority, and inference

This mission reuses the exact independently verified `-09-31a` roster and the
`-09-34a` materialized served-replay band rows. The predecessor evidence-manifest
SHA-256 is
`40bf8ea7f780602721abcc0ba1f62502d88437225747f0d08137e0f5c12cc8bf`;
the exact `band-score-rows.csv` SHA-256 is
`c6f4257cfbcb157f5d6ae748d5431c91b5a90a4f77b1b17f12aa156c6cf61316`.
No mutable ledger or reconstructed label population was re-admitted.

| Support | Value |
| --- | ---: |
| Target-date clusters | 50 |
| Market clusters | 12 |
| Promotion-countable market-days | 524 |
| Earliest hourly snapshots | 12,289 |
| Binary band rows | 135,179 |
| Target-date range | 2026-06-03 through 2026-07-30 |

The population contains `B` and `C` predecessor strata, and date multipliers are
drawn independently inside them while one market multiplier is shared. Every target
date is before the `2026-07-31` artifact-provenance boundary; nothing is pooled across
that boundary. Market-days are the deduplicated `(market, target_date)` roster already
admitted by the verified predecessor under `promotion_countable=True`, not ledger-row
counts.

The lane is mass-valid `served_replay_probability`; market Brier/decomposition uses
the captured raw market probability. Resolution is the exact market-stratified
CORP/isotonic Murphy component, with
`Brier = reliability - resolution + uncertainty`. The local estimand is:

> slice `(market resolution - served resolution)` minus the same gap in the slice's
> complement.

The broad screen freezes exact full-sample CORP maps, then uses 10,000 crossed
target-date × market exponential-multiplier replicates and a two-sided max-T 95%
interval within each dimension. Selection required all three before any P1 work:

1. a positive point of at least `0.01220508616`, half the retained full-resolution
   effect;
2. a dimension-familywise interval wholly above zero; and
3. at least 80% power at the retained `0.02441017232` effect.

Any selected slice then had to survive an exact weighted CORP refit in 2,000 crossed
replicates and a familywise Bonferroni-t interval. Los Angeles is the only slice that
passes both stages.

The retained positive controls reproduce before localisation:

| Stratum | Resolution gap | Retained `-09-34a` value |
| --- | ---: | ---: |
| B, in season | 0.0134452735 | 0.0134452735 |
| C, out of season | 0.0186386113 | 0.0186386113 |
| Combined descriptive point | 0.0166682638 | — |

## P0 — concentration versus uniformity

Los Angeles has `D=43`, `MD=43`, `999` hourly snapshots, and `10,989` band rows.
The 11-market complement has `D=50`, `MD=481`, `11,290` snapshots, and `124,190`
band rows.

| Estimand | Los Angeles | Complement | LA − complement | Familywise 95% |
| --- | ---: | ---: | ---: | ---: |
| Resolution gap | **0.029562** | 0.015527 | **+0.014034** | fixed-map `[+0.003245, +0.024824]` |
| Exact refit sensitivity | — | — | **+0.014034** | **`[+0.000736, +0.027333]`** |

The exact refit standard error is `0.003694`; power at the retained full-resolution
effect is `99.23%`. Los Angeles supplies 8.13% of band rows but 14.42% of the combined
resolution gap. Its above-complement excess is 6.84% of that pooled gap.

### Cutoff hour

The effective artifact cutoff surface is 07:00–20:00. The replay carries predawn
captures at the 07:00 artifact cutoff and post-20:00 captures at the 20:00 cutoff, so
there are 14 observed effective hours rather than 24 independently fitted hours.

No hour's simultaneous interval excludes zero in the positive direction. The largest
points are 20:00, gap `0.019014`, contrast `+0.003573`
`[-0.007565, +0.014710]`, and 18:00, gap `0.018685`, contrast `+0.002331`
`[-0.006559, +0.011220]`. There is no supported clock-hour target.

### Canonical weather regime

| Regime | Resolution gap | Slice − complement | Familywise 95% |
| --- | ---: | ---: | ---: |
| `early_morning` | 0.013048 | -0.005020 | [-0.010738, +0.000698] |
| `ramp_midday` | 0.014480 | -0.002735 | [-0.007273, +0.001803] |
| `late_day` | 0.017262 | +0.001389 | [-0.004288, +0.007066] |
| `lock_in` | 0.019014 | +0.003573 | [-0.005470, +0.012616] |

No regime interval excludes zero. The result is location-specific, not a common
forecast-cycle or intraday-stage defect.

## P1 — what distinguishes Los Angeles

Market probabilities are normalized only for entropy, mode confidence, and winner
mass; the P0 Brier/decomposition keeps the raw captured market probabilities.
Intervals below are crossed LA-minus-11-market-complement max-T intervals. Los
Angeles-only points contain one market cluster and are descriptive; the contrast gets
its market-cluster variation from the full crossed comparison.

| Market behavior | Los Angeles | Complement | LA − complement [95%] |
| --- | ---: | ---: | ---: |
| Normalized entropy | **0.2712** | 0.3618 | **-0.0906 [-0.1164, -0.0648]** |
| Mode confidence | **0.7499** | 0.6497 | **+0.1002 [+0.0727, +0.1277]** |
| Settled-winner probability | **0.6988** | 0.5629 | **+0.1359 [+0.0883, +0.1834]** |
| Mode accuracy | **81.98%** | 63.92% | **+18.06 points [+7.69, +28.43]** |
| Confident-and-correct rate | **44.84%** | 33.00% | **+11.84 points [+8.23, +15.45]** |

The served model is also more concentrated in Los Angeles than elsewhere—entropy
`0.3353` versus `0.4252`, mode confidence `0.6935` versus `0.6115`—but it is not
detectably more correct. Its Los Angeles-versus-complement winner-mass contrast is
`+0.0315` `[-0.0491, +0.1122]`, and its mode-accuracy contrast is `+2.48` points
`[-9.37, +14.32]`.

This is therefore not a slice where the market is merely less wrong. In Los Angeles
the market is both more confident and more often correct, while the model's extra
confidence does not bring extra accuracy.

### Convergence

Convergence is the earliest market-local capture hour whose mode is correct on that
row and every later retained hourly row; `24` means never. The confident version also
requires mode confidence at least 0.80 on every retained row from that hour onward.

| Persistent convergence | Los Angeles | Complement | LA − complement [95%] |
| --- | ---: | ---: | ---: |
| Market correct-mode hour | **7.12** | 11.40 | **-4.28 h [-6.92, -1.64]** |
| Model correct-mode hour | 16.42 | 16.75 | -0.34 h [-2.38, +1.70] |
| Market minus model hour | **-9.30** | -5.36 | **-3.95 h [-7.01, -0.88]** |
| Market confident-correct hour | **13.40** | 16.16 | **-2.76 h [-3.58, -1.95]** |
| Model confident-correct hour | 18.84 | 19.62 | -0.78 h [-2.71, +1.14] |
| Market minus model confident hour | **-5.44** | -3.46 | **-1.98 h [-3.88, -0.08]** |

The observable behavior is an early-convergence/timing advantage in Los Angeles.
This analysis cannot show whether the market has genuinely external information or
incorporates the same information faster; the P2 signal search below finds no
captured series that resolves that distinction.

## P2 — already-captured signal search

The signal list was sealed before correlations were opened: NBM probabilistic Tmax,
MRMS precipitation, marine context, ASOS one-minute, reanalysis/synoptic, and
multi-model spread. The response is the per-snapshot exact CORP calibrated-error
contribution whose pooled mean is the resolution gap. The association is Spearman
rank correlation after demeaning within effective cutoff hour for Los Angeles and
within market × cutoff hour for fleet. Reported intervals are max-T familywise across
all usable declared signals.

### Leakage and cutoff audit

All 524 predecessor `features.jsonl` files were hashed and joined on exact
`(market, target_date, snapshot_id)`. Feature capture time must match the scored
snapshot at identifier precision. A feature's own cutoff may be earlier than the
scored effective cutoff; it may never be later.

| Cutoff disposition | Snapshots |
| --- | ---: |
| Exact cutoff equality | 11,147 |
| Earlier, stale-but-leakage-safe feature cutoff | 822 |
| **Post-cutoff feature row excluded from every signal** | **320** |

The post-cutoff defect is real: some predawn rows carry a feature cutoff as late as
09:00 against a scored effective cutoff of 07:00/08:00. Those rows are preserved in
the audit, set unavailable for P2, and never imputed. Los Angeles contributes 25 of
the 320 exclusions. Maximum valid staleness is two hours.

### Coverage

- **Usable in Los Angeles:** six NBM signals (`D=32–33`, `N=253–776`), six
  multi-model-spread signals (`D=33–37`, `N=771–847`), and MRMS source lag
  (`D=35`, `N=824`).
- **ASOS one-minute:** all four declared fields are absent from the cutoff-bound
  feature tape. Raw files elsewhere cannot be substituted because they are not dated
  to these scored rows.
- **Marine context:** schema fields exist, but all four are null in Los Angeles; fleet
  support reaches only four markets, below the declared six-market crossed floor.
- **MRMS weather:** precipitation, rate, and convective-interruption values are all
  null; only source lag is populated.
- **Reanalysis/synoptic:** all six declared values are null on the exact population.

### Correlations

**No Los Angeles or fleet interval excludes zero after familywise correction.** The
largest Los Angeles point is NBM floor gap, `rho=+0.1785`
`[-0.0573, +0.4143]`, on `D=32`, `N=733`; the next is NBM standard deviation,
`+0.1610` `[-0.0760, +0.3980]`. The largest absolute fleet point is NBM P90 minus
forecast high, `-0.1484` `[-0.3392, +0.0424]`, on `D=34`, `M=11`, `N=3,411`.

Los Angeles intervals are target-date clustered with the market dimension degenerate
at one selected market. They are leads only, never crossed market-level decisions.
The fleet intervals have crossed date × market clustering, and they also cross zero.

The declared captured surface therefore supplies **no supported feature lead** for
the Los Angeles resolution failures. This is not evidence that every possible Los
Angeles signal is useless; it is evidence that the specifically named series are
either absent at the cutoff or unsupported on this corpus.

## Decision and next direction

The mission falsifies a uniform-deficit story. It also rules out a global hour/regime
repair and fails to identify a safe captured feature to model next.

The next separately commissioned work should distinguish two Los Angeles-specific
possibilities without fitting first:

1. the market receives external local information not present on the exact feature
   tape; or
2. the same public information reaches the market earlier than the model's
   cutoff-bound extraction/serving chain.

Useful evidence would be timestamped Los Angeles market-mode transitions joined to
source arrival/issue times, with a positive control that can explain the observed
07:00 persistent correctness. This report does **not** authorize ASOS backfill,
marine collection, feature activation, model fitting, sharpening, market blending,
or a Los Angeles candidate.

## What falsified or survived

- **Uniform across hour, market, and regime:** falsified by the powered Los Angeles
  contrast.
- **Not powered to localise:** false for Los Angeles; exact-refit power is 99.23%.
- **Common clock-hour/regime mechanism:** not supported; every simultaneous interval
  crosses zero.
- **Captured signal predicts failures:** not supported; every usable familywise
  interval crosses zero, and several named families fail the cutoff/population test.
- **Timing rather than information:** the market demonstrably converges earlier, but
  equality of underlying information is not established. The honest result is
  "Los Angeles early-convergence advantage, source unresolved."

## Evidence and independent verification

The ignored workstation evidence root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\market-information-advantage-2026-09-36a`.
It is not a production-host command path and is not assumed to exist in a clean
checkout.

Final evidence-manifest SHA-256:
`ccd9cf30814efc8b199b24870a3cb2187e3f21d8b82e2550a6056000f164d9fe`.

Independent verification SHA-256:
`b515347c2c614c1bc75f81899571c730bfd7f2aa0e182f56a5724473d2ca2865`. It independently checks the
sealed predecessor identity and support; retained B/C positive controls; Los Angeles
and complement exact resolution; the full 2,000-replicate selected-slice refit; P1
distribution and convergence points from raw band rows; 524 feature-tape hashes and
the 320 post-cutoff exclusions; all 26 P2 correlation points and max-T intervals; and
the absence of a familywise-supported signal.

## Repository verification, roll verdict, and actions not taken

Repository and roll verification are finalized in the binding commit after the
report-content commit. `git diff --check`, the documentation audit, and
`scripts\ops\roll_verdict.ps1` results are recorded there.

Only this Markdown report is changed:

| Changed file | Retained capture closures | Roll verdict |
| --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-06-workstation-where-is-the-market-information-advantage.md` | None; Markdown is outside snapshot, CLOB, observation-trigger, and CLOB-enrichment closures | `ROLL_VERDICT_PENDING` |

No source, test, config, artifact, schema registry, ledger, tape, release, pointer,
scheduler, task, or production `data/` file was changed. No model was fit or
retrained. No provider, collector, observation, market, or paid endpoint was called.
No production write, registration, capture restart, PR, merge, or master action was
performed.

## Production-host reproduction and acceptance commands

These commands use paths present on the production host. They verify the committed
handback, exact changed-file scope, documentation reachability, and mechanical roll
verdict. They do not pretend that ignored workstation evidence exists there.

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-where-is-the-market-information-advantage-2026-09-36a'
$report = 'docs/roadmap/agent-report-2026-08-06-workstation-where-is-the-market-information-advantage.md'

git rev-parse $branch
git show "${branch}:$report"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Expected changed-file scope is exactly the one Markdown report above and the expected
roll verdict is `ROLL_VERDICT_PENDING`.

Branch:
`codex/workstation-where-is-the-market-information-advantage-2026-09-36a`.

Base: `73366e5f67220719e4c5224ae847e00f026be8b1`.

Report-content commit: `REPORT_CONTENT_COMMIT_PENDING`.

No PR was opened and no merge was performed.
