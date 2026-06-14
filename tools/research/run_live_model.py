import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel
from polymarket_client import PolymarketClient

def main():
    model = TorontoHighTempModel()
    
    print("Fetching historical sources...")
    historical = model.fetch_historical_sources()
    print("Historical sources fetched successfully.")
    
    print("Fetching live sources...")
    live = model.fetch_live_sources()
    print("Live sources fetched successfully.")
    
    # We can also mock Polymarket event to build the model rows
    try:
        print("Fetching Polymarket event...")
        event = PolymarketClient().get_toronto_weather_event()
    except Exception as e:
        print(f"Could not fetch Polymarket event: {e}. Creating dummy event.")
        event = {"markets": [], "title": "Highest temperature in Toronto on May 27?"}
        
    print("\nRunning model.build...")
    res = model.build(event, historical_sources=historical, live_sources=live)
    
    print("\nTop Temp Forecast:")
    print(f"Most likely high temp: {res['top_temp']} °C")
    
    print("\nModel Distribution:")
    for temp, prob in sorted(res['distribution'].items()):
        print(f"  {temp} °C: {prob*100:.2f}%")
        
    print("\nSource Signals:")
    for row in res['source_rows']:
        print(f"  {row['Source']} | {row['Signal']} | Value: {row['Value']} | Detail: {row['Detail']}")
        
    print("\nForecast Rows:")
    for row in res['forecast_rows']:
        print(f"  {row['Source']} | Time: {row['Time']} | Temp: {row['Temp']} | Cloud: {row['Cloud']} | Wind: {row['Wind']}")

if __name__ == "__main__":
    main()
