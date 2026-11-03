"""Evening-fix B2 root cause: NAMES-only comparer for the non-reproduced Denver snapshots (L16, 2026-11-03).

For master's review; runs on the HOST in a lease slot, read-only. Gates nothing in Stage 1.

For every Denver snapshot of the replay's miss dates (non-reproduced = l1_new_vs_recorded > 1e-9, and the
reproduced ones of the same dates as a control), it compares, in memory only:
  1. the SERVED feature vector (snapshots.jsonl ``feature_vector``) with the vector the replay commit
     rebuilds from the captured ``sources`` (``live_feature_record``, as toronto_model.py:323-328 does
     at serve time);
  2. the SERVED ``distribution_components`` with the replay NEW arm's component payload
     (lockin_anchor_replay._replay, legacy=False), flattened to dotted paths;
  3. which captured source NAMES are present in the replay record.
It outputs only column / path / source NAMES with counts per name and local hour, split miss vs control.
No value is printed or written. Dict keys that look like numbers (bucket temperatures, hours) are
collapsed to ``<n>`` so no value leaks through a key.

Guarantees: stdlib plus the repository code on PYTHONPATH (print weather.__file__ first); sockets are
disabled before any repository import; bytecode writing is off; the only write is the new --out-dir.

Usage (host; PYTHONPATH must point at the c32629156 worktree's src):
    python -B denver_miss_names_v1.py --replay-jsonl <replay_c32629156_all.jsonl>
        --snapshots-root <host data\\snapshots> --out-dir <new folder>
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
NUMERIC_KEY = re.compile(r"^-?\d+(?:\.\d+)?(?:[-_ ]?\w{0,3})?$")
MAX_DEPTH = 4


def _no_network(*_args, **_kwargs):
    raise RuntimeError("network disabled in denver_miss_names_v1")


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
    if not Path(path).is_file():
        return rows
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def name_of(key):
    key = str(key)
    return "<n>" if NUMERIC_KEY.match(key) else key


def flatten(value, prefix="", depth=0):
    """dotted-path -> leaf, numeric keys collapsed; lists are leaves."""
    if isinstance(value, dict) and depth < MAX_DEPTH:
        out = {}
        for key, item in value.items():
            path = f"{prefix}.{name_of(key)}" if prefix else name_of(key)
            for sub, leaf in flatten(item, path, depth + 1).items():
                out.setdefault(sub, []).append(leaf)
        return out
    return {prefix: [value]}


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            return False
        if math.isnan(fa) and math.isnan(fb):
            return True
        return fa == fb
    try:
        return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return False


def differing_names(served, replayed):
    """Names whose values differ, plus names on one side only (tagged)."""
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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-jsonl", required=True)
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        print(f"refused: {out_dir} exists", file=sys.stderr)
        return 2

    import weather
    print(f"weather imported from {weather.__file__}", file=sys.stderr)
    from weather.backtesting.lockin_anchor_replay import _replay
    from weather.backtesting.replay import (index_records_by_snapshot, load_replay_records, parse_built_at,
                                            record_target_date)
    from weather.model.toronto_model import TorontoHighTempModel

    # Replay rows: metadata only (snapshot id, slug, hour, the reproduction L1).
    wanted = {}
    miss_dates = set()
    for row in read_jsonl(args.replay_jsonl):
        if row.get("market_id") != MARKET:
            continue
        l1 = row.get("l1_new_vs_recorded")
        wanted[str(row["snapshot_id"])] = (row["event_slug"], row.get("hour"), l1 is not None and l1 > L1_MATCH)
        if l1 is not None and l1 > L1_MATCH:
            miss_dates.add(row["target_date"])
    by_slug = defaultdict(dict)
    for snapshot_id, (slug, hour, miss) in wanted.items():
        by_slug[slug][snapshot_id] = (hour, miss)

    model = TorontoHighTempModel(market_id=MARKET)
    counts = {kind: {"miss": Counter(), "control": Counter()} for kind in ("features", "components", "sources")}
    by_hour = {kind: defaultdict(Counter) for kind in ("features", "components")}
    snapshots_seen = Counter()
    problems = Counter()
    root = Path(args.snapshots_root)
    for slug in sorted(by_slug):
        targets = by_slug[slug]
        if not any(miss for _, miss in targets.values()):
            # control only from the miss dates' own slugs
            continue
        folder = root / slug
        served = {str(s.get("snapshot_id")): s for s in read_jsonl(folder / "snapshots.jsonl")}
        records = index_records_by_snapshot(load_replay_records(folder))
        for snapshot_id, (hour, miss) in sorted(targets.items()):
            group = "miss" if miss else "control"
            snap, record = served.get(snapshot_id), records.get(snapshot_id)
            if snap is None or record is None:
                problems[f"{group}: snapshot or replay record missing"] += 1
                continue
            snapshots_seen[group] += 1
            sources = record.get("sources") or {}
            for name in sources:
                counts["sources"][group][name_of(name)] += 1
            now = parse_built_at(record)
            target = record_target_date(record)
            if target is not None:
                model.set_target_date(target)
            try:
                cutoff = model.effective_intraday_cutoff_hour(
                    now, model.source_data(sources, "wu_history").get("rows") or [])
                rebuilt = model.live_feature_record(sources, cutoff, captured_at=now,
                                                    model_version=record.get("model_version"))
            except Exception as exc:   # name the failure only
                problems[f"{group}: feature rebuild {type(exc).__name__}"] += 1
                rebuilt = None
            if rebuilt is not None:
                for name in differing_names(snap.get("feature_vector"), rebuilt):
                    counts["features"][group][name] += 1
                    by_hour["features"][f"{group}|{name}"][str(hour)] += 1
            try:
                _, payload, _ = _replay(model, record, legacy=False)
            except Exception as exc:
                problems[f"{group}: replay arm {type(exc).__name__}"] += 1
                payload = None
            if payload is not None:
                for name in differing_names(snap.get("distribution_components"), payload):
                    counts["components"][group][name] += 1
                    by_hour["components"][f"{group}|{name}"][str(hour)] += 1

    result = {
        "schema": "evening_fix_denver_miss_names_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256_file(__file__),
        "weather_file": str(Path(weather.__file__).resolve()),
        "replay_jsonl_sha256": sha256_file(args.replay_jsonl),
        "miss_dates": sorted(miss_dates),
        "snapshots_compared": dict(snapshots_seen),
        "problems": dict(problems),
        "names_only": True,
        "differing_feature_names": {g: dict(c.most_common()) for g, c in counts["features"].items()},
        "differing_component_paths": {g: dict(c.most_common()) for g, c in counts["components"].items()},
        "source_names_present": {g: dict(c.most_common()) for g, c in counts["sources"].items()},
        "by_hour": {kind: {name: dict(sorted(h.items())) for name, h in sorted(table.items())}
                    for kind, table in by_hour.items()},
    }
    out_dir.mkdir(parents=True)
    out = out_dir / "denver_miss_names.json"
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    (out_dir / "SHA256SUMS").write_text(f"{sha256_file(out)}  {out.name}\n", encoding="ascii", newline="\n")
    print(json.dumps({"out": str(out), "sha256": sha256_file(out), "snapshots_compared": dict(snapshots_seen),
                      "problems": dict(problems)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
