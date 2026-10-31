r"""R-ODC-lin and X13 against the market on the released cells: a kill-only P0 (ledger row 103, lane L16).

Rule ``docs/research/rodc-released-p0-2026-10-31/rule_rodc_released_p0.md`` (sha256 ``RULE_SHA256``) with its dated
Clarification 1 (``CLARIFICATION_SHA256``), which wins where they differ. Research tool, not a production
dependency. It edits no B-bound file; the B-bound modules it imports are named and blob-checked at start.

Arms (K = 2, fixed): **R-ODC-lin (linear surrogate on frozen R-ODC features)** on (low_so_far, dewpoint_c) from
``odc_metar_features.odc_features``, and **X13** on (low_so_far, low_prev_evening, dewpoint_c) from
``ols_floor_ladder.overnight_lows`` plus the odc dewpoint. Each arm is a market-anchored type C tilt
x = mu_m + g, g a frozen linear increment fitted once on Oct-Dec 2021-25 history only (the BASE residual,
BASE = L3's ols_floor per (market, centre, hour) in sample). The statistic is ``mr_sweep.p0_candidate`` (pin
8bb0f9563, three blobs vendored unchanged); the D3 interval is the wider of the date-clustered and the REV-2
circular block-3 bootstrap (``c3_kill_tier.block_counts``).

Stages (run only through ``scripts\ops\workstation_heavy.ps1 -Queue``, after main admits each one; cwd = the run
tree, ``PYTHONPATH=<run tree>\src``)::

    python -m tools.research.released_window.rodc_released_p0 preflight
    python -m tools.research.released_window.rodc_released_p0 fit  --out C:\t\l16\rodc\<new>
    python -m tools.research.released_window.rodc_released_p0 look --out C:\t\l16\rodc\<new> \
        --coef <fit out>\coef.json --coef-sha <sha256 of coef.json> --approval "<coordinator admission ref>"

``preflight`` reads no data: origin, clean tree, rule and blob shas. ``fit`` reads only the L9 Oct-Dec history
caches (and L3's centre 11-24 rows for control C-f). ``look`` is the single look: controls C-a, C-b, C-d, C-e on
the dev layout, the archived row 80 rows and synthetic data; then the r80 release layout and staged export
(features, C-g), then the r80 table (C-c, the restrict identity) and the statistic. Every output goes to a new
``--out`` below ``C:\t\l16\rodc``; receipts are exclusive-create. Evidence class: kill-only; no label here is an
edge claim.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np

SCHEMA = "rodc_released_p0/1"
LEDGER_ROW = 103
TREE = Path(__file__).resolve().parents[3]
RULE_PATH = "docs/research/rodc-released-p0-2026-10-31/rule_rodc_released_p0.md"
RULE_SHA256 = "9bff5c02762a27ef604219b305e6a8043497cbf0316ec2403b879f4ed09a2f11"
CLARIFICATION_PATH = "docs/research/rodc-released-p0-2026-10-31/clarification_1.md"
CLARIFICATION_SHA256 = "064c4f267fab1e70d5b046c00da2b9796adae77031918ce08caee2030cd48be6"

OUT_ROOT = Path(r"C:\t\l16\rodc")
LOOK_RECEIPT = "look_receipt.json"
FIT_RECEIPT = "fit_receipt.json"

# Inputs (read only).
R80_LAYOUT = Path(r"C:\t\r80\build\layout")
R80_LAYOUT_MANIFEST_SHA256 = "d7601613027d42673ca4259bb4df8526022f68d4286655962178d288fa635c42"
R80_EXPORT = Path(r"C:\t\r80")
R80_SUMS_SHA256 = "c0246a6593655da04b7e600385174e5a1d1cd5b36217896cde13c7cceceb73fa"
DEV_LAYOUT = Path(r"C:\swarm\v3layout")
DEV_LAYOUT_MANIFEST_SHA256 = "4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22"
ROW80_ARCHIVE = Path(r"C:\archive\ruled-out\row-80-rise-t3r3-replication")
ROW80_ROWS_SHA256 = "54fd59668d5ebb1881d1e144d62700585c497ea8eadd94e86492b90f15e75679"
ROW80_LABEL_SHA256 = "235736c9dbb3e4f2850ea762043a43cd8cecb7e88375047f57759e655faeda3e"
L9_CACHE = Path(r"C:\t\l9\cache")
L3_OCTDEC = Path(r"C:\t\l3\octdec")

# Git blob shas (sha1 of "blob <len>\0" + bytes) of every weather/tools module this driver imports.
BLOBS = {
    "src/weather/calibration/mr_sweep.py": "f49e38184d62264f9684922b02b4ca2e8923781b",         # pin 8bb0f9563
    "src/weather/calibration/mr_gate.py": "153dd07c12cd20ca079cb4ee9647f9fce99e40e7",          # pin 8bb0f9563
    "src/weather/calibration/loyo_screen.py": "fd9ea5a7a0c8923042d522512771859746e2d55a",      # pin 8bb0f9563
    "src/weather/calibration/odc_metar_features.py": "1cc4d565468bf4959137a8f6f6cec5b10adfce24",  # 0e11b018f
    "src/weather/calibration/ols_floor_ladder.py": "eedd3d32f5044cf797ba0b053afec83d580974be",  # 8167b89a8
    "src/weather/calibration/c3_kill_tier.py": "8f4f9d194dc62cb4cd481e20005ce6ae75d1f879",     # b1d8e65fd
    "src/weather/calibration/r0_ols_floor_challenger.py": "ea743d19fd0bec5eafdcaf6f41bc1886e6d15033",  # B-bound
    "src/weather/model/mg_serve_core.py": "5d1f8bc4c2ddb5d657c7b5ec50b852d2fef11b1b",          # B-bound (odc)
    "src/weather/reporting/scorecards/dev_scorecard.py": "de49bbda2564c7b973e3e39505b8194d77d0e9b0",       # B-bound
    "src/weather/reporting/scorecards/dev_scorecard_data.py": "b84127b3d61e5f82c885d03dd4ec9c87a31d5dcf",  # B-bound
    "src/weather/reporting/scorecards/loss_atlas.py": "80fa8f5605ca0208b2132ed8acceacd90e5b56dd",          # B-bound
    "src/weather/calibration/market_blend.py": "4a35e35b04cab11b27dc33c68fc8b85c4b084337",
    "src/weather/calibration/gap_to_market_atlas.py": "ba7ce305f68b1fa66ef0b30bccfa3408f5f13ffd",
    "src/weather/calibration/pooled_residual_model.py": "a7f9124fc6cb42b0307d9e681b4fef4928758b74",
    "src/weather/model/feature_store.py": "c11b3ca94747b3c1603cbbff9c4eebd4ad83cb4a",
    "src/weather/model/observed_running_max.py": "a141ff3b55e21c097621a9ec21695da1efecc570",
    "src/weather/market/market_registry.py": "c6c8b143a9ded1462ccf6bd32738fa025db4ecdc",
    "tools/research/released_window/served_market_blocks.py": "86b4652c5ac03de43d289ae4cc1e3d6e82544dbf",
}

RELEASE_FIRST, RELEASE_LAST = date(2026, 10, 1), date(2026, 10, 14)
RELEASE_DATES = tuple((RELEASE_FIRST + timedelta(days=i)).isoformat() for i in range(14))
STRATA = {"pre": ("2026-10-01", "2026-10-09"), "post": ("2026-10-10", "2026-10-14")}
EXCLUDED_MARKET_DAYS = frozenset({("austin", "2026-10-03")})
US11 = ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
        "san-francisco", "seattle")
HOURS = tuple(range(7, 13))
OCTDEC_CENTRES = ("10-10", "10-25", "11-09", "11-24", "12-09")
HISTORY_LAST = date(2025, 12, 31)
CONTROL_CENTRE = "11-24"

ARM_RODC = "R-ODC-lin (linear surrogate on frozen R-ODC features)"
ARM_X13 = "X13"
ARMS = {ARM_RODC: ("low_so_far", "dewpoint_c"), ARM_X13: ("low_so_far", "low_prev_evening", "dewpoint_c")}
ARM_UNCOVERED_MARKETS = {ARM_RODC: frozenset({"denver"}), ARM_X13: frozenset()}
MIN_FIT_ROWS = 30

MIN_DATES, MIN_SNAPS = 10, 1000            # row 80's coverage floor
DELTA_EDGE = 0.2236                       # sqrt(0.05), EXHAUSTION_REGISTER section 6
POWER_MIN = 0.5
BH_Q = 0.10
C_C_TOL, C_D_TOL, C_F_TOL = 1e-15, 1e-12, 1e-9
MIN_APPROVAL = 8
NETWORK_MODULES = ("socket", "urllib", "http", "requests", "ssl", "ftplib")

LABEL_UNTESTABLE = "UNTESTABLE"
LABEL_UNTESTABLE_EDGE = "UNTESTABLE at edge"
LABEL_UNTESTABLE_SUB = "UNTESTABLE at sub-edge"
LABEL_KILL = "KILL at edge size"
LABEL_SCREEN = "SCREEN (descriptive, forward prereg only)"
LABEL_NOT_KILLED = "NOT KILLED at edge (descriptive)"
REGISTER_TEXT = {
    ARM_RODC: ("A kill of R-ODC-lin closes only the linear market tilt on these features on these cells. "
               "Row 72's HGB candidate keeps its forward P1."),
    ARM_X13: "A kill of X13 closes it only as a market-residual tilt on these cells.",
}
MECHANISM = {"hypothesis": "the market under-uses overnight-boundary-layer information in the 07-12 morning",
             "falsifier": "the market already prices METAR lows and dewpoint",
             "history_note": "X13 is sub-edge but real on Oct-Dec history (row 95, D3 rerun, "
                             "delta [-0.00169, -0.00058]); not evidence against the market"}
SNAP_ID = re.compile(rb'"snapshot_id":\s*"([^"]+)"')


class Refused(RuntimeError):
    """A guard or control refused; nothing after it ran."""


# ----------------------------------------------------------------------------- hashing and guards

def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha(path):
    body = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest()


def check_blobs(tree=TREE, blobs=None):
    """Every imported module is at its pinned blob (sha1 over the LF working-tree bytes)."""
    blobs = BLOBS if blobs is None else blobs
    bad = {}
    for rel, want in blobs.items():
        p = Path(tree) / rel
        got = git_blob_sha(p) if p.is_file() else None
        if got != want:
            bad[rel] = got
    if bad:
        raise Refused(f"refused: imported module blob mismatch {bad}")
    return dict(blobs)


def check_rule_files(tree=TREE):
    out = {}
    for rel, want in ((RULE_PATH, RULE_SHA256), (CLARIFICATION_PATH, CLARIFICATION_SHA256)):
        got = sha256_file(Path(tree) / rel)
        if got != want:
            raise Refused(f"refused: {rel} sha256 {got} is not the pinned {want}")
        out[rel] = got
    return out


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p))).rstrip("\\/")


def _under(path, root):
    a, b = _norm(path), _norm(root)
    return a == b or a.startswith(b + os.sep)


def check_origin(tree=TREE, environ=None, cwd=None, weather_file=None):
    """The editable-.pth trap: PYTHONPATH must be exactly <tree>\\src, cwd the tree, and ``weather`` imported
    from under <tree>\\src."""
    environ = os.environ if environ is None else environ
    cwd = os.getcwd() if cwd is None else cwd
    if weather_file is None:
        import weather
        weather_file = weather.__file__
    src = Path(tree) / "src"
    pp = environ.get("PYTHONPATH")
    if pp is None or _norm(pp) != _norm(src):
        raise Refused(f"refused: PYTHONPATH is {pp!r}, not {src}")
    if _norm(cwd) != _norm(tree):
        raise Refused(f"refused: cwd {cwd} is not the run tree {tree}")
    if not _under(Path(weather_file).resolve(), src.resolve()):
        raise Refused(f"refused: weather imported from {weather_file}, not under {src}")
    return {"tree": str(tree), "pythonpath": pp, "cwd": str(cwd), "weather_file": str(weather_file)}


def code_state(tree=TREE):
    def git(*args):
        return subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True,
                              check=True).stdout.strip()

    return {"head": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD")}


def require_clean(state, allow_dirty=False):
    if state["dirty"] and not allow_dirty:
        raise Refused("refused: the run tree is dirty")
    return state


def check_out_dir(out, root=OUT_ROOT):
    """``--out`` must not exist and must sit below ``root`` (never equal to it)."""
    if out is None:
        raise Refused("refused: --out is required")
    out = Path(out)
    if not _under(out, root) or _norm(out) == _norm(root):
        raise Refused(f"refused: --out {out} is not below {root}")
    if out.exists():
        raise Refused(f"refused: --out {out} already exists")
    return out


def check_no_prior_look(root=OUT_ROOT):
    root = Path(root)
    prior = sorted(str(p) for p in root.glob(f"*/{LOOK_RECEIPT}")) if root.is_dir() else []
    if prior:
        raise Refused(f"refused: a look already ran ({prior[0]}); there is no second look")
    return True


def check_coef(path, want_sha):
    if not want_sha or not re.fullmatch(r"[0-9a-f]{64}", str(want_sha)):
        raise Refused("refused: --coef-sha (the recorded sha256 of coef.json) is required")
    got = sha256_file(path)
    if got != want_sha:
        raise Refused(f"refused: coef.json sha256 {got} is not --coef-sha {want_sha}")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_exclusive(path, payload):
    with Path(path).open("x", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=1, sort_keys=True, default=_default) + "\n")
    return sha256_file(path)


def _default(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, (set, frozenset, tuple)):
        return sorted(x) if isinstance(x, (set, frozenset)) else list(x)
    raise TypeError(f"not JSON serialisable: {type(x)}")


# ----------------------------------------------------------------------------- fit (history only)

def _usable(rows):
    return [r for r in rows if r.get("forecast_high") is not None]


def base_insample(rows):
    """L3's ols_floor mean, in sample, on one (market, centre, hour) row set: [(row, mu)] (ladder BASE recipe)."""
    from weather.calibration import ols_floor_ladder as lad
    from weather.calibration import r0_ols_floor_challenger as l3

    usable = _usable(rows)
    if len(usable) < len(lad.BASE_FEATURES) + 2:
        return []
    means = lad.fold_means(usable, lad.BASE_FEATURES)
    x = lad.design(usable, lad.BASE_FEATURES, means)
    beta, _ = l3.ols_fit(x, [float(r["actual"]) for r in usable])
    return [(r, l3.ols_predict(beta, xi)) for r, xi in zip(usable, x)]


def arm_fit(samples, columns, min_rows=MIN_FIT_ROWS):
    """OLS of the BASE residual on the centred arm columns (complete cases); None below ``min_rows``."""
    from weather.calibration import r0_ols_floor_challenger as l3

    keep = [(r, res) for r, res in samples if all(r.get(c) is not None for c in columns)]
    if len(keep) < max(min_rows, len(columns) + 2):
        return None
    x = np.array([[float(r[c]) for c in columns] for r, _ in keep], float)
    means = x.mean(axis=0)
    beta, sd = l3.ols_fit(x - means, [res for _, res in keep])
    return {"columns": list(columns), "intercept": float(beta[0]), "beta": [float(b) for b in beta[1:]],
            "means": [float(m) for m in means], "n": len(keep), "resid_sd": float(sd)}


def residual_samples(caches, hours=HOURS):
    """{(market, hour): [(row, actual - BASE)]} pooled over the centres; refuses any non-history date."""
    out = defaultdict(list)
    for c in caches:
        for hour in hours:
            rows = c["hours"].get(str(hour)) or []
            for r in rows:
                if date.fromisoformat(r["date"]) > HISTORY_LAST:
                    raise Refused(f"refused: history cache row {c['market_id']} {r['date']} after {HISTORY_LAST}")
            for r, mu in base_insample(rows):
                out[(c["market_id"], int(hour))].append((r, float(r["actual"]) - mu))
    return out


def fit_coefficients(caches, hours=HOURS, min_rows=MIN_FIT_ROWS):
    samples = residual_samples(caches, hours)
    coef = {}
    for (market, hour), s in sorted(samples.items()):
        for arm, cols in ARMS.items():
            if market in ARM_UNCOVERED_MARKETS[arm]:
                continue
            f = arm_fit(s, cols, min_rows)
            if f is not None:
                coef.setdefault(arm, {})[f"{market}|{hour}"] = f
    return coef, {f"{k[0]}|{k[1]}": len(v) for k, v in sorted(samples.items())}


def control_cf(cache_dir, l3_dir, markets=US11, centre=CONTROL_CENTRE):
    """C-f: the ladder BASE (same design / fold_means / ols_fit as ``base_insample``) equals L3's per-row
    ols_floor log loss on identical row sets at centre 11-24 (EF section 10ac, 5.3e-13); plus the placebo
    N(0,1) column's fitted |beta| (reported)."""
    from weather.calibration import ols_floor_ladder as lad

    out, worst, ok_all = {}, 0.0, True
    for market in markets:
        cache = copy.deepcopy(lad.load_caches(cache_dir, [market], [centre]))
        rows, _ = lad.score_rows(cache, None, ["BASE"], lad.BASE_FEATURES, log=lambda *a, **k: None)
        mine = {(r["hour"], r["validation_date"]): r for r in rows}
        theirs = {}
        for line in (Path(l3_dir) / f"challenger_rows_{market}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                t = json.loads(line)
                theirs[(int(t["hour"]), t["validation_date"])] = t
        common = set(mine) & set(theirs)
        diffs = [abs(mine[k]["BASE_log_loss"] - theirs[k]["ols_floor_log_loss"]) for k in common]
        ok = set(mine) == set(theirs) and bool(diffs) and max(diffs) <= C_F_TOL
        ok_all &= ok
        worst = max([worst] + diffs)
        out[market] = {"rows": len(mine), "rows_l3": len(theirs), "row_sets_equal": set(mine) == set(theirs),
                       "max_abs_log_loss_diff": max(diffs) if diffs else None, "pass": ok}
    if not ok_all:
        raise Refused(f"refused: C-f BASE does not reproduce L3 ols_floor at {centre}: {out}")
    return {"centre": centre, "tolerance": C_F_TOL, "max_abs_diff": worst, "markets": out, "verdict": "PASS"}


def placebo_beta(caches, hours=HOURS):
    """The N(0,1) ladder placebo as a one-column arm: fitted |beta| per (market, hour) (reported, not deciding)."""
    from weather.calibration import ols_floor_ladder as lad

    samples = residual_samples(caches, hours)
    betas = []
    for (market, hour), s in samples.items():
        aug = [(dict(r, placebo=lad.placebo(market, r["date"], hour)), res) for r, res in s]
        f = arm_fit(aug, ("placebo",))
        if f is not None:
            betas.append(abs(f["beta"][0]))
    return {"cells": len(betas), "abs_beta_median": float(np.median(betas)) if betas else None,
            "abs_beta_max": float(np.max(betas)) if betas else None}


def stage_fit(args):
    origin = check_origin()
    state = require_clean(code_state())
    blobs = check_blobs()
    rules = check_rule_files()
    out = check_out_dir(args.out)
    from weather.calibration import ols_floor_ladder as lad

    cache_dir = Path(args.cache_dir)
    cache_files = {f"cache_{m}_{c}.json": sha256_file(cache_dir / f"cache_{m}_{c}.json")
                   for m in US11 for c in OCTDEC_CENTRES}
    cf = control_cf(cache_dir, args.l3_dir)
    caches = lad.load_caches(cache_dir, US11, OCTDEC_CENTRES)
    coef, n_samples = fit_coefficients(caches)
    pl = placebo_beta(caches)
    out.mkdir(parents=True)
    coef_payload = {"schema": SCHEMA + "/coef", "ledger_row": LEDGER_ROW, "arms": coef, "hours": list(HOURS),
                    "centres": list(OCTDEC_CENTRES), "markets": list(US11), "min_fit_rows": MIN_FIT_ROWS,
                    "history_last": HISTORY_LAST.isoformat(), "base": "L3 ols_floor in sample per (market, "
                    "centre, hour); BASE_FEATURES forecast_high, high_so_far, current_temp; impute fc",
                    "cache_sha256": cache_files, "residual_rows": n_samples}
    coef_sha = write_exclusive(out / "coef.json", coef_payload)
    receipt = {"schema": SCHEMA + "/fit", "ledger_row": LEDGER_ROW, "stage": "fit", "origin": origin,
               "code": state, "blobs": blobs, "rules": rules, "module_sha256": sha256_file(__file__),
               "control_cf": cf, "placebo_column": pl, "coef_sha256": coef_sha,
               "cells": {arm: len(v) for arm, v in coef.items()}}
    write_exclusive(out / FIT_RECEIPT, receipt)
    print(json.dumps({"coef_sha256": coef_sha, "cells": receipt["cells"], "control_cf": cf["verdict"],
                      "control_cf_max_abs_diff": cf["max_abs_diff"], "placebo_column": pl}))
    return receipt


# ----------------------------------------------------------------------------- serve-side features (look)

def metar_valid(rec, captured):
    """mr_sweep section 2 for METAR: ok, target_date_match, fetched_at <= capture, report_time <= capture.
    Returns (data, reason)."""
    src = ((rec or {}).get("sources") or {}).get("metar") or {}
    if src.get("ok") is not True:
        return None, "metar_not_ok"
    d = src.get("data") or {}
    if d.get("target_date_match") is not True:
        return None, "target_date_mismatch"
    f, r = _utc(src.get("fetched_at")), _utc(d.get("report_time"))
    if f is None or f > captured:
        return None, "fetched_after_capture"
    if r is None:
        return None, "no_report_time"
    if r > captured:
        return None, "report_after_capture"
    return d, None


def _utc(s):
    if s is None:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(timezone.utc) if t.tzinfo else None


def instants(metar, tz):
    """[(local instant, row)] by odc rule 2 (AWC obsTime, else raw DDHHMMZ, else obs_time); undated rows dropped."""
    from weather.model.observed_running_max import metar_observation_local_time, row_obs_time_local

    raw = {str(i["rawOb"]): i["obsTime"] for i in (metar or {}).get("raw_payload") or []
           if isinstance(i, dict) and i.get("rawOb") and i.get("obsTime") is not None}
    out = []
    for row in (metar or {}).get("rows") or []:
        t = metar_observation_local_time(row, tz, raw) or row_obs_time_local(row, tz)
        if t is not None:
            out.append((t, row))
    return out


def x13_lows(metar, *, target_date, tz, unit, cutoff_hour, now):
    """(low_so_far, low_prev_evening) through ``ols_floor_ladder.overnight_lows`` on the captured METAR rows of D
    and D-1 with an instant <= the capture (and <= h:00 on D), as (minute_of_day, temperature) in memory."""
    from weather.calibration import ols_floor_ladder as lad
    from weather.model.feature_store import plausible_native_temperature, row_temp_native

    now_local = now.astimezone(tz)
    cutoff = datetime.combine(target_date, time(int(cutoff_hour), 0), tzinfo=tz)
    prev_day = target_date - timedelta(days=1)
    day, prev = [], []
    for t, row in instants(metar, tz):
        if t > now_local:
            continue
        v = row_temp_native(row)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v) or not plausible_native_temperature(v, unit):
            continue
        rec = {"minute_of_day": t.hour * 60 + t.minute, "temp_native": v}
        if t.date() == target_date and t <= cutoff:
            day.append(rec)
        elif t.date() == prev_day:
            prev.append(rec)
    if not day:
        return None, None
    return lad.overnight_lows(day, target_date, cutoff_hour, prev, None)


def snapshot_features(rec, *, market, target_date, local_hour, captured, tz, unit):
    """Arm columns for one layout snapshot (as_of_capture; cutoff = its local hour)."""
    from weather.calibration import odc_metar_features as odc

    d, reason = metar_valid(rec, captured)
    if d is None:
        return {"reason": reason}
    f = odc.odc_features(d, target_date=target_date, tz=tz, unit=unit, cutoff_hour=local_hour, now=captured)
    kept, _ = odc.kept_rows(d, target_date=target_date, tz=tz, unit=unit, cutoff_hour=local_hour, now=captured)
    temps = [r[2] for r in kept if r[2] is not None]
    from weather.model.mg_serve_core import wu_whole_f

    current = wu_whole_f(temps[-1], "half_up") if temps else None
    lo, lo_prev = x13_lows(d, target_date=target_date, tz=tz, unit=unit, cutoff_hour=local_hour, now=captured)
    return {"reason": f["reason"], "odc_low_so_far": f["low_so_far"], "dewpoint_c": f["dewpoint_c"],
            "current_temp": current, "x13_low_so_far": lo, "low_prev_evening": lo_prev,
            "n_rows": f["n_rows"], "skipped": f["skipped"]}


def arm_columns(arm, feats):
    if arm == ARM_RODC:
        return {"low_so_far": feats.get("odc_low_so_far"), "dewpoint_c": feats.get("dewpoint_c")}
    return {"low_so_far": feats.get("x13_low_so_far"), "low_prev_evening": feats.get("low_prev_evening"),
            "dewpoint_c": feats.get("dewpoint_c")}


def increment(coef_cell, cols):
    """g = sum_j beta_j (col_j - mean_j); None when any column is missing or the cell has no fit."""
    if coef_cell is None:
        return None
    vals = [cols.get(c) for c in coef_cell["columns"]]
    if any(v is None for v in vals):
        return None
    return float(sum(b * (float(v) - m) for b, v, m in zip(coef_cell["beta"], vals, coef_cell["means"])))


def control_cg(snaps_feats):
    """C-g (label-free): odc ``check_bounds`` per (market, date) over the last snapshot of each hour, and
    low_so_far <= the layout's high_so_far wherever both exist."""
    from weather.calibration import odc_metar_features as odc

    by_cell = defaultdict(dict)
    violations = []
    for s in sorted(snaps_feats, key=lambda s: s["captured"]):
        f = s["feats"]
        low = f.get("odc_low_so_far")
        hsf = s.get("high_so_far")
        if low is not None and hsf is not None and math.isfinite(hsf) and low > hsf + odc.TOL:
            violations.append((s["market"], s["date"], s["local_hour"], "layout_high_so_far", low, hsf))
        by_cell[(s["market"], s["date"])][s["local_hour"]] = {
            "low_so_far": low, "current_temp": f.get("current_temp"),
            "high_so_far": hsf if hsf is not None and math.isfinite(hsf) else None}
    checked, refused = 0, []
    for cell, by_hour in sorted(by_cell.items()):
        try:
            checked += odc.check_bounds(by_hour)
        except odc.OdcMetarRefused as exc:
            refused.append((cell, str(exc)))
    if violations or refused:
        raise Refused(f"refused: C-g feature bounds failed: {violations[:3]} {refused[:3]}")
    return {"cells": len(by_cell), "hours_checked": checked, "verdict": "PASS"}


def read_export(root, sums_sha, wanted):
    """Stream every replay_inputs.jsonl of the wanted slugs once, hashing as it reads (refuses on a mismatch with
    the export SHA256SUMS), and return {row_key: record} for the wanted snapshots, plus malformed lines."""
    root = Path(root)
    sums_path = root / "SHA256SUMS"
    if sha256_file(sums_path) != sums_sha:
        raise Refused(f"refused: export SHA256SUMS is not {sums_sha}")
    listed = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, rel = line.split(None, 1)
            listed[rel.strip().lstrip("*")] = digest
    by_slug = defaultdict(dict)
    for rk, slug in wanted.items():
        by_slug[slug][rk.split("|", 1)[1]] = rk
    recs, malformed, hashed = {}, [], {}
    for slug in sorted(by_slug):
        rel = f"data/snapshots/{slug}/replay_inputs.jsonl"
        if rel not in listed:
            malformed.append({"slug": slug, "missing_from_sums": True})
            continue
        ids = by_slug[slug]
        h = hashlib.sha256()
        with (root / rel).open("rb") as fh:
            for lineno, line in enumerate(fh, 1):
                h.update(line)
                m = SNAP_ID.search(line, 0, 16384)
                sid = m.group(1).decode() if m else None
                if sid not in ids:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    malformed.append({"slug": slug, "line": lineno})
                    continue
                if rec.get("snapshot_id") == sid:
                    recs[ids[sid]] = rec
        hashed[rel] = h.hexdigest()
        if hashed[rel] != listed[rel]:
            raise Refused(f"refused: {rel} sha256 differs from the export SHA256SUMS")
    return recs, malformed, hashed


# ----------------------------------------------------------------------------- statistic, D3 and labels

def wider_interval(sums_c, sums_pl, n_dates):
    """Date-clustered (mr_sweep, 10,000 draws) and REV-2 circular block-3 (c3_kill_tier, 2,000) intervals of
    Delta through the unchanged ``mr_sweep.paired_delta``; the wider bounds and the larger bootstrap SD."""
    from weather.calibration import c3_kill_tier as c3
    from weather.calibration import mr_sweep as sw

    dc_counts, b3_counts = sw.boot_counts(n_dates), c3.block_counts(n_dates)
    dc, b3 = sw.paired_delta(sums_c, sums_pl, dc_counts), sw.paired_delta(sums_c, sums_pl, b3_counts)
    se_dc, se_b3 = _delta_sd(sums_c, sums_pl, dc_counts), _delta_sd(sums_c, sums_pl, b3_counts)
    lo = None if None in (dc["ci95"][0], b3["ci95"][0]) else min(dc["ci95"][0], b3["ci95"][0])
    hi = None if None in (dc["ci95"][1], b3["ci95"][1]) else max(dc["ci95"][1], b3["ci95"][1])
    se = None if None in (se_dc, se_b3) else max(se_dc, se_b3)
    return {"delta": dc["delta"], "p_one_sided": dc["p_one_sided"], "ci95_date_clustered": dc["ci95"],
            "ci95_block3": b3["ci95"], "ci95_wider": [lo, hi], "se_date_clustered": se_dc, "se_block3": se_b3,
            "se_wider": se, "p_one_sided_block3": b3["p_one_sided"], "valid_draws_block3": b3["valid_draws"],
            "power_at_edge": c3.power_at(DELTA_EDGE, se), "rho_c": dc["rho_c"], "rho_c_ci95": dc["rho_c_ci95"],
            "rho_pl_mean": dc["rho_pl_mean"], "rho_pl_ci95": dc["rho_pl_ci95"]}


def _delta_sd(sums_c, sums_pl, counts):
    """SD (ddof 1) of the paired Delta replicates (as row 80's label)."""
    from weather.calibration import mr_sweep as sw

    rho_c = sw.mg._rho(*(counts @ sums_c.T).T)
    j_b = np.arange(len(counts)) % len(sums_pl)
    pl = np.empty(len(counts))
    for j, s in enumerate(sums_pl):
        pl[j_b == j] = sw.mg._rho(*(counts[j_b == j] @ s.T).T)
    d = rho_c - pl
    d = d[np.isfinite(d)]
    return float(np.std(d, ddof=1)) if len(d) > 1 else None


def label_for(testable, power, upper, lower, bh_reject, edge=DELTA_EDGE, power_min=POWER_MIN):
    """Rule section 4 order: coverage, in-run power, KILL, SCREEN, NOT KILLED."""
    if not testable:
        return LABEL_UNTESTABLE
    if power is None or power < power_min:
        return LABEL_UNTESTABLE_EDGE if upper is not None and upper >= edge else LABEL_UNTESTABLE_SUB
    if upper is not None and upper < edge:
        return LABEL_KILL
    if bh_reject and lower is not None and lower > 0:
        return LABEL_SCREEN
    return LABEL_NOT_KILLED


def bh_table(pvals, q=BH_Q):
    from weather.calibration import c3_kill_tier as c3
    from weather.calibration import mr_sweep as sw

    adj, rej = sw.bh_adjust(pvals, q)
    rej_c3 = c3.bh(pvals, q)
    if [bool(r) for r in rej] != [bool(r) for r in rej_c3]:
        raise Refused("refused: the two BH implementations disagree")
    return [float(a) for a in adj], [bool(r) for r in rej]


def control_cd(archive=ROW80_ARCHIVE):
    """C-d: row 80's label intervals and SEs reproduce from its archived rows.jsonl to 1e-12."""
    rows_p, label_p = archive / "outputs" / "look" / "rows.jsonl", archive / "label" / "label.json"
    if sha256_file(rows_p) != ROW80_ROWS_SHA256 or sha256_file(label_p) != ROW80_LABEL_SHA256:
        raise Refused("refused: C-d row 80 rows or label sha mismatch")
    rows = sorted((json.loads(x) for x in rows_p.read_text(encoding="utf-8").splitlines() if x.strip()),
                  key=lambda r: r["date"])
    label = json.loads(label_p.read_text(encoding="utf-8"))
    sums_c = np.array([r["sums_c"] for r in rows], float).T
    sums_pl = [np.array([r["sums_pl"][j] for r in rows], float).T for j in range(len(rows[0]["sums_pl"]))]
    iv = wider_interval(sums_c, sums_pl, len(rows))
    pairs = {"ci95_date_clustered": (iv["ci95_date_clustered"], label["ci95_date_clustered"]),
             "ci95_block3": (iv["ci95_block3"], label["ci95_block3_circular"]),
             "se_date_clustered": ([iv["se_date_clustered"]], [label["se_date_clustered"]]),
             "se_block3": ([iv["se_block3"]], [label["se_block3_circular"]]),
             "delta": ([iv["delta"]], [label["delta"]])}
    worst = max(abs(a - b) for mine, theirs in pairs.values() for a, b in zip(mine, theirs))
    if worst > C_D_TOL:
        raise Refused(f"refused: C-d does not reproduce row 80's label (max diff {worst})")
    return {"max_abs_diff": worst, "tolerance": C_D_TOL, "dates": len(rows), "verdict": "PASS"}


def planted_toy(kappa, n_dates=14, per_date=300, seed=20261031):
    """Synthetic per-date sufficient sums: x = kappa * e + noise, placebos independent of e."""
    from weather.calibration import mr_sweep as sw

    rng = np.random.default_rng(seed)
    didx = np.repeat(np.arange(n_dates), per_date)
    e = rng.normal(0, 0.3, len(didx))
    x = kappa * e + rng.normal(0, 0.1, len(didx))
    sums_c = sw.date_sums(x, e, didx, n_dates)
    sums_pl = [sw.date_sums(rng.normal(0, x.std(), len(didx)), e, didx, n_dates) for _ in sw.PLACEBO_SEEDS]
    return wider_interval(sums_c, sums_pl, n_dates)


def control_ce():
    """C-e: the C3 toys (positive / negation / null) and a planted toy on the mr_sweep statistic."""
    from weather.calibration import c3_kill_tier as c3

    k3 = c3.run_k3()
    planted, null = planted_toy(1.0), planted_toy(0.0)
    checks = {"c3_k3_passed": bool(k3["passed"]),
              "planted_lower_above_0": planted["ci95_wider"][0] is not None and planted["ci95_wider"][0] > 0,
              "null_covers_0": null["ci95_wider"][0] is not None and null["ci95_wider"][0] <= 0
              <= null["ci95_wider"][1]}
    if not all(checks.values()):
        raise Refused(f"refused: C-e synthetic controls failed {checks}")
    return {"checks": checks, "planted_ci95_wider": planted["ci95_wider"], "null_ci95_wider": null["ci95_wider"],
            "verdict": "PASS"}


def control_cc(t, geo):
    """C-c (w = 0 / zero-tilt identity): g = 0 gives c = m on every band, and every derived placebo equals m."""
    from weather.calibration import mr_sweep as sw

    covered = np.ones(len(t.snaps), bool)
    s = sw.band_signal("C", 1, geo["mu"].copy(), t, geo)
    c, _ = sw.tilt(t, geo, s, covered)
    m = t.p_market
    c_err = float(np.max(np.abs(c - m))) if len(c) else 0.0
    # The placebo is m + (c(d') - m(d')) = m, then clipped to [EPS, 1] and renormalised to sum(m): it equals m
    # exactly on snapshots with every m >= EPS, and the clip-renormalised m elsewhere (disclosed, counted).
    from weather.calibration import market_blend as mb

    clipped_snap = np.bincount(t.band_snap, weights=(m < mb.EPS).astype(float), minlength=len(t.snaps)) > 0
    raw = np.clip(m, mb.EPS, 1.0)
    tot_m = np.bincount(t.band_snap, weights=m, minlength=len(t.snaps))
    tot_r = np.bincount(t.band_snap, weights=raw, minlength=len(t.snaps))
    expected = np.where(clipped_snap[t.band_snap], raw * np.repeat(tot_m / tot_r, t.n), m)
    pl_err, pl_err_unclipped = 0.0, 0.0
    unclipped = ~clipped_snap[t.band_snap]
    for seed in sw.PLACEBO_SEEDS:
        pl, _ = sw.disagreement_placebo(t, c, seed)
        if len(pl):
            pl_err = max(pl_err, float(np.max(np.abs(pl - expected))))
            if unclipped.any():
                pl_err_unclipped = max(pl_err_unclipped, float(np.max(np.abs(pl - m)[unclipped])))
    ok = c_err <= C_C_TOL and pl_err <= C_C_TOL
    if not ok:
        raise Refused(f"refused: C-c zero-tilt identity failed (c {c_err}, placebo {pl_err})")
    return {"max_abs_c_minus_m": c_err, "max_abs_placebo_minus_expected": pl_err,
            "max_abs_placebo_minus_m_unclipped_snapshots": pl_err_unclipped,
            "snapshots_with_m_below_eps": int(clipped_snap.sum()), "tolerance": C_C_TOL, "verdict": "PASS"}


def control_restrict_identity(t):
    """C-e (fit = score, row 80): with fit table = score table the restriction is the identity."""
    from weather.calibration import market_blend as mb

    v = np.arange(len(t.bands), dtype=float)
    snap = np.arange(len(t.snaps)) % 2 == 0
    ok = bool(np.array_equal(mb.restrict(t, t, v), v)) and bool(np.array_equal(mb.restrict_snap(t, t, snap), snap))
    if not ok:
        raise Refused("refused: fit = score restriction is not the identity")
    return {"verdict": "PASS"}


def subgroup_deltas(arm, values, t, geo, counts, score_dates, donors, res):
    """Per-hour (07..12) and per-stratum (pre / post) Delta (reported, not deciding), from the same c, placebos
    and population as ``p0_candidate`` (recomputed and checked against its pooled Delta)."""
    from weather.calibration import market_blend as mb
    from weather.calibration import mr_sweep as sw

    covered = np.isfinite(values)
    s = sw.band_signal("C", 1, np.where(covered, values, np.nan), t, geo)
    c, _ = sw.tilt(t, geo, s, covered)
    cov_f = np.repeat(covered.astype(float), t.n)
    pls, donor_ok = [], np.ones(len(t.snaps), bool)
    for seed in sw.PLACEBO_SEEDS:
        pl, _ = sw.disagreement_placebo(t, c, seed, donors[seed])
        donor_ok &= np.bincount(t.band_snap, weights=cov_f[donors[seed][0]], minlength=len(t.snaps)) == t.n
        pls.append(pl)
    pop = mb.restrict_snap(t, t, covered & donor_ok)
    e = t.y - t.p_market
    nd = len(score_dates)
    didx = np.searchsorted(score_dates, t.snaps.date.astype(str).to_numpy())[t.band_snap]
    band = pop[t.band_snap]
    whole = sw.paired_delta(sw.date_sums((c - t.p_market)[band], e[band], didx[band], nd),
                            [sw.date_sums((p - t.p_market)[band], e[band], didx[band], nd) for p in pls], counts)
    if abs(whole["delta"] - res["p0"]["delta"]) > 1e-12:
        raise Refused(f"refused: {arm} subgroup recomputation does not reproduce the pooled Delta")
    dates = t.snaps.date.astype(str).to_numpy()
    stratum = np.where(dates <= STRATA["pre"][1], "pre", "post")
    hours = np.array([f"{h:02d}" for h in t.local_hour])
    return {"by_hour": sw._subgroups(hours, pop, t, c, pls, e, didx, nd, counts),
            "by_stratum": sw._subgroups(stratum, pop, t, c, pls, e, didx, nd, counts)}


def stage_look(args):
    origin = check_origin()
    state = require_clean(code_state())
    blobs = check_blobs()
    rules = check_rule_files()
    if not args.approval or len(args.approval.strip()) < MIN_APPROVAL:
        raise Refused("refused: --approval needs the coordinator's admission reference for this look")
    check_no_prior_look()
    out = check_out_dir(args.out)
    coef = check_coef(args.coef, args.coef_sha)

    import pandas as pd

    from weather.calibration import mr_gate as mg
    from weather.calibration import mr_sweep as sw
    from weather.market.market_registry import spec_for_id
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from tools.research.released_window import served_market_blocks as smb

    if data.DEV_LAST != date(2026, 9, 29):
        raise Refused(f"refused: dev scorecard DEV_LAST is {data.DEV_LAST} before the controls")
    r80_manifest = R80_LAYOUT / data.MANIFEST
    dev_manifest = DEV_LAYOUT / data.MANIFEST
    if sha256_file(r80_manifest) != R80_LAYOUT_MANIFEST_SHA256 or sha256_file(dev_manifest) != \
            DEV_LAYOUT_MANIFEST_SHA256:
        raise Refused("refused: a layout manifest sha changed before the run")

    # Controls on the dev layout (<= 09-29), the archived row 80 rows and synthetic data: no r80 label or price.
    controls = {"C-a": smb.atlas_positive_control(DEV_LAYOUT)}
    _, _, _, _, fit_dev, score_dev = mg.build_tables(DEV_LAYOUT)
    controls["C-b"] = mg.market_controls(fit_dev, score_dev)
    del fit_dev, score_dev
    controls["C-d"] = control_cd()
    controls["C-e"] = control_ce()

    # The release layout (local target dates 10-01..10-14), Austin 10-03 dropped.
    smb.check_release_manifest(R80_LAYOUT)
    with smb.released_dev_last(RELEASE_LAST) as override:
        lay = data.load_layout(R80_LAYOUT, RELEASE_FIRST, RELEASE_LAST)
    if lay.manifest_sha256 != R80_LAYOUT_MANIFEST_SHA256:
        raise Refused("refused: the release layout changed after the manifest check")
    dropped = smb.drop_excluded(lay)
    dates = sorted(str(d) for d in lay.dates)
    if not set(dates) <= set(RELEASE_DATES):
        raise Refused(f"refused: layout dates outside 10-01..10-14: {sorted(set(dates) - set(RELEASE_DATES))}")
    pairs = set(zip(lay.snaps.market.astype(str), lay.snaps.date.astype(str)))
    if pairs & EXCLUDED_MARKET_DAYS:
        raise Refused("refused: Austin 10-03 is still in the population")

    # Capture-time features from the staged export (label-free, price-free).
    snaps = lay.snaps
    sel = snaps[snaps.local_hour.astype(int).isin(HOURS)]
    wanted = dict(zip(sel.row_key.astype(str), sel.event_slug.astype(str)))
    recs, malformed, hashed = read_export(R80_EXPORT, R80_SUMS_SHA256, wanted)
    feats, reasons, snaps_feats = {}, defaultdict(int), []
    for r in sel.itertuples(index=False):
        spec = spec_for_id(str(r.market))
        captured = _utc(r.captured_at_utc)
        rec = recs.get(str(r.row_key))
        if rec is None or captured is None:
            reasons["no_record" if rec is None else "no_capture_time"] += 1
            continue
        f = snapshot_features(rec, market=str(r.market), target_date=date.fromisoformat(str(r.date)),
                              local_hour=int(r.local_hour), captured=captured, tz=spec.tz, unit=spec.unit)
        reasons[f.get("reason") or "ok"] += 1
        feats[str(r.row_key)] = f
        hsf = pd.to_numeric(pd.Series([getattr(r, "high_so_far", None)]), errors="coerce").iloc[0]
        snaps_feats.append({"market": str(r.market), "date": str(r.date), "local_hour": int(r.local_hour),
                            "captured": captured, "feats": f, "high_so_far": float(hsf)})
    controls["C-g"] = control_cg(snaps_feats)

    # The r80 table (labels and prices are read from here on).
    t = sc.Table(lay, dates)
    geo = sw.band_geometry(t)
    controls["C-c"] = control_cc(t, geo)
    controls["C-e"]["fit_equals_score"] = control_restrict_identity(t)
    sw.MIN_DATES, sw.MIN_SNAPS = MIN_DATES, MIN_SNAPS
    score_dates = np.array(dates)
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(t, seed) for seed in sw.PLACEBO_SEEDS}
    keys, hours, markets = t.snaps.row_key.astype(str).to_numpy(), t.local_hour, t.markets
    results, rows_out, pvals = {}, [], []
    for arm in ARMS:
        g = np.full(len(keys), np.nan)
        for i, (k, h, mk) in enumerate(zip(keys, hours, markets)):
            if int(h) not in HOURS or mk in ARM_UNCOVERED_MARKETS[arm] or k not in feats:
                continue
            inc = increment(coef["arms"].get(arm, {}).get(f"{mk}|{int(h)}"), arm_columns(arm, feats[k]))
            if inc is not None:
                g[i] = inc
        res, _ = sw.p0_candidate(arm, "C", 1, geo["mu"] + g, t, t, geo, counts, score_dates, donors)
        arm_rows = res.pop("_rows", None) or []
        entry = {"result": res, "covered_snapshots": int(np.isfinite(g).sum())}
        if res["testable"]:
            sums_c = np.array([r["sums_c"] for r in arm_rows], float).T
            sums_pl = [np.array([r["sums_pl"][j] for r in arm_rows], float).T for j in range(len(sw.PLACEBO_SEEDS))]
            iv = wider_interval(sums_c, sums_pl, len(score_dates))
            if abs(iv["delta"] - res["p0"]["delta"]) > 1e-12 or abs(iv["p_one_sided"] -
                                                                     res["p0"]["p_one_sided"]) > 1e-12:
                raise Refused(f"refused: {arm} D3 rows do not reproduce p0_candidate")
            entry["d3"] = iv
            entry.update(subgroup_deltas(arm, geo["mu"] + g, t, geo, counts, score_dates, donors, res))
        for r in arm_rows:
            rows_out.append(dict(r, arm=arm))
        pvals.append(res["p0"]["p_one_sided"] if res["testable"] else 1.0)
        results[arm] = entry
    adj, reject = bh_table(pvals)
    for (arm, entry), q, rej in zip(results.items(), adj, reject):
        d3 = entry.get("d3") or {}
        lo, hi = (d3.get("ci95_wider") or [None, None])
        entry["bh"] = {"q_value": q, "reject": rej}
        entry["label"] = label_for(entry["result"]["testable"], d3.get("power_at_edge"), hi, lo, rej)
        entry["register_text"] = REGISTER_TEXT[arm]

    if sha256_file(r80_manifest) != R80_LAYOUT_MANIFEST_SHA256 or sha256_file(dev_manifest) != \
            DEV_LAYOUT_MANIFEST_SHA256:
        raise Refused("refused: a layout manifest changed during the run; no receipt")
    out.mkdir(parents=True)
    with (out / "rows.jsonl").open("x", encoding="utf-8") as fh:
        for r in rows_out:
            fh.write(json.dumps(r, sort_keys=True, default=_default) + "\n")
    receipt = {
        "schema": SCHEMA + "/look", "ledger_row": LEDGER_ROW, "stage": "look", "approval": args.approval,
        "evidence_class": "kill-only on released dates; no label is an edge claim",
        "origin": origin, "code": state, "blobs": blobs, "rules": rules, "module_sha256": sha256_file(__file__),
        "coef_sha256": args.coef_sha, "r80_layout_manifest_sha256": R80_LAYOUT_MANIFEST_SHA256,
        "dev_layout_manifest_sha256": DEV_LAYOUT_MANIFEST_SHA256, "export_sums_sha256": R80_SUMS_SHA256,
        "export_files_hashed": len(hashed), "malformed": malformed, "override_in_process": override,
        "dates": dates, "snapshots_dropped_austin_1003": dropped, "feature_reasons": dict(reasons),
        "controls": controls, "k": len(ARMS), "bh_q": BH_Q, "delta_edge": DELTA_EDGE, "power_min": POWER_MIN,
        "coverage_floor": {"dates": MIN_DATES, "snapshots": MIN_SNAPS}, "mechanism": MECHANISM,
        "arms": results, "rows_sha256": sha256_file(out / "rows.jsonl"),
    }
    receipt_sha = write_exclusive(out / LOOK_RECEIPT, receipt)
    print(json.dumps({arm: {"label": e["label"], "power": (e.get("d3") or {}).get("power_at_edge"),
                            "ci95_wider": (e.get("d3") or {}).get("ci95_wider")} for arm, e in results.items()}))
    print("receipt", receipt_sha)
    return receipt


# ----------------------------------------------------------------------------- preflight and CLI

def stage_preflight(args):
    """Origin, clean tree, rule and blob shas, imports; reads no data."""
    origin = check_origin()
    state = require_clean(code_state())
    blobs = check_blobs()
    rules = check_rule_files()
    with contextlib.redirect_stdout(sys.stderr):
        from weather.calibration import c3_kill_tier  # noqa: F401
        from weather.calibration import mr_sweep  # noqa: F401
        from weather.calibration import odc_metar_features  # noqa: F401
        from weather.calibration import ols_floor_ladder  # noqa: F401
        from tools.research.released_window import served_market_blocks  # noqa: F401
    out = {"stage": "preflight", "origin": origin, "code": state, "rules": rules, "blobs_checked": len(blobs),
           "module_sha256": sha256_file(__file__), "verdict": "PASS"}
    print(json.dumps(out, indent=1, sort_keys=True))
    return out


def build_parser():
    ap = argparse.ArgumentParser(prog="tools.research.released_window.rodc_released_p0",
                                 description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="stage", required=True)
    for name in ("preflight", "fit", "look"):
        p = sub.add_parser(name)
        if name != "preflight":
            p.add_argument("--out", required=True)
        if name == "fit":
            p.add_argument("--cache-dir", default=str(L9_CACHE))
            p.add_argument("--l3-dir", default=str(L3_OCTDEC))
        if name == "look":
            p.add_argument("--coef", required=True)
            p.add_argument("--coef-sha", required=True)
            p.add_argument("--approval", required=True)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        {"preflight": stage_preflight, "fit": stage_fit, "look": stage_look}[args.stage](args)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
