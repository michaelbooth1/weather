import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.abspath("src"))
from toronto_model import TorontoHighTempModel

def main():
    print("Initializing model...")
    model = TorontoHighTempModel()
    
    print("\nFetching sources...")
    sources = model.fetch_sources()
    print("Fetched sources:", list(sources.keys()))
    
    mock_event = {
        "title": "Highest temperature in Toronto on May 27?",
        "updatedAt": "2026-05-27T15:00:00Z",
        "active": True,
        "markets": [
            {
                "groupItemTitle": "24 C or below",
                "question": "Will temperature be 24 C or below?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.50", "0.50"]',
            },
            {
                "groupItemTitle": "25 C",
                "question": "Will temperature be 25 C?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.30", "0.70"]',
            },
            {
                "groupItemTitle": "26 C",
                "question": "Will temperature be 26 C?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.15", "0.85"]',
            },
            {
                "groupItemTitle": "27 C or higher",
                "question": "Will temperature be 27 C or higher?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.05", "0.95"]',
            }
        ]
    }
    
    print("\nBuilding model to get analog search output...")
    res = model.build(mock_event, historical_sources=sources, live_sources=sources)
    print("\nBuild completed successfully!")
    
    analog_res = res.get("analog_search")
    if not analog_res:
        print("Error: No analog search results returned.")
        sys.exit(1)
        
    print(f"\nAnalog Search (Cutoff Hour: {analog_res.get('cutoff_hour')}:00)")
    
    today_feat = analog_res.get("today_features", {})
    print("\nToday's Features:")
    print(f"  High so far: {today_feat.get('high_so_far')} C")
    print(f"  Rise from 7 AM: {today_feat.get('rise_from_7am'):.2f} C")
    print(f"  Dew Point: {today_feat.get('dewpoint_c')} C")
    print(f"  Wind Group: {today_feat.get('wind_group')}")
    print(f"  Cloud Group: {today_feat.get('cloud_group')}")
    
    print("\nTop 5 Analogs:")
    analogs = analog_res.get("analogs", [])
    for idx, d in enumerate(analogs):
        print(f"\nAnalog #{idx+1}: Date = {d['date']} (Distance = {d['distance']:.4f}, Similarity = {d['similarity']:.1f}%)")
        print(f"  Final High: {d['final_high']} C (Bucket: {d['final_bucket']} C)")
        print(f"  High so far at cutoff: {d['high_so_far']} C")
        print(f"  Rise from 7 AM at cutoff: {d['rise_from_7am']:.2f} C")
        print(f"  Dew Point: {d['dewpoint_c']} C")
        print(f"  Wind Group: {d['wind_group']}")
        print(f"  Cloud Group: {d['cloud_group']}")
        
        path_non_null = {k: v for k, v in d['temp_path'].items() if v is not None}
        print(f"  Temperature Path: {sorted(path_non_null.items())}")

    print("\nVerify distance/similarity range:")
    for d in analogs:
        assert 0.0 <= d['similarity'] <= 100.0, "Similarity out of bounds"
        assert d['distance'] >= 0.0, "Distance cannot be negative"
        
    print("\nAll analog search tests passed successfully!")

if __name__ == "__main__":
    main()
