"""Read-only captured public inputs shared by paper and live preflight."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from weather.io import read_csv_rows as io_read_csv_rows
from weather.collection.collection_health import source_family_degradation
from weather.market.market_microstructure import (BOOK_AUDIT_STARTUP_GRACE_SECONDS, SNAPSHOT_DATA_ROOT, audit_book_tape, fleet_effective_book_gap_seconds, parse_utc_datetime, read_clob_loop_status)
from weather.market.value_helpers import bool_value, first_present, maybe_float, parse_time
from weather.time import utc_now

def read_csv_rows(path):
    return io_read_csv_rows(path, attach_diagnostics=True)


def latest_rows_for_snapshot(rows, snapshot_id):
    if not rows:
        return []
    if snapshot_id:
        return [row for row in rows if row.get("snapshot_id") == snapshot_id]
    latest = max(
        rows,
        key=lambda row: parse_time(row.get("captured_at_utc")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    return [row for row in rows if row.get("snapshot_id") == latest.get("snapshot_id")]


def latest_book_rows(folder, outcomes=None):
    allowed_outcomes = {str(value).lower() for value in (outcomes or {"yes", ""})}
    rows = [
        row
        for row in read_csv_rows(Path(folder) / "order_books_summary.csv")
        if str(row.get("outcome") or "").lower() in allowed_outcomes
    ]
    if not rows:
        return []
    latest_time = max(parse_time(row.get("captured_at_utc")) or datetime.min.replace(tzinfo=timezone.utc) for row in rows)
    return [
        row for row in rows
        if (parse_time(row.get("captured_at_utc")) or datetime.min.replace(tzinfo=timezone.utc)) == latest_time
    ]


def source_status_for_snapshot(folder, snapshot_id):
    return latest_rows_for_snapshot(read_csv_rows(Path(folder) / "source_status_long.csv"), snapshot_id)


def market_harvest_clob_feature_rows(book_rows, *, now=None):
    """Project current book rows into model-independent harvest features.

    The ordinary feature builder is anchored to model snapshot rows. The
    market-harvest profile deliberately has no model-row dependency, so its
    current midpoint, spread, depth, and freshness projection must come
    directly from the latest public book capture instead.
    """

    current = utc_now(now)
    rows = []
    for book in book_rows or []:
        captured = parse_time(
            first_present(book, "book_time_utc", "captured_at_utc")
        )
        bid_depth_1pct = maybe_float(book.get("bid_depth_1pct"))
        ask_depth_1pct = maybe_float(book.get("ask_depth_1pct"))
        bid_depth_5pct = maybe_float(book.get("bid_depth_5pct"))
        ask_depth_5pct = maybe_float(book.get("ask_depth_5pct"))
        bid_depth_all = maybe_float(book.get("bid_depth_all"))
        ask_depth_all = maybe_float(book.get("ask_depth_all"))

        def total(left, right):
            if left is None and right is None:
                return None
            return (left or 0.0) + (right or 0.0)

        row = dict(book)
        row.update({
            "snapshot_id": book.get("capture_id"),
            "clob_token_id": book.get("clob_token_id"),
            "clob_feature_available": 1.0,
            "clob_book_captured_at_utc": (
                captured.isoformat() if captured is not None else ""
            ),
            "clob_book_age_seconds": (
                (current - captured).total_seconds()
                if captured is not None
                else None
            ),
            "clob_midpoint": maybe_float(book.get("midpoint")),
            "clob_spread": maybe_float(book.get("spread")),
            "clob_best_bid": maybe_float(book.get("best_bid")),
            "clob_best_ask": maybe_float(book.get("best_ask")),
            "clob_depth_1pct_total": total(bid_depth_1pct, ask_depth_1pct),
            "clob_depth_5pct_total": total(bid_depth_5pct, ask_depth_5pct),
            "clob_depth_all_total": total(bid_depth_all, ask_depth_all),
            "clob_imbalance_1pct": maybe_float(book.get("imbalance_1pct")),
            "clob_imbalance_5pct": maybe_float(book.get("imbalance_5pct")),
        })
        rows.append(row)
    return rows


def boolish_active(value):
    if value in (None, ""):
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"active", "open", "1", "true", "yes"}:
        return True
    if text in {"closed", "inactive", "0", "false", "no"}:
        return False
    return True


def clob_token_discovery_health(token_rows):
    rows = list(token_rows or [])
    yes_rows = [
        row for row in rows
        if str(row.get("outcome") or "").strip().lower() in {"", "yes"}
    ]
    active_rows = [
        row for row in yes_rows
        if boolish_active(row.get("active")) and not bool_value(row.get("closed"), False)
    ]
    rows_with_token = [row for row in active_rows if row.get("clob_token_id")]
    rows_with_condition = [row for row in active_rows if row.get("condition_id")]
    active_blank_rows = [
        row for row in active_rows
        if not row.get("clob_token_id") and not row.get("condition_id")
    ]
    if rows_with_token and rows_with_condition:
        status = "PASS"
        root_cause = None
        reason = "active CLOB token discovery has token and condition ids"
    elif not rows:
        status = "BLOCK"
        root_cause = "missing_clob_token_file_rows"
        reason = "clob_tokens.csv has no rows"
    elif yes_rows and not active_rows:
        status = "BLOCK"
        root_cause = "inactive_gamma_market_rows"
        reason = "all YES CLOB token rows are inactive or closed"
    elif active_rows and len(active_blank_rows) == len(active_rows):
        status = "BLOCK"
        root_cause = "blank_clob_token_ids"
        reason = "active CLOB token rows have blank clob_token_id and condition_id"
    else:
        status = "BLOCK"
        root_cause = "partial_clob_token_discovery"
        reason = "active CLOB token rows are missing token ids or condition ids"
    return {
        "status": status,
        "ok": status == "PASS",
        "root_cause": root_cause,
        "reason": reason,
        "token_file_rows": len(rows),
        "yes_token_rows": len(yes_rows),
        "active_token_file_rows": len(active_rows),
        "rows_with_token_id": len(rows_with_token),
        "rows_with_condition_id": len(rows_with_condition),
        "active_blank_token_rows": len(active_blank_rows),
    }


def source_status_is_current(rows):
    if not rows:
        return False
    return any(
        bool_value(row.get("ok"), False)
        and str(row.get("status") or "").lower() in {"fresh", "fresh_cache", "ok", "available", ""}
        and not bool_value(row.get("stale"), False)
        for row in rows
    )


def source_status_degradation_preflight(folder, snapshot_id):
    payload = source_family_degradation(folder)
    available = bool(payload.get("available"))
    payload_snapshot_id = payload.get("snapshot_id")
    snapshot_matches = bool(available and (not snapshot_id or payload_snapshot_id == snapshot_id))
    trading_allowed = bool(payload.get("trading_evidence_allowed"))
    if not available:
        status = "BLOCK"
        root_cause = "missing_source_status_row"
        reason = payload.get("reason") or "source-status proof is unavailable"
    elif not snapshot_matches:
        status = "BLOCK"
        root_cause = "stale_source_status_row"
        reason = (
            f"source-status proof snapshot {payload_snapshot_id or '(missing)'} "
            f"does not match latest snapshot {snapshot_id or '(missing)'}"
        )
    elif not trading_allowed:
        status = "BLOCK"
        root_cause = "source_status_degradation_blocked"
        reason = (
            "source-status degradation blocks trading evidence: "
            f"blocking_families={payload.get('blocking_family_count', 0)} "
            f"settlement_auth_failures={payload.get('settlement_auth_failure_source_count', 0)}"
        )
    else:
        status = "PASS"
        root_cause = "source_status_clean"
        reason = "source-status degradation allows trading evidence"
    return {
        "status": status,
        "ok": status == "PASS",
        "root_cause": root_cause,
        "reason": reason,
        "available": available,
        "snapshot_id": payload_snapshot_id,
        "snapshot_matches": snapshot_matches,
        "affected_family_count": payload.get("affected_family_count", 0),
        "blocking_family_count": payload.get("blocking_family_count", 0),
        "failed_source_count": payload.get("failed_source_count", 0),
        "fallback_source_count": payload.get("fallback_source_count", 0),
        "settlement_auth_failure_source_count": payload.get("settlement_auth_failure_source_count", 0),
        "provider_cooldown_source_count": payload.get("provider_cooldown_source_count", 0),
        "expected_unavailable_source_count": payload.get("expected_unavailable_source_count", 0),
        "trading_evidence_allowed": trading_allowed,
        "live_trade_permission_allowed": bool(payload.get("live_trade_permission_allowed")),
        "promotion_readiness_allowed": bool(payload.get("promotion_readiness_allowed")),
        "free_source_replacement": payload.get("free_source_replacement") or {},
        "free_source_replacement_allowed": bool(payload.get("free_source_replacement_allowed")),
        "claim_lane_allowance": payload.get("claim_lane_allowance") or {},
    }


def uses_default_snapshot_root(folder):
    try:
        folder_path = Path(folder).resolve()
        default_root = SNAPSHOT_DATA_ROOT.resolve()
        return folder_path == default_root or default_root in folder_path.parents
    except OSError:
        return False


def preflight_book_audit(
    folder,
    now,
    max_gap_seconds,
    loop_status=None,
    active_window_start_utc=None,
):
    """Audit active-day CLOB books with the same loop-aware policy as fleet checks."""
    loop_status = read_clob_loop_status() if loop_status is None and uses_default_snapshot_root(folder) else loop_status
    effective_gap_seconds = fleet_effective_book_gap_seconds(max_gap_seconds, loop_status)
    ignore_cutoff = None
    if loop_status:
        started_at = parse_utc_datetime(loop_status.get("started_at"))
        if started_at is not None:
            ignore_cutoff = started_at + timedelta(seconds=BOOK_AUDIT_STARTUP_GRACE_SECONDS)
    active_cutoff = parse_utc_datetime(active_window_start_utc)
    if active_cutoff is not None and (ignore_cutoff is None or active_cutoff > ignore_cutoff):
        ignore_cutoff = active_cutoff
    result = audit_book_tape(
        folder,
        now=now,
        max_gap_seconds=effective_gap_seconds,
        ignore_gaps_before=ignore_cutoff,
    )
    result["maker_active_window_start_utc"] = active_cutoff.isoformat() if active_cutoff else None
    result["maker_gap_policy"] = (
        "count internal gaps ending after the later of CLOB startup grace and maker active-window start"
        if active_cutoff
        else "count internal gaps after CLOB startup grace"
    )
    return result
