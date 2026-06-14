import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))
from toronto_model import TorontoHighTempModel, DEFAULT_DATA_ROOT

def main():
    print("Initializing model...")
    model = TorontoHighTempModel()
    
    print("\nFetching sources first time (populating cache if empty)...")
    res1 = model.fetch_live_sources()
    
    cache_path = DEFAULT_DATA_ROOT / "last_good_sources.json"
    print(f"Does cache file exist? {cache_path.exists()}")
    
    # Verify structure of first fetch
    for name, info in res1.items():
        print(f"  Source '{name}': ok = {info.get('ok')}, stale = {info.get('stale')}, fetched_at = {info.get('fetched_at')}")
        assert "fetched_at" in info, f"fetched_at missing from {name}"
        assert "ok" in info, f"ok missing from {name}"
        assert "stale" in info, f"stale missing from {name}"

    # Now, let's mock a failure. We will temporarily break one of the fetchers, or mock fetch_wu_current to raise an exception
    print("\nMocking fetch failure on 'wu_current'...")
    original_fetch_wu_current = model.fetch_wu_current
    
    def failing_fetch():
        raise RuntimeError("API Rate limit exceeded mock error")
        
    model.fetch_wu_current = failing_fetch
    
    print("\nFetching sources second time (with failing 'wu_current')...")
    res2 = model.fetch_live_sources()
    
    # Restore original fetcher
    model.fetch_wu_current = original_fetch_wu_current
    
    # Verify that 'wu_current' is now marked stale but still has data and ok = True
    wu_curr_info = res2.get("wu_current", {})
    print(f"  Mocked 'wu_current': ok = {wu_curr_info.get('ok')}, stale = {wu_curr_info.get('stale')}, fetched_at = {wu_curr_info.get('fetched_at')}, error = '{wu_curr_info.get('error')}'")
    
    assert wu_curr_info.get("ok") == True, "Failed source should return ok = True from cache fallback"
    assert wu_curr_info.get("stale") == True, "Failed source should be marked as stale = True"
    assert wu_curr_info.get("error") == "API Rate limit exceeded mock error", "Should preserve the fetch error description"
    assert "data" in wu_curr_info and len(wu_curr_info["data"]) > 0, "Should preserve the cached data payload"
    
    print("\nAll freshness and cache fallback tests passed successfully!")

if __name__ == "__main__":
    main()
