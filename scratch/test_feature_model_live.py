import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath("src"))
from toronto_model import TorontoHighTempModel

def main():
    print("Initializing model...")
    model = TorontoHighTempModel()
    
    print("\nFetching sources...")
    sources = model.fetch_sources()
    print("Fetched sources:", list(sources.keys()))
    
    print("\nBuilding model...")
    # Mock a basic event structure for May 27
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
    
    res = model.build(mock_event, historical_sources=sources, live_sources=sources)
    print("\nBuild completed successfully!")
    print("Active Model Version:", res.get("model_version"))
    print("Most likely final high:", res.get("top_temp"), "C")
    print("\nModel Distribution:")
    for temp, prob in sorted(res["distribution"].items()):
        if prob > 0.01:
            print(f"  {temp} C: {prob*100:.1f}%")
            
    print("\nModel Notes:")
    for note in res["notes"]:
        print("-", note)

    print("\nBoundary Transitions:")
    bt = res.get("boundary_transitions")
    if bt:
        print(f"  Current max bucket: {bt.get('current_max_bucket')} C")
        print(f"  Cutoff hour: {bt.get('cutoff_hour')}:00")
        print(f"  Sample size: {bt.get('sample_size')} days")
        print(f"  Skip rate: {bt.get('skip_rate')*100:.2f}%")
        print("  Transitions table:")
        for t in bt.get("transitions", []):
            print(f"    {t['Target Bucket']}: {t['Probability']} (Count={t['Historical Days']})")

    print("\nLate-Day Extension Risk:")
    ld = res.get("late_day_risk")
    if ld:
        print(f"  Active: {ld.get('active')}")
        print(f"  Continuation Probability: {ld.get('continuation_probability')*100:.2f}%")
        print(f"  Stable For: {ld.get('time_since_reached')} minutes")
        print(f"  First Reached Time: {ld.get('first_reached_time')}")
        print(f"  Seasonal Baseline: {ld.get('empirical_prior')*100:.2f}%")
    else:
        print("  Inactive (outside late-day window)")

    print("\nLate-Day Extension Risk (Direct Mock Test for 16:30):")
    from zoneinfo import ZoneInfo
    mock_now = datetime(2026, 5, 27, 16, 30, tzinfo=ZoneInfo("America/Toronto"))
    ld_mock = model.predict_late_day_continuation(sources, 16, mock_now)
    if ld_mock:
        print(f"  Active: {ld_mock.get('active')}")
        print(f"  Continuation Probability: {ld_mock.get('continuation_probability')*100:.2f}%")
        print(f"  Stable For: {ld_mock.get('time_since_reached')} minutes")
        print(f"  First Reached Time: {ld_mock.get('first_reached_time')}")
        print(f"  Seasonal Baseline: {ld_mock.get('empirical_prior')*100:.2f}%")
    else:
        print("  Failed to predict for mock time")

if __name__ == "__main__":
    main()
