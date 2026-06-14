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
    sources = model.fetch_live_sources()
    
    # Inject wu_current into rows to simulate fix
    wu_history_rows = sources.get("wu_history", {}).get("data", {}).get("rows", [])
    curr = sources.get("wu_current", {}).get("data", {})
    if curr and curr.get("time"):
        mock_row = {
            "time": curr.get("time"),
            "temp_c": curr.get("temp_c"),
            "dewpoint_c": curr.get("dewpoint_c"),
            "humidity": curr.get("humidity"),
            "pressure": curr.get("pressure")
        }
        wu_history_rows.append(mock_row)
        
    cutoff = model.effective_intraday_cutoff_hour(datetime.now(timezone.utc), wu_history_rows)
    print(f"\nEffective cutoff hour: {cutoff}")
    curr = sources.get("wu_current", {}).get("data", {})
    print(f"  current_temp: {curr.get('temp_c')}")
    print(f"  current_time: {curr.get('time')}")
    print(f"  current_max (max_since_7am): {curr.get('max_since_7am_c')}")
    weather_rows = sources.get("weather_forecast", {}).get("data", {}).get("rows", [])
    wf_max = max((r.get("temp_c") for r in weather_rows if r.get("temp_c") is not None), default=None)
    print(f"  weather_forecast_max: {wf_max}")
    om_rows = sources.get("open_meteo", {}).get("data", {}).get("rows", [])
    om_max = max((r.get("temp_c") for r in om_rows if r.get("temp_c") is not None), default=None)
    print(f"  open_meteo_max: {om_max}")
    
    sources = model.fetch_live_sources()
    
    cutoff = model.effective_intraday_cutoff_hour(datetime.now(timezone.utc), sources.get("wu_history", {}).get("data", {}).get("rows", []))
    print(f"\nEffective cutoff hour: {cutoff}")
    feats = model.extract_live_features(sources, cutoff)
    print("\nFeatures Used:")
    for k, v in feats.items():
        if k not in ["feature_rows", "observations", "feature_latest"]:
            print(f"  {k}: {v}")
            
    print("\nModel Output for HGB:")
    hgb_probs, kind = model.predict_feature_distribution(sources, cutoff, datetime.now(timezone.utc))
    print(f"Kind: {kind}")
    if hgb_probs:
        sorted_probs = sorted(hgb_probs.items(), key=lambda x: x[1], reverse=True)[:5]
        for t, p in sorted_probs:
            print(f"  {t}: {p*100:.1f}%")
            
    print("\nUI Bins:")
    try:
        from polymarket_client import PolymarketClient
        market_client = PolymarketClient(target_date=CHICAGO.target_date, market_id="chicago")
        event = market_client.get_event()
        bins = model.market_bins(event)
        for b in bins:
            prob = model.bin_probability(dist, b)
            market = b.get('market_yes', 0.0)
            print(f"  {b['label']}: Model = {prob*100:.1f}%, Market = {market*100:.1f}%")
    except Exception as e:
        print(f"Error fetching bins: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    audit_chicago()
