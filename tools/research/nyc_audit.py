import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "src"))

import json
from datetime import datetime, timezone
from market_registry import CHICAGO
from toronto_model import TorontoHighTempModel

def audit_chicago():
    print(f"--- Auditing {CHICAGO.id} ---")
    model = TorontoHighTempModel(market_id="chicago")
from polymarket_client import PolymarketClient

def audit_new_york():
    print("--- Auditing nyc ---")
    
    model = TorontoHighTempModel(market_id="nyc")
    
    # 1. Look at live sources
    sources = model.fetch_live_sources()
    
    wu_history_data = sources.get("wu_history", {}).get("data", {})
    wu_current_data = sources.get("wu_current", {}).get("data", {})
    om_data = sources.get("open_meteo", {}).get("data", {})
    wf_data = sources.get("weather_forecast", {}).get("data", {})
    
    rows = wu_history_data.get("rows", [])
    
    # Let's print what we know about the current situation
    print("\nLive context:")
    if wu_current_data:
        print(f"  current_temp: {wu_current_data.get('temp_c')}")
        print(f"  current_time: {wu_current_data.get('datetime')}")
        
    if rows:
        max_since_7am = max((r.get("temp_c") for r in rows if r.get("temp_c") is not None and model.minute_of_day(r.get("time")) >= 420), default=None)
        print(f"  current_max (max_since_7am): {max_since_7am}")
        
    if wf_data:
        print(f"  weather_forecast_max: {wf_data.get('forecast_high_c')}")
        
    if om_data:
        om_rows = om_data.get("rows", [])
        om_max = max((r.get("temp_c") for r in om_rows if r.get("temp_c") is not None), default=None)
        print(f"  open_meteo_max: {om_max}")
    
    cutoff = model.effective_intraday_cutoff_hour(datetime.now(timezone.utc), sources.get("wu_history", {}).get("data", {}).get("rows", []))
    print(f"\nEffective cutoff hour: {cutoff}")
    feats = model.extract_live_features(sources, cutoff)
    print("\nFeatures Used:")
    for k, v in feats.items():
        if k not in ["observations"]:
            print(f"  {k}: {v}")

    # 3. Predict the distribution
    hgb_probs, _ = model.predict_feature_distribution(sources, cutoff, datetime.now(timezone.utc))
    
    print("\nModel Output for HGB:")
    print("Kind: hgb")
    for k, v in sorted(hgb_probs.items(), key=lambda x: -x[1])[:5]:
        print(f"  {k}: {v*100:.1f}%")

    print("\nUI Bins:")
    try:
        from market_registry import NYC
        market_client = PolymarketClient(target_date=model.target_date, market_id="nyc")
        event = market_client.get_event()
        bins = model.model_market_rows(event, hgb_probs)
        for b in bins:
            print(f"  {b['Range']}: Model = {b['Model']}")
    except Exception as e:
        print(f"Error fetching bins: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    audit_new_york()
