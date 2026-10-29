"""R-ODC PROXY feature source (DEV_WINDOW_LEDGER row 70): low_so_far and dewpoint_c from the IEM ASOS archive.

Opt-in only (``cool_season_audit rodc-gate2 --feature-source iem-proxy``). It swaps the VALUES of the two G2
columns in the maps ``rodc_gate2.load_low_map`` / ``load_dew_map`` return and keeps every key and every
high_so_far, so G2's checks (running minimum, high_so_far assertion, bounds, join coverage) run unchanged.

Archive adapter (pinned in row 70 before any run):

* rows: ``<metar_root>/<icao>/hourly/year=Y/month=MM/observations.jsonl``, every archived row;
* instant: ``valid_time_local`` (ISO with offset). A row is in the window iff its local date == D and its local
  minute of day <= h*60. There is NO late-report or capture rule (the archive has no arrival time);
* low_so_far = wu_whole_f(min of the finite ``temp_native`` in the window, half_up); none -> NaN;
* dewpoint_c = wu_whole_f(``dewpoint_native`` of the latest window row, half_up), ties last in file order;
  no window row, or no finite dewpoint on it -> NaN.

Dev dates only: any key outside Oct-Dec 2021-25 refuses.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from weather.model.mg_serve_core import wu_whole_f

FEATURE_SOURCES = ("records", "iem-proxy")
STATIONS = {"atlanta": "katl", "austin": "kaus", "chicago": "kord", "dallas": "kdal", "denver": "kbkf",
            "houston": "khou", "los-angeles": "klax", "miami": "kmia", "nyc": "klga", "san-francisco": "ksfo",
            "seattle": "ksea"}
NAN = float("nan")


class IemProxyError(RuntimeError):
    pass


def default_metar_root(research_root):
    """The archive beside the research root (``<data>/research`` -> ``<data>/metar``)."""
    return Path(research_root).parent / "metar"


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _dev_day(day):
    day = str(day)[:10]
    if not ("2021-01-01" <= day <= "2025-12-31" and int(day[5:7]) in (10, 11, 12)):
        raise IemProxyError(f"date outside the Oct-Dec 2021-25 dev window: {day}")
    return day


class Archive:
    def __init__(self, metar_root):
        self.root = Path(metar_root)
        self._months = {}
        self.files = {}

    def rows(self, market, day):
        """[(minute_of_day, file_index, temp, dewpoint)] on local date ``day``, sorted by minute then file order."""
        if market not in STATIONS:
            raise IemProxyError(f"no archive station for {market}")
        key = (market, day[:4], day[5:7])
        if key not in self._months:
            path = self.root / STATIONS[market] / "hourly" / f"year={key[1]}" / f"month={key[2]}" / "observations.jsonl"
            by = defaultdict(list)
            if path.exists():
                raw = path.read_bytes()
                self.files[str(path.relative_to(self.root)).replace("\\", "/")] = hashlib.sha256(raw).hexdigest()
                for i, line in enumerate(raw.decode("utf-8").splitlines()):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    t = datetime.fromisoformat(str(row["valid_time_local"]))
                    by[t.date().isoformat()].append((t.hour * 60 + t.minute, i, _finite(row.get("temp_native")),
                                                     _finite(row.get("dewpoint_native"))))
            for v in by.values():
                v.sort()
            self._months[key] = by
        return self._months[key].get(day, [])

    def features(self, market, day, hour):
        """(low_so_far, dewpoint_c) for (market, D, h), NaN where missing."""
        day = _dev_day(day)
        window = [r for r in self.rows(market, day) if r[0] <= int(hour) * 60]
        temps = [r[2] for r in window if r[2] is not None]
        low = wu_whole_f(min(temps), "half_up") if temps else None
        dew = wu_whole_f(window[-1][3], "half_up") if window and window[-1][3] is not None else None
        return (NAN if low is None else float(low)), (NAN if dew is None else float(dew))


def _same(a, b):
    return a == b or (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b))


def swap_maps(low_map, dew_map, archive):
    """New (low_map, dew_map) with only the low_so_far / dewpoint_c values replaced from ``archive``; the keys and
    the high_so_far entries are kept. -> (low_map, dew_map, stats)."""
    stats = defaultdict(int)
    low_out, dew_out = {}, {}
    for key, (low, high) in low_map.items():
        m, _c, d, h = key
        new = archive.features(m, d, h)[0]
        stats["low_n"] += 1
        stats["low_nan"] += int(math.isnan(new))
        stats["low_eq_source"] += int(_same(new, low))
        low_out[key] = (new, high)
    for key, (high, dew) in dew_map.items():
        m, _c, d, h = key
        new = archive.features(m, d, h)[1]
        dew = NAN if dew is None else dew
        stats["dew_n"] += 1
        stats["dew_nan"] += int(math.isnan(new))
        stats["dew_eq_source"] += int(_same(new, dew))
        dew_out[key] = (high, new)
    return low_out, dew_out, dict(stats)


def provenance(archive):
    lines = [f"{k} {v}" for k, v in sorted(archive.files.items())]
    return {"metar_root": str(archive.root), "files_read": len(lines),
            "files_manifest_sha256": hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest(),
            "adapter": "IEM ASOS archive; instant valid_time_local; D and <= h:00; no late-report or capture rule; "
                       "wu_whole_f half_up; low = min finite temp_native, dew = latest window row; missing -> NaN"}
