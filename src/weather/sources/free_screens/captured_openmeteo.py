"""Per-model Open-Meteo day highs from captured replay inputs (screen F4): extract, no download.

Reads the workstation's checksum-verified copy of captured serving inputs
(``data/inbox/replay-inputs-le0929/snapshots/<event>/replay_inputs.jsonl``, target dates <= 2026-09-29)
and keeps, per snapshot, each captured model's ``day_model_highs`` value (native unit) from
``open_meteo_multimodel`` and ``open_meteo_global_models``, plus the GFS-ensemble (``global_ensemble``)
day mean high. These were fetched by production at ``captured_at_utc``, so they are point in time.

Lines are large (~0.4 MB); only the needed fragments are located and parsed, never the whole record.
Output: ``<root>/captured_openmeteo/members.parquet`` + ``manifest.json`` (input SHA256SUMS hash).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from weather.paths import data_path
from weather.sources.free_screens import common

SOURCE = "captured_openmeteo"
SCHEMA = "free_screens_captured_openmeteo/1"
DEFAULT_INBOX = data_path("inbox", "replay-inputs-le0929")
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
SNAP_RE = re.compile(r'"snapshot_id":\s*"([^"]+)"')
HIGHS_RE = re.compile(r'"day_model_highs":\s*(\{[^{}]*\})')
ENS_RE = re.compile(r'"day_max_native":\s*(-?[0-9.]+|null)')


def market_of_slug():
    from weather.market.market_registry import REGISTRY

    return {s.slug_prefix: s.id for s in REGISTRY.values()}


def parse_event(folder):
    """'highest-temperature-in-atlanta-on-august-1-2026' -> ('atlanta', '2026-08-01')."""
    prefixes = market_of_slug()
    for prefix, market in prefixes.items():
        if folder.startswith(prefix + "-"):
            month, day, year = folder[len(prefix) + 1:].split("-")
            return market, f"{int(year):04d}-{MONTHS[month]:02d}-{int(day):02d}"
    return None, None


def _section(line, key, stop_keys):
    start = line.find(f'"{key}":')
    if start < 0:
        return ""
    ends = [p for p in (line.find(f'"{k}":', start + 1) for k in stop_keys) if p > start]
    return line[start:min(ends) if ends else len(line)]


SOURCE_KEYS = ("global_ensemble", "local_history", "metar", "mrms_precip", "nbm_probabilistic_tmax", "nws_grid",
               "nws_hourly", "open_meteo", "open_meteo_air_quality", "open_meteo_global_models",
               "open_meteo_multimodel", "station_observations", "weather_forecast", "wu_current", "wu_history")


def parse_line(line):
    srcpos = line.find('"sources":')
    m = None
    for m in SNAP_RE.finditer(line, 0, srcpos if srcpos > 0 else len(line)):
        pass
    if m is None or srcpos < 0:
        return None
    out = {"snapshot_id": m.group(1)}
    body = line[srcpos:]
    others = [k for k in SOURCE_KEYS]
    for key in ("open_meteo_multimodel", "open_meteo_global_models"):
        sec = _section(body, key, [k for k in others if k != key])
        h = HIGHS_RE.search(sec)
        if h:
            for model, value in json.loads(h.group(1)).items():
                out[model] = value
    sec = _section(body, "global_ensemble", [k for k in others if k != "global_ensemble"])
    e = ENS_RE.search(sec)
    out["gefs_mean"] = None if not e or e.group(1) == "null" else float(e.group(1))
    return out


def extract(inbox=DEFAULT_INBOX, root=common.DEFAULT_ROOT, log=print):
    inbox, out_dir = Path(inbox), Path(root) / SOURCE
    sums = inbox / "SHA256SUMS"
    sums_sha = common.sha256_bytes(sums.read_bytes()) if sums.is_file() else None
    manifest_path = out_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        target = out_dir / manifest["file"]
        if manifest.get("inbox_sha256sums") == sums_sha and target.is_file() and \
                common.sha256_bytes(target.read_bytes()) == manifest["sha256"]:
            return target, manifest
    rows, folders = [], sorted(p for p in (inbox / "snapshots").iterdir() if p.is_dir())
    for n, folder in enumerate(folders, 1):
        market, target_date = parse_event(folder.name)
        if market is None:
            continue
        if target_date > common.DEV_LAST.isoformat():
            raise ValueError(f"refused: {folder.name} is after 2026-09-29")
        path = folder / "replay_inputs.jsonl"
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                row = parse_line(line)
                if row:
                    row.update(market=market, target_date=target_date)
                    rows.append(row)
        if n % 50 == 0:
            log(f"[{n}/{len(folders)}] {len(rows)} snapshots")
    frame = pd.DataFrame(rows)
    frame["row_key"] = frame.market + "|" + frame.snapshot_id
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "members.parquet"
    frame.to_parquet(target, index=False)
    manifest = {"schema": SCHEMA, "file": target.name, "sha256": common.sha256_bytes(target.read_bytes()),
                "rows": int(len(frame)), "inbox": str(inbox), "inbox_sha256sums": sums_sha,
                "members": sorted(c for c in frame.columns if c not in ("snapshot_id", "market", "target_date",
                                                                        "row_key")),
                "fill": {c: float(frame[c].notna().mean()) for c in frame.columns
                         if c not in ("snapshot_id", "market", "target_date", "row_key")},
                "built": datetime.now().isoformat(timespec="seconds")}
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return target, manifest
