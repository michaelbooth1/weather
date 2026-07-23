"""Bounded historical-context comparison for the current-replay frontier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.reporting.research.current_replay_time_frontier import (
    EVENING_HOURS,
    HOURS,
    MAX_HISTORICAL_CONTEXT_BYTES,
    PREDAWN_HOURS,
    UNITS,
    ExperimentConfigurationError,
    _float_field,
    _resolved,
    sha256_stable_file,
)


def load_historical_hourly_context(path: str | Path) -> dict[str, Any]:
    """Load a small dated comparator without treating it as H1 evidence."""

    context_path = _resolved(path)
    initial = context_path.stat()
    if initial.st_size <= 0 or initial.st_size > MAX_HISTORICAL_CONTEXT_BYTES:
        raise ExperimentConfigurationError(
            f"historical hourly context exceeds size bound: {context_path}"
        )
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentConfigurationError(
            f"cannot read historical hourly context: {context_path}"
        ) from exc
    if payload.get("schema_version") != "hourly_model_performance_v0.3":
        raise ExperimentConfigurationError(
            f"unsupported historical hourly schema: {payload.get('schema_version')!r}"
        )
    by_hour = payload.get("by_hour") or []
    index = {}
    for source in by_hour:
        try:
            hour = int(source["hour"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExperimentConfigurationError(
                "historical hourly context has an invalid hour row"
            ) from exc
        if hour in index or hour not in HOURS:
            raise ExperimentConfigurationError(
                f"historical hourly context has duplicate/invalid hour {hour}"
            )
        index[hour] = source
    if set(index) != set(HOURS):
        raise ExperimentConfigurationError(
            "historical hourly context must contain exactly hours 0 through 23"
        )
    compact_hours = []
    for hour in PREDAWN_HOURS + EVENING_HOURS:
        source = index[hour]
        compact_hours.append(
            {
                "hour": hour,
                "market_days": int(source.get("market_days") or 0),
                "markets": int(source.get("markets") or 0),
                "model_brier": _float_field(source, "model_brier"),
                "market_brier": _float_field(source, "market_brier"),
                "model_logloss": _float_field(source, "model_logloss"),
                "market_logloss": _float_field(source, "market_logloss"),
                "model_winner_probability": _float_field(
                    source, "winner_model_probability"
                ),
                "market_winner_probability": _float_field(
                    source, "winner_market_probability"
                ),
            }
        )
    final = context_path.stat()
    if initial.st_size != final.st_size or initial.st_mtime_ns != final.st_mtime_ns:
        raise ExperimentConfigurationError(
            f"historical hourly context changed while read: {context_path}"
        )
    corpus = payload.get("corpus") or {}
    gate = payload.get("hourly_performance_gate") or {}
    return {
        "evidence_role": "DATED_NONCOMPARABLE_CONTEXT",
        "path": str(context_path),
        "sha256": sha256_stable_file(
            context_path,
            expected_size_bytes=initial.st_size,
            expected_mtime_ns=initial.st_mtime_ns,
        ),
        "schema_version": payload["schema_version"],
        "generated_at_utc": payload.get("generated_at_utc"),
        "date_min": corpus.get("date_min"),
        "date_max": corpus.get("date_max"),
        "scored_market_days": corpus.get("scored_market_days"),
        "markets": corpus.get("markets") or [],
        "gate_status": gate.get("status"),
        "gate_blockers": gate.get("blockers") or [],
        "methodology_difference": (
            "historical v0.3 uses first market-day-band checkpoint per local hour; "
            "H1 frontier uses aligned replay snapshots, then market-date/fleet-date equal weighting"
        ),
        "hours": compact_hours,
    }


def compare_historical_pattern(
    historical: Mapping[str, Any] | None,
    summaries: Sequence[Mapping[str, Any]],
    breakpoints: Sequence[Mapping[str, Any]],
    *,
    evidence_split: str = "holdout",
) -> list[dict[str, Any]]:
    """Check only directional reproduction across intentionally different corpora."""

    if not historical:
        return []
    historical_hours = {int(row["hour"]): row for row in historical.get("hours") or []}
    historical_predawn_pattern = all(
        historical_hours[hour]["model_brier"] > historical_hours[hour]["market_brier"]
        and historical_hours[hour]["model_winner_probability"]
        < historical_hours[hour]["market_winner_probability"]
        for hour in PREDAWN_HOURS
    )
    summary_index = {
        (row["split"], row["unit"], row["market_id"], row["scope"]): row
        for row in summaries
    }
    breakpoint_index = {
        (row["split"], row["unit"], row["market_id"], row["model"]): row
        for row in breakpoints
    }
    output = []
    for unit in UNITS:
        predawn = summary_index.get(
            (evidence_split, unit, "__fleet__", "predawn_03_05")
        )
        predawn_hours = [
            summary_index.get(
                (evidence_split, unit, "__fleet__", f"hour_{hour:02d}")
            )
            for hour in PREDAWN_HOURS
        ]
        evening = breakpoint_index.get(
            (evidence_split, unit, "__fleet__", "selected")
        )
        if not predawn:
            continue
        complete_predawn_hours = all(row is not None for row in predawn_hours)
        h1_predawn_pattern = (
            all(
                row["selected_vs_market"]["brier"] > 0.0
                and row["selected_vs_market"]["winner_probability"] < 0.0
                for row in predawn_hours
                if row is not None
            )
            if complete_predawn_hours
            else None
        )
        output.append(
            {
                "unit": unit,
                "historical_predawn_model_trails_market": historical_predawn_pattern,
                "h1_evidence_split": evidence_split,
                "h1_predawn_model_trails_market": h1_predawn_pattern,
                "h1_predawn_hour_count": sum(
                    row is not None for row in predawn_hours
                ),
                "h1_predawn_missing_hours": [
                    hour
                    for hour, row in zip(PREDAWN_HOURS, predawn_hours)
                    if row is None
                ],
                "predawn_direction_reproduced": (
                    historical_predawn_pattern == h1_predawn_pattern
                    if h1_predawn_pattern is not None
                    else None
                ),
                "h1_selected_market_brier_delta": predawn[
                    "selected_vs_market"
                ]["brier"],
                "h1_selected_market_winner_probability_delta": predawn[
                    "selected_vs_market"
                ]["winner_probability"],
                "h1_evening_market_catchup_hours": (
                    evening["market_catchup_hours"] if evening else []
                ),
                "h1_evening_sustained_market_catchup_hour": (
                    evening["sustained_market_catchup_hour"] if evening else None
                ),
                "claim_scope": "directional comparison only; corpora and weighting differ",
            }
        )
    return output
