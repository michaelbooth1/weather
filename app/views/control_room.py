"""Read-only operator control room for the International live-test runway."""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from app.table_utils import arrow_safe_dataframe
from weather.reporting.market.operator_control_room import (
    artifact_payload,
    attention_rows,
    evaluate_control_room,
)


def _text(value, fallback="-"):
    return fallback if value in (None, "") else str(value)


def _timestamp(value):
    if not value:
        return "not recorded"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _load_control_room_snapshot():
    from app.views.operations import host_status_snapshot
    from weather.reporting.market.operator_control_room import collect_control_room_snapshot

    return collect_control_room_snapshot(), {"host_status": host_status_snapshot()}


def _metric_columns(evaluation):
    states = evaluation["states"]
    host = evaluation.get("host") or {}
    tape = host.get("execution_tape") or {}
    readiness = evaluation.get("readiness") or {}
    columns = st.columns(6)
    columns[0].metric(
        "Capture",
        states["Capture"]["status"],
        delta=_text((host.get("streak") or {}).get("today"), "unknown"),
        delta_color="off",
    )
    columns[1].metric(
        "Host",
        states["Host"]["status"],
        delta=f"{len(host.get('flags') or [])} flags",
        delta_color="off",
    )
    columns[2].metric(
        "International",
        states["International"]["status"],
        delta="Polymarket Global",
        delta_color="off",
    )
    columns[3].metric(
        "Live readiness",
        states["Readiness"]["status"],
        delta=_text(readiness.get("status"), "no receipt"),
        delta_color="off",
    )
    columns[4].metric(
        "Execution tape",
        states["Execution tape"]["status"],
        delta=_text(tape.get("capture_state"), "unknown"),
        delta_color="off",
    )
    drift = (evaluation.get("economics") or {}).get("drift", {})
    columns[5].metric(
        "Economics",
        states["Economics"]["status"],
        delta=_text(drift.get("status"), "unknown"),
        delta_color="off",
    )


@st.fragment(run_every="300s")
def render_control_room_page(refresh_seconds=300):
    """Render a decision-first page with no live mutation controls."""

    st.markdown(
        """
        <style>
        .control-kicker {
          letter-spacing:.08em;text-transform:uppercase;color:#5f6b7a;
          font-size:.78rem;font-weight:700
        }
        .control-banner {
          border-radius:12px;padding:1rem 1.2rem;margin:.5rem 0 1rem;
          border:1px solid #d6a300;background:#fff8dc
        }
        .control-banner strong {font-size:1.45rem;color:#704f00}
        .control-contract {
          border-left:4px solid #176b87;padding:.55rem .9rem;
          background:#eef8fb;margin:.5rem 0 1rem
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="control-kicker">International Polymarket / read-only operations</div>',
        unsafe_allow_html=True,
    )
    st.title("Operator Control Room")
    st.caption(
        "A decision surface for the first capped maker-rebate test. This page reads persisted evidence only: "
        "it has no order, cancel, credential, promotion, or risk-setting controls."
    )

    try:
        control, operations = _load_control_room_snapshot()
    except Exception as exc:  # noqa: BLE001 - operator UI must fail closed
        st.error(f"Control-room evidence failed safely: {type(exc).__name__}: {exc}")
        return
    evaluation = evaluate_control_room(control, operations)
    st.markdown(
        f'<div class="control-banner"><span>LIVE TEST VERDICT</span><br><strong>{evaluation["verdict"]}</strong><br>'
        f'Target date: {_text(evaluation.get("target_date"), "no current run")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Even READY FOR EXPLICIT APPROVAL is software evidence, not trading authority. "
        "An operator must still explicitly authorize a specific run."
    )

    _metric_columns(evaluation)

    st.subheader("Attention now")
    attention = attention_rows(evaluation)
    if attention:
        st.dataframe(
            arrow_safe_dataframe(attention),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.success("No software blockers remain. Await explicit approval for a named run.")

    st.subheader("Live-test runway")
    runway = [
        {
            "Gate": name,
            "Status": state["status"],
            "Evidence-backed meaning": state["detail"],
        }
        for name, state in evaluation["states"].items()
    ]
    runway.append({
        "Gate": "Explicit operator approval",
        "Status": "ALWAYS MANUAL",
        "Evidence-backed meaning": "Approval is scoped to one named run and is never inferred from this dashboard.",
    })
    st.dataframe(arrow_safe_dataframe(runway), hide_index=True, use_container_width=True)

    contract = evaluation.get("pilot_contract") or {}
    max_budget = _text(contract.get("max_budget_usdc"), "100")
    market_count = _text(contract.get("market_count"), "1")
    st.markdown(
        '<div class="control-contract"><strong>Binding pilot contract</strong><br>'
        f'International Polymarket only; finite budget at or below {max_budget} '
        f'USDC-equivalent; exactly {market_count} market; '
        'post-only orders; no naked sells; existing risk ceilings cannot be raised.</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)
    run = evaluation.get("run") or {}
    readiness = evaluation.get("readiness") or {}
    lifecycle = run.get("order_lifecycle") or {}
    with left:
        st.subheader("Current maker evidence")
        st.dataframe(
            arrow_safe_dataframe([
                {"Metric": "Run ID", "Value": run.get("run_id")},
                {"Metric": "Mode", "Value": run.get("mode")},
                {"Metric": "Target date", "Value": run.get("target_date")},
                {"Metric": "Quote-permission rows", "Value": run.get("quote_permission_rows")},
                {"Metric": "Live-permission rows", "Value": run.get("live_trade_permission_rows")},
                {"Metric": "Open orders", "Value": lifecycle.get("current_open_order_count")},
                {"Metric": "Reserved budget", "Value": lifecycle.get("current_reserved_usdc")},
            ]),
            hide_index=True,
            use_container_width=True,
        )
    with right:
        st.subheader("Current readiness receipt")
        st.dataframe(
            arrow_safe_dataframe([
                {"Metric": "Status", "Value": readiness.get("status")},
                {"Metric": "Target date", "Value": readiness.get("target_date")},
                {"Metric": "Generated", "Value": _timestamp(readiness.get("generated_at_utc"))},
                {"Metric": "Live capital permission", "Value": readiness.get("live_capital_permission")},
                {
                    "Metric": "Explicit approval required",
                    "Value": readiness.get("requires_explicit_operator_approval"),
                },
                {"Metric": "Blockers", "Value": readiness.get("blocker_count")},
                {"Metric": "Evidence mode", "Value": (readiness.get("summary") or {}).get("evidence_mode")},
            ]),
            hide_index=True,
            use_container_width=True,
        )

    with st.expander("Evidence provenance"):
        rows = []
        for name in (
            "run",
            "readiness",
            "platform_verification",
            "economics_snapshot",
            "economics_drift",
            "economics_accepted",
        ):
            artifact = control.get(name) or {}
            rows.append({
                "Artifact": name,
                "Available": artifact.get("available") is True,
                "Recorded": _timestamp(artifact.get("recorded_at")),
                "Path": artifact.get("path"),
            })
        host_artifact = operations.get("host_status") or {}
        rows.append({
            "Artifact": "canonical_host_digest",
            "Available": host_artifact.get("available") is True,
            "Recorded": _text(artifact_payload(host_artifact).get("ts"), "not recorded"),
            "Path": host_artifact.get("path"),
        })
        st.dataframe(arrow_safe_dataframe(rows), hide_index=True, use_container_width=True)
        st.caption(f"Automatic page refresh: {refresh_seconds} seconds. No artifact is modified by this view.")
