"""MG-1 stage replay and operational check over the outcome-blind tape (read-only).

The MG-1 shadow stage ``nbm_v2_guidance_read_v1`` writes one row per snapshot to
``snapshots/<event>/nbm_guidance_read_shadow.jsonl``. The pre-registration voids
the look (§6, "Replay") unless 100% of snapshots reproduce within 1e-12. This
command proves that, in three levels:

- **L1, stage replay:** recompute every stage vector from the inputs stored on
  the tape row (read, floor, bands, served vector) and require the same status,
  reason, floor bucket and sigma, and |delta| <= 1e-12. The row's stage config
  and code hashes must equal the running module's.
- **L2, captured-input replay:** rebuild the whole row from the captured inputs
  instead: the ``nbm_probabilistic_tmax`` source item in ``replay_inputs.jsonl``,
  and the ``feature_vector`` and served bands in ``snapshots.jsonl``. The read,
  floor, bands, served vector, status and stage vector must match the tape.
- **L3, byte re-derivation (``--level l3``):** re-parse the retained NBP bulletin
  bytes (shared forecast-payload CAS, SHA-256 verified) through parser v2. The
  bulletin with the tape's issue time must give the same mean and spread, and
  the newest bulletin available at capture must be the one the tape read. This
  closes the pre-registration's §8 "``v2_mean`` not re-derived from primary
  bytes". Newest-bulletin mismatches are counted, not failed: a stale last-good
  cache can legitimately serve an older cycle.

Operational outputs: coverage per local hour block, status and fallback
reasons, PIT violations, non-maximum ``period_kind``, parser != 2, and stale
reads.

``--d0-check --day V`` supports OD32. It checks D0 condition (b) from the
forecast-payload manifests (every US NBM row captured on local day V has parser
version 2). It checks (c) from tape coverage (every T+0 snapshot of every US
market with target V has a non-error tape row bound to the current stage
hashes). It prints the candidate D0 for the production agent's status-line
commit. Conditions it cannot see stay manual: the landing was verified before
Eastern 00:00 with all three capture workers recovered, and (e) promotion
countability.

Read-only, outcome-blind contract:
- It joins no outcome. It imports no settlement, panel or scoring loader, and an
  architecture ratchet keeps it that way. Scoring the stage is the separately
  registered MG-1 look behind ``weather.mg1_reserved_window``.
- It refuses every target date before ``MG1_FLOOR`` (2026-10-15), so it never
  reads the reserved 88a dates 2026-09-30..2026-10-14.
- It writes exactly one new file, ``--out``. That file must not exist and must
  lie outside the runtime ``data/`` tree.

CLI:
  python -m weather.backtesting.nbm_guidance_read_replay --out <path.jsonl>
      [folder ...] [--snapshots-root data/snapshots] [--market MARKET]
      [--from-date YYYY-MM-DD] [--through-date YYYY-MM-DD]
      [--level l2|l3] [--cas-root PATH]
  python -m weather.backtesting.nbm_guidance_read_replay --d0-check --day YYYY-MM-DD
      --out <path.json> [--snapshots-root data/snapshots]

Exit codes: 0 pass; 2 refused; 3 replay failure (L1, L2 or L3 values); 4 the
D0 check is not met.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from weather.collection import nbm_guidance_read_shadow as shadow
from weather.collection.forecast_payload_cas import SharedForecastPayloadCAS
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.mg1_reserved_window import MG1_FLOOR
from weather.model import nbm_guidance_read as stage
from weather.paths import data_path
from weather.sources.nbm_probabilistic_tmax import nbp_parser_version_number, parse_nbp_station_tmax

TOLERANCE = stage.RENORMALISE_TOLERANCE
REPLAY_FAILED_EXIT = 3
D0_NOT_MET_EXIT = 4
HOUR_BLOCKS = (("00-12", 0, 12), ("13-16", 13, 16), ("17-23", 17, 23))
ROW_KIND = "nbm_guidance_read_replay_row"
SUMMARY_KIND = "nbm_guidance_read_replay_summary"
D0_KIND = "nbm_guidance_read_d0_check"
SHARED_SCOPE = "shared_market_invariant"


class ReplayRefused(ValueError):
    """A request outside the read-only, outcome-blind, post-floor contract."""


# --------------------------------------------------------------------------- guards


def check_target(target, *, what="target date"):
    if target is None:
        raise ReplayRefused(f"refused: {what} is unreadable")
    if target < MG1_FLOOR:
        raise ReplayRefused(
            f"refused: {what} {target} is before {MG1_FLOOR}; dates 2026-09-30..2026-10-14 are reserved "
            "for 88a and earlier dates predate the stage"
        )
    return target


def check_out_path(out_path):
    out = Path(out_path).resolve()
    data_root = Path(data_path()).resolve()
    if out == data_root or data_root in out.parents:
        raise ReplayRefused(f"refused: --out {out} is inside the runtime data tree {data_root}")
    if out.exists():
        raise ReplayRefused(f"refused: --out {out} already exists; this command never overwrites")
    return out


def select_folders(folders, snapshots_root, market=None, from_date=None, through_date=None):
    """(folder, spec, target) to replay. An explicit folder before the floor is refused."""
    if from_date is not None:
        check_target(from_date, what="--from-date")
    explicit = bool(folders)
    root = Path(snapshots_root)
    candidates = [Path(folder) for folder in folders] if explicit else sorted(
        path for path in (root.iterdir() if root.is_dir() else ()) if path.is_dir()
    )
    selected = []
    for folder in candidates:
        spec = spec_for_slug(folder.name)
        target = date_from_event_slug(folder.name)
        if spec is None or target is None:
            if explicit:
                raise ReplayRefused(f"refused: {folder.name} is not a registered market-day folder")
            continue
        if target < MG1_FLOOR:
            if explicit:
                check_target(target, what=f"{folder.name} target")
            continue
        if (from_date is not None and target < from_date) or (through_date is not None and target > through_date):
            continue
        if market is not None and spec.id != market:
            continue
        selected.append((folder, spec, target))
    return selected


# --------------------------------------------------------------------------- reading


def family_path(folder, name):
    """A family file, or its gzip sibling when a tiering step compressed it."""
    for candidate in (Path(folder) / name, Path(folder) / (name + ".gz")):
        if candidate.is_file():
            return candidate
    return None


def read_jsonl(path):
    if path is None:
        return
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"_unparseable": True}


def by_snapshot(path):
    records = {}
    for record in read_jsonl(path):
        sid = record.get("snapshot_id")
        if sid is not None:
            records[str(sid)] = record
    return records


def parse_time(value):
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def local_time(record, spec):
    captured = parse_time((record or {}).get("captured_at_utc"))
    return captured.astimezone(spec.tz) if captured is not None else None


# --------------------------------------------------------------------------- L1 / L2


def _max_abs(left, right):
    if left is None or right is None or len(left) != len(right):
        return math.inf
    return max((abs(float(a) - float(b)) for a, b in zip(left, right)), default=0.0)


def _bands(row):
    return [
        stage.band_from_row({"bin_kind": b.get("kind"), "bin_value_c": b.get("low"), "bin_value_hi_c": b.get("high")})
        for b in row.get("bands") or []
    ]


def replay_l1(row):
    """Recompute the stage from the tape row's own inputs."""
    status = row.get("status")
    if status == shadow.STATUS_ERROR:
        return {"l1": "error_row", "l1_ok": False}
    if status == shadow.STATUS_SKIPPED:
        return {"l1": "skipped_row", "l1_ok": True}
    if row.get("stage_config_sha256") != stage.stage_config_sha256() or row.get(
        "stage_code_sha256"
    ) != stage.stage_code_sha256():
        return {"l1": "stage_hash_mismatch", "l1_ok": False}
    read = stage.NbmV2Read(**(row.get("read") or {}))
    result = stage.apply(_bands(row), row.get("served_vector") or [], read, row.get("floor"), unit=row.get("unit") or "")
    delta = _max_abs(result.vector, row.get("stage_vector"))
    same = (
        result.status == status
        and result.reason == row.get("reason")
        and result.floor_bucket == row.get("floor_bucket")
        and result.sigma == row.get("sigma")
    )
    ok = same and delta <= TOLERANCE
    return {"l1": "reproduced" if ok else "mismatch", "l1_ok": ok, "l1_max_abs": delta}


L2_EXACT_FIELDS = ("read", "floor", "floor_inputs", "bands", "served_vector", "status", "reason", "floor_bucket",
                   "sigma", "unit", "captured_input_hash")


def replay_l2(row, replay_record, snapshot_record, spec):
    """Rebuild the row from replay_inputs.jsonl and snapshots.jsonl and compare."""
    if replay_record is None or snapshot_record is None:
        return {"l2": "inputs_missing", "l2_ok": False}
    if row.get("status") == shadow.STATUS_ERROR:
        return {"l2": "error_row", "l2_ok": False}
    captured = parse_time(replay_record.get("captured_at_utc"))
    if captured is None:
        return {"l2": "captured_at_missing", "l2_ok": False}
    rebuilt = shadow.build_row(
        snapshot_id=str(row.get("snapshot_id")),
        captured_at=captured,
        event_slug=str(row.get("event_slug") or ""),
        market_id=row.get("market_id"),
        target_date=row.get("target_date"),
        model={"sources": replay_record.get("sources") or {}, "feature_vector": snapshot_record.get("feature_vector")},
        model_client=SimpleNamespace(spec=SimpleNamespace(display_unit=spec.display_unit)),
        band_rows=snapshot_record.get("bands") or [],
        captured_input_hash=str(replay_record.get("captured_input_hash") or ""),
    )
    # The tape stores JSON; compare like with like.
    rebuilt = json.loads(json.dumps(rebuilt, sort_keys=True, default=str))
    differs = [field for field in L2_EXACT_FIELDS if rebuilt.get(field) != row.get(field)]
    delta = 0.0 if rebuilt.get("stage_vector") is None and row.get("stage_vector") is None else _max_abs(
        rebuilt.get("stage_vector"), row.get("stage_vector")
    )
    ok = not differs and delta <= TOLERANCE
    out = {"l2": "reproduced" if ok else "mismatch", "l2_ok": ok, "l2_max_abs": delta}
    if differs:
        out["l2_differs"] = differs
    return out


# --------------------------------------------------------------------------- L3


def bulletin_index(snapshots_root, first, last):
    """Retained national NBP bulletins seen in any US manifest, earliest availability per digest."""
    bulletins = {}
    root = Path(snapshots_root)
    for folder in sorted(root.iterdir()) if root.is_dir() else ():
        spec, target = spec_for_slug(folder.name), date_from_event_slug(folder.name)
        if spec is None or target is None or spec.display_unit != "F" or not (first <= target <= last):
            continue
        for manifest in read_jsonl(family_path(folder, "forecast_payloads.jsonl")):
            if manifest.get("source") != shadow.SOURCE_NAME or manifest.get("payload_storage_scope") != SHARED_SCOPE:
                continue
            digest = str(manifest.get("payload_hash") or "")
            if not digest:
                continue
            seen = None
            for field in ("response_received_at", "fetched_at", "first_seen_at", "captured_at_utc"):
                seen = parse_time(manifest.get(field))
                if seen is not None:
                    break
            entry = bulletins.setdefault(digest, {"payload_hash": digest, "available_at": seen})
            if seen is not None and (entry["available_at"] is None or seen < entry["available_at"]):
                entry["available_at"] = seen
    return bulletins


class BulletinParser:
    """Parse each retained bulletin once per (station, target) through the in-tree parser v2."""

    def __init__(self, cas):
        self.cas = cas
        self.text = {}
        self.parsed = {}

    def parse(self, digest, station, target):
        key = (digest, station, target)
        if key not in self.parsed:
            if digest not in self.text:
                try:
                    self.text[digest] = self.cas.read(digest).decode("utf-8")
                except Exception as exc:  # noqa: BLE001 - a missing or corrupt blob is a counted outcome
                    self.text[digest] = exc
            text = self.text[digest]
            if isinstance(text, Exception):
                self.parsed[key] = {"available": False, "reason": f"bytes_unreadable:{type(text).__name__}"}
            else:
                self.parsed[key] = parse_nbp_station_tmax(text, station, target, parser_version=2)
        return self.parsed[key]


def replay_l3(row, spec, bulletins, parser):
    read = row.get("read") or {}
    if not read.get("eligible"):
        return {"l3": "read_ineligible"}
    captured = parse_time(row.get("captured_at_utc"))
    target = str(row.get("target_date") or "")
    tape_issue = parse_time(read.get("issued_at"))
    candidates = []
    same_issue = None
    for digest, entry in bulletins.items():
        available = entry["available_at"]
        if available is None or captured is None or available > captured:
            continue
        payload = parser.parse(digest, spec.icao, target)
        issue = parse_time(payload.get("issued_at"))
        if issue is None or issue > captured or captured - issue > timedelta(hours=stage.LOOKBACK_HOURS):
            continue
        if payload.get("available") is not True or payload.get("period_kind") != "maximum":
            continue
        candidates.append((issue, digest, payload))
        if tape_issue is not None and issue == tape_issue:
            same_issue = payload
    if same_issue is None:
        return {"l3": "bulletin_not_retained", "l3_ok": False}
    values_ok = (
        abs(float(same_issue.get("mean_native")) - float(read.get("v2_mean"))) <= TOLERANCE
        and abs(float(same_issue.get("stddev_native")) - float(read.get("v2_stddev"))) <= TOLERANCE
    )
    newest = max(candidates, key=lambda item: item[0])[0]
    return {
        "l3": "reproduced" if values_ok else "value_mismatch",
        "l3_ok": values_ok,
        "l3_newest_issue": newest.isoformat(),
        "l3_newest_mismatch": newest != tape_issue,
    }


# --------------------------------------------------------------------------- replay run


def replay_folder(folder, spec, target, *, level, bulletins=None, parser=None):
    tape = list(read_jsonl(family_path(folder, shadow.TAPE_FILENAME)))
    replay_records = by_snapshot(family_path(folder, "replay_inputs.jsonl"))
    snapshot_records = by_snapshot(family_path(folder, "snapshots.jsonl"))
    rows = []
    for row in tape:
        if row.get("_unparseable"):
            rows.append({"kind": ROW_KIND, "folder": folder.name, "l1": "unparseable", "l1_ok": False})
            continue
        sid = str(row.get("snapshot_id"))
        record_target = date_from_event_slug(str(row.get("event_slug") or folder.name))
        check_target(record_target, what=f"tape row {sid} target")
        local = local_time(row, spec)
        read = row.get("read") or {}
        out = {
            "kind": ROW_KIND,
            "folder": folder.name,
            "market_id": spec.id,
            "target_date": target.isoformat(),
            "snapshot_id": sid,
            "captured_at_local": local.isoformat() if local else None,
            "hour": local.hour if local else None,
            "t_plus_0": bool(local and local.date() == target),
            "status": row.get("status"),
            "reason": row.get("reason"),
            "pit_violation": bool(row.get("pit_violation")),
            "period_kind": read.get("period_kind"),
            "parser_version": read.get("parser_version"),
            "stale": bool(read.get("stale")),
        }
        out.update(replay_l1(row))
        out.update(replay_l2(row, replay_records.get(sid), snapshot_records.get(sid), spec))
        if level == "l3":
            out.update(replay_l3(row, spec, bulletins, parser))
        rows.append(out)
    snapshots = len(snapshot_records)
    t0 = sum(
        1 for record in snapshot_records.values()
        if (local_time(record, spec) or datetime.min.replace(tzinfo=timezone.utc)).date() == target
    )
    coverage = {
        "folder": folder.name,
        "snapshots": snapshots,
        "t_plus_0_snapshots": t0,
        "tape_rows": len(tape),
        "tape_t_plus_0_rows": sum(1 for row in rows if row.get("t_plus_0")),
    }
    return rows, coverage


def summarize(rows, coverage, level):
    blocks = []
    for label, start, end in HOUR_BLOCKS:
        group = [row for row in rows if row.get("hour") is not None and start <= row["hour"] <= end]
        blocks.append({
            "block": label,
            "rows": len(group),
            "mg1": sum(1 for row in group if row.get("status") == stage.STATUS_MG1),
            "fallback": sum(1 for row in group if row.get("status") == stage.STATUS_FALLBACK),
        })
    l1_fail = sum(1 for row in rows if not row.get("l1_ok"))
    l2_fail = sum(1 for row in rows if not row.get("l2_ok"))
    l3_fail = sum(1 for row in rows if row.get("l3_ok") is False)
    summary = {
        "kind": SUMMARY_KIND,
        "level": level,
        "stage_id": stage.STAGE_ID,
        "stage_config_sha256": stage.stage_config_sha256(),
        "stage_code_sha256": stage.stage_code_sha256(),
        "rows": len(rows),
        "l1_failures": l1_fail,
        "l2_failures": l2_fail,
        "l1_max_abs": max((row.get("l1_max_abs", 0.0) for row in rows), default=None),
        "l2_max_abs": max((row.get("l2_max_abs", 0.0) for row in rows), default=None),
        "status": dict(Counter(str(row.get("status")) for row in rows)),
        "fallback_reasons": dict(Counter(
            str(row.get("reason")) for row in rows if row.get("status") != stage.STATUS_MG1
        )),
        "pit_violations": sum(1 for row in rows if row.get("pit_violation")),
        "non_maximum_period_kind": sum(
            1 for row in rows if row.get("period_kind") not in (None, "maximum")
        ),
        "parser_not_2": sum(1 for row in rows if row.get("parser_version") not in (None, 2)),
        "stale_reads": sum(1 for row in rows if row.get("stale")),
        "blocks": blocks,
        "coverage": coverage,
    }
    if level == "l3":
        summary["l3_failures"] = l3_fail
        summary["l3_newest_bulletin_mismatches"] = sum(1 for row in rows if row.get("l3_newest_mismatch"))
        summary["l3_status"] = dict(Counter(str(row.get("l3")) for row in rows))
    failed = l1_fail or l2_fail or (level == "l3" and l3_fail)
    summary["replay_check"] = "FAIL" if failed else "PASS"
    return summary


def run_replay(args):
    out = check_out_path(args.out)
    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    through_date = date.fromisoformat(args.through_date) if args.through_date else None
    selected = select_folders(args.folders, args.snapshots_root, args.market, from_date, through_date)
    bulletins = parser = None
    if args.level == "l3" and selected:
        targets = [target for _f, _s, target in selected]
        bulletins = bulletin_index(args.snapshots_root, max(min(targets) - timedelta(days=1), MG1_FLOOR),
                                   max(targets) + timedelta(days=1))
        parser = BulletinParser(SharedForecastPayloadCAS(args.cas_root))
    rows, coverage = [], []
    for folder, spec, target in selected:
        if family_path(folder, shadow.TAPE_FILENAME) is None:
            coverage.append({"folder": folder.name, "tape_rows": 0, "tape_missing": True})
            continue
        folder_rows, folder_coverage = replay_folder(
            folder, spec, target, level=args.level, bulletins=bulletins, parser=parser
        )
        rows.extend(folder_rows)
        coverage.append(folder_coverage)
    summary = summarize(rows, coverage, args.level)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.write(json.dumps(summary, sort_keys=True) + "\n")
    print(json.dumps({key: summary[key] for key in (
        "replay_check", "rows", "l1_failures", "l2_failures", "pit_violations", "fallback_reasons", "blocks"
    )}, sort_keys=True))
    return REPLAY_FAILED_EXIT if summary["replay_check"] == "FAIL" else 0


# --------------------------------------------------------------------------- D0 check


def d0_check(snapshots_root, day):
    """(b) parser v2 on every US NBM manifest row captured on local day ``day``; (c) tape coverage."""
    check_target(day, what="--day")
    root = Path(snapshots_root)
    manifest_rows = manifest_v2 = 0
    not_v2 = Counter()
    t0_snapshots = t0_covered = 0
    uncovered, unbound = [], 0
    folders = []
    for folder in sorted(root.iterdir()) if root.is_dir() else ():
        spec, target = spec_for_slug(folder.name), date_from_event_slug(folder.name)
        if spec is None or target is None or spec.display_unit != "F":
            continue
        if not (day <= target <= day + timedelta(days=2)):
            continue
        folders.append(folder.name)
        for manifest in read_jsonl(family_path(folder, "forecast_payloads.jsonl")):
            if manifest.get("source") != shadow.SOURCE_NAME:
                continue
            local = local_time(manifest, spec)
            if local is None or local.date() != day:
                continue
            manifest_rows += 1
            try:
                version = nbp_parser_version_number(manifest.get("parser_version"))
            except ValueError:
                version = None
            if version == 2:
                manifest_v2 += 1
            else:
                not_v2[str(manifest.get("parser_version"))] += 1
        if target != day:
            continue
        tape = by_snapshot(family_path(folder, shadow.TAPE_FILENAME))
        for sid, record in by_snapshot(family_path(folder, "snapshots.jsonl")).items():
            local = local_time(record, spec)
            if local is None or local.date() != day:
                continue
            t0_snapshots += 1
            row = tape.get(sid)
            if row is None or row.get("status") == shadow.STATUS_ERROR:
                uncovered.append(f"{folder.name}:{sid}")
                continue
            if row.get("stage_config_sha256") != stage.stage_config_sha256() or row.get(
                "stage_code_sha256"
            ) != stage.stage_code_sha256():
                unbound += 1
                continue
            t0_covered += 1
    condition_b = manifest_rows > 0 and manifest_v2 == manifest_rows
    condition_c = t0_snapshots > 0 and t0_covered == t0_snapshots
    met = condition_b and condition_c
    return {
        "kind": D0_KIND,
        "verified_day": day.isoformat(),
        "folders": folders,
        "condition_b_parser_2": {
            "met": condition_b, "nbm_manifest_rows": manifest_rows, "parser_v2_rows": manifest_v2,
            "other_parser_versions": dict(not_v2),
        },
        "condition_c_stage_capture": {
            "met": condition_c, "t_plus_0_snapshots": t0_snapshots, "covered": t0_covered,
            "uncovered": uncovered[:50], "uncovered_count": len(uncovered), "stage_hash_mismatch": unbound,
        },
        "candidate_d0": max(day + timedelta(days=1), MG1_FLOOR).isoformat() if met else None,
        "manual_conditions": [
            "(b) the landing was verified before Eastern 00:00 of D0 with all three capture workers recovered",
            "(e) D0 is promotion-countable (settlement-ledger flag; not read by this command)",
            "OD32: record D0 in reserved-confirmation-window.md and weather.mg1_reserved_window in one commit",
        ],
    }


def run_d0_check(args):
    out = check_out_path(args.out)
    if not args.day:
        raise ReplayRefused("refused: --d0-check needs --day YYYY-MM-DD")
    result = d0_check(args.snapshots_root, date.fromisoformat(args.day))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("verified_day", "candidate_d0")}, sort_keys=True))
    return 0 if result["candidate_d0"] else D0_NOT_MET_EXIT


# --------------------------------------------------------------------------- CLI


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folders", nargs="*", help="market-day folders (default: every folder under --snapshots-root)")
    parser.add_argument("--out", required=True, help="new output file outside data/")
    parser.add_argument("--snapshots-root", default=str(data_path("snapshots")))
    parser.add_argument("--market", default=None)
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--through-date", default=None)
    parser.add_argument("--level", choices=("l2", "l3"), default="l2", help="l2 runs L1+L2; l3 adds byte re-derivation")
    parser.add_argument("--cas-root", default=None, help="shared forecast-payload CAS root (default: the runtime one)")
    parser.add_argument("--d0-check", action="store_true", help="check D0 conditions (b) and (c) for --day")
    parser.add_argument("--day", default=None, help="the verified full day for --d0-check")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run_d0_check(args) if args.d0_check else run_replay(args)
    except ReplayRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
