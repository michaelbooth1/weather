"""M8 served-vector reproduction: does the unmodified replay reproduce what was served?

For every captured snapshot (``replay_inputs.jsonl``) of a dev target date
2026-07-31..2026-09-29, re-run the current serving pipeline once, unmodified,
and compare it with the record's ``recorded_distribution`` -- the distribution
the capture-time model produced, written by ``snapshot_store`` next to the
``sources`` it consumed as the replay fidelity canary
(``src/weather/collection/snapshot_store.py`` ``recorded_distribution``). That
vector is a model output, not an outcome: no label, settlement or price is read.

Per snapshot: ``max_abs`` (max absolute per-bucket difference over native
1-degree buckets, a missing bucket counts as 0), ``l1``, whether the bucket
supports match, and which capture-time identity parts differ from the replay
(``model_identity`` code / artifact hash, per-file fingerprints, model version,
active model kind). Per market: n, share with ``max_abs <= 1e-9``, p99 and max
of ``max_abs``, and the top mismatch reasons.

Same roots, folder selection, date guard, fail-closed folder checks, output
refusal inside ``data/`` and append-only resume as ``stage_replay``.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tools.research.model_edge_lever5 import stage_replay as l5

SCHEMA = "lever5_served_repro_v1"
TOL = 1e-9


def _int_dist(dist):
    from weather.backtesting.replay import as_int_distribution

    return as_int_distribution(dist or {})


def _files_by_path(files):
    return {str(f.get("path")): f.get("sha256") for f in (files or []) if isinstance(f, dict)}


def identity_reasons(recorded, replayed):
    """Names of the capture-time identity parts that differ from the replay."""
    if not isinstance(recorded, dict) or not recorded:
        return ["recorded_identity_missing"]
    if not isinstance(replayed, dict) or not replayed:
        return ["replay_identity_unavailable"]
    reasons = []
    for key in ("model_version", "active_model_kind"):
        if recorded.get(key) != replayed.get(key):
            reasons.append(f"{key}_differs")
    for key, files in (("code_hash", "code_files"), ("artifact_hash", "artifact_files")):
        if recorded.get(key) != replayed.get(key):
            left, right = _files_by_path(recorded.get(files)), _files_by_path(replayed.get(files))
            changed = sorted(p for p in set(left) | set(right) if left.get(p) != right.get(p))
            if changed:
                reasons.extend(f"{files[:-6]}_changed:{p}" for p in changed)
            else:
                reasons.append(f"{key}_differs")
    return reasons


def compare_record(model, record, market_id):
    from weather.backtesting.replay import parse_built_at, record_target_date, replay_model_identity

    if not record.get("sources"):
        return None
    target = record_target_date(record)
    if target is None or not (l5.FIRST_DATE <= target <= l5.LAST_DATE):
        raise l5.Refused(f"refused: record target {target} outside {l5.FIRST_DATE}..{l5.LAST_DATE}")
    model.set_target_date(target)
    now = parse_built_at(record)
    row = {"kind": "snapshot", "snapshot_id": str(record.get("snapshot_id")), "market_id": market_id,
           "target_date": target.isoformat(), "hour": now.hour if now else None}
    recorded = _int_dist(record.get("recorded_distribution"))
    if not recorded:
        row["error"] = "no_recorded_distribution"
        return row
    try:
        replayed, payload = l5._run(model, record["sources"], now)
    except Exception as exc:  # error row, the run continues
        row["error"] = f"base: {type(exc).__name__}: {exc}"
        return row
    keys = set(recorded) | set(replayed)
    diffs = [abs(recorded.get(k, 0.0) - replayed.get(k, 0.0)) for k in keys]
    row.update({
        "max_abs": max(diffs, default=0.0),
        "l1": sum(diffs),
        "support_equal": set(recorded) == set(replayed),
        "active_model_kind": payload.get("active_model_kind"),
        "recorded_commit": ((record.get("runtime_identity") or {}).get("git_commit") or "")[:12],
        "identity_reasons": identity_reasons(record.get("model_identity"), replay_model_identity(model)),
    })
    return row


def _p99(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))]


def summarize(rows):
    by_market = defaultdict(list)
    for row in rows:
        if row.get("kind") == "snapshot":
            by_market[row["market_id"]].append(row)
    out = {}
    for market, group in sorted(by_market.items()):
        ok = [r for r in group if "error" not in r]
        vals = [r["max_abs"] for r in ok]
        bad = [r for r in ok if r["max_abs"] > TOL]
        reasons = Counter()
        for r in bad:
            reasons.update(r["identity_reasons"] or ["identity_equal"])
            if not r["support_equal"]:
                reasons["support_differs"] += 1
        commits = Counter(r["recorded_commit"] for r in ok)
        out[market] = {
            "n": len(group),
            "errors": len(group) - len(ok),
            "error_kinds": dict(Counter(r["error"].split(":")[0] for r in group if "error" in r)),
            "share_within_tol": (len(ok) - len(bad)) / len(ok) if ok else None,
            "reproduces_99pct": bool(ok) and (len(ok) - len(bad)) / len(ok) >= 0.99,
            "p99_max_abs": _p99(vals),
            "max_max_abs": max(vals, default=None),
            "mismatches": len(bad),
            "top_reasons": reasons.most_common(3),
            "mismatch_identity_equal": sum(1 for r in bad if not r["identity_reasons"]),
            "recorded_commits": commits.most_common(5),
        }
    return out


def run(folders, out_path, *, summary_path=None, model_factory=None, roots=None, emit=print):
    from weather.backtesting.replay import (
        index_records_by_snapshot, is_reconstructed, load_replay_records, record_target_date)

    if model_factory is None:
        from weather.model.toronto_model import TorontoHighTempModel
        model_factory = lambda market_id: TorontoHighTempModel(market_id=market_id)  # noqa: E731
    out = l5.check_out(out_path, allow_existing=True)
    summary_file = l5.check_out(summary_path, allow_existing=True) if summary_path else None
    header = {"kind": "header", "schema": SCHEMA, "tol": TOL}
    rows, done = [], set()
    if out.exists() and out.stat().st_size > 0:
        lines = out.read_text(encoding="utf-8").splitlines()
        if json.loads(lines[0]) != header:
            raise l5.Refused(f"refused: {out} header does not match {header}")
        parsed = []
        for line in lines[1:]:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        attempts = {r["folder"]: r["attempt"] for r in parsed if r.get("kind") == "folder_done"}
        done = set(attempts)
        rows = [r for r in parsed if r.get("folder") in attempts and r.get("attempt") == attempts[r["folder"]]]
        handle = out.open("a", encoding="utf-8", newline="\n")
        if not out.read_bytes().endswith(b"\n"):
            handle.write("\n")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        handle = out.open("w", encoding="utf-8", newline="\n")
        handle.write(json.dumps(header, sort_keys=True) + "\n")
    attempt = datetime.now(timezone.utc).isoformat()
    roots = roots or l5.root_info()
    models, started = {}, time.monotonic()

    def summary():
        return {"schema": SCHEMA, "tol": TOL, "roots": roots, "markets": summarize(rows)}

    try:
        for folder, market_id in folders:
            if folder.name in done:
                continue
            t0 = time.monotonic()
            model = models.setdefault(market_id, model_factory(market_id))
            records = index_records_by_snapshot(load_replay_records(folder))
            folder_rows, error = [], None
            first = next(iter(records.values()), None)
            if first is not None:
                target = record_target_date(first)
                if target is not None:
                    model.set_target_date(target)
                error = l5.hgb_error(model) or l5.climatology_error(model)
            if error:
                folder_rows.append({"kind": "folder_error", "error": error})
            else:
                for snapshot_id in sorted(records):
                    if is_reconstructed(records[snapshot_id]):
                        continue
                    row = compare_record(model, records[snapshot_id], market_id)
                    if row is not None:
                        folder_rows.append(row)
            for row in folder_rows:
                row.update({"folder": folder.name, "attempt": attempt})
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            if not error:
                handle.write(json.dumps({"kind": "folder_done", "folder": folder.name, "attempt": attempt,
                                         "market_id": market_id}, sort_keys=True) + "\n")
            handle.flush()
            rows.extend(folder_rows)
            emit(f"TIMING folder={folder.name} snapshots={len(folder_rows)} "
                 f"seconds={time.monotonic() - t0:.1f} cumulative={time.monotonic() - started:.1f}")
            l5.write_summary(summary_file, summary())
    finally:
        handle.close()
    result = summary()
    l5.write_summary(summary_file, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--config-root", default=None)
    parser.add_argument("--snapshots-root", default=None)
    parser.add_argument("--market", default=None)
    parser.add_argument("--max-folders", type=int, default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary-out", default=None)
    args = parser.parse_args(argv)
    try:
        roots = l5.configure_roots(args.data_root, args.config_root)
        snapshots_root = args.snapshots_root or str(Path(args.data_root) / "snapshots")
        folders = l5.select_folders(snapshots_root, market=args.market, max_folders=args.max_folders)
        result = run(folders, args.out, summary_path=args.summary_out, roots=roots)
    except l5.Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result["markets"], indent=2, sort_keys=True, default=str))
    return 0
