"""Verifier for current taker profitability artifact fields."""

from __future__ import annotations

from pathlib import Path

from weather.io import read_csv_rows, read_json
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("taker_profitability_artifact_verification")

ORDER_FIELDS = (
    "fee_usdc",
    "pnl_fee_basis",
    "fee_pnl_usdc",
    "executable_depth_model_version",
    "executable_depth_mode",
    "executable_depth_size",
    "slippage_usdc",
    "executable_net_pnl_usdc",
    "expected_profit_after_friction_per_share",
)
STRATEGY_FIELDS = (
    "after_fee_pnl_scored",
    "after_slippage_pnl_scored",
    "live_profitability_evidence_basis",
    "market_benchmark_status",
    "market_smarter_slice_count",
    "market_benchmark_no_trade_net_pnl_usdc",
    "market_benchmark_avoided_loss_usdc",
    "market_benchmark_missed_gain_usdc",
)
BENCHMARK_FIELDS = (
    "market_smarter_slice_count",
    "no_trade_recommendation_count",
    "avoided_loss_usdc",
    "missed_gain_usdc",
)


def _present(value) -> bool:
    return value is not None and str(value).strip() != ""


def _check(code, status, detail, **extra):
    row = {"code": code, "status": status, "detail": detail}
    row.update(extra)
    return row


def _field_checks(rows, fields, *, scope):
    rows = list(rows or [])
    if not rows:
        return [_check(f"{scope}_rows_missing", "FAIL", f"No rows available for {scope}.")]
    keys = set().union(*(row.keys() for row in rows))
    checks = []
    for field in fields:
        if field not in keys:
            checks.append(_check(
                f"{scope}_{field}_missing",
                "FAIL",
                f"{scope} field {field!r} is absent.",
                field=field,
            ))
            continue
        if not any(_present(row.get(field)) for row in rows):
            checks.append(_check(
                f"{scope}_{field}_null_only",
                "FAIL",
                f"{scope} field {field!r} is present but null-only.",
                field=field,
            ))
    return checks


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_value(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _rows_with_fills(rows):
    return [
        row
        for row in rows or []
        if _int_value(row.get("filled_order_count") or row.get("order_rows")) > 0
    ]


def _bool_field_passes(rows, field):
    rows = list(rows or [])
    if not rows:
        return True
    return all(_bool_value(row.get(field)) for row in rows)


def _basis_is_after_fee(value):
    return str(value or "").strip().lower() in {
        "after_fee",
        "fees_included",
        "net_after_fee",
        "executable_after_fee_after_slippage",
    }


def _strategy_rows(payload):
    if not payload:
        return []
    return list(payload.get("by_strategy") or (payload.get("pnl") or {}).get("by_strategy") or [])


def _strategy_comparison(payload):
    payload = payload or {}
    return payload.get("strategy_comparison") or (payload.get("pnl") or {}).get("strategy_comparison") or {}


def verify_taker_profitability_artifacts(run_folder):
    run_folder = Path(run_folder)
    orders_path = run_folder / "orders_long.csv"
    daily_pnl_path = run_folder / "daily_pnl.json"
    strategy_summary_path = run_folder / "strategy_summary.json"
    settled_pnl_path = run_folder / "settled_pnl.json"
    if not any(path.exists() for path in (orders_path, daily_pnl_path, strategy_summary_path, settled_pnl_path)):
        return {
            "schema_version": SCHEMA_VERSION,
            "run_folder": str(run_folder),
            "status": "SKIP",
            "check_count": 1,
            "failed_check_count": 0,
            "checks": [
                _check(
                    "taker_profitability_artifacts_absent",
                    "SKIP",
                    "No taker profitability artifacts are present in this run folder.",
                )
            ],
        }
    orders = read_csv_rows(orders_path)
    filled_orders = [row for row in orders if str(row.get("order_status") or "").upper() == "FILLED"]
    order_scope = filled_orders or orders
    daily_pnl = read_json(daily_pnl_path, {}) or {}
    strategy_summary = read_json(strategy_summary_path, {}) or {}
    settled_pnl = read_json(settled_pnl_path, {}) or {}
    strategy_rows = _strategy_rows(daily_pnl) or _strategy_rows(strategy_summary)
    comparison = _strategy_comparison(daily_pnl) or _strategy_comparison(strategy_summary)
    benchmark_summary = comparison.get("market_benchmark_summary") or {}

    checks = []
    if not orders_path.exists():
        checks.append(_check("orders_tape_missing", "FAIL", f"Missing orders tape: {orders_path}"))
    else:
        checks.extend(_field_checks(order_scope, ORDER_FIELDS, scope="orders"))
    if not daily_pnl_path.exists() and not strategy_summary_path.exists():
        checks.append(_check(
            "strategy_summary_missing",
            "FAIL",
            "Missing daily_pnl.json and strategy_summary.json for taker run.",
        ))
    else:
        checks.extend(_field_checks(strategy_rows, STRATEGY_FIELDS, scope="strategy"))
        checks.extend(_field_checks([benchmark_summary], BENCHMARK_FIELDS, scope="market_benchmark"))

    if settled_pnl_path.exists():
        settled_summary = (settled_pnl.get("pnl") or {}).get("summary") or settled_pnl.get("summary") or {}
        settled_strategy_rows = _strategy_rows(settled_pnl)
        checks.extend(_field_checks([settled_summary], ("live_profitability_evidence_basis",), scope="finalization"))
        if not _basis_is_after_fee(settled_summary.get("live_profitability_evidence_basis")):
            checks.append(_check(
                "finalization_live_profitability_basis_not_after_fee_slippage",
                "FAIL",
                "Finalization live_profitability_evidence_basis is not executable after-fee/after-slippage.",
                value=settled_summary.get("live_profitability_evidence_basis"),
            ))
        if not _bool_field_passes([settled_summary], "after_fee_pnl_scored"):
            checks.append(_check(
                "finalization_after_fee_pnl_not_scored",
                "FAIL",
                "Finalization summary does not mark after-fee PnL as scored.",
            ))
        if not _bool_field_passes([settled_summary], "after_slippage_pnl_scored"):
            checks.append(_check(
                "finalization_after_slippage_pnl_not_scored",
                "FAIL",
                "Finalization summary does not mark after-slippage PnL as scored.",
            ))
        settled_strategy_rows = _rows_with_fills(settled_strategy_rows)
        if not _bool_field_passes(settled_strategy_rows, "after_fee_pnl_scored"):
            checks.append(_check(
                "finalization_strategy_after_fee_pnl_not_scored",
                "FAIL",
                "At least one finalization strategy row lacks after-fee scoring.",
            ))
        if not _bool_field_passes(settled_strategy_rows, "after_slippage_pnl_scored"):
            checks.append(_check(
                "finalization_strategy_after_slippage_pnl_not_scored",
                "FAIL",
                "At least one finalization strategy row lacks after-slippage scoring.",
            ))
    else:
        checks.append(_check(
            "finalization_payload_absent",
            "SKIP",
            "No settled_pnl.json is present; finalization-specific checks were skipped.",
        ))

    failed = [row for row in checks if row.get("status") == "FAIL"]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_folder": str(run_folder),
        "orders_path": str(orders_path),
        "daily_pnl_path": str(daily_pnl_path),
        "strategy_summary_path": str(strategy_summary_path),
        "settled_pnl_path": str(settled_pnl_path),
        "status": "BLOCK" if failed else "PASS",
        "check_count": len(checks),
        "failed_check_count": len(failed),
        "checks": checks,
    }


def latest_taker_run_folder(runs_root):
    roots = []
    for path in Path(runs_root).glob("*/*/run_summary.json"):
        try:
            roots.append((path.stat().st_mtime, path.parent))
        except OSError:
            continue
    if not roots:
        return None
    return max(roots, key=lambda row: row[0])[1]


def verify_latest_taker_profitability_artifacts(runs_root):
    run_folder = latest_taker_run_folder(runs_root)
    if run_folder is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_folder": None,
            "status": "SKIP",
            "check_count": 0,
            "failed_check_count": 0,
            "checks": [],
        }
    return verify_taker_profitability_artifacts(run_folder)
