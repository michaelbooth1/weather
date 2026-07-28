# Agent report - 2026-07-28 workstation who breaks the floor

Status: **MISSION 1 FAILED CLOSED ON A MISSING DECISION-TIME FLOOR. THE
MONOTONICITY AND SETTLEMENT-BOUND TESTS DID NOT COMPLETE. MISSIONS 2 AND 3
WERE NOT RUN.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-27g-who-breaks-the-floor.md`
from exact `origin/master`
`87e41f6b1434271adc3499b968e345066dd99258` on topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

## Mission 1 answer first

**`FAIL_LEAKAGE_GATE_STOP_BEFORE_SCORING`**.

The first disqualifying condition was not a monotonic decrease or a value
above settlement. Snapshot `20260628T030303-0400` reconstructed
`high_so_far = None`. The predeclared gate requires a finite
prediction-time `high_so_far` for every admitted frozen-corpus snapshot, so
it failed with:

```text
GateError: invalid decimal high_so_far 20260628T030303-0400: None
```

Therefore there is no evidence-backed yes/no answer to either requested
trajectory claim:

- monotone non-decreasing `high_so_far` within every frozen market-day; or
- raw `high_so_far` and `ROUND_HALF_UP(high_so_far)` never exceeding the
  frozen settled maximum.

The audit stopped before evaluating those complete-population predicates.
This result does **not** prove forward-looking contamination. It proves that
the proposed floor is undefined for at least one admitted decision instant,
which is enough to fail the frozen universal gate. Silently dropping that
instant after seeing it would change the estimand, so no retry or narrowed
population was attempted.

Before the failure, six replay files completed their one-pass validation:

| Scope | Observation |
| :--- | ---: |
| Completed native-F market-days | 6 / 129 |
| Reconstructed and manifest-pinned snapshots | 773 / 18,793 |
| Completed replay bytes | 305,241,182 / 8,610,897,941 |
| Unpinned records admitted | 0 |
| Candidate-vector stat, hash, or scan | 0 |

The six completed files were Atlanta, Austin, Chicago, Dallas, Denver, and
Houston for 2026-06-28. Their size and modification time were stable through
the reads. The failure occurred before the next replay file could be
recorded as complete.

## Required currency answer for `-28c`

The honest answer is **none of the three full-depth representations in the
question today**. The current
`codex/workstation-mm-scaled-2026-07-28c` implementation at
`c6319fa12788ab68fd83154205185ae3def695fc` does not perform a full-depth
read:

- `mm_paper_scoring.load_book_rows()` reads
  `order_books_summary.csv`;
- its mark path also reads `order_books_summary.csv`; and
- `mm_paper.load_or_build_clob_recon()` selects snapshot folders by the
  presence of `order_books_summary.csv`.

That branch has no caller of `iter_full_book_rows`. Its MM path therefore
consumes **`order_books_summary.csv`**, not `order_books.jsonl`,
`order_books_long.csv.gz`, or uncompressed `order_books_long.csv`.

The accepted storage rework at `6312e88d` adds the intended future
full-depth boundary:

1. canonical `order_books.jsonl`;
2. `order_books_long.csv.gz` fallback; then
3. uncompressed `order_books_long.csv` fallback.

The raw-to-gzip fallback is fixture-tested, but it is not wired into the
current `-28c` MM caller. Consequently:

- compressing `order_books_long.csv` tonight does **not** strand the current
  scaled scorer, because its input is the retained summary CSV;
- no family needs exclusion merely to preserve that current scorer; but
- a genuine post-cleanup full-depth `-28c` run is **NOT REHEARSED** and must
  first adopt `weather.market.order_book_tape.iter_full_book_rows`.

I cannot truthfully label the next current-code MM run a `.csv.gz` or JSONL
full-book consumer. Once the accepted boundary is wired, it will prefer
canonical JSONL and use gzip only when JSONL is unavailable.

## Hard stop boundary

The persisted Mission 1 failure receipt says:

| Operation | Result |
| :--- | :--- |
| Mission 1 complete-population monotonicity check | **NOT COMPLETED** |
| Mission 1 complete-population settlement-bound check | **NOT COMPLETED** |
| Candidate vector access | **NOT STAT'ED OR HASHED** |
| Mission 2 construction/localization | **NOT RUN** |
| Mission 2 alpha attribution | **NOT RUN** |
| Mission 2 incumbent characterization | **NOT RUN** |
| Mission 3 projection and scoring | **NOT RUN** |
| Model prediction, fitting, or serving replay | **none** |
| Vendor requests | **0** |
| Order-book or full-book reads | **0** |
| Writes below `data/` | **0** |
| Apply, deletion, or compression against real data | **none** |

There are therefore no defensible Brier scores, decomposition changes,
market-gap closure estimates, or worse-case projection rows to report.

## Current-tip binding and host admission

The historical `7068d50e` packet and its prior
`FAIL_HOST_ADMISSION_STOP_BEFORE_MISSION1` receipt remain byte-for-byte
unchanged. Reusing that root would have overwritten historical evidence and
would also have failed its old `config/locations.json` pin. The requested
`87e41f6b` tip changed that registry only by advancing
`event_metadata.last_refreshed_at_utc`; the byte length remained 54,234 and
the new pinned SHA-256 is
`826d3ec5d3f679a4481a816355acfbfe6547338214b895bf4414ade48d89e62b`.

Before any corpus or candidate-vector access, a fresh packet was frozen at:

`scratch/workstation-research-output/who-breaks-floor-20260728g-87e41f6b`

Its synthetic self-test passed. The final persisted admission and an
operator-side immediate read-only recheck reported:

| Gate | Requirement | Admission | Immediate recheck | Result |
| :--- | :--- | ---: | ---: | :--- |
| Commit | `< 70%` | 34.016230% | 33.692620% | PASS |
| Available physical memory | `> 8 GiB` | 16.053074 GiB | 16.222881 GiB | PASS |
| Free disk | `>= 50 GiB` | 68.248432 GiB | 68.240601 GiB | PASS |
| Python or robocopy processes | none | 0 | 0 | PASS |
| Training/restore or mirror process | false | false | not repeated | PASS |
| `data/` deny-write ACL | two deny entries | 2 | not repeated | PASS |

The harness consumed that exact admission receipt, enforced a 15-minute
freshness ceiling, and recorded identical fixed-input identities before and
after the failed pass. The immediate recheck is retained in the terminal
transcript; it is corroborating operator evidence, not a second
machine-readable receipt.

## Evidence and receipts

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Refrozen predeclaration | 11,000 | `83a94e1799652379c21b4d6d762372288f13c936a2a62127f53a0e98c3df1599` |
| Fresh host admission | 2,829 | `ba3755a9b210523355abfd95acbed71a51f696b99e7256d8475a30e580926a6c` |
| Mission 1 harness | 48,477 | `657bda551dd35b36a3a4bb68aee772cc80bd2ccbf09beda9f4b0ea7bfaf5163f` |
| Mission 1 gate | 425 | `b71d34282c38041719be021cd0fccaed5993704967f05506c0b622ff1b4165d6` |
| Mission 1 receipt | 19,081 | `df5690ba73943fe60901231d4d3566082886fc627c04633f5aa553e1e795aaaf` |
| Completed replay-file receipt | 2,249 | `4b331520dd6340221cc1db6279a0c61bd4053f0df0515a76c98c4d1b4407bfa8` |
| Empty floor extract header | 375 | `cf2e335e7550d1f50e8b974e126f7d555ede8f8fa3edb64178d434dd1723da72` |

The scratch evidence is outside `data/`. The candidate vector remained
unopened, as required by the Mission 1-first contract.

## NOT DONE and next admissible step

- **NOT DONE:** a complete ex-ante floor trajectory check.
- **NOT DONE:** candidate construction proof, 124-case alpha attribution,
  cadence-neutral incumbent characterization, projection, or rescoring.
- **NOT PROVEN:** strict upstream WU readability, exchange authority,
  active-release binding, or deployability.
- **NOT CHANGED:** model, floor order, blend, alpha, config, artifact,
  release, pointer, collector, scheduler, sizing, cap, trading, or serving
  state.

The failed receipt authorizes no retry. A future attempt would need a new
predeclaration made before data access that explicitly defines how
pre-observation snapshots with no finite `high_so_far` enter or leave the
estimand. Missions 2 and 3 must remain blocked until that replacement Mission
1 gate passes.
