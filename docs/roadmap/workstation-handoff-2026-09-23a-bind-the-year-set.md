# Workstation handoff 2026-09-23a — write the authorized PIT collector

> **REVISED 2026-08-05 before first dispatch.** An earlier draft of this file asked you to repair the
> `covered_years` self-sizing defect on `-09-12a`. That draft is withdrawn: `-09-01a` is a separate,
> better retrain lane that does not have the defect, and `-09-23a` has been repurposed to the one
> piece that lane is genuinely missing. **Do not start this mission until `-09-20a` has landed** — it
> depends on the refreshed branch.

**Goal: write the collector that the PIT training corpus was deliberately built without.** The corpus
module has a planner, a stager, a resume ledger and a materializer. It has **no HTTP client, on
purpose** — its own contract says a collector may submit response bytes "only after an immutable plan
exists and provider semantics have been probed," and only under separate review. This mission is that
separate review.

Branch from `codex/workstation-rescue-the-pit-retrain-lane-2026-09-20a` once it is accepted. Branch
name: `codex/workstation-write-the-pit-collector-2026-09-23a`.

## The authority you are working under

`docs/operations/forecast-source-and-training-population.md` is canonical and already answers the two
questions that stopped `-09-16a` and `-08-28a`:

- **Free tier of Open-Meteo. No paid API, ever**, without a new dated operator decision.
- Collection through the existing Previous Runs integration is **authorized by the repository owner**.
- **The training population is 2021–2025.** Decided. Do not re-open, widen or narrow it.

If you find yourself about to halt on sourcing or licensing, you have hit the exact failure mode that
file exists to prevent. Continue.

## What already exists — build to it, do not around it

`src/weather/sources/forecast_training_corpus.py` gives you the whole skeleton: `build_plan`,
`verify_plan`, `write_immutable_plan`, `_request_by_hash`, `inspect_staged_unit`, `stage_response`,
`resume_ledger`, and a `failure_ledger.jsonl`. Each collection unit is keyed by the plan's request
hash. `stage_response` records allowlisted HTTP metadata, retrieval timestamp, response SHA-256, byte
and row counts, validation result, and issue/run evidence.

**Your collector's only job is to fetch bytes and hand them to `stage_response`.** It does not
validate, it does not materialize, it does not decide coverage, and it does not write into
`corpora/`. Every one of those already exists and already fails closed.

Preserve the safety boundary exactly: **`forecast_training_corpus` itself stays network-free and its
planner stays `dry_run_no_network`.** The collector is a separate module that imports it. If you find
yourself adding `requests` to that file, you have taken a wrong turn.

## P1 — probe the provider semantics before collecting anything

The contract requires provider semantics to be probed before staging. Do that first, on **one market
and one year**, and report before going wider:

- What `issue_time_utc` and `available_at_utc` does Previous Runs actually return, and does every
  target date get exactly 24 local hourly rows?
- Does the issue evidence satisfy the corpus's acceptance rule, or does it need a documented mapping?
- Confirm on real responses that stitched continuous-archive rows are distinguishable and **do** fail
  closed. That rule is the reason this corpus exists; verify it empirically rather than trusting it.

If the provider's semantics do not satisfy the contract, **stop and report.** Do not relax the
contract to fit the provider — that inverts the entire point of the corpus.

## P2 — collect, resumably and politely

Only after P1 passes, collect 2021–2025 for all 12 markets.

- **Resume is a first-class requirement**, not a nicety. Use the existing resume ledger; a unit whose
  receipt, byte count and raw-response hash still verify must be skipped, not refetched.
- Pace the requests. A polite collector is the condition of continuing to have a free source. Report
  request count, wall time, throttling and any non-200 response.
- **Zero-row or invalid units are failures**, recorded in `failure_ledger.jsonl`. Do not retry them
  into apparent success; report them.
- Sequence it: one market end-to-end first as a sizing measurement, then stop and report bytes, time
  and request count before the remaining eleven.

## P3 — materialize and state the coverage

Run the existing `materialize`, and report what it says. Materialization requires **every** planned
market/year request; a partial build must never enter `corpora/`. If it blocks, the blocking reason
is the deliverable.

Then answer the question the retrain will ask: **is the PIT matrix complete for 2021–2025 across all
12 markets, and if not, exactly which cells are missing.**

`class_support` is expected to be tight in the severity tail at five years — Dallas 108 F, Denver
101–102 F, Houston 103–104 F, Seattle 95 F. **If it cannot clear, do not widen `covered_years`.** The
decision record forbids exactly that and names observation history — labels, METAR/ASOS, GHCNh, which
reach back further than 2021 — as the next place to look. Report it; do not route around it.

## Boundaries

- **Read-only with respect to production.** Register nothing, start no loop, mutate no scheduled
  task, write nothing under `data/` on the production host, never write to the mirror or
  `D:\weather-mirror`. Collect into your own clone.
- **Do not commit the collected corpus.** Never add `lfs: true`. The deliverable is the collector,
  the probe findings, the coverage report and the exact reproduction command.
- **Free tier only.** No paid provider, no paid tier, no new credentialed endpoint, no credential of
  any kind. Never read or expose `C:\Users\micha\.weathersync.cred`.
- **Do not make the corpus reachable from serving.** It is training-only and must stay undiscoverable
  through `forecast_history.daily_path_for`.
- **Do not fit a model, produce a candidate, or promote anything.**
- `docs/operations/reserved-confirmation-window.md` wins over this document. **No dates are reserved
  today**; the window is armed but undated. **Check the file when you run — do not assume it is still
  empty** — and exclude any reserved date from collection and from the coverage report.
- Do not weaken the trusted observed-high floor, do not relax the promotion gate for `harvest_only`
  rows, do not change providers or paid tiers.
- Per-file roll verdict from retained capture-loop import closures, not the `SOURCE_PATTERNS` glob.
- No PR, no merge. Commit to the exact branch name above and push that branch only.
- Report to `docs/roadmap/agent-report-2026-08-06-workstation-write-the-pit-collector.md`.

## What would falsify this mission

- Finding that Previous Runs cannot supply issue evidence meeting the corpus contract would mean the
  corpus cannot be filled from this source. That is a major finding and outranks collecting anything.
- Finding that the free tier throttles below a usable rate for 60 market-years would make this a
  multi-day collection rather than a mission. Report the measured rate; do not push through it.
- Finding that `stage_response` or `materialize` needs modification to accept legitimate data would
  mean the contract and the provider disagree. **Report the disagreement; do not edit the contract to
  end it** — that contract is the only thing standing between the retrain and stitched evidence.
- Finding that the corpus materializes but `class_support` still blocks would move the problem to
  observation history and close this mission with a BLOCK. That is a legitimate, useful outcome.
