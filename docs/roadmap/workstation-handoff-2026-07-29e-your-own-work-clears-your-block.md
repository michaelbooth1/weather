# Workstation handoff — 2026-07-29e: your own work clears your block

The warm tier you just built is the thing that unblocks your MM run. You do not need more disk
from me; you need me to land your branch, which is armed.

## Review verdict: merging

`codex/workstation-who-breaks-floor-2026-07-27g` @ `7232a896` is armed for the **01:15 quiet
window** (roll-sensitive: `io.py`, `schema_registry_recent_data.py`, and
`clob_order_book_tiering.py` are all in the capture loop closure).

What I checked, and why I am comfortable:

- **The PIT diff is a no-op refactor.** Every `14` becomes `PRODUCTION_CONTIGUOUS_WINDOW_DAYS =
  14` and `PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS = 7` relocates to the contract module. Values
  identical. Deriving the hot window from the contract rather than inheriting my guessed 30 is
  the right move and I am glad you did not just take my number.
- **`io.py` is purely additive** — new symbols only, no existing function touched.
- **`order_book_tape` has zero production callers**, so the new fail-loud path cannot hard-stop
  the chain. That was my main concern given the chain's blast radius.
- **The tiering step catches rather than raises**, so my 20 divergent folders will surface as
  `blocked_conflicting_tiered_pair` instead of killing the step. Mismatches are found in the
  first chunk, so there is no scan cost.

**You implemented the split-pair guard correctly.** `resolve_tiered_text` proving byte equality
before returning any iterator is exactly the "fail loudly, do not pick one" property I asked
for, and the comment naming the settlement-exclusion hazard shows you understood why.

## Your floor, quantified

I measured the eligible set on production:

| | folders | bytes |
| --- | ---: | ---: |
| eligible, older than the 30-day hot window | 192 | 24.7 GB |
| hot, inside the window | 372 | 67.5 GB |

At your measured 10.5x, applying `order_books.jsonl` reclaims **~22.4 GB (~20.9 GiB)**, and the
next `/MIR` propagates every byte of that to your mirror. Your shortfall is 12.6–17.7 GiB, so
this clears it — the low end comfortably, the high end by about 3 GiB.

That margin is thinner than I would like, which is the argument for the next families rather
than for you deleting anything else.

Note the second-order effect: 12 folders age out of the hot window per day, so once this is
running `order_books.jsonl` stops contributing to net growth entirely (~3.1 GB/day of rolling
reclaim against ~3.2 GB/day of production).

## How I am applying it, and why not all at once

Merge 01:15 → plan → **pilot apply on a single closed market-day (12 folders)** with receipts →
review in the morning → full 192-folder apply tomorrow night if the pilot is clean.

Your own report is explicit that the destructive tests stub the expensive path and that the
operator's production apply is the first real-data rehearsal. On canonical evidence, six days
from the lock, that earns a bounded first run rather than a 192-folder one.

## Mission 1: the repair path I am about to need

Your tiering step assigns `repair_from_canonical_raw_before_tiering` to a conflicting pair. I
have **20 folders** in exactly that state (all 12 markets on 2026-06-25, 8 on 2026-07-16), where
gz and plain are disjoint halves of one day.

Does that repair path exist and is it proven? If it does, tell me the exact command and what it
proves before replacing anything. If it does not, build it: rebuild the projection from
canonical `order_books.jsonl`, prove the rebuilt output covers the union of both partials
(20,680 = 18,238 + 2,442 for atlanta-june-25), and only then retire the two partials.

## Mission 2: the next families, in payoff order

You measured these; build them in this order unless your own numbers disagree:

| family | ratio | saved/day across 12 markets |
| --- | ---: | ---: |
| `clob_tokens.jsonl` | 74.2x | 0.96 GB |
| `replay_inputs.jsonl` | 12.2x | 0.60 GB |
| `variant_predictions.jsonl` | 13.1x | 0.56 GB |
| `order_books_summary.csv` | 11.3x | 0.50 GB |
| `clob_tokens.csv` | 72.2x | 0.50 GB |

`order_books_summary.csv` is the one your own MM run reads, so treat its reader proof as
load-bearing rather than routine.

## Guardrails

Unchanged. `data/` read-only on your host, single declared output root, topic branches only, no
PR/merge/master push. NOT-DONE first-class — your fail-closed stop and your refusal to land the
identity amendment without its equivalence gate were both right.

## Handback

`docs/roadmap/agent-report-<date>-workstation-item-325-warm-tier.md`, extended: the repair-path
answer first, then each new family with its reader proof and eligible/blocked verdict.

Context: streak **8/14**, lock ~2026-08-03. Production host 146 GB free. Git LFS bandwidth is
exhausted — see `docs/operations/git-lfs-policy.md`, do not delete `.git/lfs`.
