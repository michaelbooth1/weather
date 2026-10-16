"""FC-11: closed-day served-payload point-in-time (PIT) extractor.

Data layer v2 step S0b (``docs/operations/DATA_LAYER_V2_PLAN.md`` FC-11).
A fresh, read-only process that reads the per-event ``forecast_payloads``
manifests and their market-local content-addressed blobs and writes one
compressed long-format PIT table per closed local target date::

    market, event_slug, target_date, source, model, member, fetched_at,
    first_seen_at, run_init, valid_time, valid_period, field, value, unit,
    availability_basis, payload_hash

Contract:

* Outcome-blind and read-only. Nothing under the snapshots root is written;
  the output directory must lie outside the runtime ``data`` tree.
* Embargo first. The event date is parsed from the event directory name
  before its manifest is opened, and every manifest row is checked again
  (target date and local fetch date) before its blob is opened. Dates in
  ``EMBARGO_FIRST..EMBARGO_LAST`` and dates after ``--max-date`` are never
  read. A request whose range reaches into the embargo is refused.
* One PIT row set per distinct fetch ``(event, source, payload_hash,
  fetched_at)``. A ``fresh_cache`` manifest row that reuses an earlier fetch
  adds no rows; it only moves ``first_seen_at`` earlier if it was captured
  first. ``fetched_at`` is the live receipt time, so every row carries
  ``availability_basis = live_receipt``.
* ``run_init`` is never invented. Open-Meteo stores no run identity, so a
  blended product (best_match, ``*_seamless``, air quality) gets
  ``blend_unresolved`` and a single-model column gets null. NWS rows carry
  the grid ``updateTime`` the payload itself states.
* Acceptance per day: every manifest row gets exactly one disposition, and
  the written file, read back, has exactly the expected row count per fetch.
  The per-day receipt records both.
* Bounded memory and shared reads. A day is streamed to disk one fetch bucket
  at a time, never held whole. Inputs are opened with share-read, write and
  delete, so capture writers are never blocked.
* Resumable. A day with a receipt is skipped and ``--max-days`` counts only
  days extracted now, so a backlog can be worked in short nightly chunks
  against one output directory. A table without a receipt is an interrupted
  attempt and is renamed ``*.orphan-<stamp>`` before the day is redone.

This module is not imported by any capture loop; keep it that way (it must
stay roll-free). The receipt identifies its format by a name plus an integer
revision; it is not a registered core schema.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather.paths import data_path


PIT_TABLE_NAME = "fc11_served_payload_pit"
PIT_TABLE_REVISION = 1
DAY_RECEIPT_NAME = "fc11_pit_day_receipt"
RUN_RECEIPT_NAME = "fc11_pit_run_receipt"
RECEIPT_REVISION = 1

AVAILABILITY_BASIS = "live_receipt"
BLEND_UNRESOLVED = "blend_unresolved"

# Evaluation embargo for this extraction (UTC 2026-09-30..10-15). Never read.
EMBARGO_FIRST = date(2026, 9, 30)
EMBARGO_LAST = date(2026, 10, 15)

MANIFEST_JSONL = "forecast_payloads.jsonl"
MANIFEST_CSV = "forecast_payloads_long.csv"
BLOB_DIR = "forecast_payloads"

# model_sources.py fetch_open_meteo: the 21 served best_match hourly fields.
OPEN_METEO_SERVED_FIELDS = (
    "temperature_2m", "cloud_cover", "cloud_cover_low", "cloud_cover_mid",
    "cloud_cover_high", "wind_speed_10m", "shortwave_radiation", "cape",
    "temperature_925hPa", "temperature_850hPa", "geopotential_height_500hPa",
    "direct_radiation", "diffuse_radiation", "wind_gusts_10m", "visibility",
    "precipitation_probability", "precipitation", "soil_temperature_0cm",
    "soil_moisture_0_to_1cm", "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
)

# Per-model column suffixes of the multi-model Open-Meteo requests.
OPEN_METEO_MODEL_SUFFIXES = {
    "open_meteo_global_models": (
        "ecmwf_ifs025", "ecmwf_aifs025", "ncep_aigfs025", "gfs_graphcast025",
    ),
    "open_meteo_multimodel": (
        "gfs_seamless", "ncep_hrrr_conus", "ncep_nbm_conus", "ncep_nam_conus",
    ),
    "eccc_gem": ("gem_seamless", "gem_global", "gem_regional"),
}
OPEN_METEO_DEFAULT_MODEL = {
    "open_meteo": "best_match",
    "open_meteo_air_quality": "air_quality_auto",
    "global_ensemble": "gfs_seamless",
}
OPEN_METEO_SOURCES = frozenset(OPEN_METEO_DEFAULT_MODEL) | frozenset(OPEN_METEO_MODEL_SUFFIXES)
NWS_SOURCES = frozenset({"nws_hourly", "nws_grid"})
SUPPORTED_SOURCES = OPEN_METEO_SOURCES | NWS_SOURCES

NWS_HOURLY_FIELDS = {
    "temperature": None,
    "probabilityOfPrecipitation": "value",
    "dewpoint": "value",
    "relativeHumidity": "value",
}

PIT_COLUMNS = (
    "market", "event_slug", "target_date", "source", "model", "member",
    "fetched_at", "first_seen_at", "run_init", "valid_time", "valid_period",
    "field", "value", "unit", "availability_basis", "payload_hash",
)

_MONTHS = {
    name: index
    for index, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"),
        start=1,
    )
}
_SLUG_RE = re.compile(
    r"^(?:highest|lowest)-temperature-in-(?P<market>[a-z0-9-]+?)-on-"
    r"(?P<month>[a-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})$"
)
_MEMBER_RE = re.compile(r"^(?P<field>.+)_member(?P<member>\d+)$")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class ExtractionRefused(ValueError):
    """A request outside the closed-day, pre-embargo, read-only contract."""


# ---------------------------------------------------------------- helpers


def parse_event_slug(slug: str) -> tuple[str, date] | None:
    """Return ``(market, target_date)`` from an event slug, or None."""

    match = _SLUG_RE.match(str(slug or "").strip().lower())
    if not match:
        return None
    month = _MONTHS.get(match.group("month"))
    if month is None:
        return None
    try:
        target = date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None
    return match.group("market"), target


def is_embargoed(day: date) -> bool:
    return EMBARGO_FIRST <= day <= EMBARGO_LAST


def date_allowed(day: date | None, max_date: date, min_date: date | None) -> bool:
    if day is None or is_embargoed(day) or day > max_date:
        return False
    return min_date is None or day >= min_date


def check_request(max_date: date, min_date: date | None) -> None:
    if max_date >= EMBARGO_FIRST:
        raise ExtractionRefused(
            f"refused: --max-date {max_date} reaches the embargo "
            f"{EMBARGO_FIRST}..{EMBARGO_LAST}; FC-11 backlog runs stop at "
            f"{EMBARGO_FIRST - timedelta(days=1)}"
        )
    if min_date is not None and min_date > max_date:
        raise ExtractionRefused("refused: --min-date is after --max-date")


def check_out_dir(out_dir: Path, snapshot_roots: Iterable[Path]) -> Path:
    out = Path(os.path.abspath(out_dir))
    guarded = [Path(os.path.abspath(data_path()))]
    guarded.extend(Path(os.path.abspath(root)) for root in snapshot_roots)
    for root in guarded:
        if out == root or root in out.parents:
            raise ExtractionRefused(
                f"refused: --out-dir {out} is inside the read-only input tree {root}"
            )
    return out


def long_path(path: Path) -> str:
    """Return an OS path that opens past MAX_PATH on Windows."""

    text = os.path.abspath(os.fspath(path))
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        if text.startswith("\\\\"):
            return "\\\\?\\UNC\\" + text[2:]
        return "\\\\?\\" + text
    return text


_FILE_SHARE_READ_WRITE_DELETE = 0x1 | 0x2 | 0x4
_FILE_ATTRIBUTE_NORMAL = 0x80


def open_input(path: Path, mode: str = "rb", **kwargs):
    """Open an input file read-only without blocking any writer, renamer or deleter.

    CPython ``open()`` on Windows shares read and write but not delete, so a
    capture writer that replaces a manifest by rename would fail while this
    process holds it. Inputs are opened with ``FILE_SHARE_READ | WRITE |
    DELETE`` instead. Elsewhere this is plain ``open()``.
    """

    if mode not in {"rb", "r"}:
        raise ValueError(f"open_input is read-only, not {mode!r}")
    if os.name != "nt":
        return open(long_path(path), mode, **kwargs)
    import _winapi
    import msvcrt

    handle = _winapi.CreateFile(
        long_path(path), _winapi.GENERIC_READ, _FILE_SHARE_READ_WRITE_DELETE, 0,
        _winapi.OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, 0,
    )
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except BaseException:
        _winapi.CloseHandle(handle)
        raise
    return os.fdopen(fd, mode, **kwargs)


def parse_timestamp(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def utc_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_iso_precise(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def numeric(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number else None
    return None


def _zone(payload: dict):
    name = payload.get("timezone")
    if name:
        try:
            return ZoneInfo(str(name))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    offset = payload.get("utc_offset_seconds")
    if isinstance(offset, (int, float)) and not isinstance(offset, bool):
        return timezone(timedelta(seconds=int(offset)))
    return None


def _open_meteo_valid_time(raw, zone) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if zone is None:
            return None
        parsed = parsed.replace(tzinfo=zone)
    return utc_iso(parsed)


# ------------------------------------------------------- payload parsers


@dataclass(frozen=True)
class Cell:
    model: str
    member: int | None
    run_init: str | None
    valid_time: str
    valid_period: str | None
    field: str
    value: float
    unit: str | None


def _model_run_init(model: str) -> str | None:
    if model in {"best_match", "air_quality_auto"} or model.endswith("_seamless"):
        return BLEND_UNRESOLVED
    return None


def _split_open_meteo_key(source: str, key: str) -> tuple[str, str, int | None]:
    """Return ``(field, model, member)`` for one hourly column name."""

    if source == "global_ensemble":
        match = _MEMBER_RE.match(key)
        model = OPEN_METEO_DEFAULT_MODEL[source]
        if match:
            return match.group("field"), model, int(match.group("member"))
        # The unsuffixed ensemble column is the control member (S0(d) flag a).
        return key, model, 0
    for suffix in sorted(OPEN_METEO_MODEL_SUFFIXES.get(source, ()), key=len, reverse=True):
        if key.endswith("_" + suffix) and len(key) > len(suffix) + 1:
            return key[: -(len(suffix) + 1)], suffix, None
    return key, OPEN_METEO_DEFAULT_MODEL.get(source, "unresolved"), None


def parse_open_meteo(source: str, payload: dict) -> tuple[list[Cell], int]:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("open-meteo payload has no hourly block")
    times = hourly.get("time")
    if not isinstance(times, list):
        raise ValueError("open-meteo payload has no hourly time axis")
    zone = _zone(payload)
    valid_times = [_open_meteo_valid_time(raw, zone) for raw in times]
    units = payload.get("hourly_units") if isinstance(payload.get("hourly_units"), dict) else {}
    cells: list[Cell] = []
    skipped = 0
    for key in sorted(hourly):
        if key == "time":
            continue
        values = hourly[key]
        if not isinstance(values, list):
            skipped += 1
            continue
        field_name, model, member = _split_open_meteo_key(source, key)
        run_init = _model_run_init(model)
        unit = units.get(key)
        for index, raw in enumerate(values):
            value = numeric(raw)
            valid = valid_times[index] if index < len(valid_times) else None
            if value is None or valid is None:
                skipped += 1
                continue
            cells.append(Cell(model, member, run_init, valid, None, field_name, value, unit))
    return cells, skipped


def _nws_interval(raw) -> tuple[str | None, str | None]:
    text = str(raw or "").strip()
    start, _, period = text.partition("/")
    moment = parse_timestamp(start)
    return (utc_iso(moment) if moment else None), (period or None)


def _nws_run_init(properties: dict) -> str | None:
    moment = parse_timestamp(properties.get("updateTime"))
    return utc_iso(moment) if moment else None


def parse_nws_grid(payload: dict) -> tuple[list[Cell], int]:
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("nws grid payload has no properties")
    run_init = _nws_run_init(properties)
    cells: list[Cell] = []
    skipped = 0
    for key in sorted(properties):
        layer = properties[key]
        if not isinstance(layer, dict) or not isinstance(layer.get("values"), list):
            continue
        unit = layer.get("uom")
        for entry in layer["values"]:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            value = numeric(entry.get("value"))
            valid, period = _nws_interval(entry.get("validTime"))
            if value is None or valid is None:
                skipped += 1
                continue
            cells.append(Cell("nws_ndfd_grid", None, run_init, valid, period, key, value, unit))
    return cells, skipped


def parse_nws_hourly(payload: dict) -> tuple[list[Cell], int]:
    properties = payload.get("properties")
    if not isinstance(properties, dict) or not isinstance(properties.get("periods"), list):
        raise ValueError("nws hourly payload has no periods")
    run_init = _nws_run_init(properties)
    cells: list[Cell] = []
    skipped = 0
    for period in properties["periods"]:
        if not isinstance(period, dict):
            skipped += 1
            continue
        start = parse_timestamp(period.get("startTime"))
        if start is None:
            skipped += 1
            continue
        valid = utc_iso(start)
        for key, sub in NWS_HOURLY_FIELDS.items():
            raw = period.get(key)
            unit = None
            if sub is not None:
                if isinstance(raw, dict):
                    unit = raw.get("unitCode")
                    raw = raw.get(sub)
                else:
                    raw = None
            elif key == "temperature":
                unit = period.get("temperatureUnit")
            value = numeric(raw)
            if value is None:
                skipped += 1
                continue
            cells.append(Cell("nws_ndfd_hourly", None, run_init, valid, "PT1H", key, value, unit))
        speed = _NUMBER_RE.findall(str(period.get("windSpeed") or ""))
        if len(speed) == 1:
            cells.append(Cell(
                "nws_ndfd_hourly", None, run_init, valid, "PT1H", "windSpeed",
                float(speed[0]), "mph" if "mph" in str(period.get("windSpeed")) else None,
            ))
        else:
            skipped += 1
    return cells, skipped


def parse_payload(source: str, payload) -> tuple[list[Cell], int]:
    if not isinstance(payload, dict):
        raise ValueError("payload is not a JSON object")
    if source in OPEN_METEO_SOURCES:
        return parse_open_meteo(source, payload)
    if source == "nws_grid":
        return parse_nws_grid(payload)
    if source == "nws_hourly":
        return parse_nws_hourly(payload)
    raise ValueError(f"unsupported source {source}")


# --------------------------------------------------------- manifest scan


def read_manifest_rows(event_dir: Path) -> tuple[list[dict], int, str | None]:
    """Return ``(rows, unparseable_count, manifest_name)`` for one event."""

    jsonl = event_dir / MANIFEST_JSONL
    if os.path.exists(long_path(jsonl)):
        rows: list[dict] = []
        bad = 0
        with open_input(jsonl, "r", encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    bad += 1
        return rows, bad, MANIFEST_JSONL
    long_csv = event_dir / MANIFEST_CSV
    if os.path.exists(long_path(long_csv)):
        with open_input(long_csv, "r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)], 0, MANIFEST_CSV
    return [], 0, None


@dataclass
class EventRef:
    root: Path
    event_dir: Path
    slug: str
    market: str
    target_date: date


def discover_events(
    roots: Iterable[Path], max_date: date, min_date: date | None,
) -> tuple[dict[date, list[EventRef]], Counter]:
    """Group event directories by slug date without opening embargoed ones."""

    by_day: dict[date, list[EventRef]] = defaultdict(list)
    skipped: Counter = Counter()
    for root in roots:
        root = Path(root)
        if not os.path.isdir(long_path(root)):
            skipped["missing_root"] += 1
            continue
        for name in sorted(os.listdir(long_path(root))):
            parsed = parse_event_slug(name)
            if parsed is None:
                skipped["unparsed_event_name"] += 1
                continue
            market, target = parsed
            if is_embargoed(target):
                skipped["embargoed_event"] += 1
                continue
            if not date_allowed(target, max_date, min_date):
                skipped["out_of_range_event"] += 1
                continue
            event_dir = root / name
            if not os.path.isdir(long_path(event_dir)):
                continue
            by_day[target].append(EventRef(root, event_dir, name, market, target))
    return by_day, skipped


def _blob_path(event_dir: Path, row: dict) -> Path | None:
    scope = str(row.get("payload_storage_scope") or "market_local").strip()
    if scope and scope != "market_local":
        return None
    ref = str(row.get("payload_ref") or "").strip().replace("\\", "/")
    if ref:
        if ref.startswith("/") or ".." in ref.split("/"):
            return None
        return event_dir / BLOB_DIR / Path(*ref.split("/"))
    digest = str(row.get("payload_hash") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest):
        return event_dir / BLOB_DIR / "sha256" / digest[:2] / f"{digest}.json"
    return None


def _row_local_fetch_date(row: dict) -> date | None:
    moment = parse_timestamp(row.get("fetched_at"))
    return moment.date() if moment is not None else None


@dataclass
class FetchGroup:
    event: EventRef
    source: str
    payload_hash: str
    fetched_at: str
    blob: Path
    first_seen_at: str | None = None
    manifest_rows: int = 0


@dataclass
class DayResult:
    target_date: date
    events: list[str] = field(default_factory=list)
    manifest_files: Counter = field(default_factory=Counter)
    manifest_rows: int = 0
    dispositions: Counter = field(default_factory=Counter)
    rows_by_source: Counter = field(default_factory=Counter)
    fetches_by_source: Counter = field(default_factory=Counter)
    null_cells_skipped: int = 0
    open_meteo_fields_seen: set = field(default_factory=set)
    expected_by_fetch: dict = field(default_factory=dict)


def _fetch_key(group: FetchGroup) -> str:
    return "|".join((group.event.slug, group.source, group.payload_hash, group.fetched_at))


def collect_day(events: list[EventRef], max_date: date, min_date: date | None) -> tuple[DayResult, list[FetchGroup]]:
    """Assign every manifest row of one day exactly one disposition."""

    result = DayResult(target_date=events[0].target_date)
    groups: dict[tuple, FetchGroup] = {}
    for event in sorted(events, key=lambda ref: (ref.slug, str(ref.root))):
        result.events.append(event.slug)
        rows, bad, manifest_name = read_manifest_rows(event.event_dir)
        result.manifest_files[manifest_name or "none"] += 1
        result.manifest_rows += len(rows) + bad
        if bad:
            result.dispositions["unparseable_row"] += bad
        for row in rows:
            source = str(row.get("source") or "").strip()
            row_target = None
            try:
                row_target = date.fromisoformat(str(row.get("target_date") or "")[:10])
            except ValueError:
                row_target = event.target_date
            fetch_day = _row_local_fetch_date(row)
            if (
                row_target != event.target_date
                or not date_allowed(row_target, max_date, min_date)
                or (fetch_day is not None and not date_allowed(fetch_day, max_date, None))
            ):
                result.dispositions["row_date_refused"] += 1
                continue
            if source not in SUPPORTED_SOURCES:
                result.dispositions[f"unsupported_source:{source or 'blank'}"] += 1
                continue
            blob = _blob_path(event.event_dir, row)
            digest = str(row.get("payload_hash") or "").strip().lower()
            if blob is None or not digest:
                result.dispositions["no_market_local_blob_ref"] += 1
                continue
            fetched = parse_timestamp(row.get("fetched_at"))
            captured = parse_timestamp(row.get("captured_at_utc"))
            if fetched is None:
                fetched = captured
            if fetched is None:
                result.dispositions["no_fetch_time"] += 1
                continue
            fetched_text = utc_iso_precise(fetched)
            # Keyed by slug, not folder: copies of one event under several
            # roots describe the same fetch and must not duplicate PIT rows.
            key = (event.slug, source, digest, fetched_text)
            group = groups.get(key)
            if group is None:
                group = FetchGroup(event, source, digest, fetched_text, blob)
                groups[key] = group
                result.dispositions["fetch_first_row"] += 1
            else:
                result.dispositions["fetch_repeat_row"] += 1
            group.manifest_rows += 1
            if captured is not None:
                seen = utc_iso_precise(captured)
                if group.first_seen_at is None or seen < group.first_seen_at:
                    group.first_seen_at = seen
    return result, list(groups.values())


def _read_blob(group: FetchGroup) -> dict:
    with open_input(group.blob, "rb") as handle:
        raw = handle.read()
    # The store appends one durability newline that is not part of the
    # addressed bytes (SnapshotStore.write_content_addressed_payload).
    addressed = raw[:-1] if raw.endswith(b"\n") else raw
    if len(group.payload_hash) == 64 and hashlib.sha256(addressed).hexdigest() != group.payload_hash:
        raise ValueError("blob sha256 does not match payload_hash")
    return json.loads(raw.decode("utf-8"))


def _record(group: FetchGroup, cell: Cell) -> dict:
    return {
        "market": group.event.market,
        "event_slug": group.event.slug,
        "target_date": group.event.target_date.isoformat(),
        "source": group.source,
        "model": cell.model,
        "member": cell.member,
        "fetched_at": group.fetched_at,
        "first_seen_at": group.first_seen_at,
        "run_init": cell.run_init,
        "valid_time": cell.valid_time,
        "valid_period": cell.valid_period,
        "field": cell.field,
        "value": cell.value,
        "unit": cell.unit,
        "availability_basis": AVAILABILITY_BASIS,
        "payload_hash": group.payload_hash,
    }


def _cell_order(record: dict) -> tuple:
    return (record["model"], record["field"], -1 if record["member"] is None else record["member"],
            record["valid_time"])


def iter_day_records(result: DayResult, groups: list[FetchGroup]) -> Iterator[list[dict]]:
    """Yield the day's PIT records one ``(event, source, fetched_at)`` bucket at a time.

    Groups are visited in ``(event, source, fetched_at, payload_hash)`` order and
    each bucket is sorted by ``(model, field, member, valid_time)``, so the
    concatenated output has the table's sort order while only one bucket of row
    dicts is held in memory (FC-11 used to hold the whole day: 1-4M rows).
    """

    bucket_key = None
    bucket: list[dict] = []
    for group in sorted(groups, key=lambda item: (item.event.slug, item.source, item.fetched_at, item.payload_hash)):
        key = _fetch_key(group)
        if not os.path.exists(long_path(group.blob)):
            result.dispositions["missing_blob_fetch"] += 1
            result.dispositions["missing_blob_rows"] += group.manifest_rows
            continue
        try:
            payload = _read_blob(group)
            cells, skipped = parse_payload(group.source, payload)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            reason = "hash_mismatch" if "sha256" in str(exc) else "parse_error"
            result.dispositions[f"{reason}_fetch"] += 1
            result.dispositions[f"{reason}_rows"] += group.manifest_rows
            continue
        del payload
        result.null_cells_skipped += skipped
        result.fetches_by_source[group.source] += 1
        result.rows_by_source[group.source] += len(cells)
        result.dispositions["extracted_rows"] += group.manifest_rows
        result.expected_by_fetch[key] = len(cells)
        if group.source == "open_meteo":
            result.open_meteo_fields_seen.update(cell.field for cell in cells)
        this_bucket = (group.event.slug, group.source, group.fetched_at)
        if this_bucket != bucket_key and bucket:
            bucket.sort(key=_cell_order)
            yield bucket
            bucket = []
        bucket_key = this_bucket
        bucket.extend(_record(group, cell) for cell in cells)
    if bucket:
        bucket.sort(key=_cell_order)
        yield bucket


# ---------------------------------------------------------------- writers


def parquet_available() -> bool:
    return importlib.util.find_spec("pyarrow") is not None


class _JsonlGzWriter:
    def __init__(self, path: Path):
        self._handle = gzip.open(long_path(path), "wt", encoding="utf-8", compresslevel=6)

    def write(self, records: list[dict]) -> None:
        for record in records:
            self._handle.write(json.dumps({name: record[name] for name in PIT_COLUMNS}, sort_keys=True))
            self._handle.write("\n")

    def close(self) -> None:
        self._handle.close()


class _ParquetWriter:
    def __init__(self, path: Path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        self._pa = pa
        self._schema = pa.schema(
            [(name, pa.int32() if name == "member" else pa.float64() if name == "value" else pa.string())
             for name in PIT_COLUMNS],
            metadata={"pit_table": PIT_TABLE_NAME, "pit_table_revision": str(PIT_TABLE_REVISION)},
        )
        self._writer = pq.ParquetWriter(long_path(path), self._schema, compression="zstd")

    def write(self, records: list[dict]) -> None:
        columns = {name: [record[name] for record in records] for name in PIT_COLUMNS}
        self._writer.write_table(self._pa.Table.from_pydict(columns, schema=self._schema))

    def close(self) -> None:
        self._writer.close()


# Rows buffered before a write; bounds memory independently of a bucket's size.
WRITE_BATCH_ROWS = 50_000


def read_back(path: Path) -> Iterator[tuple[str, str, str, str]]:
    """Yield ``(event_slug, source, payload_hash, fetched_at)`` per written row."""

    names = ("event_slug", "source", "payload_hash", "fetched_at")
    if path.name.endswith(".parquet") or path.name.endswith(".parquet.partial"):
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(long_path(path))
        for batch in parquet.iter_batches(batch_size=WRITE_BATCH_ROWS, columns=list(names)):
            columns = [batch.column(name).to_pylist() for name in names]
            yield from zip(*columns)
        return
    with gzip.open(long_path(path), "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            yield row["event_slug"], row["source"], row["payload_hash"], row["fetched_at"]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(long_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    with open(long_path(temp), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(long_path(temp), long_path(path))


def _set_aside(path: Path, stamp: str) -> str | None:
    """Rename an earlier interrupted attempt's file out of the way; never delete it."""

    if not os.path.exists(long_path(path)):
        return None
    target = path.with_name(f"{path.name}.orphan-{stamp}")
    os.rename(long_path(path), long_path(target))
    return str(target)


def extract_and_write_day(
    out_dir: Path, events: list[EventRef], max_date: date, min_date: date | None, fmt: str,
    *, stamp: str = "",
) -> dict:
    """Extract one day and stream it to its table; return the day receipt.

    The table is written as ``<name>.partial`` and renamed only after the
    read-back checks ran, and the caller writes the receipt after that, so a
    day without a receipt is an interrupted attempt. Its leftover files are
    renamed ``*.orphan-<stamp>`` (never overwritten or deleted) before the day
    is extracted again.
    """

    result, groups = collect_day(events, max_date, min_date)
    day = result.target_date.isoformat()
    day_dir = out_dir / "pit" / f"target_date={day}"
    os.makedirs(long_path(day_dir), exist_ok=True)
    suffix = ".parquet" if fmt == "parquet" else ".jsonl.gz"
    table_path = day_dir / f"{PIT_TABLE_NAME}{suffix}"
    partial_path = day_dir / f"{PIT_TABLE_NAME}{suffix}.partial"
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    orphans = [p for p in (_set_aside(table_path, stamp), _set_aside(partial_path, stamp)) if p]

    writer = _ParquetWriter(partial_path) if fmt == "parquet" else _JsonlGzWriter(partial_path)
    written = 0
    pending: list[dict] = []
    try:
        for bucket in iter_day_records(result, groups):
            pending.extend(bucket)
            if len(pending) >= WRITE_BATCH_ROWS:
                writer.write(pending)
                written += len(pending)
                pending = []
        if pending or (fmt == "parquet" and written == 0):
            writer.write(pending)
            written += len(pending)
            pending = []
    finally:
        writer.close()

    readback: Counter = Counter("|".join(key) for key in read_back(partial_path))
    os.replace(long_path(partial_path), long_path(table_path))
    expected = Counter({key: count for key, count in result.expected_by_fetch.items() if count})
    disposition_total = sum(
        count for name, count in result.dispositions.items()
        if name in {"unparseable_row", "row_date_refused", "no_market_local_blob_ref",
                    "no_fetch_time", "fetch_first_row", "fetch_repeat_row"}
        or name.startswith("unsupported_source:")
    )
    accounted_fetch_rows = sum(
        count for name, count in result.dispositions.items()
        if name in {"extracted_rows", "missing_blob_rows", "hash_mismatch_rows", "parse_error_rows"}
    )
    fetch_rows = result.dispositions["fetch_first_row"] + result.dispositions["fetch_repeat_row"]
    checks = {
        "every_manifest_row_has_one_disposition": disposition_total == result.manifest_rows,
        "every_fetch_row_resolved": accounted_fetch_rows == fetch_rows,
        "pit_rows_written_equal_expected": sum(readback.values()) == sum(expected.values()) == written,
        "pit_rows_per_fetch_equal_expected": readback == expected,
        "no_unreadable_fetch_rows": accounted_fetch_rows == result.dispositions["extracted_rows"],
    }
    return {
        "receipt": DAY_RECEIPT_NAME,
        "receipt_revision": RECEIPT_REVISION,
        "pit_table": PIT_TABLE_NAME,
        "pit_table_revision": PIT_TABLE_REVISION,
        "target_date": day,
        "events": sorted(set(result.events)),
        "event_dirs": len(result.events),
        "manifest_files": dict(result.manifest_files),
        "manifest_rows": result.manifest_rows,
        "dispositions": dict(sorted(result.dispositions.items())),
        "manifest_rows_extracted": result.dispositions["extracted_rows"],
        "distinct_fetches_extracted": len(result.expected_by_fetch),
        "fetches_by_source": dict(sorted(result.fetches_by_source.items())),
        "pit_rows_by_source": dict(sorted(result.rows_by_source.items())),
        "pit_rows_expected": sum(expected.values()),
        "pit_rows_readback": sum(readback.values()),
        "null_or_non_numeric_cells_skipped": result.null_cells_skipped,
        "open_meteo_served_fields_seen": sorted(result.open_meteo_fields_seen),
        "open_meteo_served_fields_missing": sorted(set(OPEN_METEO_SERVED_FIELDS) - result.open_meteo_fields_seen)
        if result.fetches_by_source.get("open_meteo") else [],
        "earlier_attempt_files_set_aside": orphans,
        "checks": checks,
        "match": all(checks.values()),
        "output": {
            "path": str(table_path),
            "format": fmt,
            "bytes": os.path.getsize(long_path(table_path)),
            "sha256": _sha256_file(table_path),
        },
    }

# -------------------------------------------------------------------- run


def run(
    roots: list[Path], out_dir: Path, *, max_date: date, min_date: date | None = None,
    fmt: str = "auto", deadline: datetime | None = None, max_days: int | None = None,
    now=None,
) -> dict:
    check_request(max_date, min_date)
    out_dir = check_out_dir(out_dir, roots)
    if fmt == "auto":
        fmt = "parquet" if parquet_available() else "jsonl_gz"
    if fmt == "parquet" and not parquet_available():
        raise ExtractionRefused("refused: --format parquet but pyarrow is not importable")
    clock = now or (lambda: datetime.now(timezone.utc))
    started = clock()
    os.makedirs(long_path(out_dir / "receipts"), exist_ok=True)
    by_day, event_skips = discover_events(roots, max_date, min_date)
    days = sorted(by_day, reverse=True)
    module_sha = _sha256_file(Path(__file__))
    summaries = []
    stopped_reason = None
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    extracted = 0
    for day in days:
        receipt_path = out_dir / "receipts" / f"{day.isoformat()}.json"
        if os.path.exists(long_path(receipt_path)):
            # Resumable across runs: --max-days counts only days extracted now.
            summaries.append({"target_date": day.isoformat(), "status": "already_extracted"})
            continue
        if max_days is not None and extracted >= max_days:
            stopped_reason = "max_days"
            break
        if deadline is not None and clock() >= deadline:
            stopped_reason = "deadline"
            break
        day_started = clock()
        receipt = extract_and_write_day(out_dir, by_day[day], max_date, min_date, fmt, stamp=stamp)
        extracted += 1
        receipt["code"] = {"module": __name__, "module_sha256": module_sha}
        receipt["started_at"] = utc_iso_precise(day_started)
        receipt["finished_at"] = utc_iso_precise(clock())
        _write_json(receipt_path, receipt)
        summaries.append({
            "target_date": receipt["target_date"],
            "status": "extracted",
            "match": receipt["match"],
            "manifest_rows": receipt["manifest_rows"],
            "manifest_rows_extracted": receipt["manifest_rows_extracted"],
            "pit_rows": receipt["pit_rows_readback"],
            "bytes": receipt["output"]["bytes"],
        })
    run_receipt = {
        "receipt": RUN_RECEIPT_NAME,
        "receipt_revision": RECEIPT_REVISION,
        "roots": [str(root) for root in roots],
        "max_date": max_date.isoformat(),
        "min_date": min_date.isoformat() if min_date else None,
        "embargo": [EMBARGO_FIRST.isoformat(), EMBARGO_LAST.isoformat()],
        "format": fmt,
        "event_skips": dict(event_skips),
        "days_available": len(by_day),
        "days": summaries,
        "days_extracted": extracted,
        "days_remaining": sum(
            1 for day in days if not os.path.exists(long_path(out_dir / "receipts" / f"{day.isoformat()}.json"))),
        "all_match": all(row.get("match", True) for row in summaries),
        "stopped_reason": stopped_reason,
        "started_at": utc_iso_precise(started),
        "finished_at": utc_iso_precise(clock()),
        "code": {"module": __name__, "module_sha256": module_sha},
    }
    _write_json(out_dir / f"run_receipt_{stamp}.json", run_receipt)
    return run_receipt


def _parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = parse_timestamp(value)
    if moment is None:
        raise argparse.ArgumentTypeError("--deadline must be an ISO time with an offset")
    return moment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshots-root", action="append", type=Path, default=None,
                        help="Event-folder root(s) to read; default data/snapshots. Repeatable.")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Output root outside the runtime data tree.")
    parser.add_argument("--max-date", type=date.fromisoformat, required=True,
                        help="Last local target date to extract (must be before the embargo).")
    parser.add_argument("--min-date", type=date.fromisoformat, default=None)
    parser.add_argument("--format", choices=("auto", "parquet", "jsonl_gz"), default="auto")
    parser.add_argument("--deadline", default=None,
                        help="ISO time with offset; no new day starts at or after it.")
    parser.add_argument("--max-days", type=int, default=None,
                        help="Extract at most N new days this run (days with a receipt are skipped and not counted).")
    args = parser.parse_args(argv)
    roots = args.snapshots_root or [data_path("snapshots")]
    try:
        receipt = run(
            roots, args.out_dir, max_date=args.max_date, min_date=args.min_date,
            fmt=args.format, deadline=_parse_deadline(args.deadline), max_days=args.max_days,
        )
    except ExtractionRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({key: receipt[key] for key in (
        "days_available", "days_extracted", "days_remaining", "all_match", "stopped_reason", "format")},
        sort_keys=True))
    return 0 if receipt["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
