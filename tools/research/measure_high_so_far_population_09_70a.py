"""Measure the -09-71a cutoff direction in the -09-70a population.

The harness is a deterministic census over the tracked -09-67a B/C market-day
roster.  It reads captured ``features_long.csv`` and ``replay_inputs.jsonl``
evidence, classifies every adjacent decrease using the frozen seed, compares
three already-captured candidate fields, and measures current-archive
train/serve skew.  It performs no fitting, provider call, serving change, or
write below ``data/``.

Run from a checkout with the bundled Codex Python 3.12 runtime.  A worktree
without ignored evidence should point ``--evidence-root`` at the main
workstation checkout.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_SEED = SCRIPT_PATH.with_name("measure_high_so_far_population_09_70a_seed.json")
DEFAULT_OUTPUT = (
    DEFAULT_REPO_ROOT
    / "docs"
    / "roadmap"
    / "high-so-far-cutoff-direction-2026-09-71a.csv"
)
OUTPUT_COLUMNS = (
    "stratum",
    "market_id",
    "target_date",
    "snapshot_id",
    "local_time",
    "minute_of_day",
    "high_so_far",
    "prev_running_max",
    "drop_degrees",
    "wu_history_rows",
    "wu_history_max_c",
    "wu_current_max_since_7am_c",
    "current_temp",
    "rows_changed",
    "rows_dropped",
    "latest_datetime_changed",
    "cutoff_hour_changed",
    "previous_cutoff_hour",
    "cutoff_hour",
    "cutoff_delta",
    "capture_minute",
    "previous_capture_minute",
    "rows_lost_within_window",
    "source_kind",
    "mechanism",
    "settled_high",
)
SNAPSHOT_KEY_FIELDS = ("snapshot_id", "captured_at_utc")
FLOAT_TOLERANCE = 1e-9


class IntegrityFailure(RuntimeError):
    """A frozen population, input, or output contract failed."""


@dataclass(frozen=True)
class MarketDay:
    stratum: str
    market_id: str
    target_date: str
    settled_high: float
    unit: str


@dataclass(frozen=True)
class ReplayPayload:
    wu_history: dict[str, Any]
    wu_current: dict[str, Any]
    station: dict[str, Any]
    metar: dict[str, Any]
    eccc_swob: dict[str, Any]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrityFailure(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def maybe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def compact_number(value: float | int | None) -> str:
    if value is None:
        return ""
    number = float(value)
    if abs(number - round(number)) <= 1e-12:
        return str(int(round(number)))
    return format(number, ".15g")


def close(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and abs(left - right) <= FLOAT_TOLERANCE


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_seed(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        seed = json.load(handle)
    require(seed.get("schema_version") == "high_so_far_population_seed_v2", "seed schema drifted")
    return seed


def load_roster(repo_root: Path, seed: dict[str, Any]) -> tuple[dict[tuple[str, str], MarketDay], dict[str, Any]]:
    spec = seed["population"]
    path = repo_root / spec["roster_relative_path"]
    require(path.is_file(), f"roster missing: {path}")
    digest = sha256_file(path)
    require(digest == spec["roster_sha256"], f"roster hash drifted: {digest}")
    roster: dict[tuple[str, str], MarketDay] = {}
    for row in read_csv(path):
        market_day = MarketDay(
            stratum=row["stratum"],
            market_id=row["market_id"],
            target_date=row["target_date"],
            settled_high=float(row["settlement_high"]),
            unit=seed["markets"][row["market_id"]]["unit"],
        )
        key = (market_day.market_id, market_day.target_date)
        require(key not in roster, f"duplicate roster market-day: {key}")
        roster[key] = market_day
    require(len(roster) == 524, f"roster market-day count drifted: {len(roster)}")
    return roster, {
        "kind": "settlement_roster",
        "path": spec["roster_relative_path"],
        "bytes": path.stat().st_size,
        "sha256": digest,
    }


def first_csv_row(path: Path) -> dict[str, str] | None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return next(csv.DictReader(handle), None)


def discover_folders(
    evidence_root: Path,
    roster: dict[tuple[str, str], MarketDay],
    markets: dict[str, Any],
) -> dict[tuple[str, str], Path]:
    snapshot_root = evidence_root / "data" / "snapshots"
    require(snapshot_root.is_dir(), f"snapshot root missing: {snapshot_root}")
    discovered: dict[tuple[str, str], Path] = {}
    for folder in sorted(snapshot_root.iterdir(), key=lambda path: path.name):
        features_path = folder / "features_long.csv"
        if not features_path.is_file():
            continue
        first = first_csv_row(features_path)
        if not first:
            continue
        slug = str(first.get("event_slug") or "")
        matched = [
            market_id
            for market_id, market in markets.items()
            if slug.startswith(market["slug_prefix"])
        ]
        if len(matched) != 1:
            continue
        key = (matched[0], str(first.get("target_date") or ""))
        if key not in roster:
            continue
        require(key not in discovered, f"multiple snapshot folders match {key}")
        discovered[key] = folder
    missing = sorted(set(roster) - set(discovered))
    require(not missing, f"roster market-days missing snapshot folders: {missing[:10]}")
    require(len(discovered) == len(roster), "snapshot-folder census drifted")
    return discovered


def capture_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["snapshot_id"]), str(row["captured_at_utc"])


def local_clock(row: dict[str, Any]) -> tuple[str, int]:
    value = datetime.fromisoformat(str(row["captured_at_local"]))
    local_time = value.timetz().replace(tzinfo=None).isoformat(timespec="microseconds")
    return local_time, value.hour * 60 + value.minute


def load_features(
    evidence_root: Path,
    roster: dict[tuple[str, str], MarketDay],
    folders: dict[tuple[str, str], Path],
    seed: dict[str, Any],
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    list[dict[str, Any]],
    dict[tuple[str, str], set[tuple[str, str]]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]] = {}
    events: list[dict[str, Any]] = []
    keys_by_day: dict[tuple[str, str], set[tuple[str, str]]] = {}
    receipts: list[dict[str, Any]] = []
    support = {
        stratum: {
            "date_clusters": set(),
            "market_clusters": set(),
            "market_days": 0,
            "raw_feature_rows": 0,
            "snapshots": 0,
            "blank_high_or_current": 0,
            "below_running_max_of_current_temp": 0,
            "market_days_with_decrease": 0,
            "decrease_events": 0,
        }
        for stratum in ("B", "C")
    }
    duplicate_snapshot_ids = Counter()
    duplicate_capture_key_rows = Counter()
    for key in sorted(folders):
        market_day = roster[key]
        path = folders[key] / "features_long.csv"
        raw_rows = read_csv(path)
        scoped = []
        for file_index, row in enumerate(raw_rows):
            require(row.get("target_date") == market_day.target_date, f"target date drift in {path}")
            high = maybe_float(row.get("high_so_far"))
            current = maybe_float(row.get("current_temp"))
            if high is None or current is None:
                continue
            enriched: dict[str, Any] = dict(row)
            enriched.update(
                {
                    "stratum": market_day.stratum,
                    "market_id": market_day.market_id,
                    "settled_high": market_day.settled_high,
                    "high": high,
                    "current": current,
                    "cutoff": int(float(row["cutoff_hour"])),
                    "file_index": file_index,
                    "folder": folders[key],
                }
            )
            scoped.append(enriched)
        scoped.sort(key=lambda row: (row["captured_at_utc"], row["file_index"]))
        rows_by_day[key] = scoped
        keys_by_day[key] = {capture_key(row) for row in scoped}
        id_counts = Counter(row["snapshot_id"] for row in scoped)
        capture_key_counts = Counter(capture_key(row) for row in scoped)
        duplicate_snapshot_ids[market_day.stratum] += sum(count - 1 for count in id_counts.values())
        duplicate_capture_key_rows[market_day.stratum] += sum(
            count - 1 for count in capture_key_counts.values()
        )

        state = support[market_day.stratum]
        state["date_clusters"].add(market_day.target_date)
        state["market_clusters"].add(market_day.market_id)
        state["market_days"] += 1
        state["raw_feature_rows"] += len(raw_rows)
        state["snapshots"] += len(scoped)
        state["blank_high_or_current"] += len(raw_rows) - len(scoped)
        running_current: float | None = None
        running_high: float | None = None
        previous: dict[str, Any] | None = None
        day_decreased = False
        for row in scoped:
            high = row["high"]
            current = row["current"]
            if running_current is not None and high < running_current - FLOAT_TOLERANCE:
                state["below_running_max_of_current_temp"] += 1
            running_current = current if running_current is None else max(running_current, current)
            if previous is not None and high < previous["high"] - FLOAT_TOLERANCE:
                require(running_high is not None, "running high absent at decrease")
                event = {
                    "stratum": market_day.stratum,
                    "market_id": market_day.market_id,
                    "target_date": market_day.target_date,
                    "settled_high": market_day.settled_high,
                    "previous": previous,
                    "current_row": row,
                    "prev_running_max": running_high,
                }
                events.append(event)
                state["decrease_events"] += 1
                day_decreased = True
            running_high = high if running_high is None else max(running_high, high)
            previous = row
        if day_decreased:
            state["market_days_with_decrease"] += 1
        receipts.append(
            {
                "kind": "features_long",
                "path": relative(path, evidence_root),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    observed: dict[str, Any] = {}
    for stratum in ("B", "C"):
        state = support[stratum]
        state["date_clusters"] = len(state["date_clusters"])
        state["market_clusters"] = len(state["market_clusters"])
        state["duplicate_snapshot_id_rows"] = duplicate_snapshot_ids[stratum]
        state["duplicate_capture_key_rows"] = duplicate_capture_key_rows[stratum]
        observed[stratum] = state
        expected = seed["population"]["expected"][stratum]
        for field, value in expected.items():
            require(state[field] == value, f"{stratum} {field} drifted: {state[field]} != {value}")
    return rows_by_day, events, keys_by_day, receipts, observed


def _json_value_span(raw: bytes, start: int) -> tuple[int, int]:
    size = len(raw)
    while start < size and raw[start] in b" \t\r\n":
        start += 1
    require(start < size, "truncated JSON value")
    opening = raw[start]
    if opening == ord('"'):
        index = start + 1
        escaped = False
        while index < size:
            value = raw[index]
            if escaped:
                escaped = False
            elif value == ord('\\'):
                escaped = True
            elif value == ord('"'):
                return start, index + 1
            index += 1
        raise IntegrityFailure("unterminated JSON string")
    if opening in (ord('{'), ord('[')):
        closing = ord('}') if opening == ord('{') else ord(']')
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, size):
            value = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif value == ord('\\'):
                    escaped = True
                elif value == ord('"'):
                    in_string = False
                continue
            if value == ord('"'):
                in_string = True
            elif value == opening:
                depth += 1
            elif value == closing:
                depth -= 1
                if depth == 0:
                    return start, index + 1
        raise IntegrityFailure("unterminated JSON object/array")
    index = start
    while index < size and raw[index] not in b",}\r\n":
        index += 1
    return start, index


def json_value_by_key(raw: bytes, key: str, start: int = 0) -> Any:
    token = ('"' + key + '"').encode("utf-8")
    position = raw.find(token, start)
    if position < 0:
        return None
    colon = raw.find(b":", position + len(token))
    require(colon >= 0, f"missing colon after JSON key {key}")
    value_start, value_end = _json_value_span(raw, colon + 1)
    return json.loads(raw[value_start:value_end])


def source_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    return data if isinstance(data, dict) else value


def first_number(mapping: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = maybe_float(mapping.get(key))
        if value is not None:
            return value
    return None


def replay_payload(raw: bytes, sources_start: int, *, include_sources: bool) -> ReplayPayload:
    history = source_data(json_value_by_key(raw, "wu_history", sources_start))
    current = source_data(json_value_by_key(raw, "wu_current", sources_start))
    if not include_sources:
        return ReplayPayload(history, current, {}, {}, {})
    station = source_data(json_value_by_key(raw, "station_observations", sources_start))
    metar = source_data(json_value_by_key(raw, "metar", sources_start))
    eccc = source_data(json_value_by_key(raw, "eccc_swob", sources_start))
    return ReplayPayload(history, current, station, metar, eccc)


def replay_candidates(payload: ReplayPayload) -> dict[str, float | None]:
    return {
        "wu_history_max_c": first_number(
            payload.wu_history,
            ("max_native", "max_c", "max_temp_native", "max_temp_c"),
        ),
        "wu_current_max_since_7am_c": first_number(
            payload.wu_current,
            ("max_since_7am_native", "max_since_7am_c"),
        ),
    }


def load_replay_payloads(
    evidence_root: Path,
    folders: dict[tuple[str, str], Path],
    keys_by_day: dict[tuple[str, str], set[tuple[str, str]]],
    events: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str, str, str], dict[str, float | None]],
    dict[tuple[str, str, str, str], ReplayPayload],
    list[dict[str, Any]],
    dict[str, Any],
]:
    event_keys_by_day: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for event in events:
        day = (event["market_id"], event["target_date"])
        event_keys_by_day[day].add(capture_key(event["previous"]))
        event_keys_by_day[day].add(capture_key(event["current_row"]))
    candidates: dict[tuple[str, str, str, str], dict[str, float | None]] = {}
    event_payloads: dict[tuple[str, str, str, str], ReplayPayload] = {}
    receipts: list[dict[str, Any]] = []
    replay_rows_scanned = 0
    replay_bytes_scanned = 0
    duplicate_replay_capture_key_rows = 0
    feature_rows_missing_replay = 0
    for day in sorted(folders):
        path = folders[day] / "replay_inputs.jsonl"
        require(path.is_file(), f"replay input missing: {path}")
        expected = keys_by_day[day]
        event_expected = event_keys_by_day[day]
        digest = hashlib.sha256()
        matched: set[tuple[str, str]] = set()
        with path.open("rb") as handle:
            for raw in handle:
                digest.update(raw)
                replay_rows_scanned += 1
                replay_bytes_scanned += len(raw)
                snapshot_id = json_value_by_key(raw, "snapshot_id")
                if not isinstance(snapshot_id, str):
                    continue
                if not any(snapshot_id == key[0] for key in expected):
                    continue
                captured_at_utc = json_value_by_key(raw, "captured_at_utc")
                if not isinstance(captured_at_utc, str):
                    continue
                short_key = (snapshot_id, captured_at_utc)
                if short_key not in expected:
                    continue
                if short_key in matched:
                    duplicate_replay_capture_key_rows += 1
                    continue
                matched.add(short_key)
                sources_start = raw.find(b'"sources"')
                require(sources_start >= 0, f"replay sources missing for {short_key}")
                payload = replay_payload(raw, sources_start, include_sources=short_key in event_expected)
                full_key = (day[0], day[1], *short_key)
                candidates[full_key] = replay_candidates(payload)
                if short_key in event_expected:
                    event_payloads[full_key] = payload
        missing = sorted(expected - matched)
        feature_rows_missing_replay += len(missing)
        missing_event_rows = sorted(event_expected - matched)
        require(
            not missing_event_rows,
            f"decrease-event rows lack replay inputs in {path}: {missing_event_rows[:5]}",
        )
        receipts.append(
            {
                "kind": "replay_inputs",
                "path": relative(path, evidence_root),
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        )
    expected_event_payloads = len(
        {
            (event["market_id"], event["target_date"], *capture_key(row))
            for event in events
            for row in (event["previous"], event["current_row"])
        }
    )
    require(len(event_payloads) == expected_event_payloads, "event replay payload coverage drifted")
    return candidates, event_payloads, receipts, {
        "replay_rows_scanned": replay_rows_scanned,
        "replay_bytes_scanned": replay_bytes_scanned,
        "candidate_snapshot_rows": len(candidates),
        "event_payload_rows": len(event_payloads),
        "duplicate_replay_capture_key_rows": duplicate_replay_capture_key_rows,
        "feature_rows_missing_replay": feature_rows_missing_replay,
    }


def row_temperature(row: dict[str, Any]) -> float | None:
    return first_number(row, ("temp_native", "temp_c", "air_temp_native", "air_temp_c"))


def minute_of_day(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[1]
    text = text[:5]
    try:
        hour, minute = text.split(":")
        return int(hour) * 60 + int(minute)
    except (ValueError, TypeError):
        return None


def history_rows(payload: ReplayPayload) -> list[dict[str, Any]]:
    rows = payload.wu_history.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


def history_latest_datetime(payload: ReplayPayload) -> str:
    latest = payload.wu_history.get("latest") or {}
    if not isinstance(latest, dict):
        return ""
    return str(
        latest.get("datetime")
        or latest.get("valid_time_local")
        or latest.get("local_time")
        or latest.get("time")
        or ""
    )


def latest_history_minute(payload: ReplayPayload) -> int | None:
    minutes = [
        minute_of_day(row.get("time") or row.get("datetime"))
        for row in history_rows(payload)
    ]
    finite = [minute for minute in minutes if minute is not None]
    return max(finite) if finite else None


def row_time_identity(row: dict[str, Any]) -> str:
    return str(
        row.get("datetime")
        or row.get("valid_time_local")
        or row.get("local_time")
        or row.get("time")
        or ""
    )


def rows_lost_within_window(
    previous_payload: ReplayPayload,
    current_payload: ReplayPayload,
    previous_cutoff: int,
    current_cutoff: int,
) -> int:
    """Count rows in the previous served window absent from the current one."""
    previous_times = Counter(
        row_time_identity(row)
        for row in history_rows(previous_payload)
        if row_time_identity(row)
        and minute_of_day(row.get("time") or row.get("datetime")) is not None
        and minute_of_day(row.get("time") or row.get("datetime")) <= previous_cutoff * 60
    )
    current_times = Counter(
        row_time_identity(row)
        for row in history_rows(current_payload)
        if row_time_identity(row)
        and minute_of_day(row.get("time") or row.get("datetime")) is not None
        and minute_of_day(row.get("time") or row.get("datetime")) <= current_cutoff * 60
    )
    return sum((previous_times - current_times).values())


def retained_rows_excluded_by_narrowing(
    previous_payload: ReplayPayload,
    current_payload: ReplayPayload,
    previous_cutoff: int,
    current_cutoff: int,
) -> int:
    """Count same-timestamp raw rows excluded solely by a narrowing cutoff.

    A row must exist at the same timestamp in both captured series, have been
    admitted by the previous cutoff, and be excluded by the current cutoff.
    This isolates the window effect from raw-series row disappearance.
    """
    if current_cutoff >= previous_cutoff:
        return 0
    previous_times = Counter(
        row_time_identity(row)
        for row in history_rows(previous_payload)
        if row_time_identity(row)
    )
    lost = 0
    for row in history_rows(current_payload):
        identity = row_time_identity(row)
        minute = minute_of_day(row.get("time") or row.get("datetime"))
        if not identity or minute is None or previous_times[identity] <= 0:
            continue
        previous_times[identity] -= 1
        if current_cutoff * 60 < minute <= previous_cutoff * 60:
            lost += 1
    return lost


def history_window_max(payload: ReplayPayload, cutoff: int) -> float | None:
    values = [
        row_temperature(row)
        for row in history_rows(payload)
        if minute_of_day(row.get("time") or row.get("datetime")) is not None
        and minute_of_day(row.get("time") or row.get("datetime")) <= cutoff * 60
    ]
    finite = [value for value in values if value is not None]
    return max(finite) if finite else None


def source_kind(payload: ReplayPayload, row: dict[str, Any]) -> str:
    high = row["high"]
    current_temp = row["current"]
    cutoff = row["cutoff"]
    rows = history_rows(payload)
    row_values = [
        row_temperature(item)
        for item in rows
        if minute_of_day(item.get("time") or item.get("datetime")) is not None
        and minute_of_day(item.get("time") or item.get("datetime")) <= cutoff * 60
    ]
    finite_rows = [value for value in row_values if value is not None]
    history_max = first_number(payload.wu_history, ("max_native", "max_c"))
    if finite_rows and close(max(finite_rows), high):
        return "wu"
    if close(history_max, high):
        return "wu"
    wu_values = [
        first_number(payload.wu_current, ("temp_native", "temp_c")),
        first_number(payload.wu_current, ("max_since_7am_native", "max_since_7am_c")),
    ]
    if any(close(value, high) or close(value, current_temp) for value in wu_values):
        return "wu"
    station_source = str(
        payload.station.get("station_observation_source")
        or payload.station.get("source")
        or ""
    ).lower()
    if "eccc" in station_source:
        return "eccc"
    if station_source:
        return "station"
    eccc_values = [
        row_temperature(payload.eccc_swob.get("latest") or {}),
        first_number(payload.eccc_swob, ("max_since_7am_native", "max_since_7am_c")),
    ]
    if any(close(value, high) or close(value, current_temp) for value in eccc_values):
        return "eccc"
    metar_values = [
        row_temperature(payload.metar.get("latest") or payload.metar),
        first_number(payload.metar, ("max_since_7am_native", "max_since_7am_c")),
    ]
    if any(close(value, high) or close(value, current_temp) for value in metar_values):
        return "station"
    return "other"


def event_discriminants(
    previous_payload: ReplayPayload,
    current_payload: ReplayPayload,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    previous_rows = history_rows(previous_payload)
    current_rows = history_rows(current_payload)
    paired_temperatures = zip(previous_rows, current_rows)
    rows_changed = sum(
        1
        for previous_row, current_row in paired_temperatures
        if row_temperature(previous_row) is not None
        and row_temperature(current_row) is not None
        and not close(row_temperature(previous_row), row_temperature(current_row))
    )
    rows_dropped = max(0, len(previous_rows) - len(current_rows))
    latest_changed = history_latest_datetime(previous_payload) != history_latest_datetime(current_payload)
    cutoff_changed = previous["cutoff"] != current["cutoff"]
    cutoff_delta = current["cutoff"] - previous["cutoff"]
    previous_latest_minute = latest_history_minute(previous_payload)
    current_latest_minute = latest_history_minute(current_payload)
    previous_window_max = history_window_max(previous_payload, previous["cutoff"])
    current_at_previous_cutoff_max = history_window_max(current_payload, previous["cutoff"])
    current_window_max = history_window_max(current_payload, current["cutoff"])
    previous_source = source_kind(previous_payload, previous)
    current_source = source_kind(current_payload, current)
    history_max = first_number(current_payload.wu_history, ("max_native", "max_c"))
    empty_history = (
        (not current_rows or history_max is None)
        and close(current["high"], current["current"])
    )
    restatement = (
        bool(previous_rows)
        and bool(current_rows)
        and len(previous_rows) == len(current_rows)
        and not latest_changed
        and rows_changed > 0
    )
    if empty_history:
        mechanism = "M2_empty_history"
    elif previous_source != current_source:
        mechanism = "M4_source_switch"
    elif restatement:
        mechanism = "M1_restatement"
    elif cutoff_changed:
        mechanism = "M5_cutoff_change"
    elif rows_dropped > 0:
        mechanism = "M3_rows_dropped"
    else:
        mechanism = "M6_unexplained"
    return {
        "previous_rows": len(previous_rows),
        "current_rows": len(current_rows),
        "rows_changed": rows_changed,
        "rows_dropped": rows_dropped,
        "latest_datetime_changed": latest_changed,
        "cutoff_hour_changed": cutoff_changed,
        "cutoff_delta": cutoff_delta,
        "previous_latest_observation_minute": previous_latest_minute,
        "latest_observation_minute": current_latest_minute,
        "latest_observation_minute_delta": (
            current_latest_minute - previous_latest_minute
            if previous_latest_minute is not None and current_latest_minute is not None
            else None
        ),
        "rows_lost_within_window": rows_lost_within_window(
            previous_payload,
            current_payload,
            previous["cutoff"],
            current["cutoff"],
        ),
        "retained_rows_excluded_by_narrowing": retained_rows_excluded_by_narrowing(
            previous_payload,
            current_payload,
            previous["cutoff"],
            current["cutoff"],
        ),
        "previous_window_max": previous_window_max,
        "current_at_previous_cutoff_max": current_at_previous_cutoff_max,
        "current_window_max": current_window_max,
        "raw_series_alone_lowered_max": (
            current_at_previous_cutoff_max < previous_window_max - FLOAT_TOLERANCE
            if previous_window_max is not None and current_at_previous_cutoff_max is not None
            else None
        ),
        "cutoff_alone_lowered_current_payload_max": (
            current_window_max < current_at_previous_cutoff_max - FLOAT_TOLERANCE
            if current_at_previous_cutoff_max is not None and current_window_max is not None
            else None
        ),
        "previous_source_kind": previous_source,
        "source_kind": current_source,
        "empty_history_fallback": empty_history,
        "source_kind_changed": previous_source != current_source,
        "restatement_pattern": restatement,
        "mechanism": mechanism,
    }


def window_label(minute: int, seed: dict[str, Any]) -> str:
    windows = seed["time_windows_local"]
    if windows["pre_dawn"][0] <= minute < windows["pre_dawn"][1]:
        return "pre_dawn"
    if windows["peak_heating_window"][0] <= minute < windows["peak_heating_window"][1]:
        return "peak_heating_window"
    if windows["settlement_window"][0] <= minute < windows["settlement_window"][1]:
        return "settlement_window"
    return "other"


def classify_events(
    events: list[dict[str, Any]],
    event_payloads: dict[tuple[str, str, str, str], ReplayPayload],
    seed: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    output: list[dict[str, str]] = []
    mechanisms = {stratum: Counter() for stratum in ("B", "C")}
    windows = {stratum: Counter() for stratum in ("B", "C")}
    hours = {stratum: Counter() for stratum in ("B", "C")}
    representatives: dict[str, Any] = {}
    discriminant_totals = {stratum: Counter() for stratum in ("B", "C")}
    cutoff_delta_totals = {stratum: Counter() for stratum in ("B", "C")}
    m5_cutoff_delta_totals = {stratum: Counter() for stratum in ("B", "C")}
    m5_effect_paths = {stratum: Counter() for stratum in ("B", "C")}
    cutoff_relationships = {stratum: Counter() for stratum in ("B", "C")}
    widened_mechanisms = {stratum: Counter() for stratum in ("B", "C")}
    m6_fingerprints = {stratum: Counter() for stratum in ("B", "C")}
    drop_magnitudes: dict[str, dict[str, dict[str, list[float]]]] = {
        stratum: defaultdict(lambda: {"adjacent": [], "running_max_deficit": []})
        for stratum in ("B", "C")
    }
    for event in events:
        previous = event["previous"]
        current = event["current_row"]
        previous_key = (event["market_id"], event["target_date"], *capture_key(previous))
        current_key = (event["market_id"], event["target_date"], *capture_key(current))
        discriminants = event_discriminants(
            event_payloads[previous_key],
            event_payloads[current_key],
            previous,
            current,
        )
        current_candidates = replay_candidates(event_payloads[current_key])
        previous_candidates = replay_candidates(event_payloads[previous_key])
        previous_local_time, previous_capture_minute = local_clock(previous)
        local_time, capture_minute = local_clock(current)
        row = {
            "stratum": event["stratum"],
            "market_id": event["market_id"],
            "target_date": event["target_date"],
            "snapshot_id": current["snapshot_id"],
            "local_time": local_time,
            "minute_of_day": str(capture_minute),
            "high_so_far": compact_number(current["high"]),
            "prev_running_max": compact_number(event["prev_running_max"]),
            "drop_degrees": compact_number(event["prev_running_max"] - current["high"]),
            "wu_history_rows": str(discriminants["current_rows"]),
            "wu_history_max_c": compact_number(current_candidates["wu_history_max_c"]),
            "wu_current_max_since_7am_c": compact_number(
                current_candidates["wu_current_max_since_7am_c"]
            ),
            "current_temp": compact_number(current["current"]),
            "rows_changed": str(discriminants["rows_changed"]),
            "rows_dropped": str(discriminants["rows_dropped"]),
            "latest_datetime_changed": str(discriminants["latest_datetime_changed"]).lower(),
            "cutoff_hour_changed": str(discriminants["cutoff_hour_changed"]).lower(),
            "previous_cutoff_hour": str(previous["cutoff"]),
            "cutoff_hour": str(current["cutoff"]),
            "cutoff_delta": str(discriminants["cutoff_delta"]),
            "capture_minute": str(capture_minute),
            "previous_capture_minute": str(previous_capture_minute),
            "rows_lost_within_window": str(discriminants["rows_lost_within_window"]),
            "source_kind": discriminants["source_kind"],
            "mechanism": discriminants["mechanism"],
            "settled_high": compact_number(event["settled_high"]),
        }
        output.append(row)
        unit = seed["markets"][event["market_id"]]["unit"]
        drop_magnitudes[event["stratum"]][unit]["adjacent"].append(
            previous["high"] - current["high"]
        )
        drop_magnitudes[event["stratum"]][unit]["running_max_deficit"].append(
            event["prev_running_max"] - current["high"]
        )
        mechanisms[event["stratum"]][discriminants["mechanism"]] += 1
        if discriminants["cutoff_hour_changed"]:
            delta_key = str(discriminants["cutoff_delta"])
            cutoff_delta_totals[event["stratum"]][delta_key] += 1
            direction = "narrowed" if discriminants["cutoff_delta"] < 0 else "widened"
            cutoff_relationships[event["stratum"]][direction] += 1
            cutoff_relationships[event["stratum"]]["capture_minute_advanced"] += int(
                capture_minute > previous_capture_minute
            )
            cutoff_relationships[event["stratum"]]["raw_rows_dropped"] += int(
                discriminants["rows_dropped"] > 0
            )
            cutoff_relationships[event["stratum"]]["rows_lost_within_window"] += int(
                discriminants["rows_lost_within_window"] > 0
            )
            cutoff_relationships[event["stratum"]]["retained_rows_excluded_by_narrowing"] += int(
                discriminants["retained_rows_excluded_by_narrowing"] > 0
            )
            cutoff_relationships[event["stratum"]]["latest_observation_minute_regressed"] += int(
                discriminants["latest_observation_minute_delta"] is not None
                and discriminants["latest_observation_minute_delta"] < 0
            )
            cutoff_relationships[event["stratum"]]["latest_observation_minute_advanced"] += int(
                discriminants["latest_observation_minute_delta"] is not None
                and discriminants["latest_observation_minute_delta"] > 0
            )
            if discriminants["cutoff_delta"] > 0:
                widened_mechanisms[event["stratum"]][discriminants["mechanism"]] += 1
        if discriminants["mechanism"] == "M5_cutoff_change":
            m5_cutoff_delta_totals[event["stratum"]][str(discriminants["cutoff_delta"])] += 1
            raw_lowers = discriminants["raw_series_alone_lowered_max"]
            cutoff_lowers = discriminants["cutoff_alone_lowered_current_payload_max"]
            if raw_lowers is None or cutoff_lowers is None:
                effect_path = "unavailable"
            elif raw_lowers and cutoff_lowers:
                effect_path = "raw_series_and_cutoff"
            elif raw_lowers:
                effect_path = "raw_series_only"
            elif cutoff_lowers:
                effect_path = "cutoff_only"
            else:
                effect_path = "neither_on_wu_window_max"
            m5_effect_paths[event["stratum"]][effect_path] += 1
        if discriminants["mechanism"] == "M6_unexplained":
            fingerprint = m6_fingerprints[event["stratum"]]
            fingerprint[f"rows_{discriminants['previous_rows']}_to_{discriminants['current_rows']}"] += 1
            fingerprint["current_single_row"] += int(discriminants["current_rows"] == 1)
            fingerprint["latest_changed"] += int(discriminants["latest_datetime_changed"])
            fingerprint["same_source"] += int(not discriminants["source_kind_changed"])
            fingerprint["same_cutoff"] += int(not discriminants["cutoff_hour_changed"])
            fingerprint["no_raw_row_loss"] += int(discriminants["rows_dropped"] == 0)
            fingerprint["current_high_equals_history_max"] += int(
                close(current["high"], current_candidates["wu_history_max_c"])
            )
        for name in (
            "empty_history_fallback",
            "source_kind_changed",
            "restatement_pattern",
            "latest_datetime_changed",
            "cutoff_hour_changed",
        ):
            discriminant_totals[event["stratum"]][name] += int(bool(discriminants[name]))
        discriminant_totals[event["stratum"]]["rows_changed_positive"] += int(
            discriminants["rows_changed"] > 0
        )
        discriminant_totals[event["stratum"]]["rows_dropped_positive"] += int(
            discriminants["rows_dropped"] > 0
        )
        windows[event["stratum"]][window_label(capture_minute, seed)] += 1
        hours[event["stratum"]][str(capture_minute // 60)] += 1
        representatives.setdefault(
            discriminants["mechanism"],
            {
                "stratum": event["stratum"],
                "market_id": event["market_id"],
                "target_date": event["target_date"],
                "native_unit": unit,
                "previous_snapshot_id": previous["snapshot_id"],
                "snapshot_id": current["snapshot_id"],
                "previous_captured_at_utc": previous["captured_at_utc"],
                "captured_at_utc": current["captured_at_utc"],
                "previous_captured_at_local": previous_local_time,
                "captured_at_local": local_time,
                "previous_capture_minute": previous_capture_minute,
                "capture_minute": capture_minute,
                "previous_high_so_far": previous["high"],
                "high_so_far": current["high"],
                "previous_cutoff_hour": previous["cutoff"],
                "cutoff_hour": current["cutoff"],
                "previous_candidates": {
                    "max_rows_served_path": previous["high"],
                    **previous_candidates,
                },
                "current_candidates": {
                    "max_rows_served_path": current["high"],
                    **current_candidates,
                },
                **discriminants,
            },
        )
    output.sort(
        key=lambda row: (
            row["stratum"],
            row["market_id"],
            row["target_date"],
            row["local_time"],
            row["snapshot_id"],
        )
    )
    summary = {
        "mechanisms": {
            stratum: {name: mechanisms[stratum][name] for name in seed["classification"]["fixed_set"]}
            for stratum in ("B", "C")
        },
        "discriminant_totals": {
            stratum: dict(discriminant_totals[stratum]) for stratum in ("B", "C")
        },
        "cutoff_direction": {
            stratum: {
                "all_changed_signed_delta_distribution": dict(
                    sorted(cutoff_delta_totals[stratum].items(), key=lambda item: int(item[0]))
                ),
                "M5_signed_delta_distribution": dict(
                    sorted(m5_cutoff_delta_totals[stratum].items(), key=lambda item: int(item[0]))
                ),
                "M5_effect_path": dict(sorted(m5_effect_paths[stratum].items())),
                "relationships": dict(sorted(cutoff_relationships[stratum].items())),
                "widened_mechanisms": dict(sorted(widened_mechanisms[stratum].items())),
            }
            for stratum in ("B", "C")
        },
        "M6_fingerprints": {
            stratum: dict(sorted(m6_fingerprints[stratum].items()))
            for stratum in ("B", "C")
        },
        "time_windows": {stratum: dict(sorted(windows[stratum].items())) for stratum in ("B", "C")},
        "hour_of_day": {stratum: dict(sorted(hours[stratum].items(), key=lambda item: int(item[0]))) for stratum in ("B", "C")},
        "drop_magnitude_by_native_unit": {
            stratum: {
                unit: {
                    name: quantiles(values)
                    for name, values in drop_magnitudes[stratum][unit].items()
                }
                for unit in sorted(drop_magnitudes[stratum])
            }
            for stratum in ("B", "C")
        },
        "representative_events": representatives,
    }
    return output, summary


def candidate_value(
    name: str,
    row: dict[str, Any],
    candidates: dict[tuple[str, str, str, str], dict[str, float | None]],
) -> float | None:
    if name == "max_rows_served_path":
        return row["high"]
    key = (row["market_id"], row["target_date"], *capture_key(row))
    return (candidates.get(key) or {}).get(name)


def candidate_summary(
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
    events: list[dict[str, Any]],
    candidates: dict[tuple[str, str, str, str], dict[str, float | None]],
    seed: dict[str, Any],
) -> dict[str, Any]:
    names = tuple(seed["candidate_definitions"])
    summary = {
        stratum: {
            name: Counter(
                {
                    "snapshot_rows": 0,
                    "available_snapshot_rows": 0,
                    "exceeds_settlement_snapshot_rows": 0,
                    "adjacent_transitions": 0,
                    "available_adjacent_transitions": 0,
                    "decrease_transitions": 0,
                    "market_days_with_available_transition": 0,
                    "market_days_with_decrease": 0,
                    "decrease_event_rows": 0,
                    "available_decrease_event_rows": 0,
                    "exceeds_settlement_decrease_event_rows": 0,
                    "available_decrease_event_pairs": 0,
                    "candidate_decreases_on_high_so_far_decrease": 0,
                }
            )
            for name in names
        }
        for stratum in ("B", "C")
    }
    for rows in rows_by_day.values():
        if not rows:
            continue
        stratum = rows[0]["stratum"]
        for name in names:
            state = summary[stratum][name]
            day_available = False
            day_decreased = False
            previous_value: float | None = None
            previous_present = False
            for index, row in enumerate(rows):
                value = candidate_value(name, row, candidates)
                state["snapshot_rows"] += 1
                if value is not None:
                    state["available_snapshot_rows"] += 1
                    if value > row["settled_high"] + FLOAT_TOLERANCE:
                        state["exceeds_settlement_snapshot_rows"] += 1
                if index > 0:
                    state["adjacent_transitions"] += 1
                    if previous_present and value is not None:
                        state["available_adjacent_transitions"] += 1
                        day_available = True
                        if value < previous_value - FLOAT_TOLERANCE:  # type: ignore[operator]
                            state["decrease_transitions"] += 1
                            day_decreased = True
                previous_value = value
                previous_present = value is not None
            state["market_days_with_available_transition"] += int(day_available)
            state["market_days_with_decrease"] += int(day_decreased)
    for event in events:
        stratum = event["stratum"]
        previous = event["previous"]
        current = event["current_row"]
        for name in names:
            state = summary[stratum][name]
            state["decrease_event_rows"] += 1
            previous_value = candidate_value(name, previous, candidates)
            current_value = candidate_value(name, current, candidates)
            if current_value is not None:
                state["available_decrease_event_rows"] += 1
                if current_value > event["settled_high"] + FLOAT_TOLERANCE:
                    state["exceeds_settlement_decrease_event_rows"] += 1
            if previous_value is not None and current_value is not None:
                state["available_decrease_event_pairs"] += 1
                if current_value < previous_value - FLOAT_TOLERANCE:
                    state["candidate_decreases_on_high_so_far_decrease"] += 1
    return {
        stratum: {name: dict(state) for name, state in values.items()}
        for stratum, values in summary.items()
    }


def load_archive(
    evidence_root: Path,
    roster: dict[tuple[str, str], MarketDay],
    seed: dict[str, Any],
) -> tuple[dict[tuple[str, str, int], float], list[dict[str, Any]], dict[str, Any]]:
    markets = seed["markets"]
    daily_min_rows = int(seed["train_serve"]["daily_min_rows"])
    highs: dict[tuple[str, str, int], float] = {}
    receipts: list[dict[str, Any]] = []
    eligibility: dict[tuple[str, str], bool] = {}
    rows_by_day: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for market_id, market in sorted(markets.items()):
        target_dates = {date for (market, date) in roster if market == market_id}
        station_root = evidence_root / "data" / "wunderground" / market["station"]
        daily_path = station_root / "daily" / "daily_summary.csv"
        require(daily_path.is_file(), f"archive daily summary missing: {daily_path}")
        daily_rows = {row["local_date"]: row for row in read_csv(daily_path)}
        for target_date in target_dates:
            row = daily_rows.get(target_date)
            eligibility[(market_id, target_date)] = bool(
                row and int(row.get("row_count") or 0) >= daily_min_rows
            )
        receipts.append(
            {
                "kind": "wu_daily_summary",
                "path": relative(daily_path, evidence_root),
                "bytes": daily_path.stat().st_size,
                "sha256": sha256_file(daily_path),
            }
        )
        months = sorted({target_date[:7] for target_date in target_dates})
        for year_month in months:
            year, month = year_month.split("-")
            hourly_path = station_root / "hourly" / f"year={year}" / f"month={month}" / "observations.jsonl"
            require(hourly_path.is_file(), f"archive hourly file missing: {hourly_path}")
            digest = hashlib.sha256()
            with hourly_path.open("rb") as handle:
                for raw in handle:
                    digest.update(raw)
                    row = json.loads(raw)
                    target_date = str(row.get("local_date") or "")
                    if target_date not in target_dates:
                        continue
                    minute = minute_of_day(row.get("local_time"))
                    temperature = row_temperature(row)
                    if minute is not None and temperature is not None:
                        rows_by_day[(market_id, target_date)].append((minute, temperature))
            receipts.append(
                {
                    "kind": "wu_hourly_archive",
                    "path": relative(hourly_path, evidence_root),
                    "bytes": hourly_path.stat().st_size,
                    "sha256": digest.hexdigest(),
                }
            )
    eligible_days = 0
    for day, rows in rows_by_day.items():
        rows.sort()
        if not eligibility.get(day):
            continue
        eligible_days += 1
        for cutoff in range(7, 21):
            values = [temperature for minute, temperature in rows if minute <= cutoff * 60]
            if values:
                highs[(day[0], day[1], cutoff)] = max(values)
    return highs, receipts, {
        "market_days_with_hourly_rows": len(rows_by_day),
        "market_days_passing_daily_min_rows": eligible_days,
        "daily_min_rows": daily_min_rows,
    }


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {name: None for name in ("min", "p50", "p90", "p95", "p99", "max")}
    ordered = sorted(values)

    def nearest(probability: float) -> float:
        index = round((len(ordered) - 1) * probability)
        return ordered[index]

    return {
        "min": ordered[0],
        "p50": nearest(0.50),
        "p90": nearest(0.90),
        "p95": nearest(0.95),
        "p99": nearest(0.99),
        "max": ordered[-1],
    }


def train_serve_summary(
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
    archive_highs: dict[tuple[str, str, int], float],
    roster: dict[tuple[str, str], MarketDay],
) -> dict[str, Any]:
    def summarize(selected: list[tuple[tuple[str, str], MarketDay]]) -> dict[str, Any]:
        counts = Counter()
        absolute_differences: list[float] = []
        market_day_maxima: list[float] = []
        day_directions = Counter()
        representatives: dict[str, dict[str, Any]] = {}
        for (market_id, target_date), market_day in selected:
            rows = rows_by_day[(market_id, target_date)]
            counts["market_days"] += 1
            if not rows:
                day_directions["unavailable"] += 1
                continue
            day_deltas: list[float] = []
            for row in rows:
                counts["snapshot_rows"] += 1
                training = archive_highs.get((market_id, target_date, row["cutoff"]))
                if training is None:
                    counts["unavailable_snapshot_rows"] += 1
                    continue
                counts["comparable_snapshot_rows"] += 1
                delta = training - row["high"]
                day_deltas.append(delta)
                if abs(delta) <= FLOAT_TOLERANCE:
                    counts["equal_snapshot_rows"] += 1
                elif delta > 0:
                    counts["training_higher_snapshot_rows"] += 1
                    absolute_differences.append(abs(delta))
                else:
                    counts["training_lower_snapshot_rows"] += 1
                    absolute_differences.append(abs(delta))
                if abs(delta) > FLOAT_TOLERANCE:
                    record = {
                        "market_id": market_id,
                        "target_date": target_date,
                        "native_unit": market_day.unit,
                        "snapshot_id": row["snapshot_id"],
                        "captured_at_utc": row["captured_at_utc"],
                        "cutoff_hour": row["cutoff"],
                        "recorded_served_high_so_far": row["high"],
                        "training_archive_high_so_far": training,
                        "delta": delta,
                    }
                    if delta > 0 and (
                        "largest_training_higher" not in representatives
                        or delta > representatives["largest_training_higher"]["delta"]
                    ):
                        representatives["largest_training_higher"] = record
                    if delta < 0 and (
                        "largest_training_lower" not in representatives
                        or delta < representatives["largest_training_lower"]["delta"]
                    ):
                        representatives["largest_training_lower"] = record
                    if (
                        "largest_absolute_difference" not in representatives
                        or abs(delta)
                        > abs(representatives["largest_absolute_difference"]["delta"])
                    ):
                        representatives["largest_absolute_difference"] = record
            if not day_deltas:
                day_directions["unavailable"] += 1
                continue
            nonzero = [delta for delta in day_deltas if abs(delta) > FLOAT_TOLERANCE]
            if not nonzero:
                day_directions["all_equal"] += 1
                market_day_maxima.append(0.0)
            else:
                counts["market_days_with_difference"] += 1
                market_day_maxima.append(max(abs(delta) for delta in nonzero))
                if all(delta > 0 for delta in nonzero):
                    day_directions["training_higher_only"] += 1
                elif all(delta < 0 for delta in nonzero):
                    day_directions["training_lower_only"] += 1
                else:
                    day_directions["mixed_sign"] += 1
        return {
            **dict(counts),
            "market_day_direction": dict(day_directions),
            "nonzero_absolute_difference": quantiles(absolute_differences),
            "market_day_max_absolute_difference": quantiles(market_day_maxima),
            "representative_extrema": representatives,
        }

    output: dict[str, Any] = {}
    for stratum in ("B", "C"):
        selected = [item for item in roster.items() if item[1].stratum == stratum]
        summary = summarize(selected)
        summary["by_native_unit"] = {
            unit: summarize([item for item in selected if item[1].unit == unit])
            for unit in sorted({market_day.unit for _, market_day in selected})
        }
        output[stratum] = summary
    return output


def known_blocking_rows(
    rows_by_day: dict[tuple[str, str], list[dict[str, Any]]],
    candidates: dict[tuple[str, str, str, str], dict[str, float | None]],
    seed: dict[str, Any],
) -> list[dict[str, Any]]:
    output = []
    for spec in seed["known_blocking_rows"]:
        day = (spec["market_id"], spec["target_date"])
        matches = [row for row in rows_by_day[day] if row["snapshot_id"] == spec["snapshot_id"]]
        require(len(matches) == 1, f"known blocking row match drifted: {spec} -> {len(matches)}")
        row = matches[0]
        key = (row["market_id"], row["target_date"], *capture_key(row))
        output.append(
            {
                **spec,
                "captured_at_utc": row["captured_at_utc"],
                "local_time": local_clock(row)[0],
                "settled_high": row["settled_high"],
                "candidates": {
                    "max_rows_served_path": row["high"],
                    **candidates[key],
                },
            }
        )
    return output


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
    extract_hash = sha256_file(output_path)
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
        f"{extract_hash}  {output_path.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "csv": str(output_path),
        "csv_sha256": extract_hash,
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "sha256": str(sha_path),
        "sha256_sha256": sha256_file(sha_path),
    }


def analyze(repo_root: Path, evidence_root: Path, seed_path: Path, output_path: Path) -> dict[str, Any]:
    seed = load_seed(seed_path)
    roster, roster_receipt = load_roster(repo_root, seed)
    folders = discover_folders(evidence_root, roster, seed["markets"])
    rows_by_day, events, keys_by_day, feature_receipts, support = load_features(
        evidence_root, roster, folders, seed
    )
    candidates, event_payloads, replay_receipts, replay_support = load_replay_payloads(
        evidence_root, folders, keys_by_day, events
    )
    event_rows, event_summary = classify_events(events, event_payloads, seed)
    require(len(event_rows) == 2190, f"decrease event count drifted: {len(event_rows)}")
    archive_highs, archive_receipts, archive_support = load_archive(evidence_root, roster, seed)
    all_receipts = [roster_receipt, *feature_receipts, *replay_receipts, *archive_receipts]
    receipt_core = [
        {key: receipt[key] for key in ("kind", "path", "bytes", "sha256")}
        for receipt in sorted(all_receipts, key=lambda item: (item["kind"], item["path"]))
    ]
    manifest = {
        "artifact": "high_so_far_cutoff_direction_v1",
        "built_for": "-09-71a high_so_far cutoff-direction census",
        "seed": {
            "relative_path": relative(seed_path, repo_root),
            "bytes": seed_path.stat().st_size,
            "sha256": sha256_file(seed_path),
        },
        "source_base_commit": seed["source_base_commit"],
        "population": support,
        "population_reconciles_handoff": True,
        "classification": {
            **event_summary,
            "fixed_set": seed["classification"]["fixed_set"],
            "precedence": seed["classification"]["precedence"],
        },
        "counterfactual_candidates": candidate_summary(rows_by_day, events, candidates, seed),
        "known_blocking_rows": known_blocking_rows(rows_by_day, candidates, seed),
        "train_serve": train_serve_summary(rows_by_day, archive_highs, roster),
        "support": {
            "replay": replay_support,
            "archive": archive_support,
            "input_files": len(receipt_core),
            "input_bytes": sum(int(item["bytes"]) for item in receipt_core),
            "input_receipts_sha256": canonical_sha256(receipt_core),
            "input_file_kinds": dict(Counter(item["kind"] for item in receipt_core)),
        },
        "method": {
            "interval_treatment": "exact finite-population census; no sampling interval, bootstrap, power, or alpha applies",
            "B_and_C_reported_separately": True,
            "pooled_across_2026_07_31": False,
            "candidate_definitions": seed["candidate_definitions"],
            "train_serve": seed["train_serve"],
            "time_windows_local": seed["time_windows_local"],
            "snapshot_join": "(snapshot_id, captured_at_utc); snapshot_id is emitted verbatim but is not unique in the retained feature files",
        },
        "campaign": seed["campaign"],
        "contains_fitted_quantities": False,
        "contains_market_prices": False,
        "contains_C_endpoint": False,
        "explicitly_not_done": [
            "no alpha allocation, candidate, fitting, endpoint comparison, or accept rule",
            "no high_so_far, floor, collection, replay, scoring, settlement, or serving change",
            "no provider or exchange call, production data write, registration, restart, promotion, activation, release, trade, merge, or PR",
        ],
    }
    expected_reconciliation = seed["direction_reconciliation"]
    for stratum in ("B", "C"):
        require(
            event_summary["mechanisms"][stratum]["M5_cutoff_change"]
            == expected_reconciliation["M5_cutoff_change"][stratum],
            f"{stratum} M5 population no longer reconciles -09-70a",
        )
        require(
            event_summary["discriminant_totals"][stratum]["cutoff_hour_changed"]
            == expected_reconciliation["cutoff_hour_changed"][stratum],
            f"{stratum} raw cutoff-change population no longer reconciles -09-70a",
        )
    artifacts = write_outputs(output_path, event_rows, manifest)
    return {
        "status": "PASS",
        "verdict": "HIGH_SO_FAR_CUTOFF_DIRECTION_MEASURED",
        "artifacts": artifacts,
        "population": support,
        "mechanisms": event_summary["mechanisms"],
        "time_windows": event_summary["time_windows"],
        "train_serve": manifest["train_serve"],
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
