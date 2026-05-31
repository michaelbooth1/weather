"""Responsiveness audit: is the model lagging live conditions (and the market)
because it anchors to the lagging Wunderground *history*?

Shows, live: how stale WU history is, how far the leading observations (current
max-since-7am, SWOB, METAR) are ahead of it, the model's observed floor vs the
live-observed max, the effective vs wall cutoff, and model-vs-market top bucket.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath("src"))

from polymarket_client import PolymarketClient
from toronto_model import TorontoHighTempModel, TORONTO_TZ


def age_min(now, iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TORONTO_TZ)
    return (now - dt).total_seconds() / 60.0


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
    cur = m.source_data(sources, "wu_current")
    swob = m.source_data(sources, "eccc_swob")
    metar = m.source_data(sources, "metar")
    rows = h.get("rows") or []
    wu_max = h.get("max_c")
    latest = rows[-1] if rows else {}

    swob_latest = swob.get("latest") or {}
    live_max = m.max_value(cur.get("max_since_7am_c"), swob.get("same_day_max_c"), metar.get("temp_c"))

    print(f"=== Responsiveness audit @ {now:%Y-%m-%d %H:%M:%S} local ===\n")
    print("-- settlement source (WU history) — the model's anchor --")
    print(f"  WU history max_c   : {wu_max}  (bucket {m.round_half_up(wu_max)})")
    print(f"  WU latest row time : {latest.get('time')}  (temp {latest.get('temp_c')})")
    wu_age = None
    if latest.get("datetime"):
        wu_age = age_min(now, latest.get("datetime"))
    print(f"  WU history staleness: {wu_age:.0f} min behind now" if wu_age is not None else "  WU staleness: ?")

    print("\n-- leading live observations (currently discounted to soft signals) --")
    print(f"  WC current temp / max-since-7am : {cur.get('temp_c')} / {cur.get('max_since_7am_c')}  "
          f"(valid {cur.get('time')})")
    print(f"  SWOB air / same-day max         : {swob_latest.get('air_temp_c')} / {swob.get('same_day_max_c')}  "
          f"(age {age_min(now, swob_latest.get('local_time')):.0f} min)"
          if swob_latest.get("local_time") else
          f"  SWOB same-day max               : {swob.get('same_day_max_c')}")
    print(f"  METAR temp                      : {metar.get('temp_c')}  ({metar.get('report_time')})")

    print("\n-- THE LAG --")
    print(f"  model observed floor (WU)  : {m.round_half_up(wu_max)} C")
    print(f"  live-observed max          : {live_max} C  (bucket {m.round_half_up(live_max)})")
    if live_max is not None and wu_max is not None:
        print(f"  live LEADS WU history by   : {live_max - wu_max:+.1f} C")
    wall = m.intraday_cutoff_hour(now)
    eff = m.effective_intraday_cutoff_hour(now, rows)
    print(f"  wall cutoff {wall}  vs  effective cutoff {eff}  (model uses {eff}:00 state)")

    print("\n-- model vs market --")
    live_bucket = m.round_half_up(live_max)
    below_live = sum(p for b, p in dist.items() if live_bucket is not None and b < live_bucket)
    print(f"  model mass BELOW live-observed max ({live_bucket} C): {below_live*100:.1f}%  "
          f"<- the lag, as probability the model still leaves below what's already happened")
    print(f"  model top bucket : {max(dist, key=dist.get)}  ({dist[max(dist, key=dist.get)]*100:.1f}%)")
    bins = m.market_bins(event)
    mk = [(b['value'], b['market_yes']) for b in bins if b.get('kind') == 'eq' and b.get('market_yes')]
    if mk:
        mk_top = max(mk, key=lambda x: x[1])
        print(f"  market top bucket: {mk_top[0]}  ({mk_top[1]*100:.1f}%)")


if __name__ == "__main__":
    main()
