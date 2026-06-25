"""Winner-rank parity gate for weather-only model proof packets."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from weather.backtesting.settlement_ledger import band_value_hi, parse_band_label, resolve_outcome
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import all_specs
from weather.model.model_constants import TORONTO_TZ
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.model_history import (
    DEFAULT_LABELS_CSV,
    DEFAULT_SNAPSHOTS_ROOT,
    load_label,
    load_label_index,
    recent_completed_dates,
    safe_float,
    safe_int,
)
from weather.schema_registry import schema_version
from weather.scoring.metrics import binary_log_loss


SCHEMA_VERSION = schema_version("winner_rank_parity")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_ACTIVE_SHADOW_LONG = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_long.csv"
DEFAULT_PROPER_SCORING = DEFAULT_BACKTEST_ROOT / "proper_scoring_reliability_scorecard.json"
DEFAULT_SETTLED_DAY_ROOT_CAUSE = DEFAULT_BACKTEST_ROOT / "settled_day_root_cause.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "winner_rank_parity.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "winner_rank_parity.md"
DEFAULT_DAYS = 7
DEFAULT_MIN_SNAPSHOTS = 30
DEFAULT_TOP_HIT_GAP_TOLERANCE = 0.02
DEFAULT_TOP_MISS_EXCESS_TOLERANCE = 0
DEFAULT_BRIER_CONTRIBUTION_TOLERANCE = 0.001
DEFAULT_GUARDRAIL_BRIER_TOLERANCE = 0.003
BOTTOM_LOCATION_OWNER_MARKETS = {"miami", "nyc", "seattle"}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_probability(value: Any) -> float | None:
    number = safe_float(value)
    if number is None:
        return None
    return max(1e-9, min(1.0 - 1e-9, number))


def _safe_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _first(row: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _outcome(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "win", "winner"}:
        return 1
    if text in {"false", "no", "loss", "loser"}:
        return 0
    number = safe_float(value)
    if number is None:
        return None
    return 1 if number >= 0.5 else 0


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _sum(values: Iterable[float | None]) -> float:
    return sum(value for value in values if value is not None)


def _cutoff_regime(hour: Any) -> str:
    value = safe_int(hour)
    if value is None:
        return "unknown"
    if value <= 8:
        return "early"
    if value <= 14:
        return "ramp"
    if value <= 19:
        return "late"
    return "lock_in"


def _forecast_disagreement_bucket(value: Any) -> str:
    if value in (None, ""):
        return "unknown"
    text = str(value).strip()
    lower = text.lower()
    if any(token in lower for token in ("high", "low", "moderate", "two_sources", "one_source")):
        return text
    number = safe_float(value)
    if number is None:
        return text
    if number >= 3.0:
        return "high_disagreement"
    if number >= 1.5:
        return "moderate_disagreement"
    return "low_disagreement"


def _settlement_distance_bucket(row_value: Any, outcome: int | None, settlement_bucket: Any = None) -> str:
    existing = str(row_value).strip() if row_value not in (None, "") else ""
    if existing:
        return existing
    if outcome == 1:
        return "0"
    return "unknown"


def _current_max_trust_state(row: dict[str, Any]) -> str:
    explicit = _first(
        row,
        (
            "current_max_trust_state",
            "current_max_state",
            "micro_gate_taxonomy",
            "micro_gate_reason",
        ),
    )
    if explicit not in (None, ""):
        return str(explicit)
    if _safe_bool(row.get("source_fresh")) is False:
        return "source_stale"
    return "unknown"


def _runtime_identity(row: dict[str, Any]) -> str:
    explicit = _first(row, ("runtime_identity", "runtime_git_commit", "artifact_hash", "model_version"))
    if explicit not in (None, ""):
        return str(explicit)
    parts = [
        str(row.get("feature_schema_version") or ""),
        str(row.get("feature_family_hash") or ""),
        str(row.get("feature_missingness_hash") or ""),
    ]
    compact = "|".join(part for part in parts if part)
    return compact or "unknown"


def _clean_band_label(label: Any) -> str:
    return str(label or "").replace("Â", "").replace("Ã‚", "").strip()


def _row_band(row: pd.Series) -> tuple[str | None, int | None, int | None]:
    parsed = parse_band_label(row.get("range_label"))
    kind = row.get("bin_kind") or parsed["kind"]
    value = safe_int(row.get("bin_value_c"))
    if value is None:
        value = parsed["value"]
    value_hi = band_value_hi(row.get("range_label"), value)
    return kind, value, value_hi


def _row_outcome(row: pd.Series, settlement_bucket: int | None) -> int | None:
    kind, value, value_hi = _row_band(row)
    result = resolve_outcome(kind, value, settlement_bucket, value_hi)
    if result is None:
        return None
    return int(bool(result))


def _timestamp_series(frame: pd.DataFrame, spec: Any) -> pd.Series:
    if "captured_at_utc" in frame:
        parsed = pd.to_datetime(frame["captured_at_utc"], errors="coerce", utc=True)
        return parsed.dt.tz_convert(spec.timezone)
    if "captured_at_local" in frame:
        return pd.to_datetime(frame["captured_at_local"], errors="coerce")
    return pd.Series([pd.NaT] * len(frame), index=frame.index)


def _settlement_distance_from_bucket(row: pd.Series, settlement_bucket: int | None, outcome: int) -> str:
    if outcome == 1:
        return "0"
    kind, value, value_hi = _row_band(row)
    if settlement_bucket is None or value is None:
        return "unknown"
    if kind == "lte":
        distance = max(0, settlement_bucket - int(value))
    elif kind == "gte":
        distance = max(0, int(value) - settlement_bucket)
    else:
        distance = min(abs(settlement_bucket - int(value)), abs(settlement_bucket - int(value_hi or value)))
    if distance <= 0:
        return "0"
    if distance == 1:
        return "1"
    if distance == 2:
        return "2"
    return "3+"


def _normalize_candidate_row(row: dict[str, Any], *, source_path: str | None = None) -> dict[str, Any] | None:
    probability = _safe_probability(
        _first(row, ("probability", "candidate_probability", "model_probability", "current_probability"))
    )
    market_yes = _safe_probability(row.get("market_yes"))
    outcome = _outcome(row.get("outcome"))
    if probability is None or market_yes is None or outcome is None:
        return None
    hour = safe_int(_first(row, ("cutoff_hour", "local_hour")))
    cutoff_regime = str(row.get("cutoff_regime") or _cutoff_regime(hour))
    uses_market_features = _safe_bool(row.get("uses_market_features"))
    if uses_market_features is None:
        uses_market_features = False
    counts_toward = _safe_bool(row.get("counts_toward_weather_model_promotion"))
    return {
        "source": "active_variant_shadow",
        "source_path": source_path,
        "lane": str(row.get("claim_lane") or ("market_informed_overlay" if uses_market_features else "weather_only_core_model")),
        "variant_id": str(row.get("variant_id") or "active_candidate"),
        "variant_family": str(row.get("variant_family") or ""),
        "uses_market_features": uses_market_features,
        "counts_toward_weather_model_promotion": counts_toward if counts_toward is not None else not uses_market_features,
        "market_id": str(row.get("market_id") or ""),
        "target_date": str(row.get("target_date") or ""),
        "snapshot_id": str(row.get("snapshot_id") or row.get("run_id") or ""),
        "band_key": str(row.get("band_key") or row.get("range_label") or row.get("bin_value") or ""),
        "range_label": _clean_band_label(row.get("range_label") or row.get("band_key")),
        "model_probability": probability,
        "market_yes": market_yes,
        "outcome": outcome,
        "local_hour": hour,
        "cutoff_regime": cutoff_regime,
        "source_health_state": str(row.get("source_freshness_state") or row.get("source_health_state") or "unknown"),
        "forecast_disagreement_bucket": _forecast_disagreement_bucket(
            row.get("forecast_disagreement_bucket") or row.get("forecast_disagreement")
        ),
        "forecast_source_count_bucket": str(row.get("forecast_source_count_bucket") or row.get("forecast_source_count") or "unknown"),
        "forecast_bucket_pressure": str(row.get("forecast_bucket_pressure") or "unknown"),
        "settlement_distance_bucket": _settlement_distance_bucket(row.get("settlement_distance_bucket"), outcome),
        "band_type": str(row.get("bin_type") or row.get("bin_kind") or "unknown"),
        "current_max_trust_state": _current_max_trust_state(row),
        "runtime_identity": _runtime_identity(row),
        "captured_at_local": str(row.get("captured_at_local") or ""),
    }


def load_candidate_rows(
    paths: Iterable[str | Path],
    *,
    dates: set[str] | None = None,
    market_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        source = {"path": str(path), "exists": path.exists(), "row_count": 0, "scored_row_count": 0}
        sources.append(source)
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    source["row_count"] += 1
                    target_date = str(row.get("target_date") or "")
                    market_id = str(row.get("market_id") or "")
                    if dates and target_date not in dates:
                        continue
                    if market_ids and market_id not in market_ids:
                        continue
                    normalized = _normalize_candidate_row(row, source_path=str(path))
                    if normalized is None:
                        continue
                    source["scored_row_count"] += 1
                    rows.append(normalized)
        except OSError as exc:
            source["error"] = str(exc)
    return rows, sources


def _served_frame_rows(
    frame: pd.DataFrame,
    *,
    spec: Any,
    target_date: date,
    settlement_bucket: int | None,
    event_slug: str,
    source_path: Path,
) -> list[dict[str, Any]]:
    prepared = frame.copy()
    prepared["_row_order"] = range(len(prepared))
    prepared["_captured_at_market"] = _timestamp_series(prepared, spec)
    prepared["_model_probability"] = (
        pd.to_numeric(prepared["model_probability"], errors="coerce")
        if "model_probability" in prepared
        else pd.Series([math.nan] * len(prepared), index=prepared.index)
    )
    prepared["_market_yes"] = (
        pd.to_numeric(prepared["market_yes"], errors="coerce")
        if "market_yes" in prepared
        else pd.Series([math.nan] * len(prepared), index=prepared.index)
    )
    rows: list[dict[str, Any]] = []
    for _, row in prepared.iterrows():
        probability = _safe_probability(row.get("_model_probability"))
        market_yes = _safe_probability(row.get("_market_yes"))
        if probability is None or market_yes is None:
            continue
        outcome = _row_outcome(row, settlement_bucket)
        if outcome is None:
            continue
        captured = row.get("_captured_at_market")
        hour = int(captured.hour) if captured is not None and not pd.isna(captured) else None
        kind, value, _value_hi = _row_band(row)
        rows.append({
            "source": "served_snapshots",
            "source_path": str(source_path),
            "lane": "weather_only_core_model",
            "variant_id": "served_current",
            "variant_family": "served_current",
            "uses_market_features": False,
            "counts_toward_weather_model_promotion": True,
            "market_id": spec.id,
            "target_date": target_date.isoformat(),
            "snapshot_id": str(row.get("snapshot_id") or row.get("_row_order") or ""),
            "band_key": str(row.get("polymarket_market_id") or row.get("range_label") or value or ""),
            "range_label": _clean_band_label(row.get("range_label")),
            "model_probability": probability,
            "market_yes": market_yes,
            "outcome": outcome,
            "local_hour": hour,
            "cutoff_regime": _cutoff_regime(hour),
            "source_health_state": str(row.get("source_freshness_state") or row.get("trigger_source") or "served"),
            "forecast_disagreement_bucket": _forecast_disagreement_bucket(row.get("forecast_disagreement")),
            "forecast_source_count_bucket": str(row.get("forecast_source_count") or "unknown"),
            "forecast_bucket_pressure": str(row.get("forecast_bucket_pressure") or "unknown"),
            "settlement_distance_bucket": _settlement_distance_from_bucket(row, settlement_bucket, outcome),
            "band_type": "lte" if kind == "lte" else "gte" if kind == "gte" else "eq",
            "current_max_trust_state": _current_max_trust_state(dict(row)),
            "runtime_identity": _runtime_identity(dict(row)),
            "captured_at_local": captured.isoformat() if captured is not None and not pd.isna(captured) else "",
        })
    return rows


def load_served_rows(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    labels_csv: str | Path = DEFAULT_LABELS_CSV,
    dates: list[date] | None = None,
    as_of: str | date | datetime | None = None,
    days: int = DEFAULT_DAYS,
    market_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_dates = list(dates or recent_completed_dates(as_of=as_of, days=days))
    root = Path(snapshots_root)
    specs = [spec for spec in all_specs() if not market_ids or spec.id in market_ids]
    label_index = load_label_index(labels_csv)
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for target_date in selected_dates:
        for spec in specs:
            event_slug = event_slug_for_date(target_date, spec.id)
            folder = root / event_slug
            tape = folder / "snapshots_long.csv"
            source = {
                "market_id": spec.id,
                "target_date": target_date.isoformat(),
                "event_slug": event_slug,
                "path": str(tape),
                "exists": tape.exists(),
                "scored_row_count": 0,
                "status": "missing_tape",
            }
            sources.append(source)
            if not tape.exists():
                continue
            try:
                frame = pd.read_csv(tape)
            except Exception as exc:  # noqa: BLE001
                source.update({"status": "read_error", "error": str(exc)})
                continue
            label = load_label(event_slug, folder, label_index=label_index)
            settlement_bucket = safe_int(label.get("settlement_bucket"))
            source["settlement_bucket"] = settlement_bucket
            if settlement_bucket is None:
                source["status"] = "missing_settlement"
                continue
            scored = _served_frame_rows(
                frame,
                spec=spec,
                target_date=target_date,
                settlement_bucket=settlement_bucket,
                event_slug=event_slug,
                source_path=tape,
            )
            source["status"] = "scored" if scored else "no_scored_rows"
            source["scored_row_count"] = len(scored)
            source["snapshot_count"] = int(frame["snapshot_id"].nunique()) if "snapshot_id" in frame else 0
            rows.extend(scored)
    return rows, sources


def _group_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("source") or ""),
        str(row.get("variant_id") or ""),
        str(row.get("market_id") or ""),
        str(row.get("target_date") or ""),
        str(row.get("snapshot_id") or ""),
    )


def _row_brier(row: dict[str, Any], key: str) -> float:
    return (float(row[key]) - float(row["outcome"])) ** 2


def snapshot_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_group_key(row)].append(row)
    cases: list[dict[str, Any]] = []
    for key, group_rows in grouped.items():
        if len(group_rows) < 2:
            continue
        winners = [row for row in group_rows if row.get("outcome") == 1]
        if len(winners) != 1:
            continue
        winner = winners[0]
        model_top = max(group_rows, key=lambda row: float(row["model_probability"]))
        market_top = max(group_rows, key=lambda row: float(row["market_yes"]))
        model_top_hit = model_top is winner or model_top.get("band_key") == winner.get("band_key")
        market_top_hit = market_top is winner or market_top.get("band_key") == winner.get("band_key")
        if model_top_hit and market_top_hit:
            case_class = "model_top_hit_market_top_hit"
        elif not model_top_hit and market_top_hit:
            case_class = "model_top_miss_market_top_hit"
        elif model_top_hit and not market_top_hit:
            case_class = "model_top_hit_market_top_miss"
        else:
            case_class = "model_top_miss_market_top_miss"
        model_brier_sum = sum(_row_brier(row, "model_probability") for row in group_rows)
        market_brier_sum = sum(_row_brier(row, "market_yes") for row in group_rows)
        model_logloss_sum = sum(binary_log_loss(float(row["model_probability"]), int(row["outcome"])) for row in group_rows)
        market_logloss_sum = sum(binary_log_loss(float(row["market_yes"]), int(row["outcome"])) for row in group_rows)
        case = {
            "source": key[0],
            "variant_id": key[1],
            "market_id": key[2],
            "target_date": key[3],
            "snapshot_id": key[4],
            "lane": str(winner.get("lane") or ""),
            "variant_family": str(winner.get("variant_family") or ""),
            "uses_market_features": bool(winner.get("uses_market_features")),
            "counts_toward_weather_model_promotion": bool(winner.get("counts_toward_weather_model_promotion")),
            "case_class": case_class,
            "row_count": len(group_rows),
            "model_top_hit": model_top_hit,
            "market_top_hit": market_top_hit,
            "model_brier_sum": model_brier_sum,
            "market_brier_sum": market_brier_sum,
            "brier_gap_sum": model_brier_sum - market_brier_sum,
            "model_logloss_sum": model_logloss_sum,
            "market_logloss_sum": market_logloss_sum,
            "logloss_gap_sum": model_logloss_sum - market_logloss_sum,
            "winner_model_probability": float(winner["model_probability"]),
            "winner_market_probability": float(winner["market_yes"]),
            "winner_probability_gap_market_minus_model": float(winner["market_yes"]) - float(winner["model_probability"]),
            "model_top_probability": float(model_top["model_probability"]),
            "market_top_probability": float(market_top["market_yes"]),
            "model_top_band": model_top.get("range_label") or model_top.get("band_key"),
            "market_top_band": market_top.get("range_label") or market_top.get("band_key"),
            "winner_band": winner.get("range_label") or winner.get("band_key"),
            "local_hour": model_top.get("local_hour"),
            "cutoff_regime": model_top.get("cutoff_regime") or _cutoff_regime(model_top.get("local_hour")),
            "source_health_state": model_top.get("source_health_state") or "unknown",
            "forecast_disagreement_bucket": model_top.get("forecast_disagreement_bucket") or "unknown",
            "forecast_source_count_bucket": model_top.get("forecast_source_count_bucket") or "unknown",
            "forecast_bucket_pressure": model_top.get("forecast_bucket_pressure") or "unknown",
            "settlement_distance_bucket": model_top.get("settlement_distance_bucket") or "unknown",
            "band_type": model_top.get("band_type") or "unknown",
            "current_max_trust_state": model_top.get("current_max_trust_state") or "unknown",
            "runtime_identity": model_top.get("runtime_identity") or "unknown",
            "captured_at_local": model_top.get("captured_at_local") or "",
        }
        cases.append(case)
    return cases


def _case_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot_count = len(cases)
    row_count = sum(int(case.get("row_count") or 0) for case in cases)
    if not snapshot_count or not row_count:
        return {
            "snapshot_count": snapshot_count,
            "row_count": row_count,
            "status": "MISSING",
        }
    counts = Counter(case.get("case_class") for case in cases)
    model_top_hit_count = sum(1 for case in cases if case.get("model_top_hit"))
    market_top_hit_count = sum(1 for case in cases if case.get("market_top_hit"))
    model_brier = _sum(case.get("model_brier_sum") for case in cases) / row_count
    market_brier = _sum(case.get("market_brier_sum") for case in cases) / row_count
    model_logloss = _sum(case.get("model_logloss_sum") for case in cases) / row_count
    market_logloss = _sum(case.get("market_logloss_sum") for case in cases) / row_count
    miss_market_hit = counts.get("model_top_miss_market_top_hit", 0)
    hit_market_miss = counts.get("model_top_hit_market_top_miss", 0)
    miss_market_hit_cases = [
        case for case in cases if case.get("case_class") == "model_top_miss_market_top_hit"
    ]
    brier_contribution = (
        _sum(case.get("brier_gap_sum") for case in miss_market_hit_cases) / row_count
        if row_count
        else None
    )
    logloss_contribution = (
        _sum(case.get("logloss_gap_sum") for case in miss_market_hit_cases) / row_count
        if row_count
        else None
    )
    return {
        "status": "SCORED",
        "snapshot_count": snapshot_count,
        "row_count": row_count,
        "model_brier": model_brier,
        "market_brier": market_brier,
        "brier_gap_model_minus_market": model_brier - market_brier,
        "model_logloss": model_logloss,
        "market_logloss": market_logloss,
        "logloss_gap_model_minus_market": model_logloss - market_logloss,
        "model_top_hit_count": model_top_hit_count,
        "market_top_hit_count": market_top_hit_count,
        "model_top_hit_rate": model_top_hit_count / snapshot_count,
        "market_top_hit_rate": market_top_hit_count / snapshot_count,
        "top_hit_gap_market_minus_model": (market_top_hit_count - model_top_hit_count) / snapshot_count,
        "model_top_miss_market_top_hit_count": miss_market_hit,
        "model_top_hit_market_top_miss_count": hit_market_miss,
        "market_top_model_miss_excess": miss_market_hit - hit_market_miss,
        "winner_model_probability": _mean(case.get("winner_model_probability") for case in cases),
        "winner_market_probability": _mean(case.get("winner_market_probability") for case in cases),
        "winner_probability_gap_market_minus_model": _mean(
            case.get("winner_probability_gap_market_minus_model") for case in cases
        ),
        "model_top_miss_market_top_hit_brier_contribution": brier_contribution,
        "model_top_miss_market_top_hit_logloss_contribution": logloss_contribution,
        "case_counts": dict(sorted(counts.items())),
    }


def _summaries_by(cases: list[dict[str, Any]], key: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case.get(key) if case.get(key) not in (None, "") else "unknown"].append(case)
    rows = []
    for value, group_cases in grouped.items():
        summary = _case_summary(group_cases)
        rows.append({
            "slice": key,
            "value": value,
            **summary,
        })
    rows.sort(
        key=lambda row: (
            -(safe_float(row.get("model_top_miss_market_top_hit_brier_contribution")) or 0.0),
            -int(row.get("snapshot_count") or 0),
            str(row.get("value")),
        )
    )
    return rows[:limit] if limit else rows


def _owner_items_for_case(row: dict[str, Any]) -> list[int]:
    owners: set[int] = set()
    market_id = str(row.get("market_id") or row.get("value") or "")
    cutoff_regime = str(row.get("cutoff_regime") or row.get("value") or "").lower()
    slice_name = str(row.get("slice") or "")
    value = str(row.get("value") or "").lower()
    band_type = str(row.get("band_type") or row.get("value") or "").lower()
    distance = str(row.get("settlement_distance_bucket") or row.get("value") or "").lower()
    current_state = str(row.get("current_max_trust_state") or row.get("value") or "").lower()
    forecast = str(row.get("forecast_disagreement_bucket") or row.get("value") or "").lower()
    source = str(row.get("source") or "").lower()
    uses_market = bool(row.get("uses_market_features"))

    if uses_market or "market_informed" in value:
        owners.update({156, 264})
    if source == "served_snapshots" or row.get("variant_id") == "served_current":
        owners.add(233)
    if cutoff_regime == "early" or (slice_name == "cutoff_regime" and value == "early"):
        owners.update({160, 228, 230})
    if band_type == "eq" or distance in {"0", "1"} or slice_name in {"band_type", "settlement_distance_bucket"}:
        owners.add(230)
    if market_id in BOTTOM_LOCATION_OWNER_MARKETS or (
        slice_name == "market_id" and value in BOTTOM_LOCATION_OWNER_MARKETS
    ):
        owners.add(219)
    if (
        cutoff_regime == "ramp"
        or (slice_name == "cutoff_regime" and value in {"ramp", "late", "lock_in"})
        or "high" in forecast
        or "current" in current_state
        or "warm" in str(row.get("forecast_bucket_pressure") or "").lower()
    ):
        owners.update({194, 195, 232})
    return sorted(owners)


def owner_routes(cases: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    miss_cases = [case for case in cases if case.get("case_class") == "model_top_miss_market_top_hit"]
    dimensions = [
        "market_id",
        "local_hour",
        "cutoff_regime",
        "source_health_state",
        "forecast_disagreement_bucket",
        "settlement_distance_bucket",
        "band_type",
        "current_max_trust_state",
        "runtime_identity",
        "variant_id",
    ]
    routed: list[dict[str, Any]] = []
    for dimension in dimensions:
        for row in _summaries_by(miss_cases, dimension, limit=limit):
            if int(row.get("snapshot_count") or 0) <= 0:
                continue
            representative = next(
                (
                    case for case in miss_cases
                    if str(case.get(dimension) if case.get(dimension) not in (None, "") else "unknown")
                    == str(row.get("value"))
                ),
                {},
            )
            route_seed = {**representative, **row}
            owners = _owner_items_for_case(route_seed)
            routed.append({
                **row,
                "case_class": "model_top_miss_market_top_hit",
                "owner_items": owners,
                "suggested_item": "" if owners else "new winner-rank parity repair owner",
            })
    routed.sort(
        key=lambda row: (
            -(safe_float(row.get("model_top_miss_market_top_hit_brier_contribution")) or 0.0),
            -int(row.get("snapshot_count") or 0),
        )
    )
    return routed[:limit]


def _guardrail_status(summary: dict[str, Any], *, min_snapshots: int, brier_tolerance: float) -> str:
    if int(summary.get("snapshot_count") or 0) < min_snapshots:
        return "MISSING"
    gap = safe_float(summary.get("brier_gap_model_minus_market"))
    if gap is None:
        return "MISSING"
    return "PASS" if gap <= brier_tolerance else "BLOCK"


def candidate_guardrails(
    cases: list[dict[str, Any]],
    *,
    min_snapshots: int = 3,
    brier_tolerance: float = DEFAULT_GUARDRAIL_BRIER_TOLERANCE,
) -> list[dict[str, Any]]:
    variants = sorted({
        case.get("variant_id")
        for case in cases
        if case.get("variant_id") != "served_current"
        and not case.get("uses_market_features")
        and case.get("counts_toward_weather_model_promotion") is not False
    })
    guardrail_rows: list[dict[str, Any]] = []
    for variant_id in variants:
        variant_cases = [case for case in cases if case.get("variant_id") == variant_id]
        slices = {
            "broad": variant_cases,
            "early": [
                case for case in variant_cases
                if case.get("cutoff_regime") == "early" or (safe_int(case.get("local_hour")) or 99) <= 8
            ],
            "ramp": [
                case for case in variant_cases
                if case.get("cutoff_regime") == "ramp" or 9 <= (safe_int(case.get("local_hour")) or -1) <= 14
            ],
            "late": [
                case for case in variant_cases
                if case.get("cutoff_regime") in {"late", "lock_in"} or (safe_int(case.get("local_hour")) or -1) >= 15
            ],
            "exact_band": [case for case in variant_cases if case.get("band_type") == "eq"],
            "bottom_location": [
                case for case in variant_cases if case.get("market_id") in BOTTOM_LOCATION_OWNER_MARKETS
            ],
        }
        for guardrail, guardrail_cases in slices.items():
            summary = _case_summary(guardrail_cases)
            status = _guardrail_status(
                summary,
                min_snapshots=min_snapshots,
                brier_tolerance=brier_tolerance,
            )
            guardrail_rows.append({
                **summary,
                "variant_id": variant_id,
                "guardrail": guardrail,
                "status": status,
                "min_snapshots": min_snapshots,
                "brier_tolerance": brier_tolerance,
            })
    return guardrail_rows


def parity_gate(
    metrics: list[dict[str, Any]],
    guardrails: list[dict[str, Any]],
    *,
    min_snapshots: int = DEFAULT_MIN_SNAPSHOTS,
    top_hit_gap_tolerance: float = DEFAULT_TOP_HIT_GAP_TOLERANCE,
    top_miss_excess_tolerance: int = DEFAULT_TOP_MISS_EXCESS_TOLERANCE,
    brier_contribution_tolerance: float = DEFAULT_BRIER_CONTRIBUTION_TOLERANCE,
) -> dict[str, Any]:
    active_weather = [
        row for row in metrics
        if not row.get("uses_market_features")
        and row.get("counts_toward_weather_model_promotion") is not False
        and int(row.get("snapshot_count") or 0) >= min_snapshots
    ]
    blockers: list[dict[str, Any]] = []
    evaluated = active_weather or [
        row for row in metrics
        if row.get("variant_id") == "served_current" and int(row.get("snapshot_count") or 0) >= min_snapshots
    ]
    for row in evaluated:
        gap = safe_float(row.get("top_hit_gap_market_minus_model")) or 0.0
        excess = int(row.get("market_top_model_miss_excess") or 0)
        brier_contribution = safe_float(row.get("model_top_miss_market_top_hit_brier_contribution")) or 0.0
        if gap > top_hit_gap_tolerance:
            blockers.append({
                "variant_id": row.get("variant_id"),
                "gate": "top_hit_gap",
                "detail": (
                    f"{row.get('variant_id')} model top-hit rate trails market by "
                    f"{gap:.4f}, above tolerance {top_hit_gap_tolerance:.4f}"
                ),
                "value": gap,
                "tolerance": top_hit_gap_tolerance,
            })
        if excess > top_miss_excess_tolerance:
            blockers.append({
                "variant_id": row.get("variant_id"),
                "gate": "market_top_model_miss_excess",
                "detail": (
                    f"{row.get('variant_id')} has {excess} more model-top-miss/market-top-hit "
                    f"snapshots than reverse cases"
                ),
                "value": excess,
                "tolerance": top_miss_excess_tolerance,
            })
        if brier_contribution > brier_contribution_tolerance:
            blockers.append({
                "variant_id": row.get("variant_id"),
                "gate": "brier_contribution",
                "detail": (
                    f"{row.get('variant_id')} model-top-miss/market-top-hit Brier contribution "
                    f"{brier_contribution:.6f} exceeds tolerance {brier_contribution_tolerance:.6f}"
                ),
                "value": brier_contribution,
                "tolerance": brier_contribution_tolerance,
            })
    guardrail_blockers = [
        row for row in guardrails
        if row.get("status") == "BLOCK"
    ]
    for row in guardrail_blockers:
        blockers.append({
            "variant_id": row.get("variant_id"),
            "gate": f"candidate_guardrail_{row.get('guardrail')}",
            "detail": (
                f"{row.get('variant_id')} {row.get('guardrail')} Brier gap "
                f"{fmt_signed(row.get('brier_gap_model_minus_market'))} exceeds guardrail tolerance"
            ),
            "value": row.get("brier_gap_model_minus_market"),
            "tolerance": row.get("brier_tolerance"),
        })
    if not evaluated:
        blockers.append({
            "variant_id": None,
            "gate": "minimum_snapshot_count",
            "detail": f"no weather-only variant has at least {min_snapshots} scored snapshots",
            "value": 0,
            "tolerance": min_snapshots,
        })
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "min_snapshots": min_snapshots,
        "top_hit_gap_tolerance": top_hit_gap_tolerance,
        "top_miss_excess_tolerance": top_miss_excess_tolerance,
        "brier_contribution_tolerance": brier_contribution_tolerance,
        "evaluated_variant_count": len(evaluated),
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
    }


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def build_payload(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    labels_csv: str | Path = DEFAULT_LABELS_CSV,
    active_shadow_long: str | Path | None = DEFAULT_ACTIVE_SHADOW_LONG,
    candidate_paths: Iterable[str | Path] | None = None,
    proper_scoring: str | Path = DEFAULT_PROPER_SCORING,
    settled_day_root_cause: str | Path = DEFAULT_SETTLED_DAY_ROOT_CAUSE,
    as_of: str | date | datetime | None = None,
    days: int = DEFAULT_DAYS,
    dates: list[date] | None = None,
    market_ids: Iterable[str] | None = None,
    source_rows: list[dict[str, Any]] | None = None,
    candidate_rows: list[dict[str, Any]] | None = None,
    generated_at_utc: str | None = None,
    min_snapshots: int = DEFAULT_MIN_SNAPSHOTS,
    top_hit_gap_tolerance: float = DEFAULT_TOP_HIT_GAP_TOLERANCE,
    top_miss_excess_tolerance: int = DEFAULT_TOP_MISS_EXCESS_TOLERANCE,
    brier_contribution_tolerance: float = DEFAULT_BRIER_CONTRIBUTION_TOLERANCE,
    guardrail_brier_tolerance: float = DEFAULT_GUARDRAIL_BRIER_TOLERANCE,
) -> dict[str, Any]:
    selected_dates = list(dates or recent_completed_dates(as_of=as_of, days=days))
    selected_date_strings = {item.isoformat() for item in selected_dates}
    market_id_set = {str(item) for item in market_ids or []}
    served_sources: list[dict[str, Any]] = []
    candidate_sources: list[dict[str, Any]] = []

    if source_rows is None:
        source_rows, served_sources = load_served_rows(
            snapshots_root,
            labels_csv=labels_csv,
            dates=selected_dates,
            market_ids=market_id_set or None,
        )
    if candidate_rows is None:
        paths = list(candidate_paths or ([active_shadow_long] if active_shadow_long else []))
        candidate_rows, candidate_sources = load_candidate_rows(
            paths,
            dates=selected_date_strings,
            market_ids=market_id_set or None,
        )
        candidate_window = "selected_dates"
        if not candidate_rows and selected_date_strings:
            candidate_rows, candidate_sources = load_candidate_rows(
                paths,
                dates=None,
                market_ids=market_id_set or None,
            )
            candidate_window = "all_available_candidate_dates_fallback"
            for source in candidate_sources:
                source["date_filter_fallback"] = "no_candidate_rows_in_selected_dates"
    else:
        candidate_window = "provided_rows"
    normalized_source_rows = [
        _normalize_candidate_row(row) if "model_probability" not in row else row
        for row in source_rows
    ]
    normalized_candidate_rows = [
        _normalize_candidate_row(row) if "model_probability" not in row else row
        for row in candidate_rows
    ]
    all_rows = [
        row for row in [*normalized_source_rows, *normalized_candidate_rows]
        if row is not None
    ]
    cases = snapshot_cases(all_rows)
    metric_rows = []
    by_variant: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_variant[(case.get("source"), case.get("variant_id"))].append(case)
    for (source, variant_id), variant_cases in sorted(by_variant.items(), key=lambda item: str(item[0])):
        first = variant_cases[0] if variant_cases else {}
        metric_rows.append({
            "source": source,
            "variant_id": variant_id,
            "lane": first.get("lane"),
            "variant_family": first.get("variant_family"),
            "uses_market_features": first.get("uses_market_features"),
            "counts_toward_weather_model_promotion": first.get("counts_toward_weather_model_promotion"),
            **_case_summary(variant_cases),
        })
    by_dimension = {
        dimension: _summaries_by(cases, dimension, limit=25)
        for dimension in [
            "market_id",
            "local_hour",
            "cutoff_regime",
            "source_health_state",
            "forecast_disagreement_bucket",
            "settlement_distance_bucket",
            "band_type",
            "current_max_trust_state",
            "runtime_identity",
            "variant_id",
        ]
    }
    guardrails = candidate_guardrails(
        cases,
        min_snapshots=max(3, min(10, min_snapshots)),
        brier_tolerance=guardrail_brier_tolerance,
    )
    gate = parity_gate(
        metric_rows,
        guardrails,
        min_snapshots=min_snapshots,
        top_hit_gap_tolerance=top_hit_gap_tolerance,
        top_miss_excess_tolerance=top_miss_excess_tolerance,
        brier_contribution_tolerance=brier_contribution_tolerance,
    )
    primary = next(
        (row for row in metric_rows if row.get("variant_id") == "served_current"),
        metric_rows[0] if metric_rows else {},
    )
    routes = owner_routes(cases)
    proper_payload = _read_json(proper_scoring)
    root_cause_payload = _read_json(settled_day_root_cause)
    status = gate.get("status") if metric_rows else "MISSING"
    if status == "PASS" and any(row.get("suggested_item") for row in routes):
        status = "WARN"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": status,
        "dates": sorted(selected_date_strings),
        "summary": {
            "source_row_count": len(source_rows),
            "candidate_row_count": len(candidate_rows),
            "candidate_window": candidate_window,
            "candidate_dates": sorted({
                str(row.get("target_date"))
                for row in candidate_rows
                if row.get("target_date")
            }),
            "scored_row_count": len(all_rows),
            "snapshot_case_count": len(cases),
            "variant_count": len(metric_rows),
            "route_count": len(routes),
            "candidate_guardrail_count": len(guardrails),
            "candidate_guardrail_block_count": sum(1 for row in guardrails if row.get("status") == "BLOCK"),
            "model_top_hit_rate": primary.get("model_top_hit_rate"),
            "market_top_hit_rate": primary.get("market_top_hit_rate"),
            "market_top_model_miss_excess": primary.get("market_top_model_miss_excess"),
            "winner_probability_gap_market_minus_model": primary.get("winner_probability_gap_market_minus_model"),
            "brier_contribution": primary.get("model_top_miss_market_top_hit_brier_contribution"),
            "logloss_contribution": primary.get("model_top_miss_market_top_hit_logloss_contribution"),
            "parity_gate_status": gate.get("status"),
            "proper_scoring_status": (proper_payload or {}).get("status"),
            "settled_day_root_cause_status": (root_cause_payload or {}).get("status"),
        },
        "inputs": {
            "snapshots_root": str(snapshots_root),
            "labels_csv": str(labels_csv),
            "active_shadow_long": str(active_shadow_long) if active_shadow_long else "",
            "candidate_paths": [str(path) for path in (candidate_paths or [])],
            "proper_scoring": str(proper_scoring),
            "settled_day_root_cause": str(settled_day_root_cause),
            "days": days,
            "market_ids": sorted(market_id_set),
        },
        "source_snapshots": served_sources,
        "candidate_sources": candidate_sources,
        "primary_weather_only": primary,
        "variant_metrics": metric_rows,
        "by_dimension": by_dimension,
        "top_owner_routes": routes,
        "candidate_guardrails": guardrails,
        "diagnostic_policy": {
            "scalar_calibration": "diagnostic_only_until_parity_case_class_and_guardrails_improve",
            "global_sharpening": "diagnostic_only_until_parity_case_class_and_guardrails_improve",
            "market_informed": "separate_market_residual_lane_items_156_264",
        },
        "parity_gate": gate,
    }


def _metric_rows_for_report(payload: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for row in payload.get("variant_metrics") or []:
        rows.append([
            row.get("variant_id"),
            row.get("source"),
            row.get("lane"),
            row.get("snapshot_count"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_gap_model_minus_market")),
            fmt_num(row.get("model_top_hit_rate")),
            fmt_num(row.get("market_top_hit_rate")),
            row.get("market_top_model_miss_excess"),
            fmt_num(row.get("winner_probability_gap_market_minus_model")),
            fmt_num(row.get("model_top_miss_market_top_hit_brier_contribution")),
            fmt_num(row.get("model_top_miss_market_top_hit_logloss_contribution")),
        ])
    return rows


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    gate = payload.get("parity_gate") or {}
    lines = [
        "# Winner-Rank Parity Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Dates", ", ".join(payload.get("dates") or [])],
            ["Source rows", summary.get("source_row_count")],
            ["Candidate rows", summary.get("candidate_row_count")],
            ["Snapshot cases", summary.get("snapshot_case_count")],
            ["Primary model top-hit rate", fmt_num(summary.get("model_top_hit_rate"))],
            ["Primary market top-hit rate", fmt_num(summary.get("market_top_hit_rate"))],
            ["Market-top/model-miss excess", summary.get("market_top_model_miss_excess")],
            ["Winner probability gap market-model", fmt_num(summary.get("winner_probability_gap_market_minus_model"))],
            ["Top-miss Brier contribution", fmt_num(summary.get("brier_contribution"))],
            ["Top-miss log-loss contribution", fmt_num(summary.get("logloss_contribution"))],
            ["Parity gate", gate.get("status")],
            ["Parity blockers", gate.get("blocker_count")],
        ],
    )
    lines += ["", "## Variant Metrics", ""]
    lines += markdown_table(
        [
            "Variant",
            "Source",
            "Lane",
            "Snapshots",
            "Model Brier",
            "Market Brier",
            "Brier Gap",
            "Model Top Hit",
            "Market Top Hit",
            "Excess",
            "Winner Gap",
            "Brier Contribution",
            "LogLoss Contribution",
        ],
        _metric_rows_for_report(payload),
    )
    lines += ["", "## Gate Blockers", ""]
    blockers = gate.get("blockers") or []
    lines += markdown_table(
        ["Variant", "Gate", "Detail", "Value", "Tolerance"],
        [
            [
                row.get("variant_id") or "-",
                row.get("gate"),
                row.get("detail"),
                row.get("value"),
                row.get("tolerance"),
            ]
            for row in blockers
        ] or [["-", "-", "none", "-", "-"]],
    )
    lines += ["", "## Candidate Guardrails", ""]
    lines += markdown_table(
        ["Variant", "Guardrail", "Status", "Snapshots", "Model Brier", "Market Brier", "Brier Gap"],
        [
            [
                row.get("variant_id"),
                row.get("guardrail"),
                row.get("status"),
                row.get("snapshot_count"),
                fmt_num(row.get("model_brier")),
                fmt_num(row.get("market_brier")),
                fmt_signed(row.get("brier_gap_model_minus_market")),
            ]
            for row in payload.get("candidate_guardrails") or []
        ] or [["-", "-", "MISSING", 0, "-", "-", "-"]],
    )
    lines += ["", "## Owner-Routed Top Cases", ""]
    lines += markdown_table(
        ["Slice", "Value", "Snapshots", "Brier Contribution", "Owners", "Suggested Item"],
        [
            [
                row.get("slice"),
                row.get("value"),
                row.get("snapshot_count"),
                fmt_num(row.get("model_top_miss_market_top_hit_brier_contribution")),
                ", ".join(str(item) for item in row.get("owner_items") or []) or "-",
                row.get("suggested_item") or "-",
            ]
            for row in payload.get("top_owner_routes") or []
        ] or [["-", "-", 0, "-", "-", "-"]],
    )
    lines += ["", "## Diagnostic Policy", ""]
    policy = payload.get("diagnostic_policy") or {}
    lines += markdown_table(
        ["Candidate", "Disposition"],
        [[key, value] for key, value in sorted(policy.items())],
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the winner-rank parity gate report.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--active-shadow-long", default=str(DEFAULT_ACTIVE_SHADOW_LONG))
    parser.add_argument("--proper-scoring", default=str(DEFAULT_PROPER_SCORING))
    parser.add_argument("--settled-day-root-cause", default=str(DEFAULT_SETTLED_DAY_ROOT_CAUSE))
    parser.add_argument("--as-of", default="")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--min-snapshots", type=int, default=DEFAULT_MIN_SNAPSHOTS)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)
    payload = build_payload(
        snapshots_root=args.snapshots_root,
        labels_csv=args.labels_csv,
        active_shadow_long=args.active_shadow_long,
        proper_scoring=args.proper_scoring,
        settled_day_root_cause=args.settled_day_root_cause,
        as_of=args.as_of or None,
        days=args.days,
        min_snapshots=args.min_snapshots,
    )
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Winner-rank parity: {payload['status']} ({payload['summary'].get('snapshot_case_count')} cases)")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
