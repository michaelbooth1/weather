# L6_G forward screen: frame-builder clarification (2026-10-29)

- **Status:** DRAFT clarification to [l6g_forward_prereg_DRAFT.md](l6g_forward_prereg_DRAFT.md), written 2026-10-29
  by lane L2. It closes the prereg's open item 2 (the emitter's input frame). It changes no rule, no estimand, no
  date and no pin of the prereg, and it changes no B-bound file.
- **Timing.** D0 is 2026-10-31, so the first emission is 2026-11-01, for D0. This builder must be landed and pinned
  before that emission. It adds new files only (roll-free).
- **Written blind.** No outcome, label, price, market, settlement or 88a/panel row was read. From the 10-28 smoke
  bundle, only the manifest structure, the file layout and the column names were read; it is not a B date.

## 1. What it pins

| Field | Value |
| --- | --- |
| Frame builder | `src/weather/calibration/l6g_forward_frame.py` git blob 75a587b02ca5a579fdbbd08c65387fad249d4db9, file sha256 b394560f089a25838b2c0e0fe46c6853988fbc870a7f6bdcfa2e4b07f6129b9f (each frame manifest records it) |
| Tests | `tests/calibration/test_l6g_forward_frame.py`, 44, synthetic data only |
| L6 part (canonical part sha256) | 07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9 (B §1) |
| Season-matched L6 state behind the nowcasts | 800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db (B §1) |
| Input layout | the MG-2 receiver's per-date layout (`mg2_inputs_layout/1`); see §2 step 1 for what the builder checks |

## 2. The chain for one local date D (nothing fetches; no new source)

1. MG-2's verified forward bundle goes through `python -m weather.calibration.mg2_inputs build`. The result is the
   label-free layout: `inputs_snapshots.parquet`, `inputs_bands.parquet` and `manifest.json`. The builder re-hashes
   both files against the manifest's `files` entries and requires:
   - `target_date` = D;
   - the snapshot count equal to the manifest's `snapshots`;
   - every snapshot dated D;
   - `v2_parser_version` = 2 on every row.
2. `python -m weather.calibration.mg2_composite captured-nowcast --prev-root ...` writes `nowcasts.parquet`
   (`n_own`) and `nowcasts_manifest.json`. The builder accepts them only through `mg2_composite.forward_nowcasts`,
   whose rules the builder re-checks locally. They require:
   - `prev_day_source` "bundle prev_day";
   - the file sha equal to the one its manifest records;
   - L6 state 800072c7…;
   - a window that covers D.
3. The L6 part comes from the coefficients file, accepted only at its canonical part sha 07a67425…, computed exactly
   as `mg2_composite.load_part` does.

Repository ratchets forbid any `src` module from importing the MG-2 binding (`mg2_composite`) or naming the input
receiver. The builder therefore imports neither and re-implements these three acceptance checks. A test proves that
its checks accept and refuse exactly as the binding's `forward_nowcasts`, `load_part` and `part_sha` do.

**Disclosed:** the builder does not compare the layout manifest's `schema` string, because naming the receiver's
schema in `src` would trip the receiver ratchet. The checks above stand in for it. If a literal schema check is
wanted, the alternative is an allowlist entry for this module in that ratchet, which is a change to an existing test.
4. `python -m weather.calibration.l6g_forward_frame run` writes the frame with exclusive create, under
   `<frame_root>/<D>/` (`emit_snapshots.parquet`, `emit_bands.parquet`, `frame_manifest.json`). It then hands the
   frame to `l6g_forward_emit.emit_day`, which writes the vectors and the receipt row (prereg §3).
   - Frame columns: `l6_mu`, `v2_stddev`, `v2_mean` = N, `floor`, `covered_l6`, keyed by the layout's `row_key`.
   - `l6_mu` is the bound pre-13 arm's centre, exactly as in `l6_stack.predict`: mu = v2_mean + a_h + b_h
     (N − v2_mean) where N and v2_mean are finite; otherwise mu = v2_mean.
   - `covered_l6` is MG-1's usability mask: mu and the spread are finite, and `v2_available_at` ≤
     `captured_at_utc`.
   - A test shows that the frame plus the emitter reproduce `l6_stack.predict` band for band, to 1e-12.

The vectors are as-of-capture by construction. Every layout row is one captured snapshot with its own captured
inputs, and N comes from the captured METAR rows. `run` is the only emission entry point. The emitter's own CLI is
not used for accrual.

## 3. Outcome-blind refusals (positive, tested)

`refuse_columns` raises on any column whose name could carry a label, an outcome, a final or settled observed high,
or a price or market quote. Its marker list combines:
- the emitter's price and outcome markers;
- the dev scorecard's `LABELISH` set;
- final-high names (`observed_high`, `final_high`, `daily_max`, `settled`, `settlement`, `wu_high` and similar).

It is applied:
- to the layout snapshots, the layout bands and the nowcasts, before any value is used;
- again to the emitter's input frame, inside `run`, before `emit_day`.

The tests inject each of these columns: `winner`, `settlement_high`, `observed_high`, `final_high`, `daily_max`,
`settled_bucket`, `p_market_yes`, `best_bid`, `market_mid`, `label_source`, `y` and `outcome`. They show:
- the builder raises on each one;
- the emission path raises on each one;
- for every name the emitter's own list covers, the emitter raises too.

The point-in-time floor inputs (`high_so_far`, `trusted_current_max`, `guidance_physical_floor`) are inputs, not
outcomes.

**Disclosed:** the pinned emitter's own list does not cover the final-high names (`observed_high`, `final_high`,
`daily_max`). The emitter also drops every column outside its contract before computing. Both refusals therefore
run through the builder's `run` path.
