"""Market-making run status page for the Streamlit app."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st

from weather.reporting.market_making_dashboard import (
    BACKTEST_ROOT,
    read_csv as _read_csv,
    read_json as _read_json,
    read_jsonl as _read_jsonl,
    read_jsonl_tail as _read_jsonl_tail,
    run_folders as _run_folders,
)


def _run_label(folder):
    folder = Path(folder)
    return f"{folder.parent.name} / {folder.name}"


def _select_run_folder(folders):
    if not folders:
        return None
    labels = [_run_label(folder) for folder in folders]
    selected = st.selectbox("Run", labels, index=0)
    return folders[labels.index(selected)]


def _format_num(value, digits=2):
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _df(rows):
    normalized = []
    for row in rows or []:
        item = dict(row)
        if "Value" in item:
            item["Value"] = "-" if item["Value"] in (None, "") else str(item["Value"])
        normalized.append(item)
    return pd.DataFrame(normalized)


def _reason_rows(reason_counts):
    return [
        {"Reason": key or "-", "Rows": value}
        for key, value in sorted((reason_counts or {}).items(), key=lambda item: str(item[0]))
    ]


def _permission_rows(permission_counts):
    return [
        {"Permission": key or "-", "Records": value}
        for key, value in sorted((permission_counts or {}).items(), key=lambda item: str(item[0]))
    ]


def _latest_tick_rows(rows):
    if not rows:
        return []
    latest = max(str(row.get("generated_at_utc") or "") for row in rows)
    return [row for row in rows if str(row.get("generated_at_utc") or "") == latest]


def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _open_lifecycle_orders(rows):
    state = {}
    for row in rows:
        key = row.get("lifecycle_key")
        if not key:
            continue
        transition = row.get("transition") or row.get("event")
        if transition in {"paper_posted", "live_posted"}:
            state[key] = row
        elif transition == "filled" and key in state:
            remaining = max(0.0, _float(state[key].get("remaining_size") or state[key].get("size")) - _float(row.get("fill_size")))
            if remaining <= 1e-9:
                state.pop(key, None)
            else:
                state[key]["remaining_size"] = remaining
        elif transition in {"released", "replaced", "canceled", "expired", "blocked_by_preflight"}:
            state.pop(key, None)
    return state


def _market_health_rows(markets, quote_rows, lifecycle_rows, remediation):
    latest = _latest_tick_rows(quote_rows)
    quote_counts = Counter(row.get("market_id") for row in latest if _truthy(row.get("quote_permission")))
    permission_by_market = {}
    freshness_by_market = {}
    event_gate_by_market = {}
    next_event_by_market = {}
    for row in latest:
        market_id = row.get("market_id")
        if market_id and market_id not in permission_by_market:
            permission_by_market[market_id] = row.get("known_edge_permission") or "-"
            freshness_by_market[market_id] = row.get("source_freshness_state") or "-"
            event_gate_by_market[market_id] = row.get("event_gate_status") or "-"
            next_event_by_market[market_id] = row.get("event_gate_next_event_at_utc") or "-"
    open_orders = _open_lifecycle_orders(lifecycle_rows)
    reservation_counts = Counter(row.get("market_id") for row in open_orders.values())
    reserved_by_market = Counter()
    for row in open_orders.values():
        reserved_by_market[row.get("market_id") or "-"] += _float(row.get("remaining_risk_usdc") or row.get("open_risk_usdc"))
    incidents_by_market = defaultdict(list)
    for incident in (remediation or {}).get("incidents") or []:
        incidents_by_market[incident.get("market_id")].append(incident)
    rows = []
    for market in markets or []:
        audit = market.get("book_audit") or {}
        incidents = incidents_by_market.get(market.get("market_id")) or []
        top = incidents[0] if incidents else {}
        gates = {gate.get("name"): gate for gate in market.get("gates") or []}
        rows.append({
            "Market": market.get("market_id"),
            "Status": market.get("status"),
            "Source rows": market.get("source_status_rows"),
            "Source state": freshness_by_market.get(market.get("market_id"), "-"),
            "Model age s": market.get("model_age_seconds"),
            "CLOB age s": audit.get("trailing_age_seconds"),
            "CLOB gaps": audit.get("gaps_over_threshold"),
            "Watcher": "fresh" if (gates.get("observation_trigger") or {}).get("ok") else "-",
            "Promotion": market.get("promotion_state"),
            "Known edge": permission_by_market.get(market.get("market_id"), "-"),
            "Event gate": event_gate_by_market.get(market.get("market_id"), "-"),
            "Next event": next_event_by_market.get(market.get("market_id"), "-"),
            "Quotes": quote_counts.get(market.get("market_id"), 0),
            "Open orders": reservation_counts.get(market.get("market_id"), 0),
            "Reserved USDC": round(reserved_by_market.get(market.get("market_id"), 0.0), 4),
            "Top blocker": top.get("root_cause") or "; ".join(str(item) for item in (market.get("blocking_reasons") or market.get("stale_reasons") or ["ok"])),
        })
    return rows


def _blocker_rows(quote_rows, remediation):
    latest = _latest_tick_rows(quote_rows)
    incidents = defaultdict(list)
    for incident in (remediation or {}).get("incidents") or []:
        incidents[incident.get("market_id")].append(incident)
    grouped = {}
    for row in latest:
        reason = row.get("reason_code") or "-"
        if not reason.startswith("NO_QUOTE"):
            continue
        market_id = row.get("market_id") or "-"
        incident = (incidents.get(market_id) or [{}])[0]
        key = (market_id, reason, incident.get("root_cause") or "-")
        item = grouped.setdefault(key, {
            "Market": market_id,
            "Reason": reason,
            "Root cause": incident.get("root_cause") or "-",
            "Owner": incident.get("owner") or "-",
            "Rows": 0,
            "First seen": row.get("generated_at_utc"),
            "Last seen": row.get("generated_at_utc"),
            "Recoverable today": incident.get("recoverable_same_day", "-"),
            "Command": incident.get("suggested_command") or "-",
        })
        item["Rows"] += 1
        item["First seen"] = min(str(item["First seen"] or ""), str(row.get("generated_at_utc") or ""))
        item["Last seen"] = max(str(item["Last seen"] or ""), str(row.get("generated_at_utc") or ""))
    return sorted(grouped.values(), key=lambda row: (-row["Rows"], row["Market"], row["Reason"]))


def _budget_lifecycle_rows(run_summary):
    lifecycle = (run_summary or {}).get("order_lifecycle") or {}
    semantics = lifecycle.get("platform_balance_semantics") or {}
    return [
        {"Metric": "Current open quote risk", "Value": _format_num(lifecycle.get("current_reserved_usdc"), 4)},
        {"Metric": "Open orders", "Value": lifecycle.get("current_open_order_count", 0)},
        {"Metric": "Released this tick", "Value": _format_num(lifecycle.get("released_this_tick_usdc"), 4)},
        {"Metric": "Posted this tick", "Value": lifecycle.get("posted_this_tick_count", 0)},
        {"Metric": "Stale open orders", "Value": lifecycle.get("stale_open_order_count", 0)},
        {"Metric": "Run budget is binding", "Value": semantics.get("operator_run_budget_is_binding")},
        {"Metric": "Cross-market gross can exceed wallet", "Value": semantics.get("polymarket_cross_market_open_orders_may_exceed_wallet_balance")},
    ]


def _gate_progress_rows(run_summary, paper):
    summary = (paper or {}).get("summary") or {}
    anti = summary.get("anti_overfit") or {}
    remediation = (run_summary or {}).get("preflight_remediation") or {}
    days = anti.get("live_forward_days") or []
    return [
        {"Metric": "Current run counts", "Value": remediation.get("counts_toward_live_forward_gate", False)},
        {"Metric": "Current blocker incidents", "Value": remediation.get("incident_count", 0)},
        {"Metric": "Locked paper days", "Value": len(days)},
        {"Metric": "Paper gate", "Value": summary.get("gate_status") or "-"},
        {"Metric": "Next live gate", "Value": "item 45 live-pilot readiness"},
    ]


def _event_gate_rows(run_summary, paper=None):
    gate = (run_summary or {}).get("information_event_gate") or ((run_summary or {}).get("latest_tick") or {}).get("information_event_gate") or {}
    score = (((paper or {}).get("summary") or {}).get("event_gate_score") or {})
    rows = [
        {"Kind": "Metric", "Market": "-", "Event": "Pull rows", "Class": "-", "Action": "-", "Starts": "-", "Ends": str(gate.get("pull_rows", 0))},
        {"Kind": "Metric", "Market": "-", "Event": "Widen rows", "Class": "-", "Action": "-", "Starts": "-", "Ends": str(gate.get("widen_rows", 0))},
        {"Kind": "Metric", "Market": "-", "Event": "Exception rows", "Class": "-", "Action": "-", "Starts": "-", "Ends": str(gate.get("exception_rows", 0))},
    ]
    if score:
        rows.append({
            "Kind": "Metric",
            "Market": "-",
            "Event": "Narrowing gate",
            "Class": "-",
            "Action": "-",
            "Starts": "-",
            "Ends": score.get("narrowing_gate") or "-",
        })
    for event in gate.get("active_events") or []:
        rows.append({
            "Kind": "Active",
            "Market": event.get("market_id") or "-",
            "Event": event.get("event_id") or "-",
            "Class": event.get("event_class") or "-",
            "Action": event.get("action") or "-",
            "Starts": event.get("starts_at_utc") or "-",
            "Ends": event.get("ends_at_utc") or "-",
        })
    for event in gate.get("next_events") or []:
        rows.append({
            "Kind": "Next",
            "Market": event.get("market_id") or "-",
            "Event": event.get("event_id") or "-",
            "Class": event.get("event_class") or "-",
            "Action": "-",
            "Starts": event.get("starts_at_utc") or "-",
            "Ends": "-",
        })
    return rows


def _runtime_identity_rows(identity):
    rows = []
    for row in (identity or {}).get("loops") or []:
        rows.append({
            "Loop": row.get("name"),
            "Code state": row.get("runtime_code_state") or "-",
            "PID": row.get("pid") or "-",
            "Errors": row.get("consecutive_errors") if row.get("consecutive_errors") is not None else "-",
            "Last heartbeat": row.get("last_heartbeat") or "-",
            "Running code": row.get("process_identity_text") or "-",
            "Current code": row.get("current_identity_text") or "-",
            "Status file": row.get("status_path") or "-",
        })
    return rows


def render_market_making_page(refresh_seconds=15):
    @st.fragment(run_every=f"{refresh_seconds}s")
    def render_live():
        st.title("Market Making")

        folders = _run_folders()
        run_folder = _select_run_folder(folders)
        run_summary = _read_json(run_folder / "run_summary.json", {}) if run_folder else {}
        paper = _read_json(BACKTEST_ROOT / "mm_paper_report.json", {}) or {}
        known_edge = _read_json(BACKTEST_ROOT / "mm_known_edge_map.json", {}) or {}

        summary = paper.get("summary") or {}
        pnl = summary.get("pnl") or {}
        anti = summary.get("anti_overfit") or {}

        st.caption("Selected run: " + (_run_label(run_folder) if run_folder else "-"))

        st.subheader("Latest Tick")
        top = st.columns(6)
        top[0].metric("Latest Run", run_summary.get("run_id") or "-")
        top[1].metric("Run Mode", run_summary.get("mode") or "-")
        top[2].metric("Preflight", run_summary.get("preflight_status") or "-")
        top[3].metric("Latest Tick Quotes", run_summary.get("quote_permission_rows", 0))
        top[4].metric("Cumulative Quotes", run_summary.get("cumulative_quote_permission_rows", run_summary.get("quote_permission_rows", 0)))
        top[5].metric("Live Rows", run_summary.get("live_trade_permission_rows", 0))

        st.subheader("Paper Corpus")
        score = st.columns(5)
        score[0].metric("Paper Runs", summary.get("run_folders", 0))
        score[1].metric("Quote Rows", summary.get("quote_rows", 0))
        score[2].metric("Fills", summary.get("conservative_fills", 0))
        score[3].metric("Net USDC", _format_num(pnl.get("net_pnl_after_fees_incentives_usdc"), 4))
        score[4].metric("Gate", summary.get("gate_status") or "-")

        if run_folder:
            st.caption(f"Latest run folder: {run_folder}")
        else:
            st.info("No market-making run folders found yet.")

        if run_summary:
            st.subheader("Latest Run Summary")
            run_rows = [
                {"Metric": "Target date", "Value": run_summary.get("target_date")},
                {"Metric": "Budget USDC", "Value": _format_num(run_summary.get("budget_usdc"), 2)},
                {"Metric": "Reserved USDC", "Value": _format_num(run_summary.get("budget_reserved_usdc"), 2)},
                {"Metric": "Released USDC", "Value": _format_num(run_summary.get("budget_released_usdc"), 2)},
                {"Metric": "Open orders", "Value": run_summary.get("open_order_count")},
                {"Metric": "Latest tick rows", "Value": run_summary.get("row_count")},
                {"Metric": "Latest tick quote rows", "Value": run_summary.get("quote_permission_rows")},
                {"Metric": "Latest tick live-trade rows", "Value": run_summary.get("live_trade_permission_rows")},
                {"Metric": "Cumulative ticks", "Value": run_summary.get("cumulative_tick_count")},
                {"Metric": "Cumulative rows", "Value": run_summary.get("cumulative_row_count")},
                {"Metric": "Cumulative quote rows", "Value": run_summary.get("cumulative_quote_permission_rows")},
                {"Metric": "Cumulative paper-posted legs", "Value": run_summary.get("cumulative_paper_posted_count")},
            ]
            st.dataframe(_df(run_rows), width="stretch", hide_index=True)

            reason_rows = _reason_rows(run_summary.get("reason_counts"))
            if reason_rows:
                st.subheader("Quote Reasons")
                st.dataframe(_df(reason_rows), width="stretch", hide_index=True)
            event_gate_rows = _event_gate_rows(run_summary, paper)
            if event_gate_rows:
                st.subheader("Information Event Gate")
                st.dataframe(_df(event_gate_rows), width="stretch", hide_index=True)

        if run_folder:
            preflight = _read_json(run_folder / "preflight.json", {}) or {}
            remediation = _read_json(run_folder / "preflight_remediation.json", {}) or {}
            identity = (preflight.get("runtime_identity") or run_summary.get("runtime_identity") or {})
            lifecycle_rows = _read_jsonl(run_folder / "order_lifecycle.jsonl")
            quote_rows_all = _read_csv(run_folder / "quote_intents_long.csv")
            markets = preflight.get("markets") or []
            runtime_rows = _runtime_identity_rows(identity)
            if runtime_rows:
                st.subheader("Runtime Identity")
                st.dataframe(_df(runtime_rows), width="stretch", hide_index=True)
            if markets:
                st.subheader("Market Health")
                st.dataframe(_df(_market_health_rows(markets, quote_rows_all, lifecycle_rows, remediation)), width="stretch", hide_index=True)

            blocker_rows = _blocker_rows(quote_rows_all, remediation)
            if blocker_rows:
                st.subheader("Blocker Drilldown")
                st.dataframe(_df(blocker_rows), width="stretch", hide_index=True)

            quote_rows = quote_rows_all[-80:]
            if quote_rows:
                st.subheader("Recent Quote Intents")
                cols = [
                    "generated_at_utc",
                    "market_id",
                    "range_label",
                    "action",
                    "regime",
                    "reason_code",
                    "known_edge_permission",
                    "known_edge_reason",
                    "event_gate_status",
                    "event_gate_reason_code",
                    "event_gate_next_event_at_utc",
                    "source_freshness_state",
                    "budget_reserved_usdc",
                ]
                st.dataframe(_df([{key: row.get(key) for key in cols} for row in quote_rows]), width="stretch", hide_index=True)

            ledger_rows = _read_jsonl_tail(run_folder / "budget_ledger.jsonl", limit=30)
            if ledger_rows:
                st.subheader("Budget Ledger")
                ledger_cols = [
                    "generated_at_utc",
                    "market_id",
                    "range_label",
                    "event",
                    "budget_action",
                    "reserved_usdc",
                    "remaining_usdc",
                    "released_risk_usdc",
                    "quote_risk_usdc",
                ]
                st.dataframe(_df([{key: row.get(key) for key in ledger_cols} for row in ledger_rows]), width="stretch", hide_index=True)

            st.subheader("Budget Lifecycle")
            st.dataframe(_df(_budget_lifecycle_rows(run_summary)), width="stretch", hide_index=True)

            st.subheader("Live-Forward Gate")
            st.dataframe(_df(_gate_progress_rows(run_summary, paper)), width="stretch", hide_index=True)

        st.subheader("Paper Scoring")
        paper_rows = [
            {"Metric": "Candidate run folders", "Value": summary.get("candidate_run_folders", summary.get("run_folders", 0))},
            {"Metric": "Run folders", "Value": summary.get("run_folders", 0)},
            {"Metric": "Excluded run folders", "Value": summary.get("excluded_run_folders", 0)},
            {"Metric": "Quote rows", "Value": summary.get("quote_rows", 0)},
            {"Metric": "Quote legs", "Value": summary.get("quote_legs", 0)},
            {"Metric": "Conservative fills", "Value": summary.get("conservative_fills", 0)},
            {"Metric": "Queue-estimated legs", "Value": summary.get("queue_estimated_fill_legs", 0)},
            {"Metric": "Live-forward days", "Value": ", ".join(anti.get("live_forward_days") or []) or "-"},
            {"Metric": "Locked policy params", "Value": anti.get("locked_policy_params")},
        ]
        st.dataframe(_df(paper_rows), width="stretch", hide_index=True)

        markout_rows = paper.get("markout_slices") or []
        if markout_rows:
            st.subheader("Markout Slices")
            st.dataframe(_df(markout_rows[:60]), width="stretch", hide_index=True)

        st.subheader("Known-Edge Map")
        known_summary = known_edge.get("summary") or {}
        known_cols = st.columns(4)
        known_cols[0].metric("Records", known_summary.get("record_count", 0))
        known_cols[1].metric("Gap Cells", known_summary.get("active_model_gap_cell_count", 0))
        known_cols[2].metric("Paper Fills", known_summary.get("paper_fill_count", 0))
        known_cols[3].metric("Schema", known_edge.get("schema_version") or "-")

        permissions = _permission_rows(known_summary.get("permission_counts"))
        if permissions:
            st.dataframe(_df(permissions), width="stretch", hide_index=True)

        source_records = []
        for record in known_edge.get("records") or []:
            evidence = record.get("source_freshness_evidence") or {}
            if not evidence:
                continue
            source_records.append({
                "Freshness State": record.get("source_freshness_state"),
                "Rows": evidence.get("n"),
                "Candidate Brier": evidence.get("candidate_brier"),
                "Market Brier": evidence.get("market_brier"),
                "Delta Current": evidence.get("delta_vs_current"),
                "Delta Market": evidence.get("delta_vs_market"),
                "Permission": record.get("permission"),
                "Reason": record.get("reason"),
            })
        if source_records:
            st.subheader("Source-Freshness Gap Cells")
            st.dataframe(_df(source_records), width="stretch", hide_index=True)

    render_live()
    st.stop()
