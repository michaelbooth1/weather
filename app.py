import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st


sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src"))
)

from polymarket_client import (  # noqa: E402
    PolymarketClient,
)
from market_config import config_for_date, config_from_event  # noqa: E402
from snapshot_tracker import SnapshotStore  # noqa: E402
from toronto_model import TorontoHighTempModel, TORONTO_TZ  # noqa: E402


LIVE_REFRESH_SECONDS = 60
LIVE_CACHE_TTL_SECONDS = 55


st.set_page_config(page_title="Toronto Weather Market", layout="wide")

APP_MARKET_CONFIG = config_for_date()

st.title("Toronto Weather Market")
st.caption(
    "Single-market view for the "
    f"{APP_MARKET_CONFIG.display_date} Toronto high-temperature event."
)


@st.cache_resource(show_spinner=False)
def model_client():
    return TorontoHighTempModel()


@st.cache_resource(show_spinner=False)
def snapshot_store():
    return SnapshotStore()


@st.cache_data(show_spinner=False)
def fetch_historical_sources():
    return model_client().fetch_historical_sources()


@st.cache_data(ttl=LIVE_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_event():
    return PolymarketClient().get_toronto_weather_event()


@st.cache_data(ttl=LIVE_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_live_sources():
    return model_client().fetch_live_sources()


@st.cache_data(ttl=LIVE_CACHE_TTL_SECONDS, show_spinner=False)
def load_snapshot_history():
    path = snapshot_store().long_path
    if not path.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_csv(path)
        df["captured_at_local"] = pd.to_datetime(df["captured_at_local"])
        return df
    except Exception as e:
        st.error(f"Error loading snapshot history: {e}")
        return None




def fmt_number(value, decimals=0):
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_price(value):
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


if st.button("Rebuild historical cache"):
    fetch_historical_sources.clear()
    model_client().clear_historical_cache()
    st.rerun()

historical_sources = fetch_historical_sources()


@st.fragment(run_every=f"{LIVE_REFRESH_SECONDS}s")
def live_dashboard(static_sources):
    action_col1, action_col2 = st.columns([1, 1])
    force_snapshot = action_col1.button("Save snapshot now")
    if action_col2.button("Refresh live now"):
        fetch_event.clear()
        fetch_live_sources.clear()
        st.rerun()

    with st.spinner("Fetching Toronto market and live weather..."):
        try:
            event = fetch_event()
            live_sources = fetch_live_sources()
        except Exception as exc:
            st.error(f"Could not fetch live Toronto data: {exc}")
            st.stop()

    client = PolymarketClient()
    rows = client.event_market_rows(event)
    model = model_client().build(
        event,
        historical_sources=static_sources,
        live_sources=live_sources,
    )
    snapshot_result = snapshot_store().maybe_write(
        event,
        model,
        model_client(),
        force=force_snapshot,
    )

    # Calculate live source freshness status
    live_sources_status = []
    has_stale = False
    now_local = datetime.now(TORONTO_TZ)
    
    for name, item in model["sources"].items():
        if name == "local_history":
            continue
            
        ok = item.get("ok", False)
        stale = item.get("stale", False)
        fetched_at_str = item.get("fetched_at")
        error_msg = item.get("error", "")
        
        age_str = "-"
        if fetched_at_str:
            try:
                fetched_at = datetime.fromisoformat(fetched_at_str)
                diff = now_local - fetched_at
                minutes = int(diff.total_seconds() / 60)
                if minutes <= 0:
                    age_str = "Just now"
                elif minutes == 1:
                    age_str = "1 min ago"
                else:
                    age_str = f"{minutes} mins ago"
            except:
                pass
                
        if ok and not stale:
            status = "🟢 Live"
        elif ok and stale:
            status = "🟡 Stale"
            has_stale = True
        else:
            status = "🔴 Failed"
            has_stale = True
            
        source_display_names = {
            "wu_history": "Wunderground History",
            "wu_current": "Weather.com Current CYYZ",
            "eccc_citypage": "ECCC Citypage Forecast",
            "eccc_swob": "ECCC SWOB Live CYYZ",
            "metar": "METAR Aviation CYYZ",
            "weather_forecast": "Weather.com Hourly Forecast",
            "open_meteo": "Open-Meteo Hourly Forecast"
        }
        
        live_sources_status.append({
            "Source": source_display_names.get(name, name),
            "Status": status,
            "Age": age_str,
            "Last Fetched": fetched_at_str.split("T")[-1][:5] if fetched_at_str else "-",
            "Fetch Error": error_msg or "-"
        })

    event_config = config_from_event(event, fallback_date=model_client().target_date)
    title = event.get(
        "title",
        f"Highest temperature in Toronto on {event_config.target_date:%B %d}?",
    )
    updated_at = event.get("updatedAt", "-")
    resolution_source = event.get("resolutionSource", "")

    if has_stale:
        stale_names = [s["Source"] for s in live_sources_status if "Live" not in s["Status"]]
        st.warning(
            f"⚠️ **Stale Feed Warning:** One or more live feeds could not be updated: **{', '.join(stale_names)}**. "
            "Showing last good cached data. Traders should exercise caution as model outputs may rely on delayed inputs."
        )

    st.subheader(title)
    st.markdown(f"[Open on Polymarket]({event_config.polymarket_url})")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Status", "Active" if event.get("active") else "Inactive")
    col2.metric("Liquidity", f"${fmt_number(event.get('liquidity'), 0)}")
    col3.metric("Volume", f"${fmt_number(event.get('volume'), 0)}")
    col4.metric("Open interest", f"${fmt_number(event.get('openInterest'), 0)}")

    refreshed_at = datetime.now().strftime("%H:%M:%S")
    st.caption(
        f"Live refreshed: {refreshed_at} | Market updated: {updated_at} | "
        f"Slug: {event_config.event_slug}"
    )
    if snapshot_result.get("written"):
        st.success(
            f"Saved snapshot {snapshot_result.get('snapshot_id')} "
            f"({snapshot_result.get('bands')} bands)."
        )
    else:
        st.caption(
            "Next odds snapshot due: "
            f"{snapshot_result.get('next_due_at') or 'now'}"
        )

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.warning("No child markets were returned for this event.")

    st.subheader("Model View")
    top_temp = model.get("top_temp")
    distribution = model.get("distribution", {})
    top_prob = distribution.get(top_temp) if top_temp is not None else None

    model_col1, model_col2, model_col3 = st.columns(3)
    model_col1.metric("Most likely final high", f"{top_temp} C" if top_temp else "-")
    model_col2.metric("Top bucket probability", fmt_price(top_prob))
    model_col3.metric("Model version", model.get("model_version", "v0.3 empirical intraday"))

    st.dataframe(model["model_rows"], use_container_width=True, hide_index=True)

    # Render Model Explanation Panel
    explanation = model.get("model_explanation")
    if explanation:
        st.subheader("Model Explanation")
        
        exp_col1, exp_col2, exp_col3 = st.columns(3)
        with exp_col1:
            st.markdown("**Active Constraints**")
            st.write(f"- **Floor (Min possible high):** {explanation.get('observed_floor')} C")
            st.write(f"- **Plausible Cap:** {explanation.get('forecast_cap')} C")
        with exp_col2:
            st.markdown("**Active Regimes**")
            st.write(f"- **Wind Regime:** {explanation.get('wind_regime')}")
            st.write(f"- **Cloud Regime:** {explanation.get('cloud_regime')}")
        with exp_col3:
            st.markdown("**Model Engine**")
            st.write(f"- **Engine Type:** {explanation.get('model_type')}")
            
        st.markdown("**Top Bucket Drivers Breakdown**")
        st.dataframe(explanation["top_buckets"], use_container_width=True, hide_index=True)

    st.subheader("25 C Deep Dive")
    st.dataframe(model["deep_dive_rows"], use_container_width=True, hide_index=True)

    # Render Bucket Boundary Transition Risk Panel
    boundary = model.get("boundary_transitions")
    if boundary and boundary.get("current_max_bucket") is not None:
        st.subheader("Intraday Bucket Transition Risk")
        
        observed_bucket = boundary.get("observed_bucket", boundary.get("current_max_bucket"))
        ch_hour = boundary.get("cutoff_hour")
        n_samples = boundary.get("sample_size")
        skip_pct = boundary.get("skip_rate") * 100
        
        st.markdown(
            f"Given that the confirmed floor bucket is **{observed_bucket} C** at or before **{ch_hour:02d}:00** cutoff: "
            f"Here is how similar seasonal historical days resolved (sample size $N = {n_samples}$ days):"
        )
        
        if boundary.get("transitions"):
            st.dataframe(boundary["transitions"], use_container_width=True, hide_index=True)
        else:
            st.warning("Insufficient historical sample size for transition analysis.")
            
        st.caption(
            f"**Boundary Skip Risk:** Historically, CYYZ hourly history skipped at least one whole-degree integer temperature bucket "
            f"during afternoon warming (10 AM to 6 PM) on **{skip_pct:.1f}%** of days. "
            f"Traders should monitor live METAR or SWOB updates for intra-hour jumps that may not print in the final settlement source."
        )

    # Render Late-Day Extension Risk Panel
    ld_risk = model.get("late_day_risk")
    if ld_risk and ld_risk.get("active"):
        st.subheader("Late-Day Extension Risk")
        
        prob = ld_risk["continuation_probability"]
        time_stable = ld_risk["time_since_reached"]
        first_time = ld_risk["first_reached_time"]
        base_rate = ld_risk["empirical_prior"]
        
        if prob > 0.25:
            risk_level = "🔴 High Extension Risk"
        elif prob > 0.10:
            risk_level = "🟡 Moderate Extension Risk"
        else:
            risk_level = "🟢 Low Extension Risk"
            
        ld_col1, ld_col2, ld_col3 = st.columns(3)
        ld_col1.metric("Extension Probability", f"{prob * 100:.1f}%")
        ld_col2.metric("Risk Status", risk_level)
        ld_col3.metric("Stable For", f"{time_stable} mins")
        
        st.caption(
            f"**Extension Risk Analysis:** The current high was first reached at **{first_time}** and has been stable for **{time_stable} minutes**. "
            f"Given these conditions along with today's wind direction, cloud cover, and morning warming rates, the continuation classifier "
            f"projects a **{prob*100:.1f}%** chance that the temperature will rise further before the end of the day "
            f"(compared to a raw seasonal baseline of **{base_rate*100:.1f}%**)."
        )

    # Render Closest Historical Analogs Panel
    analogs_data = model.get("analog_search")
    if analogs_data and analogs_data.get("analogs"):
        st.subheader("Closest Historical Analogs")
        
        today_feat = analogs_data["today_features"]
        analogs_list = analogs_data["analogs"]
        
        comparison_rows = []
        comparison_rows.append({
            "Date": f"TODAY ({model_client().target_date:%B %d})",
            "Match %": "-",
            "Final High": "-",
            "High so far": f"{today_feat.get('high_so_far')} C",
            "Rise from 7 AM": f"{today_feat.get('rise_from_7am'):.1f} C",
            "Dew Point": f"{today_feat.get('dewpoint_c')} C",
            "Wind Regime": today_feat.get("wind_group"),
            "Cloud Regime": today_feat.get("cloud_group")
        })
        for d in analogs_list:
            comparison_rows.append({
                "Date": d["date"],
                "Match %": f"{d['similarity']:.1f}%",
                "Final High": f"{d['final_high']} C",
                "High so far": f"{d['high_so_far']} C",
                "Rise from 7 AM": f"{d['rise_from_7am']:.1f} C",
                "Dew Point": f"{d['dewpoint_c']} C",
                "Wind Regime": d["wind_group"],
                "Cloud Regime": d["cloud_group"]
            })
        st.dataframe(comparison_rows, use_container_width=True, hide_index=True)

        # Temp progress line chart
        hours = [f"{h:02d}:00" for h in range(7, 21)]
        chart_data = {}
        
        today_path = today_feat.get("temp_path", {})
        chart_data["Today"] = [today_path.get(h) for h in hours]
        
        for d in analogs_list:
            col_name = f"{d['date']} ({d['similarity']:.1f}%)"
            analog_path = d.get("temp_path", {})
            chart_data[col_name] = [analog_path.get(h) for h in hours]
            
        import pandas as pd
        chart_df = pd.DataFrame(chart_data, index=hours)
        
        st.markdown("**Temperature Progression Comparison (7 AM to 8 PM)**")
        st.line_chart(chart_df, use_container_width=True)

    # Render Source Freshness Status Panel
    st.subheader("Source Freshness Status")
    st.dataframe(live_sources_status, use_container_width=True, hide_index=True)

    st.subheader("Source Signals")
    st.dataframe(model["source_rows"], use_container_width=True, hide_index=True)

    if model["forecast_rows"]:
        st.subheader("Remaining Forecast")
        st.dataframe(model["forecast_rows"], use_container_width=True, hide_index=True)

    # Render Odds Timeline View Panel
    st.subheader("Odds Timeline View")
    
    # 1. Compact table of current biggest positive and negative edges
    current_edges = []
    for bin_data in model_client().market_bins(event):
        label = model_client().clean_label(
            bin_data.get("groupItemTitle") or bin_data.get("question", "")
        )
        model_prob = distribution.get(bin_data.get("value"), 0.0)
        if bin_data.get("kind") == "lte":
            model_prob = sum(prob for val, prob in distribution.items() if val <= bin_data["value"])
        elif bin_data.get("kind") == "gte":
            model_prob = sum(prob for val, prob in distribution.items() if val >= bin_data["value"])
            
        market_yes = bin_data.get("market_yes")
        if market_yes is not None:
            edge_val = model_prob - market_yes
            current_edges.append({
                "Range": label,
                "Model": f"{model_prob * 100:.1f}%",
                "Market Price": f"{market_yes * 100:.1f}%",
                "Edge Value": edge_val,
                "Edge": f"{edge_val * 100:+.1f}%"
            })
    
    if current_edges:
        pos_edges = [e for e in current_edges if e["Edge Value"] > 0.005]
        neg_edges = [e for e in current_edges if e["Edge Value"] < -0.005]
        
        pos_edges.sort(key=lambda x: x["Edge Value"], reverse=True)
        neg_edges.sort(key=lambda x: x["Edge Value"])
        
        edge_col1, edge_col2 = st.columns(2)
        with edge_col1:
            st.markdown("**Top Positive Edges (Model > Market)**")
            if pos_edges:
                st.dataframe(pos_edges, use_container_width=True, hide_index=True)
            else:
                st.caption("No positive edges.")
        with edge_col2:
            st.markdown("**Top Negative Edges (Model < Market)**")
            if neg_edges:
                st.dataframe(neg_edges, use_container_width=True, hide_index=True)
            else:
                st.caption("No negative edges.")

    # 2. Historical Timeline Line Charts
    hist_df = load_snapshot_history()
    if hist_df is not None and not hist_df.empty:
        st.write("---")
        st.markdown("**Historical Probability & Edge Timeline**")
        
        # Highlight threshold slider
        edge_threshold = st.slider(
            "Edge Highlight Threshold (Abs)",
            min_value=0.0,
            max_value=0.50,
            value=0.10,
            step=0.01,
            format="%.2f"
        )
        
        unique_bands = sorted(hist_df["range_label"].unique())
        tabs = st.tabs(list(unique_bands))
        for tab, band in zip(tabs, unique_bands):
            with tab:
                band_df = hist_df[hist_df["range_label"] == band].sort_values("captured_at_local")
                if not band_df.empty:
                    # Prepare plot dataframe
                    plot_df = band_df[["captured_at_local", "model_probability", "market_yes", "edge"]].copy()
                    plot_df.columns = ["Time", "Model Probability", "Market Price", "Edge"]
                    plot_df.set_index("Time", inplace=True)
                    
                    st.line_chart(plot_df, use_container_width=True)
                    
                    # Highlight/flag snapshots crossing threshold
                    flagged = band_df[band_df["edge"].abs() >= edge_threshold].copy()
                    if not flagged.empty:
                        st.markdown(f"⚠️ **Snapshots Crossing {edge_threshold*100:.0f}% Edge Threshold:**")
                        flagged["Time"] = flagged["captured_at_local"].dt.strftime("%m-%d %H:%M")
                        flagged["Model Prob"] = (flagged["model_probability"] * 100).map(lambda x: f"{x:.1f}%")
                        flagged["Market Price"] = (flagged["market_yes"] * 100).map(lambda x: f"{x:.1f}%")
                        flagged["Edge Value"] = (flagged["edge"] * 100).map(lambda x: f"{x:+.1f}%")
                        
                        st.dataframe(
                            flagged[["Time", "Model Prob", "Market Price", "Edge Value"]],
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.caption("No snapshots crossed the threshold for this band.")
    else:
        st.caption("No historical snapshots available to show timeline view.")

    # Render Snapshot Controls & Diagnostics Expandable Panel
    with st.expander("Snapshot Controls & Diagnostics"):
        st.markdown("### Background Loop Control")
        
        # Pause flag file path
        pause_flag_path = Path("data") / "snapshots" / "loop_pause.flag"
        
        # Toggle loop pause status
        is_paused = pause_flag_path.exists()
        loop_toggle = st.toggle("Pause Background Snapshot Loop", value=is_paused)
        
        # Act on loop pause status
        if loop_toggle != is_paused:
            if loop_toggle:
                # Create pause flag
                pause_flag_path.parent.mkdir(parents=True, exist_ok=True)
                pause_flag_path.touch()
                st.success("Background loop paused.")
            else:
                # Delete pause flag
                try:
                    pause_flag_path.unlink()
                    st.success("Background loop resumed.")
                except FileNotFoundError:
                    pass
            st.rerun()
            
        # Display file paths and metadata
        st.markdown("### Snapshot Storage & Stats")
        
        # Path details
        store = snapshot_store()
        
        # Calculate row counts
        long_rows_cnt = 0
        wide_rows_cnt = 0
        forecast_rows_cnt = 0
        
        if store.long_path.exists():
            try:
                with store.long_path.open("r", encoding="utf-8") as f:
                    long_rows_cnt = sum(1 for _ in f) - 1 # exclude header
            except:
                pass
                
        if store.wide_path.exists():
            try:
                with store.wide_path.open("r", encoding="utf-8") as f:
                    wide_rows_cnt = sum(1 for _ in f) - 1 # exclude header
            except:
                pass
                
        if store.forecasts_long_path.exists():
            try:
                with store.forecasts_long_path.open("r", encoding="utf-8") as f:
                    forecast_rows_cnt = sum(1 for _ in f) - 1 # exclude header
            except:
                pass
                
        st.write(f"- **Long Format Snapshots CSV:** `{store.long_path}` ({long_rows_cnt} rows)")
        st.write(f"- **Wide Format Snapshots CSV:** `{store.wide_path}` ({wide_rows_cnt} rows)")
        st.write(f"- **Forecast Snapshot CSV:** `{store.forecasts_long_path}` ({forecast_rows_cnt} rows)")
        st.write(f"- **JSONL Snapshot Archive:** `{store.jsonl_path}`")
        
        # Last snapshot view
        st.markdown("### View Last Snapshot")
        if hist_df is not None and not hist_df.empty:
            last_id = hist_df["snapshot_id"].iloc[-1]
            last_time = hist_df["captured_at_local"].iloc[-1]
            st.write(f"Last recorded snapshot ID: `{last_id}` captured at **{last_time}**")
            
            if st.button("Inspect Last Snapshot Details"):
                last_snapshot_df = hist_df[hist_df["snapshot_id"] == last_id].copy()
                st.dataframe(
                    last_snapshot_df[["range_label", "model_probability", "market_yes", "edge"]],
                    use_container_width=True,
                    hide_index=True
                )
                
        # Mini changelog of last 5 snapshots
        st.markdown("### Mini Changelog (Last 5 Snapshots)")
        if hist_df is not None and not hist_df.empty:
            # Group by snapshot_id to get unique snapshots
            unique_snapshots = hist_df[["snapshot_id", "captured_at_local", "top_temp_c", "top_probability"]].drop_duplicates().tail(5)
            # Format dataframe
            unique_snapshots["Time"] = pd.to_datetime(unique_snapshots["captured_at_local"]).dt.strftime("%H:%M:%S")
            unique_snapshots["Top Projected Temp"] = unique_snapshots["top_temp_c"].map(lambda x: f"{x} C")
            unique_snapshots["Top Probability"] = unique_snapshots["top_probability"].map(lambda x: f"{x*100:.1f}%")
            
            st.dataframe(
                unique_snapshots[["Time", "snapshot_id", "Top Projected Temp", "Top Probability"]],
                use_container_width=True,
                hide_index=True
            )

    with st.expander("Model notes"):
        for note in model["notes"]:
            st.write(f"- {note}")

    with st.expander("Resolution rules"):
        st.write(event.get("description", "No description returned."))
        if resolution_source:
            st.markdown(f"[Resolution source]({resolution_source})")


live_dashboard(historical_sources)
