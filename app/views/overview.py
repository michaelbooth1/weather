"""Overview page view for the Streamlit app."""

import streamlit as st


def render_overview_page(live_refresh_seconds):
    from weather.reporting.overview_helpers import (
        compute_biggest_edges,
        check_snapshot_status,
        format_edge_table,
        format_status_table,
    )

    @st.fragment(run_every=f"{live_refresh_seconds}s")
    def render_overview():
        st.markdown("""
        <style>
        .gradient-header {
            background: linear-gradient(90deg, #ff7e5f, #feb47b);
            -webkit-background-clip: text;
            color: transparent;
            font-size: 2.4rem;
            font-weight: bold;
        }
        .section-title {
            border-bottom: 2px solid #444;
            padding-bottom: 5px;
            margin-bottom: 15px;
            font-weight: 600;
            text-transform: uppercase;
        }
        </style>
        """, unsafe_allow_html=True)

        st.markdown('<div class="gradient-header">🗺️ Market Overview</div>', unsafe_allow_html=True)
        st.caption("High-level view of all active markets, biggest model edges, and data-capture health.")

        # 1. Biggest Edges
        st.markdown('<div class="section-title">🏆 Biggest Edges (Top 10)</div>', unsafe_allow_html=True)
        edges = compute_biggest_edges(n=10)
        df_edges = format_edge_table(edges)

        if not df_edges.empty:
            # Create the link target column
            df_edges["Action"] = df_edges["market_id"].apply(lambda m: f"/?market={m}")

            # Use column configuration to render links
            st.dataframe(
                df_edges[["Market", "Range Bucket", "Edge", "Model Prob", "Market Price", "Trust", "Settled Days", "Action"]],
                width='stretch',
                hide_index=True,
                column_config={
                    "Action": st.column_config.LinkColumn(
                        "Action",
                        display_text="Open Market"
                    )
                }
            )
        else:
            st.info("No active edge data found. Ensure snapshot loops are running.")

        # 2. Capture-Tape Health
        st.markdown('<div class="section-title">📊 Capture-Tape Health</div>', unsafe_allow_html=True)
        status = check_snapshot_status()
        df_status = format_status_table(status)
        st.dataframe(df_status, width='stretch', hide_index=True)

    render_overview()
    st.stop()
