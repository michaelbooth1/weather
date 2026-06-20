"""Recent model-performance history page for the Streamlit app."""

from __future__ import annotations

import importlib

import streamlit as st


def _metric_value(formatter, value):
    return formatter(value) if value is not None else "-"


def render_history_page(days=5):
    import weather.reporting.model_history as history_model

    history_model = importlib.reload(history_model)
    build_history_payload = history_model.build_history_payload
    format_daily_brier_table = history_model.format_daily_brier_table
    fmt_pct = history_model.fmt_pct
    fmt_score = history_model.fmt_score
    fmt_signed = history_model.fmt_signed
    fmt_signed_pct = history_model.fmt_signed_pct
    format_day_table = history_model.format_day_table
    format_group_table = history_model.format_group_table
    format_location_hour_table = history_model.format_location_hour_table
    format_timeline_table = history_model.format_timeline_table

    @st.cache_data(ttl=300, show_spinner="Scoring recent model history...")
    def cached_history(selected_days):
        return build_history_payload(days=selected_days, use_cache=True)

    st.title("Model History")
    st.caption("Recent settlement-scored model performance by location and target day.")

    control_cols = st.columns([1, 3])
    selected_days = control_cols[0].number_input(
        "Completed days",
        min_value=1,
        max_value=14,
        value=days,
        step=1,
    )
    if control_cols[1].button("Refresh history", width="content"):
        cached_history.clear()
        st.rerun()

    payload = cached_history(int(selected_days))
    overall = payload.get("overall") or {}
    dates = payload.get("dates") or []
    cache = payload.get("cache") or {}

    st.caption("Target dates: " + (", ".join(dates) if dates else "-"))
    if cache.get("hit"):
        st.caption(f"Loaded cached history from {cache.get('generated_at') or cache.get('path')}")

    metrics = st.columns(6)
    metrics[0].metric("Market Days", overall.get("market_days", 0))
    metrics[1].metric("Locations", overall.get("locations", 0))
    metrics[2].metric("Rows", overall.get("scored_rows", 0))
    metrics[3].metric("Brier Skill", _metric_value(fmt_signed_pct, overall.get("brier_skill_score")))
    metrics[4].metric("Daily-First Skill", _metric_value(fmt_signed_pct, overall.get("daily_first_brier_skill_score")))
    metrics[5].metric("Final Top Hit", _metric_value(lambda v: fmt_pct(v, digits=0), overall.get("final_top_hit_rate")))

    score_cols = st.columns(4)
    score_cols[0].metric("Model Brier", _metric_value(fmt_score, overall.get("model_brier")))
    score_cols[1].metric("Market Brier", _metric_value(fmt_score, overall.get("market_brier")))
    score_cols[2].metric("LogLoss Delta", _metric_value(fmt_signed, overall.get("logloss_delta")))
    score_cols[3].metric("Winner >50 Rate", _metric_value(lambda v: fmt_pct(v, digits=0), overall.get("winner_crossed_50_rate")))

    day_table = format_day_table(payload.get("days") or [])
    if day_table.empty:
        st.info("No history rows found for the selected window.")
        st.stop()

    daily_brier = format_daily_brier_table(payload.get("days") or [])
    st.subheader("Daily Brier By Location")
    st.dataframe(daily_brier, width="stretch", hide_index=True)

    st.subheader("Location / Day Summary")
    st.dataframe(day_table, width="stretch", hide_index=True)

    by_location = format_group_table(payload.get("by_location") or [], "Location")
    by_date = format_group_table(payload.get("by_date") or [], "Date")

    loc_col, date_col = st.columns(2)
    with loc_col:
        st.subheader("Overall By Location")
        st.dataframe(by_location, width="stretch", hide_index=True)
    with date_col:
        st.subheader("Overall By Day")
        st.dataframe(by_date, width="stretch", hide_index=True)

    timeline = format_timeline_table(payload.get("days") or [])
    st.subheader("Winning-Bucket Confidence Timing")
    st.dataframe(timeline, width="stretch", hide_index=True)

    location_hour = format_location_hour_table(payload.get("by_location_hour") or [])
    st.subheader("Winner-Band Catch-Up By Location/Hour")
    st.dataframe(location_hour, width="stretch", hide_index=True)

    if not by_location.empty and "Brier Skill" in by_location:
        chart_source = by_location.copy()
        chart_source["Brier Skill"] = chart_source["Brier Skill"].str.rstrip("%").astype(float)
        chart_source = chart_source.set_index("Location")[["Brier Skill"]]
        st.subheader("Brier Skill By Location")
        st.bar_chart(chart_source, width="stretch")

    st.stop()
