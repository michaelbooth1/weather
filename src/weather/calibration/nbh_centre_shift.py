"""L14 rung R-P: the NBH remaining-hours maximum as a 13-16 centre shift (rule C:/t/l14/rp/rule_rp.md).

Development evidence only. The incumbent arms (B_N, P3d_N_fix) are L2's R-A arms, imported unchanged from
``pooled_residual_model`` (which fails closed on the capture host). The candidate arms translate an incumbent's
predictive distribution by delta = a_h + b_h * x, x = max(NBH remaining-hours max, F) - A, with one (a, b) per arm
and cutoff hour fitted on out-of-sample LOYO predictions only. Production never captured NBH: the NBH input is L12's
S3 archive read with S3 LastModified as the availability instant, so nothing here establishes serve parity.
"""
from __future__ import annotations

from weather.calibration import pooled_residual_model as prm  # fails closed on the capture host

import argparse  # noqa: E402
import bisect  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

RP_RULE_SHA256 = "ed3236fa40cfc4cec35d2bcf1da129799716f399a3cb97199d3aa7fb632bbaa2"
RP_HOURS = (13, 14, 15, 16)
RP_POOLS = (("13-16", None), ("13-14", (13, 14)), ("15-16", (15, 16)))
RP_PAIRS = (("B_P", "B_N"), ("P3d_P", "P3d_N_fix"), ("P3d_P", "B_P"), ("P3d_N_fix", "B_N"))
RP_ARMS = {"B_N": "B_P", "P3d_N_fix": "P3d_P"}  # incumbent -> translated candidate
RP_MARGIN = timedelta(minutes=10)
RP_MAX_AGE = timedelta(hours=12)
RP_WINDOW_END_HOUR = 23
RP_TMP_RANGE_F = (-40, 130)
RP_COVERAGE_MIN = 0.95
RP_MEDIAN_GAP_MAX_F = 3.0
RP_TIE_TOL = 1e-12
A_GRID = tuple(round(i / 10, 1) for i in range(-30, 31))
B_GRID = tuple(round(i / 20, 2) for i in range(0, 21))
RH_EMIT = {"dev_B_N.jsonl": "bab9cac728a5b363888278ad66b12e73807b5e0ae0849bcb13f12f5e8139f186",
           "dev_P3d_N_fix.jsonl": "abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109"}
P3D_N_SHA256 = "721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec"  # MG-2 post-13 dev arm
LAST_ALLOWED = date(2026, 9, 29)


class RPError(ValueError):
    pass


def grid_order():
    """(a, b) pairs in tie-preference order: smallest b, then smallest |a|, then a < 0 before a > 0."""
    return sorted(((a, b) for a in A_GRID for b in B_GRID), key=lambda ab: (ab[1], abs(ab[0]), ab[0] > 0))


GRID = grid_order()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- NBH blocks
# parse_header_line / parse_block: verbatim from tools/research/nbm_nbs_nbh_fetch.py @ 186c42ad4 (L12's fetcher).


def parse_header_line(block):
    """Parse the first line of a station block: station, product, model version, issue time (UTC)."""
    text = block.decode("ascii", "replace") if isinstance(block, bytes) else block
    first = text.splitlines()[0] if text else ""
    m = re.match(
        r"^ ?([A-Z0-9]{3,8}) +NBM (V\S+) +(NB[A-Z]) +GUIDANCE +(\d{1,2})/(\d{1,2})/(\d{4}) +(\d{2})(\d{2}) UTC",
        first,
    )
    if not m:
        raise ValueError(f"not a NBM block header: {first!r}")
    st, ver, prod, mo, dy, yr, hh, mi = m.groups()
    issued = datetime(int(yr), int(mo), int(dy), int(hh), int(mi), tzinfo=timezone.utc)
    return {"station": st, "version": ver, "product": prod, "issued_utc": issued}


def parse_block(block):
    """Parse one NBS or NBH station block into {header, columns, rows} (see the fetcher's docstring)."""
    text = block.decode("ascii", "replace") if isinstance(block, bytes) else block
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    header = parse_header_line(lines[0])
    rows = {}
    utc_hours = None
    fhr = None
    for ln in lines[1:]:
        if len(ln) < 5 or not ln[1:4].strip():
            continue
        label = ln[1:4]
        body = ln[5:]
        if label == "DT ":
            continue
        cells = [body[i:i + 3] for i in range(0, len(body), 3)]
        if label == "UTC":
            utc_hours = [int(c) for c in cells if c.strip()]
            continue
        if label == "FHR":
            fhr = [int(c) for c in cells if c.strip()]
            continue
        rows[label.strip()] = [int(c) if c.strip() else None for c in cells]
    if utc_hours is None:
        raise ValueError("block has no UTC row")
    n = len(utc_hours)
    for k, v in rows.items():
        rows[k] = (v + [None] * n)[:n]
    valid = []
    prev = header["issued_utc"] - timedelta(seconds=1)
    for h in utc_hours:
        cand = prev.replace(hour=h, minute=0, second=0)
        while cand <= prev:
            cand += timedelta(days=1)
        valid.append(cand)
        prev = cand
    return {"header": header, "utc_hours": utc_hours, "fhr": fhr, "valid_utc": valid, "rows": rows}


def _iso_utc(text):
    return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(timezone.utc)


def read_sha256sums(path):
    """{relative posix path: sha256} from a ``sha256sum``-style file."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            out[parts[1].lstrip("*").replace("\\", "/").lstrip("./")] = parts[0]
    return out


class NBHCorpus:
    """L12's NBH station blocks: per station, cycles sorted by issue time; block bytes verified on use."""

    def __init__(self, corpus_dir, stations):
        self.root = Path(corpus_dir)
        sums = self.root / "SHA256SUMS"
        if not sums.exists():
            raise RPError(f"{self.root} has no SHA256SUMS: L12 has not finalised this corpus")
        self.sums_sha256 = _sha(sums)
        self.manifest_sha256 = _sha(self.root / "manifest.jsonl")
        self.sums = read_sha256sums(sums)
        self.stats = defaultdict(int)
        self.entries = {s: {} for s in stations}
        for line in (self.root / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                self.stats["manifest_corrupt_line"] += 1
                continue
            if rec.get("product") != "nbh":
                continue
            day = date.fromisoformat(rec["utc_date"])
            if day > LAST_ALLOWED + timedelta(days=1):
                raise RPError(f"NBH manifest row after the cutoff: {day}")
            cycle = datetime(day.year, day.month, day.day, int(rec["cycle"]), tzinfo=timezone.utc)
            for icao in stations:
                st = (rec.get("stations") or {}).get(icao) or {}
                if rec.get("status") != "ok" or st.get("status") != "ok":
                    self.stats["block_not_ok"] += 1
                    continue
                if cycle in self.entries[icao]:
                    self.stats["manifest_duplicate"] += 1
                self.entries[icao][cycle] = (_iso_utc(rec["last_modified"]), rec["blocks_file"],
                                             int(st["file_offset"]), int(st["length"]), st["sha256"])
        self.cycles = {s: sorted(v) for s, v in self.entries.items()}
        self._file_ok = {}

    def block(self, icao, cycle):
        lm, rel, off, length, sha = self.entries[icao][cycle]
        rel_posix = str(rel).replace("\\", "/")
        if rel_posix not in self._file_ok:
            expected = self.sums.get(rel_posix)
            self._file_ok[rel_posix] = expected is not None and _sha(self.root / rel_posix) == expected
        if not self._file_ok[rel_posix]:
            return None, "file_sha256sums_mismatch"
        with open(self.root / rel_posix, "rb") as handle:
            handle.seek(off)
            data = handle.read(length)
        if hashlib.sha256(data).hexdigest() != sha:
            return None, "block_sha_mismatch"
        return data, None

    def select(self, icao, t):
        """Newest cycle with LastModified + 10 min <= t and issue time > t - 12 h, else None."""
        cycles = self.cycles.get(icao) or []
        hi = bisect.bisect_right(cycles, t)
        for i in range(hi - 1, -1, -1):
            cycle = cycles[i]
            if cycle <= t - RP_MAX_AGE:
                return None
            if self.entries[icao][cycle][0] + RP_MARGIN <= t:
                return cycle
        return None


def nbh_feature(corpus, icao, target, hour, tz):
    """(f_rem or None, cycle or None, reason) at t = hour:00 local on ``target`` (rule: The feature)."""
    t_local = datetime(target.year, target.month, target.day, hour, tzinfo=tz)
    t = t_local.astimezone(timezone.utc)
    cycle = corpus.select(icao, t)
    if cycle is None:
        return None, None, "no_cycle"
    if corpus.entries[icao][cycle][0] + RP_MARGIN > t:  # defensive: PIT
        return None, cycle, "pit_violation"
    data, err = corpus.block(icao, cycle)
    if data is None:
        return None, cycle, err
    try:
        parsed = parse_block(data)
    except ValueError:
        return None, cycle, "parse_error"
    if parsed["header"]["issued_utc"] != cycle or parsed["header"]["station"] != icao:
        return None, cycle, "issue_mismatch"
    tmp = parsed["rows"].get("TMP")
    if tmp is None:
        return None, cycle, "no_tmp_row"
    by_valid = dict(zip(parsed["valid_utc"], tmp))
    values = []
    for h in range(hour, RP_WINDOW_END_HOUR + 1):
        v = by_valid.get(datetime(target.year, target.month, target.day, h, tzinfo=tz).astimezone(timezone.utc))
        if v is None:
            return None, cycle, "window_incomplete"
        if not (RP_TMP_RANGE_F[0] <= v <= RP_TMP_RANGE_F[1]):
            return None, cycle, "tmp_out_of_range"
        values.append(v)
    return float(max(values)), cycle, "ok"


def feature_x(f_rem, F, A):
    """x = max(f_rem, F) - A, or None when the row is missing."""
    if f_rem is None or F is None or A is None or not math.isfinite(float(F)) or not math.isfinite(float(A)):
        return None
    return max(float(f_rem), float(F)) - float(A)


# ----------------------------------------------------------------------------- translation


def span_of(space):
    ks = [int(k) for k in space]
    return min(ks), max(ks)


def dense(dist, lo, hi):
    import numpy as np

    p = np.zeros(hi - lo + 1)
    for k, v in dist.items():
        k = int(k)
        if not lo <= k <= hi:
            raise RPError(f"bucket {k} outside the span [{lo}, {hi}]")
        p[k - lo] += float(v)
    return p


def translate_many(p, lo, deltas, floor):
    """Rows of translated, floored masses over the span for each delta (rule: Translation)."""
    import numpy as np

    n = len(p)
    edges = lo - 0.5 + np.arange(n + 1)
    cdf = np.concatenate([[0.0], np.cumsum(p)])
    deltas = np.asarray(deltas, float)
    g = np.interp((edges[None, :] - deltas[:, None]).ravel(), edges, cdf).reshape(len(deltas), n + 1)
    q = np.diff(g, axis=1)
    q[:, 0] += g[:, 0]
    q[:, -1] += cdf[-1] - g[:, -1]
    idx = int(min(max(int(floor) - lo, 0), n - 1))
    if idx > 0:
        q[:, idx] += q[:, :idx].sum(axis=1)
        q[:, :idx] = 0.0
    return q


def translate(dist, space, delta, floor):
    """One translated distribution as {int bucket: p} over the contiguous span of ``space``."""
    lo, hi = span_of(space)
    q = translate_many(dense(dist, lo, hi), lo, [delta], floor)[0]
    return {lo + j: float(v) for j, v in enumerate(q)}


def grid_briers(dist, space, x, floor, actual):
    """Summed bucket Brier of the translated arm for every GRID pair (vector, GRID order)."""
    import numpy as np

    lo, hi = span_of(space)
    p = dense(dist, lo, hi)
    deltas = np.array([a + b * x for a, b in GRID])
    q = translate_many(p, lo, deltas, floor)
    y = np.zeros(hi - lo + 1)
    y[int(actual) - lo] = 1.0
    return ((q - y[None, :]) ** 2).sum(axis=1)


def pick_ab(sums):
    """The tie-ordered minimiser of a GRID-ordered criterion vector."""
    import numpy as np

    sums = np.asarray(sums, float)
    best = float(sums.min())
    i = int(np.flatnonzero(sums <= best + RP_TIE_TOL * max(1.0, abs(best)))[0])
    return {"a": GRID[i][0], "b": GRID[i][1], "criterion": float(sums[i]),
            "criterion_identity": float(sums[GRID.index((0.0, 0.0))])}


# ----------------------------------------------------------------------------- gate 1


def parity_verdict(stats, gaps):
    import numpy as np

    rows = stats.get("rows", 0)
    coverage = stats.get("covered", 0) / max(rows, 1)
    median_gap = float(np.median(np.abs(gaps))) if gaps else float("nan")
    checks = {"coverage": coverage >= RP_COVERAGE_MIN,
              "block_sha": stats.get("miss_block_sha_mismatch", 0) == 0
              and stats.get("miss_file_sha256sums_mismatch", 0) == 0,
              "tmp_range": stats.get("miss_tmp_out_of_range", 0) == 0,
              "pit": stats.get("miss_pit_violation", 0) == 0,
              "median_gap": bool(gaps) and median_gap <= RP_MEDIAN_GAP_MAX_F}
    return {"coverage": coverage, "median_abs_gap_f": median_gap, "checks": checks, "pass": all(checks.values())}


def _age_report(ages):
    out = {}
    for key, vals in sorted(ages.items()):
        vals = sorted(vals)
        out[key] = {"n": len(vals), "median_age_h": vals[len(vals) // 2][0] if vals else None,
                    "share_19z": sum(1 for v in vals if v[1] == 19) / max(len(vals), 1)}
    return out


def _stations(markets):
    from weather.market.market_registry import spec_for_id
    from zoneinfo import ZoneInfo

    out = {}
    for m in markets:
        spec = spec_for_id(m)
        out[m] = (spec.icao, ZoneInfo(spec.timezone))
    return out


def _require_empty(out_dir):
    out = prm.require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise RPError(f"refusing to write into a non-empty {out}")
    return out


# ----------------------------------------------------------------------------- gates 1a and 2 (nested LOYO)


def rp_loyo(*, records_root, nbm_train_corpus, nbh_corpus, rj_loyo_rows, out_dir, markets=prm.R0_MARKETS):
    """Gate 1a (training inputs) and gate 2 (nested LOYO 2021-25, B_P - B_N at 13-16). No dev row is read."""
    import numpy as np

    from weather.calibration import feature_model as fm
    from weather.calibration import ols_floor_ladder as l9

    out = _require_empty(out_dir)
    stations = _stations(markets)
    corpus = NBHCorpus(nbh_corpus, sorted({s for s, _ in stations.values()}))
    audit = {"rule_sha256": RP_RULE_SHA256, "hours": list(RP_HOURS), "gates": {},
             "inputs": {"nbm_train_corpus": _sha(nbm_train_corpus), "rj_loyo_rows": _sha(rj_loyo_rows),
                        "nbh_corpus": str(corpus.root), "nbh_sha256sums": corpus.sums_sha256,
                        "nbh_manifest": corpus.manifest_sha256, "module_sha256": _sha(__file__),
                        "prm_module_sha256": _sha(prm.__file__)},
             "nbh_corpus_stats": dict(corpus.stats)}

    def finish():
        (out / "rp_loyo_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True, default=str),
                                                encoding="utf-8")
        return audit

    timezones = {m: str(tz) for m, (_, tz) in stations.items()}
    frame, buckets = prm.dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise RPError("a training row is from 2026")
    frame, audit["train_nbm"] = prm.attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff,
                                                        timezones)
    frame = frame[frame["hour"].isin(RP_HOURS)].reset_index(drop=True)

    stats, gaps, ages, xs = defaultdict(int), [], defaultdict(list), []
    for market, day, hour, F, A in zip(frame["market"], frame["target_date"], frame["hour"], frame["F"],
                                       frame["fh"]):
        icao, tz = stations[market]
        target = date.fromisoformat(str(day)[:10])
        f_rem, cycle, reason = nbh_feature(corpus, icao, target, int(hour), tz)
        x = feature_x(f_rem, F, A)
        stats["rows"] += 1
        if x is None:
            stats[f"miss_{reason if reason != 'ok' else 'anchor_or_floor'}"] += 1
        else:
            stats["covered"] += 1
            gaps.append(x)
            t = datetime(target.year, target.month, target.day, int(hour), tzinfo=tz).astimezone(timezone.utc)
            ages[f"{market}|h{int(hour)}"].append(((t - cycle).total_seconds() / 3600, cycle.hour))
        xs.append(x)
    frame = frame.assign(rp_x=[np.nan if v is None else v for v in xs])
    audit["training"] = dict(stats)
    audit["training_cycle_age"] = _age_report(ages)
    audit["gates"]["1a_parity_training"] = parity_verdict(stats, gaps)
    if not audit["gates"]["1a_parity_training"]["pass"]:
        audit["stopped_at"] = "gate 1a parity (training half; not a kill)"
        return finish()

    rows, fits, devfit = [], {}, {}
    for hour in RP_HOURS:
        at_hour = frame[frame["hour"] == hour].reset_index(drop=True)
        years = sorted(int(y) for y in at_hour["year"].unique())
        inner = {(arm, Y): np.zeros(len(GRID)) for arm in RP_ARMS for Y in years}
        outer_sum = {arm: np.zeros(len(GRID)) for arm in RP_ARMS}
        outer = {}
        # inner fits: one model per unordered pair {Y, Z}, predicting both held-out years
        for i, Y in enumerate(years):
            for Z in years[i + 1:]:
                train = at_hour[~at_hour["year"].isin([Y, Z])].reset_index(drop=True)
                for arm, simple in prm.RUNG_ARMS.items():
                    entry = prm._rung_entry(train, simple)
                    for held, other in ((Z, Y), (Y, Z)):  # prediction of `held` is inner for outer `other`
                        val = at_hour[at_hour["year"] == held].reset_index(drop=True)
                        for market in sorted(val["market"].unique()):
                            part = val[val["market"] == market].reset_index(drop=True)
                            for j, dist in enumerate(prm._dist_from_fit(entry, part, buckets, market)):
                                x = part.at[j, "rp_x"]
                                if not math.isfinite(x):
                                    continue
                                inner[(arm, other)] += grid_briers(dist, buckets[market], float(x),
                                                                   float(part.at[j, "F"]), int(part.at[j, "y"]))
        # outer fits
        for Y in years:
            train = at_hour[at_hour["year"] != Y].reset_index(drop=True)
            val = at_hour[at_hour["year"] == Y].reset_index(drop=True)
            for arm, simple in prm.RUNG_ARMS.items():
                entry = prm._rung_entry(train, simple)
                for market in sorted(val["market"].unique()):
                    part = val[val["market"] == market].reset_index(drop=True)
                    for j, dist in enumerate(prm._dist_from_fit(entry, part, buckets, market)):
                        key = (market, str(part.at[j, "target_date"])[:10])
                        x = part.at[j, "rp_x"]
                        outer.setdefault((Y,) + key, {})[arm] = (dist, float(x), float(part.at[j, "F"]),
                                                                 int(part.at[j, "y"]), market)
                        if math.isfinite(x):
                            outer_sum[arm] += grid_briers(dist, buckets[market], float(x), float(part.at[j, "F"]),
                                                          int(part.at[j, "y"]))
        for arm in RP_ARMS:
            for Y in years:
                fits[f"{arm}|h{hour}|{Y}"] = pick_ab(inner[(arm, Y)])
            devfit[f"{arm}|h{hour}"] = pick_ab(outer_sum[arm])
        for (Y, market, day), arms in sorted(outer.items()):
            row = {"hour": int(hour), "year": int(Y), "market": market, "date": day}
            for arm, (dist, x, F, y, mk) in arms.items():
                row[f"{arm}_brier"], row[f"{arm}_log"] = fm.brier_score(dist, y), fm.log_loss(dist, y)
                ab = fits[f"{arm}|h{hour}|{Y}"]
                cand = dist if not math.isfinite(x) else translate(dist, buckets[mk], ab["a"] + ab["b"] * x, F)
                row[f"{RP_ARMS[arm]}_brier"], row[f"{RP_ARMS[arm]}_log"] = fm.brier_score(cand, y), fm.log_loss(cand, y)
            row["rp_x_missing"] = int(not math.isfinite(next(iter(arms.values()))[1]))
            rows.append(row)
        print(f"rp loyo hour {hour}: {sum(1 for r in rows if r['hour'] == hour)} rows", flush=True)

    prm._write_jsonl(out / "loyo_rows.jsonl", rows)
    (out / "ab_fits.json").write_text(json.dumps({"rule_sha256": RP_RULE_SHA256, "loyo": fits, "dev": devfit},
                                                 indent=1, sort_keys=True), encoding="utf-8")
    audit["files"] = {n: _sha(out / n) for n in ("loyo_rows.jsonl", "ab_fits.json")}
    audit["control_rj_reproduction"] = prm.rk_control(rows, prm._read_jsonl(rj_loyo_rows))
    if not audit["control_rj_reproduction"]["pass"]:
        audit["stopped_at"] = "control: R-J LOYO reproduction failed (refused, not a gate)"
        return finish()
    audit["fits_b_zero_share"] = {arm: sum(1 for k, v in fits.items() if k.startswith(arm + "|") and v["b"] == 0)
                                  / max(1, sum(1 for k in fits if k.startswith(arm + "|"))) for arm in RP_ARMS}
    audit["gates"]["2_loyo"] = prm.rg_loyo_summary(rows, pairs=RP_PAIRS, pooled=RP_POOLS)
    primary = audit["gates"]["2_loyo"]["B_P-B_N|13-16|brier"]
    audit["gates"]["2_loyo"]["pass"] = primary["ci95"][1] < 0
    if not audit["gates"]["2_loyo"]["pass"]:
        audit["stopped_at"] = "gate 2 LOYO (KILL: NBH remaining-hours path closed as a 13-16 centre input)"
    return finish()


# ----------------------------------------------------------------------------- gate 1b and the dev emit


def rp_dev_emit(*, records_root, layout, replay_root, nbm_train_corpus, nbh_dev_corpus, loyo_dir, out_dir,
                markets=prm.R0_MARKETS):
    """Gate 1b: L2's own dev_emit_rung reproduces R-H byte for byte while its A/F inputs are recorded; then the
    translated candidates are written with the LOYO-fitted dev (a, b)."""
    loyo = Path(loyo_dir)
    loyo_audit = json.loads((loyo / "rp_loyo_audit.json").read_bytes())
    if loyo_audit.get("rule_sha256") != RP_RULE_SHA256 or loyo_audit.get("stopped_at") \
            or not loyo_audit["gates"].get("2_loyo", {}).get("pass"):
        raise RPError(f"LOYO did not pass gates 1a-2: {loyo_audit.get('stopped_at')}")
    if _sha(loyo / "ab_fits.json") != loyo_audit["files"]["ab_fits.json"]:
        raise RPError("ab_fits.json changed since the LOYO audit")
    devfit = json.loads((loyo / "ab_fits.json").read_bytes())["dev"]
    out = _require_empty(out_dir)
    l2_dir = out / "l2_reproduction"
    stations = _stations(markets)
    corpus = NBHCorpus(nbh_dev_corpus, sorted({s for s, _ in stations.values()}))

    calls = []
    original = prm._dist_from_fit

    def recording(entry, one, buckets, market):
        dists = original(entry, one, buckets, market)
        for i in range(len(one)):
            calls.append({"market": market, "hour": int(one["hour"].iat[i]), "target_date": str(one["target_date"].iat[i]),
                          "F": float(one["F"].iat[i]), "A": float(one["fh"].iat[i]), "space": list(buckets[market])})
        return dists

    prm._dist_from_fit = recording
    try:
        l2_audit = prm.dev_emit_rung(records_root=records_root, layout=layout, replay_root=replay_root,
                                     nbm_train_corpus=nbm_train_corpus, out_dir=l2_dir, markets=markets,
                                     hours=RP_HOURS, loyo=False)
    finally:
        prm._dist_from_fit = original
    audit = {"rule_sha256": RP_RULE_SHA256, "gates": {}, "l2_files": l2_audit["files"],
             "inputs": {"nbh_dev_corpus": str(corpus.root), "nbh_sha256sums": corpus.sums_sha256,
                        "nbh_manifest": corpus.manifest_sha256, "loyo_audit": _sha(loyo / "rp_loyo_audit.json"),
                        "ab_fits": _sha(loyo / "ab_fits.json"), "module_sha256": _sha(__file__)},
             "nbh_corpus_stats": dict(corpus.stats), "dev_ab": devfit}

    def finish():
        (out / "rp_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True, default=str),
                                                encoding="utf-8")
        return audit

    reproduced = all(l2_audit["files"].get(n) == s for n, s in RH_EMIT.items())
    arm_names = list(prm.RUNG_ARMS)
    lines = {arm: (l2_dir / f"dev_{arm}.jsonl").read_text(encoding="utf-8").splitlines() for arm in arm_names}
    aligned = len(calls) == len(arm_names) * len(lines[arm_names[0]]) and all(
        len(lines[a]) == len(lines[arm_names[0]]) for a in arm_names)
    audit["control_rh_reproduction"] = {"files_identical": reproduced, "calls_aligned": aligned,
                                        "n_rows": len(lines[arm_names[0]])}
    if not (reproduced and aligned):
        audit["stopped_at"] = "control: R-H reproduction or input alignment failed (refused)"
        return finish()

    stats, gaps, ages = defaultdict(int), [], defaultdict(list)
    feats = {}
    writers = {arm: open(out / f"dev_{RP_ARMS[arm]}.jsonl", "w", encoding="utf-8") for arm in arm_names}
    try:
        for i in range(len(lines[arm_names[0]])):
            for k, arm in enumerate(arm_names):
                rec = json.loads(lines[arm][i])
                inp = calls[i * len(arm_names) + k]
                if rec["market"] != inp["market"] or rec["target_date"] != inp["target_date"][:10]:
                    raise RPError(f"input alignment broke at row {i}")
                target = date.fromisoformat(rec["target_date"])
                if target > LAST_ALLOWED:
                    raise RPError("dev row after the cutoff")
                key = (inp["market"], rec["target_date"], inp["hour"])
                if key not in feats:
                    icao, tz = stations[inp["market"]]
                    feats[key] = nbh_feature(corpus, icao, target, inp["hour"], tz)
                f_rem, cycle, reason = feats[key]
                x = feature_x(f_rem, inp["F"], inp["A"])
                if k == 0:
                    stats["rows"] += 1
                    if x is None:
                        stats[f"miss_{reason if reason != 'ok' else 'anchor_or_floor'}"] += 1
                    else:
                        stats["covered"] += 1
                        gaps.append(x)
                        t = datetime(target.year, target.month, target.day, inp["hour"],
                                     tzinfo=stations[inp["market"]][1]).astimezone(timezone.utc)
                        ages[f"{inp['market']}|h{inp['hour']}"].append(((t - cycle).total_seconds() / 3600,
                                                                         cycle.hour))
                ab = devfit[f"{arm}|h{inp['hour']}"]
                dist = {int(b): p for b, p in rec["distribution"].items()}
                cand = dist if x is None else translate(dist, inp["space"], ab["a"] + ab["b"] * x, inp["F"])
                writers[arm].write(json.dumps({
                    "market": rec["market"], "snapshot_id": rec["snapshot_id"], "target_date": rec["target_date"],
                    "distribution": {str(b): p for b, p in sorted(cand.items()) if p > 0}}, sort_keys=True) + "\n")
    finally:
        for w in writers.values():
            w.close()
    audit["dev"] = dict(stats)
    audit["dev_cycle_age"] = _age_report(ages)
    audit["files"] = {f"dev_{RP_ARMS[a]}.jsonl": _sha(out / f"dev_{RP_ARMS[a]}.jsonl") for a in arm_names}
    audit["gates"]["1b_parity_dev"] = parity_verdict(stats, gaps)
    if not audit["gates"]["1b_parity_dev"]["pass"]:
        audit["stopped_at"] = "gate 1b parity (dev half; not a kill)"
    return finish()


# ----------------------------------------------------------------------------- gates 3 and 4 (dev score)


def rp_score(*, layout, emit_dir, p3d_n_jsonl, out_path, start="2026-08-01", end="2026-09-29"):
    """Gate 3 (P3d_P vs P3d_N_fix) and gate 4 (vs MG-2's post-13 arm), R-J's scorecard construction."""
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = prm.require_output_outside_repo(out_path)
    if out_path.exists():
        raise RPError(f"refusing to overwrite {out_path}")
    emit = Path(emit_dir)
    audit = json.loads((emit / "rp_emit_audit.json").read_bytes())
    if audit.get("rule_sha256") != RP_RULE_SHA256 or audit.get("stopped_at"):
        raise RPError(f"emit is not an R-P emit that passed gate 1b: {audit.get('stopped_at')}")
    files = {**{f"l2_reproduction/{n}": s for n, s in RH_EMIT.items()}, **audit["files"]}
    for rel, sha in files.items():
        if _sha(emit / rel) != sha:
            raise RPError(f"{rel} changed since the emit")
    n_sha = _sha(p3d_n_jsonl)
    if n_sha != P3D_N_SHA256:
        raise RPError(f"P3d_N dev sha {n_sha} != {P3D_N_SHA256}")
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)

    def vec(path):
        return l3._vector(table, l3._candidate_frame(str(path), table, lay, folds, data)[0])

    paths = {"B_N": emit / "l2_reproduction" / "dev_B_N.jsonl",
             "P3d_N_fix": emit / "l2_reproduction" / "dev_P3d_N_fix.jsonl",
             "B_P": emit / "dev_B_P.jsonl", "P3d_P": emit / "dev_P3d_P.jsonl"}
    arms = {arm: vec(p) for arm, p in paths.items()}
    p_mg1, cov_mg1, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    p_n, cov_n, r_n = vec(p3d_n_jsonl)
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise RPError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    p_comp = np.where(cov_n[table.band_snap], p_n, p_mg1)
    p_cand = np.where(arms["P3d_P"][1][table.band_snap], arms["P3d_P"][0], p_mg1)
    briers = {arm: table.brier(v[0]) for arm, v in arms.items()}
    covs = {arm: v[1] for arm, v in arms.items()}
    briers["composite_post13"], covs["composite_post13"] = table.brier(p_comp), cov_n | cov_mg1
    briers["P3d_P_composite"], covs["P3d_P_composite"] = table.brier(p_cand), covs["P3d_P"] | cov_mg1
    common = covs["B_N"] & covs["B_P"] & covs["P3d_N_fix"] & covs["P3d_P"] & covs["composite_post13"]
    groups = [("13-16", 13, 16), ("13-14", 13, 14), ("15-16", 15, 16)] + [(f"h{h}", h, h) for h in RP_HOURS]
    pools = [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]

    def compare(arm, ref):
        rows = []
        for market, members in pools:
            in_pool = np.ones(len(table.snaps), bool) if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in (groups if members is None else groups[:3]):
                mask = common & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(briers[arm], mask)
                _, r_ = table.cells(briers[ref], mask)
                _, m = table.cells(market_b, mask)
                rows.append({"arm": arm, "reference": ref, "market": market, "group": group,
                             "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                             "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                             "R_arm_date_clustered": sc.ratio_interval(date_w[:, idx], c, m),
                             "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                             "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                             "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
        return rows

    def pick(rows, group):
        return next(r for r in rows if r["market"] == sc.ALL_MARKETS and r["group"] == group)

    def reading(rows):
        p = pick(rows, "13-16")["dR_date_clustered"]["ci95"]
        lower = [pick(rows, f"h{h}")["dR_date_clustered"]["ci95"][0] for h in RP_HOURS]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in lower) else "NULL"

    in_rp = (table.local_hour >= 13) & (table.local_hour <= 16)
    result = {"rule": "C:/t/l14/rp/rule_rp.md", "rule_sha256": RP_RULE_SHA256,
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys),
                             "common_covered_snapshots": {g: int((common & (table.local_hour >= lo)
                                                                  & (table.local_hour <= hi)).sum())
                                                          for g, lo, hi in groups}},
              "controls": {"mg1_excess_07_12": mg1_excess,
                           "composite_post13_mg1_fallback_snapshots_13_16": int((in_rp & ~cov_n & cov_mg1).sum()),
                           "gate1b": audit["gates"]["1b_parity_dev"]},
              "coverage": {"P3d_N": r_n},
              "inputs": {"emit_files": files, "p3d_n_sha256": n_sha,
                         "emit_audit_sha256": _sha(emit / "rp_emit_audit.json"),
                         "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                         "module_sha256": _sha(__file__)},
              "gates": {}, "rows": []}

    def done():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        return result

    result["rows"] += compare("B_P", "B_N")  # reported only
    result["rows"] += compare("P3d_N_fix", "composite_post13")  # reported only (incumbent sizing)
    rows = compare("P3d_P", "P3d_N_fix")
    result["rows"] += rows
    g3 = pick(rows, "13-16")["dR_date_clustered"]
    result["gates"]["3_P3d_P_vs_P3d_N_fix_13_16"] = {"dR_date_clustered": g3, "pass": g3["ci95"][1] < 0}
    if not result["gates"]["3_P3d_P_vs_P3d_N_fix_13_16"]["pass"]:
        result["stopped_at"] = "gate 3 (KILL: NBH remaining-hours path closed as a 13-16 centre input)"
        return done()
    rows = compare("P3d_P_composite", "composite_post13")
    result["rows"] += rows
    result["gates"]["4_vs_composite_post13"] = {"reading": reading(rows),
                                                "dR_date_clustered": pick(rows, "13-16")["dR_date_clustered"]}
    return done()


# ----------------------------------------------------------------------------- CLI


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.nbh_centre_shift", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lo = sub.add_parser("loyo", help="gates 1a and 2 (2021-25 only)")
    lo.add_argument("--records", required=True)
    lo.add_argument("--nbm-train-corpus", required=True)
    lo.add_argument("--nbh", required=True)
    lo.add_argument("--rj-loyo-rows", required=True)
    lo.add_argument("--out", required=True)
    em = sub.add_parser("dev-emit", help="gate 1b and the translated dev distributions")
    em.add_argument("--records", required=True)
    em.add_argument("--layout", required=True)
    em.add_argument("--replay-root", required=True)
    em.add_argument("--nbm-train-corpus", required=True)
    em.add_argument("--nbh-dev", required=True)
    em.add_argument("--loyo", required=True)
    em.add_argument("--out", required=True)
    scp = sub.add_parser("score", help="gates 3 and 4")
    scp.add_argument("--layout", required=True)
    scp.add_argument("--emit", required=True)
    scp.add_argument("--p3d-n", required=True)
    scp.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "loyo":
        res = rp_loyo(records_root=a.records, nbm_train_corpus=a.nbm_train_corpus, nbh_corpus=a.nbh,
                      rj_loyo_rows=a.rj_loyo_rows, out_dir=a.out)
        print(json.dumps({"stopped_at": res.get("stopped_at"), "gate1a": res["gates"].get("1a_parity_training"),
                          "gate2_pass": res["gates"].get("2_loyo", {}).get("pass")}, default=str))
    elif a.cmd == "dev-emit":
        res = rp_dev_emit(records_root=a.records, layout=a.layout, replay_root=a.replay_root,
                          nbm_train_corpus=a.nbm_train_corpus, nbh_dev_corpus=a.nbh_dev, loyo_dir=a.loyo,
                          out_dir=a.out)
        print(json.dumps({"stopped_at": res.get("stopped_at"), "gate1b": res["gates"].get("1b_parity_dev")},
                         default=str))
    else:
        res = rp_score(layout=a.layout, emit_dir=a.emit, p3d_n_jsonl=a.p3d_n, out_path=a.out)
        print(json.dumps({"stopped_at": res.get("stopped_at"), "gates": res["gates"]}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
