"""Four-page Streamlit router for the local owner/operator frontend."""

from __future__ import annotations

import streamlit as st


LIVE_REFRESH_SECONDS = 10
PAGE_LABELS = {
    "Cockpit": "cockpit",
    "Control Room": "control",
    "Roadmap": "roadmap",
    "Reward Simulator": "simulator",
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
    if "market" not in st.query_params:
        return "cockpit"
    # ?market=simulator opens the simulator; any other ?market= value,
    # including retired routes, keeps the Control Room.
    return "simulator" if st.query_params.get("market") == "simulator" else "control"


def _selected_page():
    default_page = _default_page()
    labels = list(PAGE_LABELS)
    default_index = next(
        index
        for index, label in enumerate(labels)
        if PAGE_LABELS[label] == default_page
    )
    st.sidebar.markdown("### Weather Operations")
    st.sidebar.caption("Owner cockpit, project and trading monitor")
    selected = st.sidebar.selectbox("Page", labels, index=default_index)
    st.sidebar.caption("Read-only frontend")
    return PAGE_LABELS[selected]


def _sync_query_params(page):
    if page == "cockpit":
        if set(st.query_params) != {"cockpit"}:
            st.query_params.clear()
            st.query_params["cockpit"] = ""
        return
    if page == "roadmap":
        if "roadmap" not in st.query_params or st.query_params.get("market"):
            st.query_params.clear()
            st.query_params["roadmap"] = ""
        return
    if set(st.query_params) != {"market"} or st.query_params.get("market") != page:
        st.query_params.clear()
        st.query_params["market"] = page


def main():
    page = _selected_page()
    _sync_query_params(page)
    if page == "roadmap":
        from app.views.roadmap import render_roadmap_page

        render_roadmap_page()
    elif page == "cockpit":
        from app.views.cockpit import render_cockpit_page

        render_cockpit_page()
    elif page == "simulator":
        from app.views.liquidity_simulator import render_liquidity_simulator_page

        render_liquidity_simulator_page()
    else:
        from app.views.control_room import render_control_room_page

        render_control_room_page(LIVE_REFRESH_SECONDS)


main()
