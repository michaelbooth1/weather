"""Bounded, research-only maker reconstruction and offline scoring.

The harness consumes an explicit coverage-audit artifact and an explicit list
of maker run folders.  It treats the mirror as immutable, processes one
market-day folder at a time, and never interprets order-book ``price_change``
events as trades.  Only protocol ``last_trade_price`` rows are admissible for
toxicity and conservative strict-through fills.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gc
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from weather.io import (
    write_csv_rows_atomic,
    write_json_atomic,
    write_text_atomic,
)
from weather.market.clob_recon import load_book_rows
from weather.market.market_registry import REGISTRY
from weather.market.mm_paper_constants import DEFAULT_CONFIG as PAPER_CONFIG
from weather.market.mm_paper_scoring import (
    fee_equivalent,
    finite_float,
    load_quote_rows,
    quote_legs,
    strict_trade_through,
)
from weather.market.mm_policy import bool_value, parse_time
from weather.reporting.data_quality.clob_coverage_audit import parse_event_slug
from weather.reporting.research.workstation_maker_report import (
    reconcile_historical_reports,
    render_report as render_maker_report,
    summarize_quote_run_classes,
    summarize_selected_holdout_fills,
    summarize_ws_validation,
)
from weather.reporting.research.research_path_contract import resolve_output_outside_read_only_roots
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("workstation_maker_research")
ACCEPTED_WS_EVENT_TYPES = frozenset({"book", "price_change", "tick_size_change", "last_trade_price", "best_bid_ask"})
TRADE_EVENT_TYPE = "last_trade_price"
MARKOUT_HORIZONS = (("1m", 60), ("5m", 300), ("30m", 1800))
POLICY_TICK_OFFSETS = {"at_touch": 0, "one_tick_wider": -1, "one_tick_inside": 1}
BASELINE_POLICY = "at_touch"
BOOTSTRAP_SEED = 20_260_722
BOOTSTRAP_REPLICATES = 10_000
QUOTE_TTL_SECONDS = 60.0
SYNTHETIC_QUOTE_SIZE = 5.0
MAX_MARK_LAG_SECONDS = 300.0
EXPECTED_FLEET_MARKET_IDS = frozenset(REGISTRY)
EXPECTED_FLEET_MARKETS = len(EXPECTED_FLEET_MARKET_IDS)
MIN_SELECTION_COMPLETE_FILLS = 10
MIN_SELECTION_ACTIVE_DATES = 3
MIN_CONFIRMATION_FLEET_DATES = 10

MARKET_DAY_COLUMNS = (
    "target_date",
    "market_id",
    "event_slug",
    "split",
    "book_rows",
    "two_sided_book_rows",
    "mean_spread",
    "median_spread",
    "mean_top_depth",
    "mean_depth_1pct",
    "mean_depth_all",
    "ws_rows",
    "ws_event_types_json",
    "unknown_ws_event_rows",
    "last_trade_price_rows",
    "sized_last_trade_price_rows",
    "side_supported_last_trade_price_rows",
    "book_matched_trade_rows",
    "toxicity_supported",
    "mean_passive_markout_1m_per_share",
    "mean_passive_markout_5m_per_share",
    "mean_passive_markout_30m_per_share",
    "negative_markout_30m_rows",
)

FILL_COLUMNS = (
    "evidence_source",
    "policy_id",
    "run_class",
    "run_folder",
    "run_id",
    "target_date",
    "market_id",
    "event_slug",
    "clob_token_id",
    "trade_id",
    "trade_time_utc",
    "trade_side",
    "passive_side",
    "quote_time_utc",
    "quote_age_seconds",
    "quote_price",
    "fill_size",
    "through_trade_price",
    "through_trade_size",
    "conservative_fill_rule",
    "gross_spread_capture_usdc",
    "markout_1m_per_share",
    "markout_1m_usdc",
    "markout_5m_per_share",
    "markout_5m_usdc",
    "markout_30m_per_share",
    "markout_30m_usdc",
    "adverse_selection_loss_30m_usdc",
    "modeled_flattening_cost_usdc",
    "theoretical_maker_fee_equivalent_usdc",
    "theoretical_maker_rebate_usdc",
    "theoretical_liquidity_reward_usdc",
    "net_after_modeled_costs_30m_usdc",
    "net_with_theoretical_rebate_30m_usdc",
    "economics_evidence_basis",
)

POLICY_DAY_COLUMNS = (
    "target_date",
    "market_id",
    "event_slug",
    "split",
    "policy_id",
    "conservative_fill_count",
    "filled_shares",
    "gross_spread_capture_usdc",
    "markout_1m_complete_fill_count",
    "markout_1m_usdc",
    "mean_markout_1m_per_share",
    "markout_5m_complete_fill_count",
    "markout_5m_usdc",
    "mean_markout_5m_per_share",
    "markout_30m_complete_fill_count",
    "markout_30m_usdc",
    "mean_markout_30m_per_share",
    "adverse_selection_loss_30m_usdc",
    "modeled_flattening_cost_usdc",
    "modeled_flattening_cost_30m_complete_usdc",
    "theoretical_maker_fee_equivalent_usdc",
    "theoretical_maker_rebate_usdc",
    "theoretical_maker_rebate_30m_complete_usdc",
    "theoretical_liquidity_reward_usdc",
    "net_after_modeled_costs_30m_usdc",
    "net_with_theoretical_rebate_30m_usdc",
)

QUOTE_RUN_DAY_COLUMNS = (
    "run_class",
    "run_folder",
    "run_id",
    "target_date",
    "market_id",
    "event_slug",
    "coverage_status",
    "quote_rows",
    "quote_permission_rows",
    "quote_legs",
    *POLICY_DAY_COLUMNS[5:],
)

ADDITIVE_POLICY_METRICS = (
    "conservative_fill_count",
    "filled_shares",
    "gross_spread_capture_usdc",
    "markout_1m_usdc",
    "markout_5m_usdc",
    "markout_30m_usdc",
    "adverse_selection_loss_30m_usdc",
    "modeled_flattening_cost_usdc",
    "modeled_flattening_cost_30m_complete_usdc",
    "theoretical_maker_fee_equivalent_usdc",
    "theoretical_maker_rebate_usdc",
    "theoretical_maker_rebate_30m_complete_usdc",
    "net_after_modeled_costs_30m_usdc",
    "net_with_theoretical_rebate_30m_usdc",
)


class MakerResearchError(ValueError):
    """Fail-closed input or evidence-contract error."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_stat(path: Path, *, include_hash: bool = False) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256_file(path) if include_hash else None,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MakerResearchError(f"invalid required JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise MakerResearchError(f"required JSON input is not an object: {path}")
    return value


def _safe_output_root(path: str | Path, *, read_only_data_root: str | Path) -> Path:
    try:
        root = resolve_output_outside_read_only_roots(path, read_only_roots=[read_only_data_root])
    except ValueError as exc:
        raise MakerResearchError(str(exc)) from exc
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_json(path: Path, payload: Any) -> None:
    write_json_atomic(path, payload, trailing_newline=True)


def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    normalized = (
        {
            key: (
                json.dumps(value, sort_keys=True)
                if isinstance(value, (dict, list, tuple))
                else value
            )
            for key, value in row.items()
        }
        for row in rows
    )
    write_csv_rows_atomic(path, columns, normalized)


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def _median(values: Iterable[float | None]) -> float | None:
    clean = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not clean:
        return None
    middle = len(clean) // 2
    if len(clean) % 2:
        return clean[middle]
    return (clean[middle - 1] + clean[middle]) / 2.0


def _sum(rows: Iterable[Mapping[str, Any]], key: str) -> float:
    return sum(finite_float(row.get(key), 0.0) or 0.0 for row in rows)


def _rounded(value: Any, digits: int = 9) -> Any:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, digits) if math.isfinite(value) else None
    return value


def _quote_market_day_counts(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    total = 0
    permission = 0
    legs = 0
    event_slugs: set[str] = set()
    days: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            total += 1
            target_date = str(row.get("target_date") or "")
            market_id = str(row.get("market_id") or "")
            event_slug = str(row.get("event_slug") or "")
            if event_slug:
                event_slugs.add(event_slug)
            key = (target_date, market_id)
            item = days.setdefault(
                key,
                {
                    "target_date": target_date,
                    "market_id": market_id,
                    "event_slug": event_slug,
                    "quote_rows": 0,
                    "quote_permission_rows": 0,
                    "quote_legs": 0,
                },
            )
            if event_slug and item["event_slug"] not in {"", event_slug}:
                raise MakerResearchError(
                    f"maker quote day has multiple event slugs for {key}: "
                    f"{item['event_slug']} vs {event_slug}"
                )
            if event_slug:
                item["event_slug"] = event_slug
            item["quote_rows"] += 1
            allowed = bool_value(row.get("quote_permission"), False)
            if allowed:
                permission += 1
                item["quote_permission_rows"] += 1
                row_legs = int(
                    (finite_float(row.get("bid_price")) is not None)
                    and (finite_float(row.get("bid_size"), 0.0) or 0.0) > 0.0
                ) + int(
                    (finite_float(row.get("ask_price")) is not None)
                    and (finite_float(row.get("ask_size"), 0.0) or 0.0) > 0.0
                )
                legs += row_legs
                item["quote_legs"] += row_legs
    return (
        {
            "quote_rows": total,
            "quote_permission_rows": permission,
            "quote_legs": legs,
            "event_slugs": sorted(event_slugs),
        },
        sorted(days.values(), key=lambda row: (row["target_date"], row["market_id"])),
    )


def _complete_fleet_calendar(
    rows: Sequence[Mapping[str, Any]], start: str, end: str
) -> bool:
    start_time = datetime.fromisoformat(start)
    end_time = datetime.fromisoformat(end)
    days = (end_time - start_time).days + 1
    if days <= 0:
        return False
    expected_dates = {
        (start_time + timedelta(days=offset)).date().isoformat()
        for offset in range(days)
    }
    markets_by_date: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        markets_by_date[str(row.get("target_date") or "")].append(
            str(row.get("market_id") or "")
        )
    if set(markets_by_date) != expected_dates:
        return False
    return all(
        len(market_ids) == EXPECTED_FLEET_MARKETS
        and set(market_ids) == EXPECTED_FLEET_MARKET_IDS
        for market_ids in markets_by_date.values()
    )


def classify_run_folder(folder: str | Path) -> dict[str, Any]:
    folder = Path(folder).resolve()
    if not folder.is_absolute() or not folder.is_dir():
        raise MakerResearchError(f"maker run folder is missing: {folder}")
    if any(part.lower() == "_quarantine" for part in folder.parts):
        raise MakerResearchError(f"quarantined maker run is forbidden: {folder}")
    config_path = folder / "run_config.json"
    summary_path = folder / "run_summary.json"
    quote_path = folder / "quote_intents_long.csv"
    for path in (config_path, summary_path, quote_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise MakerResearchError(f"maker run is missing required evidence: {path}")
    config = _read_json(config_path)
    summary = _read_json(summary_path)
    evidence_mode = str(
        summary.get("evidence_mode") or config.get("evidence_mode") or ""
    )
    mode = str(summary.get("mode") or config.get("mode") or "")
    name_lower = folder.name.lower()
    if evidence_mode == "post_settlement_evaluation":
        run_class = "post_settlement_proof"
    elif evidence_mode == "operator_drill":
        run_class = "operator_drill"
    elif "proof" in name_lower:
        run_class = "named_operator_proof"
    else:
        run_class = "primary_forward"
    quote_counts, market_days = _quote_market_day_counts(quote_path)
    target_date = str(summary.get("target_date") or config.get("target_date") or "")
    return {
        "run_folder": str(folder),
        "run_id": str(summary.get("run_id") or config.get("run_id") or folder.name),
        "target_date": target_date,
        "mode": mode,
        "evidence_mode": evidence_mode or None,
        "run_class": run_class,
        "primary_pool_eligible": run_class == "primary_forward",
        "schema_version": summary.get("schema_version") or config.get("schema_version"),
        "preflight_status": summary.get("preflight_status"),
        "live_forward_gate_status": (
            (_read_json(folder / "live_forward_gate.json").get("status"))
            if (folder / "live_forward_gate.json").is_file()
            else None
        ),
        **quote_counts,
        "quote_market_days": market_days,
        "files": {
            "run_config": _file_stat(config_path, include_hash=True),
            "run_summary": _file_stat(summary_path, include_hash=True),
            "quote_intents": _file_stat(quote_path, include_hash=True),
        },
    }


def build_input_manifest(
    *,
    coverage_json: str | Path,
    snapshots_root: str | Path,
    run_folders: Sequence[str | Path],
    coverage_start: str,
    coverage_end: str,
    books_only_start: str,
    books_only_end: str,
    tune_end: str,
) -> dict[str, Any]:
    coverage_path = Path(coverage_json).resolve()
    snapshots_root = Path(snapshots_root).resolve()
    if not coverage_start <= tune_end < coverage_end:
        raise MakerResearchError("tune_end must split the audited WS window")
    coverage = _read_json(coverage_path)
    if coverage.get("schema_version") != "clob_coverage_audit_v0.3":
        raise MakerResearchError("unexpected coverage-audit schema")
    snapshot_rows = []
    for raw in coverage.get("folders") or []:
        folder = Path(str(raw.get("folder") or "")).resolve()
        target_date = str(raw.get("target_date") or "")
        if not (coverage_start <= target_date <= coverage_end):
            raise MakerResearchError(
                f"coverage artifact contains an out-of-window folder: {folder}"
            )
        try:
            folder.relative_to(snapshots_root)
        except ValueError as exc:
            raise MakerResearchError(f"coverage folder escapes snapshots root: {folder}") from exc
        book_path = folder / "order_books_summary.csv"
        ws_path = folder / "market_ws_events.csv"
        raw_ws_path = folder / "market_ws.jsonl"
        if not book_path.is_file() or book_path.stat().st_size == 0:
            raise MakerResearchError(f"coverage folder lacks order books: {folder}")
        if not ws_path.is_file() or ws_path.stat().st_size == 0:
            raise MakerResearchError(f"coverage folder lacks normalized WS events: {folder}")
        if not raw_ws_path.is_file() or raw_ws_path.stat().st_size == 0:
            raise MakerResearchError(f"coverage folder lacks raw WS tape: {folder}")
        parsed = parse_event_slug(folder.name)
        snapshot_rows.append(
            {
                "folder": str(folder),
                "event_slug": folder.name,
                "market_id": parsed.get("market_id"),
                "target_date": target_date,
                "coverage_classification": raw.get("classification"),
                "files": {
                    "order_books_summary": _file_stat(book_path),
                    "market_ws_events": _file_stat(ws_path),
                    "market_ws_raw": _file_stat(raw_ws_path),
                },
            }
        )
    snapshot_rows.sort(key=lambda row: (row["target_date"], row["market_id"], row["event_slug"]))
    if len(snapshot_rows) != int((coverage.get("summary") or {}).get("folders") or -1):
        raise MakerResearchError("coverage folder count does not match its summary")
    if not _complete_fleet_calendar(snapshot_rows, coverage_start, coverage_end):
        raise MakerResearchError("audited WS window is not a complete 12-market calendar")

    books_only = []
    for folder in sorted(snapshots_root.iterdir()):
        if not folder.is_dir():
            continue
        parsed = parse_event_slug(folder.name)
        target_date = str(parsed.get("target_date") or "")
        if not (books_only_start <= target_date <= books_only_end):
            continue
        book_path = folder / "order_books_summary.csv"
        ws_path = folder / "market_ws_events.csv"
        raw_ws_path = folder / "market_ws.jsonl"
        book_bytes = book_path.stat().st_size if book_path.is_file() else 0
        ws_bytes = ws_path.stat().st_size if ws_path.is_file() else 0
        raw_ws_bytes = raw_ws_path.stat().st_size if raw_ws_path.is_file() else 0
        books_only.append(
            {
                "folder": str(folder.resolve()),
                "event_slug": folder.name,
                "market_id": parsed.get("market_id"),
                "target_date": target_date,
                "classification": (
                    "books_only_no_ws"
                    if book_bytes > 0 and ws_bytes == 0 and raw_ws_bytes == 0
                    else "not_books_only"
                ),
                "book_bytes": book_bytes,
                "ws_csv_bytes": ws_bytes,
                "ws_jsonl_bytes": raw_ws_bytes,
                "toxicity_claim_allowed": False,
            }
        )
    if any(row["classification"] != "books_only_no_ws" for row in books_only):
        raise MakerResearchError("the explicit books-only window contains mixed WS coverage")
    if not _complete_fleet_calendar(books_only, books_only_start, books_only_end):
        raise MakerResearchError("books-only window is not a complete 12-market calendar")

    runs = [classify_run_folder(folder) for folder in run_folders]
    if len({row["run_folder"] for row in runs}) != len(runs):
        raise MakerResearchError("maker run folders must be unique")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "maker_research_input_manifest",
        "created_at_utc": utc_now().isoformat(),
        "research_only": True,
        "promotion_authorized": False,
        "coverage_artifact": _file_stat(coverage_path, include_hash=True),
        "snapshots_root": str(snapshots_root),
        "selection": {
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "books_only_start": books_only_start,
            "books_only_end": books_only_end,
            "tune_end": tune_end,
            "snapshot_selection": "explicit calendar bounds from a completed coverage audit",
            "run_selection": "explicit approved non-quarantine folder list",
            "trade_event_contract": TRADE_EVENT_TYPE,
        },
        "snapshot_folders": snapshot_rows,
        "books_only_folders": books_only,
        "run_folders": runs,
    }
    payload["manifest_hash"] = _hash_payload(
        {key: value for key, value in payload.items() if key != "created_at_utc"}
    )
    return payload


def read_validated_ws_events(folder: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    folder = Path(folder)
    path = folder / "market_ws_events.csv"
    event_types: Counter[str] = Counter()
    unknown_types: Counter[str] = Counter()
    invalid_binding = 0
    missing_received_at = 0
    last_trade_rows = 0
    sized_last_trade_rows = 0
    side_supported_last_trade_rows = 0
    trades = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            event_type = str(row.get("event_type") or "").strip()
            event_types[event_type] += 1
            if event_type not in ACCEPTED_WS_EVENT_TYPES:
                unknown_types[event_type] += 1
            invalid_binding += int(str(row.get("event_slug") or "") != folder.name)
            received = parse_time(row.get("received_at_utc"))
            missing_received_at += int(received is None)
            if event_type != TRADE_EVENT_TYPE:
                continue
            last_trade_rows += 1
            token = str(row.get("asset_id") or row.get("clob_token_id") or "")
            price = finite_float(row.get("price") or row.get("last_trade_price"))
            size = finite_float(
                row.get("size")
                or row.get("trade_size")
                or row.get("shares")
                or row.get("amount")
                or row.get("matched_amount")
                or row.get("maker_amount")
            )
            side = str(row.get("side") or "").upper()
            sized_last_trade_rows += int(size is not None and size > 0.0)
            side_supported_last_trade_rows += int(side in {"BUY", "SELL"})
            if received is None or not token or price is None:
                continue
            trades.append(
                {
                    "trade_id": f"{folder.name}:market_ws_events.csv:{index}",
                    "time": received,
                    "clob_token_id": token,
                    "price": float(price),
                    "size": float(size) if size is not None and size > 0.0 else None,
                    "side": side,
                }
            )
    trades.sort(key=lambda row: (row["time"], row["trade_id"]))
    diagnostics = {
        "event_slug": folder.name,
        "ws_rows": sum(event_types.values()),
        "event_types": dict(sorted(event_types.items())),
        "accepted_event_types": sorted(ACCEPTED_WS_EVENT_TYPES),
        "unknown_event_types": dict(sorted(unknown_types.items())),
        "unknown_ws_event_rows": sum(unknown_types.values()),
        "invalid_event_slug_rows": invalid_binding,
        "missing_received_at_rows": missing_received_at,
        "last_trade_price_rows": last_trade_rows,
        "sized_last_trade_price_rows": sized_last_trade_rows,
        "side_supported_last_trade_price_rows": side_supported_last_trade_rows,
        "event_type_contract_status": (
            "PASS" if not unknown_types and not invalid_binding and not missing_received_at else "BLOCK"
        ),
    }
    return diagnostics, trades


def _book_index(book_rows: Iterable[Mapping[str, Any]]) -> dict[str, tuple[list[Mapping[str, Any]], list[datetime]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in book_rows:
        grouped[str(row.get("clob_token_id") or "")].append(row)
    result = {}
    for token, rows in grouped.items():
        rows.sort(key=lambda row: row["_captured_at"])
        result[token] = (rows, [row["_captured_at"] for row in rows])
    return result


def _prior_book(index: Mapping[str, tuple[list[Mapping[str, Any]], list[datetime]]], token: str, at: datetime):
    rows, times = index.get(str(token), ([], []))
    position = bisect.bisect_right(times, at) - 1
    return rows[position] if position >= 0 else None


def _future_book(
    index: Mapping[str, tuple[list[Mapping[str, Any]], list[datetime]]],
    token: str,
    at: datetime,
    *,
    max_lag_seconds: float = MAX_MARK_LAG_SECONDS,
):
    rows, times = index.get(str(token), ([], []))
    position = bisect.bisect_left(times, at)
    if position >= len(rows):
        return None
    if (times[position] - at).total_seconds() > max_lag_seconds:
        return None
    return rows[position]


def _passive_side(trade: Mapping[str, Any], prior: Mapping[str, Any] | None) -> str:
    side = str(trade.get("side") or "").upper()
    if side == "SELL":
        return "YES_BID"
    if side == "BUY":
        return "YES_ASK"
    if prior:
        price = finite_float(trade.get("price"))
        bid = finite_float(prior.get("best_bid"))
        ask = finite_float(prior.get("best_ask"))
        if price is not None and bid is not None and price <= bid:
            return "YES_BID"
        if price is not None and ask is not None and price >= ask:
            return "YES_ASK"
    return ""


def _markouts(
    *,
    book_index: Mapping[str, tuple[list[Mapping[str, Any]], list[datetime]]],
    token: str,
    trade_time: datetime,
    passive_side: str,
    fill_price: float,
) -> dict[str, float | None]:
    direction = 1.0 if passive_side == "YES_BID" else -1.0
    output = {}
    for label, seconds in MARKOUT_HORIZONS:
        future = _future_book(
            book_index, token, trade_time + timedelta(seconds=seconds)
        )
        midpoint = finite_float((future or {}).get("midpoint"))
        output[label] = (
            direction * (midpoint - fill_price) if midpoint is not None else None
        )
    return output


def _policy_quote_price(
    prior: Mapping[str, Any], passive_side: str, tick_offset: int
) -> float | None:
    bid = finite_float(prior.get("best_bid"))
    ask = finite_float(prior.get("best_ask"))
    tick = finite_float(prior.get("tick_size"), 0.001) or 0.001
    if bid is None or ask is None or ask <= bid:
        return None
    if passive_side == "YES_BID":
        price = bid + tick_offset * tick
    else:
        price = ask - tick_offset * tick
    if not (0.0 < price < 1.0):
        return None
    if passive_side == "YES_BID" and price >= ask:
        return None
    if passive_side == "YES_ASK" and price <= bid:
        return None
    return float(price)


def _financial_fields(
    *,
    quote_price: float,
    fill_size: float,
    midpoint: float,
    passive_side: str,
    markouts: Mapping[str, float | None],
    theoretical_reward_usdc: float | None = None,
) -> dict[str, Any]:
    if passive_side == "YES_BID":
        gross_spread = (midpoint - quote_price) * fill_size
    else:
        gross_spread = (quote_price - midpoint) * fill_size
    maker_fee_equivalent = fee_equivalent(
        fill_size, quote_price, PAPER_CONFIG["maker_fee_rate"]
    )
    theoretical_rebate = maker_fee_equivalent * float(
        PAPER_CONFIG["maker_rebate_pool_share"]
    )
    flattening_cost = fee_equivalent(
        fill_size, quote_price, PAPER_CONFIG["flattening_fee_rate"]
    )
    output: dict[str, Any] = {
        "gross_spread_capture_usdc": gross_spread,
        "modeled_flattening_cost_usdc": flattening_cost,
        "theoretical_maker_fee_equivalent_usdc": maker_fee_equivalent,
        "theoretical_maker_rebate_usdc": theoretical_rebate,
        "theoretical_liquidity_reward_usdc": theoretical_reward_usdc,
        "economics_evidence_basis": (
            "repository_default_parameters_stale_theoretical_not_actual_payout"
        ),
    }
    for label, _seconds in MARKOUT_HORIZONS:
        per_share = markouts.get(label)
        output[f"markout_{label}_per_share"] = per_share
        output[f"markout_{label}_usdc"] = (
            per_share * fill_size if per_share is not None else None
        )
    markout_30m_usdc = output.get("markout_30m_usdc")
    output["adverse_selection_loss_30m_usdc"] = (
        max(0.0, -float(markout_30m_usdc))
        if markout_30m_usdc is not None
        else None
    )
    output["net_after_modeled_costs_30m_usdc"] = (
        float(markout_30m_usdc) - flattening_cost
        if markout_30m_usdc is not None
        else None
    )
    output["net_with_theoretical_rebate_30m_usdc"] = (
        output["net_after_modeled_costs_30m_usdc"] + theoretical_rebate
        if output["net_after_modeled_costs_30m_usdc"] is not None
        else None
    )
    return output


def _fill_row(
    *,
    evidence_source: str,
    policy_id: str,
    target_date: str,
    market_id: str,
    event_slug: str,
    trade: Mapping[str, Any],
    passive_side: str,
    quote_time: datetime,
    quote_price: float,
    fill_size: float,
    midpoint: float,
    markouts: Mapping[str, float | None],
    run_class: str = "",
    run_folder: str = "",
    run_id: str = "",
    theoretical_reward_usdc: float | None = None,
) -> dict[str, Any]:
    row = {
        "evidence_source": evidence_source,
        "policy_id": policy_id,
        "run_class": run_class,
        "run_folder": run_folder,
        "run_id": run_id,
        "target_date": target_date,
        "market_id": market_id,
        "event_slug": event_slug,
        "clob_token_id": trade.get("clob_token_id"),
        "trade_id": trade.get("trade_id"),
        "trade_time_utc": trade["time"].isoformat(),
        "trade_side": trade.get("side") or "",
        "passive_side": passive_side,
        "quote_time_utc": quote_time.isoformat(),
        "quote_age_seconds": (trade["time"] - quote_time).total_seconds(),
        "quote_price": quote_price,
        "fill_size": fill_size,
        "through_trade_price": trade.get("price"),
        "through_trade_size": trade.get("size"),
        "conservative_fill_rule": (
            "explicit_last_trade_price_strict_trade_through_recorded_size"
        ),
    }
    row.update(
        _financial_fields(
            quote_price=quote_price,
            fill_size=fill_size,
            midpoint=midpoint,
            passive_side=passive_side,
            markouts=markouts,
            theoretical_reward_usdc=theoretical_reward_usdc,
        )
    )
    return {key: _rounded(value) for key, value in row.items()}


def reconstruct_market_day(
    entry: Mapping[str, Any],
    *,
    tune_end: str,
    quote_ttl_seconds: float = QUOTE_TTL_SECONDS,
    quote_size: float = SYNTHETIC_QUOTE_SIZE,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Reconstruct one folder and release it before the caller advances."""

    folder = Path(str(entry["folder"]))
    target_date = str(entry["target_date"])
    market_id = str(entry["market_id"])
    split = "tune" if target_date <= tune_end else "holdout"
    book_rows = load_book_rows([folder])
    ws_diagnostics, trades = read_validated_ws_events(folder)
    book_index = _book_index(book_rows)

    spreads = [finite_float(row.get("spread")) for row in book_rows]
    top_depth = [
        (finite_float(row.get("bid_size_at_best"), 0.0) or 0.0)
        + (finite_float(row.get("ask_size_at_best"), 0.0) or 0.0)
        for row in book_rows
    ]
    depth_1pct = [
        (finite_float(row.get("bid_depth_1pct"), 0.0) or 0.0)
        + (finite_float(row.get("ask_depth_1pct"), 0.0) or 0.0)
        for row in book_rows
    ]
    depth_all = [
        (finite_float(row.get("bid_depth_all"), 0.0) or 0.0)
        + (finite_float(row.get("ask_depth_all"), 0.0) or 0.0)
        for row in book_rows
    ]

    trade_markouts = []
    for trade in trades:
        prior = _prior_book(
            book_index, str(trade["clob_token_id"]), trade["time"]
        )
        if prior is None:
            continue
        passive_side = _passive_side(trade, prior)
        if not passive_side:
            continue
        markouts = _markouts(
            book_index=book_index,
            token=str(trade["clob_token_id"]),
            trade_time=trade["time"],
            passive_side=passive_side,
            fill_price=float(trade["price"]),
        )
        trade_markouts.append(
            {
                "target_date": target_date,
                "market_id": market_id,
                "event_slug": folder.name,
                "trade_id": trade["trade_id"],
                "trade_time_utc": trade["time"].isoformat(),
                "clob_token_id": trade["clob_token_id"],
                "trade_side": trade.get("side") or "",
                "passive_side": passive_side,
                "trade_price": trade["price"],
                "trade_size": trade.get("size"),
                "prior_book_age_seconds": (
                    trade["time"] - prior["_captured_at"]
                ).total_seconds(),
                **{
                    f"markout_{label}_per_share": _rounded(markouts[label])
                    for label, _seconds in MARKOUT_HORIZONS
                },
            }
        )

    fills = []
    sized_trades = [row for row in trades if (finite_float(row.get("size"), 0.0) or 0.0) > 0.0]
    for policy_id, tick_offset in POLICY_TICK_OFFSETS.items():
        remaining_by_quote: dict[tuple[str, str, str], float] = {}
        for trade in sized_trades:
            token = str(trade["clob_token_id"])
            prior = _prior_book(book_index, token, trade["time"])
            if prior is None:
                continue
            age_seconds = (trade["time"] - prior["_captured_at"]).total_seconds()
            if age_seconds < 0.0 or age_seconds > float(quote_ttl_seconds):
                continue
            passive_side = _passive_side(trade, prior)
            if not passive_side:
                continue
            quote_price = _policy_quote_price(prior, passive_side, tick_offset)
            if quote_price is None or not strict_trade_through(
                passive_side, float(trade["price"]), quote_price
            ):
                continue
            quote_key = (
                token,
                prior["_captured_at"].isoformat(),
                passive_side,
            )
            remaining = remaining_by_quote.setdefault(quote_key, float(quote_size))
            if remaining <= 0.0:
                continue
            fill_size = min(remaining, float(trade["size"]))
            if fill_size <= 0.0:
                continue
            remaining_by_quote[quote_key] = remaining - fill_size
            midpoint = finite_float(prior.get("midpoint"))
            if midpoint is None:
                continue
            markouts = _markouts(
                book_index=book_index,
                token=token,
                trade_time=trade["time"],
                passive_side=passive_side,
                fill_price=quote_price,
            )
            fills.append(
                _fill_row(
                    evidence_source="synthetic_periodic_book_quote",
                    policy_id=policy_id,
                    target_date=target_date,
                    market_id=market_id,
                    event_slug=folder.name,
                    trade=trade,
                    passive_side=passive_side,
                    quote_time=prior["_captured_at"],
                    quote_price=quote_price,
                    fill_size=fill_size,
                    midpoint=midpoint,
                    markouts=markouts,
                )
            )

    market_day = {
        "target_date": target_date,
        "market_id": market_id,
        "event_slug": folder.name,
        "split": split,
        "book_rows": len(book_rows),
        "two_sided_book_rows": sum(
            finite_float(row.get("best_bid")) is not None
            and finite_float(row.get("best_ask")) is not None
            for row in book_rows
        ),
        "mean_spread": _rounded(_mean(spreads)),
        "median_spread": _rounded(_median(spreads)),
        "mean_top_depth": _rounded(_mean(top_depth)),
        "mean_depth_1pct": _rounded(_mean(depth_1pct)),
        "mean_depth_all": _rounded(_mean(depth_all)),
        "ws_rows": ws_diagnostics["ws_rows"],
        "ws_event_types_json": ws_diagnostics["event_types"],
        "unknown_ws_event_rows": ws_diagnostics["unknown_ws_event_rows"],
        "last_trade_price_rows": ws_diagnostics["last_trade_price_rows"],
        "sized_last_trade_price_rows": ws_diagnostics["sized_last_trade_price_rows"],
        "side_supported_last_trade_price_rows": ws_diagnostics[
            "side_supported_last_trade_price_rows"
        ],
        "book_matched_trade_rows": len(trade_markouts),
        "toxicity_supported": bool(trade_markouts),
        "mean_passive_markout_1m_per_share": _rounded(
            _mean(row.get("markout_1m_per_share") for row in trade_markouts)
        ),
        "mean_passive_markout_5m_per_share": _rounded(
            _mean(row.get("markout_5m_per_share") for row in trade_markouts)
        ),
        "mean_passive_markout_30m_per_share": _rounded(
            _mean(row.get("markout_30m_per_share") for row in trade_markouts)
        ),
        "negative_markout_30m_rows": sum(
            finite_float(row.get("markout_30m_per_share")) is not None
            and float(row["markout_30m_per_share"]) < 0.0
            for row in trade_markouts
        ),
    }
    del book_index, book_rows, trades
    gc.collect()
    return market_day, ws_diagnostics, trade_markouts, fills


def summarize_policy_market_days(
    manifest: Mapping[str, Any], fills: Sequence[Mapping[str, Any]], *, tune_end: str
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in fills:
        grouped[(str(row["target_date"]), str(row["market_id"]), str(row["policy_id"]))].append(row)
    output = []
    for entry in manifest.get("snapshot_folders") or []:
        target_date = str(entry["target_date"])
        market_id = str(entry["market_id"])
        for policy_id in POLICY_TICK_OFFSETS:
            rows = grouped.get((target_date, market_id, policy_id), [])
            row: dict[str, Any] = {
                "target_date": target_date,
                "market_id": market_id,
                "event_slug": entry["event_slug"],
                "split": "tune" if target_date <= tune_end else "holdout",
                "policy_id": policy_id,
                "conservative_fill_count": len(rows),
                "filled_shares": _sum(rows, "fill_size"),
                "gross_spread_capture_usdc": _sum(rows, "gross_spread_capture_usdc"),
                "adverse_selection_loss_30m_usdc": _sum(
                    rows, "adverse_selection_loss_30m_usdc"
                ),
                "modeled_flattening_cost_usdc": _sum(
                    rows, "modeled_flattening_cost_usdc"
                ),
                "theoretical_maker_fee_equivalent_usdc": _sum(
                    rows, "theoretical_maker_fee_equivalent_usdc"
                ),
                "theoretical_maker_rebate_usdc": _sum(
                    rows, "theoretical_maker_rebate_usdc"
                ),
                "theoretical_liquidity_reward_usdc": None,
            }
            for label, _seconds in MARKOUT_HORIZONS:
                complete = [
                    item
                    for item in rows
                    if finite_float(item.get(f"markout_{label}_per_share")) is not None
                ]
                row[f"markout_{label}_complete_fill_count"] = len(complete)
                row[f"markout_{label}_usdc"] = _sum(complete, f"markout_{label}_usdc")
                row[f"mean_markout_{label}_per_share"] = _mean(
                    item.get(f"markout_{label}_per_share") for item in complete
                )
            complete_30m = [
                item
                for item in rows
                if finite_float(item.get("net_after_modeled_costs_30m_usdc")) is not None
            ]
            row["modeled_flattening_cost_30m_complete_usdc"] = _sum(
                complete_30m, "modeled_flattening_cost_usdc"
            )
            row["theoretical_maker_rebate_30m_complete_usdc"] = _sum(
                complete_30m, "theoretical_maker_rebate_usdc"
            )
            row["net_after_modeled_costs_30m_usdc"] = _sum(
                complete_30m, "net_after_modeled_costs_30m_usdc"
            )
            row["net_with_theoretical_rebate_30m_usdc"] = _sum(
                complete_30m, "net_with_theoretical_rebate_30m_usdc"
            )
            output.append({key: _rounded(value) for key, value in row.items()})
    return output


def _percentile(sorted_values: Sequence[float], probability: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * float(probability)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    fraction = position - lower
    return float(
        sorted_values[lower] * (1.0 - fraction)
        + sorted_values[upper] * fraction
    )


def _stable_seed(*parts: Any, seed: int = BOOTSTRAP_SEED) -> int:
    digest = hashlib.sha256(
        (str(seed) + "|" + "|".join(str(part) for part in parts)).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big")


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    seed: int,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Return a deterministic percentile interval over whole supplied units."""

    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {
            "n": 0,
            "mean": None,
            "ci_low": None,
            "ci_high": None,
            "positive_count": 0,
            "negative_count": 0,
            "tie_count": 0,
            "seed": int(seed),
            "replicates": int(replicates),
        }
    count = len(clean)
    means: list[float] = []
    if replicates > 0:
        rng = random.Random(seed)
        for _index in range(int(replicates)):
            means.append(
                sum(clean[rng.randrange(count)] for _item in range(count)) / count
            )
        means.sort()
    return {
        "n": count,
        "mean": _rounded(sum(clean) / count),
        "ci_low": _rounded(_percentile(means, 0.025)),
        "ci_high": _rounded(_percentile(means, 0.975)),
        "positive_count": sum(value > 0.0 for value in clean),
        "negative_count": sum(value < 0.0 for value in clean),
        "tie_count": sum(value == 0.0 for value in clean),
        "seed": int(seed),
        "replicates": int(replicates),
    }


def _aggregate_rows_by_date(
    rows: Sequence[Mapping[str, Any]], metrics: Sequence[str]
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["target_date"])].append(row)
    output = []
    for target_date, date_rows in sorted(grouped.items()):
        output.append(
            {
                "target_date": target_date,
                "market_days": len(date_rows),
                **{metric: _rounded(_sum(date_rows, metric)) for metric in metrics},
            }
        )
    return output


def summarize_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    split: str,
    policy_id: str,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row.get("split") == split and row.get("policy_id") == policy_id
    ]
    fleet_dates = _aggregate_rows_by_date(selected, ADDITIVE_POLICY_METRICS)
    market_day_values = [
        finite_float(row.get("net_after_modeled_costs_30m_usdc"), 0.0) or 0.0
        for row in selected
    ]
    fleet_date_values = [
        finite_float(row.get("net_after_modeled_costs_30m_usdc"), 0.0) or 0.0
        for row in fleet_dates
    ]
    complete_fills = int(_sum(selected, "markout_30m_complete_fill_count"))
    active_dates = sum(
        (finite_float(row.get("markout_30m_usdc"), 0.0) or 0.0) != 0.0
        or (finite_float(row.get("conservative_fill_count"), 0.0) or 0.0) > 0.0
        for row in fleet_dates
    )
    return {
        "split": split,
        "policy_id": policy_id,
        "market_days": len(selected),
        "fleet_dates": len(fleet_dates),
        "active_fill_fleet_dates": active_dates,
        "totals": {
            metric: _rounded(_sum(selected, metric))
            for metric in ADDITIVE_POLICY_METRICS
        },
        "markout_30m_complete_fill_count": complete_fills,
        "equal_market_day": bootstrap_mean_ci(
            market_day_values,
            seed=_stable_seed(split, policy_id, "market_day", seed=seed),
            replicates=replicates,
        ),
        "equal_fleet_date": bootstrap_mean_ci(
            fleet_date_values,
            seed=_stable_seed(split, policy_id, "fleet_date", seed=seed),
            replicates=replicates,
        ),
        "fleet_date_rows": fleet_dates,
    }


def paired_policy_comparison(
    rows: Sequence[Mapping[str, Any]],
    *,
    split: str,
    variant_policy_id: str,
    baseline_policy_id: str = BASELINE_POLICY,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    index = {
        (str(row["target_date"]), str(row["market_id"]), str(row["policy_id"])): row
        for row in rows
        if row.get("split") == split
    }
    pairs = []
    market_days = sorted(
        {
            (str(row["target_date"]), str(row["market_id"]))
            for row in rows
            if row.get("split") == split
        }
    )
    for target_date, market_id in market_days:
        variant = index.get((target_date, market_id, variant_policy_id))
        baseline = index.get((target_date, market_id, baseline_policy_id))
        if variant is None or baseline is None:
            continue
        variant_net = finite_float(
            variant.get("net_after_modeled_costs_30m_usdc"), 0.0
        ) or 0.0
        baseline_net = finite_float(
            baseline.get("net_after_modeled_costs_30m_usdc"), 0.0
        ) or 0.0
        pairs.append(
            {
                "target_date": target_date,
                "market_id": market_id,
                "variant_policy_id": variant_policy_id,
                "baseline_policy_id": baseline_policy_id,
                "variant_net_usdc": _rounded(variant_net),
                "baseline_net_usdc": _rounded(baseline_net),
                "delta_net_usdc": _rounded(variant_net - baseline_net),
                "variant_complete_fills": int(
                    finite_float(
                        variant.get("markout_30m_complete_fill_count"), 0.0
                    )
                    or 0.0
                ),
                "baseline_complete_fills": int(
                    finite_float(
                        baseline.get("markout_30m_complete_fill_count"), 0.0
                    )
                    or 0.0
                ),
            }
        )
    by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in pairs:
        by_date[str(row["target_date"])].append(row)
    daily = [
        {
            "target_date": target_date,
            "paired_market_days": len(date_rows),
            "variant_net_usdc": _rounded(_sum(date_rows, "variant_net_usdc")),
            "baseline_net_usdc": _rounded(_sum(date_rows, "baseline_net_usdc")),
            "delta_net_usdc": _rounded(_sum(date_rows, "delta_net_usdc")),
            "variant_complete_fills": int(_sum(date_rows, "variant_complete_fills")),
            "baseline_complete_fills": int(_sum(date_rows, "baseline_complete_fills")),
        }
        for target_date, date_rows in sorted(by_date.items())
    ]
    market_day_ci = bootstrap_mean_ci(
        [float(row["delta_net_usdc"]) for row in pairs],
        seed=_stable_seed(split, variant_policy_id, "paired_market_day", seed=seed),
        replicates=replicates,
    )
    fleet_date_ci = bootstrap_mean_ci(
        [float(row["delta_net_usdc"]) for row in daily],
        seed=_stable_seed(split, variant_policy_id, "paired_fleet_date", seed=seed),
        replicates=replicates,
    )
    complete_fills = sum(int(row["variant_complete_fills"]) for row in daily)
    active_dates = sum(int(row["variant_complete_fills"] > 0) for row in daily)
    support_status = (
        "SUPPORTED"
        if complete_fills >= MIN_SELECTION_COMPLETE_FILLS
        and active_dates >= MIN_SELECTION_ACTIVE_DATES
        else "BLOCK_INSUFFICIENT_EXPLICIT_TRADE_SUPPORT"
    )
    confirmable = (
        support_status == "SUPPORTED"
        and len(daily) >= MIN_CONFIRMATION_FLEET_DATES
        and fleet_date_ci["ci_low"] is not None
    )
    return {
        "split": split,
        "variant_policy_id": variant_policy_id,
        "baseline_policy_id": baseline_policy_id,
        "paired_market_days": len(pairs),
        "paired_fleet_dates": len(daily),
        "variant_complete_fills": complete_fills,
        "variant_active_fill_fleet_dates": active_dates,
        "support_status": support_status,
        "equal_market_day_delta": market_day_ci,
        "fleet_date_cluster_delta": fleet_date_ci,
        "confirmation_gate": {
            "status": (
                "PASS"
                if confirmable
                and float(fleet_date_ci["mean"] or 0.0) > 0.0
                and float(fleet_date_ci["ci_low"] or 0.0) > 0.0
                else "BLOCK"
            ),
            "required_complete_fills": MIN_SELECTION_COMPLETE_FILLS,
            "required_active_fill_fleet_dates": MIN_SELECTION_ACTIVE_DATES,
            "required_paired_fleet_dates": MIN_CONFIRMATION_FLEET_DATES,
            "reason": (
                "positive paired fleet-date delta with CI above zero"
                if confirmable
                and float(fleet_date_ci["mean"] or 0.0) > 0.0
                and float(fleet_date_ci["ci_low"] or 0.0) > 0.0
                else "insufficient support or paired CI does not clear zero"
            ),
        },
        "paired_fleet_date_rows": daily,
    }


def analyze_synthetic_policies(
    rows: Sequence[Mapping[str, Any]],
    *,
    tune_end: str,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    tune_summaries = [
        summarize_policy(
            rows,
            split="tune",
            policy_id=policy_id,
            seed=seed,
            replicates=replicates,
        )
        for policy_id in POLICY_TICK_OFFSETS
    ]
    tune_comparisons = [
        paired_policy_comparison(
            rows,
            split="tune",
            variant_policy_id=policy_id,
            seed=seed,
            replicates=replicates,
        )
        for policy_id in POLICY_TICK_OFFSETS
        if policy_id != BASELINE_POLICY
    ]
    eligible = [
        row
        for row in tune_comparisons
        if row["support_status"] == "SUPPORTED"
        and float((row["fleet_date_cluster_delta"] or {}).get("mean") or 0.0) > 0.0
    ]
    eligible.sort(
        key=lambda row: (
            float((row["fleet_date_cluster_delta"] or {}).get("mean") or 0.0),
            row["variant_policy_id"],
        ),
        reverse=True,
    )
    selected = eligible[0]["variant_policy_id"] if eligible else None
    selection = {
        "status": "SELECTED_FOR_LOCKED_HOLDOUT" if selected else "BLOCK_NO_TUNE_WINNER",
        "selected_policy_id": selected,
        "tune_end": tune_end,
        "criterion": (
            "highest positive equal-fleet-date mean delta in net-after-modeled-costs; "
            "minimum explicit-trade fill and active-date support"
        ),
        "theoretical_incentives_used_for_selection": False,
        "reason": (
            "one tune-supported policy had the largest positive paired mean"
            if selected
            else "no non-baseline policy had both minimum support and a positive paired tune mean"
        ),
    }
    holdout_summaries = [
        summarize_policy(
            rows,
            split="holdout",
            policy_id=policy_id,
            seed=seed,
            replicates=replicates,
        )
        for policy_id in (
            [BASELINE_POLICY, selected] if selected else [BASELINE_POLICY]
        )
    ]
    holdout_comparison = (
        paired_policy_comparison(
            rows,
            split="holdout",
            variant_policy_id=selected,
            seed=seed,
            replicates=replicates,
        )
        if selected
        else None
    )
    decision = (
        "RESEARCH_CANDIDATE_SURVIVED_LOCKED_HOLDOUT"
        if holdout_comparison
        and (holdout_comparison.get("confirmation_gate") or {}).get("status") == "PASS"
        else "STOP_NO_POLICY_SURVIVED_LOCKED_HOLDOUT"
    )
    return {
        "tune_end": tune_end,
        "baseline_policy_id": BASELINE_POLICY,
        "policy_definitions": {
            key: {"tick_offset_from_touch": value}
            for key, value in POLICY_TICK_OFFSETS.items()
        },
        "execution_assumptions": {
            "fill_rule": "explicit last_trade_price strict-through only",
            "quote_ttl_seconds": QUOTE_TTL_SECONDS,
            "quote_size_shares": SYNTHETIC_QUOTE_SIZE,
            "queue_priority_modeled": False,
            "actual_rebate_payout_available": False,
        },
        "tune": {
            "policy_summaries": tune_summaries,
            "paired_vs_baseline": tune_comparisons,
        },
        "selection": selection,
        "holdout": {
            "policy_summaries": holdout_summaries,
            "selected_vs_baseline": holdout_comparison,
        },
        "decision": decision,
        "promotion_authorized": False,
    }


def summarize_microstructure(
    market_days: Sequence[Mapping[str, Any]],
    trade_markouts: Sequence[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Summarize books and explicit-trade toxicity without row-count weighting."""

    output: dict[str, Any] = {}
    for split in ("tune", "holdout"):
        days = [row for row in market_days if row.get("split") == split]
        dates = sorted({str(row["target_date"]) for row in days})
        book_metrics = {}
        for metric in (
            "mean_spread",
            "mean_top_depth",
            "mean_depth_1pct",
            "mean_depth_all",
        ):
            market_values = [
                float(value)
                for value in (finite_float(row.get(metric)) for row in days)
                if value is not None
            ]
            date_values = []
            for target_date in dates:
                value = _mean(
                    finite_float(row.get(metric))
                    for row in days
                    if row.get("target_date") == target_date
                )
                if value is not None:
                    date_values.append(value)
            book_metrics[metric] = {
                "equal_market_day": bootstrap_mean_ci(
                    market_values,
                    seed=_stable_seed(split, metric, "market_day", seed=seed),
                    replicates=replicates,
                ),
                "equal_fleet_date": bootstrap_mean_ci(
                    date_values,
                    seed=_stable_seed(split, metric, "fleet_date", seed=seed),
                    replicates=replicates,
                ),
            }
        split_dates = set(dates)
        marks = [
            row for row in trade_markouts if str(row.get("target_date")) in split_dates
        ]
        markout_metrics = {}
        for label, _seconds in MARKOUT_HORIZONS:
            metric = f"markout_{label}_per_share"
            trade_values = [
                float(value)
                for value in (finite_float(row.get(metric)) for row in marks)
                if value is not None
            ]
            date_values = []
            for target_date in dates:
                value = _mean(
                    finite_float(row.get(metric))
                    for row in marks
                    if row.get("target_date") == target_date
                )
                if value is not None:
                    date_values.append(value)
            markout_metrics[metric] = {
                "explicit_trade_rows": len(trade_values),
                "row_weighted_mean": _rounded(_mean(trade_values)),
                "equal_supported_fleet_date": bootstrap_mean_ci(
                    date_values,
                    seed=_stable_seed(split, metric, "explicit_trade_date", seed=seed),
                    replicates=replicates,
                ),
                "interpretation": "negative values are adverse to the inferred passive side",
            }
        output[split] = {
            "market_days": len(days),
            "fleet_dates": len(dates),
            "book_metrics": book_metrics,
            "explicit_last_trade_price_rows": sum(
                int(finite_float(row.get("last_trade_price_rows"), 0.0) or 0.0)
                for row in days
            ),
            "book_matched_explicit_trade_rows": len(marks),
            "trade_markouts": markout_metrics,
        }
    return output


def _score_recorded_quote_legs(
    *,
    run: Mapping[str, Any],
    entry: Mapping[str, Any],
    legs: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    book_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    book_index = _book_index(book_rows)
    legs_by_token_side: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for leg in legs:
        legs_by_token_side[(str(leg.get("clob_token_id") or ""), str(leg.get("side") or ""))].append(leg)
    for group in legs_by_token_side.values():
        group.sort(key=lambda leg: (leg["quote_time"], str(leg.get("leg_id") or "")))
    remaining = {
        str(leg.get("leg_id") or ""): float(leg.get("quote_size") or 0.0)
        for leg in legs
    }
    output = []
    for trade in trades:
        trade_size = finite_float(trade.get("size"))
        if trade_size is None or trade_size <= 0.0:
            continue
        token = str(trade.get("clob_token_id") or "")
        prior = _prior_book(book_index, token, trade["time"])
        passive_side = _passive_side(trade, prior)
        if not passive_side or prior is None:
            continue
        candidates = []
        for leg in legs_by_token_side.get((token, passive_side), []):
            expires = leg.get("quote_expires_at")
            if not isinstance(expires, datetime):
                continue
            if not (leg["quote_time"] <= trade["time"] < expires):
                continue
            quote_price = finite_float(leg.get("quote_price"))
            if quote_price is None or not strict_trade_through(
                passive_side, float(trade["price"]), quote_price
            ):
                continue
            leg_id = str(leg.get("leg_id") or "")
            if remaining.get(leg_id, 0.0) <= 0.0:
                continue
            candidates.append(leg)
        if not candidates:
            continue
        # Superseded quotes are expired by quote_legs; this tie-break is stable
        # for duplicate captured rows and allocates one recorded trade only once.
        leg = max(candidates, key=lambda item: (item["quote_time"], str(item.get("leg_id") or "")))
        leg_id = str(leg.get("leg_id") or "")
        fill_size = min(float(trade_size), remaining[leg_id])
        if fill_size <= 0.0:
            continue
        midpoint = finite_float(prior.get("midpoint"))
        quote_price = finite_float(leg.get("quote_price"))
        if midpoint is None or quote_price is None:
            continue
        remaining[leg_id] -= fill_size
        markouts = _markouts(
            book_index=book_index,
            token=token,
            trade_time=trade["time"],
            passive_side=passive_side,
            fill_price=quote_price,
        )
        output.append(
            _fill_row(
                evidence_source="recorded_quote_intent",
                policy_id="recorded_quote_intent",
                run_class=str(run["run_class"]),
                run_folder=str(run["run_folder"]),
                run_id=str(run["run_id"]),
                target_date=str(entry["target_date"]),
                market_id=str(entry["market_id"]),
                event_slug=str(entry["event_slug"]),
                trade=trade,
                passive_side=passive_side,
                quote_time=leg["quote_time"],
                quote_price=quote_price,
                fill_size=fill_size,
                midpoint=midpoint,
                markouts=markouts,
            )
        )
    return output


def _summarize_fill_group(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "conservative_fill_count": len(rows),
        "filled_shares": _rounded(_sum(rows, "fill_size")),
        "gross_spread_capture_usdc": _rounded(
            _sum(rows, "gross_spread_capture_usdc")
        ),
        "adverse_selection_loss_30m_usdc": _rounded(
            _sum(rows, "adverse_selection_loss_30m_usdc")
        ),
        "modeled_flattening_cost_usdc": _rounded(
            _sum(rows, "modeled_flattening_cost_usdc")
        ),
        "theoretical_maker_fee_equivalent_usdc": _rounded(
            _sum(rows, "theoretical_maker_fee_equivalent_usdc")
        ),
        "theoretical_maker_rebate_usdc": _rounded(
            _sum(rows, "theoretical_maker_rebate_usdc")
        ),
        "theoretical_liquidity_reward_usdc": None,
    }
    for label, _seconds in MARKOUT_HORIZONS:
        complete = [
            row
            for row in rows
            if finite_float(row.get(f"markout_{label}_per_share")) is not None
        ]
        output[f"markout_{label}_complete_fill_count"] = len(complete)
        output[f"markout_{label}_usdc"] = _rounded(
            _sum(complete, f"markout_{label}_usdc")
        )
        output[f"mean_markout_{label}_per_share"] = _rounded(
            _mean(finite_float(row.get(f"markout_{label}_per_share")) for row in complete)
        )
    complete_30m = [
        row
        for row in rows
        if finite_float(row.get("net_after_modeled_costs_30m_usdc")) is not None
    ]
    output["modeled_flattening_cost_30m_complete_usdc"] = _rounded(
        _sum(complete_30m, "modeled_flattening_cost_usdc")
    )
    output["theoretical_maker_rebate_30m_complete_usdc"] = _rounded(
        _sum(complete_30m, "theoretical_maker_rebate_usdc")
    )
    output["net_after_modeled_costs_30m_usdc"] = _rounded(
        _sum(complete_30m, "net_after_modeled_costs_30m_usdc")
    )
    output["net_with_theoretical_rebate_30m_usdc"] = _rounded(
        _sum(complete_30m, "net_with_theoretical_rebate_30m_usdc")
    )
    return output


def score_quote_runs(
    manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Score only approved run folders and only against validated WS folders."""

    snapshot_index = {
        str(row["event_slug"]): row for row in manifest.get("snapshot_folders") or []
    }
    fills: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for run in manifest.get("run_folders") or []:
        event_slugs = set(run.get("event_slugs") or [])
        supported_slugs = sorted(event_slugs.intersection(snapshot_index))
        run_fills: list[dict[str, Any]] = []
        processed_slugs: set[str] = set()
        if supported_slugs:
            run_folder = Path(str(run["run_folder"]))
            quote_rows, run_configs = load_quote_rows([run_folder])
            config = {**PAPER_CONFIG, **(run_configs.get(str(run_folder)) or {})}
            legs = quote_legs(quote_rows, config)
            legs_by_event: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
            for leg in legs:
                legs_by_event[str(leg.get("event_slug") or "")].append(leg)
            for event_slug in supported_slugs:
                entry = snapshot_index[event_slug]
                folder = Path(str(entry["folder"]))
                book_rows = load_book_rows([folder])
                ws_diagnostics, trades = read_validated_ws_events(folder)
                if ws_diagnostics["event_type_contract_status"] != "PASS":
                    raise MakerResearchError(
                        f"WS event contract blocks quote scoring: {event_slug}"
                    )
                event_fills = _score_recorded_quote_legs(
                    run=run,
                    entry=entry,
                    legs=legs_by_event.get(event_slug, []),
                    trades=trades,
                    book_rows=book_rows,
                )
                run_fills.extend(event_fills)
                processed_slugs.add(event_slug)
                del book_rows, trades, event_fills
                gc.collect()
            del quote_rows, legs, legs_by_event
            gc.collect()
        grouped_fills: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
        for row in run_fills:
            grouped_fills[(str(row["target_date"]), str(row["market_id"]))].append(row)
        for base in run.get("quote_market_days") or []:
            target_date = str(base.get("target_date") or "")
            market_id = str(base.get("market_id") or "")
            event_slug = str(base.get("event_slug") or "")
            rows = grouped_fills.get((target_date, market_id), [])
            if event_slug not in snapshot_index:
                coverage_status = "no_valid_ws_trade_tape"
            elif event_slug not in processed_slugs:
                coverage_status = "validated_ws_not_processed"
            elif rows:
                coverage_status = "validated_ws_explicit_trade_fill"
            else:
                coverage_status = "validated_ws_no_explicit_trade_fill"
            day_rows.append(
                {
                    "run_class": run["run_class"],
                    "run_folder": run["run_folder"],
                    "run_id": run["run_id"],
                    "target_date": target_date,
                    "market_id": market_id,
                    "event_slug": event_slug,
                    "coverage_status": coverage_status,
                    "quote_rows": base.get("quote_rows", 0),
                    "quote_permission_rows": base.get("quote_permission_rows", 0),
                    "quote_legs": base.get("quote_legs", 0),
                    **_summarize_fill_group(rows),
                }
            )
        fills.extend(run_fills)
        diagnostics.append(
            {
                "run_class": run["run_class"],
                "run_folder": run["run_folder"],
                "run_id": run["run_id"],
                "target_date": run.get("target_date"),
                "quote_rows": run.get("quote_rows", 0),
                "quote_permission_rows": run.get("quote_permission_rows", 0),
                "quote_legs": run.get("quote_legs", 0),
                "event_slug_count": len(event_slugs),
                "validated_ws_event_slug_count": len(supported_slugs),
                "scored_event_slug_count": len(processed_slugs),
                "explicit_trade_fill_count": len(run_fills),
                "coverage_status": (
                    "validated_ws_scored" if supported_slugs else "no_valid_ws_trade_tape"
                ),
            }
        )
    return fills, day_rows, diagnostics


def render_report(payload: Mapping[str, Any]) -> str:
    return render_maker_report(payload)


def run_research(
    *,
    coverage_json: str | Path,
    snapshots_root: str | Path,
    run_folders: Sequence[str | Path],
    historical_reports: Sequence[str | Path],
    output_root: str | Path,
    read_only_data_root: str | Path,
    coverage_start: str,
    coverage_end: str,
    books_only_start: str,
    books_only_end: str,
    tune_end: str,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    out_root = _safe_output_root(output_root, read_only_data_root=read_only_data_root)
    manifest = build_input_manifest(
        coverage_json=coverage_json,
        snapshots_root=snapshots_root,
        run_folders=run_folders,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        books_only_start=books_only_start,
        books_only_end=books_only_end,
        tune_end=tune_end,
    )
    _write_json(out_root / "input_manifest.json", manifest)
    market_days: list[dict[str, Any]] = []
    ws_diagnostics: list[dict[str, Any]] = []
    trade_markouts: list[dict[str, Any]] = []
    synthetic_fills: list[dict[str, Any]] = []
    entries = manifest.get("snapshot_folders") or []
    for index, entry in enumerate(entries, start=1):
        market_day, diagnostics, marks, fills = reconstruct_market_day(
            entry, tune_end=tune_end
        )
        if diagnostics["event_type_contract_status"] != "PASS":
            raise MakerResearchError(
                f"WS contract validation failed for {entry['event_slug']}"
            )
        market_days.append(market_day)
        ws_diagnostics.append(diagnostics)
        trade_markouts.extend(marks)
        synthetic_fills.extend(fills)
        if index % 12 == 0 or index == len(entries):
            print(
                f"maker reconstruction {index}/{len(entries)} market-days; "
                f"explicit trades={sum(row['last_trade_price_rows'] for row in ws_diagnostics)}; "
                f"synthetic fills={len(synthetic_fills)}",
                flush=True,
            )
    ws_summary = summarize_ws_validation(
        ws_diagnostics, books_only_folders=len(manifest.get("books_only_folders") or [])
    )
    ws_payload = {"summary": ws_summary, "market_days": ws_diagnostics}
    policy_days = summarize_policy_market_days(
        manifest, synthetic_fills, tune_end=tune_end
    )
    synthetic = analyze_synthetic_policies(
        policy_days, tune_end=tune_end, seed=seed, replicates=replicates
    )
    synthetic["posthoc_holdout_diagnostics"] = summarize_selected_holdout_fills(
        synthetic_fills,
        selected_policy_id=(synthetic.get("selection") or {}).get("selected_policy_id"),
        tune_end=tune_end,
    )
    microstructure = summarize_microstructure(
        market_days, trade_markouts, seed=seed, replicates=replicates
    )
    quote_fills, quote_days, quote_diagnostics = score_quote_runs(manifest)
    quote_summary = summarize_quote_run_classes(
        quote_days, quote_diagnostics, tune_end=tune_end
    )
    history = reconcile_historical_reports(
        historical_reports, current_explicit_quote_fills=len(quote_fills)
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "workstation_maker_research_results",
        "generated_at_utc": utc_now().isoformat(),
        "research_only": True,
        "promotion_authorized": False,
        "manifest_hash": manifest["manifest_hash"],
        "coverage": {
            "coverage_artifact": manifest["coverage_artifact"],
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "ws_market_days": len(entries),
            "books_only_start": books_only_start,
            "books_only_end": books_only_end,
            "books_only_market_days": len(manifest.get("books_only_folders") or []),
        },
        "bootstrap": {"seed": int(seed), "replicates": int(replicates)},
        "ws_validation": ws_payload,
        "microstructure": microstructure,
        "synthetic_policy_evidence": synthetic,
        "recorded_quote_evidence": {
            "summary": quote_summary,
            "run_diagnostics": quote_diagnostics,
        },
        "historical_reconciliation": history,
        "economics_contract": {
            "gross_spread_capture": "modeled from pre-trade midpoint versus quote",
            "adverse_selection": "explicit-trade future midpoint markout",
            "flattening_cost": "repository default theoretical fee-equivalent",
            "maker_rebate": "repository default theoretical share; actual payout unavailable",
            "liquidity_reward": "unavailable; not included",
            "selection_metric": "net after 30m markout and modeled flattening cost, excluding theoretical incentives",
        },
    }
    output_paths = {
        "input_manifest": str((out_root / "input_manifest.json").resolve()),
        "ws_validation_json": str((out_root / "ws_validation.json").resolve()),
        "ws_validation_csv": str((out_root / "ws_validation.csv").resolve()),
        "market_day_reconstruction": str((out_root / "market_day_reconstruction.csv").resolve()),
        "explicit_trade_markouts": str((out_root / "explicit_trade_markouts.csv").resolve()),
        "synthetic_policy_fills": str((out_root / "synthetic_policy_fills.csv").resolve()),
        "synthetic_policy_market_days": str((out_root / "synthetic_policy_market_days.csv").resolve()),
        "quote_run_fills": str((out_root / "quote_run_fills.csv").resolve()),
        "quote_run_market_days": str((out_root / "quote_run_market_days.csv").resolve()),
        "results": str((out_root / "maker_research_results.json").resolve()),
        "report": str((out_root / "maker_research_report.md").resolve()),
    }
    payload["outputs"] = output_paths
    _write_json(out_root / "ws_validation.json", ws_payload)
    _write_csv(
        out_root / "ws_validation.csv",
        (
            "event_slug",
            "ws_rows",
            "event_types",
            "unknown_ws_event_rows",
            "invalid_event_slug_rows",
            "missing_received_at_rows",
            "last_trade_price_rows",
            "sized_last_trade_price_rows",
            "side_supported_last_trade_price_rows",
            "event_type_contract_status",
        ),
        ws_diagnostics,
    )
    _write_csv(out_root / "market_day_reconstruction.csv", MARKET_DAY_COLUMNS, market_days)
    _write_csv(
        out_root / "explicit_trade_markouts.csv",
        (
            "target_date", "market_id", "event_slug", "trade_id",
            "trade_time_utc", "clob_token_id", "trade_side", "passive_side",
            "trade_price", "trade_size", "prior_book_age_seconds",
            "markout_1m_per_share", "markout_5m_per_share", "markout_30m_per_share",
        ),
        trade_markouts,
    )
    _write_csv(out_root / "synthetic_policy_fills.csv", FILL_COLUMNS, synthetic_fills)
    _write_csv(out_root / "synthetic_policy_market_days.csv", POLICY_DAY_COLUMNS, policy_days)
    _write_csv(out_root / "quote_run_fills.csv", FILL_COLUMNS, quote_fills)
    _write_csv(out_root / "quote_run_market_days.csv", QUOTE_RUN_DAY_COLUMNS, quote_days)
    _write_json(out_root / "maker_research_results.json", payload)
    write_text_atomic(out_root / "maker_research_report.md", render_report(payload))
    return payload

def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run bounded explicit-trade maker reconstruction research.")
    parser.add_argument("--coverage-json", required=True)
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--run-folder", action="append", required=True)
    parser.add_argument("--historical-report", action="append", default=[])
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--read-only-data-root", required=True)
    parser.add_argument("--coverage-start", required=True)
    parser.add_argument("--coverage-end", required=True)
    parser.add_argument("--books-only-start", required=True)
    parser.add_argument("--books-only-end", required=True)
    parser.add_argument("--tune-end", required=True)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    args = parser.parse_args(argv)
    payload = run_research(
        coverage_json=args.coverage_json,
        snapshots_root=args.snapshots_root,
        run_folders=args.run_folder,
        historical_reports=args.historical_report,
        output_root=args.output_root,
        read_only_data_root=args.read_only_data_root,
        coverage_start=args.coverage_start,
        coverage_end=args.coverage_end,
        books_only_start=args.books_only_start,
        books_only_end=args.books_only_end,
        tune_end=args.tune_end,
        seed=args.bootstrap_seed,
        replicates=args.bootstrap_replicates,
    )
    print("maker research decision: " + str((payload.get("synthetic_policy_evidence") or {}).get("decision")))
    print("report written to " + str((payload.get("outputs") or {}).get("report")))

if __name__ == "__main__":
    main()
