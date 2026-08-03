# Workstation handoff 2026-09-01a — consolidate the merge queue, and stop the taker bleed

Run this now. **Rebase, consolidation and one small fix: no fit, no retrain, no candidate, no fresh
dates, no network.** `-08-16a` remains queued for 2026-08-05 04:30 and takes priority over this if
the timing collides.

## The problem this solves

Three held branches now each carry roll-sensitive files, and every merge rolls the capture loops:

| Branch | Roll-sensitive | Total |
| --- | ---: | ---: |
| `fix-maker-binding-race-2026-08-27a` @ `f1dc00ec` | 4 | 9 |
| `build-base-retrain-step-2026-08-26a` @ `71d18318` | 6 | 13 |
| `build-pit-forecast-corpus-2026-08-31a` @ `f2dbc71e` | 6 | 11 |

Roll-sensitive merges only run 01:00–04:00, roughly two a night. Three separate rolls is three
chances to disturb capture during the release build window. On 2026-08-01 we hit exactly this and the
answer worked: consolidating three branches into one rebased stack turned three risky rolls into one.
Do that again.

**Leave `fix-maker-binding-race-2026-08-27a` out of the stack.** It repairs a live defect — the chain
has been truncated since 2026-08-02, with `observed_floor_safety_monitor`, `clob_order_book_tiering`,
`promotion_refresh` and `daily_learning` all dark — so I want it merging alone and early rather than
waiting on the larger work. Two rolls total, not one, and that is a deliberate trade.

## 1. Consolidate

Rebase `build-base-retrain-step-2026-08-26a` and `build-pit-forecast-corpus-2026-08-31a` onto current
`master` @ `b13b2851` as **one stack**, in that order.

They are related work and I expect real overlap: the base-retrain step must eventually bind the PIT
corpus preflight, and both touch `schema_registry_recent_data.py`. Resolve it properly rather than
taking either side wholesale.

Give me a **conflict log**: every file that conflicted, what each side wanted, and which you took and
why. On the last consolidation the predicted overlap turned out to be stale branch ancestry rather
than real work, and I want to be able to tell the difference without re-deriving it.

Run the full suite on the combined tree and report the number.

## 2. Wire the binding both branches imply

`-08-31a` states the base-retrain branch "must bind this corpus preflight before fitting", and
`-08-26a` built a preflight with a forecast-coverage gate that currently fails at `0/N`. Those are
two halves of the same contract that have never been in one tree.

Connect them: the all-market base step must consume the corpus through
`--pit-forecast-corpus-manifest` and its preflight must fail closed when the manifest is absent,
unverified, or does not cover the planned market/date/cutoff matrix. **The ambient
`forecast_daily.csv` path must remain unreachable from the retrain lane.**

If wiring them reveals that either side's contract was wrong, say so — that is the most valuable
thing this mission can produce.

## 3. Stop the taker bleed

Separate from the model work, and it can be the last commit in the stack.

`data/taker_runs` is **74.7 GB** and growing ~2–3 GB/day. 55.3 GB of that is counterfactual
strategy-replay tape. `taker_bot_strategy_registry.py:165` declares
`counterfactual_retention_days: 14`, and `taker_bot_finalization.py:1879` writes a `retention` block
with `compaction_candidate_after_days` and a `recommended_compaction` string — **and no code reads
either back.** It is a label, not a mechanism. There is also no CLI flag to disable the tape, and
`taker_bot_daily_roll` passes no policy override.

Two things:

1. A way to disable counterfactual tape generation that the daily roll can actually pass. Default
   behaviour unchanged; I will decide separately whether to switch it on.
2. Implement the declared retention, or delete the declaration. **Do not leave a third dead knob.**
   If retention should be gated on the settled summaries existing, note that only **5 of 47** day
   folders ever got `settled_counterfactual_pnl.json`, so a rule gated on that will never fire —
   propose something that actually runs.

The operator has already approved deleting the existing 55.3 GB; that is my action on this host, not
yours. Yours is to stop it coming back.

## What I want back

1. The consolidated stack, rebased on `b13b2851`, with the conflict log and full-suite count.
2. The corpus/preflight binding, and anything it revealed about either contract.
3. The taker retention fix.
4. The complete roll-sensitive file list for the stack, so I can size the single roll.
5. Anything you think should merge separately rather than in the stack, with your reason.

## Sequencing

The release build window is open. **Do not touch the release path, the parity gate, or serving.**
Nothing here merges until I run it in a quiet window, and the maker fix goes first and alone.

## Constraints — unchanged

- Rebase onto `master` @ `b13b2851`.
- **No network access. No provider call.**
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.**
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache. Do not
  delete anything under `data/`.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- **Never rewrite published history.** Rebasing your own unmerged topic branches is fine; the
  originals must remain intact on origin so I can diff against them.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the consolidated branch under a new name — do not force-push over the three originals — and
report the branch and commit. The conflict log is the artifact I will actually read before arming the
merge.
