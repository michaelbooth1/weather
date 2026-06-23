"""Overview page view for the Streamlit app."""

import streamlit as st


def render_overview_page(live_refresh_seconds):
    from weather.reporting.overview_helpers import (
        compute_biggest_edges,
        check_snapshot_status,
        format_audit_analysis_status_table,
        format_audit_market_direction_table,
        format_audit_pending_watchlist_table,
        format_audit_recommendations_table,
        format_audit_review_queue_table,
        format_edge_table,
        format_status_table,
        load_audit_analysis_dashboard,
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
                df_edges[["Market", "Range Bucket", "Edge", "Model Prob", "Market Price", "Trust", "Settled Days", "Audit Saved", "Action"]],
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

        # 2. Audit Analysis
        st.markdown('<div class="section-title">Audit Analysis</div>', unsafe_allow_html=True)
        analysis = load_audit_analysis_dashboard()
        payload = analysis.get("payload") or {}
        analysis_status = analysis.get("status") or {}
        summary = payload.get("summary") or {}
        st.caption(
            "Generated: "
            f"{analysis_status.get('generated_at_utc') or '-'} | "
            f"Analysis: {analysis_status.get('analysis_artifact_status') or '-'} | "
            f"Audit log: {analysis_status.get('audit_log_status') or '-'}"
        )
        warning_statuses = {"MISSING", "INVALID", "STALE", "EMPTY"}
        if analysis_status.get("analysis_artifact_status") in warning_statuses:
            st.warning(analysis_status.get("analysis_artifact_detail") or "Audit analysis artifact needs attention.")
        if analysis_status.get("audit_log_status") in warning_statuses:
            st.warning(analysis_status.get("audit_log_detail") or "Audit log needs attention.")

        metric_cols = st.columns(5)
        metric_cols[0].metric("Recommendations", summary.get("recommendation_count", 0))
        metric_cols[1].metric("Ready Review", summary.get("ready_for_operator_review_count", 0))
        metric_cols[2].metric("Pending", summary.get("pending_count", 0))
        metric_cols[3].metric("Market Closer", summary.get("market_closer_count", 0))
        metric_cols[4].metric("Model Closer", summary.get("model_closer_count", 0))

        st.dataframe(format_audit_analysis_status_table(analysis), width='stretch', hide_index=True)

        recommendations_df = format_audit_recommendations_table(payload)
        if not recommendations_df.empty:
            st.markdown("**Priority Recommendations**")
            st.dataframe(recommendations_df, width='stretch', hide_index=True)
        else:
            st.info("No audit-analysis recommendations found.")

        pending_df = format_audit_pending_watchlist_table(payload)
        if not pending_df.empty:
            st.markdown("**Pending Settlement Watchlist**")
            st.dataframe(pending_df, width='stretch', hide_index=True)

        pattern_df = format_audit_market_direction_table(payload)
        if not pattern_df.empty:
            st.markdown("**By Market And Direction**")
            st.dataframe(pattern_df, width='stretch', hide_index=True)

        review_queue_df = format_audit_review_queue_table(payload)
        if not review_queue_df.empty:
            st.markdown("**Operator Review Queue**")
            st.dataframe(review_queue_df, width='stretch', hide_index=True)

        # 3. Capture-Tape Health
        st.markdown('<div class="section-title">📊 Capture-Tape Health</div>', unsafe_allow_html=True)
        status = check_snapshot_status()
        df_status = format_status_table(status)
        st.dataframe(df_status, width='stretch', hide_index=True)

    render_overview()
    st.stop()
