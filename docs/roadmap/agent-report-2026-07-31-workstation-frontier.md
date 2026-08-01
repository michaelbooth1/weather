# Workstation report — 2026-07-31: the post-floor frontier

## Outcome

The temporary observed-floor monitor is loud but non-fatal by default, the
post-fix excess-loss map is rebuilt from the accepted POST population, and the
inactive Celsius candidate entry points are ready. No preselection lock,
candidate fit, replay, promotion, pointer, serving, scheduler, capture, mirror,
ACL, PR, merge-to-master, or master-push action was performed.

The work started from exact `origin/master`
`ee63a44c395314815b5193cf8035eff8512aa49f`. The roll-sensitive monitor remains
isolated on `codex/workstation-floor-mass-2026-07-31e`; the decomposition and C
admission work are on `codex/workstation-frontier-2026-07-31f`.

## 1. Temporary monitor posture

Commit `dbc71eb0` on `codex/workstation-floor-mass-2026-07-31e` changes only the
monitor's blast radius, not its detection rules:

- default mode is `alert_only`;
- missing, malformed, duplicate, mismatched, or provenance-deficient evidence
  still produces `ALERT`/`BLOCK` with the full findings;
- default `ALERT`/`BLOCK` sets `hard_stop_pipeline = false` and is advisory to
  `settled_day_analysis_barrier`;
- `--fail-on-observed-floor-safety` on the daily refresh, or `--fail-closed` on
  the standalone monitor, restores the fail-closed hard stop;
- the daily report puts `OVER-FINAL FLOOR ALERT` before the step table, and the
  daily status and rollup retain enforcement mode, alerts, and blockers;
- the operations docs label this a deliberate, dated 2026-07-31 posture to be
  flipped after the production lock is secured.

Verification on that branch:

- observed-floor monitor plus daily-refresh tests: `117 passed, 4 subtests`;
- `compileall` over `src` and `tests`: pass;
- agent-doc audit: `PASS` over 18 agent files and 538 Markdown files;
- `git diff --check`: pass.

This branch was pushed. Integration timing remains with the operator because
`schema_registry_recent_data.py` is roll-sensitive.

## 2. Post-fix excess-loss decomposition

### Population and method

The declared output root is
`scratch/agent-runs/workstation-frontier-2026-07-31f`. The analysis consumed
only the previously accepted POST hard-floor outputs: 11,661 F-family
snapshots and 1,215 Toronto snapshots, or 12,876 snapshots / 141,636 band rows
in total. Inputs were hashed before and after and remained unchanged.

Primary weighting is snapshot-first: average band Brier within each snapshot,
then weight snapshots equally. Day-first is reported as a sensitivity. The
09:00–14:00 reliability/resolution split uses the repository's exact
market-stratified CORP isotonic Murphy identity. Model and pre-fix probability
simplexes were validated. Market YES quotes are independent binary contracts,
so the analysis correctly does not impose a market simplex.

### Where the remaining gap lives

Positive values are current-production model Brier minus market Brier; lower is
better. Hours are market-local.

| Family | Hours | Snapshots | Model | Market | Excess | Day-first excess |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| F | 00–02 | 1,537 | 0.077214 | 0.063174 | +0.014040 | +0.014582 |
| F | 03–08 | 3,106 | 0.076600 | 0.060265 | +0.016335 | +0.016791 |
| F | 09–14 | 2,761 | 0.069197 | 0.052353 | +0.016844 | +0.016676 |
| F | 15–17 | 1,384 | 0.033203 | 0.012546 | +0.020656 | +0.019842 |
| F | 18–23 | 2,873 | 0.026141 | 0.000076 | **+0.026065** | +0.026438 |
| C | 00–02 | 149 | 0.089185 | 0.065384 | **+0.023801** | +0.023477 |
| C | 03–08 | 349 | 0.087219 | 0.068676 | +0.018544 | +0.017442 |
| C | 09–14 | 294 | 0.066322 | 0.066480 | **−0.000157** | −0.001842 |
| C | 15–17 | 139 | 0.016570 | 0.017951 | −0.001381 | −0.001878 |
| C | 18–23 | 284 | 0.000323 | 0.000310 | +0.000013 | +0.000092 |

The raw F excess is still widest at 18–23 because market loss is almost zero,
but the adopted objective remains 09–14. Toronto's remaining deficit is
pre-dawn; Toronto now slightly beats market in the objective window and at
15–17. The day-first sensitivity preserves those conclusions.

### The 09:00–14:00 objective

| Scope | Model Brier | Market Brier | Gap | Reliability contribution | Resolution contribution |
| --- | ---: | ---: | ---: | ---: | ---: |
| F | 0.069197 | 0.052353 | +0.016844 | +0.002119 (12.58%) | **+0.014724 (87.42%)** |
| Toronto | 0.066322 | 0.066480 | −0.000157 | −0.000892 | +0.000735 |
| Combined | 0.068920 | 0.053713 | +0.015207 | +0.001829 (12.03%) | **+0.013378 (87.97%)** |

The largest mechanism is therefore the **resolution/information deficit:
0.013378 Brier, 87.97% of the combined 09–14 excess**. Reliability is secondary.
For Toronto, a reliability advantage is already large enough to offset its
smaller resolution deficit.

The stage split reaches the same stopping point:

- F pre-fix 09–14 excess was `0.018382`; the hard floor closed `0.001538`
  (`8.37%` of that excess), leaving `0.016844` (`91.63%`). The handoff's roughly
  2.2% figure is the different denominator of relative model-Brier improvement.
- Toronto pre-fix excess was `0.000619`; the floor closed `0.000776`, more than
  the entire prior deficit, leaving a `−0.000157` advantage.

The persisted source label `current_or_station_max_since_7am` accounts for
`0.016714` F-family Brier contribution, or 99.23% of the F net gap. It also
covers 99.49% of F snapshots, so this is an exposure attribution, not evidence
that the source itself caused the loss. The source split has almost no
contrasting population and should not be read as a new floor hypothesis.

The largest market-level 09–14 contributors within the F family are:

| Market | Snapshots | Within-market gap | Contribution to F gap | Share of F gap |
| --- | ---: | ---: | ---: | ---: |
| Dallas | 255 | +0.037111 | **+0.003427** | 20.35% |
| Chicago | 269 | +0.028614 | +0.002788 | 16.55% |
| Denver | 261 | +0.026103 | +0.002468 | 14.65% |
| San Francisco | 265 | +0.024290 | +0.002331 | 13.84% |

Thus the next target selected by the measurement is F-family morning
resolution/sharpness, with Dallas the largest named market contributor. It is
not another observed-floor redistribution. Toronto does not currently own the
primary-window deficit.

Reproducible outputs:

- `postfix_frontier_decomposition.json` — SHA-256
  `08069da72a7501054c64f19ff6b8a1a259fe3d4a13654a6ef35c667c7347d828`;
- `postfix_frontier_hourly.csv` — SHA-256
  `d61e42b955822fe299541611b1e1899da17958eaa2a514a10b5a1bf4bd24fc1e`;
- `postfix_frontier_sources.csv` — SHA-256
  `e98e89b61e3c345cc2a3ee029c59b2c8e576e09113f85803ee07074b6c6d64bc`;
- `postfix_frontier_markets.csv` — SHA-256
  `029aa693acf3b718e30b50e1f1a3da79a910d30ef64cd08e54746b48cb79fbcd`.

## 3. Inactive Celsius admission

Commit `d16e6af7` on `codex/workstation-frontier-2026-07-31f` adds the reviewed
control-plane entry points without scheduling or running them:

- the pooled trainer accepts `--family-unit C` only with the base
  `--objective band` lane and rejects F-family shadow variants;
- promotion refresh accepts `--family-unit C` and retains its existing required
  contained `--output-root`;
- family-secondary training accepts `C`, renders the correct family title, and
  requires explicit candidate-owned manifest, report, and nested artifact
  paths so it cannot fall through to F/live defaults;
- the nightly retrain runbook marks the lane inactive until the current lock is
  secured and records that it changes no serving or promotion permission.

The F-lane-unchanged proof checks both control-plane and selection behavior:

- pooled band invocation without `--family-unit` still dispatches `unit=F`;
- both other parsers still default to `F`;
- F selection still chooses only F markets, while C selection chooses only
  Toronto in the current registry fixture;
- focused CLI/family-secondary/promotion tests: `73 passed`;
- pooled feature-model regression tests: `57 passed, 44 subtests`.

No C prelock, fit, replay, artifact, release, or serving change was created.

Final frontier-branch verification:

- combined focused regression run: `130 passed, 44 subtests`;
- `compileall -q src tests`: pass;
- agent-doc audit: `PASS` over 18 agent files and 538 Markdown files;
- `git diff --check`: pass.
