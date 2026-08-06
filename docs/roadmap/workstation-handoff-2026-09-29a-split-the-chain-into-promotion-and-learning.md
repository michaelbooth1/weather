# Workstation handoff 2026-09-29a — split the chain into promotion and learning lanes

Written 2026-08-06 by the production agent.

## 1. Goal

**One blocked dependency stops promotion without also stopping learning** — so that a
transient source failure costs the day's promotion decision and nothing else, instead of
silently killing the day's model scoring, learning rollup and objective scoreboard.

## 2. Start from this — do not re-derive it

- **The blast radius is real and recurrent.** On 2026-07-27 a single transient WU timeout on
  one market stopped the chain at step 20 of 43, losing `promotion_refresh`, `daily_learning`
  and `market_beating_objective_scoreboard`. `scripts/ops/chain_recovery_run.ps1` exists
  solely because of that incident, and its docstring records it.
- **It happened again on 2026-08-06**, from a different cause: all 12 WU stations returned
  404 inside an 8-minute window, `public_wu_settlement_restore` blocked, and the chain
  hard-stopped at `settled_day_analysis_barrier`. 2026-08-05 was left unsettled fleet-wide.
- **`data/backtest/daily_learning.json` last wrote 2026-07-10** — 27 days stale as of this
  handoff. `rollup_freshness` reports it `STALE` every day and the chain proceeds anyway.
  Root cause has never been investigated; it is a P1 below.
- **`WeatherTrainingWindow` is an 18-second no-op every night.** From
  `data/logs/training_window.log`, 2026-08-06: window opens 01:00:02, `nightly_retrain`
  exits 0 at 01:00:08 with status `blocked`, capture restored by 01:00:20. It has been
  disabling capture, doing nothing, and restoring capture, nightly. The 01:00–04:00 window
  it reserves is therefore effectively free.
- **The chain already supports resume** via `--resume-from-step` plus
  `--settled-analysis-target-date`, and steps before the resume point keep their persisted
  results. Resume from the step that *failed*, never from the barrier that reported it — the
  barrier re-reads the earlier step's persisted BLOCK and blocks again.

## 3. Prioritised work

### P0 — the cheapest falsifying test, first

**Establish which steps are genuinely promotion-gating and which are purely observational**,
by reading what each step's output is consumed by. If it turns out that most post-barrier
steps really do depend on settlement truth for correctness — not merely for completeness —
then a lane split is the wrong shape and the answer is bounded per-step degradation instead.
**Report that finding and stop rather than building the wrong structure.**

The specific question to answer: does `daily_learning` (and the scoring steps feeding it)
require the *target day* to be settled, or can it run over the last known-settled corpus and
record the gap? If the latter, the split is sound.

### P1 — why `daily_learning` has not rolled up since 2026-07-10

Investigate and report. It is stale through 26 chain runs that reported all steps ok, which
means either the step is not running, is running and failing silently, or is running and
writing somewhere unread. **Do not repair it before reporting which of those it is** — the
distinction is the finding.

### P2 — the split

- **Promotion lane: fail-closed, unchanged semantics.** Never promote on incomplete
  evidence. This behaviour is correct and must not be weakened. `DELEGATION_CONTRACT.md` §2:
  do not relax a gate to make it pass.
- **Learning lane: fail-open, but records the gap explicitly.** A learning step that runs on
  a day with missing settlement must emit its own coverage/staleness field rather than
  silently producing a number that looks complete. **An unmarked partial result is worse than
  a refusal** — this project has retracted results for exactly that reason.
- The lane a step belongs to must be **declared in code**, adjacent to the step registry, and
  covered by a test that fails when a step is added without a lane.

## 4. Boundaries

`DELEGATION_CONTRACT.md` §2 applies in full. Mission-specific:

- **You own `src/weather/operations/daily_refresh*.py`** for this mission. No other in-flight
  branch holds them.
- **Do not touch `src/weather/model/model_features.py`** or
  `src/weather/model/free_source_feature_parity.py` — owned by `-09-22a`, `-09-26a`, `-09-20a`.
- **Do not touch `src/weather/reporting/source_gates/`** — concurrent mission `-09-28a` is
  adding a feature-coverage gate there and will register it into your learning lane as a
  follow-up, after this lands. Leave a registration seam; do not build the gate.
- **`src/weather/operations/nightly_retrain.py` and `base_retrain.py` are held by `-09-20a`.**
  The training-window no-op finding above is context, not licence to change the retrain.
- **Do not change `scripts/ops/chain_recovery_run.ps1`.** The production host modified it on
  2026-08-06 (`e144054b`) to add `-Refetch`; it is roll-free and already deployed.
- Roll sensitivity: `daily_refresh*.py` is **not** in the four capture closures, but verify
  per file against `runtime_identity.source_scope_files` and state the verdict per file.

## 5. What would falsify this mission

- **Most post-barrier steps genuinely require settled truth.** Then there is no learning lane
  to speak of, and the correct answer is per-step degradation with explicit coverage fields.
  Say so and do not force a split.
- **`daily_learning` turns out to be dead for a reason the split does not address** — e.g. it
  is unreachable, or its inputs have been absent since 07-10 independent of chain structure.
  Then fixing the chain shape fixes nothing, and the finding is the deliverable.
- **The fail-open lane cannot record its own gaps honestly** without the coverage plumbing
  that does not exist yet. Then this mission is blocked behind that plumbing and should say
  so rather than shipping a lane that quietly emits partial numbers.

## 6. Branch and report

- Branch: `codex/workstation-split-the-chain-2026-09-29a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-split-the-chain.md`

Report must satisfy `DELEGATION_CONTRACT.md` §5, including a **per-file roll verdict** from
the retained closures, and must state explicitly that no chain step was registered, no
production state was written, and nothing was merged.
