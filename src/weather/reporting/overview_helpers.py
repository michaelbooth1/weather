import datetime
import pandas as pd
import streamlit as st

from market_registry import all_specs
from market_config import config_for_date
from snapshot_tracker import SnapshotStore
from polymarket_client import PolymarketClient
from toronto_model import TorontoHighTempModel, TORONTO_TZ
from location_trust import score_market

@st.cache_data(ttl=60, show_spinner=False)
def compute_biggest_edges(n=10):
    edges = []
    
    for spec in all_specs():
        store = SnapshotStore(event_slug=config_for_date(market_id=spec.id).event_slug)
        if not store.long_path.exists():
            continue
            
        try:
            df = pd.read_csv(store.long_path)
            if df.empty:
                continue
                
            # Get the latest snapshot ID
            latest_snapshot_id = df.iloc[-1]["snapshot_id"]
            latest_df = df[df["snapshot_id"] == latest_snapshot_id]
            
            # Find the max absolute edge in this snapshot
            if latest_df.empty:
                continue
                
            # Edge is stored directly in the long dataframe
            latest_df = latest_df.copy()
            latest_df["abs_edge"] = latest_df["edge"].abs()
            
            # Sort by absolute edge descending and pick the top one
            top_row = latest_df.sort_values("abs_edge", ascending=False).iloc[0]
            
            # Get trust score
            try:
                trust = score_market(spec.id)
                trust_score = trust["trust_score"]
                settled_days = trust["settled_days"]
            except Exception:
                trust_score = 0
                settled_days = 0
                
            edges.append({
                "market_id": spec.id,
                "city_label": spec.city_label,
                "range_label": top_row.get("range_label", ""),
                "edge_percent": float(top_row.get("edge", 0)),
                "abs_edge": float(top_row.get("abs_edge", 0)),
                "model_prob": float(top_row.get("model_probability", 0)),
                "market_price": float(top_row.get("market_yes", 0)),
                "trust_score": trust_score,
                "settled_days": settled_days,
                "captured_at": top_row.get("captured_at_local", "")
            })
            
        except Exception as e:
            # Skip on error (e.g. malformed CSV)
            print(f"Error computing edge for {spec.id}: {e}")
            continue
            
    # Sort by absolute edge descending
    edges.sort(key=lambda x: x["abs_edge"], reverse=True)
    return edges[:n]

@st.cache_data(ttl=60, show_spinner=False)
def check_snapshot_status():
    status = []
    now = datetime.datetime.now(TORONTO_TZ)
    
    for spec in all_specs():
        store = SnapshotStore(event_slug=config_for_date(market_id=spec.id).event_slug)
        
        last_snapshot_str = "-"
        status_icon = "⚪"
        minutes_ago = -1
        
        if store.long_path.exists():
            try:
                # Just read the last few lines to save memory, or the whole file if small
                df = pd.read_csv(store.long_path)
                if not df.empty:
                    last_dt_str = df.iloc[-1]["captured_at_local"]
                    last_dt = pd.to_datetime(last_dt_str)
                    
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.tz_localize(TORONTO_TZ)
                    else:
                        last_dt = last_dt.tz_convert(TORONTO_TZ)
                        
                    diff = now - last_dt
                    minutes_ago = int(diff.total_seconds() / 60)
                    
                    # Format for display
                    last_snapshot_str = last_dt.strftime("%Y-%m-%d %H:%M")
                    
                    if minutes_ago < 30:
                        status_icon = "🟢"
                    elif minutes_ago < 60:
                        status_icon = "🟡"
                    else:
                        status_icon = "🔴"
            except Exception:
                status_icon = "🔴"
        else:
            status_icon = "🔴"
            
        status.append({
            "market_id": spec.id,
            "city_label": spec.city_label,
            "last_snapshot": last_snapshot_str,
            "minutes_ago": minutes_ago,
            "status_icon": status_icon
        })
        
    # Sort so that broken ones (red/yellow) appear at the top, then alphabetically by city
    def sort_key(x):
        priority = {"🔴": 0, "🟡": 1, "🟢": 2, "⚪": 3}.get(x["status_icon"], 4)
        return (priority, x["city_label"])
        
    status.sort(key=sort_key)
    return status

def format_edge_table(edges):
    if not edges:
        return pd.DataFrame()
        
    df = pd.DataFrame(edges)
    
    # Format columns for display
    df["Edge"] = (df["edge_percent"] * 100).map(lambda x: f"{x:+.1f}%")
    df["Model Prob"] = (df["model_prob"] * 100).map(lambda x: f"{x:.1f}%")
    df["Market Price"] = (df["market_price"] * 100).map(lambda x: f"{x:.1f}%")
    df["Trust"] = df["trust_score"].map(lambda x: f"{x:.0f}/100")
    df["Settled Days"] = df["settled_days"]
    
    # Rename columns for final output
    df = df.rename(columns={
        "city_label": "Market",
        "range_label": "Range Bucket",
        "captured_at": "Last Updated"
    })
    
    # Extract only the columns we want to show
    # (View Link will be added later in app.py due to Streamlit markdown limitations)
    return df[["Market", "Range Bucket", "Edge", "Model Prob", "Market Price", "Trust", "Settled Days", "market_id", "edge_percent"]]

def format_status_table(status):
    if not status:
        return pd.DataFrame()
        
    df = pd.DataFrame(status)
    
    df["Status"] = df["status_icon"]
    df["Last Snapshot"] = df["last_snapshot"]
    
    df = df.rename(columns={
        "city_label": "Market"
    })
    
    # Create an "Age" column
    def format_age(mins):
        if mins < 0:
            return "No data"
        if mins < 60:
            return f"{mins} mins ago"
        hours = mins // 60
        rem_mins = mins % 60
        return f"{hours}h {rem_mins}m ago"
        
    df["Age"] = df["minutes_ago"].apply(format_age)
    
    return df[["Status", "Market", "Last Snapshot", "Age"]]
