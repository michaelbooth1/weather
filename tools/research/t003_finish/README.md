# T003 parser completion runner

One-off continuation of the immutable T003 v4 script, SHA256
`b42a25f7d1fe4fc708059f1e2116607360a895a63b02f65e563435147cbf26cf`.
Its valuation, route choice, fee assumptions, source windows, eligibility and
output functions are unchanged; the AST control checks this explicitly.

Task-local evidence, PREREG.md, review request and receipts live in
`C:\t\codex\T085`. This runner needs the original T003 inventory and outputs
and the copied workstation book summaries; they are not clean-checkout inputs.
It never fetches or writes source data. Only 720 of the original 900 inventory
entries meet this task's September 29 cutoff; the 180 later dates are excluded
before source access. Each parsed row also passes the cutoff guard.

Parser controls raise the field limit to 1 Mi characters while imposing the
same bound on each logical record. Quoting, UTF-8, header and row width remain
strict; a malformed source stops with no completed event result. No recovery
or source normalization occurs. A syntactically valid long field does not
establish its economic validity.

After master review, copy this exact `scan.py` to the allowlisted task path
and use `run_chunk.ps1 -ReviewedCommit <full-reviewed-sha>`. `-CheckOnly` checks
pins without acquiring a heavy lease. Defaults are `-Mode scan -Start 0 -Count 30`.
Run starts 0,30,...,360 at count 30, then 390 at count 3. Run `-Mode compare`;
it verifies original report bindings and byte-identical output artifacts plus
every deterministic event result, source hashes and the original headline.
Only after that PASS may starts 393,423,...,693 run at count 30 (last count 27).
Then `-Mode aggregate` writes complete tables and completion_statistics.json,
including the registered descriptive date-clustered interval and scoped verdict.
An invalid source, changed input or replay mismatch stops; it is never a zero.

Keep each heavy invocation below 20 minutes. Exit 78 is a cooperative chunk
budget stop: retain receipts, verify completed event JSONs and resume at the
first incomplete index. Exit 65 is a fatal input/integrity error: do not skip
the event. HOLD exits 76; wait five minutes. Resource refusals retry in ten
minutes. Yield sixty seconds after successful chunks. Preserve wrapper output
and every executor session ID until exit. No heavy start 08:30..19:00 Toronto
on this campaign date. The master continuation explicitly authorizes resuming
after 19:00 on November 10; this runner retains the morning teardown reserve
and also bounds the evening lane to that local date. No live-session state
is inspected.

Synthetic verification, one file, no book payloads:

```powershell
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -m pytest -q tools/research/t003_finish/test_scan.py --basetemp C:\t\codex\T085\pytest-temp
```

The original internal selftest and new long-field, malformed-record, embargo,
method-identity and reproduction-gate controls are included, plus a real
inventory-metadata schema check (no book reads) and timing boundary tests.
The first approved invocation stopped before source reads on a missing `city`
inventory field. Its first repair accepted the raw plan but carried the
planning-only `index` into event receipts and omitted `city`. The r2 repair
returns exactly T003's input-record shape: event/date/city/path/bytes, deriving
city from the guarded slug. The metadata regression checks those records
against every original first-393 event receipt. The completed r1 first-30
results stay immutable in `out/stream_events_v4`; r2 starts a fresh replay in
`out/stream_events_v4_r2` and does not reuse those results. Output-only diagnosis
showed the r1 schema differences were the only deterministic JSON differences
and all 90 retained gzip/hour/episode artifacts were byte-identical to T003.
That diagnosis is not the registered first-393 reproduction PASS.
List retained pytest temp directories in the report for master cleanup.
The runner's assumptions and G2's
missing execution/latency evidence remain T003's; no result is an edge claim.

`final_reports.py` fixes the original T003 reporting scripts' task-root and
scan-pin bindings to consume this task's complete outputs. Both original
episode joins, quote-crossing diagnostics and all calculations are reused
unchanged from hash-pinned T003 source. Its `--selftest` runs both original
synthetic control suites without opening books or valuing outputs. Its real
mode requires a complete aggregate, first-393 reproduction PASS, unchanged
prereg and canonical `research_script` wrapper admission. Run it serially
after aggregation, with `-I C:\t\codex\T085\out\final_reports.py` as the
wrapper's Python arguments. The compatibility receipt records both frozen
method-source hashes and every override. It reconciles the original first-393
headline under both joins and the complete registered statistic.

The inline scanner's `completion_statistics.consecutive_episodes` is the
legacy consecutive-capture series with a 120-second gap cap; the reporting
adapter also reports the original alternative without that gap cap.
`executed_continuation.ps1` is the exact archived orchestration used with its
pinned execution commit; it is historical evidence. Use `run_chunk.ps1` with
an explicit compatible full commit for a new invocation. `check_r1_first30.py`
preserves the output-only diagnosis of the superseded r1 schema defect; it
does not declare a registered reproduction PASS or read source books.
