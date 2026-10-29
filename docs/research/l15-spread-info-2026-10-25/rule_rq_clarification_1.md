# R-Q Clarification 1 (2026-10-29): the capture side of precondition P_B uses history's node definition

Written by lane L13 on 2026-10-29 on master's ruling (2), relayed by the coordinator.

**Timing.** This was written **after** P_B's first result:
- `C:\t\l15\rq\rq_parity_b.json`, sha256 `fdf288241f2d77c3f8f7d6ff87888d7ff7c618db290455f8ab09b60f7b025de9`.
- p10 mean diff -1.41 °F (median |diff| 1.27); p90 -1.21 (1.16); r ≥ 0.986. **FAIL.**
- Gate B1 was not run, and no B1 output exists.

**Rule identity.** The rule `rule_rq.md` (sha256 `5703f06542b6f369bd32eaa2b84214bf4064b98490be3791b223c439d5e010c4`)
is unchanged. This file adds one clarification to it.

## What changes

This applies **the same node-definition fix** as R-O's Clarification 1 (`rule_rn.md`, commit `7a4354d05`) to P_B,
and nothing else.

**Why.** P_B compared two different definitions.
- **History side:** each member's max over the 3-hourly nodes of one fixed cycle.
- **Capture side:** the captured `day_member_high_p10/p90`, a max over all hourly values of the local day.

That difference alone makes the capture warmer. Train/serve parity needs one definition. The history (trained)
definition is the node max, so the capture side is recomputed to it.

**Capture side.** These values replace the captured `day_member_high_p10/p90` as P_B's comparison values.

- **Source.** The capture host's raw Open-Meteo ensemble payload blobs, as extracted for R-O Clarification 1:
  - `C:\t\ro_capture\ro_capture_members.csv`, sha256
    `8da6d14389888c2dc4cd12d2ced3d6219996cb0ca0116ca9eb7c416bbde27707`;
  - manifest `C:\t\ro_capture\ro_capture_manifest.json`, sha256
    `87411d0549f78e47982c4ecf61a50e317ec999663536a676c3cd16e557df7763`, status `ok`.
- **Same extraction, unchanged.**
  - Ensemble blobs are the ones carrying `temperature_2m_member01..30`.
  - Each label's instant is label - `utc_offset_seconds`.
- **Node maximum.** Per member, the max over exactly history's nodes, with every node required.
  - Variant B's nodes are the 18Z cycle of D-1 at fh 18, 21, …, 36: valid instants 12Z D .. 06Z D+1, kept only
    when the valid local date is D.
  - These are the same valid instants as R-O's 06Z-D nodes (fh 6..24). The extracted `node_max` is therefore
    already at variant B's node definition, and no new extraction is made.
- **Statistics.** p10 and p90 are `model_sources.percentile` over the members' node maxima, with at least 25 of 30
  members. P_B has no control statistic, so none is added.
- **Linking a blob to a snapshot.** As in R-O Clarification 1:
  - A blob of the same event is linked to a snapshot when the blob reproduces the snapshot's captured
    `day_member_high_p10`, `day_member_high_p90` and `day_max_native`, within 1e-6. This is the full-local-day
    fingerprint of `model_sources.fetch_global_ensemble`.
  - Snapshots with no linked blob, with linked blobs that disagree on the node statistics, or with a non-°F blob are
    excluded and counted.

**Unchanged.**
- The history side: corpus `C:\t\l11pb\gefs\corpus_18z_ap5`, the member highs and the availability test at the
  snapshot's `captured_at_utc`.
- The population: dev snapshots at local hours 00..06, 2026-07-30..09-29, the 11 R0 markets.
- The PASS limits for each of p10 and p90: |mean diff| <= 1.0 °F, median |diff| <= 1.0 °F, Pearson r of cell
  means >= 0.95.

## Residual difference (disclosed, not a parameter)

- **Run identity.** The capture's Open-Meteo run cannot be pinned to history's 18Z D-1 cycle. The payload carries no
  run id. At 00-06 local the served run may be the 12Z, 18Z or 00Z cycle.
- **Grid.** History is the 0.5° `pgrb2ap5` grid; Open-Meteo's ensemble has its own grid and interpolation.

## Consequence

P_B is re-run once against these capture values.
- **Fail:** variant B stays BLOCKED and the gap is recorded. There is no further clarification.
- **Pass:** gate B1 runs exactly as registered.
