from datetime import datetime, timezone
from toronto_model import TorontoHighTempModel
from model_constants import INTRADAY_CUTOFF_HOURS

def test_interpolation():
    model = TorontoHighTempModel(market_id='nyc')
    sources = model.fetch_live_sources()
    now = datetime.now(timezone.utc)
    
    # Evaluate at 13
    dist_13, _ = model.predict_feature_distribution(sources, 13, now)
    
    # Evaluate at 15
    dist_15, _ = model.predict_feature_distribution(sources, 15, now)
    
    print("13:00 model output:")
    if dist_13:
        for b in sorted(dist_13, key=dist_13.get, reverse=True)[:5]:
            print(f"  {b}: {dist_13[b]*100:.1f}%")
            
    print("\n15:00 model output:")
    if dist_15:
        for b in sorted(dist_15, key=dist_15.get, reverse=True)[:5]:
            print(f"  {b}: {dist_15[b]*100:.1f}%")

if __name__ == '__main__':
    test_interpolation()
