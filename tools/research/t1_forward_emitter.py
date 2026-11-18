"""Lane L3: the T+1 forward test's daily emitter (P3 of the T+1 forward prereg, rev 9).

The rule is ``docs/research/t1-forward-prereg-2026-10-30/README.md`` on ``claude/t1-forward-prereg-20261030``
(rev 9, ``f07e8053b055d312e8e91f1e550198fb7d04c316``), sections 2, 3 and 5. For one capture day D it writes the
arm distributions of every T+1 snapshot (market x local top-of-hour on D, target T = D + 1) to an append-only emit
store with a sha256 manifest:

* A1, NBM NBP: the TXN 10/25/50/75/90 percentiles of the latest NBP cycle that passes the receipt rule (cycle age
  at most 13 h), column valid at 00 UTC on T + 1, as a mixture of uniforms (section 3.1).
* A2, ECMWF ENS: the latest 00/12 UTC run that passes the receipt rule (run age at most 24 h), member highs from the
  bilinear ``mx2t3`` windows wholly inside local day T, dressed with a Gaussian of 2.0 F (section 3.2).
* A3: 0.5 A1 + 0.5 A2, only where both are covered.

It reads only the NBM text recorder and the ECMWF ENS recorder (plus, for description only, the sha256 of the GEM and
GEFS context manifests). It never reads a price, label or outcome: every read goes through ``_guard``, which
refuses any path outside the configured forecast roots and any path naming the WS T+1 price recorder.

The emitter does not know the venue's band ladder (that lives with the prices it must not read), so it writes each
arm as a pmf over the market's native-unit integer bins [k - 0.5, k + 0.5) plus the mass below and above the grid.
Every venue band (an integer range or an open tail) is a union of those bins, so the scorer maps bands exactly at the
look, and applies ``market_blend.EPS`` flooring and renormalisation there, per band (section 3). The defining
parameters (the five percentiles, the member highs) are written beside the pmfs.

Parity checks run with every emit; a failure VOIDs the date in the manifest and the rows are still written.
Research / shadow only. It registers nothing and writes only under ``--out``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = "t1_forward_emit/1"
UTC = dt.timezone.utc

# Section 2: the 10 US highest-temperature markets other than Denver, plus Toronto. (IANA tz, native unit);
# a test checks both against weather.market.market_registry.
MARKETS = {
    "atlanta": ("America/New_York", "F"),
    "austin": ("America/Chicago", "F"),
    "chicago": ("America/Chicago", "F"),
    "dallas": ("America/Chicago", "F"),
    "houston": ("America/Chicago", "F"),
    "los-angeles": ("America/Los_Angeles", "F"),
    "miami": ("America/New_York", "F"),
    "nyc": ("America/New_York", "F"),
    "san-francisco": ("America/Los_Angeles", "F"),
    "seattle": ("America/Los_Angeles", "F"),
    "toronto": ("America/Toronto", "C"),
}

# Section 3 constants (fixed; nothing is tuned).
NBP_ROWS = ("TXNP1", "TXNP2", "TXNP5", "TXNP7", "TXNP9")
NBP_LEVELS = (0.10, 0.25, 0.50, 0.75, 0.90)
NBP_MAX_AGE = dt.timedelta(hours=13)
ENS_MAX_AGE = dt.timedelta(hours=24)
ENS_MIN_MEMBERS = 45
ENS_PARAM = "mx2t3"
SIGMA_K_F = 2.0
GAUSS_HALF_WIDTH_SIGMAS = 10.0

# Recorder code the emitter was built and tested against (manifest ``recorder_sha256``). A different recorder
# VOIDs the date until a dated Clarification re-pins it.
PINNED_RECORDER_SHA256 = {
    "nbm_text": "a751d645c3dd41c1280f0c7c789c72cf3345d4c01d738659479b3403b743c0bd",
    "ecmwf_ens": "eb106b845928c0dcd6296f171839b1057cab9bd256f4b1be6f9c1ef8d1075bab",
}
NBM_SCHEMA = "l13_nbm_text_forward/1"
ENS_SCHEMA = "ecmwf_ens_forward/1"

DEFAULT_NBM_ROOT = Path(r"C:\t\nbm_text\forward")
DEFAULT_ENS_ROOT = Path(r"C:\t\ecmwf_ens\forward")
DEFAULT_CONTEXT_ROOTS = (Path(r"C:\t\eccc_gem\forward"), Path(r"C:\t\gefs_cycles\forward"))
# Path components the emitter refuses to read under any configuration (the comparator store).
FORBIDDEN_PARTS = ("t1_prices",)
MIN_LAG_AFTER_LAST_CAPTURE = dt.timedelta(hours=1)
MASS_TOL = 1e-9


class RefusedPath(RuntimeError):
    """A read outside the forecast roots, or of the price recorder."""


class RefusedDate(RuntimeError):
    """A capture day that cannot be emitted (not yet over, or already emitted)."""


# ---------------------------------------------------------------------------------------------------- reads
def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _guard(path, allowed_roots) -> Path:
    path = Path(path)
    lowered = [part.lower() for part in path.resolve().parts]
    for bad in FORBIDDEN_PARTS:
        if any(bad in part for part in lowered):
            raise RefusedPath(f"refused: {path} names the price recorder")
    full = _norm(path.resolve())
    for root in allowed_roots:
        r = _norm(Path(root).resolve())
        if full == r or full.startswith(r.rstrip("\\/") + os.sep):
            return path
    raise RefusedPath(f"refused: {path} is outside the forecast roots")


def _read_bytes(path, allowed_roots) -> bytes:
    with open(_guard(path, allowed_roots), "rb") as fh:
        return fh.read()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_utc(value) -> dt.datetime | None:
    if value in (None, ""):
        return None
    t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"naive time {value!r}")
    return t.astimezone(UTC)


def _iso(t: dt.datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _latest(*times):
    vals = [t for t in times if t is not None]
    return max(vals) if vals else None


# ---------------------------------------------------------------------------------------------------- snapshots
def snapshots(capture_date: dt.date):
    """Section 2: the 24 local top-of-hour times 00:00..23:00 on D, per market, with their UTC capture time.

    On a fall-back day the repeated hour takes its first occurrence (fold 0). On a spring-forward day the missing
    hour does not exist and is listed in ``skipped``.
    """
    out, skipped = [], []
    for market, (tz, unit) in MARKETS.items():
        z = ZoneInfo(tz)
        for hour in range(24):
            local = dt.datetime.combine(capture_date, dt.time(hour), tzinfo=z).replace(fold=0)
            utc = local.astimezone(UTC)
            if utc.astimezone(z).replace(tzinfo=None) != local.replace(tzinfo=None):
                skipped.append({"market": market, "local_hour": hour, "reason": "nonexistent_local_time"})
                continue
            out.append({"market": market, "unit": unit, "tz": tz, "local_hour": hour, "capture_utc": utc})
    return out, skipped


def local_day_bounds(day: dt.date, tz: str):
    z = ZoneInfo(tz)
    start = dt.datetime.combine(day, dt.time(0), tzinfo=z).astimezone(UTC)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0), tzinfo=z).astimezone(UTC)
    return start, end


# ---------------------------------------------------------------------------------------------------- NBM (A1)
def _date_dirs(root: Path, days, allowed, not_after: dt.datetime):
    """Hour directories <YYYYMMDD>/<HH> whose cycle time is at or before ``not_after`` (the day's last capture)."""
    for day in days:
        d = root / day.strftime("%Y%m%d")
        _guard(d, allowed)
        if not d.is_dir():
            continue
        for h in sorted(p for p in d.iterdir() if p.is_dir()):
            if not (h.name.isdigit() and len(h.name) == 2 and int(h.name) < 24):
                continue
            if dt.datetime.combine(day, dt.time(int(h.name)), tzinfo=UTC) <= not_after:
                yield h


def load_nbp_cycles(nbm_root: Path, days, allowed, parity: list, inputs: list, not_after: dt.datetime):
    """NBP cycles in the NBM text store under the given UTC dates, with receipt times and per-market TXN rows."""
    cycles = []
    for hour_dir in _date_dirs(nbm_root, days, allowed, not_after):
        man_path, rows_path = hour_dir / "manifest.json", hour_dir / "nbm_text.jsonl"
        if not man_path.exists() or not rows_path.exists():
            continue  # not closed: never used
        man_bytes = _read_bytes(man_path, allowed)
        rows_bytes = _read_bytes(rows_path, allowed)
        man = json.loads(man_bytes)
        rel = str(hour_dir.relative_to(nbm_root)).replace("\\", "/")
        inputs.append({"role": "nbm_text_manifest", "path": rel + "/manifest.json", "sha256": _sha(man_bytes)})
        inputs.append({"role": "nbm_text_rows", "path": rel + "/nbm_text.jsonl", "sha256": _sha(rows_bytes)})
        if man.get("schema") != NBM_SCHEMA:
            parity.append(f"nbm {rel}: schema {man.get('schema')!r}")
        if man.get("recorder_sha256") != PINNED_RECORDER_SHA256["nbm_text"]:
            parity.append(f"nbm {rel}: recorder_sha256 {man.get('recorder_sha256')} not pinned")
        if man.get("rows_sha256") != _sha(rows_bytes):
            parity.append(f"nbm {rel}: rows sha mismatch")
        rows = [json.loads(line) for line in rows_bytes.decode("utf-8").splitlines() if line.strip()]
        products = [(i, r) for i, r in enumerate(rows)
                    if r.get("kind") == "product" and r.get("product") == "nbp" and r.get("status") == "ok"]
        if not products:
            continue
        p_idx, prod = products[-1]
        cycle_utc = parse_utc(prod.get("cycle_utc"))
        published = parse_utc(prod.get("last_modified_utc"))
        fetched = parse_utc(prod.get("fetched_utc"))
        written = parse_utc(man.get("written_utc"))
        if cycle_utc is None or published is None or fetched is None or written is None:
            parity.append(f"nbm {rel}: nbp product row lacks times")
            continue
        blocks = {}
        for i, r in enumerate(rows):
            if (i < p_idx and r.get("kind") == "block" and r.get("product") == "nbp" and r.get("parse_ok") is True
                    and r.get("file_sha256") == prod.get("sha256") and parse_utc(r.get("cycle_utc")) == cycle_utc):
                market = r.get("market")
                if market in blocks:
                    blocks[market] = None  # ambiguous: two blocks for one market
                else:
                    blocks[market] = r
        cycles.append({
            "cycle_utc": cycle_utc,
            "receipt_utc": _latest(published, fetched, written),
            "published_utc": published, "fetched_utc": fetched, "manifest_written_utc": written,
            "product_sha256": prod.get("sha256"), "path": rel, "blocks": blocks,
        })
    return cycles


def nbp_knots(block: dict, target: dt.date):
    """The five TXN percentiles (integer F) in the column valid at 00 UTC on T + 1, or (None, reason)."""
    want = dt.datetime.combine(target + dt.timedelta(days=1), dt.time(0), tzinfo=UTC)
    cols = [parse_utc(c.get("valid_utc")) for c in block.get("columns") or []]
    if cols.count(want) != 1:
        return None, "nbp_column_missing"
    j = cols.index(want)
    values = block.get("values") or {}
    knots = []
    for row in NBP_ROWS:
        seq = values.get(row)
        if not isinstance(seq, list) or len(seq) != len(cols):
            return None, "nbp_row_missing"
        v = seq[j]
        if isinstance(v, bool) or not isinstance(v, int) or v <= -50 or v >= 150:
            return None, "nbp_value_missing"
        knots.append(v)
    if any(b < a for a, b in zip(knots, knots[1:])):
        return None, "nbp_percentiles_not_monotone"
    return knots, None


def nbp_segments(knots):
    """Section 3.1 as a mixture of uniforms [(a, b, mass)] in F.

    Between consecutive percentile knots with distinct values the level gap is uniform over [v_i, v_j] (the
    piecewise-linear CDF through the knots); tied knots spread their level gap uniformly over [v - 0.5, v + 0.5);
    the tails carry 0.10 each, uniform over [P10 - 1.5 max(P25 - P10, 1), P10] and [P90, P90 + 1.5 max(P90 - P75, 1)].
    """
    p10, p25, _, p75, p90 = knots
    segs = [(p10 - 1.5 * max(p25 - p10, 1), float(p10), 0.10)]
    for (va, qa), (vb, qb) in zip(zip(knots, NBP_LEVELS), list(zip(knots, NBP_LEVELS))[1:]):
        mass = qb - qa
        if vb > va:
            segs.append((float(va), float(vb), mass))
        else:
            segs.append((va - 0.5, va + 0.5, mass))
    segs.append((float(p90), p90 + 1.5 * max(p90 - p75, 1), 0.10))
    return segs


def mixture_cdf(segs, x: float) -> float:
    total = 0.0
    for a, b, m in segs:
        if x >= b:
            total += m
        elif x > a:
            total += m * (x - a) / (b - a)
    return total


# ---------------------------------------------------------------------------------------------------- ENS (A2)
def load_ens_runs(ens_root: Path, run_lo: dt.datetime, run_hi: dt.datetime, allowed, parity: list, inputs: list):
    runs = []
    _guard(ens_root, allowed)
    if not ens_root.is_dir():
        return runs
    for run_dir in sorted(p for p in ens_root.iterdir() if p.is_dir()):
        try:
            run_utc = dt.datetime.strptime(run_dir.name, "%Y%m%d%H").replace(tzinfo=UTC)
        except ValueError:
            continue
        if not (run_lo <= run_utc <= run_hi) or run_utc.hour not in (0, 12):
            continue
        man_path, pts_path = run_dir / "manifest.json", run_dir / "points.jsonl"
        if not man_path.exists() or not pts_path.exists():
            continue  # manifest not closed: never used
        man_bytes = _read_bytes(man_path, allowed)
        pts_bytes = _read_bytes(pts_path, allowed)
        man = json.loads(man_bytes)
        rel = run_dir.name
        inputs.append({"role": "ecmwf_ens_manifest", "path": rel + "/manifest.json", "sha256": _sha(man_bytes)})
        inputs.append({"role": "ecmwf_ens_points", "path": rel + "/points.jsonl", "sha256": _sha(pts_bytes)})
        if man.get("schema") != ENS_SCHEMA:
            parity.append(f"ens {rel}: schema {man.get('schema')!r}")
        if man.get("recorder_sha256") != PINNED_RECORDER_SHA256["ecmwf_ens"]:
            parity.append(f"ens {rel}: recorder_sha256 {man.get('recorder_sha256')} not pinned")
        if man.get("points_sha256") != _sha(pts_bytes):
            parity.append(f"ens {rel}: points sha mismatch")
        if parse_utc(man.get("run_utc")) != run_utc:
            parity.append(f"ens {rel}: run_utc mismatch")
        written = parse_utc(man.get("written_utc"))
        published = parse_utc(man.get("max_last_modified_utc"))
        fetched = parse_utc(man.get("max_fetched_utc"))
        points = {}
        conflict = False
        for line in pts_bytes.decode("utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") != "point" or r.get("param") != ENS_PARAM:
                continue
            published = _latest(published, parse_utc(r.get("last_modified_utc")))
            fetched = _latest(fetched, parse_utc(r.get("fetched_utc")))
            valid = parse_utc(r.get("valid_utc"))
            key = (r.get("market"), r.get("member"), valid)
            val = (float(r["bilinear_k"]), int(r.get("window_h") or 0))
            if key in points and points[key] != val:
                conflict = True
            points[key] = val
        if conflict:
            parity.append(f"ens {rel}: conflicting duplicate points")
        if written is None or published is None or fetched is None:
            parity.append(f"ens {rel}: manifest lacks times")
            continue
        runs.append({
            "run_utc": run_utc, "receipt_utc": _latest(published, fetched, written),
            "published_utc": published, "fetched_utc": fetched, "manifest_written_utc": written,
            "steps": sorted(int(s) for s in man.get("steps") or []),
            "points_sha256": man.get("points_sha256"), "path": rel, "points": points,
        })
    return runs


def ens_member_highs(run: dict, market: str, tz: str, target: dt.date):
    """Member highs (F) over the 3 h windows wholly inside local day T, or (None, reason).

    A member counts only if it has every window of the run's 3-hourly grid that lies wholly inside the day.
    """
    ds, de = local_day_bounds(target, tz)
    required = []
    k = 1
    while True:
        valid = run["run_utc"] + dt.timedelta(hours=3 * k)
        if valid > de:
            break
        if valid - dt.timedelta(hours=3) >= ds:
            required.append((3 * k, valid))
        k += 1
    if not required:
        return None, "ens_no_inside_window"
    if any(step not in run["steps"] for step, _ in required):
        return None, "ens_steps_beyond_run"
    members = sorted({m for (mk, m, _v) in run["points"] if mk == market})
    highs = {}
    for m in members:
        vals = []
        for _step, valid in required:
            pt = run["points"].get((market, m, valid))
            if pt is None or pt[1] != 3 or not math.isfinite(pt[0]):
                vals = None
                break
            vals.append(pt[0])
        if vals:
            highs[m] = (max(vals) - 273.15) * 9.0 / 5.0 + 32.0
    if len(highs) < ENS_MIN_MEMBERS:
        return None, f"ens_members_{len(highs)}_lt_{ENS_MIN_MEMBERS}"
    return [highs[m] for m in sorted(highs)], None


def gauss_mixture_cdf(highs, sigma: float, x: float) -> float:
    s = 0.0
    for h in highs:
        s += 0.5 * (1.0 + math.erf((x - h) / (sigma * math.sqrt(2.0))))
    return s / len(highs)


# ---------------------------------------------------------------------------------------------------- bins
def _to_f(native: float, unit: str) -> float:
    return native if unit == "F" else native * 9.0 / 5.0 + 32.0


def _to_native(f: float, unit: str) -> float:
    return f if unit == "F" else (f - 32.0) * 5.0 / 9.0


def binned(cdf, k_lo: int, k_hi: int, unit: str):
    """pmf over native integer bins k_lo..k_hi ([k - 0.5, k + 0.5) native), plus below / above masses."""
    edges = [cdf(_to_f(k - 0.5, unit)) for k in range(k_lo, k_hi + 2)]
    pmf = [max(0.0, edges[i + 1] - edges[i]) for i in range(len(edges) - 1)]
    return {"pmf": pmf, "below": max(0.0, edges[0]), "above": max(0.0, 1.0 - edges[-1])}


# ---------------------------------------------------------------------------------------------------- emit
def _choose(items, capture: dt.datetime, max_age: dt.timedelta, key: str):
    ok = [c for c in items if c["receipt_utc"] <= capture and capture - c[key] <= max_age and c[key] <= capture]
    return max(ok, key=lambda c: c[key]) if ok else None


def compute_rows(capture_date: dt.date, nbm_root: Path, ens_root: Path, allowed):
    """All rows for capture day D, plus parity notes and the inputs read. Pure function of the stores."""
    target = capture_date + dt.timedelta(days=1)
    parity, inputs = [], []
    snaps, skipped = snapshots(capture_date)
    first = min(s["capture_utc"] for s in snaps)
    last = max(s["capture_utc"] for s in snaps)
    days = sorted({(first - NBP_MAX_AGE).date() + dt.timedelta(days=i)
                   for i in range((last.date() - (first - NBP_MAX_AGE).date()).days + 1)})
    cycles = load_nbp_cycles(nbm_root, days, allowed, parity, inputs, last)
    runs = load_ens_runs(ens_root, first - ENS_MAX_AGE, last, allowed, parity, inputs)
    rows = []
    for s in snaps:
        market, unit, tz, cap = s["market"], s["unit"], s["tz"], s["capture_utc"]
        # A1
        a1_segs, a1 = None, {"covered": False}
        cyc = _choose(cycles, cap, NBP_MAX_AGE, "cycle_utc")
        if cyc is None:
            a1["reason"] = "nbp_no_cycle_passes_receipt_rule"
        else:
            block = cyc["blocks"].get(market)
            a1["source"] = {"cycle_utc": _iso(cyc["cycle_utc"]), "receipt_utc": _iso(cyc["receipt_utc"]),
                            "product_sha256": cyc["product_sha256"], "path": cyc["path"]}
            if block is None:
                a1["reason"] = "nbp_block_missing_or_ambiguous"
            else:
                knots, why = nbp_knots(block, target)
                if knots is None:
                    a1["reason"] = why
                else:
                    a1_segs = nbp_segments(knots)
                    a1["source"]["icao"] = block.get("icao")
                    a1["source"]["knots_f"] = dict(zip(("p10", "p25", "p50", "p75", "p90"), knots))
        # A2
        a2_highs, a2 = None, {"covered": False}
        run = _choose(runs, cap, ENS_MAX_AGE, "run_utc")
        if run is None:
            a2["reason"] = "ens_no_run_passes_receipt_rule"
        else:
            a2["source"] = {"run_utc": _iso(run["run_utc"]), "receipt_utc": _iso(run["receipt_utc"]),
                            "points_sha256": run["points_sha256"], "path": run["path"]}
            highs, why = ens_member_highs(run, market, tz, target)
            if highs is None:
                a2["reason"] = why
            else:
                a2_highs = highs
                a2["source"]["n_members"] = len(highs)
                a2["source"]["member_high_f"] = [round(h, 6) for h in highs]
        # common native grid
        lo_f, hi_f = [], []
        if a1_segs:
            lo_f.append(min(a for a, _b, _m in a1_segs))
            hi_f.append(max(b for _a, b, _m in a1_segs))
        if a2_highs:
            lo_f.append(min(a2_highs) - GAUSS_HALF_WIDTH_SIGMAS * SIGMA_K_F)
            hi_f.append(max(a2_highs) + GAUSS_HALF_WIDTH_SIGMAS * SIGMA_K_F)
        grid = None
        if lo_f:
            k_lo = math.floor(_to_native(min(lo_f), unit)) - 1
            k_hi = math.ceil(_to_native(max(hi_f), unit)) + 1
            grid = {"k_lo": k_lo, "k_hi": k_hi}
            if a1_segs:
                a1.update(covered=True, **binned(lambda x: mixture_cdf(a1_segs, x), k_lo, k_hi, unit))
                a1.pop("reason", None)
            if a2_highs:
                a2.update(covered=True, **binned(lambda x: gauss_mixture_cdf(a2_highs, SIGMA_K_F, x),
                                                  k_lo, k_hi, unit))
                a2.pop("reason", None)
        a3 = {"covered": False}
        if a1["covered"] and a2["covered"]:
            a3 = {"covered": True, "pmf": [0.5 * p + 0.5 * q for p, q in zip(a1["pmf"], a2["pmf"])],
                  "below": 0.5 * a1["below"] + 0.5 * a2["below"], "above": 0.5 * a1["above"] + 0.5 * a2["above"]}
        else:
            a3["reason"] = "a1_or_a2_uncovered"
        arms = {"A1": a1, "A2": a2, "A3": a3}
        rows.append({
            "schema": SCHEMA, "capture_date": capture_date.isoformat(), "target_date": target.isoformat(),
            "market": market, "unit": unit, "local_hour": s["local_hour"], "capture_utc": _iso(cap),
            "bins": None if grid is None else {**grid, "rule": "native integer k covers [k-0.5, k+0.5)"},
            "arms": arms,
        })
    return rows, skipped, parity, inputs


def mass_parity(rows) -> list:
    out = []
    for r in rows:
        arms = r["arms"]
        for name, arm in arms.items():
            if not arm.get("covered"):
                continue
            vals = arm["pmf"] + [arm["below"], arm["above"]]
            if min(vals) < 0 or abs(sum(vals) - 1.0) > MASS_TOL:
                out.append(f"mass {r['market']} h{r['local_hour']} {name}: sum {sum(vals)!r}")
        if arms["A3"].get("covered"):
            for p, q, b in zip(arms["A1"]["pmf"], arms["A2"]["pmf"], arms["A3"]["pmf"]):
                if abs(0.5 * p + 0.5 * q - b) > 1e-12:
                    out.append(f"blend {r['market']} h{r['local_hour']}")
                    break
    return out


def _serialise(rows) -> bytes:
    return "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")


def context_manifests(roots, capture_date: dt.date):
    """sha256 of context-store manifests (GEM, GEFS) dated D - 1..D + 1. Description only; never parsed."""
    tags = {(capture_date + dt.timedelta(days=i)).strftime("%Y%m%d") for i in (-1, 0, 1)}
    out = []
    for root in roots:
        root = Path(root)
        _guard(root, roots)
        if not root.is_dir():
            out.append({"root": str(root), "present": False})
            continue
        for man in sorted(root.glob("**/manifest.json")):
            rel = man.relative_to(root)
            if len(rel.parts) <= 3 and any(part[:8] in tags for part in rel.parts[:-1]):
                out.append({"root": str(root), "path": str(rel).replace("\\", "/"),
                            "sha256": _sha(_read_bytes(man, roots))})
    return out


def emitter_sha256() -> str:
    return _sha(Path(__file__).read_bytes())


def emit_day(capture_date: dt.date, out_root: Path, nbm_root: Path = DEFAULT_NBM_ROOT,
             ens_root: Path = DEFAULT_ENS_ROOT, context_roots=DEFAULT_CONTEXT_ROOTS, now: dt.datetime | None = None):
    """Write D's emit (append-only). Returns the manifest dict."""
    for root in (nbm_root, ens_root, *context_roots):
        if any(bad in part.lower() for bad in FORBIDDEN_PARTS for part in Path(root).resolve().parts):
            raise RefusedPath(f"refused root {root}")
    now = now or dt.datetime.now(UTC)
    snaps, _ = snapshots(capture_date)
    last = max(s["capture_utc"] for s in snaps)
    if now < last + MIN_LAG_AFTER_LAST_CAPTURE:
        raise RefusedDate(f"capture day {capture_date} is not over (last capture {_iso(last)})")
    out_root = Path(out_root)
    day_dir = out_root / capture_date.strftime("%Y%m%d")
    if day_dir.exists():
        raise RefusedDate(f"{day_dir} exists; the emit store is append-only")
    allowed = (Path(nbm_root), Path(ens_root))
    rows, skipped, parity, inputs = compute_rows(capture_date, Path(nbm_root), Path(ens_root), allowed)
    rows2, _s2, parity2, inputs2 = compute_rows(capture_date, Path(nbm_root), Path(ens_root), allowed)
    emit_bytes = _serialise(rows)
    failures = list(parity) + mass_parity(rows)
    if emit_bytes != _serialise(rows2) or inputs != inputs2 or parity != parity2:
        failures.append("determinism: a second computation from fresh reads differs")
    counts = {"snapshots": len(rows), "skipped_local_hours": len(skipped)}
    for arm in ("A1", "A2", "A3"):
        counts[f"{arm}_covered"] = sum(1 for r in rows if r["arms"][arm]["covered"])
    manifest = {
        "schema": SCHEMA, "capture_date": capture_date.isoformat(),
        "target_date": (capture_date + dt.timedelta(days=1)).isoformat(),
        "emitter": "tools/research/t1_forward_emitter.py", "emitter_sha256": emitter_sha256(),
        "rule": "docs/research/t1-forward-prereg-2026-10-30/README.md rev 9 f07e8053b055d312e8e91f1e550198fb7d04c316",
        "nbm_root": str(nbm_root), "ens_root": str(ens_root),
        "pinned_recorder_sha256": PINNED_RECORDER_SHA256,
        "inputs": inputs, "context": context_manifests(tuple(Path(r) for r in context_roots), capture_date),
        "skipped": skipped, "counts": counts,
        "parity": {"checks": ["input_integrity", "recorder_pin", "mass", "blend", "determinism"],
                   "failures": failures},
        "void": bool(failures), "emit_sha256": _sha(emit_bytes),
        "written_utc": _iso(dt.datetime.now(UTC)),
    }
    man_bytes = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")
    out_root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=out_root))
    (tmp / "emit.jsonl").write_bytes(emit_bytes)
    (tmp / "manifest.json").write_bytes(man_bytes)
    os.replace(tmp, day_dir)
    with open(out_root / "index.jsonl", "ab") as fh:
        fh.write((json.dumps({"capture_date": capture_date.isoformat(), "emit_sha256": manifest["emit_sha256"],
                              "manifest_sha256": _sha(man_bytes), "void": manifest["void"]},
                             sort_keys=True) + "\n").encode("utf-8"))
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capture-date", required=True, help="local capture day D (YYYY-MM-DD); target T = D + 1")
    ap.add_argument("--out", required=True, help="append-only emit store root")
    ap.add_argument("--nbm-root", default=str(DEFAULT_NBM_ROOT))
    ap.add_argument("--ens-root", default=str(DEFAULT_ENS_ROOT))
    ap.add_argument("--context-root", action="append", default=None)
    a = ap.parse_args(argv)
    ctx = tuple(Path(p) for p in a.context_root) if a.context_root else DEFAULT_CONTEXT_ROOTS
    try:
        man = emit_day(dt.date.fromisoformat(a.capture_date), Path(a.out), Path(a.nbm_root), Path(a.ens_root), ctx)
    except (RefusedPath, RefusedDate) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: man[k] for k in ("capture_date", "counts", "void", "emit_sha256")}, sort_keys=True))
    return 1 if man["void"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
