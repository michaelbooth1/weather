# Agent report — 2026-07-29 workstation Item 325 warm-tier build

## Outcome

**BUILD ONLY / NOT APPLIED.** The first and largest measured warm-tier
family, canonical `order_books.jsonl`, is built and eligible for deterministic
gzip representation. The other five measured high-payoff families remain
explicitly blocked. This is intentionally an incremental first-family result,
not a claim that the whole warm tier or Item 325 is complete.

The build is based on exact `origin/master`
`d2d7da082984aac5f24144dd8b0f3ae0fab77cce`. No command applied a plan to real
data. Production `data/`, its mirror, and the frozen MM evidence were not
compressed, rewritten, moved, or deleted. File-mutation proof used disposable
synthetic fixtures only.

## Independent payoff order

I measured the six requested families across 84 local market-days: all 12
markets for 2026-07-18 through 2026-07-24. These are existing read-only source
bytes, not extrapolation from the operator's Atlanta probe:

| Priority | Family | Mean raw MiB / market-day | Raw GiB / 12-market date |
| ---: | --- | ---: | ---: |
| 1 | `order_books.jsonl` | 291.60 | 3.417 |
| 2 | `clob_tokens.jsonl` | 85.25 | 0.999 |
| 3 | `replay_inputs.jsonl` | 73.27 | 0.859 |
| 4 | `variant_predictions.jsonl` | 53.12 | 0.623 |
| 5 | `order_books_summary.csv` | 48.19 | 0.565 |
| 6 | `clob_tokens.csv` | 44.67 | 0.524 |
|  | **Six-family total** |  | **6.987** |

The raw-footprint order confirms `order_books.jsonl` as the correct first
family. I did not compress the real sample, so this report does not substitute
a workstation ratio for the operator's measured production ratios or promise
an exact reclaim amount.

## Reader inventory and verdicts

The checked-in registry records 130 exact, role-tagged surfaces. The inventory
includes content readers, delegated readers, discovery and manifest paths, and
writers so that a family cannot be declared safe from a search that considered
only obvious `open()` calls.

| Family | Inventoried surfaces | Verdict | Specific remaining blocker |
| --- | ---: | --- | --- |
| `order_books.jsonl` | 23 | **Eligible** | None; reads converge on `weather.io.open_tiered_text` |
| `clob_tokens.jsonl` | 11 | Blocked | CLOB coverage and data-layer audit collectors still require the plain JSONL |
| `replay_inputs.jsonl` | 40 | Blocked | Replay/snapshot tracking and pooled-candidate replay still require the plain JSONL |
| `variant_predictions.jsonl` | 13 | Blocked | Density parity, residual-corpus, and captured-input parity paths still require the plain JSONL |
| `order_books_summary.csv` | 28 | Blocked | Latest-input, microstructure-feature, and MM scoring paths still require the plain CSV |
| `clob_tokens.csv` | 15 | Blocked | Latest-input, MM run-support, and taker-strategy paths still require the plain CSV |
| **Total** | **130** | **1 eligible / 5 blocked** | |

`weather.operations.closed_day_projection_registry` owns the complete
machine-readable surface list and the exact blocker strings. Its ratchet
requires all six measured families to remain present, requires every family to
have a non-empty inventory, and allows only `order_books.jsonl` to be eligible
in this slice.

For the eligible family, transparent resolution now covers the full-book
content reader, long-table rebuild, event-day manifest inspection and row
counting, archive and tiering discovery, storage classification, CLOB
coverage, data-layer audit, and source-family inventory. Hot capture remains a
plain-file writer; warm representation is an offline, externally approved
operation.

## Restore-on-demand read boundary and split-pair failure

`weather.io.resolve_tiered_text` and `open_tiered_text` define one bounded
plain/gzip boundary:

- plain-only and gzip-only representations are accepted;
- when both exist, their complete decompressed bytes are compared in bounded
  chunks before a representation is returned;
- an identical transitional pair selects the plain peer; and
- a malformed or divergent transitional pair fails before any rows are
  returned. A gzip-only representation fails loudly if corruption is
  encountered while it is streamed.

For this single-file warm representation, restore-on-demand is direct,
streaming gzip decompression through that boundary; it does not materialize a
new plain working copy.

`weather.market.order_book_tape` applies that rule to the canonical raw book
pair and validates any long-CSV pair before selecting a full-book
representation. The same fail-loud rule reaches the event-day manifest,
closed-day archive, CLOB tiering, CLOB coverage, data-layer audit, and source
inventory paths.

That behavior deliberately does not hide the 20 known market-days whose
`order_books_long.csv.gz` and `order_books_long.csv` are disjoint capture
segments. A reader cannot silently choose either half. The canonical raw tape,
which contains their union, remains the preferred source.

## Plan and apply safety built, but not exercised on real data

The warm planner is separate from projection cleanup. It considers only a
registry-eligible family in a closed, finalized event folder with a current
PASS event-day manifest, no writer lock, sufficient source-write quiescence,
an exact source identity, and a target date outside the configured hot window.
A gzip-only file is already warm. An identical plain/gzip transitional pair
produces a removal-only action; a divergent pair blocks.

Apply requires an externally edited, exact approved-plan identity. It reruns
the registry, date, source, finalization, manifest, lock, quiescence, and
`cleanup_preflight` gates; acquires the shared writer lock; writes deterministic
gzip with `mtime=0`; and proves decompressed byte length and SHA-256 parity.
The implementation persists and re-reads durable JSON and Markdown
checkpoints before removing the exact plain peer, immediately re-verifies the
retained gzip, and rebuilds the event-day manifest to PASS. The refreshed
manifest preserves all inventory validation checks and carries an auditable
semantic protection proof binding the exact approved backup/restore proof for
the plain bytes to the retained gzip's decompressed byte length and SHA-256.
That binding is independently re-read after default or custom refresh. It
stops on the first failure. Receipt-bound recovery covers deterministic gzip
already staged after a compression checkpoint and interruption between
plain-peer removal and manifest refresh. A normal pre-unlink failure rolls
back only the exact tool-created gzip while retaining the approved plain
source. Retry re-verifies even a previously completed action instead of
trusting receipt status alone.

Although the decompressed evidence is preserved exactly, apply physically
removes the approved plain peer after the gzip checkpoint. That is why this
handback does not describe the build itself as a production compression or
deletion, and why the operator still owns the quiet-window dry run, review,
approval, apply, and disk measurement.

## Hot-window derivation

The point-in-time production contract now owns both binding constants:

- 14 contiguous target dates; and
- a latest selected target no more than 7 days old.

The oldest date consumed by the worst valid window is therefore
`7 + (14 - 1) = 20` days old. The first point-in-time-safe warm age is 21 days.
The planner's default 30-day hot window adds 9 full days for delayed barrier or
operational recovery. It rejects a future as-of date and rejects every event
inside that configured window.

A compliant apply never newly warms an event inside the configured hot window,
so this build introduces no new gzip read cost there. A later resume of an
older event transparently reads the retained gzip through the same boundary.

## Synthetic read-cost measurement

The full-book reader benchmark used a generated 67,109,192-byte fixture with
67,593 JSONL records and 405,558 decoded book-level rows. Its gzip was
12,049,018 bytes (5.57x); the deliberately high-entropy fixture is less
compressible than the operator's 10.5x production observation.

| Full `order_book_tape` iteration | Median | Source-byte throughput |
| --- | ---: | ---: |
| Plain JSONL | 0.571765 s | 111.935 MiB/s |
| Gzip JSONL | 0.658342 s | 97.214 MiB/s |
| **Gzip overhead for 64 MiB source** | **0.086577 s** | |

A separate direct-text read was 0.032709 seconds plain and 0.126244 seconds
gzip. Linear scaling of the full consumer gives about 2.9996 seconds for the
sample's typical 291.6 MiB `order_books.jsonl`; that is a synthetic estimate,
not a production SLA. The generated fixture was removed automatically after
the benchmark.

## Verification

| Scope | Result |
| --- | --- |
| Full `test_closed_day_projection_tiering.py`, including warm planning/apply, protection-proof rebinding, callback fail-closed behavior, hot-window boundaries, deterministic gzip, receipt/lock interruption recovery, and legacy projection behavior | 55 passed |
| Changed reader/manifest/audit/storage surfaces plus focused archive and source-inventory cases | 131 passed, 36 subtests passed |
| Frozen point-in-time 14-day/7-day boundary cases | 3 passed |
| Read-only roadmap payload/lint build | OK; zero issues |
| `weather.operations.agent_docs_audit` | PASS: 18 agent files, 624 Markdown files |
| `git diff --check` | PASS |

The tiering suite used only a new synthetic pytest base directory. The bundled
runtime lacks `pyarrow`, so collection used an import-only stub; these tests do
not claim Parquet I/O coverage. They did not read or mutate a real snapshot
root.

## NOT DONE

- No real-data plan, apply, compression, plain-peer removal, manifest refresh,
  or disk reclaim.
- No eligibility change for the five blocked families.
- No archive push, archive verification, prune ledger, restore drill, mirror
  topology change, scheduler change, or capture-policy change.
- No claim that warm representation alone satisfies Item 325's week-long
  production acceptance criteria.
- No MM fetch, scoring, rewards run, or cool-bias scoring.

The next safe increment is to migrate and prove one blocked family at a time
in measured payoff order. Deletion and archive offload remain gated on the
separate sync split and restore contract.
