"""Attack and measure floor-safe point-in-time WU recovery rules for -09-73a.

This standard-library-only harness extends the frozen -09-72a observation
envelope census. It streams every retained replay payload, reproduces the two
published envelope controls, audits the disputed raw payload transitions, and
compares them with a frozen label gate and a rule stated only over payload-row
observables. It performs no fitting, outcome scoring, market comparison,
provider call, or write below ``data/``.
"""

from __future__ import annotations

import argparse
import copy
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
DEFAULT_SEED = SCRIPT_PATH.with_name("measure_safe_observation_recovery_09_73a_seed.json")
DEFAULT_OUTPUT = (
    DEFAULT_REPO_ROOT / "docs" / "roadmap" / "safe-observation-recovery-2026-09-73a.csv"
)
DEFAULT_PREREGISTRATION = (
    DEFAULT_REPO_ROOT
    / "docs"
    / "roadmap"
    / "observation-envelope-preregistration-2026-09-73a.json"
)
sys.path.insert(0, str(SCRIPT_PATH.parent))
import measure_observation_envelope_09_72a as prior  # noqa: E402


base = prior.base
RULES = (
    "envelope_max",
    "envelope_last",
    "m5_m3_label_gate",
    "observable_no_published_at_or_after",
)
NEW_CANDIDATE = "observable_no_published_at_or_after"
LABEL_COMPARATOR = "m5_m3_label_gate"
OUTPUT_COLUMNS = (
    "stratum",
    "market_id",
    "target_date",
    "snapshot_id",
    "captured_at_utc",
    "local_time",
    "minute_of_day",
    "window",
    "native_unit",
    "frozen_mechanism",
    "raw_transition_kind",
    "raw_removed_minutes",
    "raw_added_minutes",
    "raw_same_minute_value_changes",
    "served_cutoff_hour",
    "served_high_so_far",
    "previous_served_high_so_far",
    "settled_high",
    "max_captured_at_utc_used",
    "max_prior_captured_at_utc_used",
    "observable_recovered_rows",
    "observable_recovered_minutes",
    "observable_max_recovered_source_captured_at_utc",
    *tuple(
        f"{rule}_{suffix}"
        for rule in RULES
        for suffix in (
            "cutoff_hour",
            "high_so_far",
            "previous_high_so_far",
            "delta_from_served",
            "event_repaired",
            "exceeds_settled_high",
        )
    ),
)


@dataclass(frozen=True)
class ObservableState:
    cutoff_hour: int
    high_so_far: float
    current_payload_rows: int
    candidate_rows: int
    recovered_rows: int
    recovered_minutes: tuple[int, ...]
    used_fallback: bool
    prior_snapshots_used: int
    max_prior_captured_at_utc: str
    max_captured_at_utc_used: str
    max_recovered_source_captured_at_utc: str
    current_row_values: tuple[tuple[int, float], ...]
    raw_valid_row_count: int
    summary_latest_datetime: str
    summary_latest_temperature: float | None
    summary_max_temperature: float | None


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def bool_text(value: bool) -> str:
    return str(bool(value)).lower()


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def load_seed(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        seed = json.load(handle)
    base.require(
        seed.get("schema_version") == "safe_observation_recovery_seed_v2",
        "safe-recovery seed schema drifted",
    )
    return seed


def input_receipt(path: Path, root: Path, kind: str, expected_sha256: str) -> dict[str, Any]:
    base.require(path.is_file(), f"input missing: {path}")
    digest = base.sha256_file(path)
    base.require(digest == expected_sha256, f"{kind} hash drifted: {digest}")
    return {
        "kind": kind,
        "path": base.relative(path, root),
        "bytes": path.stat().st_size,
        "sha256": digest,
    }


def load_prior_protocol(
    repo_root: Path,
    seed: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[tuple[str, str, str, str], dict[str, str]],
    list[dict[str, Any]],
]:
    spec = seed["prior_protocol"]
    named = (
        ("harness_relative_path", "harness_sha256", "prior_harness"),
        ("seed_relative_path", "seed_sha256", "prior_seed"),
        ("csv_relative_path", "csv_sha256", "prior_csv"),
        ("manifest_relative_path", "manifest_sha256", "prior_manifest"),
        (
            "preregistration_relative_path",
            "preregistration_sha256",
            "prior_preregistration",
        ),
    )
    paths: dict[str, Path] = {}
    receipts: list[dict[str, Any]] = []
    for path_key, hash_key, kind in named:
        path = repo_root / spec[path_key]
        receipts.append(input_receipt(path, repo_root, kind, spec[hash_key]))
        paths[kind] = path
    prior_seed = prior.load_seed(paths["prior_seed"])
    base_seed, source_events, source_receipts = prior.load_frozen_inputs(repo_root, prior_seed)
    with paths["prior_preregistration"].open("r", encoding="utf-8") as handle:
        prior_preregistration = json.load(handle)
    base.require(
        prior_preregistration.get("outcome_scoring_authorized") is False,
        "prior protocol outcome boundary drifted",
    )
    return prior_seed, prior_preregistration, source_events, [*receipts, *source_receipts]


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


def trace_payload(
    raw: bytes,
    payload: base.ReplayPayload,
    target_date: str,
    snapshot_id: str,
    captured_at_utc: str,
) -> dict[str, Any]:
    rows = []
    for position, row in enumerate(base.history_rows(payload)):
        timestamp = str(
            row.get("datetime")
            or row.get("valid_time_local")
            or row.get("local_time")
            or ""
        )
        if len(timestamp) >= 10 and timestamp[:10] != target_date:
            continue
        minute = base.minute_of_day(row.get("time") or row.get("datetime"))
        temperature = base.row_temperature(row)
        if minute is None or temperature is None:
            continue
        rows.append(
            {
                "position": position,
                "minute_of_day": minute,
                "time": str(row.get("time") or ""),
                "datetime": timestamp,
                "temperature": temperature,
            }
        )
    latest = payload.wu_history.get("latest") or {}
    return {
        "snapshot_id": snapshot_id,
        "captured_at_utc": captured_at_utc,
        "replay_line_sha256": hashlib.sha256(raw).hexdigest(),
        "summary_latest_datetime": base.history_latest_datetime(payload),
        "summary_latest_temperature": base.row_temperature(latest),
        "summary_max_temperature": base.first_number(
            payload.wu_history,
            ("max_native", "max_c", "max_temp_native", "max_temp_c"),
        ),
        "valid_target_date_rows": len(rows),
        "rows": rows,
    }


def scan_all_replay_snapshots(
    evidence_root: Path,
    folders: dict[tuple[str, str], Path],
    feature_rows: dict[tuple[str, str], dict[tuple[str, str], list[dict[str, Any]]]],
    cutoffs: Iterable[int],
    trace_specs: dict[str, dict[str, str]],
) -> tuple[
    dict[tuple[str, str, str, str], prior.EnvelopeState],
    dict[tuple[str, str, str, str], ObservableState],
    dict[tuple[str, str, str], dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    envelope_states: dict[tuple[str, str, str, str], prior.EnvelopeState] = {}
    observable_states: dict[tuple[str, str, str, str], ObservableState] = {}
    traces: dict[tuple[str, str, str], dict[str, Any]] = {}
    trace_keys = {
        (spec["market_id"], spec["target_date"], snapshot_id)
        for spec in trace_specs.values()
        for snapshot_id in (spec["previous_snapshot_id"], spec["snapshot_id"])
    }
    receipts: list[dict[str, Any]] = []
    support = Counter()
    raw_order_inversion_examples: list[dict[str, str]] = []
    for day in sorted(folders):
        path = folders[day] / "replay_inputs.jsonl"
        base.require(path.is_file(), f"replay input missing: {path}")
        digest = hashlib.sha256()
        max_values: dict[int, float] = {}
        last_values: dict[int, float] = {}
        last_value_sources: dict[int, str] = {}
        seen_capture_keys: set[tuple[str, str]] = set()
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
        previous_capture: datetime | None = None
        previous_capture_text = ""
        unique_snapshots = 0
        for current_capture, _file_index, snapshot_id, captured_at_utc, raw in captured_records:
            short_key = (snapshot_id, captured_at_utc)
            if short_key in seen_capture_keys:
                support["duplicate_replay_capture_key_rows"] += 1
                continue
            base.require(
                previous_capture is None or current_capture > previous_capture,
                f"sorted replay capture order is not strict in {path}: {captured_at_utc}",
            )
            sources_start = raw.find(b'"sources"')
            base.require(sources_start >= 0, f"replay sources missing for {day} {short_key}")
            payload = base.replay_payload(raw, sources_start, include_sources=False)
            current_rows, off_target_rows = prior.valid_history_rows(payload, day[1])
            support["off_target_wu_rows_excluded"] += off_target_rows
            current_last = {minute: temperatures[-1] for minute, temperatures in current_rows.items()}
            for minute, temperatures in current_rows.items():
                for temperature in temperatures:
                    max_values[minute] = max(max_values.get(minute, temperature), temperature)
                    last_values[minute] = temperature
                    last_value_sources[minute] = captured_at_utc
            current_latest = max(current_last) if current_last else None
            observable_values = dict(current_last)
            recovered_sources: list[str] = []
            recovered_minutes = []
            for minute, value in last_values.items():
                if minute in current_last:
                    continue
                if current_latest is None or current_latest < minute:
                    observable_values[minute] = value
                    recovered_minutes.append(minute)
                    recovered_sources.append(last_value_sources[minute])
            support["valid_wu_rows_observed"] += sum(len(values) for values in current_rows.values())
            support["snapshots_with_valid_wu_rows"] += int(bool(current_rows))
            prior_snapshots = unique_snapshots
            max_prior = previous_capture_text
            unique_snapshots += 1
            seen_capture_keys.add(short_key)
            previous_capture = current_capture
            previous_capture_text = captured_at_utc
            trace_key = (day[0], day[1], snapshot_id)
            if trace_key in trace_keys:
                base.require(trace_key not in traces, f"duplicate trace payload: {trace_key}")
                traces[trace_key] = trace_payload(
                    raw, payload, day[1], snapshot_id, captured_at_utc
                )
            matched_rows = feature_rows[day].get(short_key) or []
            if matched_rows:
                matched_feature_keys.add(short_key)
            for feature_row in matched_rows:
                _local_time, capture_minute = base.local_clock(feature_row)
                envelope_latest = max(max_values) if max_values else None
                envelope_cutoff = prior.effective_cutoff(capture_minute, envelope_latest, cutoffs)
                envelope_max, max_fallback = prior.envelope_value(
                    max_values, envelope_cutoff, feature_row["high"]
                )
                envelope_last, last_fallback = prior.envelope_value(
                    last_values, envelope_cutoff, feature_row["high"]
                )
                base.require(max_fallback == last_fallback, "envelope fallback disagreement")
                observable_latest = max(observable_values) if observable_values else None
                observable_cutoff = prior.effective_cutoff(
                    capture_minute, observable_latest, cutoffs
                )
                observable_high, observable_fallback = prior.envelope_value(
                    observable_values, observable_cutoff, feature_row["high"]
                )
                full_key = (day[0], day[1], snapshot_id, captured_at_utc)
                envelope_state = prior.EnvelopeState(
                    cutoff_hour=envelope_cutoff,
                    envelope_max=envelope_max,
                    envelope_last=envelope_last,
                    current_payload_rows=len(current_rows),
                    envelope_rows=len(max_values),
                    rows_recovered=len(set(max_values) - set(current_rows)),
                    prior_snapshots_used=prior_snapshots,
                    max_prior_captured_at_utc=max_prior,
                    used_fallback=max_fallback,
                )
                latest_summary = payload.wu_history.get("latest") or {}
                observable_state = ObservableState(
                    cutoff_hour=observable_cutoff,
                    high_so_far=observable_high,
                    current_payload_rows=len(current_rows),
                    candidate_rows=len(observable_values),
                    recovered_rows=len(recovered_minutes),
                    recovered_minutes=tuple(sorted(recovered_minutes)),
                    used_fallback=observable_fallback,
                    prior_snapshots_used=prior_snapshots,
                    max_prior_captured_at_utc=max_prior,
                    max_captured_at_utc_used=captured_at_utc,
                    max_recovered_source_captured_at_utc=(
                        max(recovered_sources, key=parse_utc) if recovered_sources else ""
                    ),
                    current_row_values=tuple(sorted(current_last.items())),
                    raw_valid_row_count=sum(len(values) for values in current_rows.values()),
                    summary_latest_datetime=base.history_latest_datetime(payload),
                    summary_latest_temperature=base.row_temperature(latest_summary),
                    summary_max_temperature=base.first_number(
                        payload.wu_history,
                        ("max_native", "max_c", "max_temp_native", "max_temp_c"),
                    ),
                )
                existing_envelope = envelope_states.get(full_key)
                existing_observable = observable_states.get(full_key)
                if existing_envelope is not None:
                    base.require(existing_envelope == envelope_state, f"envelope state drift: {full_key}")
                    base.require(existing_observable == observable_state, f"observable state drift: {full_key}")
                envelope_states[full_key] = envelope_state
                observable_states[full_key] = observable_state
                base.require(
                    not max_prior or parse_utc(max_prior) < current_capture,
                    f"point-in-time prior receipt leaked at {full_key}",
                )
                base.require(
                    parse_utc(observable_state.max_captured_at_utc_used) <= current_capture,
                    f"point-in-time current receipt leaked at {full_key}",
                )
                base.require(
                    not observable_state.max_recovered_source_captured_at_utc
                    or parse_utc(observable_state.max_recovered_source_captured_at_utc)
                    < current_capture,
                    f"recovered-row receipt is not strict-prior at {full_key}",
                )
        support["feature_capture_keys_missing_replay"] += len(
            set(feature_rows[day]) - matched_feature_keys
        )
        receipts.append(
            {
                "kind": "replay_inputs_all_snapshots",
                "path": base.relative(path, evidence_root),
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
                "unique_snapshots": unique_snapshots,
            }
        )
    base.require(set(traces) == trace_keys, f"known raw traces missing: {trace_keys - set(traces)}")
    support["feature_capture_states"] = len(envelope_states)
    support["market_days_scanned"] = len(folders)
    support["all_replay_files_streamed_in_full"] = len(receipts)
    support["strict_capture_order_assertions"] = sum(
        item["unique_snapshots"] for item in receipts
    )
    support["future_snapshots_consumed"] = 0
    support["blank_snapshot_receipts"] = sum(
        not state.max_captured_at_utc_used for state in observable_states.values()
    )
    support["strict_prior_recovery_failures"] = 0
    support["raw_append_order_inversion_examples"] = raw_order_inversion_examples
    return envelope_states, observable_states, traces, receipts, dict(support)


def state_key(event: dict[str, Any], row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (event["market_id"], event["target_date"], *base.capture_key(row))


def event_mechanism_lookup(
    source_events: dict[tuple[str, str, str, str], dict[str, str]],
) -> dict[tuple[str, str, str], str]:
    output = {}
    for (stratum, market_id, target_date, snapshot_id), row in source_events.items():
        if stratum != "B":
            continue
        key = (market_id, target_date, snapshot_id)
        base.require(key not in output, f"duplicate event mechanism key: {key}")
        output[key] = row["mechanism"]
    return output


def candidate_value(
    rule: str,
    day: tuple[str, str],
    row: dict[str, Any],
    stratum: str,
    envelope_state: prior.EnvelopeState,
    observable_state: ObservableState,
    event_mechanisms: dict[tuple[str, str, str], str],
) -> tuple[float, int]:
    if rule == "envelope_max":
        return envelope_state.envelope_max, envelope_state.cutoff_hour
    if rule == "envelope_last":
        return envelope_state.envelope_last, envelope_state.cutoff_hour
    if stratum != "B":
        return row["high"], row["cutoff"]
    if rule == LABEL_COMPARATOR:
        mechanism = event_mechanisms.get((day[0], day[1], row["snapshot_id"]))
        if mechanism in {"M5_cutoff_change", "M3_rows_dropped"}:
            return envelope_state.envelope_last, envelope_state.cutoff_hour
        return row["high"], row["cutoff"]
    base.require(rule == NEW_CANDIDATE, f"unknown candidate rule: {rule}")
    return observable_state.high_so_far, observable_state.cutoff_hour


def raw_transition(
    previous_state: ObservableState,
    current_state: ObservableState,
) -> dict[str, Any]:
    previous = dict(previous_state.current_row_values)
    current = dict(current_state.current_row_values)
    removed = sorted(set(previous) - set(current))
    added = sorted(set(current) - set(previous))
    changed = sorted(
        minute
        for minute in set(previous) & set(current)
        if not base.close(previous[minute], current[minute])
    )
    if removed or added:
        kind = "timestamp_set_changed"
    elif changed:
        kind = "same_timestamp_value_changed"
    else:
        kind = "no_valid_row_change"
    return {
        "kind": kind,
        "removed_minutes": removed,
        "added_minutes": added,
        "same_minute_value_changes": changed,
    }


def build_event_rows(
    events: list[dict[str, Any]],
    envelope_states: dict[tuple[str, str, str, str], prior.EnvelopeState],
    observable_states: dict[tuple[str, str, str, str], ObservableState],
    source_events: dict[tuple[str, str, str, str], dict[str, str]],
    event_mechanisms: dict[tuple[str, str, str], str],
    prior_seed: dict[str, Any],
    market_units: dict[str, str],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    output: list[dict[str, str]] = []
    used_source_keys: set[tuple[str, str, str, str]] = set()
    receipt_rows = []
    for event in events:
        previous = event["previous"]
        current = event["current_row"]
        source_key = (
            event["stratum"],
            event["market_id"],
            event["target_date"],
            current["snapshot_id"],
        )
        source = source_events.get(source_key)
        base.require(source is not None, f"event absent from -09-71a artifact: {source_key}")
        used_source_keys.add(source_key)
        previous_envelope = envelope_states[state_key(event, previous)]
        current_envelope = envelope_states[state_key(event, current)]
        previous_observable = observable_states[state_key(event, previous)]
        current_observable = observable_states[state_key(event, current)]
        transition = raw_transition(previous_observable, current_observable)
        local_time, minute = base.local_clock(current)
        window = base.window_label(minute, prior_seed)
        row: dict[str, str] = {
            "stratum": event["stratum"],
            "market_id": event["market_id"],
            "target_date": event["target_date"],
            "snapshot_id": current["snapshot_id"],
            "captured_at_utc": current["captured_at_utc"],
            "local_time": local_time,
            "minute_of_day": str(minute),
            "window": window,
            "native_unit": market_units[event["market_id"]],
            "frozen_mechanism": source["mechanism"],
            "raw_transition_kind": transition["kind"],
            "raw_removed_minutes": "|".join(str(value) for value in transition["removed_minutes"]),
            "raw_added_minutes": "|".join(str(value) for value in transition["added_minutes"]),
            "raw_same_minute_value_changes": "|".join(
                str(value) for value in transition["same_minute_value_changes"]
            ),
            "served_cutoff_hour": str(current["cutoff"]),
            "served_high_so_far": base.compact_number(current["high"]),
            "previous_served_high_so_far": base.compact_number(previous["high"]),
            "settled_high": base.compact_number(event["settled_high"]),
            "max_captured_at_utc_used": current_observable.max_captured_at_utc_used,
            "max_prior_captured_at_utc_used": current_observable.max_prior_captured_at_utc,
            "observable_recovered_rows": str(current_observable.recovered_rows),
            "observable_recovered_minutes": "|".join(
                str(value) for value in current_observable.recovered_minutes
            ),
            "observable_max_recovered_source_captured_at_utc": (
                current_observable.max_recovered_source_captured_at_utc
            ),
        }
        day = (event["market_id"], event["target_date"])
        for rule in RULES:
            previous_value, _previous_cutoff = candidate_value(
                rule,
                day,
                previous,
                event["stratum"],
                previous_envelope,
                previous_observable,
                event_mechanisms,
            )
            current_value, current_cutoff = candidate_value(
                rule,
                day,
                current,
                event["stratum"],
                current_envelope,
                current_observable,
                event_mechanisms,
            )
            row[f"{rule}_cutoff_hour"] = str(current_cutoff)
            row[f"{rule}_high_so_far"] = base.compact_number(current_value)
            row[f"{rule}_previous_high_so_far"] = base.compact_number(previous_value)
            row[f"{rule}_delta_from_served"] = base.compact_number(
                current_value - current["high"]
            )
            row[f"{rule}_event_repaired"] = bool_text(
                current_value >= previous_value - base.FLOAT_TOLERANCE
            )
            row[f"{rule}_exceeds_settled_high"] = bool_text(
                current_value > event["settled_high"] + base.FLOAT_TOLERANCE
            )
        output.append(row)
        base.require(bool(row["max_captured_at_utc_used"]), f"blank event receipt: {source_key}")
        base.require(
            bool(row["max_prior_captured_at_utc_used"]),
            f"blank strict-prior event receipt: {source_key}",
        )
        base.require(
            parse_utc(row["max_captured_at_utc_used"])
            <= parse_utc(row["captured_at_utc"]),
            f"future event receipt: {source_key}",
        )
        receipt_rows.append(
            {
                "join_key": list(source_key),
                "captured_at_utc": row["captured_at_utc"],
                "max_captured_at_utc_used": row["max_captured_at_utc_used"],
                "max_prior_captured_at_utc_used": row["max_prior_captured_at_utc_used"],
                "max_recovered_source_captured_at_utc": row[
                    "observable_max_recovered_source_captured_at_utc"
                ],
            }
        )
    base.require(used_source_keys == set(source_events), "-09-71a population did not reconcile")
    output.sort(
        key=lambda row: (
            row["stratum"],
            row["market_id"],
            row["target_date"],
            row["local_time"],
            row["snapshot_id"],
        )
    )
    return output, {
        "events": len(output),
        "event_receipts": len(receipt_rows),
        "blank_current_snapshot_receipts": sum(
            not row["max_captured_at_utc_used"] for row in receipt_rows
        ),
        "blank_prior_snapshot_receipts": sum(
            not row["max_prior_captured_at_utc_used"] for row in receipt_rows
        ),
        "future_event_receipts": 0,
        "event_receipts_sha256": base.canonical_sha256(receipt_rows),
    }


def summarize_events(rows: list[dict[str, str]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for stratum in ("B", "C"):
        selected = [row for row in rows if row["stratum"] == stratum]
        result: dict[str, Any] = {"events": len(selected)}
        for rule in RULES:
            repaired_field = f"{rule}_event_repaired"
            repaired = sum(row[repaired_field] == "true" for row in selected)
            by_mechanism = {}
            for mechanism in sorted({row["frozen_mechanism"] for row in selected}):
                cell = [row for row in selected if row["frozen_mechanism"] == mechanism]
                by_mechanism[mechanism] = {
                    "events": len(cell),
                    "repaired": sum(row[repaired_field] == "true" for row in cell),
                }
            decision_rows = [
                row
                for row in selected
                if row["window"] in {"peak_heating_window", "settlement_window"}
            ]
            result[rule] = {
                "repaired": repaired,
                "repair_rate": repaired / len(selected),
                "by_mechanism": by_mechanism,
                "decision_window_events": len(decision_rows),
                "decision_window_repaired": sum(
                    row[repaired_field] == "true" for row in decision_rows
                ),
            }
        output[stratum] = result
    return output


def posthoc_m5_m3_filter_control(
    rows: list[dict[str, str]], seed: dict[str, Any]
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row["stratum"] == "B"
        and row["frozen_mechanism"] in {"M5_cutoff_change", "M3_rows_dropped"}
        and row["envelope_last_event_repaired"] == "true"
    ]
    decision = [
        row
        for row in selected
        if row["window"] in {"peak_heating_window", "settlement_window"}
    ]
    expected = seed["posthoc_m5_m3_filter_control"]
    base.require(len(selected) == expected["B_repaired"], "post-hoc M5+M3 repair control drifted")
    base.require(
        len(decision) == expected["B_decision_window_repaired"],
        "post-hoc M5+M3 decision-window control drifted",
    )
    return {
        "B_repaired": len(selected),
        "B_decision_window_repaired": len(decision),
        "event_rows_newly_above_settlement": sum(
            row["envelope_last_exceeds_settled_high"] == "true"
            and float(row["served_high_so_far"]) <= float(row["settled_high"])
            for row in selected
        ),
        "full_snapshot_safety": "NOT_DEFINED_BY_THE_POSTHOC_FILTER",
        "not_a_candidate_reason": expected["not_a_candidate_reason"],
        "nearest_stateful_operationalization": LABEL_COMPARATOR,
    }


def all_snapshot_safety(
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
    envelope_states: dict[tuple[str, str, str, str], prior.EnvelopeState],
    observable_states: dict[tuple[str, str, str, str], ObservableState],
    roster: dict[tuple[str, str], base.MarketDay],
    event_mechanisms: dict[tuple[str, str, str], str],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for stratum in ("B", "C"):
        selected = [
            (day, row)
            for day, rows in rows_by_day.items()
            if roster[day].stratum == stratum
            for row in rows
        ]
        result = {}
        for rule in RULES:
            counts = Counter()
            examples = []
            magnitudes: dict[str, list[float]] = defaultdict(list)
            deltas: dict[str, list[float]] = defaultdict(list)
            for day, row in selected:
                counts["admitted_feature_snapshot_rows"] += 1
                key = (day[0], day[1], *base.capture_key(row))
                envelope_state = envelope_states.get(key)
                observable_state = observable_states.get(key)
                if envelope_state is None or observable_state is None:
                    counts["replay_unavailable"] += 1
                    continue
                candidate, _cutoff = candidate_value(
                    rule,
                    day,
                    row,
                    stratum,
                    envelope_state,
                    observable_state,
                    event_mechanisms,
                )
                served_exceeds = row["high"] > roster[day].settled_high + base.FLOAT_TOLERANCE
                candidate_exceeds = candidate > roster[day].settled_high + base.FLOAT_TOLERANCE
                counts["available"] += 1
                counts["served_exceeds_settled_high"] += int(served_exceeds)
                counts["exceeds_settled_high"] += int(candidate_exceeds)
                counts["newly_exceeds_settled_high"] += int(candidate_exceeds and not served_exceeds)
                counts["resolved_served_exceedance"] += int(served_exceeds and not candidate_exceeds)
                counts["blank_snapshot_receipts"] += int(
                    not observable_state.max_captured_at_utc_used
                )
                counts["future_snapshots_consumed"] += int(
                    parse_utc(observable_state.max_captured_at_utc_used)
                    > parse_utc(row["captured_at_utc"])
                )
                unit = roster[day].unit
                deltas[unit].append(candidate - row["high"])
                if candidate_exceeds and not served_exceeds:
                    magnitudes[unit].append(candidate - roster[day].settled_high)
                    if len(examples) < 10:
                        examples.append(
                            {
                                "market_id": day[0],
                                "target_date": day[1],
                                "snapshot_id": row["snapshot_id"],
                                "captured_at_utc": row["captured_at_utc"],
                                "native_unit": unit,
                                "served_high_so_far": row["high"],
                                "candidate_high_so_far": candidate,
                                "settled_high": roster[day].settled_high,
                            }
                        )
            result[rule] = {
                **dict(counts),
                "new_exceedance_examples": examples,
                "new_exceedance_magnitude_by_native_unit": {
                    unit: base.quantiles(values) for unit, values in sorted(magnitudes.items())
                },
                "delta_from_served_by_native_unit": {
                    unit: {
                        "rows": len(values),
                        "mean": mean(values),
                        "distribution": base.quantiles(values),
                    }
                    for unit, values in sorted(deltas.items())
                },
            }
        output[stratum] = result
    return output


def train_serve_comparison(
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
    envelope_states: dict[tuple[str, str, str, str], prior.EnvelopeState],
    observable_states: dict[tuple[str, str, str, str], ObservableState],
    archive_highs: dict[tuple[str, str, int], float],
    roster: dict[tuple[str, str], base.MarketDay],
    event_mechanisms: dict[tuple[str, str, str], str],
) -> dict[str, Any]:
    selected = [
        (day, row)
        for day, rows in rows_by_day.items()
        if roster[day].stratum == "B"
        for row in rows
    ]
    output = {}
    for rule in RULES:
        counts = Counter()
        by_unit_counts: dict[str, Counter] = defaultdict(Counter)
        for day, row in selected:
            key = (day[0], day[1], *base.capture_key(row))
            envelope_state = envelope_states.get(key)
            observable_state = observable_states.get(key)
            if envelope_state is None or observable_state is None:
                counts["replay_unavailable"] += 1
                continue
            candidate, candidate_cutoff = candidate_value(
                rule,
                day,
                row,
                "B",
                envelope_state,
                observable_state,
                event_mechanisms,
            )
            baseline_training = archive_highs.get((day[0], day[1], row["cutoff"]))
            candidate_training = archive_highs.get((day[0], day[1], candidate_cutoff))
            if baseline_training is None or candidate_training is None:
                counts["archive_unavailable"] += 1
                continue
            baseline_error = abs(row["high"] - baseline_training)
            candidate_error = abs(candidate - candidate_training)
            movement = baseline_error - candidate_error
            unit_counts = by_unit_counts[roster[day].unit]
            for target in (counts, unit_counts):
                target["comparable_snapshot_rows"] += 1
                target["baseline_mismatch"] += int(baseline_error > base.FLOAT_TOLERANCE)
                target["candidate_mismatch"] += int(candidate_error > base.FLOAT_TOLERANCE)
                target["closer"] += int(movement > base.FLOAT_TOLERANCE)
                target["farther"] += int(movement < -base.FLOAT_TOLERANCE)
                target["equal_distance"] += int(abs(movement) <= base.FLOAT_TOLERANCE)
        comparable = counts["comparable_snapshot_rows"]
        output[rule] = {
            **dict(counts),
            "baseline_mismatch_rate": counts["baseline_mismatch"] / comparable,
            "candidate_mismatch_rate": counts["candidate_mismatch"] / comparable,
            "widens_train_serve_skew": counts["candidate_mismatch"] > counts["baseline_mismatch"],
            "by_native_unit": {
                unit: dict(values) for unit, values in sorted(by_unit_counts.items())
            },
        }
    return output


def minute_rows(trace: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["minute_of_day"]): row for row in trace["rows"]}


def build_known_traces(
    seed: dict[str, Any],
    traces: dict[tuple[str, str, str], dict[str, Any]],
    event_rows: list[dict[str, str]],
) -> dict[str, Any]:
    event_lookup = {
        (row["market_id"], row["target_date"], row["snapshot_id"]): row
        for row in event_rows
    }
    output = {}
    for name, spec in seed["known_traces"].items():
        previous = traces[(spec["market_id"], spec["target_date"], spec["previous_snapshot_id"])]
        current = traces[(spec["market_id"], spec["target_date"], spec["snapshot_id"])]
        previous_rows = minute_rows(previous)
        current_rows = minute_rows(current)
        removed = sorted(set(previous_rows) - set(current_rows))
        added = sorted(set(current_rows) - set(previous_rows))
        changed = sorted(
            minute
            for minute in set(previous_rows) & set(current_rows)
            if not base.close(
                float(previous_rows[minute]["temperature"]),
                float(current_rows[minute]["temperature"]),
            )
        )
        positional_changes = []
        for previous_row, current_row in zip(previous["rows"], current["rows"]):
            if not base.close(
                float(previous_row["temperature"]), float(current_row["temperature"])
            ):
                positional_changes.append(
                    {
                        "position": previous_row["position"],
                        "previous_minute": previous_row["minute_of_day"],
                        "current_minute": current_row["minute_of_day"],
                        "previous_temperature": previous_row["temperature"],
                        "current_temperature": current_row["temperature"],
                    }
                )
        event = event_lookup[(spec["market_id"], spec["target_date"], spec["snapshot_id"])]
        label_valid = not (
            event["frozen_mechanism"] == "M1_restatement" and bool(removed or added)
        )
        output[name] = {
            **spec,
            "previous_payload": previous,
            "current_payload": current,
            "raw_row_identity_diff": {
                "removed_minutes": removed,
                "added_minutes": added,
                "same_minute_value_changes": changed,
                "positional_temperature_changes": positional_changes,
            },
            "frozen_mechanism": event["frozen_mechanism"],
            "summary_latest_datetime_equal": (
                previous["summary_latest_datetime"] == current["summary_latest_datetime"]
            ),
            "raw_row_count_equal": (
                previous["valid_target_date_rows"] == current["valid_target_date_rows"]
            ),
            "frozen_label_valid_against_raw_timestamp_identity": label_valid,
            "served": {
                "previous": float(event["previous_served_high_so_far"]),
                "current": float(event["served_high_so_far"]),
            },
            NEW_CANDIDATE: {
                "previous": float(event[f"{NEW_CANDIDATE}_previous_high_so_far"]),
                "current": float(event[f"{NEW_CANDIDATE}_high_so_far"]),
                "event_repaired": event[f"{NEW_CANDIDATE}_event_repaired"] == "true",
                "cutoff_hour": int(event[f"{NEW_CANDIDATE}_cutoff_hour"]),
            },
        }
    san_francisco = output["san_francisco_revision"]
    base.require(
        san_francisco["frozen_mechanism"] == "M1_restatement"
        and san_francisco["raw_row_identity_diff"]["removed_minutes"] == [780]
        and san_francisco["raw_row_identity_diff"]["added_minutes"] == [840]
        and san_francisco["frozen_label_valid_against_raw_timestamp_identity"] is False,
        "San Francisco contradiction did not resolve to a raw timestamp-set change",
    )
    atlanta = output["atlanta_loss"]
    base.require(
        652 in atlanta["raw_row_identity_diff"]["removed_minutes"]
        and not [minute for minute in atlanta["raw_row_identity_diff"]["added_minutes"] if minute >= 652],
        "Atlanta raw-tail-loss positive control drifted",
    )
    return output


def assert_positive_controls(
    seed: dict[str, Any],
    prior_seed: dict[str, Any],
    events: list[dict[str, Any]],
    envelope_states: dict[tuple[str, str, str, str], prior.EnvelopeState],
    source_events: dict[tuple[str, str, str, str], dict[str, str]],
    market_units: dict[str, str],
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
    roster: dict[tuple[str, str], base.MarketDay],
    replay_support: dict[str, Any],
) -> dict[str, Any]:
    _rows, event_result = prior.build_event_rows(
        events, envelope_states, source_events, prior_seed, market_units
    )
    floor = prior.all_snapshot_safety(rows_by_day, envelope_states, roster)
    expected = seed["positive_controls_09_72a"]
    for rule in ("envelope_max", "envelope_last"):
        base.require(
            event_result["summary"]["B"][rule]["repaired"]
            == expected[f"B_repaired_by_{rule}"],
            f"{rule} B repair positive control drifted",
        )
        decision_repaired = sum(
            event_result["summary"]["B"][rule]["by_window"][window]["repaired"]
            for window in ("peak_heating_window", "settlement_window")
        )
        base.require(
            decision_repaired == expected["B_decision_window_repaired_by_each_envelope"],
            f"{rule} decision-window positive control drifted",
        )
        base.require(
            event_result["summary"]["C"][rule]["repaired"]
            == expected["C_repaired_by_each_envelope"],
            f"{rule} C repair positive control drifted",
        )
        base.require(
            floor["B"][rule]["newly_exceeds_settled_high"]
            == expected["B_new_above_settlement_by_each_envelope"],
            f"{rule} B floor positive control drifted",
        )
        base.require(
            floor["C"][rule]["newly_exceeds_settled_high"]
            == expected["C_new_above_settlement_by_each_envelope"],
            f"{rule} C floor positive control drifted",
        )
    base.require(
        replay_support["future_snapshots_consumed"] == expected["future_snapshots_consumed"],
        "future-snapshot positive control drifted",
    )
    return {
        "status": "PASS",
        "event_results": event_result["summary"],
        "all_snapshot_floor_safety": floor,
        "strict_prior_guard_failures": 0,
        "future_snapshots_consumed": replay_support["future_snapshots_consumed"],
    }


def evaluate_gates(
    seed: dict[str, Any],
    event_summary: dict[str, Any],
    safety: dict[str, Any],
    train_serve: dict[str, Any],
    replay_support: dict[str, Any],
    event_receipts: dict[str, Any],
) -> dict[str, Any]:
    expected_population = seed["expected_population"]["B"]
    candidate_safety = safety["B"][NEW_CANDIDATE]
    candidate_events = event_summary["B"][NEW_CANDIDATE]
    candidate_train_serve = train_serve[NEW_CANDIDATE]
    gates = {
        "all_B_feature_snapshots_measured": {
            "pass": candidate_safety["available"]
            == expected_population["feature_snapshots_with_replay"],
            "measured": candidate_safety["available"],
            "required": expected_population["feature_snapshots_with_replay"],
        },
        "trusted_floor_safety": {
            "pass": candidate_safety["newly_exceeds_settled_high"]
            == seed["hard_gates"]["new_above_settlement_on_all_B_feature_snapshots_with_replay"],
            "measured": candidate_safety["newly_exceeds_settled_high"],
            "required": 0,
        },
        "material_decision_window_repair": {
            "pass": candidate_events["decision_window_repaired"]
            >= seed["hard_gates"]["minimum_material_decision_window_repairs"],
            "measured": candidate_events["decision_window_repaired"],
            "of": candidate_events["decision_window_events"],
        },
        "point_in_time_receipts": {
            "pass": candidate_safety["future_snapshots_consumed"] == 0
            and candidate_safety["blank_snapshot_receipts"] == 0
            and replay_support["strict_prior_recovery_failures"] == 0
            and event_receipts["blank_current_snapshot_receipts"] == 0
            and event_receipts["blank_prior_snapshot_receipts"] == 0
            and event_receipts["future_event_receipts"] == 0,
            "future_snapshots_consumed": candidate_safety["future_snapshots_consumed"],
            "blank_snapshot_receipts": candidate_safety["blank_snapshot_receipts"],
            "blank_event_current_snapshot_receipts": event_receipts[
                "blank_current_snapshot_receipts"
            ],
            "blank_event_prior_snapshot_receipts": event_receipts[
                "blank_prior_snapshot_receipts"
            ],
            "future_event_receipts": event_receipts["future_event_receipts"],
            "strict_prior_recovery_failures": replay_support[
                "strict_prior_recovery_failures"
            ],
        },
        "train_serve_skew_non_widening": {
            "pass": not candidate_train_serve["widens_train_serve_skew"],
            "baseline_mismatch": candidate_train_serve["baseline_mismatch"],
            "candidate_mismatch": candidate_train_serve["candidate_mismatch"],
            "comparable_snapshot_rows": candidate_train_serve["comparable_snapshot_rows"],
        },
    }
    return {
        "candidate": NEW_CANDIDATE,
        "gates": gates,
        "all_pass": all(value["pass"] for value in gates.values()),
    }


def write_outputs(
    output_path: Path,
    rows: list[dict[str, str]],
    manifest: dict[str, Any],
) -> dict[str, str]:
    manifest_path = output_path.with_name(output_path.stem + "-manifest.json")
    sha_path = output_path.with_suffix(".sha256")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    extract_hash = base.sha256_file(output_path)
    manifest.update(
        {
            "extract_sha256": extract_hash,
            "extract_rows": len(rows),
            "extract_bytes": output_path.stat().st_size,
            "columns": list(OUTPUT_COLUMNS),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sha_path.write_text(
        f"{extract_hash}  {output_path.name}\n", encoding="utf-8", newline="\n"
    )
    return {
        "csv": str(output_path),
        "csv_sha256": extract_hash,
        "manifest": str(manifest_path),
        "manifest_sha256": base.sha256_file(manifest_path),
        "sha256": str(sha_path),
        "sha256_sha256": base.sha256_file(sha_path),
    }


def write_preregistration(
    path: Path,
    repo_root: Path,
    seed: dict[str, Any],
    prior_preregistration: dict[str, Any],
    artifacts: dict[str, str],
    gate_result: dict[str, Any],
    event_summary: dict[str, Any],
    safety: dict[str, Any],
    train_serve: dict[str, Any],
    known_traces: dict[str, Any],
) -> dict[str, str]:
    base.require(gate_result["all_pass"], "refusing to freeze a safety-blocked candidate")
    candidate_events = event_summary["B"][NEW_CANDIDATE]
    candidate_safety = safety["B"][NEW_CANDIDATE]
    candidate_train_serve = train_serve[NEW_CANDIDATE]
    payload = {
        "schema_version": "observation_envelope_outcome_preregistration_v2",
        "mission": "2026-09-73a",
        "status": "FROZEN_PRE_REGISTRATION_SAFETY_CLEARED_ALPHA_UNALLOCATED_NOT_EXECUTABLE",
        "protocol_frozen": True,
        "candidate_artifact_frozen": True,
        "outcome_scoring_authorized": False,
        "reason_outcome_scoring_is_blocked": (
            "The deterministic payload-observable candidate cleared every -09-73a input-integrity "
            "gate, but this mission allocates no alpha. Outcome scoring remains forbidden until "
            "the operator explicitly allocates the campaign decision and authorizes the first look."
        ),
        "bound_input_integrity_evidence": {
            "csv": {
                "path": base.relative(Path(artifacts["csv"]), repo_root),
                "sha256": artifacts["csv_sha256"],
                "rows": 2190,
            },
            "manifest": {
                "path": base.relative(Path(artifacts["manifest"]), repo_root),
                "sha256": artifacts["manifest_sha256"],
            },
            "harness": {
                "path": base.relative(SCRIPT_PATH, repo_root),
                "sha256": base.sha256_file(SCRIPT_PATH),
            },
            "seed": {
                "path": base.relative(DEFAULT_SEED, repo_root),
                "sha256": base.sha256_file(DEFAULT_SEED),
            },
        },
        "candidate_definition": {
            "name": "point_in_time_wu_observable_tail_recovery_v2",
            "kind": seed["candidates"][NEW_CANDIDATE]["kind"],
            "payload_rule": seed["candidates"][NEW_CANDIDATE]["definition"],
            "same_timestamp_rule": seed["candidates"][NEW_CANDIDATE][
                "same_timestamp_rule"
            ],
            "snapshot_order": (
                "captured_at_utc ascending within each market-day, original replay file position "
                "as the stable tie-break"
            ),
            "point_in_time_rule": (
                "At snapshot t, use the current replay payload and only replay snapshots with "
                "captured_at_utc strictly earlier than t. Emit a nonblank current-snapshot receipt, "
                "assert every recovered-row source is strictly earlier, and consume nothing after t."
            ),
            "row_identity": "target-date-local minute_of_day",
            "cutoff_rule": seed["cutoff_rule"],
            "fallback_rule": seed["fallback_rule"],
            "replay_change_scope": prior_preregistration["candidate_definition"][
                "replay_change_scope"
            ],
            "selection_reason": [
                (
                    f"repairs {candidate_events['repaired']} of 906 B decreases and "
                    f"{candidate_events['decision_window_repaired']} of "
                    f"{candidate_events['decision_window_events']} decision-window events"
                ),
                (
                    f"creates {candidate_safety['newly_exceeds_settled_high']} new above-settlement "
                    f"rows on all {candidate_safety['available']} B feature snapshots with replay"
                ),
                (
                    f"moves {candidate_train_serve['closer']} comparable B snapshots closer to "
                    f"training, {candidate_train_serve['farther']} farther, and changes paired "
                    f"mismatches {candidate_train_serve['baseline_mismatch']} to "
                    f"{candidate_train_serve['candidate_mismatch']}"
                ),
                (
                    "the San Francisco frozen M1 label is invalid against raw timestamp identity: "
                    f"removed {known_traces['san_francisco_revision']['raw_row_identity_diff']['removed_minutes']} "
                    f"and added {known_traces['san_francisco_revision']['raw_row_identity_diff']['added_minutes']}"
                ),
            ],
            "selection_used_no_forecast_outcome": True,
            "selection_used_no_market_price": True,
            "selection_used_only_input_integrity_floor_safety_and_train_serve_parity": True,
        },
        "pre_execution_gates": gate_result["gates"],
        "outcome_protocol_if_and_only_if_operator_allocates_alpha_and_authorizes_scoring": copy.deepcopy(
            prior_preregistration[
                "outcome_protocol_if_and_only_if_a_new_safe_candidate_clears_the_gates"
            ]
        ),
        "alpha": copy.deepcopy(prior_preregistration["alpha"]),
        "forbidden_actions": [
            "Do not compute Brier, CRPS, log loss, market deltas, power, or any forecast outcome until the operator allocates alpha and authorizes scoring.",
            "Do not fit, promote, activate, release, or serve a candidate from this artifact.",
            "Do not weaken, clamp with settlement, or tune the floor using realized outcomes.",
            "Do not add a C endpoint or read C forecast outcomes or market prices.",
            "Do not edit this frozen file in place; any change requires a new versioned pre-registration.",
        ],
    }
    payload["alpha"]["allocated_now"] = False
    payload["alpha"]["spent_now"] = False
    payload["alpha"]["ledger_decision_id"] = None
    payload["alpha"]["ledger_state_after_this_mission"] = (
        "7 of 20 spent, 13 available; decision 10 CLOSED UNUSED and not reassigned"
    )
    payload["alpha"]["allocation_requirement"] = (
        "The operator must explicitly allocate the campaign decision before the first outcome look. "
        "This safety mission allocates and spends nothing."
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"path": str(path), "sha256": base.sha256_file(path)}


def analyze(
    repo_root: Path,
    evidence_root: Path,
    seed_path: Path,
    output_path: Path,
    preregistration_path: Path,
) -> dict[str, Any]:
    seed = load_seed(seed_path)
    prior_seed, prior_preregistration, source_events, frozen_receipts = load_prior_protocol(
        repo_root, seed
    )
    base_seed = base.load_seed(repo_root / prior_seed["source_population"]["base_seed_relative_path"])
    roster, roster_receipt = base.load_roster(repo_root, base_seed)
    folders = base.discover_folders(evidence_root, roster, base_seed["markets"])
    rows_by_day, events, _keys_by_day, feature_receipts, population = base.load_features(
        evidence_root, roster, folders, base_seed
    )
    for stratum in ("B", "C"):
        for field in ("date_clusters", "market_clusters", "market_days", "decrease_events"):
            base.require(
                population[stratum][field] == seed["expected_population"][stratum][field],
                f"{stratum} {field} population drifted",
            )
    envelope_states, observable_states, raw_traces, replay_receipts, replay_support = (
        scan_all_replay_snapshots(
            evidence_root,
            folders,
            rows_by_capture_key(rows_by_day),
            seed["cutoff_hours"],
            seed["known_traces"],
        )
    )
    market_units = {
        market_id: str(spec["unit"]) for market_id, spec in base_seed["markets"].items()
    }
    positive_controls = assert_positive_controls(
        seed,
        prior_seed,
        events,
        envelope_states,
        source_events,
        market_units,
        rows_by_day,
        roster,
        replay_support,
    )
    event_mechanisms = event_mechanism_lookup(source_events)
    event_rows, event_receipts = build_event_rows(
        events,
        envelope_states,
        observable_states,
        source_events,
        event_mechanisms,
        prior_seed,
        market_units,
    )
    event_summary = summarize_events(event_rows)
    posthoc_label_control = posthoc_m5_m3_filter_control(event_rows, seed)
    safety = all_snapshot_safety(
        rows_by_day,
        envelope_states,
        observable_states,
        roster,
        event_mechanisms,
    )
    archive_highs, archive_receipts, archive_support = base.load_archive(
        evidence_root, roster, base_seed
    )
    baseline_train_serve = base.train_serve_summary(rows_by_day, archive_highs, roster)
    expected_controls = seed["positive_controls_09_72a"]
    base.require(
        baseline_train_serve["B"]["comparable_snapshot_rows"]
        == expected_controls["baseline_B_comparable"],
        "B baseline comparable population drifted",
    )
    baseline_mismatch = (
        baseline_train_serve["B"]["training_higher_snapshot_rows"]
        + baseline_train_serve["B"]["training_lower_snapshot_rows"]
    )
    base.require(
        baseline_mismatch == expected_controls["baseline_B_mismatch"],
        "B 9.74% baseline mismatch drifted",
    )
    train_serve = train_serve_comparison(
        rows_by_day,
        envelope_states,
        observable_states,
        archive_highs,
        roster,
        event_mechanisms,
    )
    known_traces = build_known_traces(seed, raw_traces, event_rows)
    gate_result = evaluate_gates(
        seed, event_summary, safety, train_serve, replay_support, event_receipts
    )
    base.require(
        not seed["candidates"][LABEL_COMPARATOR]["selection_eligible"],
        "label comparator unexpectedly became selectable",
    )
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
    snapshot_receipt_core = [
        {
            "key": list(key),
            "max_captured_at_utc_used": state.max_captured_at_utc_used,
            "max_prior_captured_at_utc_used": state.max_prior_captured_at_utc,
            "max_recovered_source_captured_at_utc": state.max_recovered_source_captured_at_utc,
            "recovered_minutes": list(state.recovered_minutes),
        }
        for key, state in sorted(observable_states.items())
    ]
    manifest = {
        "artifact": "safe_observation_recovery_v2",
        "built_for": "-09-73a floor-safe recovery rule or precise null",
        "source_base_commit": seed["source_base_commit"],
        "seed": {
            "relative_path": base.relative(seed_path, repo_root),
            "bytes": seed_path.stat().st_size,
            "sha256": base.sha256_file(seed_path),
        },
        "population": population,
        "evidence_root": {
            "used": "data/snapshots under the complete workstation evidence root",
            "B_dates": population["B"]["date_clusters"],
            "partial_root_with_7_B_dates_used": False,
        },
        "positive_controls_09_72a": positive_controls,
        "candidate_definitions": seed["candidates"],
        "event_results": event_summary,
        "posthoc_m5_m3_filter_control": posthoc_label_control,
        "all_feature_snapshot_floor_safety": safety,
        "train_serve": {
            "baseline_reproduction": baseline_train_serve,
            "candidate_comparison_on_paired_B_snapshots": train_serve,
        },
        "raw_payload_traces": known_traces,
        "label_audit": {
            "san_francisco_M1_label_valid": known_traces["san_francisco_revision"][
                "frozen_label_valid_against_raw_timestamp_identity"
            ],
            "conclusion": (
                "The San Francisco M1 label is wrong: stale vendor summary.latest plus equal row "
                "count and positional zipping concealed a 13:00 removal and 14:00 addition. "
                "M5+M3 is retained only as an ineligible post-hoc comparator."
            ),
        },
        "selection": gate_result,
        "support": {
            "replay": replay_support,
            "archive": archive_support,
            "event_receipts": event_receipts,
            "input_files": len(receipt_core),
            "input_bytes": sum(int(item["bytes"]) for item in receipt_core),
            "input_receipts_sha256": base.canonical_sha256(receipt_core),
            "snapshot_receipts": len(snapshot_receipt_core),
            "snapshot_receipts_sha256": base.canonical_sha256(snapshot_receipt_core),
        },
        "method": {
            "interval_treatment": (
                "exact finite-population input-integrity census; no sampling interval, bootstrap, "
                "power calculation, alpha look, forecast outcome, or market comparison"
            ),
            "B_and_C_reported_separately": True,
            "pooled_across_2026_07_31": False,
            "native_units_preserved": True,
            "current_snapshot_included": True,
            "future_snapshots_consumed": 0,
            "all_day_snapshots_used": True,
            "C_read_scope": (
                "input-integrity positive controls and floor receipts only; no candidate endpoint, "
                "forecast score, probability, market price, accept rule, or selection"
            ),
        },
        "campaign": seed["campaign"],
        "contains_fitted_quantities": False,
        "contains_outcome_scores": False,
        "contains_market_prices": False,
        "contains_C_endpoint": False,
        "explicitly_not_done": [
            "no alpha allocation or spend, Brier, CRPS, log loss, probability outcome, market comparison, C endpoint, or ledger decision",
            "no high_so_far, cutoff_hour, producer, floor, collection, replay, scoring, settlement, model, or serving change",
            "no provider or exchange call, production data write, registration, restart, promotion, activation, release, trade, merge, or PR",
        ],
    }
    artifacts = write_outputs(output_path, event_rows, manifest)
    preregistration = None
    if gate_result["all_pass"]:
        preregistration = write_preregistration(
            preregistration_path,
            repo_root,
            seed,
            prior_preregistration,
            artifacts,
            gate_result,
            event_summary,
            safety,
            train_serve,
            known_traces,
        )
    return {
        "status": "PASS",
        "verdict": (
            "OBSERVABLE_RECOVERY_FLOOR_SAFE_PREREG_FROZEN_ALPHA_UNALLOCATED"
            if gate_result["all_pass"]
            else "NO_FLOOR_SAFE_RECOVERY_RULE_THREAD_CLOSED"
        ),
        "artifacts": artifacts,
        "preregistration": preregistration,
        "selection": gate_result,
        "event_results_B": event_summary["B"],
        "posthoc_m5_m3_filter_control": posthoc_label_control,
        "all_snapshot_safety_B": safety["B"],
        "train_serve_B": train_serve,
        "raw_label_audit": {
            "san_francisco_M1_label_valid": known_traces["san_francisco_revision"][
                "frozen_label_valid_against_raw_timestamp_identity"
            ]
        },
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    result.add_argument("--evidence-root", type=Path, default=DEFAULT_REPO_ROOT)
    result.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result.add_argument(
        "--preregistration", type=Path, default=DEFAULT_PREREGISTRATION
    )
    return result


def main() -> int:
    args = parser().parse_args()
    result = analyze(
        args.repo_root.resolve(),
        args.evidence_root.resolve(),
        args.seed.resolve(),
        args.output.resolve(),
        args.preregistration.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
