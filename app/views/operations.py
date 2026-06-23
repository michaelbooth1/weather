"""Operations page view for the Streamlit app."""

import streamlit as st

from app.table_utils import arrow_safe_records


def render_operations_page():
    from weather.operations.ops_monitor import (
        ensure_clob_book_loop,
        ensure_weather_loop,
        loop_status_rows,
        nightly_retrain_status_rows,
        restart_clob_loop,
        restart_weather_loop,
        scheduled_task_rows,
        set_clob_paused,
        set_weather_paused,
        start_all_loops,
        stop_all_loops,
        stop_clob_book_loop,
        stop_weather_loop,
    )
    from weather.runtime_identity import format_runtime_identity, get_runtime_identity

    @st.cache_data(ttl=15, show_spinner=False)
    def cached_ops_snapshot():
        current_identity = get_runtime_identity()
        return {
            "current_identity": current_identity,
            "loops": loop_status_rows(current_identity),
            "nightly": nightly_retrain_status_rows(),
            "tasks": scheduled_task_rows(),
        }

    def run_ops_action(label, action):
        try:
            st.session_state["ops_last_action"] = {
                "action": label,
                "result": action(),
            }
        except Exception as exc:  # noqa: BLE001 - operator actions should surface in-page
            st.session_state["ops_last_action"] = {
                "action": label,
                "error": f"{type(exc).__name__}: {exc}",
            }
        cached_ops_snapshot.clear()
        st.rerun()

    snapshot = cached_ops_snapshot()
    current_identity = snapshot["current_identity"]
    loop_rows = snapshot["loops"]
    nightly_row = snapshot["nightly"]
    task_rows = snapshot["tasks"]
    weather_row = next(row for row in loop_rows if row["Loop"] == "Weather snapshots")
    clob_row = next(row for row in loop_rows if row["Loop"] == "CLOB books")

    st.title("Operations")
    st.caption("Current checkout")
    st.code(format_runtime_identity(current_identity), language=None)

    if "ops_last_action" in st.session_state:
        with st.expander("Last Action", expanded=True):
            st.json(st.session_state["ops_last_action"])

    status_cols = st.columns(5)
    status_cols[0].metric("Weather", weather_row["State"] or "UNKNOWN")
    status_cols[1].metric("CLOB", clob_row["State"] or "UNKNOWN")
    stale_count = sum(1 for row in loop_rows if row["Code State"] == "different")
    status_cols[2].metric("Code Drift", stale_count)
    status_cols[3].metric("Nightly", nightly_row["State"] or "UNKNOWN")
    missing_tasks = sum(1 for row in task_rows if not row.get("Registered"))
    status_cols[4].metric("Missing Tasks", missing_tasks)

    action_cols = st.columns(3)
    if action_cols[0].button("Start / Repair All", type="primary", width="stretch"):
        run_ops_action("start_all", start_all_loops)
    if action_cols[1].button("Stop All", width="stretch"):
        run_ops_action("stop_all", stop_all_loops)
    if action_cols[2].button("Refresh", width="stretch"):
        cached_ops_snapshot.clear()
        st.rerun()

    st.subheader("Loop Status")
    visible_loop_cols = [
        "Loop",
        "State",
        "PID",
        "Heartbeat",
        "Last Capture",
        "Errors",
        "Paused",
        "Mode",
        "Code State",
        "Running Code",
        "Started At",
        "Last Error",
    ]
    st.dataframe(
        arrow_safe_records([{key: row.get(key) for key in visible_loop_cols} for row in loop_rows]),
        width="stretch",
        hide_index=True,
    )

    weather_controls, clob_controls = st.columns(2)
    with weather_controls:
        st.markdown("#### Weather Snapshots")
        if st.button("Ensure Weather", width="stretch"):
            run_ops_action("ensure_weather", ensure_weather_loop)
        if st.button("Restart Weather", width="stretch"):
            run_ops_action("restart_weather", restart_weather_loop)
        if st.button("Stop Weather", width="stretch"):
            run_ops_action("stop_weather", stop_weather_loop)
        if weather_row["Paused"]:
            if st.button("Resume Weather", width="stretch"):
                run_ops_action("resume_weather", lambda: set_weather_paused(False))
        else:
            if st.button("Pause Weather", width="stretch"):
                run_ops_action("pause_weather", lambda: set_weather_paused(True))

    with clob_controls:
        st.markdown("#### CLOB Books")
        if st.button("Ensure CLOB", width="stretch"):
            run_ops_action("ensure_clob", ensure_clob_book_loop)
        if st.button("Restart CLOB", width="stretch"):
            run_ops_action("restart_clob", restart_clob_loop)
        if st.button("Stop CLOB", width="stretch"):
            run_ops_action("stop_clob", stop_clob_book_loop)
        if clob_row["Paused"]:
            if st.button("Resume CLOB", width="stretch"):
                run_ops_action("resume_clob", lambda: set_clob_paused(False))
        else:
            if st.button("Pause CLOB", width="stretch"):
                run_ops_action("pause_clob", lambda: set_clob_paused(True))

    st.subheader("Nightly Self-Improvement")
    st.dataframe(arrow_safe_records([nightly_row]), width="stretch", hide_index=True)

    st.subheader("Supervisor Tasks")
    st.dataframe(arrow_safe_records(task_rows), width="stretch", hide_index=True)

    st.subheader("Files")
    st.dataframe(
        arrow_safe_records([
            {
                "Loop": row["Loop"],
                "Status File": row["Status File"],
                "Diagnostics": row["Diagnostics"],
                "Console Log": row["Console Log"],
            }
            for row in loop_rows
        ]),
        width="stretch",
        hide_index=True,
    )
    st.stop()
