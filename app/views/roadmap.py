"""Roadmap status view for the Streamlit app."""

from __future__ import annotations

import streamlit as st

from app.table_utils import arrow_safe_records


def _open_item_rows(items):
    return [
        {
            "Item": item.get("number"),
            "Status": "blocked" if item.get("blocked") else "unblocked",
            "Title": item.get("title"),
            "Date": item.get("date") or "-",
            "Disposition": item.get("disposition") or "-",
        }
        for item in items
    ]


def render_roadmap_page():
    from weather.reporting.roadmap_backlog import summarize_roadmap_status

    @st.cache_data(ttl=30, show_spinner=False)
    def cached_summary():
        return summarize_roadmap_status()

    summary = cached_summary()

    st.title("Roadmap")
    st.caption(f"Generated: {summary.get('generated_at_utc')}")

    cols = st.columns(4)
    cols[0].metric("Closed", summary.get("closed_item_count", 0))
    cols[1].metric("Open", summary.get("open_item_count", 0))
    cols[2].metric("Open blocked", summary.get("open_blocked_item_count", 0))
    cols[3].metric("Open unblocked", summary.get("open_unblocked_item_count", 0))

    if summary.get("lint_error_count"):
        st.warning(f"Roadmap lint errors: {summary.get('lint_error_count')}")

    st.subheader("Open Items")
    st.dataframe(
        arrow_safe_records(_open_item_rows(summary.get("open_items") or [])),
        width="stretch",
        hide_index=True,
    )
    st.stop()
