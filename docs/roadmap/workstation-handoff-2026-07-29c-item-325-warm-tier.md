# Workstation handoff — 2026-07-29c: item 325, warm tier first

Runs **after** `-29b` (clear your disk, then finish the MM analysis). This is the next build,
and the operator has chosen it as the answer to our disk horizon.

## Why the warm tier, and not the scope order in the item

Item 325 lists sync-splitting and archive offload first, and names a blocking prerequisite:
`WeatherDataMirror` runs `robocopy /MIR`, so the mirror is a replica, not an archive, and
pruning locally would delete the offloaded copy. That is real, it is mine to fix, and it gates
every *deletion*.

**The warm tier needs none of it.** Compressing closed market-days in place is not a deletion:
no archive verification, no prune ledger, no mirror topology change, and it is reversible by
decompression. It is the fastest path to flat disk and it carries the least risk to the streak.

I measured it this morning on a closed day (`atlanta-on-july-20`), gzip level 6, files >5 MB:

| file | raw MB | gz MB | ratio |
| --- | ---: | ---: | ---: |
| `order_books.jsonl` | 292 | 28 | 10.5x |
| `clob_tokens.jsonl` | 81 | 1 | 74.2x |
| `replay_inputs.jsonl` | 54 | 4 | 12.2x |
| `variant_predictions.jsonl` | 51 | 4 | 13.1x |
| `order_books_summary.csv` | 46 | 4 | 11.3x |
| `clob_tokens.csv` | 43 | 1 | 72.2x |
| `snapshot_explanations_long.csv` | 24 | 1 | 27.2x |
| `variant_predictions_long.csv` | 23 | 1 | 39.9x |
| `snapshots.jsonl` | 20 | 3 | 7.4x |
| `components.jsonl` | 17 | 0 | 44.7x |
| **total** | **0.65 GB** | **0.05 GB** | **14.3x** |

Retained snapshots run **8.88 GB/day** (Jul 27) / **8.99 GB/day** (Jul 20) across 12 markets.
The warm tier should take that to roughly **1.3 GB/day**, and applied retroactively across
`data/snapshots` (345 GB, 3.5M files at the Jul 21 measurement) it is a very large one-time
reclaim. Host free space is **146 GB falling 15.7 GB/day — about 9 days.**

## The actual blocker is reader coverage, and you already mapped it

Your own projection-family registry says it: 16 of 17 families are ineligible with the blocker
*"Direct gzip readers not all proven"*, and only `order_books_long` is eligible. So the work is
**not** new compression machinery — `closed_day_projection_tiering` already exists and is
fixture-proven. The work is proving the gzip read path family by family, then marking each
eligible.

That makes this incremental and safely interruptible: every family you unlock is reclaim
banked, and a family you cannot prove stays blocked with its reason recorded.

## Mission 1: order the work by measured payoff

Per market-day, per day across 12 markets, from the table above:

| family | saved/market-day | saved/day |
| --- | ---: | ---: |
| `order_books.jsonl` | 264 MB | **3.2 GB** |
| `clob_tokens.jsonl` | 80 MB | 0.96 GB |
| `replay_inputs.jsonl` | 50 MB | 0.60 GB |
| `variant_predictions.jsonl` | 47 MB | 0.56 GB |
| `order_books_summary.csv` | 42 MB | 0.50 GB |
| `clob_tokens.csv` | 42 MB | 0.50 GB |

The first two are 55% of the win. Confirm these numbers on your own sample before committing to
the order — if my single-day probe is unrepresentative, say so and reorder.

Note `order_books.jsonl` is **canonical evidence**. Compression is not deletion and the storage
contract permits it, but the read path must be bulletproof: it is the file that saved us this
morning, and it is the only complete copy for the 20 split-projection days below.

## Mission 2: prove the readers, family by family

For each family in payoff order:

- enumerate every production reader of that artifact and show each one either already handles
  gzip or is routed through a transparent shim;
- extend the `order_book_tape` pattern — canonical first, then gzip, then plain — where a shim
  is needed, rather than teaching each call site about compression;
- fixture-prove byte-identical round-trip and a real read through every enumerated consumer;
- then flip the family to eligible in the registry with its evidence, or leave it blocked with a
  specific unmet condition.

**Deterministic gzip (`mtime=0`) as the existing tiering does**, so the artifact is a pure
function of its input and re-compression is verifiable.

## Mission 3: the restore-on-demand shim and its cost

A barrier resume or point-in-time window reaching a warm day must transparently succeed. Report
the decompression cost on the read path for the largest family, and confirm no consumer inside
the hot window ever pays it. The item sets the minimum safe hot window at ~30 days — derive it
from code rather than inheriting that number, and record the binding consumer.

## Not in scope, deliberately

No deletion, no prune ledger, no archive push, no mirror or scheduler change, no capture change.
Those wait for the sync split, which is mine. Keep `data/` read-only on your host as always —
this is a build, and I run the production apply in a quiet window.

## One live defect to design around

20 market-days (all 12 on 2026-06-25, 8 on 2026-07-16) have `order_books_long.csv.gz` and
`order_books_long.csv` as **disjoint halves of one day** — gz `00:00-20:20`, plain
`20:44-23:59`, zero capture_ids in common. Pre-fix tiering compressed a live day and capture
re-created the source. Canonical `order_books.jsonl` holds exactly the union (20,680 = 18,238 +
2,442), so nothing is lost, but any reader that falls through to the **gz** silently gets a
partial day that excludes settlement. Your shim must not paper over this: a family whose gzip
and plain forms disagree should fail loudly, not pick one.

## Guardrails

Unchanged. Single declared output root, topic branches only, no PR/merge/master push, NOT-DONE
first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-item-325-warm-tier.md`: your own payoff
measurement and ordering, then per-family reader proof with eligible/blocked verdicts, then the
restore shim and hot-window derivation.

Context: streak 7/14, lock ~2026-08-03. Host 146 GB free, ~9 days.
