"""Streamlit app router."""

from __future__ import annotations

import streamlit as st

from weather.market.market_registry import all_specs


LIVE_REFRESH_SECONDS = 60


st.set_page_config(page_title="Weather Markets", layout="wide")


def _market_labels():
    labels = {
        "Home": "overview",
        "Roadmap": "roadmap",
        "History": "history",
        "Operations": "ops",
        "Market Making": "mm",
    }
    labels.update({spec.city_label: spec.id for spec in all_specs()})
    return labels


def _default_market():
    if "roadmap" in st.query_params:
        return "roadmap"
    return "history" if "history" in st.query_params else st.query_params.get("market", "overview")


def _selected_market_id(labels):
    default_market = _default_market()
    label_list = list(labels.keys())
    default_index = 0
    for index, label in enumerate(label_list):
        if labels[label] == default_market:
            default_index = index
            break
    selected_label = st.sidebar.selectbox("Market", label_list, index=default_index)
    return labels[selected_label]


def _sync_query_params(market_id):
    if market_id == "roadmap":
        if "roadmap" not in st.query_params or st.query_params.get("market"):
            st.query_params.clear()
            st.query_params["roadmap"] = ""
        return
    if market_id == "history":
        if "history" not in st.query_params or st.query_params.get("market") or "roadmap" in st.query_params:
            st.query_params.clear()
            st.query_params["history"] = ""
        return
    if "history" in st.query_params or "roadmap" in st.query_params:
        st.query_params.clear()
    st.query_params["market"] = market_id


def main():
    market_id = _selected_market_id(_market_labels())
    _sync_query_params(market_id)

    if market_id == "history":
        from app.views.history import render_history_page

        render_history_page()
    elif market_id == "roadmap":
        from app.views.roadmap import render_roadmap_page

        render_roadmap_page()
    elif market_id == "ops":
        from app.views.operations import render_operations_page

        render_operations_page()
    elif market_id == "overview":
        from app.views.overview import render_overview_page

        render_overview_page(LIVE_REFRESH_SECONDS)
    elif market_id == "mm":
        from app.views.market_making import render_market_making_page

        render_market_making_page(LIVE_REFRESH_SECONDS)
    else:
        from app.views.single_market import render_single_market_page

        render_single_market_page(market_id, LIVE_REFRESH_SECONDS)


main()
