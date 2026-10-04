"""Point-in-time NBM v2 guidance extract for every captured US snapshot (mission 111h).

For each captured snapshot of the 11 US settlement markets on promotion-countable
market-days, emit one row: served and market band vectors, the observed floor
features at capture, the captured (parser v1) NBM features and manifest token,
NBM parser v2 percentiles for today's maximum from the newest retained national
bulletin that existed at capture time (or the v2 unavailable reason), HRRR and
NWS-grid point highs where captured, and the settled outcome.

Nothing dated after a snapshot's capture time enters its row, except the settled
outcome label, which is the scoring target. Research only: this module reads a
data root and writes one output directory. It fits nothing, changes no serving
path, and is run on production through ``scripts/ops/guidance_extract_run.ps1``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

from weather.backtesting.settlement_io import SettlementAuthorityError, resolve_market_day_label
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.reporting.research.guidance_extract_parser import PinnedParser

ROWS_SCHEMA = "guidance-extract-rows/1"
MANIFEST_SCHEMA = "guidance-extract-manifest/1"
NBM_SOURCE = "nbm_probabilistic_tmax"
STRATUM_SPLIT = "2026-08-23"
GIB = 1024 ** 3
DEFAULT_MAX_INPUT_BYTES = 160 * GIB
DEFAULT_MAX_FILE_BYTES = 4 * GIB
DEFAULT_MAX_RUNTIME_SECONDS = 7200
DEFAULT_LOOKBACK_HOURS = 24
FEATURE_NUMERIC = (
    [f"nbm_prob_tmax_p{p}" for p in (10, 25, 50, 75, 90)]
    + ["nbm_prob_tmax_mean", "nbm_prob_tmax_stddev", "nbm_prob_tmax_physical_valid_flag",
       "nbm_prob_tmax_impossible_flag", "nbm_prob_tmax_floor_gap",
       "guidance_physical_floor", "high_so_far", "trusted_current_max", "nws_grid_high",
       "open_meteo_hrrr_high_delta", "forecast_high"]
)
FEATURE_TEXT = ("guidance_impossible_features", "guidance_impossible_sources", "cutoff_hour")
V1_FIELDS = ("cycle_key", "status", "parser_version", "provider_issue_time", "provider_update_time")


class BudgetExceeded(RuntimeError):
    pass


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def iso(value):
    return value.isoformat() if value else None


def cycle_time(cycle_key):
    """``nbm-nbp:YYYYMMDDTHHZ`` -> aware UTC issue time, or None."""
    try:
        return datetime.strptime(str(cycle_key).split(":", 1)[1], "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)
    except (IndexError, ValueError):
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Budget:
    """Explicit input budget, per-file cap and wall-clock deadline."""

    def __init__(self, max_input_bytes, max_file_bytes, max_runtime_seconds):
        self.max_input_bytes = max_input_bytes
        self.max_file_bytes = max_file_bytes
        self.deadline = time.monotonic() + max_runtime_seconds
        self.bytes_by_source = Counter()
        self.files_by_source = Counter()
        self.over_cap = []

    def admit(self, path, source):
        """Charge a whole file before it is read; False if it exceeds the per-file cap."""
        size = Path(path).stat().st_size
        if size > self.max_file_bytes:
            self.over_cap.append({"path": str(path), "source": source, "bytes": size})
            return False
        self.check_time()
        if sum(self.bytes_by_source.values()) + size > self.max_input_bytes:
            raise BudgetExceeded(f"input budget {self.max_input_bytes} bytes exhausted at {path}")
        self.bytes_by_source[source] += size
        self.files_by_source[source] += 1
        return True

    def check_time(self):
        if time.monotonic() > self.deadline:
            raise BudgetExceeded("runtime deadline exceeded")


def existing(folder, name):
    """A family file, or its gzip sibling when a tiering step compressed it."""
    for candidate in (folder / name, folder / (name + ".gz")):
        if candidate.is_file():
            return candidate
    return None


def open_text(path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open(encoding="utf-8-sig", newline="")


def read_csv(path):
    with open_text(path) as stream:
        yield from csv.DictReader(stream)


def read_jsonl(path):
    with open_text(path) as stream:
        for line in stream:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    yield {"_unparseable": True}


def us_folders(data_root, first, last):
    """Yield (folder, spec, target_date) for US market folders in [first, last]."""
    root = Path(data_root) / "snapshots"
    for folder in sorted(root.iterdir()) if root.is_dir() else ():
        if not folder.is_dir():
            continue
        spec = spec_for_slug(folder.name)
        target = date_from_event_slug(folder.name)
        if spec is None or target is None or spec.display_unit != "F":
            continue
        if first <= target <= last:
            yield folder, spec, target


def manifest_rows(folder, budget):
    path = existing(folder, "forecast_payloads.jsonl")
    if path is not None:
        return (read_jsonl(path) if budget.admit(path, "forecast_payload_manifests") else iter(())), path
    path = existing(folder, "forecast_payloads_long.csv")
    if path is not None:
        return (read_csv(path) if budget.admit(path, "forecast_payload_manifests") else iter(())), path
    return iter(()), None


def availability(row):
    """When the bulletin bytes were first on our host, and the field used."""
    for field in ("response_received_at", "fetched_at", "first_seen_at", "captured_at_utc"):
        value = parse_time(row.get(field))
        if value is not None:
            return value, field
    return None, None


def build_bulletin_index(data_root, first, last, budget):
    """National bulletins seen in any US manifest, plus each snapshot's v1 NBM row."""
    bulletins, v1_rows = {}, {}
    for folder, _spec, _target in us_folders(data_root, first - timedelta(days=1), last + timedelta(days=1)):
        rows, _ = manifest_rows(folder, budget)
        for row in rows:
            if row.get("source") != NBM_SOURCE:
                continue
            v1_rows[(folder.name, row.get("snapshot_id"))] = {k: row.get(k) for k in V1_FIELDS}
            digest = str(row.get("payload_hash") or "")
            if not digest or not row.get("payload_ref") or row.get("payload_storage_scope") != "shared_market_invariant":
                continue
            seen, basis = availability(row)
            entry = bulletins.setdefault(digest, {
                "payload_hash": digest, "payload_ref": row["payload_ref"],
                "cycle_key": row.get("cycle_key"), "issue": cycle_time(row.get("cycle_key")),
                "available_at": seen, "available_basis": basis,
                "manifest_rows": 0})
            entry["manifest_rows"] += 1
            if seen is not None and (entry["available_at"] is None or seen < entry["available_at"]):
                entry["available_at"], entry["available_basis"] = seen, basis
    return bulletins, v1_rows


def parse_bulletins(bulletins, data_root, parser, stations, first, last, budget):
    """Parse each retained bulletin once for every station and nearby target date."""
    cas_root = Path(data_root) / "forecast_payload_cas"
    parsed, status = {}, Counter()
    for digest, entry in sorted(bulletins.items(), key=lambda kv: str(kv[1]["cycle_key"])):
        blob = cas_root / entry["payload_ref"]
        issue = cycle_time(entry["cycle_key"])
        if not blob.is_file():
            entry["status"] = "bytes_missing"
        elif issue is None:
            entry["status"] = "cycle_key_invalid"
        elif not budget.admit(blob, "nbp_bulletin_cas"):
            entry["status"] = "over_file_cap"
        else:
            targets = [(s, d.isoformat()) for s in stations
                       for d in (issue.date() + timedelta(days=k) for k in (-1, 0, 1)) if first <= d <= last]
            error, results = parser.parse(blob, digest, targets)
            entry["status"] = error or "parsed"
            for (station, target), result in zip(targets, results):
                parsed[(digest, station, target)] = result
        status[entry["status"]] += 1
    return parsed, dict(status)


def select_v2(bulletins, parsed, station, target, captured, lookback):
    """Newest bulletin available at capture holding today's maximum under v2."""
    candidates, skipped = [], Counter()
    for digest, entry in bulletins.items():
        issue = entry["issue"] if "issue" in entry else cycle_time(entry["cycle_key"])
        if issue is None or issue > captured or captured - issue > lookback:
            continue
        if entry["available_at"] is None or entry["available_at"] > captured:
            skipped["after_capture"] += 1
            continue
        if entry.get("status") != "parsed":
            skipped[entry.get("status") or "unparsed"] += 1
            continue
        result = parsed.get((digest, station, target))
        if result is None:
            continue
        issued = parse_time(result.get("issued_at")) or issue
        if issued > captured:
            skipped["issued_after_capture"] += 1
            continue
        candidates.append((issued, entry["available_at"], digest, entry, result))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    out = {"v2_candidates": len(candidates), "v2_skipped": dict(skipped),
           "v2_newest_cycle_key": candidates[0][3]["cycle_key"] if candidates else None,
           "v2_newest_reason": (candidates[0][4].get("reason") if candidates and not candidates[0][4].get("available")
                                else None)}
    for issued, seen, digest, entry, result in candidates:
        if result.get("available"):
            pct = result.get("percentiles") or {}
            valid = parse_time(result.get("valid_time_utc"))
            return {**out, "v2_status": "available", "v2_reason": None,
                    "v2_cycle_key": entry["cycle_key"], "v2_payload_hash": digest,
                    "v2_issued_at": iso(issued), "v2_valid_time_utc": iso(valid),
                    "v2_available_at": iso(seen), "v2_available_basis": entry["available_basis"],
                    "v2_age_hours": round((captured - issued).total_seconds() / 3600, 4),
                    "v2_forecast_hour": result.get("forecast_hour"),
                    "v2_period_kind": result.get("period_kind"),
                    **{f"v2_p{p}": finite(pct.get(str(p))) for p in (10, 25, 50, 75, 90)},
                    "v2_mean": finite(result.get("mean_native")),
                    "v2_stddev": finite(result.get("stddev_native"))}
    reason = out["v2_newest_reason"] or ("no_bulletin_available_at_capture" if not candidates else "unavailable")
    return {**out, "v2_status": "unavailable", "v2_reason": reason}


def v1_fields(row):
    """What the capture actually recorded for NBM (parser v1 on production)."""
    if not row:
        return {"v1_cycle_key": None, "v1_valid_time_utc": None, "v1_period": "no_manifest_row"}
    valid = parse_time(row.get("provider_update_time"))
    period = ("maximum" if valid and valid.hour == 0 else "minimum" if valid and valid.hour == 12
              else "unknown")
    return {"v1_cycle_key": row.get("cycle_key") or None, "v1_status": row.get("status"),
            "v1_parser_version": row.get("parser_version") or None,
            "v1_issued_at": row.get("provider_issue_time") or None,
            "v1_valid_time_utc": iso(valid), "v1_period": period}


def guidance_point(item, captured, value_fn, issue_field=None):
    """(value, issue, fetched, status) with the point-in-time rule applied."""
    if not isinstance(item, dict) or not item.get("ok"):
        return None, None, None, "not_captured"
    data = item.get("data") or {}
    if data.get("target_date_match") is False:
        return None, None, None, "target_date_mismatch"
    fetched = parse_time(data.get("fetched_at") or item.get("fetched_at"))
    issue = parse_time(data.get(issue_field)) if issue_field else None
    if (fetched and fetched > captured) or (issue and issue > captured):
        return None, None, None, "after_capture"
    value = finite(value_fn(data))
    return value, iso(issue), iso(fetched), "ok" if value is not None else "missing_value"


def point_guidance(folder, captured_by_id, budget):
    """HRRR and NWS-grid highs per snapshot from the captured replay inputs."""
    path = existing(folder, "replay_inputs.jsonl")
    if path is None:
        return {}, "replay_inputs_missing"
    if not budget.admit(path, "replay_inputs"):
        return {}, "replay_inputs_over_file_cap"
    out = {}
    for row in read_jsonl(path):
        sid = row.get("snapshot_id")
        captured = captured_by_id.get(sid)
        if captured is None:
            continue
        sources = row.get("sources") or {}
        hrrr, _, hrrr_fetched, hrrr_status = guidance_point(
            sources.get("open_meteo_multimodel"), captured,
            lambda d: (d.get("day_model_highs") or {}).get("ncep_hrrr_conus"))
        nws, nws_issue, nws_fetched, nws_status = guidance_point(
            sources.get("nws_grid"), captured, lambda d: d.get("day_max_native"), "provider_issue_time")
        nws_update = parse_time(((sources.get("nws_grid") or {}).get("data") or {}).get("provider_update_time"))
        out[sid] = {"hrrr_high": hrrr, "hrrr_issued_at": None,
                    "hrrr_issue_status": "not_exposed_by_open_meteo", "hrrr_fetched_at": hrrr_fetched,
                    "hrrr_status": hrrr_status, "nws_grid_high_raw": nws, "nws_grid_issued_at": nws_issue,
                    "nws_grid_updated_at": iso(nws_update) if nws_status == "ok" and nws_update and nws_update <= captured else None,
                    "nws_grid_fetched_at": nws_fetched, "nws_grid_status": nws_status}
    return out, "ok"


def band_vector(rows):
    """Ordered complete band support or a ValueError naming the defect."""
    items = []
    for r in rows:
        low, high = finite(r.get("bin_value_c")), finite(r.get("bin_value_hi_c"))
        kind = r.get("bin_kind")
        if low is None or low != int(low) or (high is not None and high != int(high)):
            raise ValueError("noninteger_band_limits")
        high = int(high) if high is not None else int(low)
        edges = (-math.inf if kind == "lte" else low - .5, math.inf if kind == "gte" else high + .5)
        items.append((edges, kind, int(low), high, r))
    items.sort(key=lambda item: item[0])
    if len(items) < 2 or items[0][1] != "lte" or items[-1][1] != "gte":
        raise ValueError("bands_missing_tails")
    if any(k not in {"lte", "eq", "gte"} for _, k, *_ in items):
        raise ValueError("invalid_band_kind")
    if any(a[0][1] != b[0][0] for a, b in zip(items, items[1:])):
        raise ValueError("bands_gap_or_overlap")
    return items


def contains(kind, low, high, bucket):
    return (kind == "lte" or bucket >= low) and (kind == "gte" or bucket <= high)


def snapshot_row(sid, rows, spec, target, label, features, v1_row, point, v2):
    """One extract row; raises ValueError for an inadmissible snapshot."""
    captured = parse_time(rows[0].get("captured_at_utc"))
    if captured is None:
        raise ValueError("capture_time_invalid")
    local = captured.astimezone(spec.tz)
    if local.date() != target:
        raise ValueError("capture_not_on_target_date")
    items = band_vector(rows)
    served = [finite(r.get("model_probability")) for *_, r in items]
    market = [finite(r.get("market_yes")) for *_, r in items]
    if any(v is None or not 0 <= v <= 1 for v in served + market):
        raise ValueError("missing_or_invalid_probability")
    if abs(sum(served) - 1) > .005:
        raise ValueError("served_probability_mass_invalid")
    bucket = int(finite(label.get("settlement_bucket")))
    winners = [i for i, (_, kind, low, high, _) in enumerate(items) if contains(kind, low, high, bucket)]
    if len(winners) != 1:
        raise ValueError("winner_not_unique")
    bids = [finite(r.get("best_bid")) for *_, r in items]
    asks = [finite(r.get("best_ask")) for *_, r in items]
    mids = [(b + a) / 2 if b is not None and a is not None and 0 <= b <= a <= 1 else None
            for b, a in zip(bids, asks)]
    feature_values = {k: finite(features.get(k)) for k in FEATURE_NUMERIC}
    feature_values.update({k: features.get(k) or None for k in FEATURE_TEXT})
    return {
        "schema": ROWS_SCHEMA, "snapshot_id": sid, "market": spec.id, "station": spec.icao,
        "event_slug": rows[0].get("event_slug"), "target_date": target.isoformat(),
        "stratum": "before_20260823" if target.isoformat() < STRATUM_SPLIT else "from_20260823",
        "captured_at_utc": iso(captured), "captured_at_local": local.isoformat(),
        "local_hour": local.hour, "unit": spec.display_unit, "model_version": rows[0].get("model_version"),
        "bands": [{"kind": k, "low": lo, "high": hi, "label": r.get("range_label")} for _, k, lo, hi, r in items],
        "p_served": served, "p_market_yes": market, "best_bid": bids, "best_ask": asks, "market_mid": mids,
        "winner": winners[0], "settlement_high": finite(label.get("settlement_high")),
        "settlement_bucket": bucket, "settlement_source": label.get("settlement_source"),
        "features": feature_values, "features_present": bool(features),
        **v1_fields(v1_row), **v2,
        **(point or {"hrrr_status": "no_replay_input", "nws_grid_status": "no_replay_input"}),
    }


def label_for(folder, budget):
    sidecar = folder / "settlement.json"
    if sidecar.is_file():
        budget.admit(sidecar, "settlement")
    resolved = resolve_market_day_label(folder)
    return resolved["label"], resolved["authority"]["status"]


def extract_folder(folder, spec, target, bulletins, parsed, v1_rows, lookback, budget, write):
    """Emit every admissible snapshot of one market-day; return its audit."""
    audit = {"event_slug": folder.name, "market": spec.id, "target_date": target.isoformat()}
    label, authority = label_for(folder, budget)
    audit["settlement_authority"] = authority
    if not label:
        return {**audit, "admitted": False, "reason": "no_settlement_label"}
    if label.get("promotion_countable") is not True:
        return {**audit, "admitted": False, "reason": "not_promotion_countable",
                "quality_grade": label.get("quality_grade")}
    tape = existing(folder, "snapshots_long.csv")
    if tape is None:
        return {**audit, "admitted": False, "reason": "snapshots_long_missing"}
    if not budget.admit(tape, "snapshots_long"):
        return {**audit, "admitted": False, "reason": "snapshots_long_over_file_cap"}
    groups = {}
    for row in read_csv(tape):
        groups.setdefault(row.get("snapshot_id"), []).append(row)
    features = {}
    feature_file = existing(folder, "features_long.csv")
    if feature_file is not None and budget.admit(feature_file, "features_long"):
        for row in read_csv(feature_file):
            features[row.get("snapshot_id")] = row
    captured_by_id = {sid: parse_time(rows[0].get("captured_at_utc")) for sid, rows in groups.items()}
    points, point_status = point_guidance(folder, captured_by_id, budget)
    exclusions, count, v2_status = Counter(), 0, Counter()
    for sid, rows in sorted(groups.items(), key=lambda kv: str(kv[1][0].get("captured_at_utc"))):
        captured = captured_by_id[sid]
        try:
            if captured is None:
                raise ValueError("capture_time_invalid")
            v2 = select_v2(bulletins, parsed, spec.icao, target.isoformat(), captured, lookback)
            row = snapshot_row(sid, rows, spec, target, label, features.get(sid, {}),
                               v1_rows.get((folder.name, sid)), points.get(sid), v2)
        except ValueError as exc:
            exclusions[str(exc)] += 1
            continue
        write(row)
        count += 1
        v2_status[row["v2_status"] if row["v2_status"] == "available" else row["v2_reason"]] += 1
    budget.check_time()
    return {**audit, "admitted": count > 0, "reason": None if count else "no_admissible_snapshot",
            "snapshots": count, "excluded_snapshots": dict(exclusions), "feature_rows": len(features),
            "replay_inputs": point_status, "v2_status_counts": dict(v2_status)}


def run(args):
    started = datetime.now(timezone.utc)
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"output directory {out} must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    data_root = Path(args.data_root).resolve()
    first, last = date.fromisoformat(getattr(args, "from")), date.fromisoformat(args.to)
    os.environ["SETTLEMENT_LEDGER_ROOT"] = str(data_root / "settlements")
    budget = Budget(args.max_input_bytes, args.max_file_bytes, args.max_runtime_seconds)
    lookback = timedelta(hours=args.lookback_hours)
    stations = sorted({spec.icao for _f, spec, _t in us_folders(data_root, first, last)})
    rows_path, audit_path = out / "guidance_rows.jsonl.gz", out / "market_days.jsonl.gz"
    counts, status, error = Counter(), "COMPLETE", None
    bulletins, bulletin_status = {}, {}
    with PinnedParser(args.parser_worktree, args.parser_python) as parser, \
            gzip.open(rows_path, "wt", encoding="utf-8", compresslevel=6) as rows_out, \
            gzip.open(audit_path, "wt", encoding="utf-8", compresslevel=6) as audit_out:
        def write(row):
            rows_out.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
            counts["rows"] += 1
            counts["v2_available_rows"] += row["v2_status"] == "available"
        try:
            bulletins, v1_rows = build_bulletin_index(data_root, first, last, budget)
            parsed, bulletin_status = parse_bulletins(bulletins, data_root, parser, stations, first, last, budget)
            for folder, spec, target in us_folders(data_root, first, last):
                try:
                    audit = extract_folder(folder, spec, target, bulletins, parsed, v1_rows, lookback, budget, write)
                except (SettlementAuthorityError, ValueError, OSError, csv.Error, UnicodeDecodeError) as exc:
                    # One unreadable market-day must not end a bounded run; it is recorded, never scored.
                    audit = {"event_slug": folder.name, "market": spec.id, "target_date": target.isoformat(),
                             "admitted": False, "reason": f"folder_error:{type(exc).__name__}", "detail": str(exc)[:500]}
                audit_out.write(json.dumps(audit, separators=(",", ":")) + "\n")
                counts["market_days_seen"] += 1
                counts["market_days_admitted"] += bool(audit.get("admitted"))
                counts["reason:" + str(audit.get("reason"))] += 1
        except BudgetExceeded as exc:
            status, error = "INCOMPLETE_BUDGET_EXCEEDED", str(exc)
        parser_identity = parser.identity
    outputs = {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size} for p in (rows_path, audit_path)}
    manifest = {
        "schema": MANIFEST_SCHEMA, "mission": "2026-09-111h", "status": status, "error": error,
        "started_at_utc": iso(started), "finished_at_utc": iso(datetime.now(timezone.utc)),
        "arguments": {"data_root": str(data_root), "from": first.isoformat(), "to": last.isoformat(),
                      "lookback_hours": args.lookback_hours, "max_input_bytes": args.max_input_bytes,
                      "max_file_bytes": args.max_file_bytes, "max_runtime_seconds": args.max_runtime_seconds},
        "extractor_sha256": {p.name: sha256_file(p) for p in sorted(Path(__file__).parent.glob("guidance_extract*.py"))},
        "parser": parser_identity, "stations": stations,
        "row_counts": dict(counts), "bulletins": {"distinct": len(bulletins), "status": bulletin_status},
        "bytes_read_by_source": dict(budget.bytes_by_source), "files_read_by_source": dict(budget.files_by_source),
        "bytes_read_total": sum(budget.bytes_by_source.values()), "files_over_cap": budget.over_cap,
        "outputs": outputs,
        "notes": ["Byte counts charge each whole file once when opened; settlement ledger reads by "
                  "weather.backtesting.settlement_io are not charged.",
                  "HRRR has no provider issue time: Open-Meteo does not expose the model run."],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    lines = [f"{sha256_file(out / name)}  {name}" for name in ("guidance_rows.jsonl.gz", "market_days.jsonl.gz", "manifest.json")]
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "rows": counts["rows"], "out": str(out)}), flush=True)
    return 0 if status == "COMPLETE" else 3


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.reporting.research.guidance_extract",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", required=True, help="production data directory (read only)")
    parser.add_argument("--out", required=True, help="new or empty output directory")
    parser.add_argument("--from", required=True, help="first target date, YYYY-MM-DD")
    parser.add_argument("--to", required=True, help="last target date, YYYY-MM-DD")
    parser.add_argument("--parser-worktree", required=True,
                        help="clean detached worktree of 2e17ce0eb holding parser v2")
    parser.add_argument("--parser-python", default=None, help="interpreter for the parser child")
    parser.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-runtime-seconds", type=int, default=DEFAULT_MAX_RUNTIME_SECONDS)
    return parser


def main(argv=None):
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
