"""Build the frozen ``remaining_rise_pmf_v1`` artifact for the t3-r3 stage.

The artifact is the history table that the shadow stage
``weather.model.remaining_rise_floor`` (``remaining_rise_floor_v1``) reads at
serve time. It is built exactly as the registered t3-r3 text describes
(registry sha256 ``ae86d035...6559``; remaining-rise pre-registration draft
§1, D2 draft §5):

- source: IEM ``asos.py`` METAR in the A-IEM-1 tidy layout, one parquet per
  station (``<ICAO>.parquet``), routine reports only, COR excluded;
- ``temp_f = round_half_up(T-group C * 1.8 + 32)``, else the body integer C;
- availability ``available_utc`` (valid time + 10 minutes, A-IEM-1 basis);
- complete local days have at least 20 routine rows; the day max is the max
  ``temp_f`` over those rows;
- for each local hour H the remaining rise is ``e = day max - running max of the
  day's rows available at local H:30``;
- history local dates 2024-05-01..2026-07-31 only;
- each station x calendar month x local hour cell is the empirical integer pmf
  of e convolved with a discrete Gaussian (sd 1 F, half-width 6) with the
  negative tail folded onto 0.

The constants are fixed a priori by the registration; changing any of them is a
new artifact id, never a rebuild of this one. The builder reads no settlement,
market, panel or score data, and it refuses any input file whose ``local_date``
statistics reach the reserved window (2026-09-30 or later) without decoding it.

Run (workstation, through ``scripts/ops/workstation_heavy.ps1``)::

    python -m weather.calibration.remaining_rise_pmf --metar-dir <dir> [--out <path>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import numpy as np

from weather.artifacts import writable_artifact_path

ARTIFACT_ID = "remaining_rise_pmf_v1"
ARTIFACT_FILENAME = f"{ARTIFACT_ID}.json"
CANDIDATE_ID = "t3-r3"
REGISTRY_SHA256 = "ae86d0350391219d1f96a91e944335eec2e9216f95b0fdc58e9cda3185456559"
HIST_START = "2024-05-01"
HIST_END = "2026-07-31"
RESERVED_FROM = date(2026, 9, 30)
MIN_ROUTINE_ROWS = 20
KERNEL_SD_F = 1.0
KERNEL_HALF_WIDTH = 6
HIST_CUTOFF_MINUTE = 30
UNIT = "F"
COLUMNS = ("report_type", "is_cor", "tgroup_c", "main_temp_c", "available_utc", "local_date")

DEFINITION = {
    "source": "IEM asos.py METAR, A-IEM-1 tidy layout",
    "report_type": "routine",
    "cor": "excluded",
    "temp_f": "round_half_up(tgroup_c * 1.8 + 32), else round_half_up(main_temp_c * 1.8 + 32)",
    "availability": "available_utc = valid_utc + 10 min",
    "complete_day_min_routine_rows": MIN_ROUTINE_ROWS,
    "day_max": "max temp_f over routine rows of the station-local date",
    "remaining_rise": "day max - max temp_f of the day's rows with available_utc <= local H:30",
    "history_cutoff_minute": HIST_CUTOFF_MINUTE,
    "history_local_dates": [HIST_START, HIST_END],
    "kernel": "discrete Gaussian, sd 1.0 F, k = -6..6, normalised",
    "kernel_sd_f": KERNEL_SD_F,
    "kernel_half_width": KERNEL_HALF_WIDTH,
    "negative_rise": "folded onto 0",
    "cell": "station x calendar month x local hour",
    "pmf_support": "e = base + index, e >= 0",
}

# The 11 US stations of the t3-r3 registration (Toronto has no IEM ASOS row set).
STATION_TIMEZONES = {
    "KATL": "America/New_York",
    "KAUS": "America/Chicago",
    "KBKF": "America/Denver",
    "KDAL": "America/Chicago",
    "KHOU": "America/Chicago",
    "KLAX": "America/Los_Angeles",
    "KLGA": "America/New_York",
    "KMIA": "America/New_York",
    "KORD": "America/Chicago",
    "KSEA": "America/Los_Angeles",
    "KSFO": "America/Los_Angeles",
}


class ReservedWindowInput(ValueError):
    """An input file may hold rows on or after the reserved window start."""


def build_code_sha256() -> str:
    """SHA-256 of this module's bytes, CRLF normalised to LF."""

    return hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def discrete_gaussian(sd: float = KERNEL_SD_F, half: int = KERNEL_HALF_WIDTH) -> tuple[np.ndarray, np.ndarray]:
    k = np.arange(-half, half + 1)
    w = np.exp(-0.5 * (k / sd) ** 2)
    return k, w / w.sum()


def smooth_folded_pmf(rises: Iterable[int]) -> tuple[int, list[float]]:
    """Integer pmf of the rises, kernel-smoothed, negative tail folded onto 0.

    Returns ``(base, probabilities)`` with ``P(e = base + i) = probabilities[i]``.
    Same arithmetic as the registered t3-r3 builder (``smooth_pmf`` + fold).
    """

    values = np.asarray(list(rises), int)
    if values.size == 0:
        raise ValueError("empty cell")
    lo, hi = int(values.min()), int(values.max())
    counts = np.bincount(values - lo, minlength=hi - lo + 1).astype(float)
    k, w = discrete_gaussian()
    p = np.convolve(counts, w)
    base = lo + int(k[0])
    p = p / p.sum()
    support = base + np.arange(len(p))
    negative = support < 0
    folded = p[negative].sum()
    p = p[~negative].copy()
    base = max(base, 0)
    p[0] += folded
    return int(base), [float(value) for value in p]


def _half_up(values: np.ndarray) -> np.ndarray:
    return np.floor(np.asarray(values, float) + 0.5)


def _check_not_reserved(path: Path) -> None:
    """Refuse a file whose local_date statistics reach the reserved window, before decoding rows."""

    import pyarrow.parquet as pq

    meta = pq.ParquetFile(path).metadata
    index = meta.schema.to_arrow_schema().get_field_index("local_date")
    if index < 0:
        raise ValueError(f"{path.name}: no local_date column")
    for group in range(meta.num_row_groups):
        stats = meta.row_group(group).column(index).statistics
        if stats is None or not stats.has_min_max:
            raise ReservedWindowInput(f"{path.name}: local_date statistics missing; refusing to decode")
        if stats.max >= RESERVED_FROM:
            raise ReservedWindowInput(f"{path.name}: local_date reaches {stats.max}; refusing to decode")


def load_station_rows(path: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Routine non-COR history rows by local date: ``{local_date: (available_utc_us, temp_f)}``."""

    import pyarrow.parquet as pq

    _check_not_reserved(path)
    table = pq.read_table(path, columns=list(COLUMNS)).to_pandas()
    rows = table[(table.report_type == "routine") & (~table.is_cor.astype(bool))].copy()
    raw = np.where(rows.tgroup_c.notna(), rows.tgroup_c * 1.8 + 32, rows.main_temp_c * 1.8 + 32)
    rows["temp_f"] = _half_up(raw)
    rows = rows[np.isfinite(rows.temp_f)]
    rows["local_date"] = rows.local_date.astype(str)
    rows = rows[(rows.local_date >= HIST_START) & (rows.local_date <= HIST_END)]
    available = rows.available_utc.dt.tz_convert(None).to_numpy().astype("datetime64[us]")
    by_day: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    local_dates = rows.local_date.to_numpy()
    temps = rows.temp_f.to_numpy()
    for day in sorted(set(local_dates)):
        mask = local_dates == day
        by_day[day] = (available[mask], temps[mask])
    return by_day


def station_rises(by_day: Mapping[str, tuple[np.ndarray, np.ndarray]], tzname: str) -> tuple[dict, int]:
    """``{(month, hour): [rise, ...]}`` over complete days, and the complete-day count."""

    tz, utc = ZoneInfo(tzname), ZoneInfo("UTC")
    cells: dict[tuple[int, int], list[int]] = {}
    complete = 0
    for day, (available, temps) in by_day.items():
        if len(temps) < MIN_ROUTINE_ROWS:
            continue
        complete += 1
        day_max = temps.max()
        year, month, dom = map(int, day.split("-"))
        for hour in range(24):
            cut = datetime(year, month, dom, hour, HIST_CUTOFF_MINUTE, tzinfo=tz).astimezone(utc)
            selected = available <= np.datetime64(cut.replace(tzinfo=None), "us")
            if selected.any():
                cells.setdefault((month, hour), []).append(int(day_max - temps[selected].max()))
    return cells, complete


def build_artifact(metar_dir: Path, stations: Mapping[str, str] = STATION_TIMEZONES) -> dict:
    """The artifact document (deterministic for fixed inputs)."""

    metar_dir = Path(metar_dir)
    inputs, cells = [], {}
    for station in sorted(stations):
        path = metar_dir / f"{station}.parquet"
        by_day = load_station_rows(path)
        rises, complete = station_rises(by_day, stations[station])
        inputs.append({
            "station": station,
            "file": path.name,
            "sha256": sha256_bytes(path.read_bytes()),
            "history_rows": int(sum(len(temps) for _, temps in by_day.values())),
            "complete_days": complete,
        })
        station_cells = {}
        for (month, hour) in sorted(rises):
            base, pmf = smooth_folded_pmf(rises[(month, hour)])
            station_cells.setdefault(str(month), {})[str(hour)] = {
                "base": base,
                "n_days": len(rises[(month, hour)]),
                "pmf": pmf,
            }
        cells[station] = station_cells
    return {
        "schema_version": ARTIFACT_ID,
        "artifact_id": ARTIFACT_ID,
        "candidate": CANDIDATE_ID,
        "registry_sha256": REGISTRY_SHA256,
        "unit": UNIT,
        "definition": DEFINITION,
        "build_code_sha256": build_code_sha256(),
        "inputs": inputs,
        "cell_count": sum(len(hours) for months in cells.values() for hours in months.values()),
        "cells": cells,
    }


def canonical_bytes(document: Mapping) -> bytes:
    """Canonical serialisation: sorted keys, compact separators, one trailing LF."""

    return (json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_artifact(document: Mapping, out: Path) -> str:
    data = canonical_bytes(document)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return sha256_bytes(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--metar-dir", required=True, type=Path, help="directory of A-IEM-1 <ICAO>.parquet files")
    parser.add_argument("--out", type=Path, default=None, help="output path (default: the artifacts tree)")
    args = parser.parse_args(argv)
    out = args.out or writable_artifact_path(ARTIFACT_FILENAME)
    document = build_artifact(args.metar_dir)
    digest = write_artifact(document, out)
    print(json.dumps({"artifact": ARTIFACT_ID, "path": str(out), "sha256": digest, "cell_count": document["cell_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
