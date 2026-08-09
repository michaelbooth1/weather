# Open backlog — operational work with no owner

**Created 2026-08-08** by splitting it out of `STATE_OF_PLAY.md`, which had grown to 161 lines
against a ~90 cap **because it was carrying this list**. That page answers *"what is happening right
now?"*; this one answers *"what is known-broken and unassigned?"* Neither belongs in the other.

**Not the same as [`../roadmap/active-backlog.md`](../roadmap/active-backlog.md)**, which is
*generated* from the 319 numbered roadmap items and tracks feature work. This file is hand-kept and
tracks operational defects and follow-ups that missions created and nobody picked up.

Ranked. **Rank 1 is a live risk to the capture streak**; everything below it is cost, waste, or
correctness debt. Remove an entry when it lands — do not mark it done and leave it here.

---

## 1. Log rotation — NO LONGER A RISK, IT HAPPENED (2026-08-09)

**It cost 5 h 54 m of capture** (04:32 → 10:26). `PermissionError` reopening a **625 MB**
`diagnostics.jsonl` in `append_jsonl` killed the snapshot loop; the supervisor then burned its 6/6
restart budget on the same file and opened the circuit, which would **not** have self-healed for
24 h. Found only because a merge driver refused to push onto a host whose heartbeat had not
advanced. Today's streak day survived only because it fell before the 12:00 graded window.

Production hand-rotated `diagnostics.jsonl` and `observation_triggers.jsonl`, so **the live crash
risk is currently zero and nothing prevents regrowth.** `-09-35a` carries the full spec plus two
findings that change the design: **the crash mode is *reopening* a large file** (so `.jsonl`
sidecars are the danger and held-open `.log` consoles are only disk), and **the restart circuit
breaker reads the same file being rotated**, so rotation must not clear safety state.

**Below is the pre-incident entry, kept because it sized the risk correctly and was ignored.**

## 1b. Log rotation — the top uncontrolled streak risk (as filed 2026-08-08)

| File (`data/snapshots/`) | Size | Growing |
| --- | ---: | --- |
| `observation_trigger_console.log` | **1,045 MB** | yes |
| `observation_triggers.jsonl` | **747 MB** | yes |
| `diagnostics.jsonl` | **620 MB** | yes |
| `loop_console.log` | **365 MB** | yes |
| `clob_diagnostics.20260713T*.jsonl` | 505 MB | no — rotated 07-13 |
| `clob_loop_console.20260713T*.log` | 490 MB | no — rotated 07-13 |

~28 MB/day across the four live files. **An unrotated 489 MB `clob_diagnostics.jsonl` was the write
that crash-looped the CLOB loop on 2026-07-12.** Three files are now past that size and one is
**2.1x** it. The two July-13 rotations are **995 MB of dead weight** eligible for cold storage today.

**Mission `-09-35a` is written and not dispatched.** Rotating a file a live loop holds open is the
whole difficulty — on Windows the rename succeeds and the process keeps writing to the renamed
handle, so this is a loop-side change and therefore **roll-sensitive**. Do not attempt it as a
file-move.

## 2. The maker restarts all night outside its own evidence window

`daily_roll_status.json` carries `start_time_gate.start_after_local_time: "07:05"` and **no end
time**, while `evidence_classification` rejects any run started outside **07:00–20:00** local
(`counts_toward_live_forward_gate: false`, reason *"run started after active-day evidence window"*).

So overnight restarts are **non-countable by construction**, and each one still consumes restart
budget (observed 2026-08-08: 6 of 12 in the 24h window, 1h backoff between attempts) and writes a
run folder that is later quarantined.

**Verified NOT to block the 07:05 start** — 2026-08-08's first run began at exactly 07:05:02 ET with
budget to spare. **This is waste, not an outage**: quarantine churn, disk, and log growth. The gate
needs an end time symmetric with the one it already has.

## 3. Two follow-ups the `-09-43a` repair creates

1. **The parity gate cannot reach exit 0** until the known-defects fixture
   `nine_empty_base_features_09_to_14` is narrowed to `wind_group` — it still demands 9 dead fields
   and only 1 still is. **Narrowing it RECORDS the repair; it does not weaken it.**
2. **Drop `pressure` and `pressure_trend_3h` from training in the 11 F markets**, per the
   unknowable-at-serve rule (`ESTABLISHED_FINDINGS.md` §5). Note that `pressure` staying dead *at
   serve* in those markets is **correct** — METAR carries altimeter/sea-level pressure, the trained
   feature is *station* pressure, and aliasing them would pass a presence check while being false.

## 4. Start-race orphans are unreapable

The supervisor stops only the pid in its status file. `-09-45a` (merged 2026-08-08 17:57) fixes the
**maker** daily-start race; the general shape — a duplicate worker the supervisor cannot see or
reap — is not fixed. On 2026-08-07 a duplicate maker caused **430** memory-admission refusals and put
the streak day AT_RISK. `staleness_sweep.ps1` §12 *detects* it; the code fix is unowned.

## 5. A dead tombstone reads as live closure evidence

`data/snapshots/loop_status_supervisor_status.json` is `state=DEAD` with
`restart_budget_exceeded=6>=6`, but still carries a full `source_scope_files` list. **`roll_verdict.ps1`
rejects it correctly; hand analysis did not.** It is a trap for anyone deriving a roll verdict
manually — which is already forbidden, so this is defence in depth. Delete or mark the tombstone.

## 6. Supervisor hang-detection latency exceeds the fatal gap

The derived fatal capture gap is **15 minutes** (10-minute cadence × `tolerance=1.5`). A hung loop on
2026-08-08 took **~19 minutes** to be restarted, which is longer than the threshold that dooms the
day. **Detection latency must be below the fatal gap or the guard cannot save a day it notices.**
See `derived-rules-are-the-invisible-ones` — the relationship between these two numbers is written
nowhere and neither number looks wrong alone.

## 7. Revert the Windows auto-reboot block after the build window

AU policy was changed on 2026-08-03 to stop an unattended reboot breaking the streak during the
release build window. **It is still in place.** Leaving it indefinitely means security updates stop
landing. Revert once the build window closes.

---

## Update this file when

An item lands (**remove it**), a new unowned defect is found (**add it, ranked**), or an item's rank
changes because the risk moved. If an item has been here for a month, either it is not real or it is
not actually unowned — say which.
