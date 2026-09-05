"""Project, health and trading evidence in the existing Control Room."""

from __future__ import annotations

from datetime import datetime, timezone
import re

import streamlit as st

from app.table_utils import arrow_safe_dataframe
from weather.reporting.market.operator_control_room import attention_rows, evaluate_control_room


def _text(value, fallback="Unknown"):
    return fallback if value in (None, "") else str(value)


def _timestamp(value):
    if not value:
        return "not recorded"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).strftime("%b %d, %H:%M:%S UTC")
    except ValueError:
        return "invalid timestamp"


def _money(value):
    return "—" if value is None else f"{value:,.6f}"


def _load_control_room_snapshot():
    from app.monitor_data import load_control_snapshot

    return load_control_snapshot()


def _load_monitor_extras(control):
    from app.monitor_data import load_monitor_extras

    return load_monitor_extras(control)


def _plain(text):
    return re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)


def _project_panel(project):
    with st.container(border=True):
        st.subheader("Project now")
        st.write(_plain(project.get("objective") or "Project context unavailable."))
        steps = project.get("next_steps") or []
        if steps:
            st.markdown("**Next milestone**")
            st.write(_plain(steps[0]))
        head = (project.get("source") or {}).get("head")
        dirty = " · local edits" if (project.get("source") or {}).get("dirty") else ""
        st.caption(f"Project note: {_text(project.get('updated'), 'not dated')} · Dashboard source: {str(head)[:12] if head else 'unknown'}{dirty}")
        st.caption("Code history describes this checkout. Capture runtime adoption is reported separately in host evidence.")
        if head:
            base = f"https://github.com/michaelbooth1/weather/blob/{head}/docs"
            st.markdown(f"[Project note]({base}/operations/STATE_OF_PLAY.md) · [Maker plan]({base}/roadmap/items/item-330-maker-economics-refocus-master-plan.md)")


def _health_panel(evaluation, portable):
    st.subheader("System health")
    states = evaluation["states"]
    host = evaluation.get("host") or {}
    columns = st.columns(3)
    with columns[0], st.container(border=True):
        host_current = all(row["status"] == "CURRENT" for row in evaluation.get("freshness", {}).get("Host", []))
        st.metric("Capture host", host.get("verdict") if host and host_current else states["Host"]["status"])
        st.caption(states["Host"]["detail"] if host else "Waiting for a host observation. Details below.")
        st.write(f"Capture day: {_text((host.get('streak') or {}).get('today'))}")
    with columns[1], st.container(border=True):
        tape = host.get("execution_tape") or {}
        tape_label = tape.get("capture_state") if host_current and tape.get("process_healthy") is True else states["Execution tape"]["status"]
        st.metric("Execution tape", tape_label or "UNKNOWN")
        st.caption(states["Execution tape"]["detail"] if host else "Awaiting the capture-host observation.")
    with columns[2], st.container(border=True):
        portable_label = portable.get("recorded_status") if portable.get("status") == "CURRENT" else portable.get("status", "UNAVAILABLE")
        st.metric("Portable executor", portable_label or "UNKNOWN")
        if portable.get("recorded_status"):
            st.write(f"Recorded check: {portable['recorded_status']}")
        st.caption(f"Observed {_timestamp(portable['observed_at'])}" if portable.get("observed_at") else portable.get("detail") or "No observation available.")
    with st.expander("Host details and alerts"):
        if host:
            st.write(f"Free disk: {_text(host.get('disk_free_gb'))} GiB · Free memory: {_text(host.get('ram_free_gb'))} GiB")
            chain = host.get("chain") or {}
            st.write(f"Daily chain: {_text(chain.get('status'))} · Failing step: {_text(chain.get('failing_step'), 'none recorded')}")
            st.write(f"Capture checkout: {_text((host.get('git') or {}).get('last'))}")
            runtime = host.get("capture_runtime") or {}
            if runtime:
                st.write(runtime)
        for flag in (host.get("flags") or [])[:12]:
            st.warning(str(flag))
        for flag in (portable.get("flags") or [])[:8]:
            st.write(f"Portable check: {flag}")
        if not host:
            st.info(states["Host"]["detail"])
        st.caption("Host collection is shared across browser sessions and cached for five minutes.")


def _session_panel(session):
    st.subheader("Current session")
    if not session.get("configured"):
        st.info("No portable attempt connected. The session view will populate when an attended attempt is selected at launch.")
        return
    st.caption(f"Attempt: {_text(session.get('attempt'))}. {session.get('detail', '')}")
    columns = st.columns(3)
    for column, stage in zip(columns, session.get("stages") or []):
        with column, st.container(border=True):
            st.markdown(f"**{stage['label']}**")
            if stage["state"] in {"OUTCOME UNKNOWN", "INVALID", "FINISHED · FAIL", "FINISHED · INTERRUPTED"}:
                st.warning(stage["state"])
            else:
                st.write(stage["state"])
            st.caption(stage["detail"])
            st.caption(_timestamp(stage.get("observed_at")))
            result = stage.get("result") or {}
            if result:
                st.write(f"Recorded order: {_text(result.get('order_id'))}")
                st.write(f"Recorded notional: {_money(result.get('order_notional_usdc'))} pUSD")
                st.caption(f"Cancellation reported: {_text(result.get('cancellation_observed'))} · Ending orders clear: {_text(result.get('zero_open_orders_verified'))}")
            if stage.get("journal_error"):
                st.warning(stage["journal_error"])


def _trading_panel(trading):
    st.subheader("Trades and risk")
    if not trading.get("available"):
        st.info(trading.get("detail") or "No trading evidence connected.")
        return
    age = trading.get("reconciliation") or {}
    st.caption(f"Run {trading['run_id']} · {trading.get('mode') or 'mode unknown'} · Market date {trading.get('target_date')} · {age.get('detail', '')}")
    if age.get("status") != "CURRENT":
        st.warning("Current orders and exposure are unknown. Any rows below are historical observations.")
    columns = st.columns(3)
    columns[0].metric("Recorded open orders", _text(trading.get("open_orders"), "—"))
    columns[1].metric("Recorded reserved · pUSD", _money(trading.get("reserved")))
    columns[2].metric("Reconciliation", _text(trading.get("recorded_status"), "NO RECEIPT"))
    for tab, name in zip(st.tabs(["Orders", "Fills", "Positions"]), ("orders", "fills", "positions")):
        with tab:
            rows = trading.get(name) or []
            if rows:
                st.dataframe(arrow_safe_dataframe(rows), hide_index=True, width="stretch")
            else:
                st.caption(f"No {name} rows in the selected observation. Missing evidence does not establish a zero balance.")
    for label, count in (trading.get("order_mismatches") or {}).items():
        if count:
            st.warning(f"{label}: {count:g}")


def _results_panel(trading):
    st.subheader("Results")
    if not trading.get("available"):
        st.info("Reconciled trading results will appear after a run produces accounting evidence.")
        return
    amounts = trading.get("amounts") or {}
    st.caption(f"Recorded results for {trading['run_id']}; amounts in pUSD. {(trading.get('accounting') or {}).get('detail', '')}")
    columns = st.columns(4)
    for column, label in zip(columns, ("Net reconciled P&L", "Paid maker rebates", "Paid liquidity rewards", "Actual fees")):
        column.metric(label, _money(amounts.get(label)))
    if not trading.get("accounting_complete"):
        st.info("Accounting is incomplete. Net reconciled P&L remains unknown.")
    with st.expander("Accounting breakdown and pending evidence"):
        st.dataframe(arrow_safe_dataframe([
            {"Component": name, "pUSD": _money(value),
             "Basis": "Estimate; unpaid" if name == "Estimated fill rebates" else "Recorded report"}
            for name, value in amounts.items()
        ]), hide_index=True, width="stretch")
        if not trading.get("paid_verified"):
            st.caption("Paid incentives require matched wallet credits and a verified cash basis. Estimates are never added to paid totals.")
        for missing in (trading.get("missing_evidence") or [])[:12]:
            st.write(f"Pending: {missing}")


def _activity_panel(session, project):
    st.subheader("Recent activity")
    session_tab, code_tab = st.tabs(["Session events", "Code changes"])
    with session_tab:
        events = session.get("events") or []
        if events:
            st.dataframe(arrow_safe_dataframe([
                {"When": _timestamp(row.get("recorded_at_utc")), "Stage": row.get("stage"),
                 "Event": row.get("event_type"), "Order": row.get("order_id")}
                for row in events
            ]), hide_index=True, width="stretch")
        else:
            st.caption("No lifecycle events observed in the selected attempt.")
    with code_tab:
        for commit in (project.get("source") or {}).get("commits") or []:
            st.write(f"{commit['date']} · {commit['sha'][:8]} · {commit['title']}")
        st.caption("Recent committed changes in this checkout; commits alone do not prove deployment or completed milestones.")


@st.fragment(run_every="10s")
def render_control_room_page(refresh_seconds=10):
    st.markdown("<style>.block-container{max-width:1440px;padding-top:4rem} [data-testid=stMetricValue]{font-size:1.5rem} [data-testid=stMetricLabel]{white-space:normal} @media(max-width:700px){.block-container{padding:4rem 1rem 1rem} [data-testid=stMetricValue]{font-size:1.25rem}}</style>", unsafe_allow_html=True)
    st.caption("WEATHER · INTERNATIONAL POLYMARKET · READ-ONLY MONITOR")
    st.title("Control Room")
    st.caption("Project progress, system health and trading evidence in one place.")
    try:
        control, operations = _load_control_room_snapshot()
        evaluation = evaluate_control_room(control, operations)
        extras = _load_monitor_extras(control)
    except Exception as exc:  # noqa: BLE001 - missing evidence must not imply health
        st.error(f"Monitoring evidence is unavailable: {type(exc).__name__}: {exc}")
        return
    _project_panel(extras.get("project") or {})
    _health_panel(evaluation, extras.get("portable") or {})
    _session_panel(extras.get("session") or {})
    _trading_panel(extras.get("trading") or {})
    _results_panel(extras.get("trading") or {})
    _activity_panel(extras.get("session") or {}, extras.get("project") or {})
    with st.expander("General pilot evidence checklist"):
        st.caption("This general maker checklist is separate from the portable Stage 0/1 launcher's action-time checks. A dashboard status is not trading authority.")
        st.write(evaluation["verdict"])
        st.dataframe(arrow_safe_dataframe([
            {"Area": name, "Status": state["status"], "Detail": state["detail"]}
            for name, state in evaluation["states"].items()
        ]), hide_index=True, width="stretch")
        attention = attention_rows(evaluation)
        if attention:
            st.dataframe(arrow_safe_dataframe(attention), hide_index=True, width="stretch")
    st.caption(f"Session refresh: {refresh_seconds}s while this page is open · Project: 60s · Host: 5 min · Last view update: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
