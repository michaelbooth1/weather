# Workstation handoff 2026-09-20a — rescue the PIT retrain lane

> **REVISED 2026-08-05, after this handoff was first published.** The original version of this file
> told you to extend the season window in `weather.sources.forecast_history` and collect into the
> forecast archive. **That instruction was wrong and is withdrawn.** A held branch already contains a
> purpose-built point-in-time training corpus that deliberately avoids the serving archive, and it
> already targets 2021–2025. If you started the original mission, stop and re-read from here. Nothing
> collected under the old instruction should be kept.

**Goal: rescue the better of two independently-built retrain lanes before it rots, and decide which
one survives.** We have been tracking the wrong one.

Branch from `origin/codex/workstation-consolidate-merge-queue-2026-09-01a`, refreshed onto current
`origin/master`. Branch name: `codex/workstation-rescue-the-pit-retrain-lane-2026-09-20a`.

## What was just discovered on the production host

`-09-01a` is named "consolidate merge queue" and was treated as a housekeeping branch. It is not. It
carries four substantive commits:

```text
a5247509  ops: add fail-closed all-market base retrain
9cb708c6  forecast: build point-in-time training corpus
5ae82294  retrain: bind base fleet to PIT forecast corpus
450f03c5  taker: enforce counterfactual tape retention
```

It contains `src/weather/sources/forecast_training_corpus.py` (1,536 lines) and
`docs/operations/PIT_FORECAST_TRAINING_CORPUS.md`, plus a 324-line binding of `base_retrain.py` to
that corpus with 174 lines of new tests.

**And it is a different lane from `-09-12a`, not an ancestor of it.** Verified:

| Check | Result |
| --- | --- |
| Does `-09-12a` contain `a5247509` (base retrain)? | **NO** |
| Does `-09-12a` contain `5ae82294` (PIT binding)? | **NO** |
| `source_payload.get("covered_years")` self-sizing defect on `-09-01a` | **0 occurrences** |
| Same defect on `-09-12a` | **1 occurrence** |

Two independent implementations of the first retrain exist. **The one we have been tracking in the
backlog (`-09-12a`) is the one carrying the self-sizing defect. The one we filed as housekeeping is
the one that does not.**

`-09-01a` is 59 commits behind master and last moved 2026-08-03. Its footprint is modest and mostly
additive — `model_features.py` +44, `nightly_retrain.py` +69, `forecast_history.py` +17,
`schema_registry_data.py` +25, `pooled_feature_assembly.py` +72, `storage_classes.py` +26. **It is
rescuable today and will not be rescuable indefinitely.**

## Why its corpus design is the right one — do not redesign it

`PIT_FORECAST_TRAINING_CORPUS.md` already states the contract, and it is better than what the
withdrawn instruction would have produced:

- The corpus is **training-only** and is "never discovered through
  `weather.sources.forecast_history.daily_path_for`." It is explicitly **not a serving fallback.**
  This matters: the serving archive is read live, and casual backfill into it is how the marine
  sidecar defect happened.
- **Stitched continuous-archive rows fail closed.** Empty issue identity fails closed. Target-year
  rows fail closed.
- Every target date must have exactly 24 local hourly rows with both `issue_time_utc` and
  `available_at_utc` at or before every feature cutoff.
- Immutable, content-addressed, atomically published under `corpora/<corpus_id>`; an existing
  identity is never overwritten.
- Its planner is already documented with `--years 2021,2022,2023,2024,2025` — **the population
  decided in `docs/operations/forecast-source-and-training-population.md`, independently arrived at.**

**Do not redesign this contract, do not soften its fail-closed rules, and do not make it reachable
from serving.**

## P1 — refresh it, and prove nothing was lost

Rebase or merge `-09-01a` onto current `origin/master`. 59 commits of drift is the whole difficulty
of this mission; treat it as the deliverable, not the preamble.

- Resolve every conflict in favour of **keeping both behaviours**, and list each conflict you
  resolved with one sentence on what you chose and why.
- The full suite must pass. Where a test changed meaning, say so explicitly — a silently rewritten
  assertion is how a rescue turns into a regression.
- `schema_registry_data.py` is contended by three other branches. Keep the change **purely additive**.

## P2 — adjudicate the two lanes

Produce a verdict, with evidence, on this exact question: **does `-09-01a` supersede `-09-12a`
entirely, or does `-09-12a` contain anything that must be salvaged?**

`-09-12a` uniquely carries `train_serve_feature_parity.py` — the standing control for this project's
dominant defect class, which already caught `wind_gust_kmh` and `wind_shift_3h_degrees` being dropped
at serve in all 12 markets. **That control is valuable and must not be lost** whichever lane wins.

Answer per component: base retrain step, PIT corpus, forecast training contract, train/serve parity
gate, candidate manifest handling. For each, say which branch's version survives and why. **Do not
merge the two lanes into a hybrid** — pick, justify, and name what gets ported.

If the answer is that `-09-12a` should be retired, say so plainly. Its branch ref is never deleted
regardless; agent reports live on unmerged branches.

## P3 — state what the gate now requires

With the PIT binding in place and the year set at 2021–2025, state plainly: how many cells the gate
requires, how many the corpus can currently prove, and therefore whether the first retrain PASSes,
BLOCKs, or BLOCKs pending collection.

**A BLOCK is a correct and useful answer.** The corpus module has no HTTP client by design — its
planner is permanently `dry_run_no_network` — so it is expected to have zero staged units today.
Confirming that the lane blocks precisely because nothing has been collected yet is exactly the
result that tells us the collector is the next mission and nothing else is in the way.

Do not tune anything to reach a PASS. Do not widen `covered_years`. Do not write a collector in this
mission — that is `-09-23a`, and it is deliberately separate because the corpus contract requires the
collector to be separately reviewed.

## Boundaries

- **Read-only with respect to production.** Register nothing, start no loop, mutate no scheduled
  task, write nothing under `data/` on the production host, never write to the mirror or
  `D:\weather-mirror`.
- **Do not collect, do not fetch, do not probe a provider.** The planner's `dry_run_no_network` mode
  is a safety property of this branch — preserve it. No HTTP client enters
  `forecast_training_corpus.py` in this mission.
- **Do not fit a model, produce a candidate, or promote anything.**
- Never read or expose `C:\Users\micha\.weathersync.cred`.
- `docs/operations/reserved-confirmation-window.md` wins over this document. **No dates are reserved
  today**; the window is armed but undated. Check the file when you run; do not declare, consume, or
  read a reserved date.
- Do not weaken the trusted observed-high floor, do not relax the promotion gate for `harvest_only`
  rows, do not change providers or paid tiers. **Free-tier Open-Meteo only; no paid API.**
- Concurrent missions own other files: `live_variant_settlement_scorecard.py`, `daily_refresh.py`
  (`-09-21a`); `model/feature_store.py` (`-09-22a`); `mm_*.py` (`-09-18a`). You will contend with
  `-09-21a` on `nightly_retrain.py` and `-09-22a` on `model_features.py` — both small and additive on
  your side. **Flag the overlap in your report; do not restructure either file.**
- Per-file roll verdict from retained capture-loop import closures, not the `SOURCE_PATTERNS` glob.
- No PR, no merge. Commit to the exact branch name above and push that branch only.
- Report to `docs/roadmap/agent-report-2026-08-06-workstation-rescue-the-pit-retrain-lane.md`.

## What would falsify this mission

- Finding that `-09-01a` cannot be refreshed without substantive rewrites would change this from a
  rescue to a re-derivation. **Say so early** — that is a decision for the operations host, not
  something to push through.
- Finding that `-09-12a` is in fact the stronger lane on components other than the self-sizing defect
  would reverse the premise. The lineage and defect counts above are verified; the *quality*
  comparison is yours to make and may go the other way.
- Finding that `-09-01a`'s PIT binding does not actually prevent candidate-supplied evidence from
  sizing its own gate — that the defect is absent by accident rather than by design — would mean
  neither lane is safe. That outranks everything else in this mission.
- Finding that the corpus contract is reachable from a serving path anywhere would contradict its own
  stated safety boundary and is a hard stop.
