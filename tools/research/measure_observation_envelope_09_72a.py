"""Measure point-in-time append-only WU observation envelopes for -09-72a.

This is a deterministic, standard-library-only census over the frozen -09-71a
decrease-event population.  It streams every snapshot in every admitted day's
``replay_inputs.jsonl`` in capture order and maintains two point-in-time WU
timestamp envelopes.  It does not fit or score a model, read market prices,
call a provider, or change anything below ``data/``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_SEED = SCRIPT_PATH.with_name("measure_observation_envelope_09_72a_seed.json")
DEFAULT_OUTPUT = (
    DEFAULT_REPO_ROOT / "docs" / "roadmap" / "observation-envelope-2026-09-72a.csv"
)
sys.path.insert(0, str(SCRIPT_PATH.parent))
import measure_high_so_far_population_09_70a as base  # noqa: E402


RULES = ("envelope_max", "envelope_last")
OUTPUT_COLUMNS = (
    "stratum",
    "market_id",
    "target_date",
    "snapshot_id",
    "mechanism",
    "captured_at_utc",
    "local_time",
    "minute_of_day",
    "window",
    "native_unit",
    "served_cutoff_hour",
    "served_high_so_far",
    "previous_served_high_so_far",
    "envelope_cutoff_hour",
    "envelope_max_high_so_far",
    "previous_envelope_max_high_so_far",
    "envelope_last_high_so_far",
    "previous_envelope_last_high_so_far",
    "envelope_max_delta_from_served",
    "envelope_last_delta_from_served",
    "current_payload_rows",
    "envelope_rows",
    "rows_recovered",
    "prior_snapshots_used",
    "max_captured_at_utc_used",
    "envelope_max_event_repaired",
    "envelope_last_event_repaired",
    "served_exceeds_settled_high",
    "envelope_max_exceeds_settled_high",
    "envelope_last_exceeds_settled_high",
    "settled_high",
)


@dataclass(frozen=True)
class EnvelopeState:
    cutoff_hour: int
    envelope_max: float
    envelope_last: float
    current_payload_rows: int
    envelope_rows: int
    rows_recovered: int
    prior_snapshots_used: int
    max_prior_captured_at_utc: str
    used_fallback: bool


def load_seed(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        seed = json.load(handle)
    base.require(
        seed.get("schema_version") == "observation_envelope_seed_v1",
        "observation envelope seed schema drifted",
    )
    return seed


def input_receipt(path: Path, root: Path, kind: str) -> dict[str, Any]:
    base.require(path.is_file(), f"input missing: {path}")
    return {
        "kind": kind,
        "path": base.relative(path, root),
        "bytes": path.stat().st_size,
        "sha256": base.sha256_file(path),
    }


def load_frozen_inputs(
    repo_root: Path,
    seed: dict[str, Any],
) -> tuple[dict[str, Any], dict[tuple[str, str, str, str], dict[str, str]], list[dict[str, Any]]]:
    spec = seed["source_population"]
    receipts = []
    named = (
        ("base_seed_relative_path", "base_seed_sha256", "base_seed"),
        ("base_harness_relative_path", "base_harness_sha256", "base_harness"),
        ("event_csv_relative_path", "event_csv_sha256", "event_csv"),
        ("event_manifest_relative_path", "event_manifest_sha256", "event_manifest"),
    )
    paths: dict[str, Path] = {}
    for path_key, hash_key, kind in named:
        path = repo_root / spec[path_key]
        receipt = input_receipt(path, repo_root, kind)
        base.require(
            receipt["sha256"] == spec[hash_key],
            f"{kind} hash drifted: {receipt['sha256']}",
        )
        paths[kind] = path
        receipts.append(receipt)
    base_seed = base.load_seed(paths["base_seed"])
    source_rows = base.read_csv(paths["event_csv"])
    base.require(len(source_rows) == 2190, f"-09-71a event rows drifted: {len(source_rows)}")
    by_key: dict[tuple[str, str, str, str], dict[str, str]] = {}
    counts = Counter()
    for row in source_rows:
        key = (row["stratum"], row["market_id"], row["target_date"], row["snapshot_id"])
        base.require(key not in by_key, f"duplicate -09-71a join key: {key}")
        by_key[key] = row
        counts[row["stratum"]] += 1
    for stratum in ("B", "C"):
        expected = int(spec["expected"][stratum]["decrease_events"])
        base.require(counts[stratum] == expected, f"{stratum} source events drifted")
    return base_seed, by_key, receipts


def rows_by_capture_key(
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[tuple[str, str], dict[tuple[str, str], list[dict[str, Any]]]]:
    output: dict[tuple[str, str], dict[tuple[str, str], list[dict[str, Any]]]] = {}
    for day, rows in rows_by_day.items():
        mapping: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            mapping[base.capture_key(row)].append(row)
        output[day] = mapping
    return output


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def valid_history_rows(
    payload: base.ReplayPayload,
    target_date: str,
) -> tuple[dict[int, list[float]], int]:
    result: dict[int, list[float]] = defaultdict(list)
    off_target_rows = 0
    for row in base.history_rows(payload):
        timestamp = str(
            row.get("datetime")
            or row.get("valid_time_local")
            or row.get("local_time")
            or ""
        )
        if len(timestamp) >= 10 and timestamp[4:5] == "-" and timestamp[7:8] == "-":
            if timestamp[:10] != target_date:
                off_target_rows += 1
                continue
        minute = base.minute_of_day(row.get("time") or row.get("datetime"))
        temperature = base.row_temperature(row)
        if minute is not None and temperature is not None:
            result[minute].append(temperature)
    return result, off_target_rows


def effective_cutoff(capture_minute: int, latest_observation_minute: int | None, cutoffs: Iterable[int]) -> int:
    ordered = tuple(sorted(int(value) for value in cutoffs))
    wall_eligible = [value for value in ordered if value <= capture_minute // 60]
    wall_cutoff = wall_eligible[-1] if wall_eligible else ordered[0]
    if latest_observation_minute is None:
        return wall_cutoff
    eligible = [
        value
        for value in ordered
        if value <= wall_cutoff and value * 60 <= latest_observation_minute
    ]
    return eligible[-1] if eligible else wall_cutoff


def envelope_value(values: dict[int, float], cutoff_hour: int, fallback: float) -> tuple[float, bool]:
    eligible = [value for minute, value in values.items() if minute <= cutoff_hour * 60]
    return (max(eligible), False) if eligible else (fallback, True)


def scan_all_replay_snapshots(
    evidence_root: Path,
    folders: dict[tuple[str, str], Path],
    feature_rows: dict[tuple[str, str], dict[tuple[str, str], list[dict[str, Any]]]],
    cutoffs: Iterable[int],
) -> tuple[
    dict[tuple[str, str, str, str], EnvelopeState],
    list[dict[str, Any]],
    dict[str, Any],
]:
    states: dict[tuple[str, str, str, str], EnvelopeState] = {}
    receipts: list[dict[str, Any]] = []
    support = Counter()
    day_snapshot_counts: dict[str, list[int]] = defaultdict(list)
    raw_order_inversion_examples: list[dict[str, str]] = []
    for day in sorted(folders):
        path = folders[day] / "replay_inputs.jsonl"
        base.require(path.is_file(), f"replay input missing: {path}")
        digest = hashlib.sha256()
        max_values: dict[int, float] = {}
        last_values: dict[int, float] = {}
        seen_capture_keys: set[tuple[str, str]] = set()
        previous_capture: datetime | None = None
        previous_capture_text = ""
        unique_snapshots = 0
        matched_feature_keys: set[tuple[str, str]] = set()
        captured_records: list[tuple[datetime, int, str, str, bytes]] = []
        prior_file_capture: datetime | None = None
        prior_file_capture_text = ""
        with path.open("rb") as handle:
            for file_index, raw in enumerate(handle):
                digest.update(raw)
                support["replay_rows_scanned"] += 1
                support["replay_bytes_scanned"] += len(raw)
                snapshot_id = base.json_value_by_key(raw, "snapshot_id")
                captured_at_utc = base.json_value_by_key(raw, "captured_at_utc")
                if not isinstance(snapshot_id, str) or not isinstance(captured_at_utc, str):
                    support["rows_without_capture_key"] += 1
                    continue
                current_capture = parse_utc(captured_at_utc)
                inverted = prior_file_capture is not None and current_capture < prior_file_capture
                support["raw_append_order_inversions"] += int(inverted)
                if inverted and len(raw_order_inversion_examples) < 10:
                    raw_order_inversion_examples.append(
                        {
                            "path": base.relative(path, evidence_root),
                            "previous_file_capture": prior_file_capture_text,
                            "current_file_capture": captured_at_utc,
                        }
                    )
                prior_file_capture = current_capture
                prior_file_capture_text = captured_at_utc
                captured_records.append(
                    (current_capture, file_index, snapshot_id, captured_at_utc, raw)
                )
        captured_records.sort(key=lambda item: (item[0], item[1]))
        for current_capture, _file_index, snapshot_id, captured_at_utc, raw in captured_records:
            short_key = (snapshot_id, captured_at_utc)
            if short_key in seen_capture_keys:
                support["duplicate_replay_capture_key_rows"] += 1
                continue
            base.require(
                previous_capture is None or current_capture > previous_capture,
                f"sorted replay capture order is not strict in {path}: {captured_at_utc} after {previous_capture_text}",
            )
            sources_start = raw.find(b'"sources"')
            base.require(sources_start >= 0, f"replay sources missing for {day} {short_key}")
            payload = base.replay_payload(raw, sources_start, include_sources=False)
            current_rows, off_target_rows = valid_history_rows(payload, day[1])
            support["off_target_wu_rows_excluded"] += off_target_rows
            for minute, temperatures in current_rows.items():
                for temperature in temperatures:
                    max_values[minute] = max(max_values.get(minute, temperature), temperature)
                    last_values[minute] = temperature
            support["valid_wu_rows_observed"] += sum(len(values) for values in current_rows.values())
            support["snapshots_with_valid_wu_rows"] += int(bool(current_rows))
            prior_snapshots = unique_snapshots
            max_prior = previous_capture_text
            unique_snapshots += 1
            seen_capture_keys.add(short_key)
            previous_capture = current_capture
            previous_capture_text = captured_at_utc
            matched_rows = feature_rows[day].get(short_key) or []
            if matched_rows:
                matched_feature_keys.add(short_key)
            for feature_row in matched_rows:
                _local_time, capture_minute = base.local_clock(feature_row)
                latest_minute = max(max_values) if max_values else None
                cutoff = effective_cutoff(capture_minute, latest_minute, cutoffs)
                max_value, max_fallback = envelope_value(max_values, cutoff, feature_row["high"])
                last_value, last_fallback = envelope_value(last_values, cutoff, feature_row["high"])
                base.require(max_fallback == last_fallback, "envelope fallback disagreement")
                rows_recovered = len(set(max_values) - set(current_rows))
                full_key = (day[0], day[1], snapshot_id, captured_at_utc)
                state = EnvelopeState(
                    cutoff_hour=cutoff,
                    envelope_max=max_value,
                    envelope_last=last_value,
                    current_payload_rows=len(current_rows),
                    envelope_rows=len(max_values),
                    rows_recovered=rows_recovered,
                    prior_snapshots_used=prior_snapshots,
                    max_prior_captured_at_utc=max_prior,
                    used_fallback=max_fallback,
                )
                existing = states.get(full_key)
                if existing is not None:
                    base.require(existing == state, f"duplicate feature capture state disagrees: {full_key}")
                states[full_key] = state
                base.require(
                    not max_prior or parse_utc(max_prior) < current_capture,
                    f"point-in-time prior receipt leaked at {full_key}",
                )
        missing_feature_keys = set(feature_rows[day]) - matched_feature_keys
        support["feature_capture_keys_missing_replay"] += len(missing_feature_keys)
        day_snapshot_counts[day[0]].append(unique_snapshots)
        receipts.append(
            {
                "kind": "replay_inputs_all_snapshots",
                "path": base.relative(path, evidence_root),
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
                "unique_snapshots": unique_snapshots,
            }
        )
    support["feature_capture_states"] = len(states)
    support["market_days_scanned"] = len(folders)
    support["all_replay_files_streamed_in_full"] = len(receipts)
    support["strict_capture_order_assertions"] = sum(item["unique_snapshots"] for item in receipts)
    support["future_snapshots_consumed"] = 0
    support["point_in_time_rule"] = "current snapshot plus only strictly earlier snapshots; max prior receipt asserted < current capture"
    support["raw_append_order_inversion_examples"] = raw_order_inversion_examples
    support["unique_snapshot_count_by_market"] = {
        market: sum(values) for market, values in sorted(day_snapshot_counts.items())
    }
    return states, receipts, dict(support)


def state_key(event: dict[str, Any], row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (event["market_id"], event["target_date"], *base.capture_key(row))


def bool_text(value: bool) -> str:
    return str(bool(value)).lower()


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_event_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for stratum in ("B", "C"):
        selected = [row for row in rows if row["stratum"] == stratum]
        stratum_result: dict[str, Any] = {
            "events": len(selected),
            "rows_recovered": {
                "positive_events": sum(int(row["rows_recovered"]) > 0 for row in selected),
                "distribution": base.quantiles([float(row["rows_recovered"]) for row in selected]),
            },
        }
        for rule in RULES:
            repaired_field = f"{rule}_event_repaired"
            delta_field = f"{rule}_delta_from_served"
            exceed_field = f"{rule}_exceeds_settled_high"
            repaired = [row for row in selected if row[repaired_field] == "true"]
            served_exceeds = sum(row["served_exceeds_settled_high"] == "true" for row in selected)
            candidate_exceeds = sum(row[exceed_field] == "true" for row in selected)
            newly_exceeds = sum(
                row["served_exceeds_settled_high"] == "false" and row[exceed_field] == "true"
                for row in selected
            )
            resolved_exceeds = sum(
                row["served_exceeds_settled_high"] == "true" and row[exceed_field] == "false"
                for row in selected
            )
            by_mechanism: dict[str, Any] = {}
            by_window: dict[str, Any] = {}
            by_minute: dict[str, Any] = {}
            for field, target in (("mechanism", by_mechanism), ("window", by_window), ("minute_of_day", by_minute)):
                for name in sorted({row[field] for row in selected}, key=lambda value: int(value) if field == "minute_of_day" else value):
                    cell = [row for row in selected if row[field] == name]
                    cell_repaired = sum(row[repaired_field] == "true" for row in cell)
                    target[name] = {
                        "events": len(cell),
                        "repaired": cell_repaired,
                        "repair_rate": cell_repaired / len(cell),
                    }
            by_unit = {}
            for unit in sorted({row["native_unit"] for row in selected}):
                deltas = [float(row[delta_field]) for row in selected if row["native_unit"] == unit]
                by_unit[unit] = {
                    "events": len(deltas),
                    "delta_from_served": base.quantiles(deltas),
                    "mean_delta_from_served": mean(deltas),
                    "raised": sum(value > base.FLOAT_TOLERANCE for value in deltas),
                    "unchanged": sum(abs(value) <= base.FLOAT_TOLERANCE for value in deltas),
                    "lowered": sum(value < -base.FLOAT_TOLERANCE for value in deltas),
                }
            stratum_result[rule] = {
                "events": len(selected),
                "repaired": len(repaired),
                "unrepaired": len(selected) - len(repaired),
                "repair_rate": len(repaired) / len(selected),
                "served_exceeds_settled_high": served_exceeds,
                "exceeds_settled_high": candidate_exceeds,
                "newly_exceeds_settled_high": newly_exceeds,
                "resolved_served_exceedance": resolved_exceeds,
                "new_exceedance_rows": [
                    {
                        "market_id": row["market_id"],
                        "target_date": row["target_date"],
                        "snapshot_id": row["snapshot_id"],
                        "native_unit": row["native_unit"],
                        "served_high_so_far": float(row["served_high_so_far"]),
                        "candidate_high_so_far": float(row[f"{rule}_high_so_far"]),
                        "settled_high": float(row["settled_high"]),
                    }
                    for row in selected
                    if row["served_exceeds_settled_high"] == "false" and row[exceed_field] == "true"
                ],
                "by_mechanism": by_mechanism,
                "by_window": by_window,
                "by_minute_of_day": by_minute,
                "by_native_unit": by_unit,
            }
        output[stratum] = stratum_result
    return output


def build_event_rows(
    events: list[dict[str, Any]],
    states: dict[tuple[str, str, str, str], EnvelopeState],
    source_events: dict[tuple[str, str, str, str], dict[str, str]],
    seed: dict[str, Any],
    market_units: dict[str, str],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    output = []
    used_source_keys: set[tuple[str, str, str, str]] = set()
    point_in_time_receipts = []
    for event in events:
        previous = event["previous"]
        current = event["current_row"]
        source_key = (event["stratum"], event["market_id"], event["target_date"], current["snapshot_id"])
        source = source_events.get(source_key)
        base.require(source is not None, f"event absent from -09-71a artifact: {source_key}")
        used_source_keys.add(source_key)
        previous_state = states.get(state_key(event, previous))
        current_state = states.get(state_key(event, current))
        base.require(previous_state is not None and current_state is not None, f"event replay state missing: {source_key}")
        base.require(base.close(float(source["high_so_far"]), current["high"]), f"served high join drift: {source_key}")
        base.require(
            not current_state.max_prior_captured_at_utc
            or parse_utc(current_state.max_prior_captured_at_utc) < parse_utc(current["captured_at_utc"]),
            f"event point-in-time receipt leaked: {source_key}",
        )
        max_repaired = current_state.envelope_max >= previous_state.envelope_max - base.FLOAT_TOLERANCE
        last_repaired = current_state.envelope_last >= previous_state.envelope_last - base.FLOAT_TOLERANCE
        local_time, minute = base.local_clock(current)
        window = base.window_label(minute, {"time_windows_local": seed["time_windows_local"]})
        row = {
            "stratum": event["stratum"],
            "market_id": event["market_id"],
            "target_date": event["target_date"],
            "snapshot_id": current["snapshot_id"],
            "mechanism": source["mechanism"],
            "captured_at_utc": current["captured_at_utc"],
            "local_time": local_time,
            "minute_of_day": str(minute),
            "window": window,
            "native_unit": market_units[event["market_id"]],
            "served_cutoff_hour": str(current["cutoff"]),
            "served_high_so_far": base.compact_number(current["high"]),
            "previous_served_high_so_far": base.compact_number(previous["high"]),
            "envelope_cutoff_hour": str(current_state.cutoff_hour),
            "envelope_max_high_so_far": base.compact_number(current_state.envelope_max),
            "previous_envelope_max_high_so_far": base.compact_number(previous_state.envelope_max),
            "envelope_last_high_so_far": base.compact_number(current_state.envelope_last),
            "previous_envelope_last_high_so_far": base.compact_number(previous_state.envelope_last),
            "envelope_max_delta_from_served": base.compact_number(current_state.envelope_max - current["high"]),
            "envelope_last_delta_from_served": base.compact_number(current_state.envelope_last - current["high"]),
            "current_payload_rows": str(current_state.current_payload_rows),
            "envelope_rows": str(current_state.envelope_rows),
            "rows_recovered": str(current_state.rows_recovered),
            "prior_snapshots_used": str(current_state.prior_snapshots_used),
            "max_captured_at_utc_used": current_state.max_prior_captured_at_utc,
            "envelope_max_event_repaired": bool_text(max_repaired),
            "envelope_last_event_repaired": bool_text(last_repaired),
            "served_exceeds_settled_high": bool_text(current["high"] > event["settled_high"] + base.FLOAT_TOLERANCE),
            "envelope_max_exceeds_settled_high": bool_text(current_state.envelope_max > event["settled_high"] + base.FLOAT_TOLERANCE),
            "envelope_last_exceeds_settled_high": bool_text(current_state.envelope_last > event["settled_high"] + base.FLOAT_TOLERANCE),
            "settled_high": base.compact_number(event["settled_high"]),
        }
        output.append(row)
        point_in_time_receipts.append(
            {
                "join_key": [row[name] for name in seed["source_population"]["join_keys"]],
                "captured_at_utc": row["captured_at_utc"],
                "prior_snapshots_used": current_state.prior_snapshots_used,
                "max_captured_at_utc_used": current_state.max_prior_captured_at_utc,
            }
        )
    base.require(used_source_keys == set(source_events), "-09-71a population did not reconcile exactly")
    output.sort(key=lambda row: (row["stratum"], row["market_id"], row["target_date"], row["local_time"], row["snapshot_id"]))
    return output, {
        "population_reconciles_09_71a": True,
        "events": len(output),
        "point_in_time_event_receipts": len(point_in_time_receipts),
        "point_in_time_receipts_sha256": base.canonical_sha256(point_in_time_receipts),
        "strict_prior_guard_failures": 0,
        "summary": summarize_event_rows(output),
    }


def candidate_for_rule(state: EnvelopeState, rule: str) -> float:
    return state.envelope_max if rule == "envelope_max" else state.envelope_last


def train_serve_comparison(
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
    states: dict[tuple[str, str, str, str], EnvelopeState],
    archive_highs: dict[tuple[str, str, int], float],
    roster: dict[tuple[str, str], base.MarketDay],
    *,
    event_keys: set[tuple[str, str, str, str]] | None = None,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for stratum in ("B", "C"):
        by_rule: dict[str, Any] = {}
        selected_rows = [
            (day, row)
            for day, rows in rows_by_day.items()
            if roster[day].stratum == stratum
            for row in rows
            if event_keys is None or (day[0], day[1], *base.capture_key(row)) in event_keys
        ]
        for rule in RULES:
            by_unit: dict[str, Any] = {}
            for unit in sorted({roster[day].unit for day, _row in selected_rows}):
                counts = Counter()
                baseline_errors: list[float] = []
                candidate_errors: list[float] = []
                movements: list[float] = []
                for day, row in selected_rows:
                    if roster[day].unit != unit:
                        continue
                    counts["snapshot_rows"] += 1
                    state = states.get((day[0], day[1], *base.capture_key(row)))
                    if state is None:
                        counts["envelope_unavailable"] += 1
                        continue
                    baseline_training = archive_highs.get((day[0], day[1], row["cutoff"]))
                    candidate_training = archive_highs.get((day[0], day[1], state.cutoff_hour))
                    if baseline_training is None or candidate_training is None:
                        counts["archive_unavailable"] += 1
                        continue
                    candidate = candidate_for_rule(state, rule)
                    baseline_error = abs(row["high"] - baseline_training)
                    candidate_error = abs(candidate - candidate_training)
                    movement = baseline_error - candidate_error
                    counts["comparable_snapshot_rows"] += 1
                    counts["baseline_mismatch"] += int(baseline_error > base.FLOAT_TOLERANCE)
                    counts["candidate_mismatch"] += int(candidate_error > base.FLOAT_TOLERANCE)
                    counts["closer"] += int(movement > base.FLOAT_TOLERANCE)
                    counts["farther"] += int(movement < -base.FLOAT_TOLERANCE)
                    counts["equal_distance"] += int(abs(movement) <= base.FLOAT_TOLERANCE)
                    baseline_errors.append(baseline_error)
                    candidate_errors.append(candidate_error)
                    movements.append(movement)
                by_unit[unit] = {
                    **dict(counts),
                    "mean_baseline_absolute_distance": mean(baseline_errors),
                    "mean_candidate_absolute_distance": mean(candidate_errors),
                    "mean_movement_toward_training": mean(movements),
                    "movement_toward_training": base.quantiles(movements),
                }
            aggregate = Counter()
            for cell in by_unit.values():
                for name in (
                    "snapshot_rows", "envelope_unavailable", "archive_unavailable",
                    "comparable_snapshot_rows", "baseline_mismatch", "candidate_mismatch",
                    "closer", "farther", "equal_distance",
                ):
                    aggregate[name] += int(cell.get(name, 0))
            by_rule[rule] = {**dict(aggregate), "by_native_unit": by_unit}
        output[stratum] = by_rule
    return output


def all_snapshot_safety(
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
    states: dict[tuple[str, str, str, str], EnvelopeState],
    roster: dict[tuple[str, str], base.MarketDay],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for stratum in ("B", "C"):
        result = {}
        selected = [(day, row) for day, rows in rows_by_day.items() if roster[day].stratum == stratum for row in rows]
        for rule in RULES:
            counts = Counter()
            deltas_by_unit: dict[str, list[float]] = defaultdict(list)
            new_exceedance_magnitudes: dict[str, list[float]] = defaultdict(list)
            new_exceedance_days: set[tuple[str, str]] = set()
            new_exceedance_markets = Counter()
            new_exceedance_examples: list[dict[str, Any]] = []
            for day, row in selected:
                counts["feature_snapshot_rows"] += 1
                state = states.get((day[0], day[1], *base.capture_key(row)))
                if state is None:
                    counts["envelope_unavailable"] += 1
                    continue
                candidate = candidate_for_rule(state, rule)
                served_exceeds = row["high"] > roster[day].settled_high + base.FLOAT_TOLERANCE
                candidate_exceeds = candidate > roster[day].settled_high + base.FLOAT_TOLERANCE
                counts["available"] += 1
                counts["fallback_rows"] += int(state.used_fallback)
                counts["served_exceeds_settled_high"] += int(served_exceeds)
                counts["exceeds_settled_high"] += int(candidate_exceeds)
                counts["newly_exceeds_settled_high"] += int(candidate_exceeds and not served_exceeds)
                counts["resolved_served_exceedance"] += int(served_exceeds and not candidate_exceeds)
                if candidate_exceeds and not served_exceeds:
                    unit = roster[day].unit
                    magnitude = candidate - roster[day].settled_high
                    new_exceedance_magnitudes[unit].append(magnitude)
                    new_exceedance_days.add(day)
                    new_exceedance_markets[day[0]] += 1
                    if len(new_exceedance_examples) < 10:
                        new_exceedance_examples.append(
                            {
                                "market_id": day[0],
                                "target_date": day[1],
                                "snapshot_id": row["snapshot_id"],
                                "captured_at_utc": row["captured_at_utc"],
                                "native_unit": unit,
                                "served_high_so_far": row["high"],
                                "candidate_high_so_far": candidate,
                                "settled_high": roster[day].settled_high,
                                "exceedance_magnitude": magnitude,
                            }
                        )
                deltas_by_unit[roster[day].unit].append(candidate - row["high"])
            result[rule] = {
                **dict(counts),
                "new_exceedance_market_days": len(new_exceedance_days),
                "new_exceedance_rows_by_market": dict(sorted(new_exceedance_markets.items())),
                "new_exceedance_magnitude_by_native_unit": {
                    unit: base.quantiles(values)
                    for unit, values in sorted(new_exceedance_magnitudes.items())
                },
                "new_exceedance_examples": new_exceedance_examples,
                "delta_from_served_by_native_unit": {
                    unit: {
                        "rows": len(values),
                        "mean": mean(values),
                        "distribution": base.quantiles(values),
                    }
                    for unit, values in sorted(deltas_by_unit.items())
                },
            }
        output[stratum] = result
    return output


def trace_event(
    spec: dict[str, str],
    events: list[dict[str, Any]],
    states: dict[tuple[str, str, str, str], EnvelopeState],
) -> dict[str, Any]:
    matches = [
        event for event in events
        if event["market_id"] == spec["market_id"]
        and event["target_date"] == spec["target_date"]
        and event["current_row"]["snapshot_id"] == spec["snapshot_id"]
    ]
    base.require(len(matches) == 1, f"known trace match drifted: {spec} -> {len(matches)}")
    event = matches[0]
    previous = event["previous"]
    current = event["current_row"]
    previous_state = states[state_key(event, previous)]
    current_state = states[state_key(event, current)]
    return {
        **spec,
        "stratum": event["stratum"],
        "previous_snapshot_id": previous["snapshot_id"],
        "previous_captured_at_utc": previous["captured_at_utc"],
        "captured_at_utc": current["captured_at_utc"],
        "served": {"previous": previous["high"], "current": current["high"]},
        "envelope_max": {
            "previous": previous_state.envelope_max,
            "current": current_state.envelope_max,
            "event_repaired": current_state.envelope_max >= previous_state.envelope_max - base.FLOAT_TOLERANCE,
        },
        "envelope_last": {
            "previous": previous_state.envelope_last,
            "current": current_state.envelope_last,
            "event_repaired": current_state.envelope_last >= previous_state.envelope_last - base.FLOAT_TOLERANCE,
        },
        "served_cutoff": {"previous": previous["cutoff"], "current": current["cutoff"]},
        "envelope_cutoff": {"previous": previous_state.cutoff_hour, "current": current_state.cutoff_hour},
        "current_payload_rows": current_state.current_payload_rows,
        "envelope_rows": current_state.envelope_rows,
        "rows_recovered": current_state.rows_recovered,
        "prior_snapshots_used": current_state.prior_snapshots_used,
        "max_captured_at_utc_used": current_state.max_prior_captured_at_utc,
        "strict_prior_guard_passed": (
            not current_state.max_prior_captured_at_utc
            or parse_utc(current_state.max_prior_captured_at_utc) < parse_utc(current["captured_at_utc"])
        ),
    }


def write_outputs(output_path: Path, rows: list[dict[str, str]], manifest: dict[str, Any]) -> dict[str, str]:
    manifest_path = output_path.with_name(output_path.stem + "-manifest.json")
    sha_path = output_path.with_suffix(".sha256")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    extract_hash = base.sha256_file(output_path)
    manifest.update({
        "extract_sha256": extract_hash,
        "extract_rows": len(rows),
        "extract_bytes": output_path.stat().st_size,
        "columns": list(OUTPUT_COLUMNS),
    })
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    sha_path.write_text(f"{extract_hash}  {output_path.name}\n", encoding="utf-8", newline="\n")
    return {
        "csv": str(output_path),
        "csv_sha256": extract_hash,
        "manifest": str(manifest_path),
        "manifest_sha256": base.sha256_file(manifest_path),
        "sha256": str(sha_path),
        "sha256_sha256": base.sha256_file(sha_path),
    }


def analyze(repo_root: Path, evidence_root: Path, seed_path: Path, output_path: Path) -> dict[str, Any]:
    seed = load_seed(seed_path)
    base_seed, source_events, frozen_receipts = load_frozen_inputs(repo_root, seed)
    roster, roster_receipt = base.load_roster(repo_root, base_seed)
    folders = base.discover_folders(evidence_root, roster, base_seed["markets"])
    rows_by_day, events, _keys_by_day, feature_receipts, population = base.load_features(
        evidence_root, roster, folders, base_seed
    )
    expected = seed["source_population"]["expected"]
    for stratum in ("B", "C"):
        for field in ("date_clusters", "market_clusters", "market_days", "decrease_events"):
            base.require(population[stratum][field] == expected[stratum][field], f"{stratum} {field} did not reconcile")
    states, replay_receipts, replay_support = scan_all_replay_snapshots(
        evidence_root,
        folders,
        rows_by_capture_key(rows_by_day),
        seed["envelope"]["cutoff_hours"],
    )
    event_rows, event_result = build_event_rows(
        events,
        states,
        source_events,
        seed,
        {market_id: str(spec["unit"]) for market_id, spec in base_seed["markets"].items()},
    )
    base.require(len(event_rows) == 2190, f"event output drifted: {len(event_rows)}")
    archive_highs, archive_receipts, archive_support = base.load_archive(evidence_root, roster, base_seed)
    baseline_train_serve = base.train_serve_summary(rows_by_day, archive_highs, roster)
    for stratum in ("B", "C"):
        base.require(
            baseline_train_serve[stratum]["comparable_snapshot_rows"] == seed["train_serve"]["baseline_expected_comparable"][stratum],
            f"{stratum} baseline comparable population drifted",
        )
        mismatch = baseline_train_serve[stratum]["training_higher_snapshot_rows"] + baseline_train_serve[stratum]["training_lower_snapshot_rows"]
        base.require(mismatch == seed["train_serve"]["baseline_expected_mismatch"][stratum], f"{stratum} baseline mismatch drifted")
    event_keys = {state_key(event, event["current_row"]) for event in events}
    all_receipts = [
        *frozen_receipts,
        roster_receipt,
        *feature_receipts,
        *replay_receipts,
        *archive_receipts,
    ]
    receipt_core = [
        {key: receipt[key] for key in ("kind", "path", "bytes", "sha256")}
        for receipt in sorted(all_receipts, key=lambda item: (item["kind"], item["path"]))
    ]
    manifest = {
        "artifact": "observation_envelope_v1",
        "built_for": "-09-72a point-in-time append-only observation envelope feasibility census",
        "source_base_commit": seed["source_base_commit"],
        "seed": {
            "relative_path": base.relative(seed_path, repo_root),
            "bytes": seed_path.stat().st_size,
            "sha256": base.sha256_file(seed_path),
        },
        "population": population,
        "population_reconciliation": event_result,
        "envelope_rules": seed["envelope"],
        "event_results": event_result["summary"],
        "all_feature_snapshot_floor_safety": all_snapshot_safety(rows_by_day, states, roster),
        "train_serve": {
            "definition": seed["train_serve"]["comparison"],
            "baseline_reproduction": baseline_train_serve,
            "all_feature_snapshots": train_serve_comparison(rows_by_day, states, archive_highs, roster),
            "decrease_event_snapshots": train_serve_comparison(rows_by_day, states, archive_highs, roster, event_keys=event_keys),
        },
        "known_traces": {
            name: trace_event(spec, events, states)
            for name, spec in seed["known_traces"].items()
        },
        "support": {
            "replay": replay_support,
            "archive": archive_support,
            "input_files": len(receipt_core),
            "input_bytes": sum(int(item["bytes"]) for item in receipt_core),
            "input_receipts_sha256": base.canonical_sha256(receipt_core),
            "input_file_kinds": dict(Counter(item["kind"] for item in receipt_core)),
            "snapshot_root": "data/snapshots under the complete workstation evidence root",
        },
        "method": {
            "interval_treatment": "exact finite-population input-integrity census; no outcome, interval, bootstrap, power calculation, or alpha look was performed",
            "B_and_C_reported_separately": True,
            "pooled_across_2026_07_31": False,
            "native_units_preserved": True,
            "current_snapshot_included": True,
            "future_snapshots_consumed": 0,
            "event_join_keys": seed["source_population"]["join_keys"],
            "all_day_snapshots_used": True,
        },
        "campaign": seed["campaign"],
        "contains_fitted_quantities": False,
        "contains_outcome_scores": False,
        "contains_market_prices": False,
        "contains_C_endpoint": False,
        "explicitly_not_done": [
            "no alpha allocation or spend, candidate fit or freeze, Brier or CRPS computation, market comparison, C endpoint, or ledger decision",
            "no high_so_far, cutoff_hour, producer, floor, collection, replay, scoring, settlement, model, or serving change",
            "no provider or exchange call, production data write, registration, restart, promotion, activation, release, trade, merge, or PR",
        ],
    }
    artifacts = write_outputs(output_path, event_rows, manifest)
    return {
        "status": "PASS",
        "verdict": "POINT_IN_TIME_OBSERVATION_ENVELOPE_MEASURED",
        "artifacts": artifacts,
        "events": event_result["summary"],
        "point_in_time": {
            "event_receipts": event_result["point_in_time_event_receipts"],
            "strict_prior_guard_failures": event_result["strict_prior_guard_failures"],
            "future_snapshots_consumed": replay_support["future_snapshots_consumed"],
        },
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    result.add_argument("--evidence-root", type=Path, default=DEFAULT_REPO_ROOT)
    result.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return result


def main() -> int:
    args = parser().parse_args()
    result = analyze(
        args.repo_root.resolve(),
        args.evidence_root.resolve(),
        args.seed.resolve(),
        args.output.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
