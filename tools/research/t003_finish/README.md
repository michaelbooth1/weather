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
and every executor session ID until exit. No heavy start after 08:30 Toronto
on this campaign date; this runner reserves teardown before that and cannot
resume during RQ-COMMON's 09:00..19:00 block before the task deadline.

Synthetic verification, one file, no book payloads:

```powershell
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -m pytest -q tools/research/t003_finish/test_scan.py --basetemp C:\t\codex\T085\pytest-temp
```

The original internal selftest and new long-field, malformed-record, embargo,
method-identity and reproduction-gate controls are included. Remove the owned
pytest temp directory after verification. The runner's assumptions and G2's
missing execution/latency evidence remain T003's; no result is an edge claim.
