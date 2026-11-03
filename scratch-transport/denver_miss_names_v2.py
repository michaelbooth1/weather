"""Evening-fix B2 root cause, v2: NAMES-only comparer for the non-reproduced Denver snapshots (L16, 2026-11-03).

For master's review; master runs it on the HOST no earlier than 2026-11-04 AM, read-only, on a scratch COPY of
only the listed snapshot folders, from a disposable c32629156 worktree. Gates nothing in Stage 1.
(v1, denver_miss_names_v1.py, is kept unchanged.)

What it compares, in memory only, per Denver snapshot of the listed slug folders:
  1. SERVED ``feature_vector`` (snapshots.jsonl) vs the vector the replay commit rebuilds from the captured
     ``sources`` with ``live_feature_record`` (as toronto_model.py:323-328 does at serve time);
  2. SERVED ``distribution_components`` vs the replay NEW arm's component payload
     (lockin_anchor_replay._replay, legacy=False), flattened to dotted paths (skipped with --features-only);
  3. captured source NAMES present in the replay record.
Groups: ``miss`` (l1_new_vs_recorded > 1e-9), ``control_same_slug`` (reproduced, same slug as a miss),
``control_other_slug`` (reproduced, a listed slug with no miss). Output: names with counts per name and local
hour. No value is printed or written; number-like dict keys (bucket temperatures, hours) become ``<n>``.

Guards
  (a) Opens only <snapshots-root>/<slug> for each --slug given; never walks --snapshots-root.
  (b) Prints weather.__file__ and the resolved weather.paths REPO_ROOT / DATA_ROOT / ARTIFACTS_ROOT /
      CONFIG_ROOT first; REFUSES if any of them, or --snapshots-root, or --out-dir, resolves inside the production
      root C:\\Users\\micha\\Desktop\\github\\weather.
  (d) --max-rows: refuses (exit 2, nothing written) if more snapshots would be compared. Any unexpected exception
      exits non-zero before anything is written (output is assembled in memory, written once at the end).
  Sockets are disabled before any repository import; bytecode writing is off; the only write is --out-dir.

(c) Paths the model calls can READ, from code at c32629156 (all relative to the worktree's weather.paths roots):
  - Release binding (toronto_model.py:107, :133-138, :152-200; release_serving.py:842-872):
    ARTIFACTS_ROOT/releases/current_release.json (pointer, artifacts.py:36-37, release_artifacts.py:49-50) and the
    immutable release it names under ARTIFACTS_ROOT/releases/ (verified base-model components, locations_config).
  - Unbound fallback (toronto_model.py:139-150; model_features.py:59-90, :1586-1597; artifacts.py:356-407):
    ARTIFACTS_ROOT/models/hgb/feature_model_hgb<suffix>.pkl, ARTIFACTS_ROOT/models/coefs/feature_model_coefs
    <suffix>.json and late_day_model_coefs<suffix>.json, calibrated_weights / probability_calibration /
    forecast_error_model / settlement_lag_model <suffix>.json, afternoon_residual_centering.json,
    ARTIFACTS_ROOT/manifests/f_family_secondary_artifacts.json, each with its legacy SRC_ROOT/<name> fallback;
    calibration_runtime.py:30-34 module-level defaults of the same names.
  - Model identity fingerprints (model_identity.py:38, :100-106): the same distribution artifacts.
  - Climatology prior (model_climatology.py:102-116, :211-228; market_registry.py:50-52):
    DATA_ROOT/wunderground/kbkf/daily/daily_summary.csv. NOTE: historical daily highs (an outcome-bearing file);
    read into memory only, never output. Not needed with --features-only if the feature path does not touch it.
  - mg_serve_core.py:433 CONFIG_ROOT/locations.json (only on the shadow variant path, off here).
  - Fetch-side caches (model_sources.py:570-578 last-good sources, :2304-2307 nws_points.json under DATA_ROOT/
    wunderground/kbkf/) belong to fetch_* code that the replay never calls.
  LFS: the *.pkl / large artifacts are Git LFS objects; the worktree must take them from a LOCAL-ONLY LFS checkout
  (no network fetch; this script disables sockets, so a missing object fails rather than downloads).
  The script records whether the release binding is BOUND and whether the climatology file exists (never content);
  an environment unlike the host replay's (e.g. unbound, or no climatology copy) makes component diffs spurious.

Usage (host):
    set PYTHONPATH=<disposable c32629156 worktree>\\src
    python -B denver_miss_names_v2.py --replay-jsonl <replay_c32629156_all.jsonl>
        --snapshots-root <scratch copy> --slug <slug> [--slug <slug> ...] --max-rows 2000 --out-dir <new folder>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import socket
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
MARKET = "denver"
L1_MATCH = 1e-9
PRODUCTION_ROOT = Path(r"C:\Users\micha\Desktop\github\weather")
NUMERIC_KEY = re.compile(r"^-?\d+(?:\.\d+)?(?:[-_ ]?\w{0,3})?$")
MAX_DEPTH = 4


class Refused(Exception):
    pass


def _no_network(*_args, **_kwargs):
    raise RuntimeError("network disabled in denver_miss_names_v2")


socket.socket = _no_network            # type: ignore[assignment]
socket.create_connection = _no_network  # type: ignore[assignment]
socket.getaddrinfo = _no_network        # type: ignore[assignment]


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def inside(path, root):
    path, root = Path(path).resolve(), root.resolve()
    p, r = str(path).lower().rstrip("\\/"), str(root).lower().rstrip("\\/")
    return p == r or p.startswith(r + "\\") or p.startswith(r + "/")


def name_of(key):
    key = str(key)
    return "<n>" if NUMERIC_KEY.match(key) else key


def flatten(value, prefix="", depth=0):
    if isinstance(value, dict) and depth < MAX_DEPTH:
        out = {}
        for key, item in value.items():
            path = f"{prefix}.{name_of(key)}" if prefix else name_of(key)
            for sub, leaves in flatten(item, path, depth + 1).items():
                out.setdefault(sub, []).extend(leaves)
        return out
    return {prefix: [value]}


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            return False
        return (math.isnan(fa) and math.isnan(fb)) or fa == fb
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def differing_names(served, replayed):
    s, r = flatten(served or {}), flatten(replayed or {})
    names = set()
    for key in set(s) | set(r):
        if key not in s:
            names.add(f"{key} [replay_only]")
        elif key not in r:
            names.add(f"{key} [served_only]")
        elif len(s[key]) != len(r[key]) or not all(same(a, b) for a, b in zip(s[key], r[key])):
            names.add(key)
    return names


def run(args):
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        raise Refused(f"refused: {out_dir} exists")
    for label, path in (("--snapshots-root", args.snapshots_root), ("--out-dir", args.out_dir),
                        ("--replay-jsonl", args.replay_jsonl)):
        if inside(path, PRODUCTION_ROOT):
            raise Refused(f"refused: {label} resolves inside the production root")

    import weather
    from weather import paths
    roots = {"weather_file": str(Path(weather.__file__).resolve()), "REPO_ROOT": str(paths.REPO_ROOT.resolve()),
             "DATA_ROOT": str(paths.DATA_ROOT.resolve()), "ARTIFACTS_ROOT": str(paths.ARTIFACTS_ROOT.resolve()),
             "CONFIG_ROOT": str(paths.CONFIG_ROOT.resolve())}
    print(json.dumps(roots, indent=1), file=sys.stderr)
    for label, path in roots.items():
        if inside(path, PRODUCTION_ROOT):
            raise Refused(f"refused: {label} resolves inside the production root {PRODUCTION_ROOT}")

    from weather.backtesting.lockin_anchor_replay import _replay
    from weather.backtesting.replay import (index_records_by_snapshot, load_replay_records, parse_built_at,
                                            record_target_date)
    from weather.model.toronto_model import TorontoHighTempModel

    slugs = list(dict.fromkeys(args.slug))
    for slug in slugs:
        if "/" in slug or "\\" in slug or slug in {".", ".."} or not slug.startswith("highest-temperature-in-denver"):
            raise Refused(f"refused: not a Denver slug folder name: {slug!r}")
    wanted = defaultdict(dict)   # slug -> snapshot_id -> (hour, miss)
    for row in read_jsonl(args.replay_jsonl):
        if row.get("market_id") == MARKET and row.get("event_slug") in slugs:
            l1 = row.get("l1_new_vs_recorded")
            wanted[row["event_slug"]][str(row["snapshot_id"])] = (row.get("hour"), l1 is not None and l1 > L1_MATCH)
    total = sum(len(v) for v in wanted.values())
    if total > args.max_rows:
        raise Refused(f"refused: {total} snapshots exceed --max-rows {args.max_rows}")
    missing_slugs = [slug for slug in slugs if slug not in wanted]

    model = TorontoHighTempModel(market_id=MARKET)
    environment = {"serving_bundle_status": str(getattr(model.serving_bundle, "status", None)),
                   "climatology_summary_present": (model.spec.data_root / "daily" / "daily_summary.csv").is_file()}
    groups = ("miss", "control_same_slug", "control_other_slug")
    counts = {kind: {g: Counter() for g in groups} for kind in ("features", "components", "sources")}
    by_hour = {kind: defaultdict(Counter) for kind in ("features", "components")}
    seen = Counter()
    root = Path(args.snapshots_root)
    for slug in slugs:
        targets = wanted.get(slug) or {}
        if not targets:
            continue
        folder = root / slug
        if not folder.is_dir():
            raise Refused(f"refused: listed folder missing under --snapshots-root: {slug}")
        slug_has_miss = any(miss for _, miss in targets.values())
        served = {str(s.get("snapshot_id")): s for s in read_jsonl(folder / "snapshots.jsonl")}
        records = index_records_by_snapshot(load_replay_records(folder))
        for snapshot_id, (hour, miss) in sorted(targets.items()):
            group = "miss" if miss else ("control_same_slug" if slug_has_miss else "control_other_slug")
            snap, record = served.get(snapshot_id), records.get(snapshot_id)
            if snap is None or record is None:
                raise Refused(f"refused: snapshot or replay record missing in {slug} ({group})")
            seen[group] += 1
            sources = record.get("sources") or {}
            for name in sources:
                counts["sources"][group][name_of(name)] += 1
            now = parse_built_at(record)
            target = record_target_date(record)
            if target is not None:
                model.set_target_date(target)
            cutoff = model.effective_intraday_cutoff_hour(
                now, model.source_data(sources, "wu_history").get("rows") or [])
            rebuilt = model.live_feature_record(sources, cutoff, captured_at=now,
                                                model_version=record.get("model_version"))
            for name in differing_names(snap.get("feature_vector"), rebuilt):
                counts["features"][group][name] += 1
                by_hour["features"][f"{group}|{name}"][str(hour)] += 1
            if not args.features_only:
                _, payload, _ = _replay(model, record, legacy=False)
                for name in differing_names(snap.get("distribution_components"), payload):
                    counts["components"][group][name] += 1
                    by_hour["components"][f"{group}|{name}"][str(hour)] += 1

    result = {
        "schema": "evening_fix_denver_miss_names_v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256_file(__file__),
        "roots": roots,
        "environment": environment,
        "replay_jsonl_sha256": sha256_file(args.replay_jsonl),
        "slugs": slugs,
        "slugs_without_replay_rows": missing_slugs,
        "features_only": bool(args.features_only),
        "snapshots_compared": dict(seen),
        "names_only": True,
        "differing_feature_names": {g: dict(c.most_common()) for g, c in counts["features"].items()},
        "differing_component_paths": {g: dict(c.most_common()) for g, c in counts["components"].items()},
        "source_names_present": {g: dict(c.most_common()) for g, c in counts["sources"].items()},
        "by_hour": {kind: {name: dict(sorted(h.items())) for name, h in sorted(table.items())}
                    for kind, table in by_hour.items()},
    }
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    out_dir.mkdir(parents=True)
    out = out_dir / "denver_miss_names.json"
    with out.open("xb") as handle:
        handle.write(payload)
    (out_dir / "SHA256SUMS").write_text(f"{hashlib.sha256(payload).hexdigest()}  {out.name}\n",
                                        encoding="ascii", newline="\n")
    print(json.dumps({"out": str(out), "sha256": hashlib.sha256(payload).hexdigest(),
                      "snapshots_compared": dict(seen), "environment": environment}, indent=1))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-jsonl", required=True)
    parser.add_argument("--snapshots-root", required=True, help="Scratch copy holding only the listed folders.")
    parser.add_argument("--slug", action="append", required=True, help="Denver slug folder name; repeatable.")
    parser.add_argument("--max-rows", type=int, required=True)
    parser.add_argument("--features-only", action="store_true")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    try:
        run(args)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:   # unexpected: name only, no partial output (nothing written before the end)
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
