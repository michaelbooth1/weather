"""Deep-dive: why does the model assign the probability it does to one band?

Usage: python scratch/audit_band.py [BUCKET]   (default 15)

Builds the live model and traces a single bucket's probability through every
stage of estimate_distribution: the settlement floor, the feature model, the
climatology prior, the forecast cap, and the final blended distribution, next
to the market's price for that band.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath("src"))

from polymarket_client import PolymarketClient
from toronto_model import TorontoHighTempModel, TORONTO_TZ

TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 15


def top(d, n=6):
    return [(b, round(p, 4)) for b, p in sorted(d.items(), key=lambda x: -x[1])[:n]]


def main():
    now = datetime.now(TORONTO_TZ)
    print(f"=== Band audit for {TARGET} C @ {now:%Y-%m-%d %H:%M} local ===\n")

    pm = PolymarketClient()
    event = pm.get_toronto_weather_event()
    model = TorontoHighTempModel(target_date=pm.config.target_date)
    hist = model.fetch_historical_sources()
    live = model.fetch_live_sources()
    sources = {**hist, **live}

    built = model.build(event, historical_sources=hist, live_sources=live, now=now)
    dist = built["distribution"]

    h = model.source_data(sources, "wu_history")
    cur = model.source_data(sources, "wu_current")
    swob = model.source_data(sources, "eccc_swob")
    city = model.source_data(sources, "eccc_citypage")
    wf = model.source_data(sources, "weather_forecast")
    om = model.source_data(sources, "open_meteo")
    metar = model.source_data(sources, "metar")
    local = model.source_data(sources, "local_history")

    rows = h.get("rows") or []
    cutoff = model.effective_intraday_cutoff_hour(now, rows)
    wall_cutoff = model.intraday_cutoff_hour(now)
    observed_bucket = model.round_half_up(h.get("max_c"))

    print("-- Source signals --")
    print(f"  wall cutoff hour      : {wall_cutoff}")
    print(f"  effective cutoff hour : {cutoff}  (capped to latest printed WU row)")
    print(f"  WU history rows        : {len(rows)}; max_c={h.get('max_c')} at {h.get('max_times')}")
    if rows:
        last = rows[-1]
        print(f"  WU latest row          : {last.get('time')}  temp={last.get('temp_c')}")
        print(f"  WU temps (last 6)      : {[r.get('temp_c') for r in rows[-6:]]}")
    print(f"  observed floor bucket  : {observed_bucket}  (round of WU printed high)")
    print(f"  WU current / max-7am   : {cur.get('temp_c')} / {cur.get('max_since_7am_c')}")
    print(f"  SWOB same-day max      : {swob.get('same_day_max_c')}")
    print(f"  METAR temp             : {metar.get('temp_c')}")
    print(f"  Weather.com fc max     : {model.max_row_temp(wf.get('rows'))}")
    print(f"  Open-Meteo fc max      : {model.max_row_temp(om.get('rows'))}")
    print(f"  ECCC forecast high     : {city.get('forecast_high_c')}")

    plausible_cap = model.round_half_up(model.max_value(
        observed_bucket, model.max_row_temp(wf.get("rows")),
        model.max_row_temp(om.get("rows")), city.get("forecast_high_c")))
    print(f"  plausible cap bucket   : {plausible_cap}")

    print("\n-- Feature model (HGB/LR) --")
    fp, kind = model.predict_feature_distribution(sources, cutoff, now)
    if fp:
        bw = model.feature_blend_weight(cutoff) if hasattr(model, "feature_blend_weight") else None
        print(f"  active kind={kind}  blend_weight={bw}")
        print(f"  feature top buckets : {top(fp)}")
        print(f"  feature P({TARGET})        : {round(fp.get(TARGET, 0.0), 4)}")
    else:
        print(f"  no feature model active (kind={kind})")

    print("\n-- Climatology prior (local WU history) --")
    analysis = local.get("analysis") or {}
    probs = analysis.get("bucket_probabilities") or {}
    print(f"  available={local.get('available')}  target_window_count={analysis.get('target_window_count')}")
    if probs:
        cp = {int(b): float(p) for b, p in probs.items()}
        print(f"  climatology top     : {top(cp)}")
        print(f"  climatology P({TARGET})    : {round(cp.get(TARGET, 0.0), 4)}")

    print("\n-- FINAL distribution --")
    print(f"  top buckets         : {top(dist)}")
    print(f"  FINAL P({TARGET})          : {round(dist.get(TARGET, 0.0), 4)}")
    below = sum(p for b, p in dist.items() if observed_bucket is not None and b < observed_bucket)
    print(f"  mass below floor    : {round(below, 4)}")

    print("\n-- Market --")
    for b in model.market_bins(event):
        if b.get("value") == TARGET and b.get("kind") == "eq":
            print(f"  band '{b['label']}'  market_yes={b.get('market_yes')}  "
                  f"model={round(model.bin_probability(dist, b), 4)}")


if __name__ == "__main__":
    main()
