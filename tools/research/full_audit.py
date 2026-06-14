"""
Full model audit: run all markets, compare model output to market prices.
Correctly uses local timezone for each market.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from datetime import datetime, timezone
from toronto_model import TorontoHighTempModel
from market_registry import REGISTRY

def audit_market(market_id):
    print(f"\n{'='*60}")
    print(f"  MARKET: {market_id.upper()}")
    print(f"{'='*60}")
    
    try:
        model = TorontoHighTempModel(market_id=market_id)
        spec = model.spec
        print(f"  Unit: {spec.unit}, ICAO: {spec.icao}, TZ: {spec.timezone}")
    except Exception as e:
        print(f"  ERROR creating model: {e}")
        return
    
    # Fetch live sources
    try:
        sources = model.fetch_live_sources()
    except Exception as e:
        print(f"  ERROR fetching sources: {e}")
        return
    
    # Use local time for the market's timezone
    now_local = datetime.now(spec.tz)
    print(f"  Local time: {now_local.strftime('%Y-%m-%d %H:%M %Z')}")
    
    # Get basic context
    try:
        history = model.source_data(sources, "wu_history")
        wu_current = model.source_data(sources, "wu_current")
        open_meteo = model.source_data(sources, "open_meteo")
        
        current_temp = wu_current.get("temp_c") if wu_current else None
        high_so_far = history.get("max_c") if history else None
        om_max = None
        if open_meteo:
            om_rows = open_meteo.get("rows")
            if om_rows:
                om_temps = [r.get("temp_c") for r in om_rows if r.get("temp_c") is not None]
                om_max = max(om_temps) if om_temps else None
        
        print(f"\n  Live Data:")
        print(f"    Current temp: {current_temp}")
        print(f"    High so far (WU): {high_so_far}")
        print(f"    Open-Meteo max: {om_max}")
    except Exception as e:
        print(f"  ERROR reading sources: {e}")
    
    # Get effective cutoff (using local time)
    try:
        rows = history.get("rows", []) if history else []
        cutoff_hour = model.effective_intraday_cutoff_hour(now_local, rows)
        print(f"    Effective cutoff hour: {cutoff_hour}")
    except Exception as e:
        print(f"    Cutoff hour error: {e}")
        cutoff_hour = 17
    
    # Run the raw feature model
    try:
        feat_dist, feat_kind = model.predict_feature_distribution(sources, cutoff_hour, now_local)
        if feat_dist:
            print(f"\n  Raw Feature Model ({feat_kind}):")
            sorted_feat = sorted(feat_dist.items(), key=lambda x: x[1], reverse=True)[:8]
            for bucket, prob in sorted_feat:
                print(f"    {bucket}: {prob*100:.1f}%")
        else:
            print(f"\n  Raw Feature Model: EMPTY (kind={feat_kind})")
    except Exception as e:
        print(f"  Feature model error: {e}")
        import traceback
        traceback.print_exc()
    
    # Run the full distribution estimate
    try:
        result = model.estimate_distribution(sources, now_local)
        # estimate_distribution returns the scores dict directly (not wrapped)
        if isinstance(result, dict) and result:
            final_dist = result
            print(f"\n  Final Distribution:")
            sorted_buckets = sorted(final_dist.items(), key=lambda x: x[1], reverse=True)[:10]
            for bucket, prob in sorted_buckets:
                print(f"    {bucket}: {prob*100:.1f}%")
            
            # UI bin groupings
            print(f"\n  UI Bin Summary:")
            if spec.unit == "F":
                bins = [
                    ("79 F or below", lambda k: k <= 79),
                    ("80-81 F", lambda k: 80 <= k <= 81),
                    ("82-83 F", lambda k: 82 <= k <= 83),
                    ("84-85 F", lambda k: 84 <= k <= 85),
                    ("86-87 F", lambda k: 86 <= k <= 87),
                    ("88-89 F", lambda k: 88 <= k <= 89),
                    ("90-91 F", lambda k: 90 <= k <= 91),
                    ("92-93 F", lambda k: 92 <= k <= 93),
                    ("94+ F", lambda k: k >= 94),
                ]
            else:
                bins = [
                    ("22 C or below", lambda k: k <= 22),
                    ("23 C", lambda k: k == 23),
                    ("24 C", lambda k: k == 24),
                    ("25 C", lambda k: k == 25),
                    ("26 C", lambda k: k == 26),
                    ("27 C", lambda k: k == 27),
                    ("28+ C", lambda k: k >= 28),
                ]
            
            for label, pred in bins:
                total = sum(v for k, v in final_dist.items() if pred(k))
                if total > 0.005:
                    print(f"    {label}: {total*100:.1f}%")
        else:
            print(f"\n  Final Distribution: EMPTY or unexpected format")
            print(f"    type={type(result)}, value={result}")
    except Exception as e:
        print(f"  ERROR in estimate_distribution: {e}")
        import traceback
        traceback.print_exc()


def main():
    print("=" * 60)
    print("  FULL MODEL AUDIT - June 7, 2026 Evening")
    print(f"  Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    
    # Focus on markets with active Polymarket trading
    active_markets = ["toronto", "nyc", "chicago"]
    print(f"Auditing active markets: {active_markets}")
    
    for market_id in active_markets:
        audit_market(market_id)
    
    print(f"\n\n{'='*60}")
    print("  AUDIT COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
