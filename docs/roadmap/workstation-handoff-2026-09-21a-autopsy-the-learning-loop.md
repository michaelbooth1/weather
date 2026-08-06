# Workstation handoff 2026-09-21a — autopsy the learning loop

**Goal: find out why no candidate can ever activate, and whether it fixes itself at release #1.**
`nightly_retrain_status.candidate_release` has been `{"activation": "NONE", "status": "BLOCK",
"reason": "captured_input_replay_parity_blocked"}` for weeks. Whatever the first retrain produces, it
lands into a gate that is currently refusing everything. We are about to spend a month of work on a
candidate that cannot be promoted.

Branch from refreshed `origin/master`. Branch name:
`codex/workstation-autopsy-the-learning-loop-2026-09-21a`.

## The death cluster — measured on the host 2026-08-05

Everything that measures or advances the model died inside a three-week window, and nothing has
replaced it:

| Artifact | Last written | Age |
| --- | --- | --- |
| `data/backtest/model_history_cache.json` | 2026-06-25 | 41 days |
| `data/backtest/proper_scoring_reliability_scorecard.json` | 2026-07-09 | 27 days |
| `data/backtest/daily_learning.json` | 2026-07-10 | **27 days; `nightly_retrain_status.daily_learning` is `{}`** |
| `artifacts/models/hgb/*.pkl` | June 10–13 | the model has not changed in 8 weeks |
| `artifacts/releases/` | — | empty |

`-09-19a` already solved one of these: `model_history.py` had no CLI and was only ever invoked by
opening a Streamlit view. **That is one answer, not the answer.** `daily_learning` and the parity
gate are separate producers and need their own diagnosis.

## P0 — test the cheapest hypothesis first, before building anything

`captured_input_replay_parity` blocks when `compared_rows == 0`, raising `no_comparable_rows` at
`src/weather/reporting/scorecards/live_variant_settlement_scorecard.py:2704`: *"served and replay
inputs contain no one-to-one comparable rows."* It is not reporting a disagreement between served and
replayed probabilities. **It is reporting that it could not pair a single row.**

`-09-19a` established, in the same module, that served rows on this pre-release host carry blank
`release_id` and `release_identity_status=research_unbound_non_countable`, and that
`live_variant_settlement_scorecard.py:676-677` correctly requires an explicit immutable release ID.

**The hypothesis to test first: both failures are the same missing release binding, and both clear
when release #1 activates.** If that is true, this is not a defect at all — it is two gates correctly
refusing to certify an unbound research host, and the correct action is to do nothing and let the
release fix it.

Test it directly. Find the join key `_parity_key` pairs on, and determine whether the served side is
empty, the replay side is empty, or both are populated but keyed incompatibly. **Name which of the
three it is.** That single fact decides whether the rest of this mission is a repair or a note.

Do not fix anything until you have answered it. If the answer is "clears at release #1", say so,
prove it, and stop — that is the most valuable possible outcome of this mission and it costs a day
rather than a month.

## P1 — `daily_learning` has been dead for 27 days while the chain reported success

`daily_learning.json` stopped on 2026-07-10 and `nightly_retrain_status.daily_learning` is an empty
object, yet the daily chain has continued to report its steps as ok. It carries `retrain_plan` and
`experiment_queue` — the objects that decide *what we try next*. With it dead, the project has had no
automated research agenda for a month.

Establish, in this order:

1. **Which step produces it**, and whether that step is still running at all.
2. **Whether it fails, or silently no-ops.** A step that writes nothing and reports ok is a worse
   defect than a step that fails, and it is the shape of every other failure in this cluster.
3. **Whether the reported chain status can distinguish the two.** If it cannot, that is the finding —
   the chain's success reporting is not evidence of work, and we have been reading it as if it were.

Note the two known chain hazards so you do not misattribute: a maker scoring race has truncated
stage A step 9 onward since 2026-08-02, and the chain is fail-closed such that one transient timeout
hard-stops the day. Neither explains a July 10 stop. **Do not stop at "the chain was truncated."**

## P2 — is there one root cause, or four?

Four independent producers died within about three weeks of each other, and coincidences of that
shape usually are not. Look for a shared dependency: a schema version bump, a moved or renamed path,
an admission bar that tightened, a settlement-format change, a corpus that stopped being written.

If it is four unrelated causes, say that — a negative answer here is worth having, because it changes
how we treat the next silent stop. **Do not manufacture a unifying story that the evidence does not
support.** Report what you can demonstrate and label the rest as hypothesis.

## P3 — the standing defect class

Every failure above shares one shape: **a producer stopped, and nothing noticed.** The dashboard
cache went 41 days stale, `daily_learning` 27 days, the parity gate blocked indefinitely, and the
chain kept reporting success throughout.

If, and only if, P0–P2 leave time, propose the smallest mechanism that would have caught this —
freshness assertions on the artifacts that gate promotion, surfaced where they are already read.
**Propose it; do not build it, and do not register anything.** A design paragraph is the deliverable.
We do not need a monitoring system; we need the four dead things to be alive and to complain when
they die again.

## Boundaries

- **Read-only with respect to production.** Register nothing, start no loop, mutate no scheduled
  task, write nothing under `data/` on the production host, never write to the mirror or
  `D:\weather-mirror`.
- Never read or expose `C:\Users\micha\.weathersync.cred`.
- `docs/operations/reserved-confirmation-window.md` wins over this document. **No dates are reserved
  today**; the window is armed but undated. Check the file when you run; do not read, enumerate,
  replay or score a reserved date.
- **Do not relax a gate to make it pass.** Both gates in P0 may be behaving correctly. Turning a
  correct refusal into a green check is the single worst outcome available here — it is precisely
  how a leakage-driven "win" was reported as real once already. If a gate is right, the deliverable
  is the sentence explaining why, not a patch.
- Do not weaken the trusted observed-high floor, do not relax the promotion gate for `harvest_only`
  rows, do not change providers or paid tiers.
- Per-file roll verdict from retained capture-loop import closures, not the `SOURCE_PATTERNS` glob.
- Another mission is running concurrently on `src/weather/sources/forecast_history.py` and
  `src/weather/collection/forecast_archive.py`, and a maker-producer branch owns
  `src/weather/market/mm_*.py` and `src/weather/schema_registry_data.py`. **Stay out of all of them.**
  If your diagnosis requires touching one, report the requirement instead of taking the file.
- No PR, no merge. Commit to the exact branch name above and push that branch only.
- Report to `docs/roadmap/agent-report-2026-08-06-workstation-autopsy-the-learning-loop.md`.

## What would falsify this mission

- Finding that the parity block clears automatically at release #1 makes this a note rather than a
  repair — **that is the cheapest and most likely outcome, so test it first and stop there if true.**
- Finding that `daily_learning` is intentionally disabled would mean the loop was turned off rather
  than broken; find the decision that turned it off and report it rather than turning it back on.
- Finding that the four artifacts died of four unrelated causes would kill the single-root-cause
  premise. Report that plainly rather than forcing a connection.
- Finding that any of these producers is in fact current somewhere else on disk would falsify the
  staleness table above. The paths inspected are named; show the counter-example.
