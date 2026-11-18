# Toronto native guidance (ECCC GEM and citypage) against the market: P0 rule (ledger row 90)

Status: pre-declared before any computation (2026-10-30, lane L8). Evidence class: dev-window kill-only P0
screen. It is its own arm with its own K. It is not pooled with rows 77, 78, 81 or 85-89. Nothing here is a
release, serving, capture or scheduling decision. Eligibility: coordinator ruling 2026-10-30 (lever map item 4),
accepted by master with the three additions in section 3.

## 1. Stated reason (written before any read)

`C:/t/l8tor/eccc_reason.txt`, sha256 `a92ecabdd07213f50f5229c4a99f9cb8e27f3b7cb262d6062fde9f1586c24c24`.

- GEM, RDPS and HRDPS are Canada's native NWP family. They are independent of the GFS, HRRR, NAM, IFS, AIGFS and
  BEST centres that died in the US market-residual sweep (X46-X53), and of the NBM blend that died at the Toronto
  P0 (X64, X65).
- The citypage is Environment Canada's official Toronto forecast. A crowd that uses US apps may under-weight it.
- Neither has ever been scored on its own for Toronto (register S13 CAPTURED-NOT-SCORED, L21, order 12). The sweep
  had no Toronto rows, and L14 tested only the NBM NBP bulletin.

Counterpoints, also stated before any read:

- The citypage forecast high is already a pooled served consensus vote.
- Production's `eccc_gem` is Open-Meteo's `/v1/gem` endpoint, the same pipeline as the dead OM-* centres.
- The Toronto NBM centre died at P0.

## 2. Machinery

The statistic is identical to `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md`
(sha256 `85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), sections 1, 4 and 5, through
`weather.calibration.mr_sweep` unchanged:

- market moments with the sigma^2 floor 0.25, and the exponential tilt;
- the type C band signal s_b = (x - mu_m) * (z_b - mu_m) / sigma_m^2, with x in native °C;
- the calibration-matched disagreement placebo c_pl(d) = m(d) + (c(d') - m(d')) (`market_blend.placebo_vector`,
  J = 20, seeds 20260921 + j);
- Delta = rho_c - mean_j rho_pl,j as a paired date-cluster bootstrap (B = 10,000 draws, seed 20261024, draw b uses
  derangement b mod 20), with a one-sided p;
- UNTESTABLE below 20 covered dates or 1,000 population snapshots.

The Toronto table is the row 77 Toronto table, which the dev scorecard layout does not carry (row 77 rule
`docs/research/toronto-nbm-sprint-2026-10-30/rule_toronto_nbm.md` sha256 `4af6cb4f…a65`, clarifications 2
`610fba9cc2f58669602171f64588e60357dd46e3`, 5 `94494e4b409d443004c06bc242c71ad10bcbf5d5`, 6
`f0df61c21b32a681a23ed193b07ed9d6261f4c13` and 6b `4ef1cada0ddef72997a9d709eaa9d8dde795417e`):

- **Snapshots:** the captured replay folders `highest-temperature-in-toronto-on-<month>-<day>-2026` under
  `data/inbox/replay-inputs-le0929` (SHA256SUMS sha256
  `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82`). The target date D is the slug's date. A
  record is kept only if its capture instant, in America/Toronto, falls on D and its local hour is in the block.
  The last complete record of a snapshot id wins. A line that does not parse is skipped and listed.
- **Market m:** `data/inbox/tapes-toronto-0801-0929` (SHA256SUMS sha256
  `a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0`; every per-date file is checked against it).
  The capture-time group is the latest tape group with captured_at <= t_c and t_c - captured_at <= 600 s. Every
  row's book_time must be <= t_c, and its bins must form one °C partition (lte, eq..., gte, contiguous). Failing
  groups are skipped, walking back within the 600 s limit. The displayed price follows clarification 2, 6 and 6b:
  - the midpoint when the spread is <= 0.10, a missing side counting as its bound (bid 0, ask 1);
  - otherwise `gamma_last_trade_price`;
  - otherwise the midpoint.
  A NO row's midpoint is complemented. A snapshot with no valid group is dropped before any label is joined.
- **Units:** bins are parsed with `expected_unit="C"`, and a row whose unit is not C refuses the run. Candidate
  values are native °C. Nothing is converted to °F.
- **Floor:** the METAR maximum of reports with report_time <= t_c on D (T-group tenths when present). It gives
  the rule-4 impossible mask used by the w gate's pool.
- **Labels (WU):** every date is on or before 09-29, so every label falls before the venue's 10-23 rule. The label
  is the WU CYYZ daily maximum, native integer °C, from two pinned files:
  - `data/wunderground/cyyz/daily/daily_summary.csv`, sha256
    `1ced925a605b6f4e82fa20cbe238b9c91d841a9390da604bc648b630dac920e1`;
  - `data/inbox/wu-cyyz-0811-0929/daily_summary_cyyz_0811_0929.csv`, sha256
    `c9e16b1d4cf624cde3f4b6b02cde5d483747a7ed67f70750fd1f5cc27594433a`.

  A non-C row, a non-integer value or two different values for a date refuse the run. A label that falls in other
  than exactly one bin drops that snapshot.
- **Dates:** fit table 2026-08-01..09-29, burn-in 08-01..08-14, scored 08-15..09-29. 07-31 has no tape and is not
  in the population. Nothing after 09-29 is read.

## 3. Disclosures (master, 2026-10-30)

- **Prior reads of these dates and prices.** Toronto prices and labels on these dates have already been read
  twice:
  - L11's Toronto r4 dead-bucket read of 08-10..09-29 (X25, EF §10ad);
  - row 77's X64 and X65 (07-16, NBM arms, KILL).

  The 07-12 market-residual estimand of these two candidates has never been read.
- **Citypage is already a served vote.** C2 therefore measures residual information beyond the pooled vote. It
  does not measure the value of the citypage forecast itself.
- **The GEM cycle cannot be identified.** Every captured `eccc_gem` row has `run_time` and `model_run_age_hours`
  null (Open-Meteo supplies no run time). Values are point-in-time as served at capture, but the model cycle
  behind each one cannot be named.
- **Serve parity.** Both candidates are production's captured Open-Meteo GEM and ECCC citypage fields. A survivor
  needs no new recorder. Datamart HRDPS/RDPS stay BLOCKED on the forward recorder
  (`claude/eccc-gem-recorder-20261030` @ `ac447ebe0650e1c51ffceffe0fafde177d3dc322`, not registered or running).
- **Outcome-free S1** (coverage only; no observation, label or price read): `C:/t/l8tor/eccc_s1.py` sha256
  `301146bf19d271f6744403da1788784deaa827288f01d2df4739db93167ca478`, output `C:/t/l8tor/eccc_s1_out.json` sha256
  `7b9a4e908d7b3471974ebb11d2ce733dd553d89a01093a7f8f4809bdc4dd406e`.
  - Over 61 dates and 11,298 snapshots, the GEM day high is present in 99.6% of snapshots and the citypage
    forecast high in 46%.
  - In local 07-12, GEM covers 2,994 of 2,999 snapshots and citypage covers 2,999 of 2,999.

## 4. Hour block

Local 07..12 inclusive, fixed before any read:

- It is the only block where both candidates are fully covered. The citypage high goes structurally null after
  mid-afternoon, when the product switches to tonight's low.
- 07-12 carries most of the remaining sharpness/shape excess (EF §10ag).
- Row 77 already read 07-16 for Toronto with NBM.

Other hours are not tested. The sweep's sub-blocks 06-09 and 10-12 are reported descriptively only.

## 5. Candidates (K = 2)

| id | value | type | sign |
| --- | --- | --- | --- |
| GEM-SEAMLESS | `sources.eccc_gem.data.day_model_highs.gem_seamless` (Open-Meteo GEM seamless, local-day max of hourly 2 m temperature, native °C) | C | + |
| CITYPAGE-FH | `sources.eccc_citypage.data.forecast_high_native` (EC citypage forecast high, native °C) | C | + |

A snapshot is covered by a candidate when all of these hold:

- the source has `ok` true;
- its `fetched_at` is present and <= `captured_at_utc`;
- the value is finite and within [-40, 50] °C.

Otherwise it is uncovered.

## 6. Decision

- BH at q = 0.10 over K = 2.
- A candidate SURVIVES iff it is testable, BH-rejected, and its Delta 95% lower bound is > 0. Otherwise it is a KILL,
  or UNTESTABLE.
- Only for a survivor:
  - the w = 0 identity control;
  - then the 37cb46be w gate (`mr_gate.gate_candidate`, block 07-12), with c_pl,0 as the placebo.

  A survivor that fails the w gate is KILL (w).
- One run. The code writes only under `--out` and refuses to overwrite. Outputs:
  - the receipt JSON, with every input sha;
  - per-date rows with the six sufficient sums;
  - the extracted capture-time feature file.

## 7. Kill and reopen line (written now)

If both candidates are KILL, production's captured Open-Meteo GEM and ECCC citypage are KILLED for Toronto
against the market on the dev window. They reopen only with a new rule on dates disjoint from 2026-08-01..09-29.
Datamart HRDPS/RDPS (a different product) stay BLOCKED on the forward recorder, not killed. Under the per-date
rule 9, recorder dates through about 12-14 become readable from 12-15. A survivor earns only a forward shadow
question; it is not an adoption.
