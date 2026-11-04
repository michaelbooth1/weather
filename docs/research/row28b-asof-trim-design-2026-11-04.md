# Row-28b forward inputs: the (a) export-side as-of-capture trim, design note (no code)

Status: **APPROVED by master 2026-11-04 (about 11:15) and BUILT** on `claude/r28b-input-trim-20261104`, with the
rulings in §8 (which override the text above where they differ) and the build in §9. Designed by lane L16
(workstation, non-capture), 2026-11-04, from origin/master `b6c8f40fd1ba7659f7bd3d0513a52d02aad0989d`. Nothing is
scheduled or pulled.

How it was written:

- Only code and rule text were read. No bundle, export, snapshot, label, price, outcome or panel file was opened
  or listed.
- No B-bound file is edited. `mg2_input_export.py`, `mg2_inputs.py`, `mg2_input_allowlist.py`, `mg2_composite.py`,
  `r0_ols_floor_challenger.py` and `scripts/ops/mg2_input_export.ps1` were read at origin/master only, as design
  references.
- The 343b emitter (`weather.calibration.yearround_refit`) was read at
  `claude/item343b-yearround-module-20261103` @ `c2368cddd`.

Authority:

- DECISION_LOG 2026-11-04 (owner, "approve all recommendations"), item (5).
- The reserved-window row-28b row.
- 343b design §10 (DECIDED).

These allow the workstation (WS) to hold full-day input bundles for local target dates >= 2026-12-17. Only the
sha-pinned 343b emitter may read them, and agents see names, sizes and shas only. The (a) as-of-capture trim is
"built as defence in depth". The row also narrows row-28b to "reads labels only, and only for its scored window
2026-12-17..2027-01-30". **This design assumes no read of any kind past 2027-01-30** (§7).

## 1. What the trim is for, and what it must not change

Today's MG-2 bundle for target date D is cut once, at local midnight ending D in America/Los_Angeles
(`mg2_input_allowlist.export_cut_utc`), and only by capture time. That leaves four kinds of outcome-proxy
(label-equivalent) bytes on the WS that the 343b emitter never needs:

1. **Late snapshots of D.** METAR rows travel whole in every `replay_inputs.jsonl` record. A record captured late
   on D carries nearly the whole local day's observations. The same goes for the late `features_long.csv` rows
   (`high_so_far`, `trusted_current_max`) and the late `snapshots_long.csv` model probabilities.
2. **D+1-morning captures of D's own folder, for eastern markets.** The LA cut is 03:00 ET on D+1, so these
   markets' folders keep captures from after their own local day ended.
3. **`prev_day/<slug D-1>/metar_rows.jsonl`.** This is D-1's last snapshot captured at or before D's LA cut, so
   it carries D-1's whole day. It can also carry D's own early observations if D-1's folder was still capturing
   during D.
4. **NBM manifest rows of the D-1, D and D+1 folders captured after the last snapshot that could use them.**
   These are forecasts, not outcomes, but no emitted row can use them.

**The goal.** Keep only what the 343b emitter can use for a scored row. That means every snapshot with
`captured_at <= T*`, the last scored cutoff of (market, D) (§2). `prev_dmax` ships as one scalar per market and
date, or not at all (§4), instead of the full `prev_day/` record.

**The invariant (acceptance criterion).** The trim is defence in depth, so it must not change what row-28b
measures. For any batch, `yearround_refit emit` on the trimmed inputs must produce:

- a `shadow_rows.jsonl` byte-identical to emission on the untrimmed inputs;
- the same set of hole (market, date) keys in `emit_holes`.

Section 3.3 lists exactly which receipt fields may differ (stats only). If the invariant cannot hold for a date,
the trim refuses that date. It never ships a silently different input.

## 2. The last scored cutoff, T*(market, D)

**The emitter's gate** (`yearround_refit.shadow_rows`, the same as `mg2_p3d_n.emit_rows` under `as_of_capture`)
admits a snapshot when all of these hold:

- its captured `cutoff_hour` is in `INTRADAY_CUTOFF_HOURS`, which is (7, ..., 20) at origin/master;
- `local_hour >= cutoff_hour`;
- the date is in Dec 17 – May 31 coverage;
- the snapshot has a usable NBM mean and an as-of-capture replay observation.

Only hours 13–16 have a fit (prereg: `hours: 13, 14, 15, 16`). `serve_distribution` returns None at 17–20, which
`stats.no_fit_for_hour` counts. The replay record used is the latest one captured at or before the snapshot's
own capture (`as_of_capture`), and `scan_replay_as_of` reads observations as of that instant.

**Definition.** Set H_LAST = 16, the last scored hour. Then

    T*(m, D) = max captured_at_utc over the snapshots s of market m's D folder with
               int(cutoff_hour(s)) <= H_LAST  and  local date of captured_at(s) == D

`cutoff_hour` is the captured effective WU print cutoff from `features_long.csv` (the field `mg2_inputs.build`
copies into the layout). It is never recomputed from wall-clock time. That keeps the trim on the bound cutoff
semantics, so it adds no cutoff logic of its own.

**Why this is safe for the rows.**

- Every snapshot that yields a shadow row has a cutoff hour of at most 16, so it is captured at or before T*.
- Every replay record that row's as-of lookup can select is captured at or before that snapshot, and so at or
  before T*.
- So no input of any emitted row is removed, and the rows are byte-identical.

**What it does leak.** Snapshots captured at or before T* whose cutoff hour is under 13 are kept, but they are
earlier, so they carry less. Non-monotone captures are also kept. Example: a WU print stall that records cutoff 16
at 19:10 local makes T* = 19:10 and keeps everything up to it. That is the price of not changing rows. A stall is
disclosed as a count (`late_t_star`, T* local hour >= 18), never cut away.

**Two hard walls**, whichever comes first:

- **W1.** T* is never after local midnight ending D *in the market's own time zone*. This removes item 2 of §1
  for eastern markets. No scored row can sit there, because the local date of any gated snapshot is D.
- **W2.** No snapshot of D can be found with an integer cutoff hour of at most 16 (`features_long.csv` missing,
  empty or unparseable). Then the date is **refused for that market**: nothing is kept for (m, D) and the manifest
  names the reason. This changes no emitted row, because the full input would give a hole there too (no snapshot
  passes the scored hours). The hole reason is covered in §3.3.

## 3. Where it runs and what it writes

### 3.1 Host side, downstream of the bound exporter, never inside it

The trim is a **new stdlib-only one-shot**, `python -m weather.calibration.r28b_input_trim` (name proposed). It
runs under its own wrapper, `scripts/ops/r28b_input_trim.ps1`, on the capture host.

- **Input.** Only the already-published MG-2 bundle: `<repo>\data\exports\mg2-inputs\<D>\`, verified first against
  its `manifest.json.sha256`, `manifest.json` and `<D>.SHA256SUMS`. It opens **nothing under `data\snapshots\` or
  `forecast_payload_cas\`**, so it adds no read of the capture tree. It cannot race a capture writer, and it needs
  no quiet guard or shared-read handle.
- **Imports.** The bound `mg2_input_allowlist`, read-only, for `classify_path`, the projections, the `*_problems`
  self-checks, `slug_for`, `parse_slug` and `allowlist_sha256()`. It does not import `mg2_input_export`. It never
  edits `mg2_input_export.py`, `mg2_inputs.py` or `mg2_input_allowlist.py`. It does not change
  `scripts/ops/mg2_input_export.ps1`, which is on the B-bound list.
- **Output.** Only `<repo>\data\exports\r28b-inputs\`:
  - `<D>\`, published by an atomic rename from `.<D>.partial`, as the exporter does;
  - `<D>.SHA256SUMS`;
  - `<D>.prev_dmax.json`, only if §4 is switched on;
  - the wrapper's run receipt under `_runs\`.

  It refuses an output inside the capture tree or inside `mg2-inputs\`. The MG-2 bundle is never modified, moved
  or deleted.
- **Dates.** The local target date D must be:
  - inside the window master sets, by default the scored window 2026-12-17..2027-01-30 (§7);
  - after D's LA export cut, and after MG-2 has published D;
  - no earlier than 2026-12-21. The trim and the first pull both start at the first emission batch, so no
    row-28b artefact exists for any date before then.
- **Admission.** The run is light: a re-read of a published bundle of a few MB, streamed, with flat memory.
  Even so, it runs where the exporter does:
  - inside 00:30–09:00 America/Toronto;
  - under the shared workload lease (`Enter-WeatherHeavyWorkloadLease -Workload r28b_input_trim`);
  - after the exporter's 04:15 run and its 07:00 retry, for example at 07:45;
  - with the same host-identity, memory-evidence and 5 GiB free-space refusals, and the kill-on-close job.

  It is a manual one-shot first. Registering it as a scheduled task needs the owner's yes and its own
  registration review, and nothing here registers anything.
- **Roll class.** No capture loop imports it, and the module refuses a production importer with the
  `mg2_p3d_n`-style frame walk. The verdict comes from `scripts\ops\roll_verdict.ps1 -Branch <b>` at review,
  never by hand.

**Rejected alternatives.**

- **(i) A trim flag inside `mg2_input_export`.** It edits a B-bound file and changes MG-2's bound bytes.
- **(ii) A second exporter that re-reads the capture tree.** It duplicates the bound reader, adds capture-tree
  reads, and creates a parity hazard against MG-2's bundle.
- **(iii) A WS-side trim.** The full-day bytes would already be on the WS. Defence in depth must be export-side.

**Dependency (master).** The trim consumes MG-2's published bundle, so `WeatherMg2InputExport` must keep running
for every row-28b date. The exporter already accepts any D >= 2026-10-28.

- If MG-2's task stops first, the fallback calls the bound `mg2_input_export.export()` as a library from the trim
  wrapper. It writes a **host-private** staging bundle under `data\exports\r28b-inputs\_source\<D>\` that never
  leaves the host and is deleted after the trim publishes.
- That is still read-only use of the bound module, but it is a capture-tree read by row-28b's own run, so it
  needs master's ruling (Q2).

### 3.2 What the trimmed bundle holds

It keeps the MG-2 bundle format: schema `mg2_input_bundle/1`, the same allowlist sha, the same paths. So the
existing pure verifier `mg2_inputs.verify_bundle` and the existing layout builder `mg2_inputs.build` accept it
unchanged, with no new receiver code path. The only differences:

| MG-2 bundle path (D) | Trimmed bundle |
| --- | --- |
| `snapshots/<slug D>/replay_inputs.jsonl` | records with `captured_at_utc <= T*(m, D)` only; each kept record is byte-identical to the MG-2 line (no re-serialisation) |
| `snapshots/<slug D>/snapshots_long.csv`, `features_long.csv` | header plus rows with `captured_at_utc <= T*(m, D)`; kept lines byte-identical |
| `snapshots/<slug D-1|D|D+1>/forecast_payloads.jsonl` (NBM rows) | rows with `captured_at_utc <= T*(m, D)` only |
| `forecast_payload_cas/sha256/<hh>/<sha>.blob` | only blobs still referenced by a kept NBM row; re-hashed on copy |
| `prev_day/<slug D-1>/metar_rows.jsonl` | **dropped**, never copied (§4) |
| `manifest.json` | rebuilt (§3.4); the files list is re-hashed and re-counted |

A market refused under W2 has no files for D. Its manifest entry reads `present: false` with reason
`r28b_no_scored_cutoff_snapshot`.

### 3.3 Proof of the invariant, and the receipt fields that may move

**Synthetic, in the archive shard.** One synthetic forward window builds an MG-2-format bundle and covers:

- a stalled cutoff;
- an eastern market with D+1-morning captures;
- a market with only 17–20 cutoffs;
- a missing `features_long.csv`;
- an NBM row after T*.

On that window, `mg2_inputs.build` followed by the 343b `shadow_rows` and `emit_holes` must give:

- byte-identical rows, full against trimmed;
- an identical hole key set;
- receipt differences only in the fields below.

**Fields that may differ, by construction:**

- `stats.outside_cutoff_hours`, `stats.no_fit_for_hour` and `stats.replay_hours` counts;
- the emit receipt's `snapshots_sha256` and `replay_sha256` (different input bytes);
- `source_presence.gated_market_dates`;
- for a (market, date) whose only gated rows in the full input were at hours 17–20, the hole reason moves from
  `no_row_served` to `no_snapshot_at_a_scored_cutoff`. Both are 0-row holes.

**One live risk.** `refuse_absent_emit_sources` is driven by the gated set. On the full input, a batch can refuse
on a (market, date) whose gated rows are all at 17–20 and lack an observation. On the trimmed input the same batch
would pass. That is a refusal difference, not a row difference. Two fixes, for master's choice (Q1):

- **(a), recommended.** The 343b emitter gates on the state's fitted hours (13–16) instead of
  `INTRADAY_CUTOFF_HOURS`. Every stat and refusal is then trim-invariant. This is a change to L56's module under
  review, not a B-bound file.
- **(b)** Keep 17–20 in the gate and set H_LAST = 20. The trim then keeps everything up to cutoff 20, which leaks
  four more hours.

**Real data.** Run only on dates master already allows, with counts and sha equality only, no value printed.

- **Option 1.** On development-window MG-2 bundles (target dates <= 2026-09-28), if master holds them on the WS:
  1. trim them on the WS with the same module, as a test harness only;
  2. run `shadow_rows` with the C5 coverage window on full and trimmed inputs;
  3. compare the rows' sha and the hole sets.
- **Option 2.** If no such bundles exist, the synthetic proof stands alone. The first real batch (12-21) then has
  no full-input twin on the WS, by design.

### 3.4 Manifest and host receipt (names, shas and counts only)

**The manifest** copies these keys from the MG-2 manifest:

- `schema`, `target_date`, `export_cut_utc`, `allowlist_sha256`, `exporter_sha256`, `host_repo_head`;
- `read_mode`, `min_quiet_seconds`;
- `markets`, as amended by W2.

It does **not** copy `market_price_coverage`, `book_coverage` or `coverage_counts`, even if a manual run had set
them. It adds an `r28b_trim` block:

- the trim schema (`r28b_input_trim/1`);
- the trim module sha;
- the source MG-2 `manifest.json` sha, plus the `<D>.SHA256SUMS` sha;
- H_LAST, and the W1 and W2 rules by name;
- per market: T* as an instant, the T* local hour, `late_t_star`, and the reason when refused;
- per file: rows kept and dropped;
- the blob counts: referenced, copied, dropped;
- `prev_day: "dropped"`, or `"prev_dmax_scalar"` under §4.

T* and capture instants are capture metadata, not outcomes.

**The wrapper's run receipt** (`r28b_input_trim_run/1`) holds:

- the exit code and the published flag;
- the source and trimmed manifest shas;
- `finished_utc` from the host clock.

On the day of each trim, master receives the manifest shas with a host timestamp. That is what lets a late
weekly pull (§5) prove the bytes were fixed by the host on D+1.

**Self-checks** that refuse the date (nothing is published):

- every kept record passes the allowlist's `*_problems` functions;
- every kept line is byte-equal to its MG-2 source line;
- no kept row has `captured_at_utc > T*`;
- the trimmed bundle passes `mg2_inputs.verify_bundle` logic. This is re-implemented as a stdlib check on the
  host, because `mg2_inputs` imports `mg2_composite`, which refuses on the capture host. The receiver runs the
  real one on the WS.

## 4. prev_dmax as a scalar instead of `prev_day/`

**Finding.** The 343b emitter does not read `prev_day/` at all.

- `shadow_rows` reads only the snapshot layout (`mg2_p3d_n.SNAPSHOT_COLUMNS`) and the D folders'
  `replay_inputs.jsonl`.
- `prev_day/` feeds only MG-2's L6 nowcast: `mg2_composite._prev_day_last_rows` → `l3.routine_dmax` →
  `prev_dmax`.
- `mg2_inputs.build` never opens it either.

So the trimmed bundle drops `prev_day/` outright (§3.2).

**Recommendation: ship no prev_dmax by default.** An outcome-proxy scalar with no reader is the opposite of
defence in depth. Two more reasons:

- D-1's max is itself an outcome proxy for D-1.
- For D = 2026-12-17, D-1 = 2026-12-16 lies *outside* the row-28b line, under the general post-09-29 embargo.
  So shipping that value needs a ruling (Q3).

**If master wants it shipped** (a later row-28b consumer, or symmetry with MG-2), the spec is:

- **File.** `<out>\<D>.prev_dmax.json`, beside the bundle and outside its allow-listed tree, so the existing
  receiver's "no unlisted files" check is untouched. Schema `r28b_prev_dmax/1`, one entry per market:
  - `value` (float, or null with a reason);
  - `source_snapshot_captured_at_utc`;
  - `rule`;
  - `routine_rows`.

  Its sha goes into the trimmed manifest's `r28b_trim` block.
- **Source snapshot.** D-1's last snapshot captured **at or before local midnight ending D-1 in the market's own
  time zone**. This is not the LA cut of D, so none of D's own observations ride along. It is stricter than MG-2's
  bundle choice, which `mg2_composite` already guards at serve time with `prev_dmax_after_snapshot_days`. The
  difference is disclosed, and it matters only if the two are ever compared.
- **Value.** `routine_dmax` semantics: modal-minute routine rows that are non-COR, on local D-1, at least 20 of
  them, half-up max. The host module is stdlib-only and cannot import `r0_ols_floor_challenger` (B-bound, with
  numpy and pandas). So it carries a stdlib port of the METAR temperature parse and `routine_dmax`, and a WS test
  proves that port equal to `l3.parse_captured_metar` + `l3.routine_dmax` on synthetic METAR, including COR, the
  T-group, missing groups, a day boundary and below-20-row days. That is a parity surface, which is one more
  reason for the default "off".
- **No source snapshot, or fewer than 20 routine rows.** `value: null` with a reason. Never a fallback.

## 5. Transfer to the WS (designed here, not done here)

- **When.** No pull of any kind before the first emission batch, 2026-12-21. This design performs no pull. Pulls
  are per weekly batch, at most the dates `emit` will read in that batch.
- **What.** Only `data\exports\r28b-inputs\<D>\` and its `<D>.SHA256SUMS` (and `<D>.prev_dmax.json` under §4).
  Never `data\exports\mg2-inputs\<D>\`, for row-28b.
  - If the MG-2 lane separately holds full-day MG-2 bundles for the same dates under its own carve-out, they stay
    in MG-2's inbox.
  - The 343b `emit` command line and its receipt name the row-28b inbox. The emit receipt's `snapshots_sha256`
    and `replay_sha256` must trace to a trimmed manifest.
- **Receiver.** `mg2_inputs.receive` has a D+1 deadline (`deadline(day)`: 23:59 WS local on D+1) and writes MG-2's
  ledger `C:\t\mg2\forward\input_receipts.jsonl`. A weekly row-28b pull misses that deadline by design, and must
  never write MG-2's ledger. Row-28b therefore needs a thin WS-side verifier in the new module that:
  - calls the pure `mg2_inputs.verify_bundle(root, day)` unchanged;
  - adds `r28b_trim` checks: the trim schema, the trim module sha pinned in the forward prereg, and T* and
    `captured_at` consistency, counts only;
  - checks that the trimmed manifest sha equals the one master logged from the host on D+1 (§3.4), which replaces
    the D+1 deadline as the anti-tamper rule;
  - appends to its own ledger, for example `C:\t\r28b\forward\input_receipts.jsonl`.

  It reuses `mg2_inputs.build`, with its v2 parser pin, to make the layout that `emit --snapshots` reads.
- **Agents.** Agents see names, sizes and shas only. Only the sha-pinned 343b emitter (and `mg2_inputs.build`,
  which feeds it) reads trimmed bundle content.

## 6. Tests (when code is authorised)

All tests are synthetic and focused, run through `workstation_heavy.ps1 -Queue` with a flat, deleted `--basetemp`.
New test files go into the archive shard (`windows-qualification.yml` plus `EXPECTED_SHARDS`).

- **T\* computation:**
  - integer and string cutoff hours;
  - an unparseable cutoff hour, ignored for T* (never treated as <= 16);
  - the local-date rule across DST;
  - W1 for every US10 time zone, plus Denver for completeness;
  - W2 refusal.
- **Trim byte-equality:** kept lines are identical to the MG-2 lines; nothing captured after T* survives in any
  of the five file kinds; blob pruning; `prev_day/` is never copied.
- **The invariant (§3.3):** row bytes and hole keys; only the listed receipt fields move; plus whichever Q1 fix
  master picks.
- **Manifest:** only the allow-listed keys are carried over; the coverage blocks are refused; the `r28b_trim`
  block is complete; `verify_bundle` passes on the trimmed bundle, and fails on a hand-edited kept line or an
  extra file.
- **Boundaries:**
  - the trim refuses an input outside `data\exports\mg2-inputs\`, an output inside the capture tree or
    `mg2-inputs\`, a date before 2026-12-21 or outside the window, and a reparse point on any path component;
  - the trim refuses a production importer;
  - a static AST ratchet: the trim imports only the standard library and `mg2_input_allowlist`, and nothing
    imports it except tests and its wrapper.
- **The wrapper:** `-PlanOnly`, window refusal, lease, teardown before lease release, and the receipt.
- **§4, only if switched on:** port parity against `l3` on synthetic METAR; the own-time-zone midnight source
  rule; the null reasons.
- **WS verifier:** a late pull past MG-2's deadline is accepted only with the host-logged manifest sha; MG-2's
  ledger is never written.

## 7. Scope against the 2027-01-30 label line

- Row-28b reads labels only for 2026-12-17..2027-01-30, and the trim never reads a label at any date.
- The trim's default date window is therefore **2026-12-17..2027-01-30**, starting no earlier than 12-21 by run
  date. The trim refuses any D outside the window.
- The prereg's emission window runs to 2027-05-31, but the dates after 2027-01-30 stay closed to row-28b unless a
  frozen amendment and a new owner line say otherwise (reserved-window row-28b row). This design therefore plans
  no trim, pull or emission input for 2027-01-31 or later.
- If master later rules that emission-only inputs past 01-30 may travel, only trimmed bundles travel for those
  dates (Q4), and the window constant is the only change.

## 8. Master's rulings (2026-11-04), as built

The questions as first put are kept in the history of this file; the answers below bind the build. Where a
ruling differs from the text above, the ruling wins.

- **Q1, superseded by master's later ruling of the same day.** The 343b `shadow_rows` row gate and its stats
  counters stay at `INTRADAY_CUTOFF_HOURS` (7..20); H_LAST stays 16. Exactly the counters named in §3.3
  (`outside_cutoff_hours`, `no_fit_for_hour`, `replay_hours`) may differ between full and trimmed inputs, and the
  invariance receipt lists them by name (`stats_allowed_to_differ`). `shadow_rows` byte-equality, hole-key
  equality and an equal `refuse_absent_emit_sources` outcome stay hard: any other difference is a STOP (§3.3's
  live risk is therefore caught, not fixed).
- **Q2.** No library use of the bound exporter. A date whose MG-2 bundle is not published by its D+1 deadline
  (09:00 America/Toronto on D+1), or whose `export_finished_utc` is later, is a NAMED hole:
  `r28b_hole_not_exported_by_deadline` or `r28b_hole_exported_after_deadline`, written once to
  `data\exports\r28b-inputs\_holes\<D>.json` and disclosed. A bundle that turns up later never replaces it.
- **Q3.** `prev_dmax` is OFF and not built. `prev_day/` is dropped (§4's scalar spec is not implemented).
- **Q4.** No inputs after 2027-01-30. The trim and the verifier hard-refuse every D outside 2026-12-17..2027-01-30.
- **Q5.** No scheduled task. Master runs `scripts\ops\r28b_input_trim.ps1` weekly on the host as a detached,
  lease-held one-shot inside 07:30–09:00 (after the 04:15 and 07:00 exports), and logs each trimmed manifest sha
  with the host timestamp for the workstation verifier. The wrapper carries no registration code.
- **Q6.** The 10-29..11-02 bundles are not used. The 2026-09-28 dev rehearsal bundle cannot be used without a new
  date-override path: the trim's Q4 window refuses it, and the 343b emitter refuses it too (its forward-receipt
  window, and its Dec 17 – May 31 coverage gate would emit no row). No override is added. The invariance
  therefore runs on the **first forward batch**: `r28b_inputs compare` emits on the full and on the trimmed inputs
  and reports booleans, counts and shas only. Unequal is a STOP (a STOP marker beside the row-28b ledger), and
  nothing emits from the trimmed set until master rules (`r28b_inputs gate`).

## 9. Build (L16, 2026-11-04)

- `src/weather/calibration/r28b_input_trim.py`: the host one-shot (stdlib plus the bound `mg2_input_allowlist`,
  read-only). It reads only `data\exports\mg2-inputs\<D>\` and its `<D>.SHA256SUMS`, verified first, and writes
  only under `data\exports\r28b-inputs\`.
- `scripts/ops/r28b_input_trim.ps1`: the host wrapper (07:30–09:00 Toronto, shared lease `r28b_input_trim`,
  capture-host identity, memory and disk refusals, pinned `-P -B` child in a kill-on-close job, run receipt).
  `-PlanOnly` touches nothing.
- `src/weather/calibration/r28b_inputs.py`: the workstation `verify`, `hole`, `compare` and `gate` commands and
  the row-28b ledger `C:\t\r28b\forward\input_receipts.jsonl` (it refuses MG-2's ledger).
- Tests: `tests/calibration/test_r28b_input_trim.py`, synthetic only, in the archive shard.
- Runbook: [operations topology](../operations/OPERATIONS_DESIGN.md), "Row-28b input trim".

Nothing here registers a task or pulls a bundle.
