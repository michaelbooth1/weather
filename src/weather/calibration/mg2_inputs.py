"""MG-2 daily input transfer, workstation side: pull, receive (verify) and build the label-free layout.

Research and shadow only (binding plan section 9; master's rulings of 2026-10-25). The import refuses
from a production package and on the dedicated capture host (through ``mg2_composite``). Nothing here
fetches over a network, reads a label, settlement or price file, or computes anything from the
D-1 METAR rows: ``prev_day/`` is hashed and schema-checked by the receiver and never opened by the
builder (pinned by ``tests/calibration/test_mg2_inputs.py``).

* ``pull``: read-only copy of ``<share>/<D>/`` into ``<inbox>/<D>/incoming/`` once the host has written
  ``manifest.json.sha256`` (its ready marker). The share is a parameter; master picks it.
* ``receive``: every section 9.3 integrity check, the section 9.2 schema check, the deadline (23:59
  workstation local on D+1) and at most two attempts (one host re-export). Outcomes go to
  ``<inbox>/<D>/verified/``, ``<inbox>/_quarantine/<D>/attempt-<n>/`` (a forbidden or unlisted name) or
  ``<inbox>/_refused/<D>/attempt-<n>/``, and one line each is appended to the receipts ledger.
* ``concat``: one window layout from per-date layouts, for ``mg2_composite emit``/``score``; it refuses a
  duplicate row key or date, mixed builder or parser identities and (with ``--ledger``) a date with no
  ``verified`` receipt for the same bundle.
* ``build``: the inputs-only layout (``inputs_snapshots.parquet``, ``inputs_bands.parquet``,
  ``manifest.json``) from a verified bundle, with v2 NBM guidance from the pinned parser and
  ``v2_parser_version`` = 2 stamped on every row.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import stat
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from weather.calibration import mg2_composite as _mg2  # refuses on the capture host
from weather.calibration import mg2_input_allowlist as allow


def _refuse_production_import():
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _mg2._PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.mg2_inputs is research-only; imported from {name}")
        frame = frame.f_back


_refuse_production_import()

LEDGER = Path(r"C:\t\mg2\forward\input_receipts.jsonl")
LAYOUT_SCHEMA = "mg2_inputs_layout/1"
RECEIPT_SCHEMA = "mg2_input_receipt/1"
MAX_ATTEMPTS = 2
MAX_PULL_BYTES = 8 * 1024 ** 3
LOOKBACK = timedelta(hours=24)
STRATUM_SPLIT = "2026-08-23"
FLOOR_FIELDS = ("guidance_physical_floor", "high_so_far", "trusted_current_max")
BLOCKS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23))
V2_COLUMNS = ("v2_candidates", "v2_newest_cycle_key", "v2_newest_reason", "v2_status", "v2_reason",
              "v2_cycle_key", "v2_payload_hash", "v2_issued_at", "v2_valid_time_utc", "v2_available_at",
              "v2_available_basis", "v2_age_hours", "v2_forecast_hour", "v2_period_kind", "v2_p10", "v2_p25",
              "v2_p50", "v2_p75", "v2_p90", "v2_mean", "v2_stddev")
NAME_CHECKS = ("no_unlisted_files", "schema")  # a failure here quarantines the bundle
TERMINAL = ("verified", "late", "missing")


class InputRefused(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_link(path):
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _walk_files(root):
    """Relative posix paths of every regular file under ``root``; refuses links and other entries."""
    root = Path(root)
    out = []
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            full = Path(current) / name
            if _is_link(full):
                raise InputRefused(f"link in bundle: {full.relative_to(root).as_posix()}")
        for name in files:
            full = Path(current) / name
            if not full.is_file():
                raise InputRefused(f"not a regular file: {full.relative_to(root).as_posix()}")
            out.append(full.relative_to(root).as_posix())
    return sorted(out)


# ----------------------------------------------------------------------------- the ledger

def read_ledger(ledger, day=None):
    path = Path(ledger)
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if day is None or r.get("target_date") == day.isoformat()]


def append_receipt(ledger, receipt):
    """Append one receipt line; the ledger is never rewritten."""
    path = Path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"schema": RECEIPT_SCHEMA, **receipt}, sort_keys=True, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return receipt


def _terminal(rows):
    for r in rows:
        if r.get("status") in TERMINAL:
            return r
    failed = [r for r in rows if r.get("attempt")]
    return failed[-1] if len(failed) >= MAX_ATTEMPTS else None


def deadline(day):
    """End of D+1 on the workstation clock (aware): 23:59 local on D+1 is the last verified minute."""
    return datetime.combine(day + timedelta(days=2), time(0)).astimezone()


# ----------------------------------------------------------------------------- pull

def pull(*, share_root, day, inbox, ledger=LEDGER, max_bytes=MAX_PULL_BYTES):
    """Copy ``<share_root>/<D>/`` read-only into ``<inbox>/<D>/incoming/``. Never writes the share."""
    src = Path(share_root) / day.isoformat()
    dest_root = Path(inbox) / day.isoformat()
    rows = read_ledger(ledger, day)
    if _terminal(rows):
        return {"status": "already_recorded", "receipt": _terminal(rows)}
    if (dest_root / "incoming").exists():
        return {"status": "already_pulled"}
    if not src.is_dir() or not (src / allow.MANIFEST_SHA).is_file():
        return {"status": "not_ready"}
    if _is_link(src):
        raise InputRefused("share date folder is a link")
    manifest_sha = (src / allow.MANIFEST_SHA).read_text(encoding="utf-8").split()[0].strip().lower()
    if any(r.get("manifest_sha256") == manifest_sha for r in rows):
        return {"status": "unchanged_since_refusal", "manifest_sha256": manifest_sha}
    files = _walk_files(src)
    total = sum((src / f).stat().st_size for f in files)
    if total > max_bytes:
        raise InputRefused(f"bundle is {total} bytes, over the {max_bytes} byte pull cap")
    staging = dest_root / ".incoming.partial"
    if staging.exists():
        shutil.rmtree(staging)
    for rel in files:
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / rel, target)
    os.replace(staging, dest_root / "incoming")
    return {"status": "pulled", "files": len(files), "bytes": total, "manifest_sha256": manifest_sha}


# ----------------------------------------------------------------------------- receive

def _jsonl(path):
    out = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                out.append(json.loads(line))
    return out


def _csv(path):
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        return header, [dict(zip(header or (), row)) for row in reader if row]


def _row_count(path, kind):
    if kind in ("snapshots_long", "features_long"):
        return len(_csv(path)[1])
    if kind == "nbm_blob":
        return None
    return len(_jsonl(path))


def verify_bundle(root, day):
    """Every section 9.3 check on a bundle directory. Returns ``(checks, manifest, manifest_sha)``.

    ``checks`` maps check name -> list of problems (names and paths only, never values).
    """
    root = Path(root)
    checks = {k: [] for k in ("manifest_sha", "files_match", "no_unlisted_files", "allowlist_sha", "schema",
                              "dates_and_cut", "markets", "blob_hashes")}
    manifest_path, sha_path = root / allow.MANIFEST, root / allow.MANIFEST_SHA
    if not manifest_path.is_file() or not sha_path.is_file():
        checks["manifest_sha"].append("manifest_missing")
        return checks, None, None
    manifest_sha = sha256_file(manifest_path)
    declared = (sha_path.read_text(encoding="utf-8").split() or [""])[0].strip().lower()
    if declared != manifest_sha:
        checks["manifest_sha"].append("manifest_sha256_mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        checks["manifest_sha"].append("manifest_unparseable")
        return checks, None, manifest_sha
    if manifest.get("schema") != allow.BUNDLE_SCHEMA or manifest.get("target_date") != day.isoformat():
        checks["manifest_sha"].append("manifest_schema_or_date")
    if manifest.get("allowlist_sha256") != allow.allowlist_sha256():
        checks["allowlist_sha"].append("allowlist_sha256_mismatch")
    cut = allow.export_cut_utc(day)
    if parse_time(manifest.get("export_cut_utc")) != cut:
        checks["dates_and_cut"].append("export_cut_mismatch")

    try:
        present = _walk_files(root)
    except InputRefused as exc:
        checks["no_unlisted_files"].append(str(exc))
        return checks, manifest, manifest_sha
    kinds = {}
    for rel in present:
        kind = allow.classify_path(rel, day)
        if kind is None:
            checks["no_unlisted_files"].append(f"unlisted_file:{rel}")
        else:
            kinds[rel] = kind
    listed = {str(f.get("path")): f for f in manifest.get("files") or [] if isinstance(f, dict)}
    for rel in kinds:
        if kinds[rel][0] != "manifest" and rel not in listed:
            checks["no_unlisted_files"].append(f"file_not_in_manifest:{rel}")
    for rel, entry in sorted(listed.items()):
        kind = kinds.get(rel)
        if kind is None:
            if allow.classify_path(rel, day) is None:
                checks["no_unlisted_files"].append(f"manifest_lists_unlisted:{rel}")
            else:
                checks["files_match"].append(f"missing:{rel}")
            continue
        path = root / rel
        if sha256_file(path) != entry.get("sha256") or path.stat().st_size != entry.get("bytes"):
            checks["files_match"].append(f"hash_or_bytes:{rel}")
            continue
        try:
            rows = _row_count(path, kind[0])
        except (ValueError, UnicodeDecodeError, csv.Error):
            checks["schema"].append(f"unparseable:{rel}")
            continue
        if rows != entry.get("rows"):
            checks["files_match"].append(f"rows:{rel}")

    referenced, markets = {}, set()
    unparseable = {p.split(":", 1)[1] for p in checks["schema"] if p.startswith("unparseable:")}
    for rel, (kind, market, folder_date) in sorted(kinds.items()):
        if kind in ("manifest", "nbm_blob") or rel in unparseable:
            continue
        path = root / rel
        slug = rel.split("/")[1]
        try:
            if kind in ("snapshots_long", "features_long"):
                header, records = _csv(path)
                if header != list(allow.CSV_FIELDS[path.name]):
                    checks["schema"].append(f"header:{rel}")
                    continue
            else:
                records = _jsonl(path)
        except (ValueError, UnicodeDecodeError, csv.Error):
            checks["schema"].append(f"unparseable:{rel}")
            continue
        if kind == "replay_inputs":
            markets.add(market)
        for i, record in enumerate(records):
            if not isinstance(record, dict):
                checks["schema"].append(f"not_an_object:{rel}[{i}]")
                continue
            if kind == "replay_inputs":
                problems = allow.replay_record_problems(record)
            elif kind == "prev_day_metar":
                problems = allow.prev_day_record_problems(record)
            elif kind == "nbm_manifest":
                problems = allow.nbm_row_problems(record)
            else:
                problems = [f"forbidden:{k}" for k in record if allow.forbidden(k)]
            checks["schema"].extend(f"{p}@{rel}[{i}]" for p in problems)
            if record.get("event_slug") != slug:
                checks["dates_and_cut"].append(f"event_slug:{rel}[{i}]")
            if "target_date" in record and str(record.get("target_date"))[:10] != folder_date.isoformat():
                checks["dates_and_cut"].append(f"target_date:{rel}[{i}]")
            captured = parse_time(record.get("captured_at_utc"))
            if captured is None or captured > cut:
                checks["dates_and_cut"].append(f"captured_after_cut:{rel}[{i}]")
            if kind == "nbm_manifest" and record.get("payload_storage_scope") == allow.NBM_SCOPE:
                digest = str(record.get("payload_hash") or "")
                if record.get("payload_ref") != allow.blob_ref(digest) or not allow.BLOB_RE.match(
                        str(record.get("payload_ref"))):
                    checks["schema"].append(f"payload_ref:{rel}[{i}]")
                else:
                    referenced[record["payload_ref"]] = digest
    missing = sorted(set(allow.MARKETS) - markets)
    checks["markets"].extend(f"market_missing:{m}" for m in missing)
    for rel, (kind, _m, _d) in sorted(kinds.items()):
        if kind != "nbm_blob":
            continue
        ref = rel.split("/", 1)[1]
        if ref not in referenced:
            checks["no_unlisted_files"].append(f"unreferenced_blob:{rel}")
        elif sha256_file(root / rel) != referenced[ref]:
            checks["blob_hashes"].append(f"blob_hash:{rel}")
    return checks, manifest, manifest_sha


def _now(now):
    if now is None:
        return datetime.now().astimezone()
    value = datetime.fromisoformat(str(now)) if not isinstance(now, datetime) else now
    return value if value.tzinfo else value.astimezone()


def receive(*, inbox, day, ledger=LEDGER, now=None):
    """Verify ``<inbox>/<D>/incoming/`` and record the outcome in the append-only receipts ledger."""
    inbox, now = Path(inbox), _now(now)
    base = inbox / day.isoformat()
    incoming, verified = base / "incoming", base / "verified"
    rows = read_ledger(ledger, day)
    done = _terminal(rows)
    if done:
        return {"status": "already_recorded", "receipt": done}
    receipt = {"target_date": day.isoformat(), "recorded_at": now.isoformat(),
               "deadline": deadline(day).isoformat(), "allowlist_sha256": allow.allowlist_sha256()}
    if now >= deadline(day):
        status = "late" if incoming.exists() else "missing"
        return append_receipt(ledger, {**receipt, "status": status, "reason": status})
    if not (incoming / allow.MANIFEST_SHA).is_file():
        return {"status": "not_ready", "target_date": day.isoformat()}
    attempt = 1 + sum(1 for r in rows if r.get("attempt"))
    checks, _manifest, manifest_sha = verify_bundle(incoming, day)
    failed = [k for k, v in checks.items() if v]  # in section 9.3 order
    summary = {k: {"pass": not v, "problems": v[:50], "problem_count": len(v)} for k, v in checks.items()}
    receipt.update(manifest_sha256=manifest_sha, checks=summary, attempt=attempt)
    if not failed:
        os.replace(incoming, verified)
        receipt.pop("attempt")
        return append_receipt(ledger, {**receipt, "status": "verified", "reason": None,
                                       "path": str(verified)})
    quarantine = any(k in NAME_CHECKS for k in failed)
    target = inbox / ("_quarantine" if quarantine else "_refused") / day.isoformat() / f"attempt-{attempt}"
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(incoming, target)
    if quarantine:
        return append_receipt(ledger, {**receipt, "status": "quarantined", "reason": "forbidden_field",
                                       "path": str(target)})
    return append_receipt(ledger, {**receipt, "status": f"refused:{failed[0]}", "reason": ",".join(failed),
                                   "path": str(target)})


# ----------------------------------------------------------------------------- build (label-free layout)

def cycle_time(cycle_key):
    try:
        return datetime.strptime(str(cycle_key).split(":", 1)[1], "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)
    except (IndexError, ValueError):
        return None


def availability(row):
    for field in ("response_received_at", "fetched_at", "first_seen_at", "captured_at_utc"):
        value = parse_time(row.get(field))
        if value is not None:
            return value, field
    return None, None


def bulletin_index(bundle):
    """National NBM bulletins named by the bundle's NBM manifest rows (``guidance_extract`` semantics)."""
    bulletins = {}
    for path in sorted(Path(bundle, "snapshots").glob("*/forecast_payloads.jsonl")):
        for row in _jsonl(path):
            if row.get("source") != allow.NBM_SOURCE:
                continue
            digest = str(row.get("payload_hash") or "")
            if not digest or not row.get("payload_ref") or row.get("payload_storage_scope") != allow.NBM_SCOPE:
                continue
            seen, basis = availability(row)
            entry = bulletins.setdefault(digest, {
                "payload_hash": digest, "payload_ref": row["payload_ref"], "cycle_key": row.get("cycle_key"),
                "issue": cycle_time(row.get("cycle_key")), "available_at": seen, "available_basis": basis,
                "manifest_rows": 0})
            entry["manifest_rows"] += 1
            if seen is not None and (entry["available_at"] is None or seen < entry["available_at"]):
                entry["available_at"], entry["available_basis"] = seen, basis
    return bulletins


def parse_bulletins(bulletins, bundle, parser, stations, day):
    cas = Path(bundle) / "forecast_payload_cas"
    parsed, status = {}, Counter()
    for digest, entry in sorted(bulletins.items(), key=lambda kv: str(kv[1]["cycle_key"])):
        blob = cas / entry["payload_ref"]
        if not blob.is_file():
            entry["status"] = "bytes_missing"
        elif entry["issue"] is None:
            entry["status"] = "cycle_key_invalid"
        else:
            targets = [(s, day.isoformat()) for s in stations
                       if day in {entry["issue"].date() + timedelta(days=k) for k in (-1, 0, 1)}]
            error, results = parser.parse(blob, digest, targets) if targets else (None, [])
            entry["status"] = error or "parsed"
            for (station, target), result in zip(targets, results):
                parsed[(digest, station, target)] = result
        status[entry["status"]] += 1
    return parsed, dict(status)


def select_v2(bulletins, parsed, station, target, captured, lookback=LOOKBACK):
    """Newest bulletin available at capture holding today's maximum (``guidance_extract.select_v2``)."""
    candidates, skipped = [], Counter()
    for digest, entry in bulletins.items():
        issue = entry["issue"]
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


def band_vector(rows):
    """Ordered complete band support or a ValueError naming the defect (``guidance_extract.band_vector``)."""
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


def block_of(hour):
    for name, lo, hi in BLOCKS:
        if lo <= hour <= hi:
            return name
    return None


def _floor(features):
    values = [finite(features.get(k)) for k in FLOOR_FIELDS]
    values = [v for v in values if v is not None]
    return max(values) if values else None


def snapshot_rows(sid, rows, spec, target, features, v2, parser_meta):
    """One label-free snapshot row plus its band rows; raises ValueError for an inadmissible snapshot."""
    captured = parse_time(rows[0].get("captured_at_utc"))
    if captured is None:
        raise ValueError("capture_time_invalid")
    local = captured.astimezone(spec.tz)
    if local.date() != target:
        raise ValueError("capture_not_on_target_date")
    items = band_vector(rows)
    served = [finite(r.get("model_probability")) for *_, r in items]
    if any(v is None or not 0 <= v <= 1 for v in served):
        raise ValueError("missing_or_invalid_probability")
    if abs(sum(served) - 1) > .005:
        raise ValueError("served_probability_mass_invalid")
    floor = _floor(features)
    bucket = math.floor(floor + 0.5) if floor is not None else None
    hour, day = local.hour, target.isoformat()
    row_key = f"{spec.id}|{sid}"
    stratum = "before_20260823" if day < STRATUM_SPLIT else "from_20260823"
    block = block_of(hour)
    snap = {"row_key": row_key, "snapshot_id": sid, "market": spec.id, "station": spec.icao,
            "event_slug": rows[0].get("event_slug"), "target_date": day, "date": day, "stratum": stratum,
            "captured_at_utc": iso(captured), "captured_at_local": local.isoformat(), "local_hour": hour,
            "block": block, "unit": spec.display_unit, "model_version": rows[0].get("model_version"),
            "features_present": bool(features),
            "cutoff_hour": (features.get("cutoff_hour") or None) if features else None,
            **{k: finite(features.get(k)) for k in FLOOR_FIELDS},
            "n_bands": len(items), "floor": floor, "floor_bucket": float(bucket) if bucket is not None else None,
            **{k: v2.get(k) for k in V2_COLUMNS}, **parser_meta}
    bands = [{"row_key": row_key, "band_index": i, "kind": kind, "low": lo, "high": hi, "p_served": served[i],
              "floor_impossible": bool(bucket is not None and kind != "gte" and hi < bucket),
              "date": day, "market": spec.id, "local_hour": hour, "block": block, "stratum": stratum}
             for i, (_, kind, lo, hi, _r) in enumerate(items)]
    return snap, bands


class _PinnedV2:
    """The pinned v2 parser (``guidance_extract_parser.PinnedParser``) with its declared version."""

    parser_version = 2

    def __init__(self, worktree, python=None):
        from weather.reporting.research.guidance_extract_parser import PinnedParser

        self._inner = PinnedParser(worktree, python)
        self.identity = self._inner.identity

    def parse(self, blob, sha256, targets):
        return self._inner.parse(blob, sha256, targets)

    def close(self):
        self._inner.close()


BUILD_READS = ("snapshots_long.csv", "features_long.csv", "forecast_payloads.jsonl")


def _check_bundle_files(bundle, manifest, day):
    """Re-hash exactly the files the builder reads (band tapes, features, NBM rows, blobs) against the manifest."""
    listed = {str(f["path"]): f for f in manifest.get("files") or []}
    for rel, entry in sorted(listed.items()):
        kind = allow.classify_path(rel, day)
        if kind is None or kind[0] not in ("snapshots_long", "features_long", "nbm_manifest", "nbm_blob"):
            continue
        if sha256_file(Path(bundle) / rel) != entry.get("sha256"):
            raise InputRefused(f"bundle file changed since verification: {rel}")


def build(*, bundle, out, day, parser=None, parser_worktree=None, parser_python=None):
    """The label-free layout for target date ``day`` from a verified bundle directory."""
    import pandas as pd

    from weather.market.market_registry import spec_for_id

    bundle, out = Path(bundle), Path(out)
    if bundle.name != "verified":
        raise InputRefused("build reads only a verified bundle (<inbox>/<D>/verified)")
    manifest_path = bundle / allow.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (bundle / allow.MANIFEST_SHA).read_text(encoding="utf-8").split()[0].strip().lower() != \
            sha256_file(manifest_path) or manifest.get("target_date") != day.isoformat():
        raise InputRefused("bundle manifest does not match its sha or target date")
    _check_bundle_files(bundle, manifest, day)
    if out.exists() and any(out.iterdir()):
        raise InputRefused(f"output directory {out} must be new or empty")
    owned = parser is None
    parser = parser or _PinnedV2(parser_worktree, parser_python)
    try:
        if getattr(parser, "parser_version", None) != 2:
            raise InputRefused("the layout parser must declare parser_version 2")
        identity = dict(parser.identity)
        parser_meta = {"v2_parser_version": 2, "v2_parser_module_sha256": identity.get("module_sha256")}
        specs = {m: spec_for_id(m) for m in allow.MARKETS}
        folders = []
        for m, spec in specs.items():
            folder = bundle / "snapshots" / allow.slug_for(m, day)
            if (folder / "snapshots_long.csv").is_file():
                folders.append((folder, spec))
        stations = sorted({spec.icao for _f, spec in folders})
        bulletins = bulletin_index(bundle)
        parsed, bulletin_status = parse_bulletins(bulletins, bundle, parser, stations, day)
    finally:
        if owned:
            parser.close()
    snaps, bands, exclusions = [], [], Counter()
    for folder, spec in folders:
        groups = {}
        for row in _csv(folder / "snapshots_long.csv")[1]:
            groups.setdefault(row.get("snapshot_id"), []).append(row)
        features = {}
        if (folder / "features_long.csv").is_file():
            features = {r.get("snapshot_id"): r for r in _csv(folder / "features_long.csv")[1]}
        for sid, rows in sorted(groups.items(), key=lambda kv: str(kv[1][0].get("captured_at_utc"))):
            captured = parse_time(rows[0].get("captured_at_utc"))
            try:
                if captured is None:
                    raise ValueError("capture_time_invalid")
                v2 = select_v2(bulletins, parsed, spec.icao, day.isoformat(), captured)
                snap, band_rows = snapshot_rows(sid, rows, spec, day, features.get(sid, {}), v2, parser_meta)
            except ValueError as exc:
                exclusions[f"{spec.id}:{exc}"] += 1
                continue
            snaps.append(snap)
            bands.extend(band_rows)
    out.mkdir(parents=True, exist_ok=True)
    snap_frame = pd.DataFrame(snaps, columns=_snapshot_columns())
    band_frame = pd.DataFrame(bands, columns=_band_columns())
    if not snap_frame.empty:
        snap_frame["local_hour"] = snap_frame.local_hour.astype("int64")
        snap_frame["v2_parser_version"] = snap_frame.v2_parser_version.astype("int64")
        band_frame["band_index"] = band_frame.band_index.astype("int64")
    snap_frame.to_parquet(out / "inputs_snapshots.parquet", index=False)
    band_frame.to_parquet(out / "inputs_bands.parquet", index=False)
    layout = {"schema": LAYOUT_SCHEMA, "target_date": day.isoformat(),
              "bundle_manifest_sha256": sha256_file(manifest_path),
              "allowlist_sha256": allow.allowlist_sha256(), "builder_sha256": sha256_file(__file__),
              "parser": {**identity, "parser_version": 2}, "bulletins": {"distinct": len(bulletins),
                                                                         "status": bulletin_status},
              "markets": sorted(spec.id for _f, spec in folders), "snapshots": len(snaps),
              "excluded_snapshots": dict(exclusions),
              "files": {name: {"sha256": sha256_file(out / name), "rows": rows}
                        for name, rows in (("inputs_snapshots.parquet", len(snaps)),
                                           ("inputs_bands.parquet", len(bands)))}}
    (out / "manifest.json").write_text(json.dumps(layout, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return layout


WINDOW_SCHEMA = "mg2_inputs_window/1"
LAYOUT_FILES = ("inputs_snapshots.parquet", "inputs_bands.parquet")


def _read_layout(root):
    """One per-date layout and its manifest, re-hashed against that manifest."""
    import pandas as pd

    root = Path(root)
    path = root / "manifest.json"
    if not path.is_file():
        raise InputRefused(f"layout {root} has no manifest.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != LAYOUT_SCHEMA:
        raise InputRefused(f"layout {root} is not {LAYOUT_SCHEMA}")
    for name in LAYOUT_FILES:
        entry = (manifest.get("files") or {}).get(name) or {}
        if not (root / name).is_file() or sha256_file(root / name) != entry.get("sha256"):
            raise InputRefused(f"layout {root}: {name} does not match its manifest")
    snaps = pd.read_parquet(root / "inputs_snapshots.parquet")
    bands = pd.read_parquet(root / "inputs_bands.parquet")
    day = str(manifest.get("target_date"))
    if len(snaps) != manifest.get("snapshots") or (len(snaps) and set(snaps.date.astype(str)) != {day}):
        raise InputRefused(f"layout {root}: snapshot rows do not match its target date {day}")
    return manifest, sha256_file(path), snaps, bands


def concat(*, layouts, out, ledger=None):
    """One window layout from verified per-date layouts; refuses any duplicate row key or date.

    Also refuses mixed allow-list, builder or parser identities, band rows with no snapshot, and (with
    ``ledger``) a date whose bundle has no ``verified`` receipt for the same manifest sha.
    """
    import pandas as pd

    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise InputRefused(f"output directory {out} must be new or empty")
    if not layouts:
        raise InputRefused("concat needs at least one layout")
    members, snap_frames, band_frames, seen_dates, identity = [], [], [], set(), None
    receipts = {}
    if ledger is not None:
        for r in read_ledger(ledger):
            if r.get("status") == "verified":
                receipts[(r.get("target_date"), r.get("manifest_sha256"))] = r
    for root in layouts:
        manifest, manifest_sha, snaps, bands = _read_layout(root)
        day = manifest["target_date"]
        if day in seen_dates:
            raise InputRefused(f"duplicate target date {day}")
        seen_dates.add(day)
        ident = (manifest.get("allowlist_sha256"), manifest.get("builder_sha256"),
                 (manifest.get("parser") or {}).get("module_sha256"), (manifest.get("parser") or {}).get("parser_version"))
        if identity is None:
            identity = ident
        elif ident != identity:
            raise InputRefused(f"layout {root} was built with a different allow-list, builder or parser")
        if ledger is not None and (day, manifest.get("bundle_manifest_sha256")) not in receipts:
            raise InputRefused(f"no verified receipt for {day} with bundle manifest {manifest.get('bundle_manifest_sha256')}")
        if snaps.row_key.duplicated().any():
            raise InputRefused(f"duplicate row_key inside the {day} layout")
        orphans = set(bands.row_key) - set(snaps.row_key)
        if orphans:
            raise InputRefused(f"{len(orphans)} band row keys in the {day} layout have no snapshot")
        members.append({"target_date": day, "path": str(root), "manifest_sha256": manifest_sha,
                        "bundle_manifest_sha256": manifest.get("bundle_manifest_sha256"),
                        "snapshots": int(len(snaps)), "bands": int(len(bands))})
        snap_frames.append(snaps)
        band_frames.append(bands)
    snaps = pd.concat(snap_frames, ignore_index=True)
    bands = pd.concat(band_frames, ignore_index=True)
    dup = snaps.row_key[snaps.row_key.duplicated()]
    if len(dup):
        raise InputRefused(f"{dup.nunique()} row keys appear in more than one layout")
    if bands.duplicated(["row_key", "band_index"]).any():
        raise InputRefused("duplicate (row_key, band_index) band rows")
    order = snaps.sort_values(["date", "market", "captured_at_utc", "row_key"]).index
    snaps = snaps.loc[order].reset_index(drop=True)
    bands = bands.sort_values(["date", "market", "row_key", "band_index"]).reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    snaps.to_parquet(out / "inputs_snapshots.parquet", index=False)
    bands.to_parquet(out / "inputs_bands.parquet", index=False)
    members.sort(key=lambda m: m["target_date"])
    window = {"schema": WINDOW_SCHEMA, "first": members[0]["target_date"], "last": members[-1]["target_date"],
              "dates": [m["target_date"] for m in members], "members": members,
              "allowlist_sha256": identity[0], "builder_sha256": identity[1],
              "parser": {"module_sha256": identity[2], "parser_version": identity[3]},
              "concat_sha256": sha256_file(__file__), "ledger_checked": ledger is not None,
              "files": {name: {"sha256": sha256_file(out / name), "rows": rows}
                        for name, rows in (("inputs_snapshots.parquet", len(snaps)),
                                           ("inputs_bands.parquet", len(bands)))}}
    (out / "manifest.json").write_text(json.dumps(window, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", **{k: window[k] for k in ("first", "last", "dates", "files")}}


def _snapshot_columns():
    return ["row_key", "snapshot_id", "market", "station", "event_slug", "target_date", "date", "stratum",
            "captured_at_utc", "captured_at_local", "local_hour", "block", "unit", "model_version",
            "features_present", "cutoff_hour", *FLOOR_FIELDS, "n_bands", "floor", "floor_bucket",
            *V2_COLUMNS, "v2_parser_version", "v2_parser_module_sha256"]


def _band_columns():
    return ["row_key", "band_index", "kind", "low", "high", "p_served", "floor_impossible", "date", "market",
            "local_hour", "block", "stratum"]


# ----------------------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="python -m weather.calibration.mg2_inputs", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("pull", help="read-only copy of <share>/<D>/ into <inbox>/<D>/incoming/")
    q.add_argument("--share-root", required=True)
    q.add_argument("--inbox", required=True)
    q.add_argument("--date", required=True)
    q.add_argument("--ledger", default=str(LEDGER))
    q = sub.add_parser("receive", help="verify <inbox>/<D>/incoming/ and append the receipt")
    q.add_argument("--inbox", required=True)
    q.add_argument("--date", required=True)
    q.add_argument("--ledger", default=str(LEDGER))
    q.add_argument("--now", default=None, help="ISO time override (tests and replays)")
    q = sub.add_parser("build", help="label-free layout from <inbox>/<D>/verified/")
    q.add_argument("--bundle", required=True)
    q.add_argument("--date", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--parser-worktree", required=True)
    q.add_argument("--parser-python", default=None)
    q = sub.add_parser("concat", help="one window layout from per-date layouts (refuses duplicate row keys)")
    q.add_argument("--layout", action="append", required=True, help="a per-date layout directory (repeat)")
    q.add_argument("--out", required=True)
    q.add_argument("--ledger", default=None, help="also require a verified receipt per date")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    day = date.fromisoformat(args.date) if getattr(args, "date", None) else None
    try:
        if args.command == "concat":
            result = concat(layouts=args.layout, out=args.out, ledger=args.ledger)
        elif args.command == "pull":
            result = pull(share_root=args.share_root, day=day, inbox=args.inbox, ledger=args.ledger)
        elif args.command == "receive":
            result = receive(inbox=args.inbox, day=day, ledger=args.ledger, now=args.now)
        else:
            result = build(bundle=args.bundle, out=args.out, day=day, parser_worktree=args.parser_worktree,
                           parser_python=args.parser_python)
    except InputRefused as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), flush=True)
        return 2
    print(json.dumps(result, sort_keys=True, default=str), flush=True)
    status = str(result.get("status", "ok"))
    return 3 if status == "quarantined" or status.startswith("refused") else 0


if __name__ == "__main__":
    raise SystemExit(main())
