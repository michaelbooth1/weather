# Settlement-source audit

Status: canonical implementation and verification contract. Production adoption
is tracked separately from source qualification.

The audit classifies the selected settlement label for each event, records its
source lineage, and supplies the truth-label gate for settlement-scored trading
evidence. Classification and promotion-countability rules are unchanged by its
bounded storage path. The owner is
`weather.reporting.source_gates.settlement_source_audit`.

## Revision and output contract

Inputs stream into a new disposable SQLite index on every invocation. Label
CSV rows retain encounter order. Ledger files retain sorted path order and
physical JSONL row order. The last whole row for each nonempty event slug wins
within each input family; nonempty fields from that selected label overlay the
selected ledger row. Selection never substitutes timestamp order. Invalid JSONL
syntax retains the legacy skip behavior; invalid row types and oversized records
fail the build.

The index emits event-slug order and accumulates the existing summaries without
retaining superseded histories or the completed event array in Python memory.
The existing JSON schema, field values, report ordering, and gate decisions are
preserved for supported inputs. Empty input still produces a missing-evidence
audit; incomplete or malformed gate input cannot pass.

`open_settlement_source_audit(...)` owns the index and returns a payload whose
`rows` supports repeatable iteration only inside that context. CLI and daily
orchestration use this API. `build_settlement_source_audit(...)` remains a
materialized compatibility API for small callers; it is unsuitable for large
production reports. A daily provisional-label retry releases the old index
before rebuilding from corrected inputs.

`settlement_label_gate_from_path(...)` streams both compact and pretty legacy
JSON, retains only requested-date gate details, and validates the complete file
before returning a passing gate. It rejects duplicate root keys, truncated
tails, trailing content, invalid row types, and oversized individual values.
Trading evidence uses this reader instead of loading the full JSON document.

## Resource bounds and publication

The index uses an 8 MiB SQLite cache, disabled mmap, and file-backed temporary
sort storage. Default index and encoded JSON limits are declared in the owner
modules and exposed as `--max-index-bytes` and `--max-output-bytes`. An index
limit bounds SQLite database pages; it is not a reservation for journal files,
staged output, or the previous valid report. Reserve space for those separately.
The default limits are 2 GiB of database pages and 512 MiB per JSON output.
Input records and reader values have independent limits, and market summaries
allow at most 4,096 distinct groups. Exceeding a limit fails without truncating
evidence into a passing result.

`--scratch-root` selects the parent of an invocation-specific temporary index.
The daily caller uses a disposable directory below its configured backtest
root. Normal completion, exceptions, and cooperative cancellation close the
database and remove that invocation's temporary files. Abrupt process death can
leave partial attempt directories; those are never reused as an index or read
as authoritative output. Cleanup must target only reviewed attempt paths.

Publication first completes staged JSON and Markdown, then replaces each
canonical file atomically. Authoritative JSON is replaced last. A failed or
interrupted JSON stream cannot replace the previous complete audit. Markdown is
advisory: the two filenames are not an atomic multi-file transaction, and a
failure between final replacements can leave Markdown newer than JSON.

These bounds supplement the existing isolated-child memory, time, admission,
and teardown gates; they do not raise or bypass those gates.

## Sealed offline hash reuse

Live lineage paths receive fresh SHA-256 hashes. Size and mtime never qualify a
file for cached content identity.

An offline caller with a reviewed sealed corpus may pass
`sealed_lineage_sha256`, an iterable of `(absolute_path, expected_sha256)` pairs,
to the context API. The invocation stores those identities in SQLite, verifies
bytes on first use, and reuses only those exact declared hashes. It checks every
declared file again before yielding a completed audit and before publishing JSON.
A missing file, stale digest, or same-size/same-mtime content change fails the
sealed build. Files outside the declared set remain uncached. There is no
persistent cache, implicit seal, or scheduled live-input reuse.

## Reconciliation timing and the learning barrier

Traced from code 2026-10-16 (no host data read). `_classify` in the audit labels a
row `SOURCE_DISAGREEMENT` when Polymarket reconciliation is `mismatch`, or when
any supporting bucket (WU final, weather.com max-since-7, live normalized high,
snapshot high, market resolution) differs from the canonical ledger value. That
check runs before the `PROVISIONAL` and `UNRECONCILED` checks, so a row whose
reconciliation is still `not_closed`, `fetch_error` or `not_requested` is labelled
a disagreement as soon as one supporting source differs. Classification is
unchanged by the policy below.

**Decided policy (owner, 2026-10-16, "Option 1"; implemented).** An undecided
`SOURCE_DISAGREEMENT` row defers instead of blocking the settled-day analysis
barrier, and stays non-countable:

- `settlement_label_gate_for_target_dates(..., defer_undecided_disagreement=True)`
  defers a blocking row only when all hold: status `SOURCE_DISAGREEMENT`;
  reconciliation in `UNDECIDED_RECONCILIATION_STATUSES` (`not_closed`: event not
  resolved; `fetch_error`: Gamma fetch failed; `not_requested`: Polymarket never
  consulted, which a requested re-finalize would decide); and a
  `disagreement_sources` list that does not contain `market_resolution`. A
  disagreement with Polymarket's own winning band is a substantive mismatch, and a
  row without the list cannot prove otherwise, so both keep blocking.
- Still blocking, as before: `mismatch`; `unavailable` (closed event, no winning
  band) and any empty or other status; `SOURCE_REVISION`, `PROVISIONAL`,
  `UNRECONCILED` and every other class; missing audit rows. A deferred row never
  hides another row's blocker on the same date.
- Deferred rows are listed as `deferred_non_countable`
  (`date:market:SOURCE_DISAGREEMENT:<reconciliation>`) with `deferral_policy`; the
  gate adds both keys only in deferral mode, so default output is unchanged.
- Only the daily `settlement_source_audit` step (the barrier's
  `label_provenance_audit` dependency) uses deferral mode, and reports
  `target_date_deferred_non_countable`; the status summary and run report carry it.
- Non-countability is unchanged and enforced where it was: the audit row keeps
  `promotion_blocker` true and `proof_grade_label` false; label
  `promotion_countable` still requires reconciliation `match`
  (`promotion_countability`, `PROMOTION_RECONCILIATION_STATUSES`); trading evidence
  calls the strict gate, which still blocks the date. A deferred row becomes
  countable only after a later finalize records `match`.

A blocking row whose reconciliation is `match` is rescued as before and listed
under `non_countable_reconciled`. The daily retry
(`_provisional_target_blocker_slugs` in `daily_refresh_trading_steps.py`)
re-reconciles only when every remaining blocker is `PROVISIONAL`; deferred rows
are not blockers, so they neither prevent nor join that retry, and nothing
re-reconciles them automatically (that was Option 2, not chosen).

Follow-up candidate (new owner question, not decided): `PROVISIONAL` and
`UNRECONCILED` rows with the same undecided reconciliation still block, so the
rule is asymmetric; the owner approved deferral for `SOURCE_DISAGREEMENT` only
(master-agent ruling 2026-10-16).

**History.** `daily_refresh_status.json` and the audit JSON are overwritten each
run. `data/backtest/daily_progress_ledger.jsonl` gets one row per non-dry run,
also on BLOCK days (it is written after the step loop). Its
`daily_refresh_blockers` field lists failed steps with `root_cause_class`; the
barrier entry (`settled_day_analysis_barrier`) also carries
`audit_blocker_classes`, the sorted classes of the audit step's target-date
blockers. Two additive JSON fields record per-row detail:
`settlement_audit_target_date_blockers` (`target_date`, `market_id`,
`blocker_class`) and `settlement_audit_deferred_non_countable` (the same plus
`reconciliation_status` and `countable: false`). Rows written before this change
lack them; the ledger schema version is unchanged because the fields are additive
and the CSV writer keeps the union of columns.

## Verification and acceptance

Use the project interpreter and the host's required admission wrapper. The
focused tests cover frozen legacy rows, summaries and target-date decisions;
duplicate/late revisions and label overlay; bounded reader growth; disk and
output limits; cancellation and process termination; sealed-file mutations; and
daily retry plus trading consumers. The scaling fixture retains semantic hashes,
input/output bytes, elapsed time, Python allocation peaks, and sampled process
memory alongside its test output.

A synthetic scaling result proves only its declared fixture. Representative
corpus qualification must bind the exact source, sealed input inventory and
environment, preserve baseline results, and demonstrate at most 2 GiB private
memory through build, gate and publication. Production scheduling and guarded
adoption require their own receipts. No successful source test proves a repaired
historical ledger, completed daily chain, promotion readiness, or market edge.

## Update this file when

Update when revision ordering, index ownership, public APIs/CLI options,
publication behavior, resource bounds, sealed hash rules, consumer contracts,
or the reconciliation retry and barrier policy change. Run the agent documentation audit and matching owner tests.
