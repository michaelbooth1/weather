# Workstation handoff — 2026-07-28a: storage branch rework, release binding only

`codex/production-storage-pressure-2026-07-28` @ `6312e88d` is accepted in substance. One
change blocks the merge. Everything else stands and I do not want it rebuilt.

**Rebase or merge from current `origin/master` `2d4c2811` first** — I changed
`clob_order_book_tiering.py` under you (details at the bottom).

## Disk got materially worse overnight — this is now time-sensitive

| | yesterday | now |
| :--- | ---: | ---: |
| Free | 174.6 GB | **162 GB** |
| Trend | −2.4 GB/day | **−22.6 GB/day** |
| Headroom | ~73 days | **~7 days** |

I told you this was "not an emergency on this host." That was wrong, and the operator's
instinct to move the work up was right. Treat this as the priority.

## What blocks the merge

The branch adds `allow_pinned_external_pointer` to `resolve_verified_active_release` and
`load_verified_active_serving_bundle`, bypassing the requirement that the active release
pointer live directly inside the releases root. `load_pinned_serving_bundle` uses it to
verify a plan-bound release from a pointer payload written to a temp directory.

The implementation is careful — the payload is hash-bound to the approved plan, release IDs
stay constrained to `releases_root`, served bindings are reverified, the result is checked
against the plan's `release_id`, `manifest_sha256` and `release_dir`, and the default is
`False` with exactly one caller. I want to be clear that this is not sloppy work.

It is still a relaxation of a release-containment invariant whose own docstring exists to
"[prevent] a valid pointer from laundering identity onto legacy global model paths," landing
in the window where establishing trustworthy release binding is the entire objective, in
service of a storage cleanup. The operator has declined it. Release-path changes need their
explicit authorization and this did not have it.

## What to do instead

The protection you are buying is against the plan going stale between approval and execution.
That does not require relaxing containment:

- Resolve the **genuine active pointer** through the unmodified strict path.
- Assert the resolved `release_id`, `manifest_sha256` and `release_dir` match the approved
  plan binding.
- If they do not match, **abort the cleanup** — the plan was approved against a different
  release and must be replanned.

Same time-of-check/time-of-use guarantee, no weakening. Revert `release_artifacts.py` and
`release_serving.py` to their master state.

If some reachability input genuinely cannot be resolved under the strict rule, fall back to
your own stated principle rather than to a new opt-in: **unknown or ambiguously referenced
entries are retained.** Reclaiming less is always acceptable here; the replay cache is 32 GiB
against a 77 GiB projection prize, so precision on the cache is not worth a release-path change.

## If the rework is not quick, split instead

Mission 3 imports none of this — I checked `closed_day_projection_tiering` and
`closed_day_projection_registry` and neither touches `release_artifacts`, `release_serving`,
or `replay_cache_retention`. It is also the larger prize.

So if the rework will take more than a few hours, push Mission 1 + Mission 3 as a separate
branch I can merge tonight, and let Mission 2 follow when the release binding is sorted. Say
which you are doing so I can plan the quiet window.

## Measurements from here, to help you size Mission 3

Production plan run this morning, after my tiering change:

| Status | Folders | Bytes |
| :--- | ---: | ---: |
| `already_tiered` | 508 | — |
| `already_tiered_source_present` (duplicates) | 20 | **4.33 GiB** |
| `candidate` | 12 | 15.93 GiB |
| `blocked_active_or_unsettled` (today) | 12 | 3.55 GiB |

Observed gzip ratio on these is about **94%** (0.70 GiB → 0.04 GiB). If the uncompressed
projection families behave similarly the reclaim is very large — but `order_books_long` is
unusually repetitive, so do not assume `price_history` or `snapshot_explanations_long` match
it. Measuring the per-family ratio is worth doing before you promise a number.

The 20 duplicates remain untouchable by the existing tiering tool: `apply_tiering` only
processes `candidate` rows and skips anything with an existing gzip. That gap is yours.

## What I changed under you

`clob_order_book_tiering.py`, twice, both roll-free:

1. The eligibility cutoff used the **UTC** date. UTC rolls at 20:00 local, so from 20:00 until
   the 00:05 daily roll it marked the current day settled while the CLOB loop was still
   appending. A plan run at 22:00 offered all 12 live markets as candidates.
2. The first fix padded the date by a day, which cost ~13 GiB of daily reclaim. Replaced with
   the real invariant: `MIN_QUIET_SECONDS` (7200s) since last write, checked at plan time and
   again immediately before each compression. New statuses `blocked_recently_written` and
   `skipped_recently_written`.

If your projection tiering has the same date-based eligibility shape, it has the same bug.
**Gate on writer quiescence, not on date arithmetic**, and re-check immediately before acting
rather than trusting the plan.

## Guardrails

Unchanged. Build only — no apply, deletion, or compression against real data; I run those here.
`data/` read-only, topic branch, no PR/merge/master push, no serving or scheduler change.

## Handback

Push the reworked branch (or the split pair). State which release-resolution path you used and
show the abort-on-drift behaviour under test.
