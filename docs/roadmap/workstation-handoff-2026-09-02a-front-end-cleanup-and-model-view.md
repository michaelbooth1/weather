# Workstation handoff 2026-09-02a — front-end cleanup, and a UI you can see the model in

Run this now. **UI only: no model change, no serving change, no fit, no retrain, no candidate, no
fresh dates, no network.** This runs in parallel with the model track and must not touch it.
`-08-16a` remains queued for 2026-08-05 04:30 and takes priority.

## What already exists — I inspected it, so don't rediscover it

Streamlit **1.57.0**. Launcher `scripts/launch/start_weather_dashboard.ps1` (port 8501, headless,
opens `?market=ops`, logs to `data/logs/streamlit_*.log`).

```
app/streamlit_app.py     3 KB   thin router, query-param driven
app/table_utils.py       1 KB
app/views/overview.py       19 KB   2026-07-21
app/views/single_market.py  31 KB   2026-07-12   <- the model-facing page
app/views/market_making.py  24 KB   2026-07-12
app/views/operations.py      6 KB   2026-06-22   <- oldest, most stale
app/views/history.py         5 KB
app/views/roadmap.py         1 KB
```

`tests/app/` — 6 files, **25 tests, all passing in 3.05s**. `app/AGENTS.md` already sets the rules:
thin router, bodies in views, domain logic stays in `weather`, preserve query params, no import-time
network calls, Arrow-safe tables, `AppTest` coverage for visible behaviour. **Follow it; do not
rewrite it to suit the new work unless you can say why.**

`single_market.py` already renders Model View, Model Explanation, Top-Bucket Deep Dive, Intraday
Bucket Transition Risk, Late-Day Extension Risk, Closest Historical Analogs, Source Freshness, Source
Signals, Remaining Forecast, and an Odds Timeline.

**This is not a greenfield build. It is a cleanup and one significant addition.**

## 1. The addition: make the pipeline visible

The operator wants to *look at the model*. The single most useful thing you can show is **where the
centre moves, stage by stage** — because that is the question this project has spent a month on, and
the machinery to answer it already exists and is not surfaced anywhere.

`DistributionPipelineState` (`model_distribution.py:92`) already records named stage snapshots via
`snapshot()` and `snapshot_normalized()` — `{kind}_feature_model`, `feature_blend`, and others
through prior, calibration, floor and band conversion. `model_presentation.py:104` already has
stage-aware presentation helpers.

Build a view that shows, for a chosen market and cutoff hour:

- each pipeline stage's distribution, in order, as it actually ran;
- the **centre at each stage**, and the delta each stage applied;
- where the **trusted observed-high floor** binds, and how much mass it truncates;
- the final served distribution against the market's implied distribution, side by side.

The point is that someone looking at it should be able to answer "which stage moved the centre, and
by how much" **without running a replay**. If a stage is absent for a given row, show it as absent —
do not interpolate, and do not hide it.

Consume the existing pipeline state. **Do not reimplement any stage, do not recompute a distribution
in the view, and do not change `model_distribution.py`.** If the stage data you need is not reachable
from the serving result without a model change, stop and report exactly what is missing rather than
reaching into internals.

## 2. The cleanup

**`operations.py` is from 2026-06-22 and predates most of the ops surface it claims to show.** Since
then we grew `scripts/ops/streak.ps1`, `scripts/ops/status.ps1`, the capture streak clock, the
release-admissibility clock, `data/alerts/MORNING_BRIEFING.md`, and `data/backtest/daily_refresh_status.json`.
Make that page tell the truth about the host as it is now. The two clocks and the capture streak are
the things actually worth seeing.

Beyond that, use judgement — you have read more of this UI than I have. I am specifically **not**
handing you a defect list, because I want to know what you find. Candidates I would look at:
dead code paths, views that assume pre-floor-repair behaviour (the serving floor defect shipped
2026-07-31), duplicated table logic that belongs in `table_utils.py`, silent `except` blocks, and any
place the UI would render a stale artifact as though it were current.

Report what you changed and why. **Do not do a stylistic rewrite** — this is a working app and churn
costs review time.

## 3. The roll-sensitivity question

`app/**/*.py` is in the capture supervisor's `SOURCE_PATTERNS`, so **every UI commit currently rolls
the capture loops** — the fleet restart that gates all our merges into a 01:00–04:00 window. That is
a large tax on front-end work that is supposed to run in parallel.

I checked: the only importer of `app.*` anywhere under `src/` is
`python_runtime_audit.py:414`, inside an audit function. No capture loop imports it.

**Investigate and propose — do not implement.** Can `app/**` come out of `SOURCE_PATTERNS` so UI work
stops rolling the fleet? What would still need to trigger a roll, and what breaks if the runtime
audit's import is no longer covered? If the answer is that it must stay roll-sensitive, say so and
explain why — that is a useful answer too.

This one is worth getting right: it changes the cost of every future UI change.

## What I want back

1. The pipeline/model view, with `AppTest` coverage, on a branch off `master` @ `db1f10e1`.
2. The cleanup, with a list of what you found and what you changed.
3. Your `SOURCE_PATTERNS` recommendation, with reasoning — proposal only.
4. Full `tests/app` count, plus the full-suite count if you touched anything outside `app/`.
5. Anything in the UI that is quietly wrong about the model as it stands today. That is the most
   valuable thing you could find here, and it is why I want fresh eyes on it rather than a rewrite.

## Sequencing

Parallel to the model track. **Do not touch `src/weather/model/`, the release path, the parity gate,
serving, or anything the model missions are holding.** If a UI need requires a model change, that is a
finding to report, not a change to make.

## Constraints — unchanged

- Base on `master` @ `db1f10e1`.
- **No network access.**
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.** Use fixtures for view tests; do not build UI tests on reserved dates.
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache. Do not
  delete anything under `data/`.**
- **Never weaken the trusted observed-high floor** — including displaying anything that implies it
  should be relaxed.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Include a short note on what the new view
shows and how to reach it, so I can launch it and look without reading the diff first.
