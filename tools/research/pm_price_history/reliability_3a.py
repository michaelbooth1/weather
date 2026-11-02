"""3a: history-tier market reliability by price bin (ledger row 113), the single pre-registered run.

Rule: ``docs/research/pm-history-reliability-3a-2026-11-01/rule_3a.md`` (sha256 023b75ed...837a) and its
Clarification 1 (pins this file's sha256 and the vendored statistic's sha256).

The statistic is L21's, unchanged: ``l21_stats_e541ad401.py`` beside this file is a byte-identical copy of
``docs/research/market-reliability-bin-2026-11-01/run_reliability.py`` at
e541ad401110157c71b14b0bfa4589020bb6fe82 (sha256 ``L21_STATS_SHA256``; checked at import). This module only:

- builds the population from the sealed step-2 history run (book mid at pinned local times, after side);
- swaps L21's leave-one-date-out groups for leave-one-calendar-month-out groups (the ``starts`` argument
  of L21's ``deltas``; the fold arithmetic is L21's own);
- reads labels and hourly observations ONLY from the bounded extracts (dated <= 2026-05-26);
- applies the rule's C2 order: 1 price integrity, 2 label integrity, 3 synthetic controls,
  4 training-score check, 5 realised power. No real Delta reaches stdout, the receipt or any file
  unless steps 1-5 passed.

Modes (one required):
--synthetic-only   Opens no label and no observation file. Reads only the sealed run (re-verified against
                   SHA256SUMS). Runs steps 1, 3, 4 (null) and 5 (null projection); step 2's label part is
                   NOT RUN, its band-tiling part runs.
--real-run         Needs --labels-extract and --expect-sha equal to this file's sha256. --hourly-extract
                   applies the floor exclusion; without it the verdict is labelled floor-unadjusted.

No network. Standard library plus numpy and pandas (and L21's imports). No B-bound file is touched.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tools.research.pm_price_history import guards
from tools.research.pm_price_history import l21_stats_e541ad401 as l21

# ----------------------------------------------------------------------------- frozen constants (rule_3a)
L21_STATS_SHA256 = "df12cc8cab980b2af71c55942ce9ec9bbc8422d17c5852bdfc7ae332e421f7a3"
L21_COMMIT = "e541ad401110157c71b14b0bfa4589020bb6fe82"
RULE_SHA256 = "023b75ed6fcdd14ecc83e5f36f961077c3e338130f7f0434bb3836732088837a"
RUN_SUMS_SHA256 = "5073afd8f16ad4a7e9eb21b06df7bbaf78464f12ad4101b27440afc9ed31fe71"
FIDCHECK_OUTPUT_SHA256 = "1ea5c9af53e48590f073b38868a355d956141c6a49b1d0730af03085341fbf55"
# the only extractor whose output 3a accepts (extract_bounded_v1.py; its manifest records its own sha256)
EXTRACTOR_SHA256 = "a93779d0cf696c88b999a2bd566592a0f1e2bc5ebabaf992bef68eb7eb40db6e"
HARD_LAST = date(2026, 5, 26)
D_FIRST, D_LAST = date(2025, 12, 1), HARD_LAST
NYC25_FIRST, NYC25_LAST = date(2025, 1, 1), date(2025, 11, 30)
B12 = ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
       "san-francisco", "seattle", "toronto")
R1R2 = ("london", "paris", "seoul", "tokyo", "shanghai", "munich", "madrid", "beijing", "wellington",
        "hong-kong")
DECIDING_HOURS = (7, 10)
DESCRIPTIVE_HOURS = (13,)
TOL_S = 120
DJF = ("12", "01", "02")
LABEL_EXACTLY_ONE_MIN = 0.99
LABEL_UNUSABLE_MAX_PCT = 2         # Clarification 1 ruling 3: partial + missing <= 2% of D market-dates
POWER_RESTATE_ABOVE_PCT = 1        # ruling 3: restate N and MDE80 when more than 1% of D is excluded
# L21 raises its own step names; 3a's C2 order numbers them one higher (Clarification 1 section 2).
L21_STEP_NAMES = {"2_synthetic_controls": "3_synthetic_controls",
                  "3_training_score_check": "4_training_score_check",
                  "4_realised_power": "5_realised_power",
                  "labels": "2_label_integrity"}
RULE_T2_N, RULE_T2_MDE80 = 1419, 0.105
# ruling 2: the completeness threshold is the settlement code's own, not a 3a number.
COMPLETENESS_SOURCE = ("src/weather/backtesting/settlement_ledger.py:34 COMPLETE_DAY_MIN_ROWS "
                       "(applied at :498 as row_count >= it; venue_label_reader.py:205 treats < it as incomplete)")
TAILS_FIRST = (0, 10, 1, 9, 2, 8, 3, 4, 5, 6, 7)          # [0,.02) [.95,1] [.02,.05) [.90,.95) [.05,.10) [.80,.90) ..
ARMS = l21.ARMS


def _check_vendored():
    got = l21.sha256_file(Path(l21.__file__))
    if got != L21_STATS_SHA256:
        raise SystemExit(f"refused: vendored L21 statistic sha256 {got} != {L21_STATS_SHA256}")


class Refusal(Exception):
    """Fail-closed refusal; reported as a mechanical failure, never as a read."""


def within_unusable_cap(unusable: int, n: int) -> bool:
    """Ruling 3, integer-exact: partial + missing <= 2% of D (exactly 2.0% passes)."""
    return n > 0 and unusable * 100 <= LABEL_UNUSABLE_MAX_PCT * n


def restate_needed(excluded: int, n: int) -> bool:
    """Ruling 3, integer-exact: N and MDE80 are restated only when MORE than 1% of D is excluded."""
    return excluded * 100 > POWER_RESTATE_ABOVE_PCT * n


def require_hist_date(d: date) -> date:
    """No history, label or observation dated after 2026-05-26 is ever used (the date is not echoed)."""
    if d > HARD_LAST:
        raise Refusal(f"refused: a date after {HARD_LAST} reached 3a")
    return d


# ----------------------------------------------------------------------------- sealed run

class SealedRun:
    """Every byte read from the sealed run is checked against its SHA256SUMS entry at the moment it is read."""

    def __init__(self, run_dir: Path, expect_sums_sha: str):
        self.root = run_dir
        sums = run_dir / "SHA256SUMS"
        raw = sums.read_bytes()
        got = hashlib.sha256(raw).hexdigest()
        if got != expect_sums_sha:
            raise Refusal("refused: SHA256SUMS sha256 does not match the pinned value")
        self.sums = {}
        for line in raw.decode("utf-8").splitlines():
            digest, rel = line.split("  ", 1)
            self.sums[rel.replace("\\", "/")] = digest
        self.sums_sha256, self.verified = got, 0

    def read(self, rel: str) -> bytes:
        rel = rel.replace("\\", "/")
        digest = self.sums.get(rel)
        if digest is None:
            raise Refusal("refused: file not listed in the sealed run's SHA256SUMS")
        data = (self.root / rel).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise Refusal("refused: a sealed-run file does not match SHA256SUMS")
        self.verified += 1
        return data

    def verify_all(self) -> int:
        """Rule section 6 step 1: the whole SHA256SUMS re-verifies, not only the files 3a reads."""
        for rel, digest in self.sums.items():
            if l21.sha256_file(self.root / rel) != digest:
                raise Refusal("refused: a sealed-run file does not match SHA256SUMS")
        self.all_verified = len(self.sums)
        return self.all_verified

    def summary(self) -> dict:
        return {"sha256sums_sha256": self.sums_sha256, "files_listed": len(self.sums),
                "files_reverified": getattr(self, "all_verified", 0), "files_read_and_verified": self.verified}


def local_epoch(day: date, hour: int, tz: str) -> int:
    return int(datetime(day.year, day.month, day.day, hour, 0, tzinfo=ZoneInfo(tz)).timestamp())


def pick(stamps, prices, ts, side):
    if side == "after":
        i = bisect.bisect_left(stamps, ts)
        ok = i < len(stamps) and stamps[i] - ts <= TOL_S
    else:
        i = bisect.bisect_right(stamps, ts) - 1
        ok = i >= 0 and ts - stamps[i] <= TOL_S
    return prices[i] if ok else None


def band_parse(label, unit):
    from weather.units import parse_temperature_band
    b = parse_temperature_band(label, expected_unit=unit)
    if b is None:
        return None
    return {"kind": b.kind, "value": int(b.value), "value_hi": int(b.value_hi),
            "high": int(b.value_hi if b.kind == "eq" else b.value)}


def tiles(bands) -> bool:
    """lte first, gte last, eq in between, contiguous whole degrees, no gap or overlap."""
    s = sorted(bands, key=lambda b: (b["value"], b["value_hi"]))
    if len(s) < 2 or s[0]["kind"] != "lte" or s[-1]["kind"] != "gte":
        return False
    if any(b["kind"] != "eq" for b in s[1:-1]):
        return False
    upper = s[0]["value"]
    for b in s[1:]:
        if b["value"] != upper + 1:
            return False
        upper = b["value_hi"] if b["kind"] == "eq" else None
    return True


def segment(market, d):
    if market in B12 and D_FIRST <= d <= D_LAST:
        return "D"
    if market == "nyc" and NYC25_FIRST <= d <= NYC25_LAST:
        return "NYC25"
    return None


def load_population(run: SealedRun, specs: dict) -> tuple[list, dict]:
    """One pass over the admitted, in-scope events: per ladder the mid at each (side, hour)."""
    paths = {}
    for line in run.read("tokens.jsonl").decode("utf-8").splitlines():
        if line.strip():
            t = json.loads(line)
            paths[(t["market"], t["event_slug"], str(t["yes_token"]))] = t["path"]
    info = Counter()
    by_md = defaultdict(list)
    for line in run.read("events.jsonl").decode("utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            d = date.fromisoformat(e["event_date"])
            if d > HARD_LAST:            # prices only (no outcome is in the run); skipped silently, uncounted
                continue
            guards.require_admitted(d)
            if e["market"] in R1R2:
                info[f"r1r2_excluded_no_venue_rule_label_extract:{e['market']}"] += 1
                continue
            seg = segment(e["market"], d)
            if seg is None:
                info["events_out_of_segments"] += 1
                continue
            by_md[(e["market"], e["event_date"])].append((seg, e))
    ladders = []
    for (market, ds), evs in sorted(by_md.items()):
        if len(evs) > 1:
            info[f"duplicate_market_date_excluded:{evs[0][0]}"] += 1
            continue
        seg, e = evs[0]
        d = require_hist_date(date.fromisoformat(ds))
        spec = specs[market]
        bands = []
        for i, b in enumerate(e["bands"]):
            pb = band_parse(b.get("band_label"), spec["unit"])
            if pb is None:
                bands = None
                break
            bands.append({**pb, "band_index": i, "token": str(b["yes_token"])})
        if bands is None:
            info[f"ladder_band_unparseable:{seg}"] += 1
            continue
        stamps = {h: local_epoch(d, h, spec["tz"]) for h in (*DECIDING_HOURS, *DESCRIPTIVE_HOURS)}
        mids = {}
        for b in bands:
            rel = paths.get((market, e["slug"], b["token"]))
            if rel is None:
                mids = None
                break
            body = json.loads(gzip.decompress(run.read(rel)))
            pts = sorted((int(p["t"]), float(p["p"])) for p in body.get("history") or [] if "t" in p and "p" in p)
            st, pr = [p[0] for p in pts], [p[1] for p in pts]
            for side in ("after", "before"):
                for hr, ts in stamps.items():
                    mids[(b["band_index"], side, hr)] = pick(st, pr, ts, side)
        if mids is None:
            info[f"ladder_token_missing:{seg}"] += 1
            continue
        ladders.append({"market": market, "date": ds, "segment": seg, "bands": bands, "mids": mids,
                        "tiles": tiles(bands)})
    info["ladders_loaded"] = len(ladders)
    return ladders, dict(info)


def build_rows(ladders, seg, side, hours, labels=None, floors=None):
    """L21 Pop rows for one variant. Incomplete or zero-sum ladders are excluded and counted."""
    out, info, key = [], Counter(), 0
    for lad in ladders:
        if lad["segment"] != seg:
            continue
        for hr in hours:
            m = [lad["mids"][(b["band_index"], side, hr)] for b in lad["bands"]]
            if any(v is None for v in m):
                info[f"incomplete:{lad['market']}:{hr:02d}"] += 1
                continue
            if sum(m) <= 0:
                info[f"zero_sum:{lad['market']}:{hr:02d}"] += 1
                continue
            fl = np.nan if floors is None else floors.get((lad["market"], lad["date"], hr), np.nan)
            win = None if labels is None else labels.get((lad["market"], lad["date"]))
            key += 1
            for b, v in zip(lad["bands"], m):
                imp = (not np.isnan(fl)) and b["kind"] != "gte" and b["high"] < np.floor(fl + 0.5)
                out.append({"row_key": key, "band_index": b["band_index"], "date": lad["date"],
                            "market": lad["market"], "local_hour": hr, "p_market_yes": float(v),
                            "impossible": bool(imp), "winner": win})
    rows = pd.DataFrame(out)
    if len(rows):
        rows = rows.sort_values(["date", "market", "local_hour", "row_key", "band_index"]).reset_index(drop=True)
    info["ladders"] = int(rows["row_key"].nunique()) if len(rows) else 0
    info["band_rows"] = int(len(rows))
    info["impossible_rows"] = int(rows["impossible"].sum()) if len(rows) else 0
    info["dates"] = int(rows["date"].nunique()) if len(rows) else 0
    info["market_dates"] = int(rows.groupby(["market", "date"]).ngroups) if len(rows) else 0
    return rows, dict(info)


# ----------------------------------------------------------------------------- bounded extracts

class Extract:
    """A bounded extract, read like the sealed run: every byte through its SHA256SUMS, at the moment it is read.

    Refuses unless the manifest (itself read through SHA256SUMS) names ``kind``, declares ``last`` <= 2026-05-26
    and records ``script_sha256`` equal to the pinned ``EXTRACTOR_SHA256``. A file not listed is never read.
    """

    def __init__(self, root: Path, kind: str, expect_extractor_sha: str = EXTRACTOR_SHA256):
        self.root = Path(root)
        raw = (self.root / "SHA256SUMS").read_bytes()
        self.sums_sha256 = hashlib.sha256(raw).hexdigest()
        self.sums = {}
        for line in raw.decode("utf-8").splitlines():
            digest, rel = line.split("  ", 1)
            self.sums[rel.replace("\\", "/")] = digest
        self.verified = 0
        manifest = json.loads(self.read("manifest.json"))
        if manifest.get("kind") != kind:
            raise Refusal(f"refused: extract kind is not {kind}")
        if date.fromisoformat(manifest["last"]) > HARD_LAST:
            raise Refusal("refused: extract manifest declares a last date after 2026-05-26")
        if manifest.get("script_sha256") != expect_extractor_sha:
            raise Refusal("refused: the extract was not made by the pinned extractor")
        self.kind, self.extractor_sha256 = kind, manifest["script_sha256"]

    def read(self, rel: str) -> bytes:
        rel = rel.replace("\\", "/")
        digest = self.sums.get(rel)
        if digest is None:
            raise Refusal("refused: file not listed in the extract's SHA256SUMS")
        data = (self.root / rel).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise Refusal("refused: an extract file does not match its SHA256SUMS")
        self.verified += 1
        return data

    def listed(self, prefix: str, suffix: str) -> list:
        return sorted(r for r in self.sums if r.startswith(prefix) and r.endswith(suffix))

    def summary(self) -> dict:
        return {"root": str(self.root), "kind": self.kind, "sha256sums_sha256": self.sums_sha256,
                "manifest_sha256": self.sums["manifest.json"], "extractor_sha256": self.extractor_sha256,
                "files_listed": len(self.sums), "files_read_and_verified": self.verified}


def verify_extract(root: Path, kind: str) -> Extract:
    return Extract(root, kind)


def load_labels(ext: Extract, specs: dict, wanted: set) -> tuple[dict, dict]:
    """(market, date) -> settled whole-degree bucket, from the daily extract only (Clarification 1, L1-L3).

    A wanted market-date with no row, or a row without a numeric bucket, is *missing*; a row with
    ``row_count`` below the settlement ledger's complete-day minimum is *partial* (``sparse``). Both are left
    out of the returned map and counted. ``info["native_high"]`` keeps the raw native high of each usable
    market-date for the containment-vs-bucket diagnostic (ruling 1; it never selects anything).
    """
    from weather.backtesting.settlement_ledger import COMPLETE_DAY_MIN_ROWS
    from weather.sources.daily_summary import native_bucket, native_high
    out, info, highs = {}, Counter(), {}
    for market, spec in specs.items():
        rel = f"{spec['icao']}/daily_summary.csv"
        if rel not in ext.sums:
            continue                       # no source for this station: its wanted dates count as missing
        seen = set()
        with io.StringIO(ext.read(rel).decode("utf-8"), newline="") as h:
            for row in csv.DictReader(h):
                d = require_hist_date(date.fromisoformat(row["local_date"]))
                if d in seen:
                    raise Refusal("refused: two daily rows for one station-date (not echoed)")
                seen.add(d)
                key = (market, d.isoformat())
                if key not in wanted:
                    continue
                try:
                    rc = int(float(row.get("row_count") or 0))
                except (TypeError, ValueError):
                    rc = 0
                bucket = native_bucket(row)
                out[key] = "missing" if bucket is None else ("sparse" if rc < COMPLETE_DAY_MIN_ROWS else bucket)
                highs[key] = native_high(row)
    unusable = {}
    for key in wanted:
        state = out.get(key, "missing")
        if state in ("missing", "sparse"):
            info[f"{state}_wu_day"] += 1
            unusable[key] = state
    info["unusable"] = unusable
    info["native_high"] = {k: highs.get(k) for k, v in out.items() if v not in ("missing", "sparse")}
    return {k: v for k, v in out.items() if v not in ("missing", "sparse")}, info


def load_floors(ext: Extract, specs: dict, wanted: set) -> dict:
    """(market, date, hour) -> max observed temp_native with local time <= hour:00, hourly extract only."""
    from weather.units import to_float
    obs = defaultdict(list)
    for market, spec in specs.items():
        for rel in ext.listed(f"{spec['icao']}/hourly/", "/observations.jsonl"):
            with io.StringIO(ext.read(rel).decode("utf-8")) as h:
                for line in h:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    d = require_hist_date(date.fromisoformat(row["local_date"]))
                    if (market, d.isoformat()) not in wanted:
                        continue
                    t = to_float(row.get("temp_native"))
                    lt = str(row.get("local_time") or "")
                    if t is None or ":" not in lt:
                        continue
                    hh, mm = lt[:5].split(":")
                    obs[(market, d.isoformat())].append((int(hh) * 60 + int(mm), t))
    floors = {}
    for (market, ds), rows in obs.items():
        for hr in (*DECIDING_HOURS, *DESCRIPTIVE_HOURS):
            seen = [t for minute, t in rows if minute <= hr * 60]
            if seen:
                floors[(market, ds, hr)] = max(seen)
    return floors


def completeness_min_rows() -> int:
    from weather.backtesting.settlement_ledger import COMPLETE_DAY_MIN_ROWS
    return int(COMPLETE_DAY_MIN_ROWS)


def containment_pick(bands, high):
    """The single band whose native range contains the raw high (the rule's original text), else None."""
    if high is None:
        return None
    hits = [b["band_index"] for b in bands
            if (b["kind"] == "lte" and high <= b["value"]) or (b["kind"] == "gte" and high >= b["value"])
            or (b["kind"] == "eq" and b["value"] <= high <= b["value_hi"])]
    return hits[0] if len(hits) == 1 else None


def containment_diagnostic(ladders, labels, highs):
    """Ruling 1: labelled D market-dates where containment of native_high and the settlement bucket pick
    different bands (containment picking no single band counts as different). A count only; it never
    selects or excludes anything."""
    n, differ, none = 0, 0, 0
    for lad in ladders:
        key = (lad["market"], lad["date"])
        if lad["segment"] != "D" or key not in labels:
            continue
        n += 1
        c = containment_pick(lad["bands"], highs.get(key))
        none += c is None
        differ += c != labels[key]
    return {"D_labelled_market_dates": n, "containment_vs_bucket_differ": differ,
            "of_which_containment_picks_no_single_band": none}


def by_market_fold(keys):
    """market -> month fold -> sorted dates (all dates are inside D, <= 2026-05-26)."""
    out = defaultdict(lambda: defaultdict(list))
    for market, ds in sorted(keys):
        out[market][ds[:7]].append(ds)
    return {m: dict(v) for m, v in out.items()}


def winners(ladders, buckets):
    """Per (market, date): the band_index whose range holds the bucket; None unless exactly one."""
    from weather.backtesting.settlement_ledger import resolve_outcome
    out, counts = {}, Counter()
    for lad in ladders:
        key = (lad["market"], lad["date"])
        if key not in buckets:
            continue
        hits = [b["band_index"] for b in lad["bands"]
                if resolve_outcome(b["kind"], b["value"], buckets[key], b["value_hi"])]
        counts["exactly_one" if len(hits) == 1 else ("none" if not hits else "several")] += 1
        if len(hits) == 1:
            out[key] = hits[0]
    return out, dict(counts)


# ----------------------------------------------------------------------------- LOMO adapters over L21

def month_starts(pop):
    months = np.array([d[:7] for d in pop.dates])
    starts = np.flatnonzero(np.r_[True, months[1:] != months[:-1]])
    return starts, [str(months[s]) for s in starts]


def deciding_lomo(pop, y, schemes, eval_mask=None):
    """L21 ``deciding`` with the fold groups set to calendar months (rule_3a section 5)."""
    D = pop.D
    starts, labels = month_starts(pop)
    fit = l21.Stats(pop, y, pop.scored, pop.date_idx, D)
    ev = fit if eval_mask is None else l21.Stats(pop, y, eval_mask, pop.date_idx, D)
    point, kp = l21.deltas(fit, ev, np.ones((1, D)), starts)
    res = {}
    draws = {name: l21.deltas(fit, ev, W, starts)[0] for name, W in schemes.items()}
    for j, arm in enumerate(ARMS):
        per = {name: {"ci95": l21.interval(d[:, j]), "sd": float(d[:, j].std(ddof=1))} for name, d in draws.items()}
        lo = min(v["ci95"][0] for v in per.values())
        hi = max(v["ci95"][1] for v in per.values())
        se = max(v["sd"] for v in per.values())
        res[arm] = {"point": float(point[0, j]), "per_scheme": per, "widest": [lo, hi], "se": se,
                    "power_at_edge": l21.power_at_edge(se)}
    res["_lomo_beta_by_month"] = dict(zip(labels, l21.BETA_GRID[l21.BETA_ORDER[kp[0]]].tolist()))
    res["_stats"] = fit
    return res


def step_synthetic_lomo(pop, schemes):
    """L21 ``step_synthetic`` with ``deciding_lomo`` (same seeds, labels and checks)."""
    rng = np.random.default_rng(l21.SEED)
    y_null = pop.synthetic_y(1.0, rng)
    rng = np.random.default_rng(l21.SEED)
    y_plant = pop.synthetic_y(l21.PLANTED_BETA_TRUE, rng)
    null_res, null_ins = deciding_lomo(pop, y_null, schemes), l21.in_sample(pop, y_null)
    plant_res, plant_ins = deciding_lomo(pop, y_plant, schemes), l21.in_sample(pop, y_plant)
    checks = {
        "null_all_arms_cover_0": all(null_res[a]["widest"][0] <= 0.0 <= null_res[a]["widest"][1] for a in ARMS),
        "null_beta_hat_in_range": l21.NULL_BETA[0] <= null_ins["beta_hat"] <= l21.NULL_BETA[1],
        "planted_beta_hat_in_range": l21.PLANTED_BETA[0] <= plant_ins["beta_hat"] <= l21.PLANTED_BETA[1],
        "planted_a3_widest_lower_gt_0": plant_res["A3_power_lodo"]["widest"][0] > 0.0,
    }
    numbers = {"null": l21.control_summary(null_res, null_ins), "planted": l21.control_summary(plant_res, plant_ins),
               "checks": checks}
    if not all(checks.values()):
        raise l21.Untestable("3_synthetic_controls", numbers)
    return numbers, (y_null, null_res, null_ins)


def pearson_point_lomo(pop, y, res):
    """L21 ``pearson_point`` at the point LOMO fits."""
    r = y - pop.mt
    sc = pop.scored
    fit = res["_stats"]
    starts, labels = month_starts(pop)
    month_of_date = np.searchsorted(starts, np.arange(pop.D), side="right") - 1
    Sm, Nm = np.add.reduceat(fit.S, starts, axis=0), np.add.reduceat(fit.N, starts, axis=0)
    T, TN = fit.S.sum(0), fit.N.sum(0)
    g2_tab = np.divide(T[None] - Sm, TN[None] - Nm, out=np.zeros_like(Sm), where=(TN[None] - Nm) > 1e-9)
    mo = month_of_date[pop.date_idx]
    g2 = g2_tab[mo, pop.bin]
    beta_m = np.array([res["_lomo_beta_by_month"][lab] for lab in labels])
    kcol = np.searchsorted(l21.BETA_GRID, beta_m)[mo]
    g3 = pop.q[np.arange(len(pop.m)), kcol].astype(float) - pop.mt
    return {arm: float(np.corrcoef(g[sc], r[sc])[0, 1]) for arm, g in zip(ARMS, (pop.g1, g2, g3))}


def crossed_interval_lomo(pop, y):
    """L21 ``crossed_interval`` (descriptive, 2,000 draws) with month fold groups."""
    cell_keys = sorted(set(zip(pop.date_idx.tolist(), pop.market_idx.tolist())))
    index = {k: i for i, k in enumerate(cell_keys)}
    cell = np.array([index[k] for k in zip(pop.date_idx.tolist(), pop.market_idx.tolist())])
    cd = np.array([k[0] for k in cell_keys])
    cm = np.array([k[1] for k in cell_keys])
    dstarts, _ = month_starts(pop)
    mo = (np.searchsorted(dstarts, np.arange(pop.D), side="right") - 1)[cd]
    starts = np.flatnonzero(np.r_[True, mo[1:] != mo[:-1]])
    st = l21.Stats(pop, y, pop.scored, cell, len(cell_keys))
    rng = np.random.default_rng(l21.SEED)
    D, M = pop.D, len(pop.markets)
    wd = rng.multinomial(D, np.full(D, 1 / D), size=l21.B_CROSSED)
    wm = rng.multinomial(M, np.full(M, 1 / M), size=l21.B_CROSSED)
    W = wd[:, cd] * wm[:, cm]
    d, _ = l21.deltas(st, st, W, starts)
    return {arm: l21.interval(d[:, j]) for j, arm in enumerate(ARMS)}


# ----------------------------------------------------------------------------- verdict and descriptives

def verdict_3a(res, floor_unadjusted):
    arms = {}
    for arm in ARMS:
        killed, positive = l21.arm_label(arm, *res[arm]["widest"])
        arms[arm] = "KILLED" if killed else ("SCREEN-POSITIVE (descriptive only)" if positive
                                             else "NOT KILLED, NOT SCREEN-POSITIVE")
    if all(v == "KILLED" for v in arms.values()):
        line = "B12-HIST: KILL at edge size (all three arms below Delta 0.2236)"
        if floor_unadjusted:
            line += " (floor-unadjusted; conservative toward KILL)"
    else:
        line = ("B12-HIST: NOT KILLED (selection evidence only: a dev-window or forward prereg may cite it; "
                "never an edge claim, never model improvement)")
    return {"verdict": line, "arms": arms, "selection_evidence_only": True,
            "dev_wins_on_disagreement_with_row_106": True}


def tails_first(table):
    return [table[i] for i in TAILS_FIRST]


def masked(pop, mask, fn):
    keep = pop.scored.copy()
    pop.scored = keep & mask
    try:
        return fn()
    finally:
        pop.scored = keep


def collapse(table):
    def agg(idx):
        n = sum(table[i]["n"] for i in idx)
        obs = sum((table[i]["observed"] or 0) * table[i]["n"] for i in idx)
        mt = sum((table[i]["mean_m_normalised"] or 0) * table[i]["n"] for i in idx)
        return {"n": n, "observed": obs / n if n else None, "mean_m_normalised": mt / n if n else None}
    return {"low_tail_[0,.10)": agg((0, 1, 2)), "middle_[.10,.90)": agg((3, 4, 5, 6, 7, 8)),
            "high_tail_[.90,1]": agg((9, 10))}


def descriptives(pop, y, schemes, res, extra_pops):
    dc = {"date_clustered": schemes["date_clustered"]}
    tab = l21.bin_table(pop, y, pop.scored, schemes)
    n_tot = sum(t["n"] for t in tab)
    r = (y - pop.mt)[pop.scored]
    out = {"bins_scored_tails_first": tails_first(tab),
           "lomo_beta_by_month": res["_lomo_beta_by_month"],
           "calibration_line": l21.calibration_line(pop, y, schemes),
           "pearson_g_r": pearson_point_lomo(pop, y, res),
           "ece": float(sum(t["n"] / n_tot * abs(t["d_b"]["point"]) for t in tab if t["n"])),
           "f_bin_in_sample_oracle": float(sum(t["n"] * t["d_b"]["point"] ** 2 for t in tab if t["n"])
                                           / (r * r).sum()),
           "crossed_date_x_market_ci95": crossed_interval_lomo(pop, y)}
    if (~pop.scored).any():
        allm = np.ones(len(pop.m), bool)
        out["include_impossible_same_g"] = l21.public(deciding_lomo(pop, y, schemes, eval_mask=allm))
        out["bins_all_rows_including_impossible"] = tails_first(l21.bin_table(pop, y, allm, schemes))
    mk = np.array(pop.markets)[pop.market_idx]
    out["per_market"] = {}
    for market in pop.markets:
        sel = mk == market
        out["per_market"][market] = masked(pop, sel, lambda: {
            "bins_collapsed": collapse(l21.bin_table(pop, y, pop.scored, dc)),
            "arms_date_clustered": l21.public(deciding_lomo(pop, y, dc))})
    months = np.array([d[5:7] for d in pop.dates])[pop.date_idx]
    out["per_season"] = {}
    for name, sel in (("Dec-Feb", np.isin(months, DJF)), ("Mar-May", ~np.isin(months, DJF))):
        out["per_season"][name] = masked(pop, sel, lambda: {
            "bins_tails_first": tails_first(l21.bin_table(pop, y, pop.scored, schemes)),
            "arms": l21.public(deciding_lomo(pop, y, schemes))})
    out["per_pinned_time"] = {}
    for hr in DECIDING_HOURS:
        out["per_pinned_time"][f"{hr:02d}:00"] = masked(pop, pop.hour == hr, lambda: {
            "bins_tails_first": tails_first(l21.bin_table(pop, y, pop.scored, schemes)),
            "arms": l21.public(deciding_lomo(pop, y, schemes))})
    for name, (p2, y2) in extra_pops.items():
        s2 = l21.date_weights(p2.D)
        out[name] = {"bins_tails_first": tails_first(l21.bin_table(p2, y2, p2.scored, s2)),
                     "arms": l21.public(deciding_lomo(p2, y2, {"date_clustered": s2["date_clustered"]}))}
    out["2025_line"] = ("2025 history exists only for NYC (and London, R1); no 2025 statement is made for any "
                        "other market. NYC 2025 is descriptive and never pooled.")
    return out


MID_CAVEAT = ("Price = the venue's sampled book mid from public /prices-history (step-2 fidcheck: median "
              "|history - captured mid| 0, |history - last trade| median 0.035); not a traded price and not the "
              "Gamma display price; in thin or wide books, above all in the tail bins, the mid can sit far from "
              "any executable price. 3a measures the mid as a forecast.")


# ----------------------------------------------------------------------------- main

def specs_for(markets):
    from weather.market.market_registry import spec_for_id
    out = {}
    for m in markets:
        s = spec_for_id(m)
        out[m] = {"tz": s.timezone, "unit": s.display_unit, "icao": s.icao.lower()}
    return out


def y_for(pop, rows):
    win = rows.drop_duplicates("row_key").set_index("row_key")["winner"]
    return pop.y_from_winner({int(k): int(v) for k, v in win.items()})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True, help="sealed step-2 run directory")
    ap.add_argument("--expect-run-sums", default=RUN_SUMS_SHA256)
    ap.add_argument("--out", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic-only", action="store_true")
    mode.add_argument("--real-run", action="store_true")
    ap.add_argument("--labels-extract")
    ap.add_argument("--hourly-extract")
    ap.add_argument("--expect-sha")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    _check_vendored()
    script = Path(__file__).resolve()
    script_sha = l21.sha256_file(script)
    if args.real_run and args.expect_sha != script_sha:
        raise SystemExit(f"refused: --real-run needs --expect-sha equal to this script's sha256 {script_sha}")
    if args.real_run and not args.labels_extract:
        raise SystemExit("refused: --real-run needs --labels-extract")
    if args.synthetic_only and (args.labels_extract or args.hourly_extract):
        raise SystemExit("refused: --synthetic-only opens no label or observation extract")
    out_path = Path(args.out)
    run_dir = Path(args.run)
    floor_unadjusted = not args.hourly_extract
    receipt = {"schema": "pm_history_reliability_3a_receipt/1", "mode": "real" if args.real_run else "synthetic_only",
               "command_line": [sys.executable, *sys.argv], "script_sha256": script_sha,
               "l21_stats_sha256": L21_STATS_SHA256, "l21_commit": L21_COMMIT, "rule_sha256": RULE_SHA256,
               "git": l21.git_tip(script.parent), "seed": l21.SEED,
               "draws": {"date_clustered": l21.B_DATE, "block3": l21.B_BLOCK, "block3_circular": l21.B_CIRC,
                         "crossed_descriptive": l21.B_CROSSED},
               "edge": l21.EDGE, "window_D": [D_FIRST.isoformat(), D_LAST.isoformat()],
               "deciding_hours_local": list(DECIDING_HOURS), "side": "after", "tolerance_s": TOL_S,
               "folds": "leave-one-calendar-month-out", "floor_unadjusted": floor_unadjusted,
               "mid_caveat": MID_CAVEAT,
               "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
               "steps": {}}
    stage, rc = "preflight", 0
    try:
        receipt["preflight"] = pre = l21.preflight()
        if args.real_run and not pre["ok"]:
            raise Refusal("preflight refused: memory, thread caps or an active workstation-heavy job")
        stage = "1_price_integrity"
        run = SealedRun(run_dir, args.expect_run_sums)
        run.verify_all()
        stage = "build_population"
        specs = specs_for(B12)
        ladders, load_info = load_population(run, specs)
        receipt["population_load"] = load_info
        receipt["steps"]["1_price_integrity"] = {"status": "PASS", **run.summary(),
                                                 "fidcheck_output_sha256": FIDCHECK_OUTPUT_SHA256}
        d_ladders = [x for x in ladders if x["segment"] == "D"]
        d_unparseable = load_info.get("ladder_band_unparseable:D", 0)
        d_token_missing = load_info.get("ladder_token_missing:D", 0)
        # a D ladder whose bands do not parse cannot tile: it counts as a non-tiling ladder (fails step 2)
        tiling = {"ladders": len(d_ladders) + d_unparseable, "tile": sum(x["tiles"] for x in d_ladders),
                  "of_which_band_unparseable": d_unparseable}
        stage = "2_label_integrity"
        labels = floors = None
        if args.real_run:
            lab_ext = verify_extract(Path(args.labels_extract), "daily")
            wanted = {(x["market"], x["date"]) for x in ladders}
            buckets, label_info = load_labels(lab_ext, specs, wanted)
            receipt["input_sha256"] = {"labels_extract": lab_ext.summary()}
            unusable = label_info.pop("unusable")
            highs = label_info.pop("native_high")
            label_info = dict(label_info)
            n_d = len(d_ladders)
            d_keys = {(x["market"], x["date"]) for x in d_ladders}
            missing_keys = {k for k in d_keys if unusable.get(k) == "missing"}
            partial_keys = {k for k in d_keys if unusable.get(k) == "sparse"}
            d_missing, d_partial = len(missing_keys), len(partial_keys)
            numbers = {"tiling": tiling, "label_load": label_info,
                       "completeness_threshold": {"min_rows": completeness_min_rows(),
                                                  "source": COMPLETENESS_SOURCE},
                       "D_market_dates": n_d, "D_missing_wu": d_missing, "D_partial_wu": d_partial,
                       "D_unusable_share": (d_missing + d_partial) / n_d if n_d else None,
                       "D_unusable_cap_pct": LABEL_UNUSABLE_MAX_PCT,
                       "D_missing_dates_by_market_fold": by_market_fold(missing_keys),
                       "D_partial_counts_by_market_fold": {
                           m: {f: len(v) for f, v in folds.items()}
                           for m, folds in by_market_fold(partial_keys).items()}}
            # tiling and the combined cap are checked before any winner, floor or diagnostic is computed
            if tiling["tile"] != tiling["ladders"] or not within_unusable_cap(d_missing + d_partial, n_d):
                raise l21.Untestable("2_label_integrity", numbers)
            labels, win_counts = winners(ladders, buckets)
            labelled = [x for x in d_ladders if (x["market"], x["date"]) in buckets]
            one = sum(1 for x in labelled if (x["market"], x["date"]) in labels)
            numbers.update({"winner_counts_all_segments": win_counts,
                            "D_exactly_one_share": one / len(labelled) if labelled else None})
            if not labelled or one / len(labelled) < LABEL_EXACTLY_ONE_MIN:
                raise l21.Untestable("2_label_integrity", numbers)
            numbers["containment_diagnostic"] = containment_diagnostic(ladders, labels, highs)
            if args.hourly_extract:
                hr_ext = verify_extract(Path(args.hourly_extract), "hourly")
                floors = load_floors(hr_ext, specs, wanted)
                receipt["input_sha256"]["hourly_extract"] = hr_ext.summary()
            n_scored = sum(1 for x in d_ladders if (x["market"], x["date"]) in labels)
            # the 1% denominator also holds D ladders dropped at load (unparseable bands, missing token)
            n_d_all = n_d + d_unparseable + d_token_missing
            numbers.update({"D_market_dates_incl_dropped_at_load": n_d_all,
                            "D_dropped_at_load": {"band_unparseable": d_unparseable,
                                                  "token_missing": d_token_missing},
                            "D_scored_market_dates": n_scored,
                            "D_excluded_share": (n_d_all - n_scored) / n_d_all})
            if restate_needed(n_d_all - n_scored, n_d_all):
                numbers["power_restated"] = {
                    "N": n_scored, "N_basis": "label-based (ruling 3 literal): D market-dates with a winner",
                    "rule_N": RULE_T2_N, "rule_MDE80": RULE_T2_MDE80,
                    "MDE80_T2": RULE_T2_MDE80 * float(np.sqrt(RULE_T2_N / n_scored)) if n_scored else None,
                    "note": "T2 SE scaled by sqrt(1419 / N); the gate stays the realised SE (step 5)"}
            receipt["steps"]["2_label_integrity"] = {"status": "PASS", **numbers}
            keep = set(labels)
            ladders = [x for x in ladders if (x["market"], x["date"]) in keep]
        else:
            receipt["steps"]["2_label_integrity"] = {"status": "NOT RUN (synthetic-only: needs labels)",
                                                     "tiling_outcome_free": tiling}
        stage = "build_population"
        rows, info = build_rows(ladders, "D", "after", DECIDING_HOURS, labels, floors)
        receipt["population"] = info
        pop = l21.Pop(rows)
        schemes = l21.date_weights(pop.D)
        receipt["population"]["months"] = month_starts(pop)[1]
        if args.real_run:                  # the scored N after build_rows exclusions, beside the label-based N
            receipt["steps"]["2_label_integrity"]["N_final_scored_market_dates"] = info["market_dates"]
        stage = "3_synthetic_controls"
        synth, (y_null, null_res, null_ins) = step_synthetic_lomo(pop, schemes)
        receipt["steps"]["3_synthetic_controls"] = synth
        if args.real_run:
            y = y_for(pop, rows)
            stage = "4_training_score_check"
            step4 = l21.step_training(l21.in_sample(pop, y), "real")            # held locally (F1)
            receipt["steps"]["4_training_score_check"] = {"status": "PASS (numbers withheld until step 5 passes)"}
            stage = "5_realised_power"
            res = deciding_lomo(pop, y, schemes)
            step5 = l21.step_power(res, "real")
            receipt["steps"]["4_training_score_check"] = {"status": "PASS", **step4}
            receipt["steps"]["5_realised_power"] = step5
            stage = "verdict_and_descriptives"
            extra = {}
            for name, seg, side, hours in (("descriptive_13h", "D", "after", DESCRIPTIVE_HOURS),
                                           ("before_side_sensitivity", "D", "before", DECIDING_HOURS),
                                           ("nyc_2025_descriptive_never_pooled", "NYC25", "after", DECIDING_HOURS)):
                r2, i2 = build_rows(ladders, seg, side, hours, labels, floors)
                receipt.setdefault("descriptive_populations", {})[name] = i2
                if len(r2) and r2["date"].nunique() > l21.BLOCK_LEN:
                    p2 = l21.Pop(r2)
                    extra[name] = (p2, y_for(p2, r2))
            receipt.update({"deciding": l21.public(res), "verdict": verdict_3a(res, floor_unadjusted),
                            "descriptive": descriptives(pop, y, schemes, res, extra)})
        else:
            receipt["steps"]["4_training_score_check"] = l21.step_training(null_ins, "synthetic null (dry run)")
            receipt["steps"]["5_realised_power"] = l21.step_power(null_res, "synthetic null projection (dry run)")
            receipt["verdict"] = {"verdict": "NONE (synthetic-only dry run; no real Delta exists)"}
    except l21.Untestable as exc:
        step = L21_STEP_NAMES.get(exc.step, exc.step)
        receipt["steps"][step] = {"status": "FAILED", **exc.numbers,
                                  **({"l21_step_name": exc.step} if step != exc.step else {})}
        receipt["verdict"] = {"verdict": f"B12-HIST: UNTESTABLE (failed at {step})"}
    except KeyboardInterrupt:
        raise
    except BaseException as exc:                                               # F2: everything else is mechanical
        for key in ("deciding", "descriptive"):
            receipt.pop(key, None)
        if args.real_run and stage in ("5_realised_power", "verdict_and_descriptives"):
            receipt["steps"]["4_training_score_check"] = {"status": "PASS (numbers withheld: no Delta emitted)"}
            receipt["steps"].pop("5_realised_power", None)
        receipt["verdict"] = {"verdict": f"B12-HIST: MECHANICAL FAILURE at {stage}, no Delta emitted"}
        receipt["exception"] = l21.sanitise(exc)
        rc = 3
    receipt["seconds"] = round(time.perf_counter() - t0, 2)
    receipt["peak_working_set_mb"] = l21.peak_mb()
    text = json.dumps(receipt, indent=1, sort_keys=True, default=float)
    with open(out_path, "x", encoding="utf-8") as h:
        h.write(text)
    print(json.dumps({"verdict": receipt["verdict"], "steps": receipt["steps"],
                      "population": receipt.get("population"), "seconds": receipt["seconds"],
                      "peak_working_set_mb": receipt["peak_working_set_mb"],
                      "receipt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
                     indent=1, sort_keys=True, default=float))
    return rc


if __name__ == "__main__":
    sys.exit(main())
