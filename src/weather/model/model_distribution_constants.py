"""Distribution-model constants shared across probability mixins."""

# --- Forecast floor ---------------------------------------------------------
# The cap bounds the distribution from above (the high won't exceed the
# forecast); the forecast floor is its mirror — when independent forecasts
# agree, the high will very likely *reach* near them, so mass far below the
# forecast is suppressed. Kept soft (residual mass always remains) and decayed
# to zero by late afternoon, when a low high-so-far falsifies the forecast.
FORECAST_FLOOR_MARGIN = 2            # "almost certainly reaches forecast minus this"
                                     # (2 for same-day forecasts, which rarely miss low by >2)
FORECAST_AGREEMENT_SPREAD = 5.0      # forecasts must agree within this many degrees
                                     # (v0.5.1 widened from 3.0; the 2026-06-09 replay
                                     # regate measured 3.0 worse by ~0.0003 once the
                                     # falsification bench guards the stale-source case)
FORECAST_FLOOR_MIN_SOURCES = 2       # and come from at least this many sources
FORECAST_FLOOR_BASE = 0.5            # per-degree decay below the threshold (softer than the cap)

# --- Forecast falsification bench -------------------------------------------
# A forecast the observed day has already falsified must not keep propping up
# the FLOOR (2026-06-09: Open-Meteo said 27.6 C all afternoon while the WU
# high of 24 printed at 12:35 and never rose). A source loses its floor vote
# when it is past the peak window, the printed high has stood unimproved for
# the falsification window, and the source still claims a degree or more above
# it. The PULL deliberately keeps every source, but now only blends toward the
# consensus forecast bucket and above; replays measured that benching sources
# entirely backfires (it was softening the over-sharp feature model on the bust
# day). Serving-side only: the trained forecast FEATURE (resolve_forecast_high)
# is not benched, so no train/serve skew is introduced.
FALSIFICATION_EARLIEST_HOUR = 13   # mornings plateau before the ramp; never bench early
FALSIFICATION_STAND_MINUTES = 90   # the high must have stood unimproved this long
FALSIFICATION_MARGIN = 1.0         # C above the standing high a claim must exceed

# --- Forecast pull (upper-tail mirror of the forecast floor) ----------------
# The floor lifts the BOTTOM; the pull lifts the TOP. The HGB feature model
# saturates ~1 C below agreeing hot morning forecasts (it under-calls the high),
# yet the forecast-vs-realized tracker
# (`weather.collection.forecast_tracker`) measured the
# morning consensus actually being reached ~70% of the time while the model gave
# it only ~45%. So early in the day, blend the distribution toward a SMOOTH
# forecast density: a Gaussian of width ~RMSE around each source's CONTINUOUS
# forecast value, averaged over sources, then kept on the consensus bucket and
# above so it cannot inject fresh low-tail mass. Spreading the forecast over its
# real uncertainty -- instead of rounding it to one bucket and forcing 85% of
# the mass above it -- keeps the result stable across the x.5 rounding boundary
# (a 0.5C Open-Meteo wiggle no longer swings a bucket 40+ points) and caps how
# much any single source concentrates one bucket. Time-decayed (the observed
# high takes over by mid-afternoon); the downstream observed floors own the low
# side.
FORECAST_SOFT_SIGMA = 1.5           # C; the forecast's real 1-sigma width (~Open-Meteo
                                    # RMSE 1.68). The mixture widens further on disagreement.
FORECAST_PULL_BLEND_MAX = 0.75      # cap on the morning blend toward the forecast density
FORECAST_PULL_START_HOUR = 12       # full strength through noon (the high usually is
                                    # not reached until mid-afternoon)
FORECAST_PULL_END_HOUR = 16         # faded to zero by this hour
# NOTE (2026-06-12): fading this to 14 was tried to fix the measured 13-14h
# winner under-call and FAILED a frozen 15-day Toronto A/B (14h Brier +0.0046,
# aggregate +0.0003). The pull was softening an over-sharp-but-wrong core
# distribution at 13-14h; removing it made the model
# more confident in its lagged call. The 13-14h under-call lives in the
# HGB/observed-floor path (printed-cutoff lag), not here -- it needs an
# item-40-style intra-hour ramp feature + retrain, not a distribution knob.

# --- Fallback forecast-source cluster ---------------------------------------
# The unweighted empirical fallback path uses live forecast highs as one
# correlated forecast-family vote, not one independent bump per NWP-adjacent
# source. A median center preserves the consensus shape while avoiding a
# single-source maximum. The step reaches the cap once a second forecast-family
# source is present; additional sources improve agreement confidence only
# through the spread penalty, not through unbounded weight stacking.
FORECAST_CLUSTER_SOURCE_WEIGHT_STEP = 1.40
FORECAST_CLUSTER_MAX_WEIGHT = 2.40

# --- Ramp-window warm-tail repair ------------------------------------------
# The 2026-06-20 settled audit found the ramp window buying a broad warm tail
# when one hot forecast/current-max-like source sat above the rest of the
# guidance and the printed high had not caught up. Keep the feature model's
# learned shape, but add a serving-side safety valve that damps buckets beyond
# the robust forecast/current-observed anchor when warm outlier or high
# disagreement evidence is present.
RAMP_WARM_TAIL_START_HOUR = 8
RAMP_WARM_TAIL_END_HOUR = 14
RAMP_WARM_TAIL_DISAGREEMENT = 4.0
RAMP_WARM_TAIL_SOURCE_CAP_MARGIN = 1.0
RAMP_WARM_TAIL_ANCHOR_MARGIN = 1.0
RAMP_WARM_TAIL_DECAY = 0.45

# --- Bucket transition prior ------------------------------------------------
# The dashboard's X/X+1/X+2/>=X+3 transition table is now also a small numeric
# prior: conditional on the printed WU high bucket at the effective cutoff, how
# often did the final settlement stay there or climb. Kept low-weight because
# the HGB feature model and late-day continuation model already consume richer
# features; this mainly protects exact-bucket boundary shapes.
BUCKET_TRANSITION_MIN_SAMPLE = 20
BUCKET_TRANSITION_BLEND_MAX = 0.12

# --- Live-observed floors ---------------------------------------------------
# Wunderground *history* (the settlement source) prints with a lag and can stall
# for hours. When a WU print exists, non-resolution observations (SWOB, METAR,
# ASOS) that lead it remain hedged by the learned WU catch-up rate; v0.4.8 made
# that disagreement path hard and was wrong. The separate empty-WU contract
# may hard-floor the effective observed high already admitted by feature
# extraction from captured, cutoff-aligned station/current evidence.
LIVE_FLOOR_HEDGE = 0.40   # retained fraction one bucket below, when no learned rate
LIVE_FLOOR_BASE = 0.12    # per-degree decay for buckets further below
LIVE_FLOOR_HEDGE_MIN = 0.30   # hedge clamp: never harder than this...
LIVE_FLOOR_HEDGE_MAX = 0.80   # ...and never weaker than this when a rate exists
METAR_LIVE_SIGNAL_REACHED_BASELINE = 0.50
METAR_LIVE_SIGNAL_MAX_WEIGHT = 0.60
METAR_LIVE_SIGNAL_SIGMA = 0.90
WU_FLOOR_LIVE_SUPPORT_MIN_RESIDUAL = 0.001

# --- Current-max boundary over-lock guard ----------------------------------
# WU same-day max support evidence outside validated markets:
# it can imply the final high may have reached at least that bucket, but when
# WU history is still one bucket lower and official observations do not confirm
# the higher bucket, it must not become exact-band lock-in by itself.
CURRENT_MAX_BOUNDARY_CONFLICT_EXACT_CAP = 0.55

# --- Late-day lock-in (upper-tail mirror of the floors) ---------------------
# The biggest model-vs-market gap is end-of-day under-confidence: once the day
# is past its peak and the temperature is falling, the high is essentially
# locked at the observed maximum, but the forecast cap stays wide and SWOB
# overshoot keeps mass on a higher bucket the high will never reach. As the day
# closes (time) AND the temperature drops below the day's high (past peak),
# concentrate mass onto the observed high by suppressing buckets above it. Soft
# one bucket up (WU history can still revise up a degree), strong further up.
LATE_LOCKIN_START_HOUR = 15    # no lock-in before this (peak is usually 15-16h)
LATE_LOCKIN_FULL_HOUR = 17     # full strength by this hour (the high is locked by ~17-18h)
LATE_LOCKIN_PEAK_DROP = 2.0    # degrees the temp must fall below the high for full past-peak
LATE_LOCKIN_HEDGE = 0.05       # retained fraction one bucket above the high at full strength
LATE_LOCKIN_BASE = 0.15        # per-degree decay for buckets further above
LATE_DAY_CONTINUATION_BLEND_15H = 0.35
LATE_DAY_CONTINUATION_BLEND_17H = 0.45
# The heuristic above needs the temperature to FALL off the peak; an evening
# plateau (current == high) left strength at 0 all night on 2026-06-09 while
# the market sat at 92% -- "it could still rise" priced at 20%+ against a
# learned ~2-5% revision-up rate. The learned floor below uses the lag
# artifact's measured P(WU final > printed high | hour) curve (91.9% at 10:00
# -> 16.3% at 16:00 -> 0.3% at 20:00) as 1 - rate, gated to late hours and a
# high that has already stood, where conditioning on the day's shape no longer
# dominates the unconditional rate.
LEARNED_LOCKIN_START_HOUR = 17   # the unconditional rate is trustworthy from here
LEARNED_LOCKIN_STAND_MINUTES = 90  # a just-reached high keeps the heuristic only
HIGH_HAS_STOOD_START_HOUR = 13
HIGH_HAS_STOOD_END_HOUR = 15
HIGH_HAS_STOOD_MIN_MINUTES = 60
HIGH_HAS_STOOD_MIN_FORECAST_SOURCES = 2
HIGH_HAS_STOOD_FORECAST_MARGIN = 0.25  # Celsius delta; converted per market.
HIGH_HAS_STOOD_ROLLOVER_MARGIN = 0.25  # Celsius delta below the printed high.
EXPANDED_LOCKIN_START_HOUR = 15
EXPANDED_LOCKIN_END_HOUR = 19
EXPANDED_LOCKIN_STAND_MINUTES = 60
EXPANDED_LOCKIN_FORECAST_MARGIN = 0.50
EXPANDED_LOCKIN_ROLLOVER_MARGIN = 0.25
EXPANDED_LOCKIN_MAX_STRENGTH = 0.85
# A softer bridge for Austin-style afternoons where the official current has
# rolled below a high that has stood, but one or two forecast-family sources
# still leave a modest one/two-bucket rebound plausible.
STANDING_HIGH_PARTIAL_START_HOUR = 13
STANDING_HIGH_PARTIAL_END_HOUR = 19
STANDING_HIGH_PARTIAL_MIN_MINUTES = 60
STANDING_HIGH_PARTIAL_ROLLOVER_MARGIN = 0.25
STANDING_HIGH_PARTIAL_FORECAST_UPSIDE_MAX = 1.25
STANDING_HIGH_PARTIAL_FORECAST_AGREEMENT_SPREAD = 3.0
STANDING_HIGH_PARTIAL_MAX_STRENGTH = 0.55
STANDING_HIGH_PARTIAL_ONE_UP_RETAINED = 0.55
STANDING_HIGH_PARTIAL_TWO_UP_RETAINED = 0.30
STANDING_HIGH_PARTIAL_BASE = 0.18
COMPONENT_SCHEMA_VERSION = "toronto_distribution_components_v0.1"
VALIDATED_WU_MAX_HARD_FLOOR_MARKETS = frozenset({"miami"})
