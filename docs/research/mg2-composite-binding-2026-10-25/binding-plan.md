# MG-2 composite binding plan

- **Status:** DRAFT. Master APPROVED the design on 2026-10-25. The binding commit and D0 wait for two
  things:
  - the single Fable review, which the coordinator relays;
  - serve parity (§6, rule §1a). Both inputs now have captured readers (rule §8 captured-source
    Clarification), and P3d_N's forward state is bound (rule §8 C3-binding, `c6cc39f7…`). The L6 part is
    still to be re-frozen on the captured-METAR nowcast;
  - master's host exporter and share (§9.3). The workstation pull, receiver and layout builder are built
    (§9.7); rule §8 Clarification C1 (2026-10-25) makes `high_so_far` the METAR-only running max.
- **Rule:** [rule.md](rule.md) (draft sha256 in the record line of the coordinator report). The rule
  owns every definition.
- **Purpose of this plan:** how the binding is executed, what it reads, and what is pending.
- **Supersedes:** [the L8 draft plan](../high-so-far-parity-shadow-2026-10-24/mg2-binding-plan.md).
- **Dev numbers are selection evidence only.**

## 1. Design (fixed by the coordinator)

The composite switches on local hour, fixed at 13.

- **Before 13:00 local:** MG-1 plus lane L6's own-obs stack.
- **From 13:00 local:** P3d_N, L2's pooled residual model on the captured NBM 07Z `v2_mean` plus bias
  (pick `1ce2b5b4…`, rule §8 C2), floored at L8's METAR-only
  `weather.model.observed_running_max.running_max_since_midnight`. It replaces the former arm A; A′ and
  A_N are dropped.

**Inherited from MG-1:**
- **Floor:** the rule-4 mask.
- **Calibration:** none.
- **Fallback:** MG-1 falls back to served.

**Scoring:** forward scoring is by captured-input replay at frozen hashes. No capture-host serving
change is made.

**Sources merged into this branch:**
- `claude/stack-l5-20261025` @ `505f35ffd` (G, B2, L6, L1, L7, L5);
- L8 `f6ee3351e`;
- L3 `eaed66d6a`.

All three were full merges; the allowlists, shard lists and findings were resolved as unions.

## 2. The MG-1 reservation: option 3 now, option 2 adds only the read clause

**Quoted clauses (rule §4.1 carries the same text).**

The reservation scope row, in `docs/operations/reserved-confirmation-window.md` and the MG-1
pre-registration §7:

> Reserved **only** against reading or modifying the morning guidance-read (forecast-scoring) family: do not score, enumerate outcomes for, or join to an outcome the MG-1 vector or any other candidate that reads NBM station guidance into band probabilities (including the held RV-1 and HG-1), do not substitute reserved dates for such a candidate, and do not modify MG-1, without a new explicit owner decision.

The MG-1 pre-registration §6:

> **Window leakage:** before the look, any MG-1 vector or any morning guidance-read-family candidate was joined to an outcome (winner, settlement or Brier) on a reserved date, or MG-1 was modified (§7 scope). Uses §7 leaves untouched do not void the look.

The MG-1 pre-registration §5:

> **One look**, after the 45th counted date has settled. No interim outcome look.

**MG-2 is in the reserved family.** It reads NBM in three places:
- before 13:00, MG-1's centre and spread;
- every hour, `guidance_physical_floor` in the rule-4 floor;
- after 13:00, the MG-1 fallback.

Every gate is also against the MG-1 vector.

**Option 3 (now).** Accrue outcome-blind from D0. The four checks below are the ones the scope row's
exemption names: "outcome-blind operational checks (coverage, PIT, replay reproduction, parser version)
are permitted".

| Step | What it does |
| --- | --- |
| `emit` | Captured-input replay at the frozen coefficients. Reads `inputs_snapshots.parquet` and `inputs_bands.parquet` only, and refuses label or market columns. |
| `check` | Coverage ≥ 90% of 00-16; PIT; replay reproduction to 1e-12; parser version 2. |

`score` refuses any date on or before `MG1_LAST` unless the rule carries a dated owner decision id
(test-pinned).

**Option 2 (pending the owner).**
- **Trigger:** a dated Clarification sets `owner_decision_id: OD-YYYY-MM-DD-<slug>`.
- **Effect:** one look, strictly after MG-1's.
- **Scorer guard:** it also needs an MG-1 look receipt and a closed recorded window.
- **Nothing else changes.**
- **Not this lane's edits:** the reservation file and DECISION_LOG are the owner's.

## 3. N, MDE and read dates for both branches

- **Gate:**
  - G1: Δ(00-16) upper bound < +0.0010 (non-inferiority);
  - G2: Δ(13-16) upper bound < 0.
- **Interval:** fixed-market, date-clustered 95%, one-sided α 0.025 each.
- **N:** 45 countable dates in either branch.
- **Variance:** taken from the dev window (43 dates × 11 markets).

| | Branch 2: owner exemption | Branch 1: post-window fallback |
| --- | --- | --- |
| Start | D0 = first target date after the binding commit | first target date after `MG1_LAST` (today 2026-11-29; moves later with it) |
| 45th date (all countable) | D0 + 44, e.g. 2026-12-11 for D0 = 2026-10-28 | 2027-01-12 today |
| Earliest read | the later of the 45th date's settlement and MG-1's completed look; e.g. 2026-12-12 | the 45th date's settlement; 2027-01-13 today |

Both branches have the same MDE and power:

| Gate | MDE80 | Power at the dev point | Power at half the dev point |
| --- | ---: | ---: | ---: |
| G2 (13-16) | 0.0060 | 0.998 | 0.683 |
| G1 (00-16) | 0.0022 | > 0.999 | 0.951 |

G1's power at zero effect is 0.247. N = 60 would give G2 0.80 at half the dev effect, 15 dates later.

The branch is fixed before any read: Branch 2 holds only if the owner decision is recorded before
MG-1's look completes. Exactly one look in either case.

## 4. Measures beside the gate

Each half is reported separately against MG-1:
- **Pre-13:** Δ(00-12) and Δ(07-12).
- **Post-13:** Δ(13-16) and Δ(17-23).

Also reported: per hour, per-market signs, dR and the crossed interval.

## 5. Clarification clause

Rule §8 holds the dated Clarifications made before D0:
- C1, the METAR-only running max;
- C2, P3d_N in the post-13 slot;
- the captured-source Clarification;
- L2's Clarification 3, the forward-window P3d_N refit and its frozen state sha.

After D0 nothing changes, except the §2 owner-decision Clarification, which changes permission only.

## 6. Input overlap with MG-1

Rule §9 has the table. In summary:

- **Before 13:00:** MG-2 reads MG-1's NBM v2 centre and spread.
- **Every hour:** both use the identical rule-4 floor, including `guidance_physical_floor`.
- **After 13:00:** P3d_N reads the captured NBM 07Z `v2_mean` (F4/F5, the same v2 column MG-1 uses),
  plus the METAR-only L8 running max and current_temp from F1 `sources.metar`.
- **Retired dev sources:** two dev inputs were later free fetches and are refused forward:
  - IEM own-station observations, replaced by the captured-METAR L6 reader
    (`mg2_composite.captured_nowcast`, matching L3 @ `ecd8c9ba6`);
  - Open-Meteo Previous Runs, the former arm A's forecast_high, which P3d_N does not use. The capture's
    `gfs_seamless` day high is the current run, a different lead, with an MAE of 2.26 °F vs the PIT
    value on 13-16 rows (L2's P3d serve-parity note).

  Both captured readers are registered (`captured_nbm_v2_mean_07z`, `captured_metar_l6_own`).

## 7. Release binding

At the binding commit, `release-binding.json` records:
- the commit sha;
- the sha256 of each file in `mg2_composite.RELEASE_FILES`;
- the function sha256 `8cc4d8ec13a64419…` (rule §8 Clarification C1; docstring-only change from `c057e454…`);
- the coefficient part sha256s:
  - L6 `07a67425…`, the captured-nowcast re-freeze (the IEM-fitted `313d1743…` is retired);
- the P3d_N state sha256 `c6cc39f7…` (L2's Clarification 3 forward refit; the file bytes of
  `p3d_n_state.pkl`, schema `mg2_p3d_n_state/1`, verified before unpickling);
- the two named input sources;
- the rule's raw sha256.

`emit` (forward) and `score` refuse on any mismatch.

The coefficients file is runtime state, kept local at `C:\t\mg2\freeze\mg2_coefficients.json`. Its hash
is in the rule. It is not committed, under the repository's data and artifacts rule; it is regenerated
byte-identically by `freeze`.

## 8. Operations from D0 (option 3)

Daily or weekly, all through `scripts\ops\workstation_heavy.ps1`:

0. **Receive and verify the day's input bundle** (§9). A date whose bundle is missing, late or
   refused is recorded as non-countable and is not processed further.
1. **Build the forward inputs-only layout** from the verified bundle only. The layout is snapshots and
   bands. It needs the same harness as `C:\swarm\v3layout`, without labels or market files, and must
   expose the parser version (§9.1, derived fields).
2. **Read the two named inputs from the bundle**, through the readers registered by the rule §8
   Clarification. No external fetch is allowed: forward `emit` refuses while either source is
   `PENDING` or `external_fetch`.
3. **Run the steps in order:**
   - `mg2_composite nowcast` (frozen refit; the dev-window control must reproduce `d2453d0d…`);
   - `emit`;
   - `check`.

   Results go under `C:\t\mg2\forward\<date>`.

No outcome, label, price or market file is opened before the look.

## 9. Input transfer

**Why this is needed.** Forward accrual runs on the workstation, but the captured inputs are on the
capture host, and the data mirror has been paused since 08-12. Master's ruling: a plan whose inputs
cannot arrive is not a binding.

This section is the exact specification for the host side, which master builds. **No host code is
built by this lane, and no host data was read to write it.** Every item below is derived from code:
- the readers in `weather.calibration.mg2_composite`;
- L3's `scan_replay_observations` / `_event_folders`;
- `weather.model.observed_running_max`;
- the MG-1 and L6 readers (`free_source_candidates.mg1`, `l6_stack`, `dev_scorecard.Table`);
- the v2 guidance builder `weather.reporting.research.guidance_extract`;
- the writers in `weather.collection.snapshot_store` (`SnapshotStore._set_paths` and its `*_COLUMNS`);
- `weather.paths.data_path`.

**Transfer direction.** The transfer is inputs only, one bundle per target date. Outcomes travel once,
at the look, by a separate transfer (§9.6).

### 9.1 Files (the exact list)

**Paths.** All paths are relative to the host data root, `weather.paths.data_path()`, which is
`<repo>\data`.
- `<slug>` is a US market-day folder name, `highest-temperature-in-<city>-on-<month>-<d>-<yyyy>`. It is
  resolved by `market_registry.spec_for_slug` with display unit F, for the 11 fixed markets.
- Each bundle for target date **D** covers the folders whose event date is D.
- The METAR part also covers the D−1 folders (F1b).

**Producer.** The per-folder files are written by `SnapshotStore.write` / `write_replay_input`, run
inside the capture workers (`weather.collection.snapshot_tracker`), into
`data_path("snapshots", <slug>)`. F4 is the shared forecast-payload content-addressed store (CAS)
written by `model_sources` (`shared_forecast_payload_cas`).

| # | Host path | Format | Used by | Fields that travel (allow-list; everything else is dropped) |
| --- | --- | --- | --- | --- |
| F1 | `snapshots\<slug>\replay_inputs.jsonl` (D folders) | JSONL, one captured-input replay payload per snapshot (`REPLAY_SCHEMA_VERSION`) | P3d_N `current_temp`, `high_so_far` (L8 `running_max_since_midnight`); L6 own-obs nowcast on captured METAR | top level: `schema_version`, `snapshot_id`, `captured_at_utc`, `captured_at_local`, `event_slug`, `target_date`, `model_version`, `captured_input_hash` (provenance only; it hashes the unstripped payload, so it cannot be re-verified on the bundle). `sources.metar`: the item envelope `ok`, `status`, `stale`, `fetched_at`, and `data`: `rows` (each row whole), `station_id`, `target_date_match`, `report_time`. **No station surface** (`sources.station`, `sources.station_observations`) travels: master 2026-10-25, METAR only. `sources.open_meteo_multimodel.data`: was provisional for the former arm A; **no MG-2 code reads it** under P3d_N, so it may be dropped from the allow-list (master's exporter call). |
| F1b | `snapshots\<slug>\replay_inputs.jsonl` (D−1 folders) | as F1 | L6 `prev_dmax` (the complete previous local date's routine METAR maximum) | `snapshot_id`, `captured_at_utc`, `captured_at_local`, `event_slug`, `target_date`, `sources.metar.data.rows`, last snapshot of the folder only |
| F2 | `snapshots\<slug>\snapshots_long.csv` | CSV, `snapshot_store.LONG_COLUMNS`, one row per snapshot × band | band support and the served vector `p_served` (MG-1's and MG-2's fallback, the rule-4 mask) | `snapshot_id`, `captured_at_utc`, `captured_at_local`, `event_slug`, `model_version`, `range_label`, `bin_kind`, `bin_value_c`, `bin_value_hi_c`, `model_probability`. The `_c` names hold native °F here (`AGENTS.md`). |
| F3 | `snapshots\<slug>\features_long.csv` | CSV, `snapshot_store.FEATURE_AUDIT_COLUMNS`, one row per snapshot | rule-4 floor F = max(`guidance_physical_floor`, `high_so_far`, `trusted_current_max`); `cutoff_hour` | `snapshot_id`, `captured_at_utc`, `captured_at_local`, `event_slug`, `target_date`, `model_version`, `cutoff_hour`, `guidance_physical_floor`, `high_so_far`, `trusted_current_max` |
| F4 | `snapshots\<slug>\forecast_payloads.jsonl`, or `forecast_payloads_long.csv` when the JSONL is absent (D−1, D, D+1 folders); the bundle always carries it as `forecast_payloads.jsonl` | JSONL/CSV, `snapshot_store.FORECAST_PAYLOAD_COLUMNS` | MG-1's NBM v2 centre and spread: the bulletin index and availability time of `guidance_extract.build_bulletin_index` / `select_v2` | rows with `source == "nbm_probabilistic_tmax"` only, and only those with `captured_at_utc` ≤ the D export cut (§9.3). Fields: `snapshot_id`, `captured_at_utc`, `event_slug`, `source`, `status`, `parser_version`, `provider_issue_time`, `provider_update_time`, `response_received_at`, `fetched_at`, `first_seen_at`, `cycle_key`, `payload_hash`, `payload_ref`, `payload_storage_scope`, `payload_bytes` |
| F5 | `forecast_payload_cas\<payload_ref>` | bytes: the NBM national bulletin (NBP text), content-addressed | v2 percentiles, mean and stddev, through the pinned parser (`guidance_extract_parser.PinnedParser`, `parser_version=2`) | only the blobs named by an admitted F4 row with `payload_storage_scope == "shared_market_invariant"`, deduplicated by `payload_hash`. Bytes are copied unchanged, and the receiver re-hashes each one against its `payload_hash`. |

**What the workstation derives, not transfers:**
- `row_key`, `date`, `local_hour`, `market`, `station`;
- the band frame (`kind`, `low`, `high`, `band_index`, `p_served`);
- the v2 columns (`v2_mean`, `v2_stddev`, `v2_available_at`, `v2_period_kind`, `v2_status`, `v2_cycle_key`, `v2_payload_hash`, `v2_issued_at`);
- **`v2_parser_version`**, stamped from the pinned parser module's sha256 in each built layout.

These are built by an inputs-only layout builder: `guidance_extract`'s v2 path, with its label and
market joins removed: `weather.calibration.mg2_inputs build` (§9.7). The binding reads nothing else.

**Stated per input half:**
- **MG-1's half (and the comparator):** F2, F3, F4, F5.
- **L6's half, once on captured METAR:** F1 `sources.metar`, plus F1b. Only
  `n_own` is used. The ring/upstream stations (`n_up`, `n_ring`) are not in the capture and not used.
- **P3d_N:** F1 `sources.metar`, and the v2 columns MG-1's half already derives from F4/F5.

**Resolved by master (2026-10-25):**
- **F1b `prev_dmax`.** D−1 METAR rows may travel as model input, provided no workstation code computes
  anything from them against bands or labels. The receiver only hashes and schema-checks `prev_day/`; the
  layout builder never opens it (pinned by `tests/calibration/test_mg2_inputs.py`: an import and AST scan
  of the receiver and builder, and a build that is byte-identical when `prev_day/` is garbage or absent).
- **Station surface: dropped.** Weather Underground-sourced station rows do not travel, and neither does
  any station surface. The serve definition changes accordingly: rule §8 Clarification C1 makes MG-2's
  `high_so_far` the METAR-only running max (`running_max_since_midnight(..., metar_only=True)`, default
  unchanged), equal to the serve value whenever the station surface is METAR. The capture carries no
  `sources.station` key, so the dev emission was already METAR-only.

**The allow-list is code.** `weather.calibration.mg2_input_allowlist` (stdlib only, no file access) holds
this section's lists, the forbidden-key set, the bundle path patterns, the export cut and the reference
projections. Its `allowlist_sha256()` is recorded in every bundle manifest, and the receiver refuses a
bundle whose sha differs. The host exporter imports the same module, so both sides embed the same bytes.

### 9.2 Exclusions (input side only)

**Allow-list.** The allow-list is §9.1. A file, column or key that is not listed does not travel. The
host exporter projects onto the allow-list; it never copies a file and deletes columns afterwards.

**Never transferred, as files:**
- `snapshots\<slug>\settlement.json`;
- `settlements\**`, including every `ledger.jsonl`;
- any `labels.parquet` / `market.parquet`;
- `snapshots_wide.csv`, `variant_predictions*`, `components*`, `snapshot_explanations*`,
  `source_status*`, `observation_payloads*`, `forecasts_long.csv` / `forecasts.jsonl`;
- the 88a and panel artifacts;
- wallet, order, fill, position and P&L ledgers;
- order-book and trade tapes;
- anything else under `data\`.

**Never transferred, as columns or keys.** Any of the following, at any depth, is forbidden:
- **Labels**, the scorecard's `LABELISH` set: `winner`, `settlement_high`, `settlement_bucket`,
  `settlement_source`, `is_winner`, `p_market_yes`, `best_bid`, `best_ask`, `market_mid`,
  `promotion_countable`, `label_source`.
- **Market prices**, which the binding does not need, since MG-2 vs MG-1 is weather-only:
  `market_yes`, `market_no`, `edge`, `variant_edge`, `last_trade_price`, `volume`, `liquidity`,
  `market_status`, `polymarket_market_id`, `condition_id`, `clob_token_ids`, `clob_yes_token_id`,
  `clob_no_token_id`, `enable_order_book`.
- **Settlement-series, history and station surfaces:**
  - source keys `wu_history`, `wu_current`, `local_history`, `station_observations`, `station`, and the
    key `station_observation_source`;
  - every key starting `wu_`;
  - columns `wu_history_high_c`, `wu_current_c`, `wu_max_since_7am_c`, `latest_wu_history_time`,
    `latest_wu_history_minute`, `latest_wu_history_temp`;
  - every `reanalysis_prev_*` column;
  - `settlement_authority`, `quality_grade`.
- **Not needed:** the served `recorded_distribution`. F2 carries `p_served`.

**Receiver check (workstation, before any parse beyond keys and headers):**
- each CSV header must equal its allow-list exactly;
- each JSONL record's key tree must be inside its allow-list;
- the recursive forbidden-key list above is checked on every record. METAR rows travel whole, so they
  are scanned key by key.

**On a forbidden or unlisted name:**
- **Refuse the whole bundle.**
- **Quarantine it.** It is moved to `data\inbox\mg2-inputs\_quarantine\<D>\` unread. Only the
  offending path and key name are logged, never a value.
- **Record D as non-countable**, with reason `forbidden_field`.
- **Do not repair it on the workstation.** A corrected bundle may be re-exported once by the host, and
  only before the §9.3 deadline.

### 9.3 Mechanism (proposal; host side built by master)

**Exporter.** A new host script `scripts\ops\mg2_input_export.ps1`, which wraps a read-only Python
exporter. It runs as a new Scheduler task, `WeatherMg2InputExport`, built and registered by master.
- **Reads:** only the §9.1 paths.
- **Writes:** only `data\exports\mg2-inputs\<D>\`.
- **Imports:** nothing from the capture loop closure.
- **Lease:** it holds the shared lease from `scripts\ops\workload_admission.ps1`.

**Bundle layout.** Paths mirror the host data root, so the verified bundle is itself a replay root for
the existing readers (`<bundle>\snapshots\<slug>\replay_inputs.jsonl`):

```text
<D>\snapshots\<slug_D>\replay_inputs.jsonl             (F1, projected)
<D>\snapshots\<slug_D>\snapshots_long.csv              (F2, projected; header exactly the allow-list)
<D>\snapshots\<slug_D>\features_long.csv               (F3, projected; header exactly the allow-list)
<D>\snapshots\<slug_D-1|D|D+1>\forecast_payloads.jsonl  (F4, NBM rows only, projected)
<D>\prev_day\<slug_D-1>\metar_rows.jsonl                (F1b: the folder's last snapshot, METAR rows)
<D>\forecast_payload_cas\sha256\<hh>\<sha256>.blob      (F5, unchanged bytes)
<D>\manifest.json
<D>\manifest.json.sha256                               (written last: the ready marker)
```

`manifest.json` holds:
- `schema` `mg2_input_bundle/1` and target date D;
- the export cut and the export start and end times in UTC;
- the exporter's code sha256 and the host repository HEAD;
- `allowlist_sha256`, from `mg2_input_allowlist.allowlist_sha256()` (both sides import the same module);
- for each file: bundle path, sha256, bytes and row count; source host path, source size and source
  mtime;
- per market: expected (the 11), present, and the reason when absent;
- `export_cut_utc`, which must equal `mg2_input_allowlist.export_cut_utc(D)`;
- `files`: a list of `{path, sha256, bytes, rows}` (rows = JSONL records or CSV data rows; null for
  blobs), plus the host source path, size and mtime;
- NBM manifest rows and blobs, with any missing-blob count.

**When:**
- **Export cut:** local midnight ending D in the westernmost of the 11 markets, so every local hour
  00-23 of D is captured in every market.
- **Run time:** 04:15 host local on D+1. That is after the cut and after the 01:00–04:00 quiet window,
  inside the 00:30–09:00 admitted window, and it finishes before 06:00.
- **Retry:** the exporter re-runs once at 07:00 if the first run fails. It never runs later.

**How the bundle moves.** The workstation pulls the dated folder read-only over a dedicated share. It
copies only `data\exports\mg2-inputs\<D>\` into the workstation's `data\inbox\mg2-inputs\<D>\`. This is
a new narrow channel, not a restart of the paused data mirror: the mirror carries settlements and
ledgers and must not be the route.
- Master chooses the share; the pull takes it as a parameter (`--share-root`).
- The pull, receiver and builder are built: `python -m weather.calibration.mg2_inputs pull | receive |
  build` (§9.7).

**Integrity (receiver):**
1. `manifest.json.sha256` matches the manifest.
2. Every listed file is present, and its sha256, bytes and row count match.
3. There are no unlisted files.
4. The allow-list sha equals the receiver's.
5. The §9.2 schema check passes.
6. Every F1-F4 row has `target_date` D (F1b: D−1) and `captured_at_utc` ≤ the export cut.
7. All 11 markets are present.
8. Every F5 blob re-hashes to its `payload_hash`.

**Result:** a verified bundle is moved to `data\inbox\mg2-inputs\<D>\verified\`. Any failure refuses
the bundle and records why:
- a forbidden or unlisted name (checks 3 and 5) quarantines it to
  `data\inbox\mg2-inputs\_quarantine\<D>\attempt-<n>\`, reason `forbidden_field`;
- any other failure moves it to `data\inbox\mg2-inputs\_refused\<D>\attempt-<n>\`, status
  `refused:<first failed check>`.

At most two attempts are received per date (the first export plus one host re-export). After the second
failure the date is closed. The pull skips a share bundle whose manifest sha was already refused, so an
hourly pull cannot spend the second attempt on the same bytes.

**Deadline:** a bundle not verified by 23:59 workstation local on D+1 is late. It is refused even if it
arrives afterwards. There is no backfill.

**Receipt ledger.** Every outcome is appended to the workstation receipt ledger
`C:\t\mg2\forward\input_receipts.jsonl` the same day: D, status (`verified` / `missing` / `late` /
`refused:<reason>` / `quarantined`), the manifest sha and the check results. This happens before any
MG-2 processing of D. The ledger is append-only and is never edited.

### 9.4 Countability (consistent with N = 45)

**Input-countable.** A target date D is input-countable when both hold:
- its bundle is `verified` by the deadline;
- the outcome-blind `check` on D passes: coverage ≥ 90% of 00-16 snapshots, PIT, replay reproduction to
  1e-12, and parser version 2.

Both are recorded in the receipt ledger before the look, and neither reads an outcome.
- **Missing, late, refused or quarantined bundle:** D is non-countable.
- **A missing market:** the whole date is non-countable, because the gate uses the fixed 11 markets.
  Relaxing this would take a dated Clarification before D0.
- **A failed check:** D is non-countable for that date only. It does not void the look.

**Countable dates for the look** are dates that are input-countable **and** promotion-countable.
Promotion-countability is the same settlement-quality flag MG-1's rule uses. It is learned only at the
look, from the §9.6 label transfer.

**The look's date set:**
- **Membership:** the first 45 countable dates in date order from the branch's start, D0 (Branch 2) or
  `MG1_LAST` + 1 (Branch 1).
- **No skipping:** a countable date is never excluded, so there is no skipping inside the 45.
- **Read date:** every non-countable date moves the 45th date, and so the earliest read, one day later.

Input-countability is fixed daily, before and without outcomes, so the date set cannot be chosen on
results. Rule §3 carries this definition.

### 9.5 What this changes in operations

§8 step 0 receives and verifies the bundle. Steps 1-3 read only `verified\` bundles. MG-2 never reads
the host data root directly.

### 9.6 The one outcome transfer (at the look only)

Labels travel once: after the earliest read date and, in Branch 2, after MG-1's look completes. That is
a single host export of `settlement_bucket` / winner and `promotion_countable` for the input-countable
dates in order, until 45 countable dates are found. It goes to a separate inbox path and is never
merged into an input bundle.
- **Branch 1:** this needs no owner decision.
- **Branch 2:** it needs the §2 decision id in the rule.

The daily channel never carries it.

### 9.7 Workstation scripts and how they would be scheduled (not registered)

Built on this branch. **No Scheduler task is registered on the workstation.** Master builds and registers
the host exporter and the share.

| Step | Command | When (workstation local) | Wrapper |
| --- | --- | --- | --- |
| pull | `python -m weather.calibration.mg2_inputs pull --share-root <share> --inbox data\inbox\mg2-inputs --date <D>` | 06:30 on D+1, then hourly until 23:00 | none (a small copy; never writes the share) |
| receive | `python -m weather.calibration.mg2_inputs receive --inbox data\inbox\mg2-inputs --date <D>` | right after each pull | none |
| build | `python -m weather.calibration.mg2_inputs build --bundle data\inbox\mg2-inputs\<D>\verified --date <D> --out C:\t\mg2\forward\layout\<D> --parser-worktree <pinned 2e17ce0eb worktree>` | after `verified` | `workstation_heavy.ps1 -Queue -MinAvailableMemoryGB 3` |
| emit, check | `mg2_composite emit` / `check` on the built layout (§8 steps 1-3) | after build | `workstation_heavy.ps1 -Queue` |

- `pull` returns `not_ready` until `manifest.json.sha256` exists. It also returns `already_pulled`,
  `already_recorded` or `unchanged_since_refusal`. None of these writes the ledger.
- `receive` appends exactly one ledger line per outcome: `verified`, `quarantined`, `refused:<check>`,
  `late` or `missing`. `not_ready` writes nothing. The first `receive` at or after 00:00 on D+2 records
  `late` (a bundle is waiting) or `missing` (none arrived).
- The builder reads only `verified\` and re-hashes the files it reads against the verified manifest. It
  never opens `prev_day\`. It reuses `guidance_extract`'s v2 selection (copied, and pinned equal by a
  test) without its label and market joins. It stamps `v2_parser_version` = 2 and the parser module
  sha256 on every row.
- Daily per-date runs need a forward multi-date layout for `emit`; concatenating the per-date layouts is
  an open item (§11).

## 10. Roll class

The branch is **ROLL-SENSITIVE**. It carries L8's `src/weather/model/model_base.py`,
`model_features.py` and `model_distribution.py` edits. Those files are in the capture closure through
`snapshot_tracker` → `toronto_model`. The edits are shadow-switch only and production is
byte-identical, but the files change.

This lane's own additions are roll-free:
- `src/weather/calibration/mg2_composite.py`, imported by nothing in `src/` or `app/` (test-pinned);
- the tests;
- the allowlists (`.ps1`, `.codex`);
- the docs.

Run `scripts\ops\roll_verdict.ps1 -Branch claude/mg2-composite-binding-20261025` on the capture host for
the mechanical verdict. On this workstation it cannot read the supervisors' closure evidence.

**Binding needs no merge.** The forward accrual runs from this branch on the workstation. A landing
can wait for a quiet window.

**Capture-host import (master ruling 2026-10-26).** MG-2, the C7/C8 gates and the B-1 scorer score only
on the workstation, from host-exported bundles (§9). By design their modules (`mg2_composite`,
`mg2_p3d_n`, `b_scorer` and the research modules they import, such as `r0_ols_floor_challenger` and
`ols_floor_ladder`) cannot be imported on the capture host: they refuse there, and their tests skip there.
The importer ratchets in `tests/calibration/test_ols_floor_ladder.py` and
`tests/calibration/test_r0_ols_floor_challenger.py` list them as WS-only importers. The host side is only
the stdlib exporter (`weather.calibration.mg2_input_export`, branch `claude/mg2-input-export-20261026`) and
the allow-list. Any host serve path for MG-2 would first
require moving the shared pure functions into a neutral module that imports cleanly on the host.

## 11. Open items

- **Fable review (one pass), before the binding commit and D0.** Master's scope: the binding, the
  readers, the receiver and the exporter allow-list together. Files, as the diff of base `505f35ffd`
  against this branch's head:
  - `src/weather/calibration/mg2_composite.py`, `mg2_inputs.py`, `mg2_input_allowlist.py`
  - `src/weather/model/observed_running_max.py` (the `metar_only` switch) and
    `src/weather/calibration/r0_ols_floor_challenger.py` (its pass-through)
  - `tests/calibration/test_mg2_composite.py`, `tests/calibration/test_mg2_inputs.py`,
    `tests/model/test_high_so_far_parity_shadow.py`, `tests/operations/test_mg2_composite_admission.py`
  - `docs/research/mg2-composite-binding-2026-10-25/`
  - the allowlist lines, and master's host exporter once built

  Reading the merged L8 and L3 code is optional context.
- **Owner:** the option 2 exemption, or Branch 1 by default.
- **Serve parity.** These block D0:
  - the L6 re-freeze on the captured-METAR nowcast, after the reader reproduces L3's `3806687c…`;
  - a re-sized MDE on the P3d_N design.

  The N/MDE table in §3 is for the dev-source design.
- **Retrain-window overlap.** The retrain window is armed, not dated. If it is declared and P3d_N is
  ruled a retrain-family candidate, MG-2's post-13 slot overlaps it. This needs an owner ruling.
- **Input transfer (master, host).** The `WeatherMg2InputExport` exporter (importing
  `mg2_input_allowlist`) and task, and the share. Until both exist, D0 cannot be set.
- **Forward multi-date layout.** `build` writes one layout per target date; `emit` and `score` read one
  layout over the window. `mg2_inputs concat` joins verified per-date layouts into that one window,
  refusing a duplicate date or `row_key`, and refusing a tampered, mixed or unreceipted layout.
- **Workstation scheduling.** §9.7 lists how the scripts would be scheduled; nothing is registered.
