"""Bounded active-day projections over append-only market evidence tapes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.io import (
    read_csv_tail_rows_with_diagnostics,
    read_jsonl_tail_with_diagnostics,
)
from weather.market.market_microstructure_features import (
    clob_feature_rows_from_rows,
    parse_time,
    point_at_or_before,
    snapshot_band_key,
    sort_book_points,
    sort_price_history_points,
    sort_ws_event_points,
    ws_rows_from_jsonl,
)


LATEST_GROUP_MAX_SCAN_BYTES = 1 * 1024 * 1024
BOOK_HISTORY_MAX_SCAN_BYTES = 8 * 1024 * 1024
ENRICHMENT_HISTORY_MAX_SCAN_BYTES = 4 * 1024 * 1024
FEATURE_HISTORY_SECONDS = 300

_READ_OK = {"ok", "missing", "empty"}


def _failed(diagnostics, status, detail):
    diagnostics.update({"status": status, "error": detail, "sufficient": False})
    return []


def _time(value):
    return parse_time(value) or datetime.min.replace(tzinfo=timezone.utc)


def _series_is_nondecreasing(rows, *, key, time_field):
    previous = {}
    for row in rows:
        timestamp = parse_time(row.get(time_field))
        if timestamp is None:
            return False
        series = key(row)
        if series in previous and timestamp < previous[series]:
            return False
        previous[series] = timestamp
    return True


def _latest_time_group(rows, diagnostics, *, time_field="captured_at_utc", outcomes=None):
    if diagnostics.get("status") not in _READ_OK:
        return []
    allowed = None if outcomes is None else {str(value).strip().lower() for value in outcomes}
    eligible = [
        (index, row)
        for index, row in enumerate(rows)
        if allowed is None or str(row.get("outcome") or "").strip().lower() in allowed
    ]
    if not eligible:
        diagnostics["sufficient"] = bool(diagnostics.get("reached_start"))
        if not diagnostics["sufficient"]:
            return _failed(diagnostics, "scan_limit_exhausted", "bounded suffix has no eligible complete row")
        return []
    parsed = [(index, row, parse_time(row.get(time_field))) for index, row in eligible]
    if any(timestamp is None for _index, _row, timestamp in parsed):
        if diagnostics.get("reached_start") and all(timestamp is None for _index, _row, timestamp in parsed):
            diagnostics.update({"sufficient": True, "selected_group": None})
            return [row for _index, row, _timestamp in parsed]
        return _failed(diagnostics, "invalid_timestamp", f"{time_field} is missing or malformed")
    if not diagnostics.get("reached_start") and not _series_is_nondecreasing(
        [row for _index, row, _timestamp in parsed],
        key=lambda _row: "all",
        time_field=time_field,
    ):
        return _failed(diagnostics, "non_monotonic_tail", f"{time_field} decreases inside bounded suffix")
    latest_time = max(timestamp for _index, _row, timestamp in parsed)
    selected = [(index, row) for index, row, timestamp in parsed if timestamp == latest_time]
    first_selected = min(index for index, _row in selected)
    if not diagnostics.get("reached_start"):
        prior_eligible = [
            (index, row)
            for index, row in eligible
            if index < first_selected
        ]
        if not prior_eligible:
            return _failed(
                diagnostics,
                "scan_limit_exhausted",
                f"latest {time_field} batch begins at the bounded suffix boundary",
            )
    diagnostics.update({
        "sufficient": True,
        "selected_group": latest_time.isoformat(),
        "selected_row_count": len(selected),
    })
    return [row for _index, row in selected]


def _rows_for_group(rows, diagnostics, group_value, *, group_field="snapshot_id"):
    if diagnostics.get("status") not in _READ_OK or not group_value:
        return []
    indices = [index for index, row in enumerate(rows) if row.get(group_field) == group_value]
    if not indices:
        diagnostics.update({
            "status": "target_group_absent",
            "sufficient": bool(diagnostics.get("reached_start")),
            "target_group": str(group_value),
            "error": f"{group_field}={group_value!r} is absent from the bounded suffix",
        })
        return []
    if not diagnostics.get("reached_start") and indices != list(range(indices[0], indices[-1] + 1)):
        return _failed(
            diagnostics,
            "non_contiguous_group",
            f"{group_field}={group_value!r} is not one contiguous append batch",
        )
    if not diagnostics.get("reached_start") and indices[0] == 0:
        return _failed(
            diagnostics,
            "scan_limit_exhausted",
            f"{group_field}={group_value!r} begins at the bounded suffix boundary",
        )
    selected = [rows[index] for index in indices]
    diagnostics.update({
        "status": "ok",
        "sufficient": True,
        "target_group": str(group_value),
        "selected_row_count": len(selected),
    })
    return selected


def _latest_snapshot_rows(rows, diagnostics):
    latest = _latest_time_group(rows, diagnostics)
    if not latest:
        return []
    latest_id = max(latest, key=lambda row: _time(row.get("captured_at_utc"))).get("snapshot_id")
    if not latest_id:
        return _failed(diagnostics, "missing_group_key", "latest snapshot batch has no snapshot_id")
    latest_ids = {row.get("snapshot_id") for row in latest}
    if latest_ids != {latest_id}:
        return _failed(
            diagnostics,
            "ambiguous_latest_batch",
            "latest captured_at_utc contains more than one snapshot_id",
        )
    return _rows_for_group(rows, diagnostics, latest_id)


def _book_history_sufficient(snapshot_rows, book_rows, diagnostics, max_age_seconds):
    if diagnostics.get("status") not in _READ_OK:
        return False
    if diagnostics.get("reached_start"):
        diagnostics["history_sufficient"] = True
        return True
    if not _series_is_nondecreasing(
        book_rows,
        key=lambda row: snapshot_band_key(row),
        time_field="captured_at_utc",
    ):
        _failed(diagnostics, "non_monotonic_tail", "book timestamps decrease within a band")
        return False
    books = sort_book_points(book_rows)
    checked_bands = 0
    for snapshot in snapshot_rows:
        snapshot_time = parse_time(snapshot.get("captured_at_utc"))
        if snapshot_time is None:
            continue
        points = books.get(snapshot_band_key(snapshot)) or []
        index, point = point_at_or_before(points, snapshot_time)
        if point is None:
            _failed(diagnostics, "scan_limit_exhausted", "bounded book suffix cannot prove no prior matching book")
            return False
        age = (snapshot_time - point["captured_at"]).total_seconds()
        if age < 0 or age > float(max_age_seconds):
            continue
        midpoint = point.get("midpoint")
        if midpoint is None:
            # Every history-dependent midpoint feature is null when the
            # selected current midpoint is null; the current book fields are
            # therefore exact without an earlier horizon.
            continue
        checked_bands += 1
        if points[0]["captured_at"] > point["captured_at"] - timedelta(
            seconds=FEATURE_HISTORY_SECONDS
        ):
            _failed(
                diagnostics,
                "scan_limit_exhausted",
                "bounded book suffix does not cover the 300-second feature window",
            )
            return False
        boundary_found = any(
            prior.get("midpoint") is None
            or abs(float(prior["midpoint"]) - float(midpoint)) > 1e-9
            for prior in reversed(points[:index])
        )
        if not boundary_found:
            _failed(
                diagnostics,
                "scan_limit_exhausted",
                "bounded book suffix does not contain the midpoint-stickiness boundary",
            )
            return False
    diagnostics.update({
        "history_sufficient": True,
        "history_horizon_seconds": FEATURE_HISTORY_SECONDS,
        "history_checked_band_count": checked_bands,
    })
    return True


def _selected_book_tokens(snapshot_rows, book_rows):
    books = sort_book_points(book_rows)
    selected = []
    for snapshot in snapshot_rows:
        snapshot_time = parse_time(snapshot.get("captured_at_utc"))
        if snapshot_time is None:
            continue
        _index, point = point_at_or_before(books.get(snapshot_band_key(snapshot)) or [], snapshot_time)
        if point is not None:
            selected.append((str(point["row"].get("clob_token_id") or ""), snapshot_time))
    return [(token, timestamp) for token, timestamp in selected if token]


def _point_history_sufficient(
    points_by_token,
    selected_tokens,
    diagnostics,
    *,
    prior_seconds,
    value_key,
):
    if diagnostics.get("status") in {"missing", "empty"}:
        diagnostics["history_sufficient"] = True
        return True
    if diagnostics.get("status") != "ok":
        return False
    if diagnostics.get("reached_start"):
        diagnostics["history_sufficient"] = True
        return True
    checked_tokens = set()
    for token, snapshot_time in selected_tokens:
        points = points_by_token.get(token) or []
        _index, point = point_at_or_before(points, snapshot_time)
        if point is None:
            _failed(diagnostics, "scan_limit_exhausted", f"bounded enrichment suffix has no point for token {token}")
            return False
        required_start = snapshot_time - timedelta(seconds=FEATURE_HISTORY_SECONDS)
        if point.get(value_key) is not None:
            required_start = min(
                required_start,
                point["captured_at"] - timedelta(seconds=prior_seconds),
            )
        if points[0]["captured_at"] > required_start:
            _failed(diagnostics, "scan_limit_exhausted", f"bounded enrichment suffix is too short for token {token}")
            return False
        checked_tokens.add(token)
    diagnostics.update({
        "history_sufficient": True,
        "history_horizon_seconds": FEATURE_HISTORY_SECONDS,
        "history_checked_token_count": len(checked_tokens),
    })
    return True


def _projection_status(diagnostics):
    failures = []
    for name, item in diagnostics.items():
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if (status in _READ_OK and item.get("sufficient") is not False) or status == "raw_fallback":
            continue
        if status == "target_group_absent" and item.get("sufficient"):
            continue
        failures.append(f"{name}:{status}")
    return {
        "status": "BLOCK" if failures else "PASS",
        "ok": not failures,
        "failures": failures,
        "detail": ", ".join(failures) if failures else "bounded latest-input reads are complete",
    }


def load_latest_market_inputs(
    folder,
    *,
    market_id=None,
    max_age_seconds=180.0,
    latest_group_max_scan_bytes=LATEST_GROUP_MAX_SCAN_BYTES,
    book_history_max_scan_bytes=BOOK_HISTORY_MAX_SCAN_BYTES,
    enrichment_history_max_scan_bytes=ENRICHMENT_HISTORY_MAX_SCAN_BYTES,
):
    """Load one market's current decision inputs with length-independent I/O.

    A suffix is accepted only when an append-batch boundary and every feature
    history dependency are present. Otherwise the projection returns no CLOB
    feature rows and explicit blocking diagnostics instead of falling back to
    a full historical scan or approximating a feature.
    """

    folder = Path(folder)
    diagnostics = {}

    snapshot_tail, snapshot_diag = read_csv_tail_rows_with_diagnostics(
        folder / "snapshots_long.csv",
        max_bytes=latest_group_max_scan_bytes,
    )
    diagnostics["snapshots"] = snapshot_diag
    snapshot_rows = _latest_snapshot_rows(snapshot_tail, snapshot_diag)
    snapshot_id = snapshot_rows[0].get("snapshot_id") if snapshot_rows else None

    source_tail, source_diag = read_csv_tail_rows_with_diagnostics(
        folder / "source_status_long.csv",
        max_bytes=latest_group_max_scan_bytes,
    )
    diagnostics["source_status"] = source_diag
    source_rows = _rows_for_group(source_tail, source_diag, snapshot_id)

    token_tail, token_diag = read_csv_tail_rows_with_diagnostics(
        folder / "clob_tokens.csv",
        max_bytes=latest_group_max_scan_bytes,
    )
    diagnostics["clob_tokens"] = token_diag
    token_rows = _latest_time_group(token_tail, token_diag)

    book_tail, book_diag = read_csv_tail_rows_with_diagnostics(
        folder / "order_books_summary.csv",
        max_bytes=book_history_max_scan_bytes,
    )
    diagnostics["order_books"] = book_diag
    book_rows = _latest_time_group(
        book_tail,
        book_diag,
        outcomes={"", "yes", "no"},
    )

    feature_tail, feature_diag = read_csv_tail_rows_with_diagnostics(
        folder / "clob_features_long.csv",
        max_bytes=latest_group_max_scan_bytes,
    )
    diagnostics["clob_features"] = feature_diag
    clob_feature_rows = _rows_for_group(feature_tail, feature_diag, snapshot_id)

    if not clob_feature_rows and snapshot_rows and feature_diag.get("status") in {
        "missing",
        "empty",
        "target_group_absent",
        "scan_limit_exhausted",
    }:
        if _book_history_sufficient(snapshot_rows, book_tail, book_diag, max_age_seconds):
            price_rows, price_diag = read_csv_tail_rows_with_diagnostics(
                folder / "price_history.csv",
                max_bytes=enrichment_history_max_scan_bytes,
            )
            diagnostics["price_history"] = price_diag
            ws_rows, ws_diag = read_csv_tail_rows_with_diagnostics(
                folder / "market_ws_events.csv",
                max_bytes=enrichment_history_max_scan_bytes,
            )
            diagnostics["market_ws_events"] = ws_diag
            ws_records, ws_jsonl_diag = read_jsonl_tail_with_diagnostics(
                folder / "market_ws.jsonl",
                max_bytes=enrichment_history_max_scan_bytes,
            )
            diagnostics["market_ws_jsonl"] = ws_jsonl_diag
            selected_tokens = _selected_book_tokens(snapshot_rows, book_tail)
            ws_jsonl_rows = ws_rows_from_jsonl(ws_records)
            if (
                price_diag.get("status") == "ok"
                and not price_diag.get("reached_start")
                and not _series_is_nondecreasing(
                    price_rows,
                    key=lambda row: str(row.get("clob_token_id") or ""),
                    time_field="point_time_utc",
                )
            ):
                _failed(price_diag, "non_monotonic_tail", "price-history timestamps decrease within a token")
            if (
                ws_diag.get("status") == "ok"
                and not ws_diag.get("reached_start")
                and not _series_is_nondecreasing(
                    ws_rows,
                    key=lambda row: str(row.get("asset_id") or row.get("clob_token_id") or ""),
                    time_field="received_at_utc",
                )
            ):
                _failed(ws_diag, "non_monotonic_tail", "WebSocket timestamps decrease within a token")
            if (
                ws_jsonl_diag.get("status") == "ok"
                and not ws_jsonl_diag.get("reached_start")
                and not _series_is_nondecreasing(
                    ws_jsonl_rows,
                    key=lambda row: str(row.get("asset_id") or row.get("clob_token_id") or ""),
                    time_field="received_at_utc",
                )
            ):
                _failed(ws_jsonl_diag, "non_monotonic_tail", "raw WebSocket timestamps decrease within a token")
            price_points = sort_price_history_points(price_rows)
            ws_csv_points = sort_ws_event_points(ws_rows)
            ws_jsonl_points = sort_ws_event_points(ws_jsonl_rows)
            histories_ok = (
                _point_history_sufficient(
                    price_points,
                    selected_tokens,
                    price_diag,
                    prior_seconds=300,
                    value_key="price",
                )
                and _point_history_sufficient(
                    ws_csv_points,
                    selected_tokens,
                    ws_diag,
                    prior_seconds=60,
                    value_key="price",
                )
                and _point_history_sufficient(
                    ws_jsonl_points,
                    selected_tokens,
                    ws_jsonl_diag,
                    prior_seconds=60,
                    value_key="price",
                )
            )
            if histories_ok:
                clob_feature_rows = clob_feature_rows_from_rows(
                    snapshot_rows,
                    book_tail,
                    price_history_rows=price_rows,
                    ws_event_rows=ws_rows,
                    ws_jsonl_records=ws_records,
                    event_slug=folder.name,
                    max_age_seconds=max_age_seconds,
                    market_id=market_id,
                )
                feature_diag.update({
                    "status": "raw_fallback",
                    "sufficient": True,
                    "selected_row_count": len(clob_feature_rows),
                    "error": None,
                })

    diagnostics["projection"] = _projection_status(diagnostics)
    diagnostics["total_scanned_bytes"] = sum(
        int(item.get("scanned_bytes") or 0)
        for item in diagnostics.values()
        if isinstance(item, dict)
    )
    diagnostics["total_read_bytes"] = sum(
        int(item.get("read_bytes") or 0)
        for item in diagnostics.values()
        if isinstance(item, dict)
    )
    return {
        "snapshot_rows": snapshot_rows,
        "source_rows": source_rows,
        "token_rows": token_rows,
        "book_rows": book_rows,
        "clob_feature_rows": clob_feature_rows,
        "diagnostics": diagnostics,
    }
