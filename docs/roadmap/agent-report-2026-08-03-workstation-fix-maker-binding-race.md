# Workstation report 2026-08-03 — fix the maker scoring binding race

## Verdict

The recurring maker-score race is repaired on a topic branch based exactly on
`master` at `fbe0d93c`. The scheduled active-day canonical fallback now binds
the largest complete-record byte prefix visible at enumeration with SHA-256,
then the isolated scorer validates and reads exactly that prefix. Growth after
capture is excluded from this score. Truncation or any mutation within the
captured prefix fails closed.

Projection inputs and ordinary non-scheduled callers keep the existing exact
size/mtime contract. No live data, forbidden date, fit, retrain, candidate,
held-candidate score, artifact, cache, archive, scheduler, pointer, promotion,
host, mirror, ACL, or credential access occurred.

## Challenge answers

### 1. Is the canonical tape always append-only?

No, not under every repository writer path.

- The production maker loop creates a new run folder and writes the first tick,
  then retains that run ID and uses `append_csv_rows` for later ticks.
- The daily-roll launcher does not pass a run ID. A mid-day restart launches a
  new process, which generates a new run ID; forced recovery can quarantine the
  unhealthy prior folder rather than resume its tape.
- `weather.operations.market_making_tape_encoding repair` is an explicit writer
  that can rewrite a legacy-encoded canonical tape in place. The callable
  `build_run_once` surface can also overwrite a reused run ID when invoked with
  `append=False`, although the scheduled roll does not do that.

Therefore a rule that merely accepts `actual_size >= captured_size` would be
unsound. The shipped contract additionally hashes the captured prefix before
the child is launched and validates that same prefix before and after parsing.
An encoding repair, reorder, or overwrite inside it is rejected even if file
size does not change.

### 2. What happens at a truncated final CSV line?

The existing `iter_csv_rows` is not a sufficient boundary contract: Python's
CSV reader can yield an unterminated unquoted final row as a short row. The new
binding trims the captured size to the last LF and therefore excludes a normal
mid-row append. The bounded child reader uses strict CSV parsing; if that LF is
inside an unfinished quoted field rather than a record terminator, parsing
raises instead of admitting a partial row. Tests cover both cases.

### 3. Is mtime still meaningful?

Only as capture-time receipt metadata. A correct append changes mtime, so mtime
cannot be an equality gate under prefix semantics. `captured_mtime_ns` and the
full file size observed at capture remain in the receipt for diagnosis; prefix
length plus SHA-256 are the integrity identity. Exact projection bindings keep
their existing mtime equality check.

### 4. Would a sealed child-workspace copy be safer?

A retained sealed copy would make later reproduction independent of the source
tape, but producing it safely still needs a record boundary and hash while the
source is live. It would also duplicate as much as the configured 512 MiB input
budget on the disk-constrained host, add a full write plus later read, and need
its own retention/cleanup contract. The hash-bound reader provides deterministic
bytes without that extra disk allocation. A snapshot remains a reasonable
future choice if durable replay of every daily score becomes a requirement.

## Race and integrity tests

Synthetic fixtures prove:

- the former exact binding rejects a file that grows between capture and
  validation;
- the scheduled prefix binding scores only the captured row after the same
  growth;
- an unquoted partial final row is excluded;
- an unfinished quoted record containing a newline fails strict parsing; and
- a same-length rewrite inside the prefix fails the SHA-256 check.

Verification:

```text
python -m pytest tests/market/test_mm_scoring_projection.py -q
8 passed

python -m pytest tests/market -q
432 passed, 18 subtests passed

python -m pytest tests/operations/test_daily_refresh.py \
  tests/operations/test_daily_refresh_resources.py \
  tests/operations/test_import_architecture.py -q
148 passed, 4 subtests passed

python -m pytest -q
3291 passed, 4 skipped, 820 subtests passed

python -m weather.schema_registry audit --paths src --strict
PASS (0 unregistered versions)

python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 589 Markdown files)
```

The Windows full-suite run used a process-scoped PowerShell execution-policy
bypass for scheduler-contract tests and an extended-length pytest temp path for
the executor sandbox tests. These accommodations change neither repository nor
runtime state.

## Blast-radius specification — analysis only

The blanket rule that every isolated-step error stops the pipeline should be
replaced only after an explicit dependency and failure-scope contract is added.
This report does not implement that change.

Each step should declare `requires`, `produces`, and one of four failure scopes:

1. `pipeline`: stop because trustworthy orchestration or host containment is
   no longer provable;
2. `pause_resume`: persist a resumable interruption because capture-resource
   admission or the post-step host reserve is unsafe;
3. `promotion_lane`: continue independent evidence work, but deny the settled
   barrier, readiness, promotion, and release actions; or
4. `dependents_only`: mark only transitive consumers blocked and keep running
   independent siblings.

Genuine whole-pipeline stops are narrow: failure to persist the authoritative
status/manifest, loss of the daily lock, an unterminated child or uncertain
process-tree containment, and host-resource conditions that make further work
unsafe. Resource admission is a pause, not a completed failure.

Settlement restoration, label finalization, exchange-economics currentness,
the settled-day barrier, runtime-identity reconciliation, configured observed-
floor enforcement, production readiness, and promotion must remain fail-closed
for promotion/release. Their failure need not suppress unrelated diagnostics,
retention inventory, or learning reports; it must instead make those outputs
diagnostic-only and keep all state-changing release paths unreachable.

Maker scoring, taker evidence analyses, settlement/source audits, trading
evidence, CLOB tiering, replay repair, closed-day conversion, performance
reports, price-free learning, disagreement rehydration, and variant scorecards
should fail their step and declared consumers, not every later sibling. In the
current incident, maker failure would be recorded as a blocker consumed by the
existing `settled_day_analysis_barrier`, while settlement-source audit,
observed-floor monitoring, CLOB tiering, retention inventory, and independent
learning would still run. Promotion would remain blocked.

The stage manifest and evening trigger must accept a new partial-error state,
carry the complete failure/dependency ledger into Stage B, and select runnable
steps from the graph rather than treating Stage A as all-or-nothing. Tests must
prove step-local continuation, transitive blocking, promotion denial, clean
child termination before continuation, resumable resource pauses, and hard
stop on status/containment uncertainty. Until that graph and those tests exist,
the current fail-closed blast radius should remain unchanged.

## Roll-sensitive files

These changed files match `SOURCE_PATTERNS` and consume a capture-loop roll when
merged:

- `src/weather/market/mm_paper_scoring.py`
- `src/weather/market/mm_scoring_projection.py`
- `src/weather/operations/daily_refresh_trading_steps.py`
- `src/weather/schema_registry_recent_data.py`

`README.md`, tests, and this report do not match `SOURCE_PATTERNS`. No
`scripts/**/*.ps1` or `tools/**` file changed. Merge timing remains with the
operator after lock night.
