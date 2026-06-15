# 5. METAR Historical Layer [PARTIAL - SERVING RETUNE LEFT]

- [x] Collect historical METAR rows for CYYZ.
- [x] Compare full-day hourly METAR max versus final WU bucket.
- [x] Quantify how often METAR misses the settlement bucket by intraday cutoff hour.
- [ ] Use this to calibrate the live METAR sanity-check role instead of a small hard-coded signal.

Implementation status (2026-06-13): the cutoff-hour quantification is shipped.
`src.metar_history cutoff-miss [--all-markets]` classifies, for each registered
market and each intraday cutoff hour (9-19), the METAR max-so-far bucket versus
the WU FINAL settlement bucket as miss (below) / match / exceed, and reports the
rates, the mean still-to-go gap, and the first hour whose match+exceed rate
reaches 0.5 (when METAR-so-far becomes a usable floor on a typical day). It
writes `data/backtest/metar_cutoff_miss_report.md` (+ `.json`) fleet-wide or a
per-market `analysis/cutoff_miss_report.md`. `tests/test_metar_cutoff_miss.py`
(4 tests) covers the hourly reader and the miss/match/exceed/gap classification
on synthetic data. After the seasonal METAR deep-fill (below; ~1312 matched
days/market) the rates are statistically meaningful and converged: Toronto
METAR-so-far reaches the WU final bucket on >=50% of days by 15:00 (miss-rate
0.94 at 09:00 -> 0.36 at 15:00 -> 0.02 by 18:00, with near-zero overshoot -- a
clean leading, non-overshooting signal); Miami reaches it earlier (14:00) and
runs slightly ABOVE WU late-day (mean gap to final goes negative after 16:00,
i.e. KMIA ASOS reads a touch warmer than the WU settlement source late). The
rates are stable across the 2010-2026 and 1995-2026 windows. REMAINING: the
serving-role retune (replace the small hard-coded live METAR signal with this
learned miss/lead behavior) is a `model_distribution.py` change that overlaps
item 23's settlement-lag model and was deferred here to avoid colliding with
in-flight item-40 serving work.

Seasonal METAR deep-fill (2026-06-13): backfilled the May 20-June 30 high-temp
window for all 12 markets, **1995-2026**, from IEM ASOS (one year-window per
request, resumable, with 429 backoff after the first pass hit rate limits).
Every market went from ~8 normalized days to **~1359** (1230 for Austin, whose
early years are source-unavailable; errors=0). This is the item-29/30
"deep-fill METAR/ASOS" data action and is what gives the cutoff-miss analysis
its statistical power.

Codex audit (2026-05-28): partial. `src/metar_history.py` collects IEM ASOS
METAR data, normalizes local rows, and generates a full-day WU comparison report
over 656 matched days. Issues found: intraday miss rates by cutoff hour are not
computed, and the live model only uses METAR as a small hard-coded sanity-check
signal rather than a calibrated role learned from this layer.

Codex update (2026-05-31): still partial. This item should stay open because
METAR can be valuable as an independent airport observation stream, but only if
its miss/lead behavior is learned by cutoff hour and market bucket.

Codex update (2026-06-12): `src.metar_history` is now registry-driven instead
of CYYZ-only. It backfills any registered market station from IEM ASOS,
normalizes to the shared native-unit hourly/daily schema, writes manifests, and
feeds item 30's source-redundancy truth table. This still does not close item 5:
the remaining work is the cutoff-hour miss/lead calibration and serving-role
retirement/retuning.

Codex audit (2026-05-28): partial. `src/metar_history.py` collects IEM ASOS
METAR data, normalizes local rows, and generates a full-day WU comparison report
over 656 matched days. Issues found: intraday miss rates by cutoff hour are not
computed, and the live model only uses METAR as a small hard-coded sanity-check
signal rather than a calibrated role learned from this layer.

Codex update (2026-05-31): still partial. This item should stay open because
METAR can be valuable as an independent airport observation stream, but only if
its miss/lead behavior is learned by cutoff hour and market bucket.

Codex update (2026-06-12): `src.metar_history` is now registry-driven instead
of CYYZ-only. It backfills any registered market station from IEM ASOS,
normalizes to the shared native-unit hourly/daily schema, writes manifests, and
feeds item 30's source-redundancy truth table. This still does not close item 5:
the remaining work is the cutoff-hour miss/lead calibration and serving-role
retirement/retuning.
