# R28b item 4: presence-only T+2 check (draft; not run)

- **Status.** Dated research note, lane L59, WS, 2026-11-03. **Drafted and self-tested on synthetic data only. Not
  run.**
- **Source.** Master ruling R28b, `C:\t\rulings-20261101\rulings.md` (sha256 `2499b5af…b2c44d`):
  - `:477`: "Decide go/no-go on a T+2 sibling from the census lead-2 counts and the presence check";
  - `:733`: due 11-20.
- **Go/no-go is master's** (conditions at the end of this note).

## What it measures (ruling R28b, WS brief item 4)

"Horizon +2 completeness flags and reason codes only, from the price recorder's cycle manifests, over 3 closed days.
Also: does any recorded NBM product cover D+2?"

- **The recorder.** The WS T+1 price forward recorder records events at horizons 1 and 2. It runs
  `tools/research/t1_price_forward_recorder.py` on `claude/t1-price-recorder-20261030` @ `32998ac68`, writing to
  `C:\t\t1_prices\forward\<YYYYMMDD>\`.
- **Where the T+2 flags live.** Each slot's cycle record carries `complete` and `reasons`. Reasons are
  `<market>+<h>:gamma_<status>` or `<market>+<h>:ladder_incomplete`, plus the unattributed `stop_file` and
  `events_missing` (`run_slot`). The day `manifest.json` has counts but is **not split by horizon** (`close_day`). So
  the T+2 flags come only from the cycle records.
- **What `t2_presence_check_v1.py` reports, for the 3 latest closed UTC days:**
  - **Per market:** the h=2 complete cycles, the h=2 complete top-of-hour cycles, and the h=2 reason-code counts.
  - **Per day:**
    - cycles, top-of-hour cycles and the manifest counts;
    - cycles with an unattributed reason;
    - torn and unclosed line counts;
    - gap-record counts from `gaps.jsonl`;
    - integrity: the manifest `file_sha256`, and every cycle's `rows_sha256` recomputed from raw bytes.

## Price-blind design

- **Event rows are never parsed.** Event rows hold the Gamma Yes prices and book levels. The check selects cycle
  records by their sorted-key prefix `{"complete": `, parses only those, and keeps only `CYCLE_FIELDS`. Event rows
  are only hashed as bytes.
- **Manifests** are projected to counts, horizons and shas.
- **Output.** One result JSON under an explicit `--out` outside the root, never overwritten. The self-test asserts
  that no event-row field reaches it.
- **Light.** About 12 MB per day at 96 cycles, according to the recorder note. Three days take well under a minute
  and under 1 GB. The check needs no `workstation_heavy` slot, but runs on master's go.

## Can it run now? NO, it needs master's go on the data boundary

- **Why not.** The recorder's days are all after 2026-10-30, the recorder's first day. The standing boundary is: no
  data dated 2026-09-30 or later.
  - This check reads flags, counts and shas only, never a price.
  - It still opens forward-period files, and selecting the days needs a listing of the day-folder names.
- **What was done.** Neither the root nor any day folder was listed or opened. Whether 3 closed days exist is
  therefore not verified.
- **Before it can run, master must rule** whether a flags-and-counts-only read of those files is allowed.
- **Run form, if allowed (one shot, by hand, no task):**
  - `python -I tools/research/t2_presence_check_v1.py --root C:/t/t1_prices/forward --out C:/t/L59/t2check
    --today-utc <today UTC> --days 3`

## Does any recorded NBM product cover D+2? Per the recorder's documentation, yes

- **Source.** The NBM text forward recorder (`docs/research/nbm-text-forward-recorder-2026-10-30.md` on
  `claude/nbm-text-recorder-20261030`) records **NBH** (1-25 h), **NBS** (3-hourly to 72 h, with TXN), **NBE**
  (12-hourly extended, with TXN) and **NBP** (TXN percentiles; not issued every hour).
- **Arithmetic for the D+2 max.** It sits in the TXN column valid at 00 UTC on D+3, which is the emitter's T+1
  convention moved one day. For a 07Z cycle on D, that column is 65 h ahead.
- **NBS and NBE** reach it from any cycle on D: 00Z on D to 00Z on D+3 is exactly NBS's 72 h.
- **NBP's maximum lead is not stated** in that note. Confirming it needs a recorded NBP block, dated after 10-30,
  so it is not done here.
  - The T+1 emitter's A1 arm is NBP (`tools/research/t1_forward_emitter.py`, pinned `5d348b75`). A T+2 A1 arm
    therefore depends on that unverified NBP lead.

## Evidence for a T+2 sibling and the go conditions (ruling R28b (4) and `:477`)

- **No dev measurement exists.** The 88a census found no complete ladder at any lead ("census 0/0/0",
  `FINDINGS_DIGEST.md:88`). Its lead-2 counts give no T+2 evidence beyond that zero.
- **Power ≥ 0.5 at its own N (rule 6) cannot be shown yet.** A T+2 contrast has no SD of its own. T+1's
  forward SD, once read, is a near-twin at a different distance (rule 19). So a stated conservative bound would be
  needed, and none is computed here.
- **A NEW emitter file is required**, never `t1_forward_emitter.py` (pinned `5d348b75`). This draft writes no
  emitter.
- **The owner's yes is required for any new daily task.** This check is one-shot and manual. It creates, assumes and
  registers no scheduled task.
