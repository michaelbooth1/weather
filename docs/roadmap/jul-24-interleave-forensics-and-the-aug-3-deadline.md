# The July 24 interleave: located, characterised, and on a hard Aug 3 deadline

Production-side forensics for the single malformed line reported in
`agent-report-2026-07-29-workstation-hash-keystone.md` (commit `ea0167a7`, unpushed at time of
writing, so this was derived independently on the production host).

## Location

`data/snapshots/highest-temperature-in-toronto-on-july-24-2026/replay_inputs.jsonl`, **line 46**,
byte offset **6,706,296**, length **162,613** bytes plus `\r\n`. `json.loads` fails with
`Expecting ',' delimiter: line 1 column 8156`.

Every other `*.jsonl` in that market-day parses clean: `components` 24,046, `variant_predictions`
17,160, `snapshots` 196, `forecasts` 196, `features` 196 — all 0 malformed.

## It is a lost write, not a formatting defect

The line is 162,613 bytes against a ~155 KB file average, so it is **not** two whole records
spliced. Structural probe: **2 record starts**, final brace depth **3** (never returns to 0), no
depth-0 close anywhere, 0 NUL bytes.

Record A was mid-write, reached `..."src/weather/sources/__init__.py"` inside its `scope_files`
array, and record B was then written at that exact point with no intervening newline. A's remaining
bytes were never written. B completes normally and terminates the line.

The decisive corroboration is the record count: **every per-instant file for that day has 196
records; `replay_inputs.jsonl` has 195.** Two records collided into one line and one instant was
truncated permanently. Record B carries `built_at 2026-07-24T05:43:41.426670-04:00`, so this
happened at 05:43 local — predawn, consistent with an age-only eviction of a still-owned lock.

Record A's visible fragment also contains, verbatim,
`"base_model_binding_reason": "no verified active-release base-model serving graph is bound"` —
the same deficit the keystone report names as one of the two reasons the current release cannot
bind Toronto. The evidence recorded its own blocker.

## Why this is a hard deadline, not a backlog item

July 24 is **inside the streak** (day 4 of Jul 21-28). A lock at ~Aug 3 covers Jul 21-Aug 3, which
includes Jul 24. Thirteen of fourteen Toronto daily files are wholly strict-readable; this one line
is the fourteenth. **If it is not resolved before the lock, the lock fails on July 24** and the
window has to be rebuilt from a later start date — pushing the first release out by however long
the next 14 contiguous complete days take, which at the historical base rate is not days.

## Three repair paths, and why the choice is not mine alone

1. **Split the line.** Recovers B as a valid record; A remains a truncated fragment. Yields 196
   lines of which one is still malformed. Does not achieve strict-readability on its own.
2. **Drop the A fragment, keep B.** Yields 195 wholly valid lines and a file that is strict-
   readable, at the cost of one instant permanently absent from the day. Admissible only if the
   point-in-time contract tolerates a documented single-instant gap rather than requiring all 196.
3. **Reconstruct A.** Its siblings (`snapshots`, `forecasts`, `features`) all retain 196 records, so
   the inputs for that instant may still exist and A may be re-derivable. This is the only path
   that restores 196/196 genuinely, and it is a code question rather than a text edit.

Path 2 is a deletion from canonical evidence and path 3 is a write to it, so neither is being taken
on inference. The choice turns on what the PIT contract requires of record count versus record
validity, which is exactly what the unpushed keystone report should settle.

**No repair has been attempted. The file is untouched.**

## The same defect class, fixed on the operations side

`C:\Users\micha\ops\mirror-weather-data.ps1` guarded single-instance with age alone
(`if ($ageH -lt 12) { exit 0 }`), meaning a mirror run exceeding 12 hours would be joined by the
next night's run, both robocopying the same tree. Replaced with a liveness-first gate: a lock whose
owner PID is alive is never evicted at any age, and age decides only when the lock carries no
readable PID. Process-name matching prevents a recycled PID from reading as a live run. Verified
against five lock states (live owner backdated 99h; dead owner fresh; no PID fresh; no PID 99h old;
no lock) — all five behave as intended.
