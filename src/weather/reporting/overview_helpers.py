import datetime
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from weather.collection.snapshot_tracker import SnapshotStore
from weather.market.market_config import config_for_date
from weather.market.market_registry import all_specs
from weather.market.polymarket_client import PolymarketClient
from weather.model.toronto_model import TORONTO_TZ, TorontoHighTempModel
from weather.reporting.candidate_lifecycle.model_market_disagreement_audit import (
    DEFAULT_GAP_THRESHOLD_POINTS,
    DEFAULT_LOG_PATH as DEFAULT_DISAGREEMENT_AUDIT_LOG,
    audit_key_for_row,
    audit_saved_for_row,
    ensure_audit_record_saved,
    load_audit_index,
    read_audit_log,
    row_gap_points,
)
from weather.reporting.candidate_lifecycle.model_market_disagreement_analysis import (
    DEFAULT_JSON_OUT as DEFAULT_DISAGREEMENT_ANALYSIS_JSON,
    parse_time,
)
from weather.reporting.location_analysis.location_trust import score_market

@st.cache_data(ttl=60, show_spinner=False)
def compute_biggest_edges(n=10):
    edges = []
    try:
        audit_index = load_audit_index()
    except Exception:
        audit_index = {}
    
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
            audit_status_by_key = {}
            for _idx, candidate_row in latest_df.iterrows():
                candidate_dict = candidate_row.to_dict()
                if not candidate_dict.get("event_slug"):
                    candidate_dict["event_slug"] = store.event_slug
                gap_points = row_gap_points(candidate_dict)
                if gap_points is None or gap_points + 1e-9 < DEFAULT_GAP_THRESHOLD_POINTS:
                    continue
                try:
                    status = ensure_audit_record_saved(
                        candidate_dict,
                        folder=store.root,
                        audit_index=audit_index,
                    )
                    audit_key = status.get("audit_key") or audit_key_for_row(candidate_dict)
                    audit_status_by_key[audit_key] = status
                except Exception as exc:
                    print(f"Error saving edge audit for {spec.id}: {exc}")
            
            # Sort by absolute edge descending and pick the top one
            top_row = latest_df.sort_values("abs_edge", ascending=False).iloc[0]
            top_row_dict = top_row.to_dict()
            if not top_row_dict.get("event_slug"):
                top_row_dict["event_slug"] = store.event_slug
            top_audit_key = audit_key_for_row(top_row_dict)
            audit_status = {
                "saved": audit_saved_for_row(top_row_dict, audit_index=audit_index),
                "triggered": False,
                "written": False,
            }
            audit_status = audit_status_by_key.get(top_audit_key, audit_status)
            
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
                "captured_at": top_row.get("captured_at_local", ""),
                "event_slug": top_row_dict.get("event_slug"),
                "snapshot_id": top_row.get("snapshot_id", ""),
                "bin_kind": top_row.get("bin_kind", ""),
                "bin_value_c": top_row.get("bin_value_c", ""),
                "bin_value_hi_c": top_row.get("bin_value_hi_c", top_row.get("bin_value_hi", "")),
                "audit_saved": bool(audit_status.get("saved")),
                "audit_triggered": bool(audit_status.get("triggered")),
                "audit_written": bool(audit_status.get("written")),
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
    if "audit_saved" not in df:
        df["audit_saved"] = False
    df["Audit Saved"] = df["audit_saved"].map(bool)
    
    # Rename columns for final output
    df = df.rename(columns={
        "city_label": "Market",
        "range_label": "Range Bucket",
        "captured_at": "Last Updated"
    })
    
    # Extract only the columns we want to show
    # (View Link will be added later in app.py due to Streamlit markdown limitations)
    return df[["Market", "Range Bucket", "Edge", "Model Prob", "Market Price", "Trust", "Settled Days", "Audit Saved", "market_id", "edge_percent"]]

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


def _format_minutes(value):
    if value is None:
        return "-"
    value = int(value)
    if value < 60:
        return f"{value} mins"
    hours = value // 60
    minutes = value % 60
    return f"{hours}h {minutes}m"


def _age_minutes(now_utc, timestamp):
    if timestamp is None:
        return None
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)
    delta = now_utc - timestamp.astimezone(datetime.timezone.utc)
    return max(0, int(delta.total_seconds() // 60))


def _latest_audit_time(rows):
    latest = None
    for row in rows or []:
        parsed = parse_time(row.get("audited_at_utc"))
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def load_audit_analysis_dashboard(
    analysis_path=DEFAULT_DISAGREEMENT_ANALYSIS_JSON,
    *,
    now_utc=None,
    analysis_stale_minutes=90,
    audit_stale_minutes=240,
):
    """Load audit-analysis status and payload for the overview dashboard."""
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    analysis_path = Path(analysis_path)
    payload = None
    artifact_status = "MISSING"
    artifact_detail = "analysis artifact not found"
    generated_at = None
    analysis_age_minutes = None

    if analysis_path.exists():
        try:
            payload = json.loads(analysis_path.read_text(encoding="utf-8"))
            generated_at = parse_time(payload.get("generated_at_utc"))
            analysis_age_minutes = _age_minutes(now_utc, generated_at)
            if generated_at is None:
                artifact_status = "INVALID"
                artifact_detail = "generated_at_utc is missing or invalid"
            elif analysis_age_minutes is not None and analysis_age_minutes > analysis_stale_minutes:
                artifact_status = "STALE"
                artifact_detail = f"analysis is older than {analysis_stale_minutes} minutes"
            else:
                artifact_status = "OK"
                artifact_detail = "analysis artifact is fresh"
        except Exception as exc:
            payload = None
            artifact_status = "INVALID"
            artifact_detail = f"could not read analysis artifact: {exc}"

    summary = (payload or {}).get("summary") or {}
    audit_log_path = Path(summary.get("audit_log_path") or DEFAULT_DISAGREEMENT_AUDIT_LOG)
    audit_log_status = "MISSING"
    audit_log_detail = "audit log not found"
    latest_audit_at = None
    audit_log_age_minutes = None
    audit_row_count = 0
    if audit_log_path.exists():
        try:
            audit_rows = read_audit_log(audit_log_path)
            audit_row_count = len(audit_rows)
            latest_audit_at = _latest_audit_time(audit_rows)
            audit_log_age_minutes = _age_minutes(now_utc, latest_audit_at)
            if not audit_rows:
                audit_log_status = "EMPTY"
                audit_log_detail = "audit log has no saved disagreement snapshots"
            elif latest_audit_at is None:
                audit_log_status = "INVALID"
                audit_log_detail = "audit rows are missing audited_at_utc timestamps"
            elif audit_log_age_minutes is not None and audit_log_age_minutes > audit_stale_minutes:
                audit_log_status = "STALE"
                audit_log_detail = f"no qualifying audit snapshot in {audit_stale_minutes} minutes"
            else:
                audit_log_status = "OK"
                audit_log_detail = "audit log has recent qualifying snapshots"
        except Exception as exc:
            audit_log_status = "INVALID"
            audit_log_detail = f"could not read audit log: {exc}"

    return {
        "payload": payload or {},
        "status": {
            "analysis_artifact_status": artifact_status,
            "analysis_artifact_detail": artifact_detail,
            "analysis_path": str(analysis_path),
            "generated_at_utc": generated_at.isoformat() if generated_at else None,
            "analysis_age_minutes": analysis_age_minutes,
            "audit_log_status": audit_log_status,
            "audit_log_detail": audit_log_detail,
            "audit_log_path": str(audit_log_path),
            "latest_audit_at_utc": latest_audit_at.isoformat() if latest_audit_at else None,
            "audit_log_age_minutes": audit_log_age_minutes,
            "audit_log_row_count": audit_row_count,
        },
    }


def format_audit_analysis_status_table(analysis):
    status = (analysis or {}).get("status") or {}
    rows = [
        {
            "Check": "Analysis artifact",
            "Status": status.get("analysis_artifact_status") or "MISSING",
            "Latest": status.get("generated_at_utc") or "-",
            "Age": _format_minutes(status.get("analysis_age_minutes")),
            "Detail": status.get("analysis_artifact_detail") or "-",
        },
        {
            "Check": "Audit log",
            "Status": status.get("audit_log_status") or "MISSING",
            "Latest": status.get("latest_audit_at_utc") or "-",
            "Age": _format_minutes(status.get("audit_log_age_minutes")),
            "Detail": status.get("audit_log_detail") or "-",
        },
    ]
    return pd.DataFrame(rows)


def format_audit_recommendations_table(payload, *, limit=10):
    rows = []
    for item in (payload or {}).get("recommendations") or []:
        evidence = item.get("evidence") or {}
        route = item.get("route") or {}
        rows.append({
            "Priority": item.get("priority"),
            "Category": item.get("category"),
            "Market": item.get("market_id"),
            "Range Bucket": item.get("range_label"),
            "Direction": item.get("direction"),
            "Cases": evidence.get("case_count"),
            "Resolved": evidence.get("resolved_count"),
            "Pending": evidence.get("pending_count"),
            "Market Closer": evidence.get("market_closer_count"),
            "Repair Lane": route.get("repair_lane"),
            "Roadmap Owner": route.get("roadmap_owner"),
            "Counts As Evidence": bool(route.get("counts_toward_repair_evidence")),
            "Automatic Change": bool(route.get("automatic_model_or_trading_change_allowed")),
            "Action": item.get("action"),
        })
    return pd.DataFrame(rows[:limit])


def format_audit_pending_watchlist_table(payload, *, limit=10):
    rows = []
    for item in (payload or {}).get("pending_watchlist") or []:
        rows.append({
            "Market": item.get("market_id"),
            "Target Date": item.get("target_date"),
            "Range Bucket": item.get("range_label"),
            "Direction": item.get("direction"),
            "Gap Points": item.get("gap_points"),
            "Model-Market Points": item.get("model_minus_market_points"),
            "Audited": item.get("audited_at_utc"),
            "Evidence Use": "Settlement watchlist only",
        })
    return pd.DataFrame(rows[:limit])


def format_audit_market_direction_table(payload, *, limit=12):
    groups = (payload or {}).get("groups") or {}
    rows = []
    for item in groups.get("by_market_direction") or []:
        rows.append({
            "Market": item.get("market_id"),
            "Direction": item.get("direction"),
            "Cases": item.get("case_count"),
            "Resolved": item.get("resolved_count"),
            "Pending": item.get("pending_count"),
            "Model Closer": item.get("model_closer_count"),
            "Market Closer": item.get("market_closer_count"),
            "Avg Gap Points": item.get("avg_gap_points"),
            "Avg Brier Gap": item.get("avg_brier_gap_market_minus_model"),
        })
    return pd.DataFrame(rows[:limit])


def format_audit_review_queue_table(payload, *, limit=10):
    queue = (payload or {}).get("operator_review_queue") or {}
    rows = []
    for item in queue.get("rows") or []:
        rows.append({
            "Review ID": item.get("review_queue_id"),
            "Status": item.get("status"),
            "Priority": item.get("priority"),
            "Market": item.get("market_id"),
            "Range Bucket": item.get("range_label"),
            "Repair Lane": item.get("repair_lane"),
            "Roadmap Owner": item.get("roadmap_owner"),
            "Next Experiment": item.get("next_experiment"),
            "Counts As Evidence": bool(item.get("counts_toward_repair_evidence")),
            "Automatic Change": bool(item.get("automatic_model_or_trading_change_allowed")),
        })
    return pd.DataFrame(rows[:limit])
