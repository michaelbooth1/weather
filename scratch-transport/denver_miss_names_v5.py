"""Evening-fix B2 root cause, v5: NAMES-only feature comparer, price-free inputs (L16, 2026-11-03).

For master's review; master runs it on the HOST, read-only, on a scratch COPY holding per Denver slug folder ONLY
``features.jsonl`` and ``replay_inputs.jsonl``, from a disposable c32629156 worktree (PYTHONPATH=<worktree>\\src).
Gates nothing in Stage 1. v1-v4 are kept unchanged. Changes from v4 (master's host review of 257f295c, minors):

N1  The weather.paths production-root check runs BEFORE weather.backtesting.replay / weather.model.toronto_model are
    imported (v3 order restored).
N2  Per target snapshot_id only ONE parsed row is retained per file (replay_inputs: the LAST row; features: the FIRST
    row), plus a sha256 per row of the canonical JSON (sort_keys) of the classing projection. DUP_SAME = all those
    hashes equal (byte-identical canonical JSON; a 1 vs 1.0 change counts as DIFFERS). features.jsonl is streamed
    after the rebuild, so its projection uses the compared keys. Memory scales with the number of targets. The
    output records the in-process peak memory (private commit, working set) taken just before writing.
N3  A group with targets but nothing compared is a reported NOTE; the run refuses only if the MISS group has
    nothing compared.

v4 changes from v3 (master's host review of cfd47116), all retained (M9 amended by N3):

B1  Network guard no longer breaks ``ssl``: ssl, http.client, urllib3 and requests are imported BEFORE the guard, and
    ``socket.socket`` is replaced by a SUBCLASS whose constructor raises (so any later ``class X(socket.socket)``
    still works). ``socket.create_connection`` / ``getaddrinfo`` / ``socketpair`` raise too.
M1  Each slug folder and each opened file is resolved; refused if it resolves inside the production root, outside
    --snapshots-root, or anywhere other than <root>/<slug>[/<file>] (closes junctions and symlinked folders/files).
M2  Refuses when WEATHER_MARKET_REGISTRY (market_registry.py:323-327) or any WEATHER_* path-override variable
    (name containing PATH, ROOT, DIR, REGISTRY, FILE, MANIFEST, CAS, POINTER, RELEASE, CONFIG, DATA, ARTIFACT, CACHE)
    is set. Other WEATHER_* variable NAMES present are recorded (never values).
M3  Both slug files are streamed line by line; only rows whose snapshot_id is a target are kept.
M4  Output is written into a temporary sibling directory and renamed; the parent must already exist.
M5  Rows with l1_new_vs_recorded None form their own group ``no_vector``.
M6  model_version and feature_schema_version are reported as HEADER-key differences, apart from features.
M7  Served row = the FIRST features.jsonl row of the snapshot_id (capture time; snapshot_store.py:923-936); later
    duplicates come from the backfill path (:2654-2718). DUP_SAME / DUP_DIFFERS are reported as their own classes.
    The replay record = the LAST replay_inputs.jsonl row, as replay.index_records_by_snapshot (replay.py:82-84) did
    for the host replay; replay duplicates are reported too.
M8  sha256 is computed over exactly the bytes that are parsed (one binary read, line by line).
M9  Missing replay records / served rows are counted per group and the run continues; it refuses only if a group
    that had target snapshots ends with none compared.
Serving status is recorded; c32629156 tracks no release pointer, so the expected status is RESEARCH_UNBOUND,
reported as ``UNBOUND`` (fine for the features path: it reads no release-bound component).

Unchanged from v3: per slug only the allowlisted files are opened (snapshots.jsonl / components.jsonl carry market
prices and are never opened; replay_inputs_reconstructed.jsonl is never opened); --features-only mandatory, no
component path; compared keys = the keys live_feature_record emits (feature_store.py:452-463) for the rebuilt
record, JSON round-tripped as append_jsonl writes (snapshot_store.py:2547-2555); names and counts only, no values,
no outcome field; explicit --slug folders, no walk; prints weather.__file__ and weather.paths roots and refuses the
production root; --max-rows; any unexpected exception exits 1 with the type name only; no bytecode written.

Usage (host):
    set PYTHONPATH=<disposable c32629156 worktree>\\src
    python -B denver_miss_names_v5.py --features-only --replay-jsonl <replay_c32629156_all.jsonl>
        --snapshots-root <scratch copy> --slug <slug> [--slug ...] --max-rows 2000 --out-dir <new folder>
Self-test (synthetic fixtures; imports the real weather chain from PYTHONPATH):
    set PYTHONPATH=<c32629156 tree>\\src
    python -B denver_miss_names_v5.py --self-test
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

# --- B1: import the TLS/HTTP stack first, then guard the network -----------------------------------------
import socket  # noqa: E402
import ssl  # noqa: E402,F401
import http.client  # noqa: E402,F401
try:  # optional in the venv; imported before the guard so their socket subclasses bind to the real class
    import urllib3  # noqa: F401
    import requests  # noqa: F401
except ImportError:  # pragma: no cover
    pass

_REAL_SOCKET = socket.socket


class NetworkDisabledError(RuntimeError):
    pass


def _no_network(*_args, **_kwargs):
    raise NetworkDisabledError("network disabled in denver_miss_names_v5")


class _NoNetworkSocket(_REAL_SOCKET):
    """Still a class (subclassable, as ssl.SSLSocket needs); constructing one raises."""

    def __init__(self, *args, **kwargs):  # noqa: D401
        raise NetworkDisabledError("network disabled in denver_miss_names_v5")


def install_network_guard():
    socket.socket = _NoNetworkSocket            # type: ignore[assignment,misc]
    socket.create_connection = _no_network      # type: ignore[assignment]
    socket.getaddrinfo = _no_network            # type: ignore[assignment]
    socket.socketpair = _no_network             # type: ignore[assignment]


install_network_guard()

import argparse  # noqa: E402
import ctypes  # noqa: E402
import ctypes.wintypes  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import tracemalloc  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

MARKET = "denver"
L1_MATCH = 1e-9
PRODUCTION_ROOT = Path(r"C:\Users\micha\Desktop\github\weather")
ALLOWED_SLUG_FILES = ("features.jsonl", "replay_inputs.jsonl")
HEADER_KEYS = ("model_version", "feature_schema_version")
GROUPS = ("miss", "control", "no_vector")
NUMERIC_KEY = re.compile(r"^-?\d+(?:\.\d+)?(?:[-_ ]?\w{0,3})?$")
FORBIDDEN_FLAG = re.compile(r"(?i)^--?(?:.*component.*|full|with-components|no-features-only)(?:=.*)?$")
PATH_OVERRIDE_ENV = re.compile(
    r"^WEATHER_.*(?:PATH|ROOT|DIR|REGISTRY|FILE|MANIFEST|CAS|POINTER|RELEASE|CONFIG|DATA|ARTIFACT|CACHE)", re.I)


class Refused(Exception):
    pass


# --- helpers -----------------------------------------------------------------------------------------------

def norm(path):
    return str(Path(path).resolve()).lower().rstrip("\\/")


def inside(path, root):
    p, r = norm(path), norm(root)
    return p == r or p.startswith(r + "\\") or p.startswith(r + "/")


def name_of(key):
    key = str(key)
    return "<n>" if NUMERIC_KEY.match(key) else key


def check_env(environ=None):
    environ = os.environ if environ is None else environ
    names = sorted(k for k in environ if k.upper().startswith("WEATHER_"))
    bad = [k for k in names if k.upper() == "WEATHER_MARKET_REGISTRY" or PATH_OVERRIDE_ENV.match(k)]
    if bad:
        raise Refused(f"refused: path-override environment variable(s) set: {bad}")
    return names


def resolve_slug_folder(root, slug):
    """M1: <root>/<slug> must resolve to itself (no junction / symlink), inside root, outside production."""
    root_res = Path(root).resolve()
    folder = Path(root) / slug
    if not folder.is_dir():
        return None
    folder_res = folder.resolve()
    if inside(folder_res, PRODUCTION_ROOT) or not inside(folder_res, root_res) or norm(folder_res) != norm(root_res / slug):
        raise Refused(f"refused: slug folder {slug} resolves outside {root_res} or inside the production root")
    if folder.is_symlink():
        raise Refused(f"refused: slug folder {slug} is a symlink")
    return folder_res


def projection_hash(row, keys):
    """N2: sha256 of the canonical JSON of the classing projection (missing key -> null)."""
    blob = json.dumps({k: row.get(k) for k in keys}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def stream_slug_file(folder_res, root, name, keep_ids, keep="first", hash_keys=()):
    """M1/M3/M8: allowlisted name, resolved in place; streamed; sha256 over the parsed bytes; keep target ids only.
    N2: per target id ONE row is retained (keep='first' or 'last') plus one projection hash per row seen."""
    if name not in ALLOWED_SLUG_FILES:
        raise Refused(f"refused: {name!r} is not an allowed slug file {ALLOWED_SLUG_FILES}")
    path = Path(folder_res) / name
    if path.is_symlink() or not path.is_file():
        raise Refused(f"refused: {name} in {Path(folder_res).name} is missing or not a regular file")
    res = path.resolve()
    if norm(res) != norm(Path(folder_res) / name) or inside(res, PRODUCTION_ROOT) or not inside(res, Path(root).resolve()):
        raise Refused(f"refused: {name} in {Path(folder_res).name} resolves elsewhere")
    digest, size, lines, skipped = hashlib.sha256(), 0, 0, 0
    if keep not in ("first", "last"):
        raise ValueError(keep)
    kept = {}
    with res.open("rb") as handle:
        for raw in handle:
            digest.update(raw)
            size += len(raw)
            text = raw.strip()
            if not text:
                continue
            lines += 1
            try:
                row = json.loads(text.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                skipped += 1        # replay._read_jsonl skips these too (replay.py:59-62)
                continue
            if not isinstance(row, dict):
                skipped += 1
                continue
            snapshot_id = str(row.get("snapshot_id"))
            if snapshot_id in keep_ids:
                entry = kept.get(snapshot_id)
                if entry is None:
                    kept[snapshot_id] = {"row": row, "hashes": [projection_hash(row, hash_keys)]}
                else:
                    entry["hashes"].append(projection_hash(row, hash_keys))
                    if keep == "last":
                        entry["row"] = row
            del row
    meta = {"file": name, "sha256": digest.hexdigest(), "bytes": size, "rows": lines, "undecodable_skipped": skipped}
    return kept, meta


def as_written(record):
    return json.loads(json.dumps(record, sort_keys=True, default=str))


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            return False
        return (math.isnan(fa) and math.isnan(fb)) or fa == fb
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def differing(served, rebuilt, keys):
    names = set()
    for key in keys:
        if key not in rebuilt:
            continue
        if key not in served:
            names.add(f"{name_of(key)} [missing_in_served]")
        elif not same(served[key], rebuilt[key]):
            names.add(name_of(key))
    return names


REPLAY_CLASS_KEYS = ("sources", "built_at", "target_date", "model_version")


def dup_class(entry):
    """N2: from retained hashes only. None for a single row."""
    hashes = entry["hashes"]
    if len(hashes) < 2:
        return None
    return "DUP_SAME" if len(set(hashes)) == 1 else "DUP_DIFFERS"


def compare_slug(root, slug, targets, rebuild):
    """targets: snapshot_id -> (hour, group). Returns the per-slug result (names and counts only)."""
    folder_res = resolve_slug_folder(root, slug)
    if folder_res is None:
        return None
    ids = set(targets)
    replay_kept, replay_meta = stream_slug_file(folder_res, root, "replay_inputs.jsonl", ids,
                                                keep="last", hash_keys=REPLAY_CLASS_KEYS)
    rebuilt = {}
    for snapshot_id in ids:
        entry = replay_kept.get(snapshot_id)
        if entry:
            rebuilt[snapshot_id] = as_written(rebuild(entry["row"]))  # last wins, as index_records_by_snapshot
            entry["row"] = None                                       # N2: drop the replay record once rebuilt
    feature_keys = sorted({k for r in rebuilt.values() for k in r} - set(HEADER_KEYS))
    all_keys = feature_keys + list(HEADER_KEYS)
    feature_kept, feature_meta = stream_slug_file(folder_res, root, "features.jsonl", ids,
                                                  keep="first", hash_keys=all_keys)
    counts = {g: Counter() for g in GROUPS}
    header = {g: Counter() for g in GROUPS}
    by_hour = defaultdict(Counter)
    classes = Counter()
    missing = {g: Counter() for g in GROUPS}
    compared = Counter()
    for snapshot_id, (hour, group) in sorted(targets.items()):
        rep_entry, feat_entry = replay_kept.get(snapshot_id), feature_kept.get(snapshot_id)
        if rep_entry and dup_class(rep_entry):
            classes[f"{group}:REPLAY_{dup_class(rep_entry)}"] += 1
        if not rep_entry:
            missing[group]["replay_record"] += 1
            continue
        if not feat_entry:
            missing[group]["served_feature_row"] += 1
            continue
        compared[group] += 1
        kind = dup_class(feat_entry)
        if kind:
            classes[f"{group}:{kind}"] += 1
        served = feat_entry["row"]                                    # M7: first row = capture time
        names = differing(served, rebuilt[snapshot_id], feature_keys)
        heads = differing(served, rebuilt[snapshot_id], HEADER_KEYS)
        classes[f"{group}:{'DIFFERS' if names else 'NO_DIFFERENCE'}"] += 1
        if heads:
            classes[f"{group}:HEADER_DIFFERS"] += 1
        for name in names:
            counts[group][name] += 1
            by_hour[f"{group}|{name}"][str(hour)] += 1
        for name in heads:
            header[group][name] += 1
    return {
        "files_opened": [replay_meta, feature_meta],
        "targets": dict(Counter(g for _, g in targets.values())),
        "compared": dict(compared),
        "missing": {g: dict(c) for g, c in missing.items() if c},
        "compared_feature_key_count": len(feature_keys),
        "classes": dict(sorted(classes.items())),
        "differing_feature_names": {g: dict(c.most_common()) for g, c in counts.items() if c},
        "header_key_differences": {g: dict(c.most_common()) for g, c in header.items() if c},
        "by_hour": {name: dict(sorted(h.items())) for name, h in sorted(by_hour.items())},
    }


def write_output(out_dir, result):
    """M4: temp sibling directory, then rename; the parent must already exist."""
    out_dir = Path(out_dir)
    parent = out_dir.parent
    if not parent.is_dir():
        raise Refused(f"refused: output parent {parent} does not exist")
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    tmp = parent / f".{out_dir.name}.tmp-{os.getpid()}"
    tmp.mkdir()
    try:
        with (tmp / "denver_miss_names.json").open("xb") as handle:
            handle.write(payload)
        with (tmp / "SHA256SUMS").open("xb") as handle:
            handle.write(f"{digest}  denver_miss_names.json\n".encode("ascii"))
        if out_dir.exists():
            raise Refused(f"refused: {out_dir} appeared meanwhile")
        os.rename(tmp, out_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return digest


def load_weather_chain():
    """The exact import chain of the host run (B1 regression surface). N1: roots checked before replay/model import."""
    import weather
    from weather import paths
    roots = {"weather_file": str(Path(weather.__file__).resolve()), "REPO_ROOT": str(paths.REPO_ROOT.resolve()),
             "DATA_ROOT": str(paths.DATA_ROOT.resolve()), "ARTIFACTS_ROOT": str(paths.ARTIFACTS_ROOT.resolve()),
             "CONFIG_ROOT": str(paths.CONFIG_ROOT.resolve())}
    for label, path in roots.items():
        if inside(path, PRODUCTION_ROOT):
            raise Refused(f"refused: {label} resolves inside the production root {PRODUCTION_ROOT}")
    from weather.backtesting.replay import parse_built_at, record_target_date
    from weather.model.toronto_model import TorontoHighTempModel
    model = TorontoHighTempModel(market_id=MARKET)
    status = str(getattr(model.serving_bundle, "status", None))

    def rebuild(record):
        sources = record.get("sources") or {}
        now = parse_built_at(record)
        target = record_target_date(record)
        if target is not None:
            model.set_target_date(target)
        cutoff = model.effective_intraday_cutoff_hour(now, model.source_data(sources, "wu_history").get("rows") or [])
        return model.live_feature_record(sources, cutoff, captured_at=now, model_version=record.get("model_version"))

    serving = {"status": status, "serving_status": "UNBOUND" if status == "RESEARCH_UNBOUND" else status}
    return roots, serving, rebuild


# --- host run ----------------------------------------------------------------------------------------------

def group_notes(group_targets, group_compared):
    """N3: refuse only if MISS has nothing compared; other empty groups become notes."""
    if not group_compared.get("miss"):
        raise Refused(f"refused: miss group has nothing compared (targets {group_targets.get('miss', 0)})")
    return [f"group {g}: {group_targets[g]} target(s), none compared" for g in GROUPS
            if g != "miss" and group_targets.get(g) and not group_compared.get(g)]


def run(args):
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        raise Refused(f"refused: {out_dir} exists")
    for label, path in (("--snapshots-root", args.snapshots_root), ("--out-dir", args.out_dir),
                        ("--replay-jsonl", args.replay_jsonl)):
        if inside(path, PRODUCTION_ROOT):
            raise Refused(f"refused: {label} resolves inside the production root")
    env_names = check_env()
    slugs = list(dict.fromkeys(args.slug))
    for slug in slugs:
        if "/" in slug or "\\" in slug or slug in {".", ".."} or not slug.startswith("highest-temperature-in-denver"):
            raise Refused(f"refused: not a Denver slug folder name: {slug!r}")
    roots, serving, rebuild = load_weather_chain()
    print(json.dumps({**roots, **serving}, indent=1), file=sys.stderr)

    wanted = defaultdict(dict)
    replay_digest = hashlib.sha256()
    with Path(args.replay_jsonl).open("rb") as handle:
        for raw in handle:
            replay_digest.update(raw)
            if not raw.strip():
                continue
            row = json.loads(raw.decode("utf-8"))
            if row.get("market_id") == MARKET and row.get("event_slug") in slugs:
                l1 = row.get("l1_new_vs_recorded")
                group = "no_vector" if l1 is None else ("miss" if l1 > L1_MATCH else "control")
                wanted[row["event_slug"]][str(row["snapshot_id"])] = (row.get("hour"), group)
    total = sum(len(v) for v in wanted.values())
    if total > args.max_rows:
        raise Refused(f"refused: {total} snapshots exceed --max-rows {args.max_rows}")

    per_slug, group_targets, group_compared = {}, Counter(), Counter()
    for slug in slugs:
        targets = wanted.get(slug) or {}
        if not targets:
            per_slug[slug] = {"replay_rows": 0}
            continue
        result = compare_slug(args.snapshots_root, slug, targets, rebuild)
        if result is None:
            per_slug[slug] = {"folder_missing": True, "targets": dict(Counter(g for _, g in targets.values()))}
            group_targets.update(g for _, g in targets.values())
            continue
        per_slug[slug] = result
        group_targets.update(result["targets"])
        group_compared.update(result["compared"])
    notes = group_notes(group_targets, group_compared)
    totals = {g: Counter() for g in GROUPS}
    header_totals = {g: Counter() for g in GROUPS}
    for result in per_slug.values():
        for g, names in (result.get("differing_feature_names") or {}).items():
            totals[g].update(names)
        for g, names in (result.get("header_key_differences") or {}).items():
            header_totals[g].update(names)
    output = {
        "schema": "evening_fix_denver_miss_names_v5",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "roots": roots,
        "serving": serving,
        "weather_env_names_present": env_names,
        "replay_jsonl_sha256": replay_digest.hexdigest(),
        "allowed_slug_files": list(ALLOWED_SLUG_FILES),
        "served_row_rule": "first features.jsonl row per snapshot_id (capture time); replay record = last row",
        "duplicate_rule": "hash-only: sha256 of canonical JSON (sort_keys) of the classing projection per row",
        "notes": notes,
        "peak_memory_bytes_before_write": peak_memory_bytes(),
        "features_only": True,
        "names_only": True,
        "group_targets": dict(group_targets),
        "group_compared": dict(group_compared),
        "per_slug": per_slug,
        "differing_feature_names_total": {g: dict(c.most_common()) for g, c in totals.items() if c},
        "header_key_differences_total": {g: dict(c.most_common()) for g, c in header_totals.items() if c},
    }
    digest = write_output(out_dir, output)
    print(json.dumps({"out": str(out_dir / "denver_miss_names.json"), "sha256": digest, "serving": serving,
                      "group_compared": dict(group_compared)}, indent=1))


# --- self-test ---------------------------------------------------------------------------------------------

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


_N1_PROBE = r"""
import importlib.util, sys
from pathlib import Path
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("dmn_v5_n1_probe", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from weather import paths
mod.PRODUCTION_ROOT = Path(paths.REPO_ROOT)
heavy = ("weather.backtesting.replay", "weather.model.toronto_model")
before = [m for m in heavy if m in sys.modules]
try:
    mod.load_weather_chain()
    print("NOT_REFUSED")
except mod.Refused:
    after = [m for m in heavy if m in sys.modules]
    print("REFUSED_CLEAN" if not before and not after else "REFUSED_BUT_IMPORTED " + repr(after))
"""

_GUARD_ONLY_PROBE = r"""
import socket, sys
sys.dont_write_bytecode = True
real = socket.socket
class NoNet(real):
    def __init__(self, *a, **k):
        raise RuntimeError("blocked")
socket.socket = NoNet
import ssl, http.client
try:
    import urllib3, requests
except ImportError:
    pass
try:
    socket.socket()
    print("SOCKET_OPENED")
except RuntimeError:
    print("OK")
"""


def self_test():
    results = {}
    secret_values = (987.654321, "SYNTH-VALUE-XYZ")

    def check(name, ok):
        results[name] = "PASS" if ok else "FAIL"

    # B1 (a): after the guard, the TLS/HTTP stack imports and socket.socket is still a class
    import importlib
    for module in ("ssl", "http.client", "urllib3", "requests"):
        try:
            importlib.import_module(module)
            check(f"b1_import_after_guard_{module}", True)
        except Exception:
            check(f"b1_import_after_guard_{module}", False)
    check("b1_socket_is_class", isinstance(socket.socket, type))
    try:
        socket.socket()
        check("b1_socket_blocked", False)
    except NetworkDisabledError:
        check("b1_socket_blocked", True)
    try:
        socket.create_connection(("192.0.2.1", 9))
        check("b1_create_connection_blocked", False)
    except NetworkDisabledError:
        check("b1_create_connection_blocked", True)
    # B1 (b): a fresh interpreter that patches with a subclass FIRST, then imports ssl/http.client/requests cold
    probe = subprocess.run([sys.executable, "-B", "-c", _GUARD_ONLY_PROBE], capture_output=True, text=True, timeout=60)
    check("b1_cold_import_after_subclass_guard", probe.returncode == 0 and probe.stdout.strip() == "OK")
    # B1 (c): the real weather import chain of the host run, and one rebuild on a synthetic empty record
    serving = None
    try:
        roots, serving, rebuild = load_weather_chain()
        check("b1_weather_chain_imports", True)
        check("b1_weather_not_production", not inside(roots["weather_file"], PRODUCTION_ROOT))
        record = rebuild({"sources": {}, "built_at": "2026-01-05T18:00:00-07:00", "target_date": "2026-01-05",
                          "model_version": "synthetic"})
        check("b1_rebuild_on_synthetic_record_returns_dict", isinstance(record, dict) and "cutoff_hour" in record)
        check("serving_status_recorded", serving["serving_status"] == "UNBOUND")
    except Exception as exc:
        check(f"b1_weather_chain_imports ({type(exc).__name__})", False)

    # N1: in a fresh interpreter, a production root equal to this weather tree is refused BEFORE replay/model import
    n1 = subprocess.run([sys.executable, "-B", "-c", _N1_PROBE, str(Path(__file__).resolve())],
                        capture_output=True, text=True, timeout=60)
    check("n1_prod_root_refused_before_replay_import", n1.returncode == 0 and n1.stdout.strip() == "REFUSED_CLEAN")

    tmp = Path(tempfile.mkdtemp(prefix="dmn_v5_selftest_"))
    try:
        root = tmp / "copy"
        root.mkdir()
        slug = "highest-temperature-in-denver-on-january-5-2026"
        folder = root / slug
        folder.mkdir()

        def write(name, rows, target=folder):
            (target / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

        write("replay_inputs.jsonl", [
            {"snapshot_id": s, "sources": {"fake": v}} for s, v in (
                ("s1", {"a": 1.0, "b": "x", "model_version": "m"}),
                ("s2", {"a": 2.0, "b": "y", "model_version": "m"}),
                ("s3", {"a": 3.0, "b": "z", "model_version": "m"}),
                ("s4", {"a": 4.0, "b": "w", "model_version": "m"}),
                ("s5", {"a": 5.0, "b": "v", "model_version": "m"}),
                ("s6", {"a": 6.0, "b": "u", "model_version": "m"}))])
        replay_path = folder / "replay_inputs.jsonl"                  # N2: an earlier, different replay row for s2
        replay_path.write_text(json.dumps({"snapshot_id": "s2", "sources": {"fake": {
            "a": 2.0, "b": "EARLIER", "model_version": "m"}}}) + "\n" + replay_path.read_text(encoding="utf-8"),
            encoding="utf-8")
        write("features.jsonl", [
            {"snapshot_id": "s1", "a": 1.0, "b": "x", "model_version": "m"},                     # no difference
            {"snapshot_id": "s2", "a": secret_values[0], "b": "y", "model_version": "m"},        # one differing key
            {"snapshot_id": "s3", "a": 3.0, "b": "z", "model_version": "m"},                     # DUP_SAME
            {"snapshot_id": "s3", "a": 3.0, "b": "z", "model_version": "m"},
            {"snapshot_id": "s4", "a": 4.0, "b": "w", "model_version": "m"},                     # DUP_DIFFERS:
            {"snapshot_id": "s4", "a": 4.0, "b": secret_values[1], "model_version": "m"},        # first row equal
            {"snapshot_id": "s5", "a": 5.0, "b": "v", "model_version": "OTHER"},                 # header only
        ])                                                                                        # s6: missing served
        (folder / "snapshots.jsonl").write_text('{"snapshot_id": "s1", "bands": []}\n', encoding="utf-8")
        for name in ("snapshots.jsonl", "components.jsonl", "replay_inputs_reconstructed.jsonl", "../features.jsonl"):
            try:
                stream_slug_file(folder.resolve(), root, name, {"s1"})
                check(f"refuse_third_file_{name}", False)
            except Refused:
                check(f"refuse_third_file_{name}", True)
        targets = {"s1": (17, "control"), "s2": (18, "miss"), "s3": (19, "control"), "s4": (20, "miss"),
                   "s5": (21, "no_vector"), "s6": (22, "miss")}
        out = compare_slug(root, slug, targets, lambda r: dict(r["sources"]["fake"]))
        text = json.dumps(out)
        c = out["classes"]
        check("zero_difference", c.get("control:NO_DIFFERENCE") == 2)
        check("one_differing_key", out["differing_feature_names"].get("miss") == {"a": 1})
        check("dup_same", c.get("control:DUP_SAME") == 1)
        check("dup_differs_first_row_compared", c.get("miss:DUP_DIFFERS") == 1 and c.get("miss:NO_DIFFERENCE") == 1)
        check("none_group", out["targets"].get("no_vector") == 1 and out["compared"].get("no_vector") == 1)
        check("header_key_class", out["header_key_differences"] == {"no_vector": {"model_version": 1}}
              and c.get("no_vector:HEADER_DIFFERS") == 1 and c.get("no_vector:NO_DIFFERENCE") == 1)
        check("missing_rows_counted", out["missing"] == {"miss": {"served_feature_row": 1}})
        check("files_opened_only_two", sorted(m["file"] for m in out["files_opened"]) == sorted(ALLOWED_SLUG_FILES))
        check("sha_over_parsed_bytes", out["files_opened"][1]["sha256"]
              == hashlib.sha256((folder / "features.jsonl").read_bytes()).hexdigest())
        # N2: hash-only retention; one row per id; replay keeps LAST, features keep FIRST; classing from hashes
        check("n2_replay_dup_classed_last_row_used", c.get("miss:REPLAY_DUP_DIFFERS") == 1
              and out["differing_feature_names"].get("miss") == {"a": 1})
        feat_kept, _ = stream_slug_file(folder.resolve(), root, "features.jsonl", set(targets), keep="first",
                                        hash_keys=["a", "b", "model_version"])
        rep_kept, _ = stream_slug_file(folder.resolve(), root, "replay_inputs.jsonl", set(targets), keep="last",
                                       hash_keys=list(REPLAY_CLASS_KEYS))
        check("n2_one_row_retained_per_id", all(isinstance(e["row"], dict) and set(e) == {"row", "hashes"}
                                                for e in list(feat_kept.values()) + list(rep_kept.values())))
        check("n2_features_first_row_kept", feat_kept["s4"]["row"]["b"] == "w" and len(feat_kept["s4"]["hashes"]) == 2)
        check("n2_replay_last_row_kept", rep_kept["s2"]["row"]["sources"]["fake"]["b"] == "y"
              and len(rep_kept["s2"]["hashes"]) == 2)
        check("n2_dup_class_from_hashes", dup_class(feat_kept["s3"]) == "DUP_SAME"
              and dup_class(feat_kept["s4"]) == "DUP_DIFFERS" and dup_class(feat_kept["s1"]) is None
              and dup_class(rep_kept["s2"]) == "DUP_DIFFERS")
        # N3: empty non-miss group -> note; empty miss group -> refused
        notes = group_notes(Counter(miss=2, control=3, no_vector=1), Counter(miss=1, no_vector=1))
        check("n3_empty_control_is_note", notes == ["group control: 3 target(s), none compared"])
        try:
            group_notes(Counter(miss=2, control=3), Counter(control=3))
            check("n3_empty_miss_refused", False)
        except Refused:
            check("n3_empty_miss_refused", True)
        check("no_values_in_output", all(str(v) not in text for v in secret_values))
        # junction / symlink folder refused
        outside = tmp / "outside"
        outside.mkdir()
        write("features.jsonl", [], outside)
        write("replay_inputs.jsonl", [], outside)
        link = root / "highest-temperature-in-denver-on-january-6-2026"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True)
        if made.returncode == 0:
            try:
                compare_slug(root, link.name, {"s1": (17, "control")}, lambda r: {})
                check("junction_folder_refused", False)
            except Refused:
                check("junction_folder_refused", True)
            os.rmdir(link)
        else:
            check("junction_folder_refused (mklink failed)", False)
        # WEATHER_* environment
        try:
            check_env({"WEATHER_MARKET_REGISTRY": "x"})
            check("env_market_registry_refused", False)
        except Refused:
            check("env_market_registry_refused", True)
        try:
            check_env({"WEATHER_FORECAST_FANOUT_CAS_ROOT": "x"})
            check("env_path_override_refused", False)
        except Refused:
            check("env_path_override_refused", True)
        check("env_benign_names_recorded", check_env({"WEATHER_WORKSTATION_WRAPPER_ACTIVE": "1"})
              == ["WEATHER_WORKSTATION_WRAPPER_ACTIVE"])
        # streaming memory bound: ~40 MB of non-target rows, traced peak far below the file size
        big = root / "highest-temperature-in-denver-on-january-7-2026"
        big.mkdir()
        filler = json.dumps({"snapshot_id": "x", "pad": "p" * 380})
        with (big / "features.jsonl").open("w", encoding="utf-8") as handle:
            for i in range(100_000):
                handle.write(filler.replace('"x"', f'"n{i}"') + "\n")
            handle.write(json.dumps({"snapshot_id": "t1", "a": 1.0}) + "\n")
        write("replay_inputs.jsonl", [{"snapshot_id": "t1", "sources": {"fake": {"a": 1.0}}}], big)
        size = (big / "features.jsonl").stat().st_size
        tracemalloc.start()
        res = compare_slug(root, big.name, {"t1": (17, "control")}, lambda r: dict(r["sources"]["fake"]))
        _, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        check("streaming_memory_bound", res["compared"].get("control") == 1 and traced_peak < size / 10)
        results_detail = {"streaming_file_bytes": size, "streaming_traced_peak_bytes": traced_peak}
        # output written via temp sibling; parent must exist
        try:
            write_output(tmp / "no-parent" / "out", {"x": 1})
            check("output_parent_must_exist", False)
        except Refused:
            check("output_parent_must_exist", True)
        digest = write_output(tmp / "out", {"x": 1})
        check("output_renamed_from_temp", (tmp / "out" / "denver_miss_names.json").is_file()
              and not list(tmp.glob(".out.tmp-*")) and len(digest) == 64)
        # args
        for argv in (["--features-only", "--with-components"], ["--components"], ["--full"],
                     ["--replay-jsonl", "x", "--snapshots-root", "y", "--slug", "s", "--max-rows", "1", "--out-dir", "z"]):
            check(f"refuse_args_{' '.join(argv)[:40]}", main(argv, _quiet=True) == 2)
        check("prod_root_inside", inside(PRODUCTION_ROOT / "data" / "snapshots", PRODUCTION_ROOT))
        check("prod_root_sibling_not_refused", not inside(Path(str(PRODUCTION_ROOT) + "-wt"), PRODUCTION_ROOT))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    check("tmp_removed", not tmp.exists())
    ok = all(v == "PASS" for v in results.values())
    print(json.dumps({"self_test": "PASS" if ok else "FAIL", "checks": results, "detail": results_detail,
                      "serving": serving, "python": sys.version.split()[0],
                      "peak_memory_bytes": peak_memory_bytes()}, indent=1))
    return 0 if ok else 1


def main(argv=None, _quiet=False):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()
    bad = [a for a in argv if FORBIDDEN_FLAG.match(a)]
    if bad:
        if not _quiet:
            print(f"refused: component/full flags are removed: {bad}", file=sys.stderr)
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
    except Exception as exc:   # unexpected: name only; nothing written before the final rename
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
