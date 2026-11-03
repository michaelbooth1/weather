"""Evening-fix B2 root cause, v3: NAMES-only feature comparer, price-free inputs (L16, 2026-11-03).

For master's review; master runs it on the HOST, read-only, on a scratch COPY holding per Denver slug folder ONLY
``features.jsonl`` and ``replay_inputs.jsonl``, from a disposable c32629156 worktree. Gates nothing in Stage 1.
v1 and v2 are kept unchanged. v3 differs from v2 in what it opens:

- Per slug it opens exactly two files, from the allowlist ``ALLOWED_SLUG_FILES``; any other name is refused in code.
  It never opens snapshots.jsonl (its "bands" carry market_yes/market_no/best_bid, snapshot_store.py:775-822, :920),
  components.jsonl (market_yes, snapshot_store.py:2319-2351), replay_inputs_reconstructed.jsonl, or anything else.
- The served vector comes from features.jsonl. At capture, ``SnapshotStore.write`` (snapshot_store.py:680) puts
  the same object ``model.get("feature_vector")`` into the snapshots.jsonl record (:917) and, via
  ``audit_row(base, feature_vector)`` (:923-936; feature_store.py:474-480), into features.jsonl. audit_row keeps
  FEATURE_AUDIT_COLUMNS (feature_store.py:319-330), which hold every key build_live_feature_record emits
  (feature_store.py:452-463); for those keys the vector's value overwrites the base value. Both files are written
  by append_jsonl (snapshot_store.py:2547-2555). The backfill path (:2654-2718) also writes features.jsonl from
  snapshots.jsonl's feature_vector, skipping ids already in features_long.csv, so duplicates are possible:
  they are counted and classed (DUP_SAME / DUP_DIFFERS), never silently resolved.
- The captured replay record is read from replay_inputs.jsonl by a local copy of the captured half of
  replay.load_replay_records / _read_jsonl (replay.py:50-63, :71), so replay_inputs_reconstructed.jsonl (:74) is
  never opened even if present.
- Features only: the component path is removed; any component/full flag is refused.

Compared keys: exactly the keys that ``live_feature_record`` (model_features.py:1249-1255 ->
feature_store.build_live_feature_record :445-464) emits for the rebuilt record, keyed by snapshot_id. The rebuilt
record is JSON round-tripped the way append_jsonl writes (sort_keys, default=str) before comparison.
Output: names of differing keys with counts per group and local hour, duplicate classes, per-slug files opened with
sha256. No values, no outcome field. Number-like names are collapsed to ``<n>``.

Guards: (a) explicit --slug folder names, opened by name, no walk; (b) prints weather.__file__ and weather.paths
roots, refuses any root or input/output inside the production root; (d) --max-rows, non-zero exit on any unexpected
exception, output assembled in memory and written once at the end. Sockets disabled before repository imports; no
bytecode written. The DATA_ROOT climatology probe is dropped (the features path does not read it).

Paths outside the slug folder on this path (static trace, 2026-11-03): CONFIG_ROOT/markets.json at import
(market_registry.py:364-369); ARTIFACTS_ROOT/releases/current_release.json and, if present, the release it names
(release_serving.py:111, :842-875); if absent (RESEARCH_UNBOUND) the unbound artifacts under ARTIFACTS_ROOT
(toronto_model.py:228-273). LFS artifacts must come from a local-only LFS checkout.

Usage (host):
    set PYTHONPATH=<disposable c32629156 worktree>\\src
    python -B denver_miss_names_v3.py --features-only --replay-jsonl <replay_c32629156_all.jsonl>
        --snapshots-root <scratch copy> --slug <slug> [--slug ...] --max-rows 2000 --out-dir <new folder>
Self-test (synthetic fixtures only, no repository import):
    python -B denver_miss_names_v3.py --self-test
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import hashlib
import json
import math
import re
import shutil
import socket
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
MARKET = "denver"
L1_MATCH = 1e-9
PRODUCTION_ROOT = Path(r"C:\Users\micha\Desktop\github\weather")
ALLOWED_SLUG_FILES = ("features.jsonl", "replay_inputs.jsonl")
NUMERIC_KEY = re.compile(r"^-?\d+(?:\.\d+)?(?:[-_ ]?\w{0,3})?$")
FORBIDDEN_FLAG = re.compile(r"(?i)^--?(?:.*component.*|full|with-components|no-features-only)(?:=.*)?$")


class Refused(Exception):
    pass


def _no_network(*_args, **_kwargs):
    raise RuntimeError("network disabled in denver_miss_names_v3")


socket.socket = _no_network            # type: ignore[assignment]
socket.create_connection = _no_network  # type: ignore[assignment]
socket.getaddrinfo = _no_network        # type: ignore[assignment]


# --- helpers -----------------------------------------------------------------------------------------------

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def inside(path, root):
    p, r = str(Path(path).resolve()).lower().rstrip("\\/"), str(Path(root).resolve()).lower().rstrip("\\/")
    return p == r or p.startswith(r + "\\") or p.startswith(r + "/")


def name_of(key):
    key = str(key)
    return "<n>" if NUMERIC_KEY.match(key) else key


def open_slug_file(folder, name):
    """The only way a slug-folder file is read: allowlisted name, directly inside the folder, regular file."""
    if name not in ALLOWED_SLUG_FILES:
        raise Refused(f"refused: {name!r} is not an allowed slug file {ALLOWED_SLUG_FILES}")
    folder = Path(folder)
    path = folder / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve():
        raise Refused(f"refused: {name} in {folder.name} is missing or not a regular file in the folder")
    data = path.read_bytes()
    return data, {"file": name, "sha256": sha256_bytes(data), "bytes": len(data)}


def jsonl_rows(data):
    """Same as replay._read_jsonl (replay.py:50-63): strip, skip blank and undecodable lines."""
    rows, skipped = [], 0
    for line in data.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1
    return rows, skipped


def as_written(record):
    """JSON round-trip as append_jsonl writes (snapshot_store.py:2547-2555: sort_keys, default=str)."""
    return json.loads(json.dumps(record, sort_keys=True, default=str))


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            return False
        return (math.isnan(fa) and math.isnan(fb)) or fa == fb
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def differing_keys(served, rebuilt):
    """Names of rebuilt keys whose served value differs; a key absent from the served row is tagged."""
    names = set()
    for key, value in rebuilt.items():
        if key not in served:
            names.add(f"{name_of(key)} [missing_in_served]")
        elif not same(served[key], value):
            names.add(name_of(key))
    return names


def index_with_duplicates(rows, keys=None):
    """snapshot_id -> last row, plus duplicate classes (keys=None compares whole rows)."""
    by_id = defaultdict(list)
    for row in rows:
        by_id[str(row.get("snapshot_id"))].append(row)
    last, dup_same, dup_differs = {}, set(), set()
    for snapshot_id, group in by_id.items():
        last[snapshot_id] = group[-1]
        if len(group) > 1:
            def project(row):
                return {k: row.get(k) for k in keys} if keys is not None else row
            first = project(group[0])
            if all(same(project(other), first) for other in group[1:]):
                dup_same.add(snapshot_id)
            else:
                dup_differs.add(snapshot_id)
    return last, dup_same, dup_differs


def compare_slug(folder, targets, rebuild):
    """targets: snapshot_id -> (hour, miss). rebuild(record) -> rebuilt feature record (dict)."""
    feat_bytes, feat_meta = open_slug_file(folder, "features.jsonl")
    rep_bytes, rep_meta = open_slug_file(folder, "replay_inputs.jsonl")
    feature_rows, feat_skipped = jsonl_rows(feat_bytes)
    replay_rows, rep_skipped = jsonl_rows(rep_bytes)
    replay_last, rep_dup_same, rep_dup_differs = index_with_duplicates(replay_rows)
    rebuilt_by_id, compared_keys = {}, set()
    for snapshot_id in targets:
        record = replay_last.get(snapshot_id)
        if record is None:
            raise Refused(f"refused: replay record missing in {Path(folder).name}")
        rebuilt_by_id[snapshot_id] = as_written(rebuild(record))
        compared_keys |= set(rebuilt_by_id[snapshot_id])
    served_last, f_dup_same, f_dup_differs = index_with_duplicates(feature_rows, keys=sorted(compared_keys))
    counts = {g: Counter() for g in ("miss", "control")}
    by_hour = defaultdict(Counter)
    classes = Counter()
    for snapshot_id, (hour, miss) in sorted(targets.items()):
        group = "miss" if miss else "control"
        served = served_last.get(snapshot_id)
        if served is None:
            raise Refused(f"refused: served feature row missing in {Path(folder).name}")
        if snapshot_id in f_dup_differs:
            classes[f"{group}:DUP_DIFFERS"] += 1
        elif snapshot_id in f_dup_same:
            classes[f"{group}:DUP_SAME"] += 1
        names = differing_keys(served, rebuilt_by_id[snapshot_id])
        classes[f"{group}:{'DIFFERS' if names else 'NO_DIFFERENCE'}"] += 1
        for name in names:
            counts[group][name] += 1
            by_hour[f"{group}|{name}"][str(hour)] += 1
    return {
        "files_opened": [feat_meta, rep_meta],
        "undecodable_lines_skipped": {"features.jsonl": feat_skipped, "replay_inputs.jsonl": rep_skipped},
        "feature_rows_duplicate_ids": {"DUP_SAME": len(f_dup_same), "DUP_DIFFERS": len(f_dup_differs)},
        "replay_rows_duplicate_ids": {"DUP_SAME": len(rep_dup_same), "DUP_DIFFERS": len(rep_dup_differs)},
        "compared_key_count": len(compared_keys),
        "classes": dict(sorted(classes.items())),
        "differing_feature_names": {g: dict(c.most_common()) for g, c in counts.items()},
        "by_hour": {name: dict(sorted(h.items())) for name, h in sorted(by_hour.items())},
    }


# --- host run ----------------------------------------------------------------------------------------------

def run(args):
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        raise Refused(f"refused: {out_dir} exists")
    for label, path in (("--snapshots-root", args.snapshots_root), ("--out-dir", args.out_dir),
                        ("--replay-jsonl", args.replay_jsonl)):
        if inside(path, PRODUCTION_ROOT):
            raise Refused(f"refused: {label} resolves inside the production root")
    slugs = list(dict.fromkeys(args.slug))
    for slug in slugs:
        if "/" in slug or "\\" in slug or slug in {".", ".."} or not slug.startswith("highest-temperature-in-denver"):
            raise Refused(f"refused: not a Denver slug folder name: {slug!r}")

    import weather
    from weather import paths
    roots = {"weather_file": str(Path(weather.__file__).resolve()), "REPO_ROOT": str(paths.REPO_ROOT.resolve()),
             "DATA_ROOT": str(paths.DATA_ROOT.resolve()), "ARTIFACTS_ROOT": str(paths.ARTIFACTS_ROOT.resolve()),
             "CONFIG_ROOT": str(paths.CONFIG_ROOT.resolve())}
    print(json.dumps(roots, indent=1), file=sys.stderr)
    for label, path in roots.items():
        if inside(path, PRODUCTION_ROOT):
            raise Refused(f"refused: {label} resolves inside the production root {PRODUCTION_ROOT}")
    from weather.backtesting.replay import parse_built_at, record_target_date
    from weather.model.toronto_model import TorontoHighTempModel

    wanted = defaultdict(dict)
    with Path(args.replay_jsonl).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("market_id") == MARKET and row.get("event_slug") in slugs:
                l1 = row.get("l1_new_vs_recorded")
                wanted[row["event_slug"]][str(row["snapshot_id"])] = (row.get("hour"), l1 is not None and l1 > L1_MATCH)
    total = sum(len(v) for v in wanted.values())
    if total > args.max_rows:
        raise Refused(f"refused: {total} snapshots exceed --max-rows {args.max_rows}")

    model = TorontoHighTempModel(market_id=MARKET)
    environment = {"serving_bundle_status": str(getattr(model.serving_bundle, "status", None))}

    def rebuild(record):
        sources = record.get("sources") or {}
        now = parse_built_at(record)
        target = record_target_date(record)
        if target is not None:
            model.set_target_date(target)
        cutoff = model.effective_intraday_cutoff_hour(now, model.source_data(sources, "wu_history").get("rows") or [])
        return model.live_feature_record(sources, cutoff, captured_at=now, model_version=record.get("model_version"))

    per_slug = {}
    root = Path(args.snapshots_root)
    for slug in slugs:
        targets = wanted.get(slug) or {}
        if not targets:
            per_slug[slug] = {"replay_rows": 0}
            continue
        folder = root / slug
        if not folder.is_dir():
            raise Refused(f"refused: listed folder missing under --snapshots-root: {slug}")
        per_slug[slug] = compare_slug(folder, targets, rebuild)
    totals = {g: Counter() for g in ("miss", "control")}
    for result in per_slug.values():
        for group, names in (result.get("differing_feature_names") or {}).items():
            totals[group].update(names)
    result = {
        "schema": "evening_fix_denver_miss_names_v3",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "roots": roots,
        "environment": environment,
        "replay_jsonl_sha256": sha256_bytes(Path(args.replay_jsonl).read_bytes()),
        "allowed_slug_files": list(ALLOWED_SLUG_FILES),
        "features_only": True,
        "names_only": True,
        "per_slug": per_slug,
        "differing_feature_names_total": {g: dict(c.most_common()) for g, c in totals.items()},
    }
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    out_dir.mkdir(parents=True)
    with (out_dir / "denver_miss_names.json").open("xb") as handle:
        handle.write(payload)
    (out_dir / "SHA256SUMS").write_text(f"{sha256_bytes(payload)}  denver_miss_names.json\n",
                                        encoding="ascii", newline="\n")
    print(json.dumps({"out": str(out_dir / "denver_miss_names.json"), "sha256": sha256_bytes(payload),
                      "environment": environment}, indent=1))


# --- self-test (synthetic, no repository import) -----------------------------------------------------------

class PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]


def peak_memory_bytes():
    counters = PMC()
    counters.cb = ctypes.sizeof(PMC)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    query = kernel32.K32GetProcessMemoryInfo
    query.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(PMC), ctypes.wintypes.DWORD]
    query.restype = ctypes.wintypes.BOOL
    if not query(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError(ctypes.get_last_error(), "K32GetProcessMemoryInfo failed")
    return {"peak_working_set": counters.PeakWorkingSetSize, "peak_private_commit": counters.PeakPagefileUsage}


def self_test():
    secret_values = (987.654321, "SYNTH-VALUE-XYZ")
    results = {}
    tmp = Path(tempfile.mkdtemp(prefix="dmn_v3_selftest_"))
    try:
        folder = tmp / "highest-temperature-in-denver-on-january-5-2026"
        folder.mkdir()

        def write(name, rows):
            (folder / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

        # replay records carry the synthetic "sources" the fake rebuild reads
        write("replay_inputs.jsonl", [
            {"snapshot_id": "s1", "sources": {"fake": {"a": 1.0, "b": "x"}}},
            {"snapshot_id": "s2", "sources": {"fake": {"a": 2.0, "b": "y"}}},
            {"snapshot_id": "s3", "sources": {"fake": {"a": 3.0, "b": "z"}}},
            {"snapshot_id": "s4", "sources": {"fake": {"a": 4.0, "b": "w"}}},
        ])
        write("features.jsonl", [
            {"snapshot_id": "s1", "event_slug": "e", "a": 1.0, "b": "x"},                      # no difference
            {"snapshot_id": "s2", "event_slug": "e", "a": secret_values[0], "b": "y"},         # one differing key
            {"snapshot_id": "s3", "event_slug": "e", "a": 3.0, "b": "z"},                      # DUP_SAME
            {"snapshot_id": "s3", "event_slug": "e", "a": 3.0, "b": "z"},
            {"snapshot_id": "s4", "event_slug": "e", "a": 4.0, "b": secret_values[1]},         # DUP_DIFFERS, last equal
            {"snapshot_id": "s4", "event_slug": "e", "a": 4.0, "b": "w"},
        ])
        (folder / "snapshots.jsonl").write_text('{"snapshot_id": "s1", "bands": []}\n', encoding="utf-8")
        (folder / "replay_inputs_reconstructed.jsonl").write_text('{"snapshot_id": "s9"}\n', encoding="utf-8")

        # 1. a third file name is refused, whatever exists in the folder
        for name in ("snapshots.jsonl", "components.jsonl", "replay_inputs_reconstructed.jsonl", "../features.jsonl"):
            try:
                open_slug_file(folder, name)
                results[f"refuse_{name}"] = "FAIL (opened)"
            except Refused:
                results[f"refuse_{name}"] = "PASS"
        # 2-4. classes and names
        targets = {"s1": (17, False), "s2": (18, True), "s3": (19, False), "s4": (20, True)}
        out = compare_slug(folder, targets, lambda record: dict(record["sources"]["fake"]))
        text = json.dumps(out)
        checks = {
            "zero_difference_s1": out["classes"].get("control:NO_DIFFERENCE") == 2,     # s1 and s3
            "one_differing_key_s2": out["differing_feature_names"]["miss"] == {"a": 1},
            "dup_same_s3": out["classes"].get("control:DUP_SAME") == 1,
            "dup_differs_s4": out["classes"].get("miss:DUP_DIFFERS") == 1
            and out["classes"].get("miss:NO_DIFFERENCE") == 1,
            "dup_counts": out["feature_rows_duplicate_ids"] == {"DUP_SAME": 1, "DUP_DIFFERS": 1},
            "files_opened_only_two": [m["file"] for m in out["files_opened"]] == list(ALLOWED_SLUG_FILES),
            "no_values_in_output": all(str(v) not in text for v in secret_values),
            "by_hour_names_only": out["by_hour"] == {"miss|a": {"18": 1}},
        }
        results.update({k: "PASS" if v else "FAIL" for k, v in checks.items()})
        # 5. component flags and a missing --features-only are refused
        for argv in (["--features-only", "--with-components"], ["--components"], ["--full"],
                     ["--replay-jsonl", "x", "--snapshots-root", "y", "--slug", "s", "--max-rows", "1", "--out-dir", "z"]):
            results[f"refuse_args_{' '.join(argv)[:40]}"] = "PASS" if main(argv, _quiet=True) == 2 else "FAIL"
        # 6. production-root refusal
        results["prod_root_inside"] = "PASS" if inside(PRODUCTION_ROOT / "data" / "snapshots", PRODUCTION_ROOT) else "FAIL"
        results["prod_root_sibling"] = "PASS" if not inside(Path(str(PRODUCTION_ROOT) + "-wt"), PRODUCTION_ROOT) else "FAIL"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    results["tmp_removed"] = "PASS" if not tmp.exists() else "FAIL"
    ok = all(v == "PASS" for v in results.values())
    print(json.dumps({"self_test": "PASS" if ok else "FAIL", "checks": results,
                      "peak_memory_bytes": peak_memory_bytes()}, indent=1))
    return 0 if ok else 1


def main(argv=None, _quiet=False):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()
    bad = [a for a in argv if FORBIDDEN_FLAG.match(a)]
    if bad:
        if not _quiet:
            print(f"refused: component/full flags are removed in v3: {bad}", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser()
    parser.add_argument("--features-only", action="store_true", help="Mandatory.")
    parser.add_argument("--replay-jsonl", required=True)
    parser.add_argument("--snapshots-root", required=True, help="Scratch copy: per slug only the two allowed files.")
    parser.add_argument("--slug", action="append", required=True, help="Denver slug folder name; repeatable.")
    parser.add_argument("--max-rows", type=int, required=True)
    parser.add_argument("--out-dir", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if not args.features_only:
        if not _quiet:
            print("refused: --features-only is mandatory", file=sys.stderr)
        return 2
    try:
        run(args)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:   # unexpected: name only; nothing was written before the end
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
