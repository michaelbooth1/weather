import sys
import json
from pathlib import Path

SRC_ROOT = Path("src").resolve()
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from polymarket_client import PolymarketClient
from toronto_model import TorontoHighTempModel

def main():
    client = PolymarketClient(market_id="toronto")
    event = client.get_event()

    model = TorontoHighTempModel(market_id="toronto")
    live = model.fetch_live_sources()
    hist = model.fetch_historical_sources()

    res = model.build(event, historical_sources=hist, live_sources=live)

    print("=== MODEL OUTPUT ===")
    print("Top Temp:", res.get("top_temp"))
    print("Distribution:")
    for temp, prob in res.get("distribution", {}).items():
        if prob > 0.01:
            print(f"  {temp}°C: {prob:.1%}")

    print("\n=== FEATURE VECTOR ===")
    features = res.get("feature_vector", {})
    for k, v in features.items():
        print(f"  {k}: {v}")

    print("\n=== SOURCES (Summary) ===")
    sources = res.get("sources", {})
    print(f"  WU History Max: {sources.get('wu_history', {}).get('max_c')}")
    print(f"  WU Current Temp: {sources.get('wu_current', {}).get('temp_c')}")
    print(f"  WU Max Since 7am: {sources.get('wu_current', {}).get('max_since_7am_c')}")
    print(f"  ECCC SWOB Same Day Max: {sources.get('eccc_swob', {}).get('same_day_max_c')}")
    
    wf = sources.get("weather_forecast", {}).get("rows", [])
    wf_max = max((r.get("temp_c") for r in wf if r.get("temp_c") is not None), default=None)
    print(f"  Weather Forecast Max: {wf_max}")

    om = sources.get("open_meteo", {}).get("rows", [])
    om_max = max((r.get("temp_c") for r in om if r.get("temp_c") is not None), default=None)
    print(f"  Open Meteo Max: {om_max}")
    
    print(f"  ECCC Forecast High: {sources.get('eccc_citypage', {}).get('forecast_high_c')}")

if __name__ == "__main__":
    main()
