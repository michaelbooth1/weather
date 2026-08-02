# Pre-release audit — 2026-08-01 evening (what is actually left before release #1)

Read-only audit at 21:45. Every claim verified against live state tonight; nothing assumed from
memory. Lock lands ~2026-08-03 if Aug 2–3 stay clean; earliest build start is **2026-08-04 after
~10:00** (Aug 3 settles then — runbook §7a-bis).

## Verified green tonight

| Check | State |
| :--- | :--- |
| Streak | 11/14, day 1 = 07-21; Aug 1 captured clean (149+, zero in-window gaps); grades tomorrow |
| Release store | `artifacts/releases` absent, pointer absent — exactly what the bootstrap requires |
| Clean-tree gate | currently dirty (18:00 config refresh) — **expected**; committing drift is build step §1 |
| Mirror | one-shot fired 18:15 result 0 — workstation now holds Jul 31 labels; 04:30 cadence resumes |
| MM roll | 07:05 trigger fired (result 0) and today **counts** toward live-forward |
| Disk | 109.0 GB free — *up* from 104.9 yesterday; slope no longer the panic it read as |
| Merge queue | nothing armed; no roll-sensitive merge can fire on lock night by default |
| Build path | preselection rehearsed on real evidence; downstream rehearsed synthetically; timings known (~71 min no-retry floor) |

## F0 — THE BUILD IS ALREADY AUTOMATED, AND MY RUNBOOK MISSED IT

`scripts/ops/training_window.ps1` (~lines 229-275) contains a **self-disarming first-inactive-release
bootstrap**. The 01:00 window arms it only while all three hold: a **receipted staged PIT source**
exists, the release store is absent/empty, and no active pointer exists — then falls back to ordinary
research mode once release #1 exists.

It is **currently disarmed**: the staged root
`data/analysis/point_in_time/production_source_2026-07-16` does not exist (verified tonight). That
`2026-07-16` suffix is a fixed identifier in the script, not a live date.

**This is the better build path and it should be the primary one.** The training window stops capture
before training, so the build runs with the fleet already quiesced, in the quiet window, gated on
`point_in_time_staging_receipt verify`, and self-disarming. My runbook documented a manual 04:00 build
that reproduces all of that by hand under time pressure. Runbook corrected tonight with the arming
procedure (`staging_receipt create`, exact filenames, the log line to watch for).

Two things this also settles: the automated path passes the **staged** `replay_manifest.json`, which
independently confirms the F1 correction below; and `point_in_time_staging_receipt` has a `create`
verb, so the receipt is authored, not hand-written.

**Remaining question for build day:** whether to arm the automated path or run §3b manually. Default
to automated. Do not do both — the release-store-empty check would disarm the second, but racing them
is needless.

## Findings — the actual remaining work

**F1 — `promotion_corpus.json` is July 11: pre-boundary and stale.** Runbook §3b's example passes it
as `--point-in-time-source-replay-manifest`. Using it would cross the `2026-07-31` `rows[-1]`
boundary. The sanctioned alternative already exists: folder mode, or omitting the flag so the prelock
copies the replay manifest hash-bound by the staged source itself. **Runbook corrected tonight** —
build day must not reach for that file.

**F2 — No generator exists for the two promotion files.** `promote` requires
`--decision` and `--market-day-boundary`; the code contains only fail-closed *validators*
(`validate_promotion_decision`, `validate_market_day_boundary` in
`src/weather/operations/release_promotion.py`), the boundary proof carries a staleness limit so it
must be authored at promotion time, and the decision must declare
`release_kind: serving_identity_bootstrap` plus review and candidate-only-build proof. Today we would
be hand-writing JSON against a validator by trial and error, inside the window. **→ workstation
mission `-08-11a`** (schemas, templates, worked validation walkthrough — docs only).

**F3 — The runbook ends at promotion; cutover is undocumented.** After the pointer exists, workers
must reload/restart to bind it (`worker_release_binding`), and the whole point of release #1 — parity
restart, scorecard identity, replay-cache classification — needs a "how do we know it worked"
checklist. **→ folded into `-08-11a`**; stub section added to the runbook tonight.

**F4 — Final input check for 07-31 → 08-03 must run on this host.** Mirror lag makes the workstation
structurally too late (Aug 3 labels reach it Aug 5). No new tooling needed: **preselection itself is
the verifier** — the rehearsal proved it materializes, hash-binds, and fails safe, so build-day
ordering is simply "run preselection first and read its exclusion list"; pooled fit then names any
F-coverage gap ~25 min in. Runbook §7b annotated.

**F5 — OS reboot still pending** (uptime > 10 days, 5 power-loss incidents/90 d on record). The last
safe slots are tonight after grading cover or tomorrow's 01:00–04:00 quiet window — outside
12:00–18:00 an out-of-window gap costs nothing and the S4U fleet self-recovers. **Operator decision;
recommended before the final two streak days.**

**F6 — The 01:00 training-window task commits config drift locally without pushing** every night.
Standing morning duty until the race is fixed post-lock: push the orphan (one
`Start-ScheduledTask WeatherOneShotPush`) so origin stays in sync and any armed merge is not
silently aborted (the 2026-08-01 three-merge failure was exactly this).

**F7 — The catastrophic-slice threshold is still open — deliberately.** It must be frozen after the
lock but **before** the continuation candidate exists. Working proposal on record: no protected slice
may regress by more than the pooled improvement. Not pre-release-blocking.

## Lock-day checklist (mechanisms now all known)

1. Both clocks read **14 from 2026-07-21**: `streak.ps1` and
   `release_admissibility_clock grade-range` (ledger root `data/settlements`), morning of Aug 4.
2. Snapshot `clock.json` + receipt hashes as lock evidence.
3. Flip the observed-floor monitor to fail-closed: add its flag to the daily-refresh scheduled task
   arguments (the CLI documents "defaults off during the temporary pre-lock alert-only posture") —
   scheduler re-registration, roll-free for capture, operator-approved as part of the ratified
   checklist.
4. Commit the config drift and **prove** `git_dirty is False` before spending window time (§1).
5. No roll-sensitive merge armed (already true). Held for after the lock: the gate harness
   (`b9c62ead`) and the empty-manifest diagnostic fix (`b28efa54`), both quiet-window merges.

## What is deliberately NOT being done before release #1

Merging the gate harness or diagnostic fix (roll-sensitive, zero pre-release value); any retrain or
candidate work (blocked on release identity); disk reclaim (parked; pointer unlocks 32 GB + tiering);
backups (deprioritized); MM promotion-gate relaxation; marine backfill (needs an artifact that
declares the columns); the workstation resume handoff (fires only when the pointer exists and is
verified).
