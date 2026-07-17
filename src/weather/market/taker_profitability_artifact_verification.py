"""Verifier for current taker profitability artifact fields."""

from __future__ import annotations

from pathlib import Path

from weather.io import (
    iter_csv_rows,
    read_json,
    read_pretty_json_top_level_values,
)
from weather.market.taker_bot_artifact_projection import (
    DEFAULT_PROJECTION_MAX_BYTES,
    load_settled_finalization_projection,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("taker_profitability_artifact_verification")

ORDER_OPPORTUNITY_FIELDS = (
    "fee_usdc",
    "pnl_fee_basis",
    "executable_depth_model_version",
    "executable_depth_mode",
    "executable_depth_size",
    "expected_profit_after_friction_per_share",
)
FILLED_ORDER_FIELDS = (
    "fee_pnl_usdc",
    "slippage_usdc",
    "executable_net_pnl_usdc",
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
EXCHANGE_ECONOMICS_FIELDS = (
    "exchange_economics_snapshot_id",
    "exchange_economics_hash",
    "exchange_economics_evidence_basis",
)


def _read_small_json(path):
    path = Path(path)
    try:
        if path.stat().st_size > DEFAULT_PROJECTION_MAX_BYTES:
            return {}
    except OSError:
        return {}
    return read_json(path, {}) or {}


def _small_enough_to_materialize(path):
    try:
        return Path(path).stat().st_size <= DEFAULT_PROJECTION_MAX_BYTES
    except OSError:
        return False


def _current_strategy_summary_for_large_daily(
    strategy_summary_path,
    daily_pnl_path,
):
    """Return a compact summary only when it is newer and identity-aligned."""

    if not _small_enough_to_materialize(strategy_summary_path):
        return {}
    summary = _read_small_json(strategy_summary_path)
    try:
        summary_stat = Path(strategy_summary_path).stat()
        daily_stat = Path(daily_pnl_path).stat()
    except OSError:
        return {}
    if summary_stat.st_mtime_ns < daily_stat.st_mtime_ns:
        return {}
    daily_identity = read_pretty_json_top_level_values(
        daily_pnl_path,
        ("run_id", "target_date"),
    )
    if not all(
        summary.get(field) not in (None, "")
        and str(summary.get(field)) == str(daily_identity.get(field))
        for field in ("run_id", "target_date")
    ):
        return {}
    if summary.get("schema_version") != schema_version("taker_strategy_report"):
        return {}
    return summary


def _present(value) -> bool:
    return value is not None and str(value).strip() != ""


def _check(code, status, detail, **extra):
    row = {"code": code, "status": status, "detail": detail}
    row.update(extra)
    return row


class _FieldPresence:
    """Fixed field-presence state for a streamed row population."""

    def __init__(self, fields):
        self.fields = tuple(fields)
        self.row_count = 0
        self.key_seen = {field: False for field in self.fields}
        self.value_seen = {field: False for field in self.fields}

    def add(self, row):
        self.row_count += 1
        for field in self.fields:
            if field in row:
                self.key_seen[field] = True
                if _present(row.get(field)):
                    self.value_seen[field] = True


def _field_checks_from_presence(presence, *, scope):
    if not presence.row_count:
        return [_check(f"{scope}_rows_missing", "FAIL", f"No rows available for {scope}.")]
    checks = []
    for field in presence.fields:
        if not presence.key_seen[field]:
            checks.append(_check(
                f"{scope}_{field}_missing",
                "FAIL",
                f"{scope} field {field!r} is absent.",
                field=field,
            ))
            continue
        if not presence.value_seen[field]:
            checks.append(_check(
                f"{scope}_{field}_null_only",
                "FAIL",
                f"{scope} field {field!r} is present but null-only.",
                field=field,
            ))
    return checks


def _field_checks(rows, fields, *, scope):
    presence = _FieldPresence(fields)
    for row in rows or []:
        presence.add(row)
    return _field_checks_from_presence(presence, scope=scope)


def _streamed_order_presence(path):
    fields = tuple(dict.fromkeys(
        ORDER_OPPORTUNITY_FIELDS + FILLED_ORDER_FIELDS + EXCHANGE_ECONOMICS_FIELDS
    ))
    all_orders = _FieldPresence(fields)
    filled_orders = _FieldPresence(fields)
    for row in iter_csv_rows(path):
        all_orders.add(row)
        if str(row.get("order_status") or "").upper() == "FILLED":
            filled_orders.add(row)
    return all_orders, filled_orders


def _presence_subset(presence, fields):
    subset = _FieldPresence(fields)
    subset.row_count = presence.row_count
    for field in subset.fields:
        subset.key_seen[field] = presence.key_seen.get(field, False)
        subset.value_seen[field] = presence.value_seen.get(field, False)
    return subset


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
    return list(
        payload.get("by_strategy")
        or (payload.get("pnl") or {}).get("by_strategy")
        or payload.get("strategies")
        or []
    )


def _strategy_comparison(payload):
    payload = payload or {}
    return (
        payload.get("strategy_comparison")
        or (payload.get("pnl") or {}).get("strategy_comparison")
        or payload.get("comparison")
        or {}
    )


def _settled_summary_from_strategy_payload(payload):
    """Recover finalization-wide checks from the compact settled strategy artifact."""

    payload = payload or {}
    summary = dict(payload.get("summary") or {})
    strategy_rows = _strategy_rows(payload)
    filled_rows = [
        row for row in strategy_rows
        if _int_value(row.get("filled_order_count")) > 0
    ]
    after_fee = bool(filled_rows) and _bool_field_passes(
        filled_rows,
        "after_fee_pnl_scored",
    )
    after_slippage = bool(filled_rows) and _bool_field_passes(
        filled_rows,
        "after_slippage_pnl_scored",
    )
    summary.setdefault("filled_order_count", sum(
        _int_value(row.get("filled_order_count")) for row in strategy_rows
    ))
    summary.setdefault("after_fee_pnl_scored", after_fee)
    summary.setdefault("after_slippage_pnl_scored", after_slippage)
    summary.setdefault(
        "live_profitability_evidence_basis",
        "executable_after_fee_after_slippage" if after_fee else "paper_no_fee",
    )
    gate = payload.get("exchange_economics_gate") or {}
    exchange_values = {
        "exchange_economics_snapshot_id": gate.get("snapshot_id"),
        "exchange_economics_hash": (
            gate.get("snapshot_hash") or gate.get("exchange_economics_hash")
        ),
        "exchange_economics_evidence_basis": gate.get("evidence_basis"),
    }
    for field in EXCHANGE_ECONOMICS_FIELDS:
        summary.setdefault(field, payload.get(field) or exchange_values.get(field))
    return summary


def _exchange_gate_from_payloads(*payloads):
    for payload in payloads:
        payload = payload or {}
        gate = payload.get("exchange_economics_gate")
        if gate:
            return gate
        summary = payload.get("summary") or {}
        snapshot_id = (
            payload.get("exchange_economics_snapshot_id")
            or summary.get("exchange_economics_snapshot_id")
        )
        economics_hash = (
            payload.get("exchange_economics_hash")
            or summary.get("exchange_economics_hash")
        )
        status = (
            payload.get("exchange_economics_status")
            or summary.get("exchange_economics_gate_status")
        )
        if snapshot_id or economics_hash or status:
            return {
                "status": status or "PASS",
                "ok": status in {None, "", "PASS"},
                "snapshot_id": snapshot_id,
                "snapshot_hash": economics_hash,
                "reason": summary.get("exchange_economics_gate_reason"),
            }
    return {}


def verify_taker_profitability_artifacts(run_folder, exchange_economics_gate=None):
    run_folder = Path(run_folder)
    orders_path = run_folder / "orders_long.csv"
    run_config_path = run_folder / "run_config.json"
    daily_pnl_path = run_folder / "daily_pnl.json"
    strategy_summary_path = run_folder / "strategy_summary.json"
    settled_pnl_path = run_folder / "settled_pnl.json"
    if not any(path.exists() for path in (
        orders_path,
        daily_pnl_path,
        strategy_summary_path,
        settled_pnl_path,
    )):
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
    run_config = _read_small_json(run_config_path)
    daily_payload = {}
    strategy_summary_payload = {}
    if daily_pnl_path.exists() and _small_enough_to_materialize(daily_pnl_path):
        daily_payload = _read_small_json(daily_pnl_path)
        strategy_summary_payload = _read_small_json(strategy_summary_path)
    elif daily_pnl_path.exists():
        strategy_summary_payload = _current_strategy_summary_for_large_daily(
            strategy_summary_path,
            daily_pnl_path,
        )
    else:
        strategy_summary_payload = _read_small_json(strategy_summary_path)
    settled_payload = (
        load_settled_finalization_projection(settled_pnl_path)
        if settled_pnl_path.exists()
        else None
    )
    if settled_payload is not None:
        settled_summary = _settled_summary_from_strategy_payload(settled_payload)
    else:
        settled_payload = _read_small_json(settled_pnl_path)
        settled_summary = (
            (settled_payload.get("pnl") or {}).get("summary")
            or settled_payload.get("summary")
            or {}
        )
    strategy_rows = _strategy_rows(daily_payload) or _strategy_rows(
        strategy_summary_payload
    )
    comparison = _strategy_comparison(daily_payload) or _strategy_comparison(
        strategy_summary_payload
    )
    benchmark_summary = comparison.get("market_benchmark_summary") or {}

    checks = []
    exchange_gate = exchange_economics_gate or _exchange_gate_from_payloads(
        run_config,
        daily_payload,
        strategy_summary_payload,
        settled_payload,
    )
    gate_status = str(exchange_gate.get("status") or "").upper()
    exchange_required = exchange_gate.get("required") is not False
    if not exchange_gate:
        checks.append(_check(
            "exchange_economics_gate_missing",
            "FAIL",
            "Taker profitability artifacts do not cite an exchange-economics gate.",
        ))
    elif not exchange_required:
        checks.append(_check(
            "exchange_economics_gate_not_required",
            "SKIP",
            "Exchange-economics gate was not required for this non-production artifact root.",
        ))
    elif gate_status == "BLOCK" or exchange_gate.get("ok") is False:
        checks.append(_check(
            "exchange_economics_gate_blocked",
            "FAIL",
            exchange_gate.get("reason") or "Exchange-economics gate is not current.",
            exchange_economics_snapshot_id=exchange_gate.get("snapshot_id"),
            exchange_economics_hash=exchange_gate.get("snapshot_hash"),
        ))
    elif not (exchange_gate.get("snapshot_id") and (exchange_gate.get("snapshot_hash") or exchange_gate.get("exchange_economics_hash"))):
        checks.append(_check(
            "exchange_economics_snapshot_identity_missing",
            "FAIL",
            "Exchange-economics gate does not include snapshot id and hash.",
        ))
    if not orders_path.exists():
        checks.append(_check("orders_tape_missing", "FAIL", f"Missing orders tape: {orders_path}"))
    else:
        all_orders, filled_orders = _streamed_order_presence(orders_path)
        order_scope = filled_orders if filled_orders.row_count else all_orders
        checks.extend(_field_checks_from_presence(
            _presence_subset(order_scope, ORDER_OPPORTUNITY_FIELDS),
            scope="orders",
        ))
        if exchange_required:
            checks.extend(_field_checks_from_presence(
                _presence_subset(order_scope, EXCHANGE_ECONOMICS_FIELDS),
                scope="orders_exchange_economics",
            ))
        if filled_orders.row_count:
            checks.extend(_field_checks_from_presence(
                _presence_subset(filled_orders, FILLED_ORDER_FIELDS),
                scope="orders",
            ))
        else:
            checks.append(_check(
                "orders_realized_profitability_fields_skipped_no_fills",
                "SKIP",
                "No filled orders are present; realized fee/slippage/net-P&L fields are not required.",
            ))
    if not daily_pnl_path.exists() and not strategy_summary_path.exists():
        checks.append(_check(
            "strategy_summary_missing",
            "FAIL",
            "Missing daily_pnl.json and strategy_summary.json for taker run.",
        ))
    else:
        checks.extend(_field_checks(strategy_rows, STRATEGY_FIELDS, scope="strategy"))
        if exchange_required:
            checks.extend(_field_checks(strategy_rows, EXCHANGE_ECONOMICS_FIELDS, scope="strategy_exchange_economics"))
        checks.extend(_field_checks([benchmark_summary], BENCHMARK_FIELDS, scope="market_benchmark"))

    if settled_pnl_path.exists():
        settled_strategy_rows = _strategy_rows(settled_payload)
        checks.extend(_field_checks([settled_summary], ("live_profitability_evidence_basis",), scope="finalization"))
        if exchange_required:
            checks.extend(_field_checks([settled_summary], EXCHANGE_ECONOMICS_FIELDS, scope="finalization_exchange_economics"))
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
        "run_config_path": str(run_config_path),
        "daily_pnl_path": str(daily_pnl_path),
        "strategy_summary_path": str(strategy_summary_path),
        "settled_pnl_path": str(settled_pnl_path),
        "status": "BLOCK" if failed else "PASS",
        "exchange_economics_gate": exchange_gate,
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
