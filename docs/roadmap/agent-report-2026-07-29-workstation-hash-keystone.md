# Agent report - 2026-07-29 workstation hash keystone

Status: **the hash fix is retroactive, but the operational streak is not the
release-admissibility streak.** All 2,470 intact Toronto captured-input rows in
the July 16-29 audit recover their original self-hashes. The malformed July 24
line still makes that whole daily JSONL file fail closed, no current candidate
qualifies, and the current immutable release still has no Toronto route.

This handback executes
`docs/roadmap/workstation-handoff-2026-07-30d-the-hash-defect-is-the-keystone.md`
from exact `origin/master`
`471d1087b9d5d5a7896e3b1e259d794c593b39ce`. The prior strict-parity branch was
pushed before work began. No `data/` file, release pointer, serving route,
promotion state, or master branch was changed.

## 1. The streak answer

### Plain answer

**No: fourteen days reported by `streak.ps1` do not guarantee an admissible
PIT/release window. Complete-grade capture is necessary but not sufficient.**
The operational counter has been treating a necessary property as if it were
the whole lock. Protecting it was not wasted - it preserves the irreplaceable
capture tape - but reaching 14 is an invitation to run the strict lock, not
proof that the lock will pass.

There is also a direct contract mismatch:

- `scripts/ops/streak_status.py` advances on
  `quality_grade in {"complete", "manual_override"}`;
- `latest_toronto_lock_revisions` in
  `weather.operations.point_in_time_staging_receipt` requires every current
  revision to be exactly `complete`.

The operational counter can therefore reach 14 while the staging receipt
rejects the same dates.

### The real daily predicate

Keep two separate clocks:

1. **Operational capture streak** - the existing ledger/cadence signal from
   `streak.ps1`.
2. **Release-admissible input streak** - contiguous dates for which all of the
   following are true:
   - the settlement ledger history verifies and the latest date revision is
     exactly `complete`;
   - the folder resolves to the exact Toronto market/date and contains the
     canonical snapshot and captured-input tapes;
   - every bounded JSONL line parses strictly, with no duplicate/conflicting
     snapshot identity and no reconstructed input;
   - each pinned snapshot is present in the tape, its captured-input self-hash
     verifies, and its recorded distribution is finite, nonnegative, and
     mass-preserving;
   - settlement unit/winning-band identity, feature-quality quarantine, tape
     inventory, and immutable file hashes pass the production source checks.

Compute that second grade once after daily settlement/finalization, stream the
bounded files, persist the per-date PASS/BLOCK reason and input hashes, then
collapse contiguous PASS dates exactly as `streak.ps1` collapses ledger
grades. Do not make the frequent host-status monitor rescan hundreds of
megabytes of hot tape.

Candidate skill, qualification, the complete route/base-model graph, immutable
release verification, and forward parity are still release-level gates. They
should be reported beside the two clocks, not folded into a market-day grade.

The checkout-visible ledger read during this task ended on July 27 at 7/14;
the handoff records July 28 as day 8. That lag does not change the conclusion
or the projected earliest lock. The July 16-29 diagnostic window is not a
hidden completed lock: July 17, 19, and 20 are `partial`, and July 24 still has
the malformed source line.

The canonical runbooks now state the two-clock distinction instead of claiming
that the operational count alone unlocks release #1.

## 2. Hash retroactivity and strict-partition count

### Verdict: retroactive for every intact affected row

The stored digest is recoverable. The writer hashed the pre-persistence typed
payload:

- `recorded_distribution` temperature buckets were integers;
- nested captured-source maps can also have integer keys, including
  local-history `bucket_counts` and `bucket_probabilities`;
- `sort_keys=True` therefore emitted those maps in numeric order.

JSON then represented the object keys as strings. A reader that blindly sorted
those strings used lexicographic order and computed a different digest.

`weather.captured_input_hash.captured_input_payload_sha256` now restores the
schema-owned integer distribution buckets and recursively restores other
numeric-key mappings only when persisted order proves the original type:
numeric order differs from lexicographic order and the file contains numeric
order. Genuine numeric-looking string maps that were emitted
lexicographically remain strings. The original canonical hash is then
recomputed and compared normally.

This is not insertion-order acceptance, a derived replacement hash, or a data
rewrite. The claimed digest must still exactly match canonical SHA-256, and
malformed JSON still blocks. The algorithm label remains
`sha256-canonical-json;omit=captured_input_hash` because the implementation now
reproduces the original writer-side algorithm rather than inventing a new
digest.

The shared helper is used by:

- `SnapshotStore` when creating new captured-input self-hashes;
- strict captured-input replay/serve parity verification; and
- release-bound worker snapshot verification.

### Toronto July 16-29 re-audit

| Target date | Self-hash-valid intact partitions | Malformed lines |
| :--- | ---: | ---: |
| 2026-07-16 | 193 | 0 |
| 2026-07-17 | 172 | 0 |
| 2026-07-18 | 205 | 0 |
| 2026-07-19 | 165 | 0 |
| 2026-07-20 | 180 | 0 |
| 2026-07-21 | 191 | 0 |
| 2026-07-22 | 197 | 0 |
| 2026-07-23 | 207 | 0 |
| 2026-07-24 | 194 | **1** |
| 2026-07-25 | 195 | 0 |
| 2026-07-26 | 185 | 0 |
| 2026-07-27 | 158 | 0 |
| 2026-07-28 | 193 | 0 |
| 2026-07-29 | 35 | 0 |
| **Total** | **2,470** | **1** |

Therefore:

- self-hash-valid intact partitions rise from **0 to 2,470**;
- **13 of 14** daily files are wholly strict-readable;
- those 13 whole files contain **2,276** partitions;
- July 24's 194 intact rows validate, but the strict reader correctly blocks
  the whole file while its one malformed line remains;
- strict forward-shadow comparisons remain at zero until an executable
  Toronto route/release exists and the July 24 source is reviewed and repaired.

The hash fix recovers the evidence immediately, but it does not turn this
calendar slice into an admissible contiguous release window.

### Affected fleet scope

The eight July 29 markets originally blocked were:

`atlanta`, `austin`, `dallas`, `denver`, `houston`, `miami`, `nyc`, and
`toronto`.

After typed canonicalization, all **284/284** current-day fleet rows verify.
The four markets that escaped the original defect were `chicago`,
`los-angeles`, `san-francisco`, and `seattle`. Their captured temperature
supports did not cross a decimal-width boundary, so numeric and lexicographic
key ordering happened to coincide. The failing F supports crossed `99 -> 100`;
Toronto crossed `9 -> 10`. That asymmetric boundary behavior is the mechanism
fingerprint.

## 3. Smallest release that binds the incumbent

### Contract verdict

A literal incumbent-only release with no candidate artifact is **not**
supported by the current schema. The semantic contract always requires the
pooled model/registry roles, and every executable `promote` or `shadow` route
must name a candidate variant bound to that pooled model.

The contract does already support the practical no-market-promotion shape:

1. freeze a `research_only` semantic release;
2. give every runtime market an explicit `shadow` route and a complete exact
   base-model serving graph;
3. leave `promote_markets` empty;
4. verify it inactive;
5. only under a separate reviewed boundary decision, use the one-time
   `serving_identity_bootstrap` lifecycle to create the first pointer.

That binds the exact incumbent HGB/LR/calibration graph and makes it reversible.
The pooled candidate remains present only as a verified shadow lane; no market
route is promoted. Existing lifecycle tests prove that this bootstrap is
one-time, review-bound, research-only, sequence 1, and rollback-preserving.

### What the missing Toronto route means

The rehearsal release is not missing the generic route or base-graph serving
roles. Its route's `markets` mapping omits Toronto, and the base-model graph is
required to have exactly the same market set. It consequently omits Toronto's
per-market base-model component bindings too. `TorontoHighTempModel` accepts
only an explicit `promote` or `shadow` route when an active pointer exists, so
absence (and `blocked`) cannot bind the incumbent.

This is not a Toronto promotion prerequisite. A Toronto `shadow` route is
sufficient. The repository already contains all seven canonical Toronto base
component artifacts. The smallest supported artifact fix is therefore a new
all-shadow research release that freezes Toronto plus the eleven F markets,
not a new route decision or release schema. The nightly orchestration CLI is
currently F-only, so constructing that exact twelve-market bootstrap needs a
reviewed artifact-build entry point or a bounded direct use of the existing
candidate freezer. It does not need a serving design change.

No inactive release was authored here because this task supplied no reviewed
all-shadow candidate input set, and no pointer action was authorized.

## 4. Malformed interleaved line and containment

The defect is:

```text
data/snapshots/highest-temperature-in-toronto-on-july-24-2026/replay_inputs.jsonl
line 46
```

- raw line SHA-256:
  `8f17b3b1de8d85a101bbe3f50b32aa7f03f00df90d2e801806fa78856054e47f`;
- line length: 162,613 characters;
- JSON failure: character 8,155;
- a second JSON object begins inside the first object's
  `runtime_identity.source_scope_files` array;
- the two embedded captures are around `09:34:37Z` and `09:43:42Z`.

The current writer could still reproduce this before this patch.
`append_jsonl` streams one JSON object through many writes. The market-day
`.snapshot.lock` was broken solely when its mtime exceeded 300 seconds, without
checking whether the recorded owner PID was still alive. A healthy but slow
snapshot transaction could therefore remain active past five minutes, have a
second process delete its lock, and interleave chunks. The roughly nine-minute
capture separation is consistent with that live mechanism. The production
capture entry points use `maybe_write` and this lock; direct `write` calls are
test-only in the current tree.

Containment now treats a parseable lock as recoverable only when its recorded
PID is dead. Age remains a fallback only for legacy/torn locks with no
trustworthy owner identity. Regression tests cover both an old live-owner lock
that must be preserved and a fresh dead-owner lock that must be recovered.

The July 24 data was not repaired or rewritten. It remains a reviewed,
one-line canonical-evidence repair for the operator.

## Verification

- Focused captured-hash, snapshot-writer, worker-binding, and parity suite:
  **43 passed, 2 subtests passed**.
- Read-only Toronto re-audit: **2,470 valid, 0 hash mismatches, 1 malformed**.
- Read-only July 29 fleet re-audit: **284 valid, 0 hash mismatches**.
- `git diff --check`: PASS.
- `data/`: read only.

Integration note: the previously pushed strict inactive-forward-shadow branch
predates this helper and must use `captured_input_payload_sha256` when it is
rebased or merged. Its local insertion-order diagnostic must not become an
authorizing compatibility path.
