r"""Row-28b forward inputs, capture-host side: the (a) as-of-capture trim of a published MG-2 bundle.

Design: ``docs/research/row28b-asof-trim-design-2026-11-04.md`` (master approved 2026-11-04, rulings Q1-Q6).
Owner authority: DECISION_LOG 2026-11-04 item (5) and the reserved-window row-28b row (defence in depth for the
row-28b forward-input carve-out).

A manual one-shot, run weekly by master on the capture host through ``scripts/ops/r28b_input_trim.ps1`` (a detached,
lease-held runner inside 00:30-09:00, after the 04:15 and 07:00 MG-2 exports; no scheduled task, master Q5). It
imports only the standard library and the bound ``mg2_input_allowlist`` (read-only), and no capture loop imports it.

* **Reads the published MG-2 bundle only.** ``<repo>\data\exports\mg2-inputs\<D>\`` and its ``<D>.SHA256SUMS``,
  verified first (ready marker, manifest sha, allowlist sha, export cut, every file's sha and size, no unlisted
  file, the SUMS lines, no link or reparse point). Nothing under ``data\snapshots\`` or ``forecast_payload_cas\``
  is opened, and the bound exporter is never imported or run (master Q2).
* **T\*(m, D), the last scored cutoff.** The latest ``captured_at_utc`` in m's D ``features_long.csv`` whose
  captured ``cutoff_hour`` is an integer <= ``H_LAST`` (16) and whose capture lies on local date D in m's own time
  zone. ``cutoff_hour`` is the captured effective WU print cutoff; it is never recomputed from wall-clock time.
  - **W1** (``r28b_w1_after_local_midnight``): a snapshot captured at or after local midnight ending D in m's own
    zone never sets T\* and is never kept (the LA export cut otherwise lets eastern D+1-morning captures through).
  - **W2** (``r28b_w2_no_scored_cutoff_snapshot``): no such snapshot (``features_long.csv`` absent, empty or
    without an integer cutoff <= 16) refuses the market for D by name; none of its files travel.
* **Trim, not rewrite.** For each market: ``replay_inputs.jsonl``, ``snapshots_long.csv``, ``features_long.csv``
  (D) and the D-1, D and D+1 NBM ``forecast_payloads.jsonl`` keep only records captured at or before T\*; every
  kept line is the source line, byte for byte. Only NBM blobs referenced by a kept row are copied (re-hashed).
  ``prev_day/`` is dropped and no ``prev_dmax`` is built (master Q3).
* **Format unchanged.** ``mg2_input_bundle/1`` with the same allowlist sha, so the workstation verifies it with the
  bound MG-2 receiver's ``verify_bundle`` as is. The manifest copies only ``COPY_KEYS`` from the source (never a coverage
  block), rebuilds ``files``, ``markets`` and ``nbm_blobs``, and adds the ``r28b_trim`` block (T\* per market,
  kept and dropped counts, the source manifest and SUMS shas, this module's sha).
* **Dates (master Q4, Q6).** Only local target dates 2026-12-17..2027-01-30, and no run before 2026-12-21. There is
  no date override.
* **Holes (master Q2).** A date whose MG-2 bundle was not published by its D+1 deadline (09:00 America/Toronto on
  D+1, the end of the exporter's admission window), or whose ``export_finished_utc`` is later, becomes a NAMED hole:
  ``<out>\_holes\<D>.json`` (write-once). Nothing is trimmed for it, ever.

Output, all under ``<out>`` (default ``<repo>\data\exports\r28b-inputs``) and nowhere else: ``<D>\`` (published by an
atomic rename from ``.<D>.partial``), ``<D>.SHA256SUMS`` beside it and ``_holes\<D>.json``.

    python -m weather.calibration.r28b_input_trim --date 2026-12-17 [--date ...]
        [--source-root <repo>\data\exports\mg2-inputs] [--out <repo>\data\exports\r28b-inputs]

Exit: 0 trimmed (absent markets named in the output), 2 refused, 3 not ready (before the deadline), 4 a hole was
recorded or already stands.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import shutil
import stat
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.calibration import mg2_input_allowlist as allow

# The same prefixes as mg2_composite._PRODUCTION_PREFIXES (pinned by a workstation test; mg2_composite itself
# refuses on the capture host, so it is not imported here).
PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                       "weather.trading", "weather.capture", "weather.sources", "weather.execution",
                       "maker_core", "app")


def _refuse_production_import():
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.r28b_input_trim is a one-shot; imported from {name}")
        frame = frame.f_back


_refuse_production_import()

SCHEMA = "r28b_input_trim/1"
HOLE_SCHEMA = "r28b_input_hole/1"
WINDOW_FIRST = date(2026, 12, 17)   # the row-28b forward line (owner 2026-11-04)
WINDOW_LAST = date(2027, 1, 30)     # the scored window's last date (master narrowing; Q4: nothing later)
FIRST_RUN = date(2026, 12, 21)      # the first emission batch: no trim and no pull before it
H_LAST = 16                         # the last scored hour (prereg hours 13-16)
LATE_T_STAR_HOUR = 18               # T* at or after 18:00 local is disclosed as late_t_star (a WU print stall)
HOST_TZ = "America/Toronto"
DEADLINE_HOUR = 9                   # D+1 09:00 America/Toronto: the end of the exporter's admission window
SUMS_SUFFIX = ".SHA256SUMS"
HOLES_DIR = "_holes"
CHUNK = 1 << 20
W1 = "r28b_w1_after_local_midnight"
W2 = "r28b_w2_no_scored_cutoff_snapshot"
NO_REPLAY = "r28b_no_replay_record_by_t_star"
HOLE_NOT_EXPORTED = "r28b_hole_not_exported_by_deadline"
HOLE_EXPORTED_LATE = "r28b_hole_exported_after_deadline"
HOLE_REASONS = (HOLE_NOT_EXPORTED, HOLE_EXPORTED_LATE)
# The same zones as the MG-2 exporter's TZ table (pinned by a workstation test).
TZ = {"atlanta": "America/New_York", "austin": "America/Chicago", "chicago": "America/Chicago",
      "dallas": "America/Chicago", "denver": "America/Denver", "houston": "America/Chicago",
      "los-angeles": "America/Los_Angeles", "miami": "America/New_York", "nyc": "America/New_York",
      "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
# Source manifest keys carried into the trimmed manifest. Never a coverage block (market_price_coverage,
# book_coverage), whatever the source run set.
COPY_KEYS = ("schema", "exporter_schema", "target_date", "export_cut_utc", "export_started_utc",
             "export_finished_utc", "allowlist_sha256", "exporter_sha256", "host_repo_head", "min_quiet_seconds",
             "read_mode", "dropped_after_cut", "nbm_rows_bad_ref")
TRIMMED_KINDS = ("replay_inputs", "snapshots_long", "features_long", "nbm_manifest")


class TrimRefused(RuntimeError):
    """The trim cannot run for this date; nothing is published."""


class NotReady(TrimRefused):
    """The MG-2 bundle is not published yet and its deadline has not passed; nothing is written."""


# ----------------------------------------------------------------------------- small helpers

def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def module_sha256():
    return sha256_file(Path(__file__))


def _is_link(path):
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _walk(root):
    """Relative posix paths of every regular file under ``root``; a link, reparse point or other entry refuses."""
    root = Path(root)
    if _is_link(root):
        raise TrimRefused(f"link or reparse point refused: {root.name}")
    out = []
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            full = Path(current) / name
            if _is_link(full):
                raise TrimRefused(f"link or reparse point refused: {full.relative_to(root).as_posix()}")
        for name in files:
            full = Path(current) / name
            if not stat.S_ISREG(os.lstat(full).st_mode):
                raise TrimRefused(f"not a regular file: {full.relative_to(root).as_posix()}")
            out.append(full.relative_to(root).as_posix())
    return sorted(out)


def cutoff_value(value):
    """The captured cutoff hour as an int, else None. A superset of the emitter's ``int(str(x))`` parse, so T*
    never ends before a snapshot the emitter gates (accepting more can only keep more)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError:
            return None
    return int(number) if math.isfinite(number) and number.is_integer() else None


def local_bounds(market, day):
    """(start, end) of local date ``day`` in the market's own zone, as aware UTC."""
    zone = ZoneInfo(TZ[market])
    start = datetime.combine(day, time(0), tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone).astimezone(timezone.utc)
    return start, end


def deadline_utc(day):
    """The MG-2 bundle's publication deadline: 09:00 America/Toronto on D+1."""
    return datetime.combine(day + timedelta(days=1), time(DEADLINE_HOUR),
                            tzinfo=ZoneInfo(HOST_TZ)).astimezone(timezone.utc)


def check_date(day, today):
    """Row-28b dates only (master Q4), and no run before the first emission batch."""
    if not WINDOW_FIRST <= day <= WINDOW_LAST:
        raise TrimRefused(f"{day} is outside the row-28b input window {WINDOW_FIRST}..{WINDOW_LAST} (master Q4): "
                          f"refused, and there is no override")
    if today < FIRST_RUN:
        raise TrimRefused(f"no row-28b trim runs before the first emission batch {FIRST_RUN} (today {today})")


def csv_records(path):
    """``(raw bytes, fields)`` per CSV record of a bundle file, the raw bytes exactly as stored (quoted newlines
    stay inside one record; quotes are balanced by the csv module's doubling)."""
    with open(path, "rb") as handle:
        pending = b""
        for line in handle:
            pending += line
            if pending.count(b'"') % 2:
                continue
            fields = next(csv.reader(io.StringIO(pending.decode("utf-8"), newline="")), [])
            yield pending, fields
            pending = b""
    if pending:
        raise TrimRefused(f"unterminated quoted CSV record in {Path(path).name}")


def jsonl_records(path):
    """``(raw bytes, record)`` per non-blank line, the raw bytes exactly as stored."""
    with open(path, "rb") as handle:
        for line in handle:
            if line.strip():
                yield line, json.loads(line)


# ----------------------------------------------------------------------------- the source bundle

def _check_roots(source_root, out):
    source_root, out = Path(source_root), Path(out)
    if not source_root.is_absolute() or not out.is_absolute():
        raise TrimRefused("absolute --source-root and --out are required")
    source_root, out = Path(os.path.abspath(source_root)), Path(os.path.abspath(out))
    if source_root.name != "mg2-inputs" or source_root.parent.name != "exports":
        raise TrimRefused(f"the source must be the published MG-2 export root ...\\exports\\mg2-inputs: {source_root}")
    data = source_root.parent.parent
    for forbidden in (source_root, data / "snapshots", data / "forecast_payload_cas"):
        if out == forbidden or forbidden in out.parents:
            raise TrimRefused(f"output {out} is inside {forbidden}")
    if source_root in out.parents or out in source_root.parents:
        raise TrimRefused(f"output {out} overlaps the source {source_root}")
    for root in (source_root, out):
        if root.exists() and _is_link(root):
            raise TrimRefused(f"link or reparse point refused: {root}")
    return source_root, out


def load_source(source_root, day):
    """The verified published MG-2 bundle of ``day``: ``(bundle dir, manifest, manifest sha, sums sha)``."""
    iso = day.isoformat()
    bundle, sums = Path(source_root) / iso, Path(source_root) / f"{iso}{SUMS_SUFFIX}"
    present = _walk(bundle)
    manifest_path, marker = bundle / allow.MANIFEST, bundle / allow.MANIFEST_SHA
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    declared = (marker.read_text(encoding="ascii").split() or [""])[0].strip().lower()
    if declared != manifest_sha:
        raise TrimRefused("source manifest.json does not match its manifest.json.sha256")
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != allow.BUNDLE_SCHEMA or manifest.get("target_date") != iso:
        raise TrimRefused("source manifest schema or target date")
    if manifest.get("allowlist_sha256") != allow.allowlist_sha256():
        raise TrimRefused("source allowlist sha differs from this checkout's mg2_input_allowlist")
    if parse_time(manifest.get("export_cut_utc")) != allow.export_cut_utc(day):
        raise TrimRefused("source export cut differs from the contract's")
    listed = {str(e.get("path")): e for e in manifest.get("files") or [] if isinstance(e, dict)}
    for rel in present:
        if allow.classify_path(rel, day) is None:
            raise TrimRefused(f"unlisted file in the source bundle: {rel}")
        if rel not in (allow.MANIFEST, allow.MANIFEST_SHA) and rel not in listed:
            raise TrimRefused(f"source file not in its manifest: {rel}")
    for rel, entry in listed.items():
        path = bundle / rel
        if rel not in present or sha256_file(path) != entry.get("sha256") or path.stat().st_size != entry.get("bytes"):
            raise TrimRefused(f"source file missing or changed since export: {rel}")
    if not sums.is_file() or _is_link(sums):
        raise TrimRefused(f"source {iso}{SUMS_SUFFIX} is missing")
    expected = {f"{iso}/{allow.MANIFEST}": manifest_sha, f"{iso}/{allow.MANIFEST_SHA}": sha256_file(marker)}
    expected.update({f"{iso}/{rel}": e["sha256"] for rel, e in listed.items()})
    got = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, _, name = line.partition("  ")
            got[name] = digest
    if got != expected:
        raise TrimRefused(f"source {iso}{SUMS_SUFFIX} does not match the bundle")
    return bundle, manifest, manifest_sha, sha256_file(sums)


# ----------------------------------------------------------------------------- T* and the trim

def t_star(bundle, market, day):
    """T*(m, D) and its disclosure counts from m's D ``features_long.csv`` (None when W2 applies)."""
    slug = allow.slug_for(market, day)
    path = Path(bundle) / "snapshots" / slug / "features_long.csv"
    out = {"t_star_utc": None, "t_star_local_hour": None, "late_t_star": False, "w1_excluded": 0,
           "cutoff_unparseable": 0, "status": "refused", "reason": W2}
    if not path.is_file():
        return out
    start, end = local_bounds(market, day)
    records = csv_records(path)
    header = next(records, (b"", []))[1]
    if header != list(allow.CSV_FIELDS["features_long.csv"]):
        raise TrimRefused(f"features_long.csv header differs from the contract for {market}")
    best = None
    for _raw, fields in records:
        if not fields:
            continue
        row = dict(zip(header, fields))
        hour = cutoff_value(row.get("cutoff_hour"))
        if hour is None:
            out["cutoff_unparseable"] += 1
            continue
        captured = parse_time(row.get("captured_at_utc"))
        if hour > H_LAST or captured is None:
            continue
        if captured >= end:
            out["w1_excluded"] += 1
            continue
        if captured < start:
            continue
        best = captured if best is None or captured > best else best
    if best is not None:
        local = best.astimezone(ZoneInfo(TZ[market]))
        out.update(t_star_utc=best.isoformat(), t_star_local_hour=local.hour,
                   late_t_star=local.hour >= LATE_T_STAR_HOUR, status="kept", reason=None)
    return out


def _kept_lines(path, kind, cut, slug, counts):
    """The source lines of one file captured at or before ``cut``, plus the self-checks on each kept record."""
    lines = []
    if kind in ("snapshots_long", "features_long"):
        records = csv_records(path)
        raw_header, header = next(records, (b"", []))
        if header != list(allow.CSV_FIELDS[Path(path).name]):
            raise TrimRefused(f"{Path(path).name} header differs from the contract")
        lines.append(raw_header)
        for raw, fields in records:
            if not fields:
                continue
            captured = parse_time(dict(zip(header, fields)).get("captured_at_utc"))
            if captured is not None and captured <= cut:
                lines.append(raw)
                counts["kept"] += 1
            else:
                counts["dropped"] += 1
        return lines
    for raw, record in jsonl_records(path):
        captured = parse_time(record.get("captured_at_utc")) if isinstance(record, dict) else None
        if captured is None or captured > cut:
            counts["dropped"] += 1
            continue
        problems = (allow.replay_record_problems(record) if kind == "replay_inputs"
                    else allow.nbm_row_problems(record))
        if problems:
            raise TrimRefused(f"forbidden or unlisted field in a kept {kind} record: {sorted(set(problems))[:10]}")
        if kind == "replay_inputs" and record.get("event_slug") != slug:
            raise TrimRefused("a kept replay record names another event")
        lines.append(raw)
        counts["kept"] += 1
    return lines


def _market_files(listed, market, day):
    """The source bundle paths of one market for D, by kind (prev_day never)."""
    out = []
    for rel in sorted(listed):
        kind = allow.classify_path(rel, day)
        if kind is not None and kind[1] == market and kind[0] in TRIMMED_KINDS:
            out.append((rel, kind[0]))
    return out


def _refs(lines):
    refs = {}
    for raw in lines:
        row = json.loads(raw)
        digest = str(row.get("payload_hash") or "")
        if (row.get("payload_storage_scope") == allow.NBM_SCOPE and row.get("payload_ref") == allow.blob_ref(digest)
                and allow.BLOB_RE.match(str(row.get("payload_ref")))):
            refs[digest] = row["payload_ref"]
    return refs


def _write(staging, rel, chunks):
    target = Path(staging).joinpath(*rel.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with open(target, "xb") as handle:
        for chunk in chunks:
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _self_check(staging, manifest, day, stars):
    """Before publishing: every file listed and matching, nothing unlisted, no prev_day, nothing after T* or W1."""
    listed = {e["path"]: e for e in manifest["files"]}
    present = [p for p in _walk(staging) if p not in (allow.MANIFEST, allow.MANIFEST_SHA)]
    if sorted(present) != sorted(listed):
        raise TrimRefused("self-check: the staged files differ from the trimmed manifest")
    for rel, entry in listed.items():
        kind = allow.classify_path(rel, day)
        if kind is None or kind[0] == "prev_day_metar":
            raise TrimRefused(f"self-check: {rel} may not travel in a trimmed bundle")
        path = Path(staging) / rel
        if sha256_file(path) != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise TrimRefused(f"self-check: {rel} does not match its entry")
        if kind[0] == "nbm_blob":
            continue
        cut = parse_time(stars[kind[1]]["t_star_utc"])
        end = local_bounds(kind[1], day)[1]
        if kind[0] in ("snapshots_long", "features_long"):
            records = csv_records(path)
            header = next(records, (b"", []))[1]
            times = [parse_time(dict(zip(header, f)).get("captured_at_utc")) for _r, f in records if f]
        else:
            times = [parse_time(r.get("captured_at_utc")) for _r, r in jsonl_records(path)]
        if any(t is None or t > cut for t in times):
            raise TrimRefused(f"self-check: {rel} holds a record captured after T*")
        if any(t >= end for t in times):
            raise TrimRefused(f"self-check {W1}: {rel} holds a record captured after local midnight ending D")


# ----------------------------------------------------------------------------- holes

def hole_path(out, day):
    return Path(out) / HOLES_DIR / f"{day.isoformat()}.json"


def record_hole(out, day, reason, now, source_finished=None):
    """The named hole of ``day`` (write-once). Returns ``(record, sha256)``."""
    if reason not in HOLE_REASONS:
        raise TrimRefused(f"unknown hole reason {reason}")
    path = hole_path(out, day)
    if path.exists():
        body = path.read_bytes()
        return json.loads(body), hashlib.sha256(body).hexdigest()
    record = {"schema": HOLE_SCHEMA, "target_date": day.isoformat(), "reason": reason,
              "deadline_utc": deadline_utc(day).isoformat(), "decided_utc": now.isoformat(),
              "source_export_finished_utc": source_finished, "trim_module_sha256": module_sha256()}
    body = (json.dumps(record, indent=1, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(body)
    return record, hashlib.sha256(body).hexdigest()


# ----------------------------------------------------------------------------- one date

def trim(*, day, source_root, out, now=None):
    """Trim one target date. Returns a result dict (status ``trimmed`` or ``hole``); raises NotReady/TrimRefused."""
    now = now or datetime.now(timezone.utc)
    check_date(day, now.astimezone(ZoneInfo(HOST_TZ)).date())
    source_root, out = _check_roots(source_root, out)
    iso = day.isoformat()
    final, staging, sums = out / iso, out / f".{iso}.partial", out / f"{iso}{SUMS_SUFFIX}"
    if hole_path(out, day).exists():
        record, sha = record_hole(out, day, json.loads(hole_path(out, day).read_bytes())["reason"], now)
        return {"target_date": iso, "status": "hole", "reason": record["reason"], "hole_sha256": sha,
                "already_recorded": True}
    if final.exists() or sums.exists():
        raise TrimRefused(f"{final} already exists: one trim per date")
    if staging.exists():
        raise TrimRefused(f"{staging} exists from an earlier failed run; the wrapper removes it under the lease")
    if not (source_root / iso / allow.MANIFEST_SHA).is_file():
        if now <= deadline_utc(day):
            raise NotReady(f"the MG-2 bundle {iso} is not published yet (deadline {deadline_utc(day).isoformat()})")
        record, sha = record_hole(out, day, HOLE_NOT_EXPORTED, now)
        return {"target_date": iso, "status": "hole", "reason": record["reason"], "hole_sha256": sha}
    bundle, source, source_sha, sums_sha = load_source(source_root, day)
    finished = parse_time(source.get("export_finished_utc"))
    if finished is None or finished > deadline_utc(day):
        record, sha = record_hole(out, day, HOLE_EXPORTED_LATE, now, source.get("export_finished_utc"))
        return {"target_date": iso, "status": "hole", "reason": record["reason"], "hole_sha256": sha}
    listed = {str(e["path"]): e for e in source.get("files") or []}
    out.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        entries, stars, markets, refs, file_counts = [], {}, {}, {}, {}
        for market in allow.MARKETS:
            star = t_star(bundle, market, day)
            files = _market_files(listed, market, day)
            kept = {}
            if star["status"] == "kept":
                cut = parse_time(star["t_star_utc"])
                for rel, kind in files:
                    counts = {"kept": 0, "dropped": 0}
                    kept[rel] = (kind, _kept_lines(bundle / rel, kind, cut, allow.slug_for(market, day), counts))
                    file_counts[rel] = counts
                replay = allow.slug_for(market, day)
                if not kept.get(f"snapshots/{replay}/replay_inputs.jsonl", (None, []))[1]:
                    star.update(status="refused", reason=NO_REPLAY)
            if star["status"] != "kept":
                kept = {}
                for rel, _kind in files:
                    file_counts[rel] = {"kept": 0, "dropped": None}  # the market is refused: nothing read
            entry = dict((source.get("markets") or {}).get(market) or
                         {"expected": True, "present": False, "reason": "absent_in_source"})
            if star["status"] != "kept":
                entry.update(present=False, reason=star["reason"])
            markets[market] = entry
            stars[market] = star
            for rel, (kind, lines) in sorted(kept.items()):
                if kind == "nbm_manifest":
                    refs.update(_refs(lines))
                digest, size = _write(staging, rel, lines)
                rows = len(lines) - 1 if kind in ("snapshots_long", "features_long") else len(lines)
                entries.append({**listed[rel], "sha256": digest, "bytes": size, "rows": rows,
                                "r28b_source_sha256": listed[rel]["sha256"],
                                "r28b_rows_dropped": file_counts[rel]["dropped"]})
        blobs = {"referenced": len(refs), "copied": 0, "missing": 0, "hash_mismatch": 0}
        for digest in sorted(refs):
            rel = f"forecast_payload_cas/{refs[digest]}"
            if rel not in listed:
                blobs["missing"] += 1
                continue
            with open(bundle / rel, "rb") as handle:
                sha, size = _write(staging, rel, iter(lambda: handle.read(CHUNK), b""))
            if sha != digest:
                raise TrimRefused(f"blob {rel} does not hash to its name")
            blobs["copied"] += 1
            entries.append({**listed[rel], "sha256": sha, "bytes": size, "rows": None,
                            "r28b_source_sha256": listed[rel]["sha256"], "r28b_rows_dropped": 0})
        source_blobs = sum(1 for rel in listed if allow.classify_path(rel, day)[0] == "nbm_blob")
        dropped_paths = sorted(rel for rel in listed if allow.classify_path(rel, day)[0] == "prev_day_metar")
        manifest = {k: source[k] for k in COPY_KEYS if k in source}
        manifest.update({
            "files": sorted(entries, key=lambda e: e["path"]), "markets": markets, "nbm_blobs": blobs,
            "coverage_counts": False,
            "r28b_trim": {
                "schema": SCHEMA, "trim_module_sha256": module_sha256(),
                "source_manifest_sha256": source_sha, "source_sums_sha256": sums_sha,
                "h_last": H_LAST, "late_t_star_hour": LATE_T_STAR_HOUR,
                "walls": {"W1": W1, "W2": W2}, "prev_day": "dropped", "prev_day_files_dropped": len(dropped_paths),
                "window": [WINDOW_FIRST.isoformat(), WINDOW_LAST.isoformat()],
                "deadline_utc": deadline_utc(day).isoformat(), "markets": stars,
                "files": {rel: file_counts[rel] for rel in sorted(file_counts)},
                "nbm_blobs_in_source": source_blobs, "nbm_blobs_pruned": source_blobs - blobs["copied"],
                "trimmed_utc": now.isoformat()}})
        _self_check(staging, manifest, day, stars)
        body = json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8")
        (staging / allow.MANIFEST).write_bytes(body)
        manifest_sha = hashlib.sha256(body).hexdigest()
        (staging / allow.MANIFEST_SHA).write_bytes((manifest_sha + "\n").encode("ascii"))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)  # only this run's own staging folder
        raise
    os.replace(staging, final)
    lines = [f"{manifest_sha}  {iso}/{allow.MANIFEST}",
             f"{sha256_file(final / allow.MANIFEST_SHA)}  {iso}/{allow.MANIFEST_SHA}"]
    lines += [f"{e['sha256']}  {iso}/{e['path']}" for e in manifest["files"]]
    sums.write_bytes(("\n".join(sorted(lines, key=lambda s: s.split("  ", 1)[1])) + "\n").encode("utf-8"))
    absent = sorted(m for m, v in markets.items() if not v.get("present"))
    return {"target_date": iso, "status": "trimmed", "manifest_sha256": manifest_sha,
            "source_manifest_sha256": source_sha, "absent_markets": absent,
            "refused_markets": {m: s["reason"] for m, s in stars.items() if s["status"] != "kept"},
            "late_t_star": sorted(m for m, s in stars.items() if s["late_t_star"]), "files": len(manifest["files"]),
            "nbm_blobs": blobs}


# ----------------------------------------------------------------------------- CLI

def build_parser():
    repo = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.r28b_input_trim")
    parser.add_argument("--date", action="append", required=True, help="local target date D (repeatable)")
    parser.add_argument("--source-root", default=str(repo / "data" / "exports" / "mg2-inputs"))
    parser.add_argument("--out", default=str(repo / "data" / "exports" / "r28b-inputs"))
    return parser


def main(argv=None, now=None):
    args = build_parser().parse_args(argv)
    status = 0
    for text in args.date:
        try:
            result = trim(day=date.fromisoformat(text), source_root=args.source_root, out=args.out, now=now)
        except NotReady as exc:
            print(json.dumps({"target_date": text, "status": "not_ready", "reason": str(exc)}))
            status = max(status, 3)
            continue
        except (TrimRefused, ValueError, OSError) as exc:
            print(json.dumps({"target_date": text, "status": "refused", "reason": str(exc)}))
            status = max(status, 2)
            continue
        print(json.dumps(result, sort_keys=True))
        if result["status"] == "hole":
            status = max(status, 4)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
