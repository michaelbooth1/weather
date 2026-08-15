"""Two-page Streamlit router for the local operator frontend."""

from __future__ import annotations

import streamlit as st


LIVE_REFRESH_SECONDS = 300
PAGE_LABELS = {
    "Control Room": "control",
    "Roadmap": "roadmap",
}


st.set_page_config(
    page_title="Weather Operations",
    page_icon=":material/cloud:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _default_page():
    if "roadmap" in st.query_params:
        return "roadmap"
    requested = st.query_params.get("market")
    return requested if requested in PAGE_LABELS.values() else "control"


def _selected_page():
    default_page = _default_page()
    labels = list(PAGE_LABELS)
    default_index = next(
        index
        for index, label in enumerate(labels)
        if PAGE_LABELS[label] == default_page
    )
    st.sidebar.markdown("### Weather Operations")
    st.sidebar.caption("International maker pilot")
    selected = st.sidebar.selectbox("Page", labels, index=default_index)
    st.sidebar.caption("Read-only frontend")
    return PAGE_LABELS[selected]


def _sync_query_params(page):
    if page == "roadmap":
        if "roadmap" not in st.query_params or st.query_params.get("market"):
            st.query_params.clear()
            st.query_params["roadmap"] = ""
        return
    if "roadmap" in st.query_params or st.query_params.get("market") != "control":
        st.query_params.clear()
        st.query_params["market"] = "control"


def main():
    page = _selected_page()
    _sync_query_params(page)
    if page == "roadmap":
        from app.views.roadmap import render_roadmap_page

        render_roadmap_page()
    else:
        from app.views.control_room import render_control_room_page

        render_control_room_page(LIVE_REFRESH_SECONDS)


main()
