# MG-1 look-day runbook, 2026-11-03 (DRAFT)

- **Status: DRAFT by lane L16, 2026-11-03, for master review.** It is not in force, not signed and not an owner
  decision. It is the MG-1 counterpart of B-1 Clarification 6 (the B look chain), and it is due to master before
  2026-11-25. It is not a `b1-clarification-*` file, so R14's record globs do not freeze it.
- **Placeholders:** every `<PIN: …>` is a sha256 that §2 lists and master fills. Every `<…>` path or date is
  master's to fill on the day. **MISSING** marks a flag, command or producer that does not exist in the code on
  the named branches. Nothing here invents one.
- **Code read** (commands, flags and refusals are quoted from these trees, cited as `file:line`):

  | Short name | Branch | Tip |
  | --- | --- | --- |
  | look | `claude/mg1-look-scoring-r11-20261103` | `8c307dbb8e272cec4b8b30c6dd4251d2f6e4a576` (WIP) |
  | countable | `claude/mg1-countable-head2-r11-20261103` | `f118e0d8072dae85fc30b70a32bcdb0d54f1ce3e` |
  | R24 base (combo C) | `claude/r24-venue-label-audit-20261101` | `513475d31584dccb6222edec9eee31630aa8a761` |
  | freeze-keys | `claude/r24-freeze-keys-20261103` | `a1676b09f5db89dda5f02a4da083d0b1352f36e4` (parent: the R24 base) |

  `mg1_look.py` lines are on look, `mg1_countable.py` lines on countable, and `venue_label_audit.py` lines on
  freeze-keys.
- **Rulings cited:**
  - Master rulings 2026-11-01 (R11, R24, C9, C10, C14): WS copy `C:\t\rulings-20261101\rulings.md`, sha256
    `2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d`, cited as "rulings:<line>".
  - Master rulings 2026-11-03 (A1-A14, T1-T5): host file `C:\tmp\agent-kit\rulings-20261103-mg1-b.md`, sha256
    `28c4f298c9d128189468ab62562ebb79e055a6c42328315c8182178642b01906`. It is quoted from the WS coordinator's
    verbatim condensed copy `C:\t\mg1-b-rulings-20261103\rulings_condensed.md`, sha256
    `f1ded718b1fc8e7fc5598b59b12f6557276abfd2b341accaa7d51ff44cbad016`, and cited as "11-03:<line>".
  - Master's 2026-11-03 messages, cited by ruling name:
    - Q1: `skipped_dates` means T2; a market-day in neither list, or any inconsistency, holds.
    - Q2: the `label_dates` key list.
    - Q3: `A1_MIN_NEGATIVE_MARKETS`.
    - B2: the pin timetable (mg1_look 11-12/13).
    - "Unexplained absence holds".
- **History only:** nothing in this draft comes from an outcome, label, price, settlement, ledger or panel value.
  It cites code and rulings only.
- **Revision 2 (2026-11-03):** this revision applies master's rulings on revision 1 (`b015497a3`), cited as
  "11-03 R1" to "R8" by point number. Two builds carry them; neither is landed:
  - **[A]** `claude/mg1-look-holds-checkkeys-20261103` @ `ebf7bcda1c78cc8ea5ad1b178d1219523724bf78`, stacked on
    look `8c307dbb8`. It adds the audit-status hold, `check-keys`, held exit 4 and FREEZE_THROUGH. The entry pin
    is re-registered there at `6f17cf15cfcab686b63b298b57dfc6b58806b3748d502fd4293dc6844d5362bc`.
  - **[B]** `claude/r24-freeze-atomic-20261103` @ `f27dc81962011812a7f8d3e0c77e583791357da4`, stacked on
    freeze-keys `a1676b09f`; it lands with freeze-keys after combo C. It adds refuse-unless-OK, the atomic
    tmp-and-rename and `freeze --recover`. It is split into a new module,
    `src/weather/backtesting/venue_label_freeze.py`, so the 600-line budget of `venue_label_audit.py` is not raised.
  - Line cites marked [A] or [B] are on those tips. Unmarked cites stay on the four trees above.
- **Revision 3 (2026-11-03):** master's `--market` rulings, cited as "11-03 M1" to "M5":
  - **[A]** moves to `3f2e500e7cf982f62a67c019d1c8584acb13b096`. It adds the pre-stamp `--market` check (M3), and
    the entry pin is re-registered at `1130ece532bfb8673d68c0610aaa41ccdf3b780fe76348c26b0413a8af6fa379`. [A]
    line cites below are on this tip; cites on `ebf7bcda1` above them in the file were not renumbered.
  - **[C]** `claude/mg1-capture-price-export-20261103` @ `d3926b85c740f4c51072cdec0ce05da5f5c2f116`, on combo
    A' `a026af7f6`. It adds the host price tool `tools/research/capture_price_export.py` and the host concat
    `src/weather/calibration/mg1_market.py` (step 4a). Unprefixed [C] cites are in the price tool.
  - M1: prices gate the MG-1 verdict only through the signed materiality condition (the 00-16 served-minus-market
    gap, then the bar; A9, A5). `--market` stays required.
  - M4: B takes `--market` from the same producer, with its own layout, on B's look morning.

## 0. Rules for every step

- **Host and checkout.** Every step runs on the capture host, from the production root. The look's start marker
  and receipt live at the fixed `data/mg1_look/` path of the checkout that runs it (`mg1_look.py:11-22`, `:72`).
  B's VOID 5 compares those bytes (`receipt_problems`, `mg1_look.py:195-227`).
- **Lease and window.** Run each step 00:30-09:00 under `Enter-WeatherHeavyWorkloadLease`, and refuse on
  `$null`. Keep clear of the 04:15, 06:50 and 07:00 tasks, the sequencer suites and Stage A (rulings:241 R24 (1);
  `docs/operations/HOST_LOAD_POLICY.md` "An agent's one-off wrapper"). Steps run serially, one at a time (C14,
  rulings:705).
  - **The lease wrapper is master's** (11-03 R5): a host `.ps1` that master owns, following the one-off pattern of
    the host load policy. It is not a repository file. **No allowlist entry** (11-03 §4 ruling (e)):
    `venue_label_audit` and `mg1_look` run only under master's lease, 00:30-09:00, through that `.ps1`.
- **Embargo.** Before the look, master reads only stdout, receipts, manifests and the counts-only audit. It never
  reads a CSV, a METAR file or a label value (R24 (2), rulings:240). After the look, the result file is read only
  as §1 step 7 says.
  - **Prices** (11-03 M2): step 4a's price tool and concat are registered steps of the look path. They run only
    on the look morning, after D45's finality, under the lease, in the same session as the look, on the host. No
    price CSV or parquet goes to the WS before the look receipt, and no agent or human views a price value.
- **Logging.** Every step's full stdout and stderr, its exit code, `Get-Date -Format o` before and after, and the
  sha256 of every file it wrote go into master's look log: on the host, `C:\tmp\suite-logs\mg1-look-<yyyymmdd>.log`,
  written by master's wrapper (11-03 §4 ruling (c)).
- **Command form.** One bare line per command. Every module runs as `.\venv\Scripts\python.exe -m <module>`.
  The look must run exactly as `python -m weather.calibration.mg1_look`, because only that `__main__` name at the
  registered bytes can stamp (`mg1_look.py:150-162`; `mg1_reserved_window.registered_confirmation_entry`).

## 1. Sequence (closed list)

Step R comes first, then steps 1 to 7 in this order, each once, except the conditional step 2a. The C14 ruling
fixes the look morning (rulings:705): "the MG-1 look is on or after 11-30. That morning runs serially under the
lease: P3 --final, then freeze --look mg1 (which includes the refresh), then the look."

### Step R. Owner-constant record (before step 3 and before the mg1_look pin)

The owner's open questions are one constant each in `mg1_look.py` (11-03:8; `mg1_look.py:237-247`). Each answer
is a one-line change, recorded in a dated note before the look (`mg1_look.py:237-239`). Master carries these
questions with the owner; they are not asked in the WS chat (11-03:8).

| Constant | Line | Branches built (`OWNER_CHOICES`, `:247-248`) | Value in force at 8c307dbb8 | Owner answer |
| --- | --- | --- | --- | --- |
| `A1_DENVER_SCORED` (A1) | `:240` | `True`, `False` | `True` | owner question, open |
| `A1_MIN_NEGATIVE_MARKETS` (A1, Q3) | `:243` | `1` to `len(MARKETS)` | `8` | owner question, open |
| `A5_BAR` (A5) | `:242` | `"as_written"`, `"magnitude"` | `"as_written"` | owner question, open |
| `A12_FALSIFIER_4` (A12) | `:245` | `"point"`, `"interval"` | `"point"` | owner question, open |

This draft proposes no answer. The record step is:

1. Master records each owner answer, verbatim and dated, in DECISION_LOG and in the dated note.
2. The one-line edit of each changed constant lands in `mg1_look.py`.
3. Then the entry pin is re-registered at the new bytes (`MG1_CONFIRMATION_ENTRY_POINTS`), and the final
   `mg1_look` sha goes into §2.

The code forces this order:

- **Before P3.** `support_markets()` reads `A1_DENVER_SCORED` (`mg1_look.py:307-310`). `mg1_countable` takes its
  support set from it (`mg1_countable.py:79-83`). At the look, `_parse_countable` refuses a list whose per-date
  `markets` keys are not exactly the support set in force (`mg1_look.py:329-331`). So A1 must be fixed before step
  3 writes the final list. P1 and P2 (steps 1 and 2) run under the value then in force and are report-only.
- **Before the pin.** Any constant edit changes the `mg1_look.py` bytes. Every caller is then refused until the
  entry sha is re-registered, and the edited look is refused too (`mg1_reserved_window.py:39-43` on look). C10
  (rulings:701) rules that no `mg1_look.py` edit may follow the S1 commit, or B's VOID 5 trips. Under the B2
  timetable, the mg1_look pin is 11-12/13 and S1 is 11-22..25. **An owner answer that arrives after the pin
  means a re-pin before S1.** After S1, it would be a master ruling.
- **Refusal.** `owner_constants()` refuses any value outside the built branches, and any
  `A1_MIN_NEGATIVE_MARKETS` above the scored-market count (`mg1_look.py:291-304`), when `score` starts
  (`:953`).
  - **Master's action:** fix the constant by a reviewed edit and re-pin. Nothing is consumed.
- **Logged:** the four values in force are written into the result as `owner_constants` (`mg1_look.py:979-980`).
- **Master's plan (11-03 R7):**
  - Master asks the owner to answer A1, A1_MIN_NEGATIVE_MARKETS, A5 and A12 by 11-10. The constants are then in
    `mg1_look.py` before the 11-12/13 pin.
  - A later answer means a re-pin before S1, which master owns.
  - Lanes do not ask the owner anything; this draft records the plan only.

### Step 1. P1 countability report, 2026-11-14

```powershell
.\venv\Scripts\python.exe -m weather.calibration.mg1_countable --ledger-root <SETTLEMENTS_ROOT>
```

- **Flags:**
  - `--ledger-root` is required (`mg1_countable.py:250`).
  - Report mode is the default, with no `--final` (`:251`, `:263-264`).
  - **MISSING:** a report `--out`. `--out` is read only with `--final` (`:252`, `:259-262`), so the report goes to
    stdout only.
- **Preconditions:**
  - Run at or after `NOT_BEFORE_UTC` 2026-11-14T00:00Z (`:59`, `:181-182`), in the slot 11-14 07:15-08:55 under
    the lease (rulings:54).
  - The mg1_look head and Head 2 have landed together as one head (C10, rulings:701; rulings:53).
- **Refusals** (exit 2, stdout `{"status": "refused", "reason": …}`, `:265-267`; nothing is written):
  - before 11-14T00:00Z (`:181-182`);
  - the MG-1 window is not recorded (`:163-164`);
  - no date from D0 has ended in every support market (`:185-186`);
  - a support market's settlement ledger is missing (`:118-119`).
  - **Master's action:** fix the cause and re-run the same day if the slot allows, else the next admitted
    morning.
- **Outcome** (exit 0): JSON with:
  - per-date `status` only (`countable` / `non_countable` / `pending`);
  - `counts`, `countable_reached`, `required_mg1_last`, `recorded_mg1_last`, `extend_mg1_last`;
  - `ledger_sha256` per market, `module_sha256`, `host`, `run_utc` (`:191-200`).
  - Nothing per market-day is printed.
- **Master's action on the outcome:**
  - `extend_mg1_last` true, or any `non_countable` / `pending` date: step 2a (R11 (4), rulings:12).
  - Otherwise: a dated no-move note (rulings:54).
- **Logged:** the stdout JSON, its sha256, and the run time.

### Step 2. P2 countability report, 2026-11-27

The command is step 1's. The preconditions, refusals and outcome are step 1's, on 11-27 (rulings:11, :54).
Master's action is the same.

### Step 2a. MG1_LAST extension (only when P1, P2 or P3 requires it)

- **What changes:** one commit covering `MG1_LAST`, the reservation status line, rows 25/26/39 of
  `reserved-confirmation-window.md`, and the DLv2 row (R11 (4), rulings:12). MG1_LAST is extended only, never
  shortened.
- **How it lands:**
  - It is suite-gated, never the light path, because it edits a `.py` file (C9, rulings:700).
  - Master runs `scripts\ops\roll_verdict.ps1 -Branch <b>`:
    - RS: the 01:00-04:00 quiet-window merge within two nights;
    - otherwise: the next suite-gated combo (rulings:27 (5), :54).
  - No agent derives the verdict by hand.
- **Refusal it prevents:**
  - `read_countable` refuses a 45th countable date after the recorded `MG1_LAST` (`mg1_look.py:367-369`).
  - `final_rows` refuses the same (`mg1_countable.py:219-221`).
- **Logged:** the commit sha, the verdict output verbatim, and the new `MG1_LAST`.

### Step 3. P3 final countable list, 2026-11-30 (if nothing moved)

```powershell
.\venv\Scripts\python.exe -m weather.calibration.mg1_countable --ledger-root <SETTLEMENTS_ROOT> --final --out <COUNTABLE_PATH>
```

- **Flags:** `--ledger-root`, `--final`, `--out` (`mg1_countable.py:250-252`). `--final` without `--out` is
  refused (`:260-261`).
- **Preconditions:**
  - The first admitted morning at least two days after the 45th date: 11-30 if there is no move (rulings:11,
    :54; C14 rulings:705; `FINAL_MIN_DAYS_AFTER` `:60`, `:222-223`).
  - Step R's A1 answer is in the landed `mg1_look.py`.
  - Any extension from step 2a has landed.
- **Refusals** (exit 2; nothing written):
  - `--out` exists (`:235-236`);
  - fewer than 45 countable dates among the ended dates (`:216-217`);
  - the 45th date is after the recorded `MG1_LAST` (`:219-221`);
  - less than two days after the 45th date (`:222-223`);
  - `write_countable` refused (`:239-242`, `mg1_look.py:373-400`).
  - **Master's action:**
    - on the `MG1_LAST` refusal: step 2a, then P3 again (rerun "only when its own output requires a move",
      rulings:54);
    - otherwise: fix the cause and re-run on the next admitted morning. The look moves with it (C14).
- **Outcome** (exit 0): `mg1_countable/1` written once, mode "x" (`mg1_look.py:373-400`). Stdout carries `sha256`,
  `dates`, `last` (the 45th date, `D45` below), `ledger_sha256`, `module_sha256` and `host`
  (`mg1_countable.py:243-245`). Pending counts as non-countable (`:12`, `:224`).
  - Both Clarification 1 caveats are null, with `caveat_reasons` (`:62`, `:225-226`).
- **Logged:** the stdout JSON, the list's sha256, and `D45`.

### Step 4. R24 refresh and freeze --look mg1 (same morning, after step 3)

R24's weekly refresh, Mondays 11-09, 11-16, 11-23 and 11-30 (rulings:295), is the routine run before this step:

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.venue_label_audit refresh --through <D>
```

On the look morning, the freeze includes its own refresh (`venue_label_audit.py:410-418`; C14). So no separate
refresh runs that morning.

- **The weekly refresh is a hand run, not a scheduled task** (11-03 R5). Master runs it by hand under the lease
  on 11-16 and 11-23, and on the look morning (inside the freeze).
- **Its refusals:**
  - `--through` after today (`:349-350`);
  - `--start` after `--through` (`:351-352`);
  - an existing run folder (`:356-359`).
- **Exit 3 on `STATION_DRIFT`** (`:77`, `:517`). Master rules it outcome-blind the same day. For a real station
  change, master adds a dated `venue_rule_stations.json` entry (rulings:295).

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.venue_label_audit freeze --look mg1 --through <FREEZE_THROUGH>
```

- **Flags:**
  - `--label-root` is a top-level flag, before the subcommand; its default is `DEFAULT_LABEL_ROOT`
    (`venue_label_audit.py:480`).
  - `freeze --through` is required (`:484`). In [B], `--through` and `--look` are optional at parse time, and
    the command refuses (exit 2) unless both are given without `--ruling` (`venue_label_audit.py:438-443` [B]).
  - `--start` defaults to `2026-10-22` (`:71`, `:485`).
  - `--look` is required (`:487`).
  - The look reads only look id `mg1` (`FREEZE_LOOK_ID`, `mg1_look.py:252`, checked at `:436-438`).
- **`<FREEZE_THROUGH>`, as ruled (11-03 R6):** the latest date with finality in ALL scored MG-1 markets on the
  look morning. A value below `D45` is a hold.
  - **Where it is enforced:** the freeze does not know a look's scored markets, so the look checks it.
    - `mg1_look.latest_final_date(frozen_at_utc)` is the latest date that has ended in every scored market at
      the freeze (`mg1_look.py:434-439` [A]).
    - The look holds on any other `through` (`:480-482` [A]). It holds first on one below `D45` (`:474-475` [A]).
    - [B]'s docs record the same rule (`docs/operations/venue-rule-labels.md`, "Through").
  - **How to compute it:** take the scored markets at the freeze time, using the last time zone to reach
    midnight. With the Pacific markets in, a freeze at 05:00 local (10:00Z) on 11-30 gives 2026-11-29.
  - It must also not be after today (`:349-350`).
- **Preconditions:**
  - Step 3 is done, so `D45` is known.
  - The freeze runs after `D45` has ended in every scored market (`settled_at`, `mg1_look.py:403-410`). The look
    refuses labels frozen earlier (`:442-444`), and a look id is frozen only once (`venue_label_audit.py:416-417`).
  - The lease is free (rulings:296: "about 05:00 or later, lease free").
- **Refusals** (exit 2, stderr `refused: …`, `:514-515`):
  - a bad look id (`:413-414`);
  - `frozen/mg1` exists (`:416-417`);
  - any refresh refusal;
  - a build manifest without `label_dates` or `skipped_dates`, refused before any folder is made (`:422-425`).
  - **Master's action:** a refusal before `frozen/mg1` exists can be re-run with a new run id. A failed refresh
    makes no `frozen/mg1` (the folder is made at `:426`, after the refresh at `:418`).
- **Outcomes that are not refusals (freeze-keys, without [B]):**
  - **Exit 3 (`STATION_DRIFT`):** `frozen/mg1/freeze_receipt.json` IS written, with `audit_status` (`:455`).
  - **A missing source file** is recorded with `sha256` null and `missing_source` (`:436-438`), and the freeze
    still writes.
- **With [B]**, both become refusals that leave no `frozen/mg1`:
  - **Not OK.** Unless the run's audit status is `OK`, the freeze refuses before any folder under `frozen/` is
    made (`FreezeDrift`, `venue_label_freeze.py:54-57`, `:111-113` [B]). On `STATION_DRIFT` it exits 3
    (`venue_label_audit.py:482` [B]). Master rules the drift outcome-blind, then freezes again.
  - **Atomic.** The copy and its receipt are built in `frozen/mg1.tmp-<utc>-<pid>/` (`:123` [B]). The freeze
    re-reads and re-hashes them (`:161` [B]), and renames the folder to `frozen/mg1` only when verified
    (`:165` [B]).
    - A missing source, a sha mismatch or a manifest mismatch refuses (exit 2) and keeps the tmp folder.
    - A crash keeps only the tmp folder.
    - A later freeze lists such folders in `ignored_partial_dirs` and ignores them (`:70-73` [B]).
  - **Recovery** (11-03 R2(c)), for a `frozen/mg1` left defective by a pre-[B] freeze:

    ```powershell
    .\venv\Scripts\python.exe -m weather.backtesting.venue_label_audit freeze --recover mg1 --ruling <MASTER_RULING.json>
    ```

    - It moves a receipt-less or null-sha folder to `frozen/mg1.void-<utc>/`, with `recovery_record.json`
      (`venue_label_freeze.py:200-222` [B]).
    - It runs only while `data/mg1_look/started-*` and `receipt-*` are absent (`LOOK_STAMPS`, `:48-51` [B]).
    - The ruling file needs `schema_version` `venue_label_freeze_recovery_ruling_v1`, `dated`,
      `outcome_blind: true`, `look_id` and `reason`.
    - The re-freeze is outcome-blind, because the freeze copies bytes and reads no label value.
- **Outcome** (exit 0): stdout carries `look_dir`, `freeze_receipt_sha256` and `frozen_sha256` per market for
  `label_csv`, `manifest` and `wu_daily_summary`, plus the counts-only audit (`:504-507`, `:516`).
- **Logged** (R24 (3), rulings:241: "Log the shas before the look"): the stdout, the freeze receipt's sha256, and
  each frozen file's sha256.

### Step 4a. Capture-time prices for `--market` [C] (same session, after step 4)

  - **Embargo** (11-03 M2). The price tool and the concat are **registered steps of the look path**:
    - they run ONLY on this look morning, after D45's finality, under master's lease, in the same session as
      the look, ON THE HOST;
    - neither the concat nor the look ever exports a price CSV or parquet to the WS before the look receipt.
      Both refuse an `--out` under `data\exports`, the capture tree or a UNC (share) path (`:109-125` [C];
      `mg1_market.py:117-130` [C]);
    - logs and manifests carry counts, shas and booleans only. No agent or human views a price value;
    - the same rule as B's T4: a finite price outside [0, 1] refuses, and the look is HELD.

- **The price tool** (on the host, through master's `.ps1`):

  ```powershell
  .\venv\Scripts\python.exe -P -B -m tools.research.capture_price_export --look mg1 --data-root <repo>\data --out <PRICES_DIR> --from 2026-10-15 --through <D45> [--coverage-root <repo>\data\exports\mg2-inputs]
  ```

  - **What it reads:** per date, the 11 markets' `snapshots_long.csv` through the unchanged exporter's bounded
    reader, rows at or before `export_cut_utc(D)` only, so its row set is the bundle's (`export_market`,
    `:153-185`).
  - **What it writes**, create-only per date: `<D>.prices.csv` (`row_key, kind, low, high, p_market_yes,
    out_of_range`), the counts-only `<D>.capture_prices.json` (`capture_price_export/1`), then `<D>.SHA256SUMS`
    last (`export_date`, `:215-271`). Prices go through R19's `capture_price`. A finite price outside [0, 1] is
    flagged and never written as a value.
  - **The R19 cross-check** (M5, `cross_check`, `:188-207`). From 10-29, each snapshot's `[n_rows, n_priced]` must
    equal the R19 sidecar, or the date refuses. For 10-15..10-28 no sidecar exists: the receipt records
    `none_before_r19` and the tool's own counts, disclosed, with no refusal.
  - **Refusals** (exit 2, nothing written for the date):
    - off the capture host (`:99-106`);
    - `--through` not yet ended in every market (`:222-225`);
    - a date after `--through` (`:220-221`);
    - an `--out` under `data\exports`, the capture tree or a share (`:109-125`);
    - files already present for the date (`:227-229`);
    - a missing R19 sidecar from 10-29, or one that differs (`:194-205`).
  - **Exit 3:** a source changed in the last 30 minutes; re-run once quiet.
- **The concat** (on the host, same session):

  ```powershell
  .\venv\Scripts\python.exe -m weather.calibration.mg1_market build --look mg1 --layout <LAYOUT_ROOT> --prices <PRICES_DIR> --out <MARKET_DIR>
  ```

  - **Host guard:** it refuses unless the execution-host id equals the dedicated capture id. This is the
    identity check the R19 host wrapper makes. It runs at command time, not at import (`mg1_market.py:101-114`).
  - **The join:** each layout band `(row_key, kind, low, high)` takes its `band_index` from exactly one price row
    (`build`, `:181-254`).
  - **Refused** (exit 2): an unmatched layout band, a duplicate price row, a date without a published file set,
    or a SUMS or sha mismatch (`:133-165`, `:218-223`).
  - **Held** (exit 4): a matched price that is flagged, or not empty and not finite in [0, 1] (`:224-226`).
  - **Writes** `<MARKET_DIR>\market.parquet`, then `mg1_market_manifest.json` (`mg1_market/1`): the look id,
    the layout and market shas, the per-date file shas and cross-check, the counts, and `range_ok` and
    `duplicate_free`.
- **Logged:** both commands' stdout (counts only), exit codes, and the sha256 of every receipt, SUMS file, the
  market file and its manifest. A price CSV or the parquet is never opened or copied off the host.

### Step 5. Keys-only checks of the freeze (master, read-only, before step 6)

Master reads only `frozen/mg1/freeze_receipt.json` and the audit. It never reads a frozen CSV. It checks:

- `schema_version` is `venue_label_freeze_receipt_v1` and `look_id` is `mg1` (`mg1_look.py:251-252`, `:436-438`);
- `through` is on or after `D45`;
- `frozen_at_utc` is after `settled_at(D45)`;
- `audit_status` is not `STATION_DRIFT`;
- every scored market has `label_csv_matches_manifest` and `wu_daily_summary_matches_manifest` true, and no null
  `sha256` (`:449-460`);
- every scored market has a `label_dates` list and a `skipped_dates` map, keys only (`venue_label_audit.py:68`,
  `:446-447`).

The pre-stamp `label_key_check` (Q2; `mg1_look.py:472-532`) is the code-side check. It reads:

- the receipt's `label_dates` and `skipped_dates`;
- the frozen manifest's `skipped_dates` and `label_source_counts`.

It parses no CSV and calls no reader.

- **The dry run** (11-03 R3; [A]):

  ```powershell
  .\venv\Scripts\python.exe -m weather.calibration.mg1_look check-keys --rule <MG1_RULE_PATH> --countable <COUNTABLE_PATH> --label-freeze <FREEZE_RECEIPT_PATH> --out <CHECK_RECORD_PATH> [--layout <LAYOUT_ROOT>] [--market <MARKET_DIR>\market.parquet]
  ```

  - **Flags:** `--rule`, `--countable`, `--label-freeze` and `--out` are required; `--layout` is optional
    (`mg1_look.py:1133-1138` [A]).
  - **What it runs** (`check_keys`, `:998-1033` [A]), every pre-stamp check except the A6 status count, which
    needs the MG-1 vector and runs only in step 6:
    - the owner constants;
    - the rule sha and the marker absence;
    - the countable list;
    - the window and finality;
    - the freeze: audit status, FREEZE_THROUGH and hashes;
    - the label keys and every inconsistency hold;
    - with `--layout`, the A3 hole check;
    - with `--market` (M3, [A] `mg1_look.py:621-667`), the `--market` check: see step 6.
  - **It never stamps, joins or reads a label or price.** It writes `<CHECK_RECORD_PATH>` once (mode "x") for
    every outcome. The record is counts-only `mg1_check_keys/1`, with the verdict and the reason text.
  - **Exit:** 0 pass, 4 held, 2 refused, including a record path that already exists.
  - **Master's action:** run it right before step 6. On 4 or 2, rule from the record; nothing is consumed.
- **Without [A]**, there is no standalone command. The check runs only inside step 6, after the layout hole check
  (`:970-971`) and before the stamp (`:998`).
- **Logged:** each check as pass or fail, with the receipt fields read (the keys and the counts).

### Step 6. The look

```powershell
.\venv\Scripts\python.exe -m weather.calibration.mg1_look run --rule <MG1_RULE_PATH> --layout <LAYOUT_ROOT> --countable <COUNTABLE_PATH> --label-freeze <FREEZE_RECEIPT_PATH> --market <MARKET_PARQUET> --out <OUT_DIR> [--shadow <SHADOW>] [--serving-change <YYYY-MM-DD> ...]
```

- **Flags** (`mg1_look.py:1041-1050`):
  - `--rule`: the signed pre-registration, sha256 `MG1_RULE_SHA256` (`:69-70`).
  - `--layout`: the label-free snapshots and bands (`:546-548`). The WS ships the concat layout and its
    `SHA256SUMS` to the host before P3 (rulings:53). **MISSING on the named branches:** its producer. R11 Head 1
    (`mg1_layout.py`, `claude/r11-head1-20261101`) is not one of the trees read here, so no flag of it is quoted.
  - `--countable`: step 3's file.
  - `--label-freeze`: `frozen/mg1/freeze_receipt.json` from step 4 (`:1045-1046`). The frozen files are read
    from that receipt's own folder (`:446-456`).
  - `--market`: `<MARKET_DIR>\market.parquet` from step 4a, columns `row_key`, `band_index` and
    `p_market_yes`, read only at the join (`:753`). Its producer is step 4a [C].
    - **The pre-stamp `--market` check** (M3; `market_check`, [A] `mg1_look.py:621-667`, called at `:1120`). It
      reads no price value. It needs:
      - the file to exist;
      - its parquet schema to name exactly the three columns;
      - its sha to equal the manifest's `market_sha256`, where the manifest is MG-1's and names this layout;
      - the manifest's `range_ok` and `duplicate_free` to be true.
    - A missing or mismatched file refuses (2). A false or absent boolean holds (4).
  - `--out`: the folder for `mg1_look_result.json` (`:230`, `:965-968`).
  - `--shadow`: optional; the captured `nbm_v2_guidance_read_v1` shadow vector, "when it exists" (`:1049`).
    Whether it is passed is **open for master**.
  - `--serving-change`: repeatable; serving-change dates under pre-registration section 2 (`:1050`). The list is
    master's.
- **Preconditions:**
  - Step R is recorded, and the landed `mg1_look.py` sha equals the registered entry pin (§2).
  - The window has closed: today is after the recorded `MG1_LAST` (`:957-959`).
  - `D45` has ended in every scored market (`:960-963`).
  - Steps 3 to 5 are done the same morning, under the lease.
  - Neither `data/mg1_look/started-<rule sha>.json` nor `receipt-<rule sha>.json` exists (`:139-141`).
  - The result file does not exist (`:966-968`).
- **Before the stamp (nothing consumed).**
  - **With [A]** (11-03 R4): a refusal exits 2 (`EXIT_REFUSED`) with stderr `refused: …`, and a hold exits 4
    (`EXIT_HELD`) with stderr `held: …` (`mg1_look.py:283`, `:1158-1163` [A]).
  - **Without [A]**, both exit 2 and differ only in the `held:` text (`:1064-1066`).
  - [A] adds two holds: a freeze `audit_status` other than `OK` (`:471-473` [A]), and a `through` other than
    FREEZE_THROUGH (`:480-482` [A]).
  - **Refused:**
    - an owner constant outside the built branches (`:953`);
    - the rule sha (`:134-137`);
    - an existing start marker or receipt (`:139-141`);
    - a countable list that is malformed, starts off D0, skips a date, has other than 45 countable dates, or has
      `markets` keys other than the support set (`:313-351`);
    - `D45` after `MG1_LAST` (`:367-369`);
    - the window not closed (`:958-959`);
    - `D45` not ended (`:960-963`);
    - the freeze receipt missing, unreadable, of the wrong schema or look id, frozen before `settled_at(D45)`,
      lacking a market, mismatched against its manifest, or with a frozen file missing or differing from its
      sha (`:428-460`);
    - `label_dates` missing (`:501-505`);
    - the result exists (`:966-968`);
    - a repeated layout `row_key` (`:553-554`).
  - **Held** (`MG1LookHeld`, `:83-84`; master rules from the message alone):
    - freeze `through` before `D45` (`:440-441`);
    - a countable market-day with no layout rows (A3 hole, `:555-559`);
    - label-metadata inconsistencies: the key list not sorted and distinct, differing from the manifest's,
      `skipped_dates` differing, a count mismatch against `label_source_counts`, or an overlap with
      `skipped_dates` (`:513-524`);
    - a countable market-day in `skipped_dates`, or in neither list (Q1; "Unexplained absence holds";
      `:525-531`);
    - used rows whose `v2_status` is not "available" (A6, `:973-976`).
  - **Master's action on a refusal or hold:** fix the input or rule from the message. The look is not spent: no
    marker, no receipt and no result exist.
- **The stamp.** The first `join_outcomes` call checks the registered entry point (`:155-157`), then writes
  `started-<rule sha>.json` (mode "x") with `looked_at_utc`, before the loader runs (`:158-161`). From here on,
  the look is spent.
- **After the stamp:**
  - A label refusal the metadata did not predict masks that market-day (T2, 11-03:20). It is disclosed in
    `label_masked` and raises the receipt flag `label_refusal_unpredicted_by_metadata` (`:1002-1007`).
  - Every exit writes the result and the receipt: a verdict, a VOID (`:940-943`), or ABORTED (`:1017-1023`).
  - On ABORTED, the exception is re-raised after the receipt is written.
    - If it is an `MG1LookRefused` (for example the `winner_band` refusal), `main` exits 2 with `refused:`, the
      same as a pre-stamp refusal. That is true with and without [A]: `mg1_look.py:1161-1163` [A].
    - Any other exception exits non-zero with a traceback.
    - Master tells ABORTED apart by the start marker and the receipt existing. See §4 item 9.
  - **Master's action:** none re-runs. MG-1 has exactly one look (`:128`, `:968`). A VOID's dates "are spent
    and are not re-run" (`:942`).
- **Outcome** (exit 0): stdout `{"receipt": <path>, "decision": …}` (`:1067-1068`). The receipt is
  `data/mg1_look/receipt-<rule sha>.json`, `mg1_look_receipt/1`, with the fields `RECEIPT_FIELDS` (`:73-76`),
  including `label_freeze_receipt_sha256` and `flags`.
- **Logged:** the stdout and stderr, the exit code, and the sha256 of the start marker, the receipt and the
  result.

### Step 7. Receipt check and receipt commit

```powershell
.\venv\Scripts\python.exe -m weather.calibration.mg1_look check-receipt --receipt data\mg1_look\receipt-<MG1_RULE_SHA256>.json
```

- **Flags:** `--receipt` (`mg1_look.py:1039-1040`). It prints `{"receipt", "problems"}` and exits 1 if any
  problem is found (`:1056-1059`). It reads no outcome.
- **Checks:** `receipt_problems` (`:195-227`) checks:
  - the schema and the fields;
  - `body_sha256`;
  - the signed rule;
  - that the entry point is registered at its recorded sha;
  - that the bytes equal the receipt at the fixed path.
- **Master's action on a problem:** the look is spent either way. B's VOID 5 runs the same checks, so master
  rules before B's look session.
- **The commit:** the receipt, the start marker, the result and step 4's freeze receipt are copied into the
  repository record the same day (`mg1_look.py:21-22`; `look-day-dry-run-checklist.md:63`). The commit carries
  their sha256s and the look-log extract. Master owns this commit.
  - **Record path** (11-03 §4 ruling (d)): `docs/research/mg1-look-record/` in the repository, holding
    `mg1_look_receipt.json` (a byte-exact copy) and `mg1-look-record.md`. It mirrors B's R14 record pattern but
    is **not** an R14 frozen record. A small record writer (`mg1_look_record.py`) is planned after combo C.
- **Logged:** the check output, the commit sha, and each copied file's sha256, which must equal the
  originals'.

## 2. Closed sha list (master fills every PIN before step 6)

| Item | Path | Current value (tree) | Final |
| --- | --- | --- | --- |
| mg1_look | `src/weather/calibration/mg1_look.py` | `825d57a31f2415f4ac2d81530884c29e914c613165a76cea0983b519a8df077c` (look, WIP); master `1e691c58b68a203aebaed3f505295971f56821e92555e3bc12ef8a4db23ff305` cannot score | `<PIN: mg1_look final, after step R>` |
| entry pin | `MG1_CONFIRMATION_ENTRY_POINTS["weather.calibration.mg1_look"]` in `src/weather/mg1_reserved_window.py` | `825d57a3…` (look, `:69-70`); `1e691c58…` (master) | `<PIN: equals mg1_look final>` |
| mg1_reserved_window | `src/weather/mg1_reserved_window.py` | `0195e35ba49f2ab98ffac09b0fa5a1cb0a831ea9035fca7d0f0cac7ca6f0bcca` (look); `32906db3ebc32b16ba9397933aae33d39a3ca7cc02b0d6242620fb5ad244910c` (countable) | `<PIN: after the combined head and any MG1_LAST move>` |
| mg1_countable | `src/weather/calibration/mg1_countable.py` | `9f59b90be66b0500db6ed6c7e9c77bf1bb4c5e61b41269e0b19560f5ef0f4db3` (countable) | `<PIN: mg1_countable final>` |
| venue_label_audit with freeze-keys | `src/weather/backtesting/venue_label_audit.py` | `2f84e5514d9a2db81c37d299121f60a25d2838c6995e9e51250c6cfe93ba8ddd` (freeze-keys); R24 base `7670fd08f006275bd5766fdce05344586512411a56e34183c1ba2b6fb51c64ce` has no key copy | `<PIN: venue_label_audit final>` |
| venue_rule_labels (writes the manifest `label_dates`) | `src/weather/backtesting/venue_rule_labels.py` | `1842b6da48af90a62999262dd6b92b1b66eaaf323553bb90455c020e5be83405` (freeze-keys); `7bababd2…` elsewhere has no `label_dates` | `<PIN: venue_rule_labels final>` |
| read_venue_labels | `src/weather/backtesting/venue_label_reader.py` | `a4483777143446f309d569ad90e0b9fac695d371bbb1d62b6a7d6367e6a32b66` (all four trees and master) | `<PIN: venue_label_reader at the look>` |
| MG-1 rule | `docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md` | `b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665` (`MG1_RULE_SHA256`, `mg1_look.py:70`) | fixed |
| capture_price_export [C] | `tools/research/capture_price_export.py` | on [C] `d3926b85c` | `<PIN: price tool at the look>` |
| mg1_market [C] | `src/weather/calibration/mg1_market.py` | on [C] `d3926b85c` | `<PIN: concat at the look>` |
| market file and manifest | `<MARKET_DIR>\market.parquet`, `mg1_market_manifest.json` | written on the look morning (step 4a) | logged in step 4a |
| mg1.py (recorded in the receipt) | `src/weather/reporting/scorecards/free_source_candidates/mg1.py` | `ad6e524ee103072e7738d78264cf1df855a30b01b43099425d4a1de7ae3d889d` (master) | `<PIN: mg1.py at the look>` |

Countable's tree was built on mg1_look `4489e0f30`. Its file there hashes to `8baede1d…`, not look's `825d57a3…`.
The pins above are therefore for the combined head that C10 requires (rulings:701), not for either branch alone.

## 3. Outcome summary for master

| Step | Exit | Meaning | Master does |
| --- | --- | --- | --- |
| R | refusal in `score` | an owner constant is outside the built branches | reviewed edit and re-pin; nothing consumed |
| 1, 2 | 2 | refused, nothing written | fix, re-run in an admitted slot |
| 1, 2 | 0, extension required | `MG1_LAST` must move | step 2a |
| 3 | 2 | refused, nothing written | 2a if `MG1_LAST`; else the next morning, and the look moves with it |
| 4 | 2 | refused; `frozen/mg1` absent (with [B], also a failed check: only a tmp folder is left) | re-run (new run id) |
| 4 | 3 | `STATION_DRIFT`. With [B], refused and nothing frozen; without [B], `frozen/mg1` is written | rule the drift outcome-blind; with [B], freeze again; without [B], hold the look and recover by ruling |
| 4 `--recover` | 0 / 2 | the defective freeze is moved to `.void-<utc>` / refused, nothing moved | re-freeze / rule |
| 4a price tool [C] | 0 / 2 / 3 | dates written / refused, nothing written for that date / a source too fresh | step 4a concat / fix and re-run / re-run once quiet |
| 4a concat [C] | 0 / 2 / 4 | market file and manifest written / refused (unmatched, duplicate, files) / held: a price out of range | step 5 / fix the files / the look is held; rule outcome-blind |
| 5 `check-keys` [A] | 0 | every pre-stamp check passes; nothing stamped | step 6 |
| 5 `check-keys` [A] | 4 | held; record written; nothing consumed | rule from the record |
| 5 `check-keys` [A] | 2 | refused; record written (unless the record path existed); nothing consumed | fix the input |
| 6 | 2, `refused:` | refused before the stamp; nothing consumed, unless the start marker exists (ABORTED, §4 item 9) | fix the input |
| 6 | 4, `held:` [A] (2, `refused: held:` without [A]) | held before the stamp; nothing consumed | rule from the message |
| 6 | 0 | verdict or VOID, receipt written | step 7; never re-run |
| 6 | non-zero, traceback; or 2 with the marker present | ABORTED after the stamp, receipt written | step 7; never re-run |
| 7 | 1 | receipt problems | rule before B's session |

## 4. Open items for master (revision 2: rulings applied, the rest inventoried)

1. **Audit status.** Ruled (11-03 R1, R2(a)) and built: [A] holds the look unless `OK`, and [B] refuses to
   freeze unless `OK`.
2. **A freeze that dies mid-copy.** Ruled (11-03 R2(b), R2(c)) and built in [B]: atomic tmp-and-rename, plus
   `freeze --recover`.
3. **A standalone pre-stamp check.** Ruled (11-03 R3) and built in [A]: `check-keys`.
4. **Held and refused share exit 2.** Ruled (11-03 R4) and built in [A]: refused 2, held 4. Tests:
   `tests/calibration/test_mg1_look_check_keys.py` [A].
5. **Inventory of what is still missing** (11-03 R5), each with its owner:

   | Item | State and file:line | Owner |
   | --- | --- | --- |
   | (a) `--layout` producer | R11 Head 1, `claude/r11-head1-20261101` @ `9dc1c9798366f17d8f0f8af1c3e41733d644c30d`, not on master. `src/weather/calibration/mg1_layout.py`: `concat --layouts --out [--ledger]` writes "one window layout for D0..MG1_LAST" (`mg1_layout.py:226`, `:269-272`), after per-date `stage`, `admit` and `build` (`:251-268`). The planned landing is an RF combo night, 11-04/05, with fallback 11-05/06 (rulings:27 (2)). The WS ships the concat layout and `SHA256SUMS` to the host before P3 (rulings:53). | R11 lane (head); master (landing, host copy) |
   | (b) `--market` producer | **Ruled and built 11-03 (M1-M5):** step 4a, [C] `d3926b85c` (the price tool and the `mg1_market` concat, on the host, as registered look-path steps), plus [A]'s pre-stamp check. `--market` stays required. B takes `--market` from the same producer with its own layout (M4). | L16 (built); master (landing) |
   | (c) look-log path | **Ruled 11-03:** on the host, `C:\tmp\suite-logs\mg1-look-<yyyymmdd>.log`, written by master's wrapper. R24 (3) requires the shas to be logged before the look (rulings:241). | master |
   | (d) receipt repository record path | **Ruled 11-03:** `docs/research/mg1-look-record/` with `mg1_look_receipt.json` (byte-exact) and `mg1-look-record.md`. It mirrors B's R14 pattern but is not an R14 frozen record. The receipt is copied the same day (`mg1_look.py:21-22`; `look-day-dry-run-checklist.md:63`). | master |
   | (e) admission or allowlist entry | **Ruled 11-03: no allowlist entry.** `venue_label_audit` and `mg1_look` run only under master's lease, 00:30-09:00, through master's host `.ps1`. (Context: `venue_label_audit` matches the heavy-module regex at `scripts/ops/workload_admission.ps1:908-917`; `mg1_look` and `mg1_countable` do not.) | master (host) |

6. **FREEZE_THROUGH.** Ruled (11-03 R6) and built in [A]. See §1 step 4.
7. **The owner-constant timing.** It is master's plan (11-03 R7; §1 step R): answers by 11-10, before the
   11-12/13 pin. A later answer means a re-pin before S1, which master owns.
8. **The combined-head pins.** Noted by master (11-03 R8). [A] moved the entry pin to `6f17cf15…`, and its
   M3 commit moves it again, to `1130ece5…`. §2's PIN slots stay open until the combined head is final. A test
   pinning `mg1_look`'s copied `MARKET_*` constants to `mg1_market`'s lands with that head, where both modules
   share a tree.
9. **New: ABORTED can exit 2.** A post-stamp `MG1LookRefused` re-raises after the receipt is written. `main` then
   prints `refused:` and exits 2, so the exit code alone does not separate it from a pre-stamp refusal
   (`mg1_look.py:1161-1163` [A]). Today the start marker existing is the only tell. No fix is proposed here; a
   distinct code is master's call.
10. **Pre-existing on look (8c307dbb8):** `tests/operations/test_schema_registry.py::...strict_audit...` fails
    there because `mg1_look.FREEZE_RECEIPT_SCHEMA` names `venue_label_freeze_receipt_v1` before the
    `venue_labels` family is on that tree. It is the same with and without [A], and it clears once look and
    combo C's R24 module share a tree.
