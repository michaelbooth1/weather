# MG-3 state rule amendment FWD-1: the 07-12 P3d_H state rebuilt on FORWARD_CENTRES (item 341)

Lane L3, 2026-10-27. This amends the MG-3 frozen P3d_H state rule `rule_mg3_p3dh_state.md`
`9e63899ddcfcbd795f10f0437c7bd9f9b6fc9740767b8d824818ef0f7f95cc5d` (DEV_WINDOW_LEDGER row 38).

- **Approval.** Master approved the item 341 proposal on 2026-10-27, relayed by the coordinator. The proposal is
  `C:\t\l3\mg3rebuild\proposal.md`, sha256 `9bde9b0de6f2096451cba3ad673143bc98f5e94e6a0d7f6f94a0ac6b5dccc3bf`.
- **Before any fit.** This file is written and pushed before any fit, and before any read of the HRRR extras it
  names. Ledger row 66 is written PENDING before the first run. Nothing in §3-§6 runs until master has reviewed
  this amendment.
- **Companion documents.** The decision-rule changes are in `clarification_mg3_dc1_fwd1.md`, which amends MG3-DC-1
  and clarification 0712-1. The re-scoped comparison is in `rule_mg3_fwdcmp.md`, ledger row 67.
- **Evidence class.** This rule covers a freeze, its controls, one weight refit and one history LOYO:
  - the weight refit reads dev labels ≤ 2026-09-29, exactly as row 40 did;
  - the history LOYO uses 2021-25 only.
  - No row dated 2026 is trained on or scored.
  - No outcome, label, price or market row dated after 2026-09-29 is read.

Unless another file is named, line references are to `src/weather/calibration/pooled_residual_model.py` on
`claude/mg3-freeze-20261026` @ `b750df163`.

## 0. Why (the defect this fixes)

### How the 07-12 state was built

Row 38 built the 07-12 state from `dev_training_frame` (`:1005-1011`, called at `:6423`), which covers Aug-Sep
2021-25 only. The state is `e92764773e1614aae548ccfd74b3a60740f25105578abd045b0808fe6dd159c0`. Three fields follow
from that frame:

| Field | What row 38 stored |
| --- | --- |
| `centres` | the four Aug-Sep centres (`:6429`) |
| `buckets` | the 09-07 centre's `bucket_space` only (`:1010`) |
| `train_y` | Aug-Sep labels only |

### What happens on an Oct-Dec target date

- **Centre.** `state_features` (`mg_serve_core.py:531-552`) picks the nearest Aug-Sep centre, which is 09-22 for
  any December date.
- **Normal.** The (market, centre) normal is the September one. For Chicago on 12-15 it is about 38.7 °F off.
- **mu0.** mu0 is about 38.7 °F off when NBM is missing.
- **Bias.** There is no (market, "oct_dec") bias, so the state falls back to `bias_global`. mu0 is about 1.2 °F off
  when NBM is present.
- **Climatology mix.** The 2% p_clim mix sits on season-impossible bands, which pushes mass onto the top `gte` band.

### Why the fix is a rebuild

MG-2's served forward state `c6cc39f7…` (`forward_fit`, `:6115`) avoids all of this. It trains on
`forward_training_frame` (`:6040-6052`) with `FORWARD_CENTRES` (`:5840`). The fix is to build MG-3's 07-12 state
the same way. Nothing in the serve path changes: `state_features` reads `centres`, `season_of` and `buckets`
from the state.

## 1. What is rebuilt: the 07-12 block only

### 1.1 Arm, hyperparameters and constants: all unchanged

| Item | Frozen value |
| --- | --- |
| Arm | `RK_ARMS["P3d_H"]` (`:3785-3790`): `_rung_entry(train, simple=False, extra_hgb=("k_max", "k_gap", "k_tcdc"))`. The `mg3_freeze_state` arm assertion (`:6416-6418`) stays |
| Mean and scale models | `MEAN_HGB_PARAMS` (`:130`); the scale-model construction; inner-LOYO z set as `_rung_entry` (`:1371`) |
| Bias | `bias_by="season"`, the default (`:462`) |
| Constants | `FLOOR_MIX_CLIM` 0.02, `KERNEL_BANDWIDTH` 0.25, `MIN_SCALE` 0.5, clim alpha 0.10 |
| Raw columns | `DEV_KEEP_X` = (x_high_so_far, x_current_temp) (`:995`) |
| Hours | `RR_HOURS` 07-12: one fit per local hour, pooled over the 11 R0 markets |
| Conversion | **disabled**, as fitted: raw high_so_far and current_temp, with no WU rounding. This differs from MG-2's state and is kept as frozen |
| HRRR point rule | RN-1 `e4869491a8480f302c0bb4c33b0d55d4110ef98551f0db26e59d3441e204004b`: `rr_point_rule` on land `22069beebb5609755b35621bac05e91a1b35e434670c993a93a8aca9434fd7d6`, with KSFO index 3 and every other station index 4 |
| NBM | `attach_training_nbm` with the L9 corpus `1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd` |
| Schema and serve math | `mg3_p3d_h_state/1`, the row 38 rule §2, unchanged |

No hyperparameter, column, hour, centre list or constant is tuned. A fit whose controls fail stops (§3.5).

### 1.2 Training rows (the change)

- **Frame.** `forward_training_frame(C:\t\l2\records, R0_MARKETS)` (`:6040`):
  - every `FORWARD_CENTRES` record: 2026-08-08, 08-23, 09-07, 09-22, 10-10, 10-25, 11-09, 11-24 and 12-09;
  - target years 2021-25;
  - columns reduced to `DEV_KEEP_X`;
  - the frame's hours 07-12 kept.
- **Refusals.** The fit refuses in three cases, the second being `forward_fit`'s guard (`:6136-6137`):
  - a year of 2026 or later;
  - a year outside `FORWARD_YEARS`;
  - a duplicate (market, target_date, hour) key across the centres' records.
- **Disclosed and unchanged.**
  - `FORWARD_CENTRES` has no 12-24 centre.
  - `train_y`, and so p_clim, pools the Aug-Dec labels per market and hour. This is MG-2's own design.

### 1.3 Training HRRR: the union of three corpora

The single Aug-Sep corpus (`_mg3_hrrr` 07-12 branch, `:6268-6285`) is replaced by the union of three sealed
corpora:

| Corpus | Seal | Days used |
| --- | --- | --- |
| `C:\t\l13\hrrr_0712` (Aug-Sep) | manifest `fef6c307a411e6373af05830b55c4dff8cb23d08f46e18f07949821f08fe88e6` (`RR_CORPUS_SHA256`, `:4813`), unchanged | `_rr_train_day` (`:4889`), Aug-Sep 2021-25 |
| `C:\t\l13\hrrr_cool0712` (Oct-Dec 2024-25) | SHA256SUMS `fe2dad2c9b2567ff28a9916f42c51a9196d33fc79f40690332745c2ed2acbc4d` | target dates 2024-10-01..12-31 and 2025-10-01..12-31 |
| `C:\t\l16odc\hrrr_cool0712_2123` (Oct-Dec 2021-23, R-ODC's backfill) | its SHA256SUMS, recorded in row 66 before any read | target dates 2021-23, months 10-12 |

**Access.**
- Master granted item 341 read access on 2026-10-27. The grant is recorded as an append-only line in
  `C:\t\l13\hrrr_cool0712_ACCESS.txt`.
- No extra is read before master has reviewed this rule, and none before the 2021-23 seal exists.
- Sealed files are never written. Every file must hash to its SHA256SUMS line, or the run refuses.

**Union rules (any failure refuses the build).**
- **One station list.** `stations.json` must be byte-identical across the three corpora. The Aug-Sep and 2024-25
  corpora both hash to `52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3`. The 2021-23 corpus
  must equal it.
- **One point rule.** `rr_point_rule` is recomputed against each corpus and must give the RN-1 choice on all three.
- **No overlaps.** A (station, target date, hour) key present in more than one corpus refuses the build.
- **No imputation.** A key with no cycle published in time keeps NaN extras, the HGB's native missing value. This
  covers the 70 `no_cycle_published_in_time` keys of the 2024-25 seal and any such key in 2021-23. Such keys are
  counted and never filled from another cycle.
- **New pins.** Each new corpus gets pinned constants analogous to `RR_CORPUS_SHA256`.

**The dev HRRR is unchanged:** `_rr_dev_day` (`:4893`) on `fef6c307…`.

### 1.4 Coverage gate (refuse, never warn)

**Rule.** HRRR training coverage, from `rk_parity_training` (`:3972`), must be at least `RK_COVERAGE_MIN` = 0.95
in **every** (season, year) cell:
- the cells are {aug_sep, oct_dec} × {2021, …, 2025}, ten in all;
- coverage is the share of training rows whose (station, date, hour) key has all three extras finite.

**Why per cell, not pooled.** Missing extras clustered in one season or year would teach the HGB that "NaN means
cool season".

**Failure.** A cell below 0.95 refuses the freeze. MG3-DC-1's fallback then applies (`clarification_mg3_dc1_fwd1.md`
§3).

### 1.5 What the state stores (as `forward_fit`, `:6150-6175`)

**Changed fields:**

| Field | Value |
| --- | --- |
| `centres` | `list(FORWARD_CENTRES)` (replaces `:6429`) |
| `buckets` | per market, the union of `bucket_space` over every `FORWARD_CENTRES` record (`:6043-6052`) |
| `season_of` | as `forward_fit` |

**Provenance adds:**
- `availability_counts(frame)` (`:6054`);
- `train_window` (centres, first and last month-day);
- training rows per (season, year);
- per-cell HRRR coverage;
- the three corpora's seal shas;
- this amendment's sha256.

**Every other field** is as in row 38's rule §2: `extra_hgb`, `point_rule`, conversion disabled, `constants` and
`hours`.

## 2. The 13-16 state: unserved, binding slot PENDING permanently

The 13-16 state is `e891d884e06164a6925f6b2bbf1c7756529cb35222ab0c8c863552cfa7457db7`.

**It is never served.**
- SM-H `b6bc242a…` replaced it at 13-15 (binding note `6507946e…`, ledger row 52).
- San Francisco 13-16 and h16 are MG-2's bound arm.
- `mg3_serve.py` never loads it.

**It is not refitted.** It has the same Aug-Sep-centres defect as the 07-12 state.

**Binding.**
- MG-3's release binding keeps `states["13-16"]` as `PENDING` permanently.
- `mg3_verify_release` must accept that slot as PENDING, and must refuse if it is ever filled.
- MG3-DC-1's "every §2.3 field filled" condition excludes this slot (`clarification_mg3_dc1_fwd1.md` §2).

## 3. Controls (the SM-H pattern; they replace row 38's re-emit identity for 07-12)

Row 38's control required byte identity with the old dev emit `a2dc30e2…`. A new state cannot meet it. These
controls replace it. All tolerances are fixed now.

1. **Inputs.**
   - Every input sha in §1 must match.
   - Training rows per (season, year) and per-cell coverage are recorded.
   - The coverage gate in §1.4 must pass.
2. **Export parity (every training row).**
   - Reload the state from its file only after its sha256 is checked.
   - Then, on every training row with a finite high_so_far and current_temp, compare:
     - the frozen state's serve math (`mg3_state_distribution`, `:6322`);
     - the in-process fit's distribution (`_dist_from_fit`).
   - PASS if max |Δp| ≤ 1e-9 over each market's buckets.
3. **Dev re-emit (new reference).**
   - Re-run the 07-12 dev emit exactly as row 38 did:
     - layout `C:\swarm\v3layout`;
     - the same replay root and eligibility;
     - the RN-1 2026 HRRR row hook;
     - dev dates 2026-08-01..09-29, inputs only.
   - Every P3d_H distribution comes from the frozen state through the serve math.
   - Write it twice, to separate files. PASS if they are byte-identical.
   - Its sha becomes the new `MG3_BLOCKS["07-12"]["reference_sha256"]` and the `MG3_RR_EMIT["dev_P3d_H.jsonl"]`
     entry (`:6260-6266`).
4. **Fold reproduction.** This runs after the §5 LOYO exists. It shows that the served builder is the scored
   specification.
   - For each hour and held-out year, build a fold state with the same state builder on the other four years'
     rows.
   - Apply the §5 fold support exactly as the LOYO applied it: `buckets` replaced, `train_y` edge-clipped.
   - Serve the held-out rows through `mg3_state_distribution`.
   - PASS if the keys (hour, year, market, date) equal §5's P3d_H rows, with none missing or extra, and every
     edge-folded distribution matches to 1e-9.
5. **Failure.**
   - FAIL of any control stops the rebuild. The state is not bound, and the failure is reported with the first
     differing row.
   - No tolerance, input or code is changed to make a control pass without a new ruling.
   - The fallback in `clarification_mg3_dc1_fwd1.md` §3 applies.

## 4. Weight refit RF-2 (once; the rule is unchanged)

RF-2 refits the weights once, under the unchanged weight rule
`4fb02a2cec9a6c5c4fc06e811bd69d3ba35721d0650475c8584de313765ef6e8`. It uses the same function and code path as RF-1
(`mg3_refit_weights_rf1`, `:6595`; note `b13f2e03…`).

**Inputs.**
- the new 07-12 dev P3d_H vectors from §3.3;
- the SM-L6 partner's dev vectors `2366d67c5cdd6eb26b98064807210ade1c657829b7fa8e683535b94a9a2faa76`;
- season nowcasts `714fa14e04c416da922803514fea1de8fe64459a0ea543878ddddfd6bc34896a`;
- dev dates 2026-08-01..09-29;
- dev labels ≤ 2026-09-29, read as row 40 read them. Nothing is scored.

**Checks, as RF-1.**
- **Control.** The unchanged function reproduces the old table `c7b8ebc0…` from its old inputs, with a difference
  of 0.0.
- **Identity.** Same row coverage as the inputs, and no duplicates.
- **Coverage.** Share at least 0.95 in every hour.

**Output.** `C:\t\l3\mg3fwd\weights_rf2\blend_l6_H_weights.json` plus a sidecar.

**What it replaces.** Its sha replaces RF-1 `891be564…` in the MG-3 07-12 binding (`clarification_mg3_dc1_fwd1.md`
§1). The partner stays SM-L6 `800072c7…`.

**Disclosure.** The stated limitation of MG3-DC-1 §2.2 still applies: the weights are fitted on Aug-Sep dev dates
for a partner built for Oct-Dec.

## 5. History LOYO (shared by the §2.2a drop check and row 67)

- **Folds.** Blocked leave-one-year-out over 2021-25. For each held-out year y and each hour 07-12:
  - fit the §1 specification on the other four years' §1.2 rows, all nine centres, with the §1.3 union HRRR;
  - use the same fit call that the state builder makes.
- **Held-out rows.**
  - **Oct-Dec rows** (the five Oct-Dec centres) are the decision rows.
  - **Aug-Sep rows** are reported only.
- **Per-fold support (no held-out outcome enters the support).** This uses R-ODC's construction, at env commit
  `701b7bb5d554a75914d224b4f2058431e5c4de50` (`rodc_octdec.py` sha256
  `14472030ae3827f174b751cda8c04d573fb905e578ede06182ad8d14494445de`).
  - **Support.** Per market, every integer from the minimum to the maximum of y over the four training years' rows
    of the same season, hours 07-12. This is `fold_support` semantics; the Aug-Sep reported rows use the Aug-Sep
    training rows. The function refuses if the held-out year is present.
  - **Training labels.** `train_y` is clipped into [min, max] (`open_edges`).
  - **Scoring.** Every scored distribution is folded onto the support with `<= min` / `>= max` edge buckets, and y
    is clipped the same way (`edge_brier`). Each arm's distribution is folded before scoring, so all arms are
    scored on one partition.
  - **Reuse.** The implementation imports these functions or reproduces them exactly, and a test proves equality on
    fixtures.
- **Blend.** The blend is the row 49 construction (rule `55c7ad4a895b5e111ea5d35dd6c9b86d468be6a15d18acbfa6fd96d0df69d0f5`), with two
  substitutions:
  - the P3d_H term is the fold distribution;
  - the weights w_h are RF-2.
  The rest of the construction:
  - the L6 term is SM-L6 from the row 46 LOYO vectors `loyo_vectors.parquet`
    `0fde7553ffba47cc37ca54a342d59ccbfd3adcd3e1da53bb18ac4548ad35d433`, held-out year only;
  - the stop check reproduces `loyo.json` `07ef7810d81e434c93e08e552d3ca2df0ec195790a52b6431e578ab3ce515919`;
  - blend = w_h · P3d_H + (1 − w_h) · SM-L6, bucket by bucket;
  - the MG-1 fallback and rule-4 floor are as MG-3 serves them.
- **Outputs.**
  - LOYO rows (keys, per-arm distributions and Brier, and support per fold and market as [min, max, count]);
  - `y_in_support` / `y_below_support` / `y_above_support` counts;
  - no-cycle counts.
  These outputs feed:
  - the §3.4 fold control;
  - the drop check (`clarification_mg3_dc1_fwd1.md` §1);
  - the §6 re-size;
  - row 67's COMP′.
- **Year scope.** Every fold runs once, on 2021-25 together. Nothing is fitted or scored before the 2021-23 seal
  exists.

## 6. Positive control (re-scoped row 41)

The MG-3 emitter (`mg3_serve`) runs on the dev window 2026-08-01..09-29 from the bound files. It must reproduce two
things to 1e-9:

1. **07-12.** Using the rebuilt state, RF-2 and the SM-L6 partner, it reproduces:
   - the §3.3 P3d_H dev vectors;
   - the RF-2 blend on the same rows, recomputed from those vectors.
2. **13-15.** Using SM-H `b6bc242a…`, it reproduces `mg3_state_distribution` on the same dev rows (inputs only).

The original row 41 targets no longer exist. They were R-R `rr_score.json` gate 4, which was the Aug-Sep arm, and
R-K gate 3, which SM-H replaced at 13-15. This control replaces them. PASS is required before the binding commit.

## 7. Outputs (outside the repository, write-once)

`C:\t\l3\mg3fwd\`:
- `state_0712\p3d_h_state.pkl`, `p3d_h_state.json`, `export_parity.json`, `control\dev_P3d_H.jsonl` (and the second
  write), `fold_control.json`, `control.json`;
- `weights_rf2\`;
- `loyo\` (rows, support, summary);
- `posctl\`.

An existing file refuses the run.

## 8. Mechanics and limits

- **Code.** New commits on top of `claude/mg3-freeze-20261026` @ `b750df163`, with no force-push and no rebase:
  - `mg3_freeze_state` 07-12 (`:6380-6505`);
  - `_mg3_hrrr` (`:6268-6297`);
  - the pins at `:6260-6266`, `:6587-6590` and `:7347`;
  - the tests pinning old shas: `tests/calibration/test_mg3_freeze.py:350`, `tests/model/test_mg3_serve_parity.py:31`
    and the `tests/model/test_mg3_serve.py` docstring.
- **Serve path.** No logic change to `mg_serve_core.state_features` or to `mg3_serve.py`. Only the bound shas
  change.
- **How heavy steps run.** Through `scripts/ops/workstation_heavy.ps1 -Queue`, serially, with OMP/MKL/OPENBLAS=10 and
  `-MinAvailableMemoryGB 3`.
- **Order.** This rule pushed, then master review, then the §3.1-3.3 freeze, then §4, then §5, then §3.4 and §6,
  then the binding.
- **Limits.**
  - Data ≤ 2026-09-29.
  - No paid data and no new dependency.
  - No change to MG-2, B, PT-1 or MG-1, or to R-ODC (row 65, L8, which runs as declared).
- **Outside this rule.** The January wrap-around of nearest-centre selection stays in item 341 under master's own
  assignment, with a 12-01 deadline. MG-3's window ends before January.
