"""Re-audit the low end: where does the model's P(<=17) come from, and is the
forecast floor firing? Dumps the live distribution, the floor plan, and every
market band's model-vs-market price."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath("src"))

from polymarket_client import PolymarketClient
from toronto_model import TorontoHighTempModel, TORONTO_TZ


def main():
    now = datetime.now(TORONTO_TZ)
    pm = PolymarketClient()
    event = pm.get_toronto_weather_event()
    m = TorontoHighTempModel(target_date=pm.config.target_date)
    hist = m.fetch_historical_sources()
    live = m.fetch_live_sources()
    built = m.build(event, historical_sources=hist, live_sources=live, now=now)
    sources = {**hist, **live}
    dist = built["distribution"]

    h = m.source_data(sources, "wu_history")
    observed = m.round_half_up(h.get("max_c"))
    cutoff = m.effective_intraday_cutoff_hour(now, h.get("rows") or [])
    wf = m.max_row_temp(m.source_data(sources, "weather_forecast").get("rows"))
    om = m.max_row_temp(m.source_data(sources, "open_meteo").get("rows"))
    ec = m.source_data(sources, "eccc_citypage").get("forecast_high_c")

    print(f"=== Low-end re-audit @ {now:%Y-%m-%d %H:%M} local ===")
    print(f"active model kind : {getattr(m, 'active_model_kind', '?')}")
    print(f"cutoff hour       : {cutoff}   now.hour={now.hour}")
    print(f"observed floor    : {observed} C   (WU max_c={h.get('max_c')})")
    print(f"forecasts         : WC={wf} OM={om} ECCC={ec}")
    plan = m.forecast_floor_plan([wf, om, ec], now.hour, observed)
    print(f"forecast_floor_plan: {plan}   (threshold, strength) or None")

    print("\n-- distribution low buckets --")
    for t in range(13, 21):
        print(f"  {t} C: {dist.get(t, 0.0) * 100:5.2f}%")
    cum = 0.0
    print("\n-- cumulative P(<= t) --")
    for t in range(14, 20):
        c = sum(p for b, p in dist.items() if b <= t)
        print(f"  P(<= {t}) = {c * 100:5.2f}%")

    print("\n-- market bands: model vs market --")
    print(f"  {'band':<18} {'kind':>4} {'val':>4} {'model':>8} {'market':>8}")
    for b in m.market_bins(event):
        mp = m.bin_probability(dist, b)
        my = b.get("market_yes")
        print(f"  {str(b.get('label')):<18} {str(b.get('kind')):>4} {str(b.get('value')):>4} "
              f"{mp * 100:7.2f}% {('-' if my is None else f'{my*100:6.2f}%'):>8}")


if __name__ == "__main__":
    main()
