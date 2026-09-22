"""One-event-at-a-time extraction from the hash-verified closed-event export."""
from __future__ import annotations

from collections import Counter
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from weather.market.market_registry import spec_for_slug
from tools.research.missing_information.methods import Band, peak_time, validate_bands


def finite(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def make_snapshot(rows, features, settlement, spec, target_date):
    if not rows:
        raise ValueError("empty snapshot")
    first = rows[0]
    captured = datetime.fromisoformat(first["captured_at_local"])
    if captured.tzinfo is None:
        raise ValueError("capture time lacks timezone")
    local = captured.astimezone(spec.tz)
    if local.date().isoformat() != target_date:
        raise ValueError("capture_not_on_target_date")
    items = []
    for r in rows:
        lo, hi = finite(r["bin_value_c"]), finite(r.get("bin_value_hi_c"))
        if lo is None or lo != int(lo) or (hi is not None and hi != int(hi)):
            raise ValueError("noninteger band limits")
        band = Band(r["bin_kind"], int(lo), int(hi if hi is not None else lo))
        items.append((band, r))
    items.sort(key=lambda pair: pair[0].edges)
    bands = [b for b, _ in items]
    validate_bands(bands)
    p_model = [finite(r.get("model_probability")) for _, r in items]
    p_market = [finite(r.get("market_yes")) for _, r in items]
    if any(v is None or v < 0 or v > 1 for v in p_model + p_market):
        raise ValueError("missing_or_invalid_probability")
    if abs(sum(p_model) - 1) > .005:
        raise ValueError("model_probability_mass_invalid")
    if sum(p_market) <= 0:
        raise ValueError("market_zero_probability_mass")
    bucket = int(settlement["settlement_bucket"])
    winners = [i for i, b in enumerate(bands) if b.contains(bucket)]
    if len(winners) != 1:
        raise ValueError("winner_not_unique")
    s = {
        "snapshot_id": first["snapshot_id"], "market": spec.id, "date": target_date,
        "captured_at_local": local.isoformat(), "captured_at_utc": captured.astimezone(timezone.utc).isoformat(),
        "hour": local.hour, "decimal_hour": local.hour + local.minute / 60 + local.second / 3600,
        "stratum": "before_20260823" if target_date < "2026-08-23" else "from_20260823",
        "unit": spec.unit, "station": spec.icao, "coastal": spec.coastal,
        "bands": [asdict(b) for b in bands], "labels": [r["range_label"] for _, r in items],
        "p_model": p_model, "p_market": p_market, "winner": winners[0],
        "tokens": [r.get("clob_yes_token_id") for _, r in items],
        "settlement_high": float(settlement["settlement_high"]), "settlement_bucket": bucket,
        "model_version": first.get("model_version"),
        "station_source": first.get("station_observation_source"),
        "station_id": first.get("station_observation_station_id"),
        "features": {k: finite(v) for k, v in features.items() if finite(v) is not None},
    }
    for name in ("station_current_c", "station_max_since_7am_c", "nws_forecast_max_c",
                 "open_meteo_max_c", "forecast_disagreement"):
        s[name] = finite(first.get(name))
    return s


def extract_event(folder):
    settlement = json.loads((folder / "settlement.json").read_text(encoding="utf-8-sig"))
    spec = spec_for_slug(folder.name)
    if spec is None:
        return [], {"folder": folder.name, "reason": "unknown_market"}
    date = settlement.get("target_date")
    if not isinstance(date, str) or not "2026-08-01" <= date <= "2026-09-19":
        return [], {"folder": folder.name, "reason": "target_outside_scope", "date": date}
    if settlement.get("promotion_countable") is not True:
        return [], {"folder": folder.name, "reason": "not_promotion_countable", "date": date,
                    "market": spec.id, "quality_grade": settlement.get("quality_grade")}
    if settlement.get("settlement_unit", settlement.get("unit", spec.unit)) != spec.unit:
        raise ValueError(f"settlement unit mismatch: {folder.name}")
    features = {}
    feature_file = folder / "features_long.csv"
    if feature_file.exists():
        for row in read_csv(feature_file):
            sid = row["snapshot_id"]
            if sid in features and features[sid] != row:
                raise ValueError(f"conflicting feature snapshot: {folder.name}/{sid}")
            features[sid] = row
    groups = {}
    for row in read_csv(folder / "snapshots_long.csv"):
        groups.setdefault(row["snapshot_id"], []).append(row)
    snapshots, exclusions = [], Counter()
    for sid, rows in groups.items():
        try:
            snapshots.append(make_snapshot(rows, features.get(sid, {}), settlement, spec, date))
        except ValueError as exc:
            exclusions[str(exc)] += 1
    snapshots.sort(key=lambda r: r["captured_at_utc"])
    times = [datetime.fromisoformat(s["captured_at_local"]) for s in snapshots]
    maxima = [s["station_max_since_7am_c"] for s in snapshots]
    peak = peak_time(times, maxima)
    envelope_peak = peak_time(times, maxima, envelope=True)
    for s, time in zip(snapshots, times):
        s["hours_from_peak"] = (time - peak).total_seconds() / 3600 if peak else None
        s["hours_from_envelope_peak"] = (time - envelope_peak).total_seconds() / 3600 if envelope_peak else None
    audit = {"folder": folder.name, "market": spec.id, "date": date, "unit": spec.unit,
             "promotion_countable": True, "snapshots": len(snapshots),
             "excluded_snapshots": dict(exclusions), "feature_rows": len(features),
             "source_snapshot_rows": sum(map(len, groups.values())),
             "peak_time": peak.isoformat() if peak else None,
             "envelope_peak_time": envelope_peak.isoformat() if envelope_peak else None,
             "last_capture": times[-1].isoformat() if times else None,
             "max_decreases": sum(a is not None and b is not None and b < a for a, b in zip(maxima, maxima[1:])),
             "settlement": settlement}
    return snapshots, audit


def extract(root, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    output_file = output / "snapshots.jsonl"
    audits, seen = [], set()
    count = 0
    with output_file.open("x", encoding="utf-8") as stream:
        for folder in sorted(Path(root).iterdir()):
            if not folder.is_dir() or not (folder / "settlement.json").exists():
                continue
            snapshots, audit = extract_event(folder)
            key = (audit.get("market"), audit.get("date"))
            if snapshots and key in seen:
                raise ValueError("duplicate market-date folders")
            if snapshots:
                seen.add(key)
            for s in snapshots:
                stream.write(json.dumps(s, allow_nan=False, separators=(",", ":")) + "\n")
            count += len(snapshots)
            audits.append(audit)
            if len(audits) % 50 == 0:
                print(f"extracted {len(audits)} folders / {count} snapshots", flush=True)
    (output / "extraction_audit.json").write_text(json.dumps(audits, indent=2) + "\n", encoding="utf-8")
    return {"folders": len(audits), "market_days": len(seen), "snapshots": count,
            "output_sha256": sha256(output_file)}
