# Repository health ratchets

Status: canonical. Owns static growth limits and reviewed exceptions.
Read when adding dependencies, modules, legacy names, evidence blobs or daily-chain
report inputs. Package import direction is owned by [package boundaries](package-boundaries.md).

`tests/operations/test_repo_health_ratchets.py` checks tracked files only; its
support module never imports application code or reads runtime state. Run it with
the schema, import-architecture (including maker-core), agent-doc and path-policy
audits through the host's admitted test wrapper. The full suite discovers it normally.

## Contracts

- Python modules under src (including maker_core), app, tests and tools have a
  2,000-line ceiling. Existing larger files have individual maximums in
  `tests/fixtures/repo_health_baseline.json`; reductions do not buy growth elsewhere.
- Modules not reachable from maintained operational entrypoints are named
  exceptions, not candidates for automatic deletion. Static/lazy imports, literal
  dynamic imports and module strings are traced. Schema-owner metadata is excluded
  as evidence of execution. Tests alone do not establish an operational caller.
- Retired-family tokens have per-file, per-symbol count ceilings. Legacy `_c`
  identifiers and field-name strings are frozen per file. Neither rule changes
  native settlement units or authorizes deleting historical evidence.
- Literal unsigned regexes in band/range/temperature contexts outside
  `weather.units` are frozen exceptions. New parsing uses the canonical signed
  parser. The scan handles regex aliases and module-level band patterns; it is
  not a proof about arbitrary computed patterns.
- Tracked Git blobs over 1 MiB need a named size ceiling. Roadmap data over
  250,000 bytes must carry its mission id in its filename. LFS pointers are
  measured as tracked Git bytes; the rule does not hydrate or size LFS payloads.
- Runtime third-party imports, including literal dynamic imports, must map to
  project dependencies or a named optional extra. Existing transitive or pending
  declarations have path-specific allowances and explicit reasons.
- Every literal JSON reference in daily-refresh, promotion, scoreboard and proof
  packet consumers has a reviewed producer or input/output disposition. A scheduled
  producer must be present on the daily-refresh dependency path rooted in its
  PowerShell contract. Explicit exceptions identify an owner and disposition.
  The seven D1-09 producers remain explicit unresolved inputs. No test schedules
  them, and a static code path does not prove dispatch, freshness or a successful
  runtime result. Skip flags and freshness gates retain their separate authority.

## Changing allowances

The baseline is bounded by the immutable reviewed seed commit named in the test
helper and by its previous committed revision. Ordinary edits may only remove
exceptions or lower numeric ceilings. Tighten the corresponding baseline when
removing debt; do not regenerate it from a larger current inventory to silence a
failure. Retiring a producer also requires changing its consumers or their explicit
contract, rather than leaving a stopped report looking scheduled.

A new justified exception is a deliberate governance change: document the owner,
reason and retirement route, review it, and bind a new seed explicitly. Never
silently widen the seed hash or create a blanket directory waiver. New scheduled
producer contracts can be added with their verified source path; unscheduled
exceptions remain bounded by the reviewed list.

## Update this file when

Update when a scanner's scope, thresholds, baseline ownership, dependency mapping
or report-producer contract changes. Dated findings belong in the handback report.
