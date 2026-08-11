# Agent report 2026-08-24 - production execution-tape capture

**VERDICT: IMPLEMENTED AND READY FOR PRODUCTION-HOST VERIFICATION, BUT THE FULL-SUITE
ACCEPTANCE CHECK IS NOT PROVEN ON THIS WORKSTATION.** The fixture-backed capture,
dedupe, rotation, gap accounting, status, and offline sizing checks pass. The required
full-suite command was run, but collection stopped with 66 CPython ABI errors because
the available interpreter is 3.12 and the repository venv's compiled dependencies are
3.11. No exchange or weather endpoint was called, nothing was armed, and nothing was
registered or scheduled.

## What shipped

`weather.market.execution_tape_capture` is an explicit operator command over the
documented public market websocket. It has no credential, wallet, signing, user-stream,
or order-placement path. Live subscription seeds come only from the retained
`config/location_market_events.json`; market discovery does not call a REST endpoint.
The offline `replay-fixture`, `sizing`, and `status` commands do not open a connection.

`weather.market.execution_tape_store` owns a single-writer, append-only evidence
boundary:

- One directory per location market-day at
  `data/snapshots/<event_slug>/execution_tape/`.
- Held-open, fsynced JSONL writers rotate before a part would exceed 64 MiB. Parts are
  numbered and immutable after rotation; no tape is rewritten or deleted.
- The dedupe key is exactly `transaction_hash`, scoped to its market-day tape. The
  first row wins. An exact redelivery is suppressed and recorded in `dedupe-*.jsonl`.
  If the same hash arrives with different identity fields, it is still suppressed,
  and both identities, both fingerprints, and the differing fields are retained as
  conflict evidence.
- A trade is admitted only if both its token ID and condition ID resolve to the same
  retained market-day seed. Missing or conflicting routes go to a bounded rejection
  tape rather than being guessed into a market.
- `gaps-*.jsonl` records every OPEN and CLOSED dark interval, including startup and
  unclean-restart gaps, with disconnect/reconnect timestamps and seconds dark. A prior
  `CONNECTED` status is converted to an explicit dark gap from its last heartbeat as
  soon as a new process opens the tape; a stopped counter cannot republish green.
- Atomic global and per-market-day status records the physical JSONL rows and byte
  counts last counted, trades written, duplicates suppressed, maximum trade timestamp
  seen, connection state, reconnects, and dark seconds. Zero trades while continuously
  connected is `NO_TRADES_CONNECTED_QUIET`; zero trades with a disconnected/open gap is
  `NO_TRADES_DISCONNECTED_NOT_QUIET`.

No supervisor, registration script, scheduled task, ensure command, service, or live
configuration was added. Starting capture remains an operator decision.

## Fixture and measured support

The committed fixture was verified before implementation:

| Measure | Value |
| --- | ---: |
| Path | `docs/roadmap/execution-tape-pilot-2026-08-10-trades.jsonl` |
| Bytes, LF-normalised | 15,967 |
| SHA-256 | `2710e5cf4d9438ac2c1362575344075f9a84da51481b2285170a84074b67e32a` |
| Rows | 40 |
| Distinct condition IDs | 11 |
| Rows with `transaction_hash` | 40 of 40 |

The retained pilot report covers one date/time cluster: a single 30-minute evening
window, across 3 location markets, 11 condition markets, and 66 token IDs. There is no
date replication, so crossed date x market clustering and a defensible inferential
interval are not estimable. No confidence interval or significance claim is made. The
counts below are deterministic fixture measurements; the daily and annual values are
planning extrapolations only. No data is pooled across the 2026-07-31 boundary.

### Storage sizing

The planning arithmetic uses the observed `79.98 trades/hour` across 3 location markets:

`79.98 * 24 / 3 = 639.84 projected trades per location market-day`.

| Basis | Bytes/trade | Bytes/location market-day | Bytes/day, 12 markets | GB/year, 12 markets |
| --- | ---: | ---: | ---: | ---: |
| Committed LF fixture, 15,967 / 40 | 399.175 | 255,408.132 | 3,064,897.584 | 1.118688 |
| Pilot's as-captured CRLF tape, 16,007 / 40 | 400.175 | 256,047.972 | 3,072,575.664 | 1.121490 |
| Offline replay through the production trade-row envelope | 934.175 | 597,722.532 | 7,172,670.384 | 2.618025 |

The writer-envelope row includes receive/session/seed/schema/raw-hash provenance, so its
trade JSONL footprint is the conservative implementation number for this code, not the
~400-byte wire-row number. Fixed seed/gap/status files and any future duplicate or
rejection rows are additional, small overhead. The envelope replay used the fixture route,
so real event-slug lengths can move it slightly.

**79.98/hour is one 30-minute evening window, not a day.** Overnight and
pre-settlement rates are unmeasured. None of the annual figures above is a stable annual
run rate. At the stated 151.4 GB free and -10.7 GB/day host trajectory, exhaustion still
lands around 2026-08-24; even the writer-envelope extrapolation is only about 7.17 MB/day,
so this capture does not materially move that disk cliff, but it also does not cure it.

## Is the documented channel sufficient?

Yes for the blocker this mission names: market-wide execution occurrence, condition/token,
price, size, side, exchange timestamp, and transaction hash survive the public
`last_trade_price` channel, and reconnect delivery can be audited. That is enough to build
the missing market execution tape and measure trade intensity around candidate maker
quotes.

It is **not sufficient by itself** to prove that a trade filled one of our quotes. The
public event has no local order ID, owner identity, maker/taker attribution, queue
position, or lifecycle link. A future claim about our own fill rate or queue position must
join separately retained order-lifecycle evidence; this module does not manufacture that
attribution and no credentialed path was added.

## Verification

Commands run on the workstation, without installing packages:

| Check | Result |
| --- | --- |
| Fixture capture tests plus new schema lookup | **PASS: 11 passed in 0.27 s** |
| Full `pytest -q` suite | **NOT COLLECTED: 66 collection errors in 4.06 s** |
| `compileall -q app src tests` with an isolated pycache prefix | **PASS** |
| `python -m weather.operations.agent_docs_audit` | **PASS: 18 agent files, 775 Markdown files** |
| Direct execution-tape storage-class classification | **PASS** |

The full-suite collection errors are environmental, not test failures: bundled Codex
Python is 3.12.13; the repository venv points at a removed Python 3.11 and contains
CPython 3.11 builds of scikit-learn, SciPy, Matplotlib, and PyArrow. The errors include
missing `sklearn.__check_build._check_build`, `pyarrow.lib`, SciPy `_ccallback_c`, and
Matplotlib `_c_internal_utils`. Per the handoff, nothing was installed. The production
host must run the canonical full-suite command with its working project interpreter
before acceptance.

Running all of `tests/operations/test_schema_registry.py` separately produced 6 passes
and one pre-existing source-tree audit failure for unregistered literal
`native_station_pressure_train_serve_v1`; the exact new schema lookup test passes. That
literal exists in `src/weather/calibration/feature_training_policy.py` on the base and was
not introduced or changed here.

## Roll verdict

Command (PowerShell execution policy bypass was required on this workstation):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-execution-tape-capture-2026-09-69a
```

Repository-owned verdict: **ROLL-SENSITIVE**. The script reported 10 changed files and 4
importable files after local `master` was cleanly fast-forwarded to the required
`origin/master` base `6af61e8d`:

| File | Script-derived closure verdict |
| --- | --- |
| `docs/operations/OPERATIONS_DESIGN.md` | Free by contract (documentation) |
| `docs/operations/data-storage-class-contract.md` | Free by contract (documentation) |
| `docs/roadmap/agent-report-2026-08-24-workstation-execution-tape-capture.md` | Free by contract (documentation) |
| `src/weather/market/execution_tape_capture.py` | `free` |
| `src/weather/market/execution_tape_store.py` | `free` |
| `src/weather/operations/storage_classes.py` | `free` |
| `src/weather/schema_registry_recent_data.py` | **ROLL -> `clob_loop`, `loop`, `observation_trigger`** |
| `tests/market/test_execution_tape_capture.py` | Free by contract (test) |
| `tests/operations/test_schema_registry.py` | Free by contract (test) |
| `tests/operations/test_storage_classes.py` | Free by contract (test) |

The script also reported dormant `clob_enrichment` at 348.4 hours old as fully subsumed
by the live closures. The schema-registry change is additive-only: five new `SchemaSpec`
entries were appended and no existing registration or behavior was changed. This remains
a roll-sensitive branch and must use the 01:00-04:00 quiet-window merge procedure; it must
not merge in the 12:00-18:00 graded window.

## Production-host reproduction

From `C:\Users\Michael\Documents\github\weather` with the production project
interpreter:

```powershell
# Fixture integrity.
Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\execution-tape-pilot-2026-08-10-trades.jsonl

# Offline sizing; no connection is opened.
.\venv\Scripts\python.exe -m weather.market.execution_tape_capture sizing `
  --fixture .\docs\roadmap\execution-tape-pilot-2026-08-10-trades.jsonl `
  --pilot-report .\docs\roadmap\execution-tape-pilot-2026-08-10-report.json

# Offline writer replay; creates only the named scratch evidence directory.
.\venv\Scripts\python.exe -m weather.market.execution_tape_capture replay-fixture `
  --fixture .\docs\roadmap\execution-tape-pilot-2026-08-10-trades.jsonl `
  --snapshots-root C:\tmp\weather-execution-tape-09-69a-replay

# Required acceptance check on the production host.
.\venv\Scripts\python.exe -m pytest -q

# Read last-counted status after any future operator-authorized run.
.\venv\Scripts\python.exe -m weather.market.execution_tape_capture status
```

The following is the explicit live command supplied for operator review. It was **not**
run here; running it starts read-only capture and is the operator's decision:

```powershell
.\venv\Scripts\python.exe -m weather.market.execution_tape_capture capture `
  --event-metadata .\config\location_market_events.json `
  --market all
```

## What was not done

- No exchange endpoint or weather endpoint call from the workstation.
- No order placement, credentials, wallet, signing, user stream, or maker identity path.
- No task registration, scheduling, supervision, arming, production write, restart, merge,
  or production working-tree mutation.
- No serving-floor, frozen-protocol, settlement, or `high_so_far` change.
- No alpha/ledger decision spent or allocated: alpha remains **7 of 20 spent, 13
  available**. Decision 10 remains **RETIRED** and unassigned.
- No claim that the public channel attributes a trade to one of our maker orders.
- No stable-day or stable-year claim from the 30-minute pilot.

## Git identity

- Branch: `codex/workstation-execution-tape-capture-2026-09-69a`
- Required base: `origin/master` at `6af61e8db2ccc45b52d746dc2b4fd4e464e726a5`
- Implementation commit: `d4c4dff6653ff76dbb6e219d2587aa21a35606c9`
