"""Band-level CLOB features derived from the fast book tape.

The CLOB recorder owns raw evidence. This module turns that evidence into
model-ready rows keyed like ``snapshots_long.csv``: one row per
``(snapshot_id, market, band)`` using only book rows captured at or before the
snapshot timestamp.
"""

import argparse
import bisect
import csv
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


CLOB_MODEL_FEATURE_COLUMNS = [
    "clob_feature_available",
    "clob_book_age_seconds",
    "clob_midpoint",
    "clob_spread",
    "clob_best_bid",
    "clob_best_ask",
    "clob_depth_1pct_total",
    "clob_depth_5pct_total",
    "clob_depth_all_total",
    "clob_imbalance_1pct",
    "clob_imbalance_5pct",
    "clob_liquidity_score",
    "clob_midpoint_change_60s",
    "clob_midpoint_change_300s",
    "clob_midpoint_stickiness_seconds",
    "clob_price_history_available",
    "clob_price_history_age_seconds",
    "clob_price_history_price",
    "clob_price_history_change_60s",
    "clob_price_history_change_300s",
    "clob_price_history_points_300s",
    "clob_ws_event_count_60s",
    "clob_ws_event_count_300s",
    "clob_ws_last_age_seconds",
    "clob_ws_last_price",
    "clob_ws_price_change_60s",
    "clob_model_edge_to_midpoint",
    "clob_model_edge_to_price_history",
    "clob_market_yes_minus_midpoint",
]

CLOB_FEATURE_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "event_slug",
    "market_id",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "clob_token_id",
    "clob_book_captured_at_utc",
    *CLOB_MODEL_FEATURE_COLUMNS,
]


def maybe_float(value):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def band_value(value):
    number = maybe_float(value)
    if number is None:
        return None
    if abs(number - round(number)) < 1e-9:
        return int(round(number))
    return number


def band_value_hi(row, value):
    explicit = band_value(
        row.get("bin_value_hi")
        if row.get("bin_value_hi") not in (None, "")
        else row.get("bin_value_hi_c")
    )
    if explicit is not None:
        return explicit
    label = str(row.get("range_label") or "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?\s*(?:-|\u2013)\s*([-+]?\d+(?:\.\d+)?)", label)
    if match:
        return band_value(match.group(1))
    return value


def snapshot_band_key(row):
    kind = str(row.get("bin_kind") or row.get("bin_type") or "eq").lower()
    value = band_value(row.get("bin_value") or row.get("bin_value_c"))
    value_hi = band_value_hi(row, value)
    return kind, value, value_hi


def book_band_key(row):
    kind = str(row.get("bin_kind") or "eq").lower()
    value = band_value(row.get("bin_value"))
    value_hi = band_value(row.get("bin_value_hi"))
    if value_hi is None:
        value_hi = value
    return kind, value, value_hi


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except UnicodeDecodeError:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            return list(csv.DictReader(handle))


def read_jsonl_records(path):
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def payload_sha1(payload):
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def ws_rows_from_payload(received_at_utc, event_slug, market_id, payload, raw_sha1):
    payloads = payload if isinstance(payload, list) else [payload]
    rows = []
    for item in payloads:
        item = item if isinstance(item, dict) else {"message": item}
        price_changes = item.get("price_changes")
        if isinstance(price_changes, list) and price_changes:
            for change in price_changes:
                change = change if isinstance(change, dict) else {"price": change}
                rows.append({
                    "received_at_utc": received_at_utc,
                    "event_slug": event_slug,
                    "market_id": market_id,
                    "event_type": change.get("event_type") or item.get("event_type"),
                    "asset_id": change.get("asset_id") or item.get("asset_id") or change.get("clob_token_id"),
                    "market": change.get("market") or item.get("market"),
                    "price": change.get("price"),
                    "side": change.get("side") or item.get("side"),
                    "raw_sha1": raw_sha1,
                })
            continue
        rows.append({
            "received_at_utc": received_at_utc,
            "event_slug": event_slug,
            "market_id": market_id,
            "event_type": item.get("event_type"),
            "asset_id": item.get("asset_id") or item.get("clob_token_id"),
            "market": item.get("market"),
            "price": item.get("price"),
            "side": item.get("side"),
            "raw_sha1": raw_sha1,
        })
    return rows


def ws_rows_from_jsonl(records):
    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        payload = record.get("payload")
        if payload is None:
            continue
        raw_sha1 = record.get("raw_sha1") or payload_sha1(payload)
        rows.extend(ws_rows_from_payload(
            record.get("received_at_utc"),
            record.get("event_slug"),
            record.get("market_id"),
            payload,
            raw_sha1,
        ))
    return rows


def sort_book_points(rows):
    grouped = {}
    for row in rows:
        if str(row.get("outcome") or "").lower() != "yes":
            continue
        captured = parse_time(row.get("captured_at_utc"))
        key = book_band_key(row)
        if captured is None or key[1] is None:
            continue
        point = {
            "captured_at": captured,
            "row": row,
            "midpoint": maybe_float(row.get("midpoint")),
        }
        grouped.setdefault(key, []).append(point)
    for points in grouped.values():
        points.sort(key=lambda item: item["captured_at"])
    return grouped


def sort_price_history_points(rows):
    grouped = {}
    for row in rows:
        if str(row.get("outcome") or "").lower() != "yes":
            continue
        token_id = str(row.get("clob_token_id") or "")
        point_time = parse_time(row.get("point_time_utc"))
        price = maybe_float(row.get("price"))
        if not token_id or point_time is None or price is None:
            continue
        grouped.setdefault(token_id, []).append({
            "captured_at": point_time,
            "row": row,
            "price": price,
        })
    for points in grouped.values():
        points.sort(key=lambda item: item["captured_at"])
    return grouped


def sort_ws_event_points(rows):
    grouped = {}
    seen = set()
    for row in rows:
        token_id = str(row.get("asset_id") or row.get("clob_token_id") or "")
        event_time = parse_time(row.get("received_at_utc"))
        price = maybe_float(row.get("price"))
        if not token_id or event_time is None:
            continue
        dedupe_key = (
            token_id,
            event_time.isoformat(),
            row.get("event_type") or "",
            price,
            row.get("side") or "",
            row.get("raw_sha1") or "",
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        grouped.setdefault(token_id, []).append({
            "captured_at": event_time,
            "row": row,
            "price": price,
        })
    for points in grouped.values():
        points.sort(key=lambda item: item["captured_at"])
    return grouped


def point_at_or_before(points, timestamp):
    times = [point["captured_at"] for point in points]
    idx = bisect.bisect_right(times, timestamp) - 1
    if idx < 0:
        return None, None
    return idx, points[idx]


def prior_midpoint_change(points, current_idx, current_time, current_midpoint, seconds, tolerance_seconds=90):
    if current_midpoint is None:
        return None
    target = current_time - timedelta(seconds=float(seconds))
    idx, prior = point_at_or_before(points, target)
    if prior is None:
        return None
    if (target - prior["captured_at"]).total_seconds() > float(tolerance_seconds):
        return None
    prior_midpoint = prior.get("midpoint")
    if prior_midpoint is None:
        return None
    return current_midpoint - prior_midpoint


def prior_value_change(points, current_idx, current_time, current_value, seconds, value_key="price", tolerance_seconds=90):
    if current_value is None:
        return None
    target = current_time - timedelta(seconds=float(seconds))
    idx, prior = point_at_or_before(points, target)
    if prior is None:
        return None
    if (target - prior["captured_at"]).total_seconds() > float(tolerance_seconds):
        return None
    prior_value = prior.get(value_key)
    if prior_value is None:
        return None
    return current_value - prior_value


def count_points_since(points, timestamp, seconds):
    start = timestamp - timedelta(seconds=float(seconds))
    times = [point["captured_at"] for point in points]
    left = bisect.bisect_left(times, start)
    right = bisect.bisect_right(times, timestamp)
    return max(0, right - left)


def midpoint_stickiness_seconds(points, current_idx, epsilon=1e-9):
    current = points[current_idx]
    current_midpoint = current.get("midpoint")
    if current_midpoint is None:
        return None
    start_time = current["captured_at"]
    for idx in range(current_idx - 1, -1, -1):
        midpoint = points[idx].get("midpoint")
        if midpoint is None or abs(midpoint - current_midpoint) > epsilon:
            break
        start_time = points[idx]["captured_at"]
    return (current["captured_at"] - start_time).total_seconds()


def liquidity_score(depth_5pct_total, spread):
    if depth_5pct_total is None or spread is None:
        return None
    return math.log1p(max(0.0, float(depth_5pct_total))) / (1.0 + 100.0 * max(0.0, float(spread)))


def empty_feature_values(age_seconds=None):
    values = {column: None for column in CLOB_MODEL_FEATURE_COLUMNS}
    values["clob_feature_available"] = 0.0
    values["clob_book_age_seconds"] = age_seconds
    return values


def features_from_book_point(snapshot_row, points, current_idx, snapshot_time):
    point = points[current_idx]
    row = point["row"]
    book_time = point["captured_at"]
    midpoint = point.get("midpoint")
    spread = maybe_float(row.get("spread"))
    bid_1 = maybe_float(row.get("bid_depth_1pct"))
    ask_1 = maybe_float(row.get("ask_depth_1pct"))
    bid_5 = maybe_float(row.get("bid_depth_5pct"))
    ask_5 = maybe_float(row.get("ask_depth_5pct"))
    bid_all = maybe_float(row.get("bid_depth_all"))
    ask_all = maybe_float(row.get("ask_depth_all"))
    depth_1 = (bid_1 or 0.0) + (ask_1 or 0.0) if bid_1 is not None or ask_1 is not None else None
    depth_5 = (bid_5 or 0.0) + (ask_5 or 0.0) if bid_5 is not None or ask_5 is not None else None
    depth_all = (bid_all or 0.0) + (ask_all or 0.0) if bid_all is not None or ask_all is not None else None
    model_probability = maybe_float(snapshot_row.get("model_probability"))
    market_yes = maybe_float(snapshot_row.get("market_yes"))
    values = {
        "clob_feature_available": 1.0,
        "clob_book_age_seconds": (snapshot_time - book_time).total_seconds(),
        "clob_midpoint": midpoint,
        "clob_spread": spread,
        "clob_best_bid": maybe_float(row.get("best_bid")),
        "clob_best_ask": maybe_float(row.get("best_ask")),
        "clob_depth_1pct_total": depth_1,
        "clob_depth_5pct_total": depth_5,
        "clob_depth_all_total": depth_all,
        "clob_imbalance_1pct": maybe_float(row.get("imbalance_1pct")),
        "clob_imbalance_5pct": maybe_float(row.get("imbalance_5pct")),
        "clob_liquidity_score": liquidity_score(depth_5, spread),
        "clob_midpoint_change_60s": prior_midpoint_change(points, current_idx, book_time, midpoint, 60),
        "clob_midpoint_change_300s": prior_midpoint_change(points, current_idx, book_time, midpoint, 300),
        "clob_midpoint_stickiness_seconds": midpoint_stickiness_seconds(points, current_idx),
    }
    return values, row.get("clob_token_id"), book_time.isoformat()


def enrich_with_price_history(values, token_id, price_history, snapshot_time, model_probability):
    values.update({
        "clob_price_history_available": 0.0,
        "clob_price_history_age_seconds": None,
        "clob_price_history_price": None,
        "clob_price_history_change_60s": None,
        "clob_price_history_change_300s": None,
        "clob_price_history_points_300s": 0.0,
        "clob_model_edge_to_price_history": None,
    })
    points = price_history.get(str(token_id or "")) or []
    idx, point = point_at_or_before(points, snapshot_time)
    if point is None:
        return values
    price = point.get("price")
    point_time = point["captured_at"]
    values.update({
        "clob_price_history_available": 1.0,
        "clob_price_history_age_seconds": (snapshot_time - point_time).total_seconds(),
        "clob_price_history_price": price,
        "clob_price_history_change_60s": prior_value_change(points, idx, point_time, price, 60),
        "clob_price_history_change_300s": prior_value_change(points, idx, point_time, price, 300),
        "clob_price_history_points_300s": float(count_points_since(points, snapshot_time, 300)),
        "clob_model_edge_to_price_history": (
            model_probability - price
            if model_probability is not None and price is not None
            else None
        ),
    })
    return values


def enrich_with_ws_events(values, token_id, ws_events, snapshot_time):
    values.update({
        "clob_ws_event_count_60s": 0.0,
        "clob_ws_event_count_300s": 0.0,
        "clob_ws_last_age_seconds": None,
        "clob_ws_last_price": None,
        "clob_ws_price_change_60s": None,
    })
    points = ws_events.get(str(token_id or "")) or []
    idx, point = point_at_or_before(points, snapshot_time)
    values["clob_ws_event_count_60s"] = float(count_points_since(points, snapshot_time, 60))
    values["clob_ws_event_count_300s"] = float(count_points_since(points, snapshot_time, 300))
    if point is None:
        return values
    price = point.get("price")
    point_time = point["captured_at"]
    values.update({
        "clob_ws_last_age_seconds": (snapshot_time - point_time).total_seconds(),
        "clob_ws_last_price": price,
        "clob_ws_price_change_60s": prior_value_change(points, idx, point_time, price, 60),
    })
    return values


def clob_feature_rows_for_folder(folder, max_age_seconds=180, market_id=None):
    folder = Path(folder)
    snapshots = read_csv_rows(folder / "snapshots_long.csv")
    books = sort_book_points(read_csv_rows(folder / "order_books_summary.csv"))
    price_history = sort_price_history_points(read_csv_rows(folder / "price_history.csv"))
    ws_event_rows = read_csv_rows(folder / "market_ws_events.csv")
    ws_event_rows.extend(ws_rows_from_jsonl(read_jsonl_records(folder / "market_ws.jsonl")))
    ws_events = sort_ws_event_points(ws_event_rows)
    rows = []
    for snapshot in snapshots:
        snapshot_time = parse_time(snapshot.get("captured_at_utc"))
        key = snapshot_band_key(snapshot)
        base = {
            "snapshot_id": snapshot.get("snapshot_id"),
            "captured_at_utc": snapshot.get("captured_at_utc"),
            "event_slug": snapshot.get("event_slug") or folder.name,
            "market_id": snapshot.get("market_id") or market_id,
            "range_label": snapshot.get("range_label"),
            "bin_kind": key[0],
            "bin_value": key[1],
            "bin_value_hi": key[2],
            "clob_token_id": None,
            "clob_book_captured_at_utc": None,
        }
        if snapshot_time is None or key not in books:
            rows.append({**base, **empty_feature_values()})
            continue
        idx, point = point_at_or_before(books[key], snapshot_time)
        if point is None:
            rows.append({**base, **empty_feature_values()})
            continue
        age = (snapshot_time - point["captured_at"]).total_seconds()
        if age < 0 or age > float(max_age_seconds):
            rows.append({**base, **empty_feature_values(age_seconds=age)})
            continue
        features, token_id, book_time = features_from_book_point(snapshot, books[key], idx, snapshot_time)
        model_probability = maybe_float(snapshot.get("model_probability"))
        market_yes = maybe_float(snapshot.get("market_yes"))
        midpoint = features.get("clob_midpoint")
        features["clob_model_edge_to_midpoint"] = (
            model_probability - midpoint
            if model_probability is not None and midpoint is not None
            else None
        )
        features["clob_market_yes_minus_midpoint"] = (
            market_yes - midpoint
            if market_yes is not None and midpoint is not None
            else None
        )
        enrich_with_price_history(features, token_id, price_history, snapshot_time, model_probability)
        enrich_with_ws_events(features, token_id, ws_events, snapshot_time)
        rows.append({
            **base,
            "clob_token_id": token_id,
            "clob_book_captured_at_utc": book_time,
            **features,
        })
    return rows


def feature_index_for_folder(folder, max_age_seconds=180, market_id=None):
    index = {}
    for row in clob_feature_rows_for_folder(folder, max_age_seconds=max_age_seconds, market_id=market_id):
        key = (
            row.get("market_id"),
            str(row.get("snapshot_id")),
            row.get("bin_kind"),
            band_value(row.get("bin_value")),
            band_value(row.get("bin_value_hi")),
        )
        index[key] = row
    return index


def write_clob_feature_rows(folder, out_name="clob_features_long.csv", jsonl_name="clob_features.jsonl", max_age_seconds=180, market_id=None):
    folder = Path(folder)
    rows = clob_feature_rows_for_folder(folder, max_age_seconds=max_age_seconds, market_id=market_id)
    csv_path = folder / out_name
    jsonl_path = folder / jsonl_name if jsonl_name else None
    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CLOB_FEATURE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        if jsonl_path is not None:
            with jsonl_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return {"rows": len(rows), "csv_path": str(csv_path), "jsonl_path": str(jsonl_path) if jsonl_path else None}


def _load_market_helpers():
    from weather.collection.collection_health import latest_market_folder  # noqa: WPS433
    from weather.market.market_registry import REGISTRY, all_specs, spec_for_slug  # noqa: WPS433

    return latest_market_folder, REGISTRY, all_specs, spec_for_slug


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build band-level CLOB model features from snapshot/book tapes.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders to process. Defaults to latest folder per market.")
    parser.add_argument("--market", default="all", help="Market id to process when folders are omitted, or 'all'.")
    parser.add_argument("--snapshots-root", type=Path, default=Path("data") / "snapshots")
    parser.add_argument("--max-age-seconds", type=float, default=180.0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    args = parser.parse_args(argv)

    latest_market_folder, registry, all_specs, spec_for_slug = _load_market_helpers()
    targets = []
    if args.folders:
        for folder in args.folders:
            folder_path = Path(folder)
            spec = spec_for_slug(folder_path.name)
            market_id = args.market if args.market != "all" else (spec.id if spec else None)
            targets.append((folder_path, market_id))
    else:
        if args.market == "all":
            specs = list(all_specs())
        else:
            spec = registry.get(args.market)
            if spec is None:
                raise SystemExit(f"unknown market id: {args.market}")
            specs = [spec]
        for spec in specs:
            folder = latest_market_folder(spec, snapshots_root=args.snapshots_root)
            if folder is not None:
                targets.append((Path(folder), spec.id))

    results = []
    for folder, market_id in targets:
        result = write_clob_feature_rows(
            folder,
            max_age_seconds=args.max_age_seconds,
            market_id=market_id,
        )
        results.append({
            "folder": str(folder),
            "market_id": market_id,
            **result,
        })

    if args.json:
        print(json.dumps({"folders": len(results), "results": results}, indent=2, sort_keys=True))
    else:
        for result in results:
            print(
                f"{result['market_id'] or '-'} {result['folder']}: "
                f"{result['rows']} rows -> {result['csv_path']}"
            )
    return results
