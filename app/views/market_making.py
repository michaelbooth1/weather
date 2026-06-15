"""Market-making run status page for the Streamlit app."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import streamlit as st


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "data" / "mm_runs"
BACKTEST_ROOT = REPO_ROOT / "data" / "backtest"


def _read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_csv(path, limit=None):
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return []
    return rows[-limit:] if limit else rows


def _read_jsonl_tail(path, limit=20):
    path = Path(path)
    if not path.exists():
        return []
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    except OSError:
        return []
    rows = []
    for line in lines[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line})
    return rows


def _run_folders(runs_root=RUNS_ROOT):
    if not runs_root.exists():
        return []
    folders = []
    for summary in runs_root.glob("*/*/run_summary.json"):
        folders.append(summary.parent)
    return sorted(folders, key=lambda folder: folder.stat().st_mtime, reverse=True)


def _latest_run():
    folders = _run_folders()
    if not folders:
        return None, {}
    folder = folders[0]
    return folder, _read_json(folder / "run_summary.json", {}) or {}


def _format_num(value, digits=2):
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _df(rows):
    return pd.DataFrame(rows or [])


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


def render_market_making_page(refresh_seconds=15):
    @st.fragment(run_every=f"{refresh_seconds}s")
    def render_live():
        st.title("Market Making")

        run_folder, run_summary = _latest_run()
        paper = _read_json(BACKTEST_ROOT / "mm_paper_report.json", {}) or {}
        known_edge = _read_json(BACKTEST_ROOT / "mm_known_edge_map.json", {}) or {}

        summary = paper.get("summary") or {}
        pnl = summary.get("pnl") or {}
        anti = summary.get("anti_overfit") or {}

        top = st.columns(5)
        top[0].metric("Latest Run", run_summary.get("run_id") or "-")
        top[1].metric("Run Mode", run_summary.get("mode") or "-")
        top[2].metric("Preflight", run_summary.get("preflight_status") or "-")
        top[3].metric("Quotes", run_summary.get("quote_permission_rows", 0))
        top[4].metric("Live Rows", run_summary.get("live_trade_permission_rows", 0))

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
                {"Metric": "Rows", "Value": run_summary.get("row_count")},
                {"Metric": "Quote rows", "Value": run_summary.get("quote_permission_rows")},
                {"Metric": "Live-trade rows", "Value": run_summary.get("live_trade_permission_rows")},
            ]
            st.dataframe(_df(run_rows), width="stretch", hide_index=True)

            reason_rows = _reason_rows(run_summary.get("reason_counts"))
            if reason_rows:
                st.subheader("Quote Reasons")
                st.dataframe(_df(reason_rows), width="stretch", hide_index=True)

        if run_folder:
            preflight = _read_json(run_folder / "preflight.json", {}) or {}
            markets = preflight.get("markets") or []
            if markets:
                st.subheader("Preflight By Market")
                visible = []
                for row in markets:
                    details = row.get("blocking_reasons") or row.get("stale_reasons") or ["ok"]
                    visible.append({
                        "Market": row.get("market_id"),
                        "Status": row.get("status"),
                        "Snapshot Rows": row.get("snapshot_rows"),
                        "Quote Rows": row.get("quote_input_rows"),
                        "Detail": "; ".join(str(item) for item in details),
                    })
                st.dataframe(_df(visible), width="stretch", hide_index=True)

            quote_rows = _read_csv(run_folder / "quote_intents_long.csv", limit=80)
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
                    "budget_action",
                    "reserved_usdc",
                    "remaining_usdc",
                    "quote_risk_usdc",
                ]
                st.dataframe(_df([{key: row.get(key) for key in ledger_cols} for row in ledger_rows]), width="stretch", hide_index=True)

        st.subheader("Paper Scoring")
        paper_rows = [
            {"Metric": "Run folders", "Value": summary.get("run_folders", 0)},
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
