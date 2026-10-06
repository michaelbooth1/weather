"""Shared development scoring harness for the model-parity swarm v2 (agent F1, 2026-10-04).

Every number this module produces is DEVELOPMENT evidence on the 111h extract (targets
2026-08-01..2026-09-29). Hunters import it; they never re-implement scoring.

Contract (DESIGN section 1 rules 1-6, asserted in code):
- Rule 5: the cache refuses target dates after 2026-09-29; the count of such rows is reported
  (must be 0) and ``score`` re-asserts it.
- Rules 2/3: hunters read only ``candidate_inputs()`` (explicit column allow-list; no market prices,
  books, winner or settlement) and hand back a frame ``row_key, band_index, p`` (row_key = "market|snapshot_id"). ``score`` refuses
  any other column. ``from_rowwise`` passes guarded dicts that raise on forbidden keys.
- Rule 4: ``score`` applies 81a's floor mask (max of captured guidance_physical_floor, high_so_far,
  trusted_current_max; bands with ``kind != gte and high < floor(floor + 0.5)`` set to 0) and
  renormalises. A candidate on a row with no captured floor falls back to served, as in 81a.
  ``unfloored=True`` is a labelled diagnostic and never classified LEAD.
- Rule 6: the primary estimand is all rows, with an explicit served fallback for rows the candidate
  does not cover; matched-row tables are secondary and labelled "selected on availability".
- Rule 1 (point in time) concerns external inputs; ``assert_point_in_time`` is the join guard.

Statistics: per-snapshot Brier is the mean over bands of (p - y)^2 (81a). Snapshots are averaged
within a market-day, market-days weigh equally. Intervals come from ONE crossed date x market
bootstrap weight matrix W (2000 draws x 626 market-days, 81a's ``crossed_weights``, seed 20260921),
cached at C:\\swarm\\cache\\W.npy: every interval is a ratio of ``W[:, cells] @ values``.
MDE80/power reuse 81a's ``inference`` (effect -0.0075).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.missing_information.methods import Band, crossed_weights, validate_bands
from tools.research.morning_guidance.statistics import DRAWS, SEED, inference, summarize

EXTRACT = Path(r"C:\Users\Michael\Documents\nbm-guidance-111h")
CACHE = Path(r"C:\swarm\cache")
INPUTS = ("guidance_rows.jsonl.gz", "market_days.jsonl.gz", "manifest.json")
PARSER_HEAD = "2e17ce0eb"
LAST_TARGET_DATE = "2026-09-29"
CACHE_VERSION = 1

BLOCKS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23))
AGGREGATES = (("00-16", 0, 16), ("all", 0, 23))
GROUPS = BLOCKS + AGGREGATES
STRATA = ("before_20260823", "from_20260823", "pooled")
POPULATIONS = ("all_row", "matched")
MATCHED_LABEL = "selected on availability"

LEAD_LINE = -0.0133          # twice-81a line as written in DESIGN section 1 (EF 10j)
LEAD_GAP_SHARE = 0.05        # EF 1d bar: estimate <= -5% of the block's served-market gap
LEAD_MIN_MARKETS = 8         # >= 8 of 11 markets with the same (negative) sign, from stratum
RATIO_MARKET_FLOOR = 0.005   # ratio to market not interpretable below this market Brier
TAIL_GAP = 0.30              # EF 1/1f severity tail: served SE > market SE and |p - market| >= 0.30
MDE_EFFECT = -0.0075
LEAKAGE_SUSPECT_RATIO = 0.5  # candidate Brier below half the market's in a block is suspicious

LABEL_COLUMNS = frozenset({"winner", "settlement_high", "settlement_bucket", "settlement_source",
                           "is_winner"})
MARKET_COLUMNS = frozenset({"p_market_yes", "best_bid", "best_ask", "market_mid"})
FORBIDDEN = LABEL_COLUMNS | MARKET_COLUMNS

TOP_ALLOWED = (
    "snapshot_id", "market", "station", "event_slug", "target_date", "stratum", "captured_at_utc",
    "captured_at_local", "local_hour", "unit", "model_version", "features_present",
    "v1_cycle_key", "v1_status", "v1_parser_version", "v1_issued_at", "v1_valid_time_utc", "v1_period",
    "v2_candidates", "v2_newest_cycle_key", "v2_newest_reason", "v2_status", "v2_reason",
    "v2_cycle_key", "v2_payload_hash", "v2_issued_at", "v2_valid_time_utc", "v2_available_at",
    "v2_available_basis", "v2_age_hours", "v2_forecast_hour", "v2_period_kind",
    "v2_p10", "v2_p25", "v2_p50", "v2_p75", "v2_p90", "v2_mean", "v2_stddev",
    "hrrr_high", "hrrr_issued_at", "hrrr_issue_status", "hrrr_fetched_at", "hrrr_status",
    "nws_grid_high_raw", "nws_grid_issued_at", "nws_grid_updated_at", "nws_grid_fetched_at",
    "nws_grid_status")
TOP_IGNORED = ("schema", "bands", "p_served", "v2_skipped")   # bands/p_served go to the band table
FEATURE_ALLOWED = (
    "nbm_prob_tmax_p10", "nbm_prob_tmax_p25", "nbm_prob_tmax_p50", "nbm_prob_tmax_p75",
    "nbm_prob_tmax_p90", "nbm_prob_tmax_mean", "nbm_prob_tmax_stddev",
    "nbm_prob_tmax_physical_valid_flag", "nbm_prob_tmax_impossible_flag", "nbm_prob_tmax_floor_gap",
    "guidance_physical_floor", "high_so_far", "trusted_current_max", "nws_grid_high",
    "open_meteo_hrrr_high_delta", "forecast_high", "guidance_impossible_features",
    "guidance_impossible_sources", "cutoff_hour")
FLOOR_FIELDS = ("guidance_physical_floor", "high_so_far", "trusted_current_max")
DERIVED_ALLOWED = ("row_key", "date", "block", "n_bands", "floor", "floor_bucket")
SNAPSHOT_ALLOWED = TOP_ALLOWED + FEATURE_ALLOWED + DERIVED_ALLOWED
BAND_ALLOWED = ("row_key", "band_index", "kind", "low", "high", "p_served", "floor_impossible")
BAND_CONTEXT = ("market", "date", "stratum", "local_hour", "block", "floor", "high_so_far",
                "guidance_physical_floor", "nws_grid_high", "hrrr_high", "forecast_high",
                "v2_p10", "v2_p50", "v2_p90")
CANDIDATE_COLUMNS = ("row_key", "band_index", "p")


class LeakageError(AssertionError):
    """A forbidden (market or settlement) value was requested by candidate code."""


class GuardedDict(dict):
    """Dict that refuses forbidden keys, for row-wise candidate functions."""

    def __getitem__(self, key):
        if key in FORBIDDEN:
            raise LeakageError(f"forbidden candidate input: {key}")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in FORBIDDEN:
            raise LeakageError(f"forbidden candidate input: {key}")
        return super().get(key, default)


# ----------------------------------------------------------------------------- identity

def harness_sha256():
    """HARNESS_SHA256: sha256 over harness.py then __init__.py bytes of this package."""
    here = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ("harness.py", "__init__.py"):
        digest.update((here / name).read_bytes())
    return digest.hexdigest()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dependency_sha256():
    root = Path(__file__).resolve().parents[1]
    return {name: _sha256(root / name) for name in (
        "missing_information/methods.py", "morning_guidance/statistics.py",
        "morning_guidance/candidate.py", "missing_information/extract.py")}


def _finite(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def block_of(hour):
    return next(name for name, low, high in BLOCKS if low <= hour <= high)


def floor_value(features):
    floors = [v for v in (_finite(features.get(k)) for k in FLOOR_FIELDS) if v is not None]
    return max(floors) if floors else None


def floor_impossible(bands, floor):
    """81a mask: a non-gte band whose high is below the floor's canonical bucket is impossible."""
    if floor is None:
        return [False] * len(bands)
    bucket = math.floor(float(floor) + .5)
    return [b["kind"] != "gte" and b["high"] < bucket for b in bands]


# ----------------------------------------------------------------------------- loading

def verify_extract(root=EXTRACT):
    """Every file matches SHA256SUMS; manifest COMPLETE at the pinned parser head."""
    root = Path(root)
    sums = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.strip().lstrip("*")] = digest
    if set(sums) != set(INPUTS):
        raise ValueError(f"SHA256SUMS names {sorted(sums)}")
    actual = {name: _sha256(root / name) for name in INPUTS}
    if actual != sums:
        raise ValueError("input bytes do not match SHA256SUMS")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "COMPLETE" or not manifest["parser"]["head"].startswith(PARSER_HEAD):
        raise ValueError("extract is not COMPLETE at the pinned parser head")
    return {"input_path": str(root), "sha256": actual, "status": manifest["status"],
            "parser_head": manifest["parser"]["head"], "manifest_rows": manifest["row_counts"]["rows"],
            "manifest_market_days_admitted": manifest["row_counts"]["market_days_admitted"]}


def _parse_rows(path):
    snaps, bands, after = [], [], Counter()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["target_date"] > LAST_TARGET_DATE:
                after[row["target_date"]] += 1          # rule 5: counted, never cached
                continue
            unknown = set(row) - set(TOP_ALLOWED) - set(TOP_IGNORED) - FORBIDDEN - {"features"}
            if unknown:
                raise ValueError(f"unclassified extract fields {sorted(unknown)}")
            if row["unit"] != "F":
                raise ValueError("111h population is US Fahrenheit markets only")
            features = row.get("features") or {}
            unknown = set(features) - set(FEATURE_ALLOWED)
            if unknown:
                raise ValueError(f"unclassified feature fields {sorted(unknown)}")
            b = [{k: x[k] for k in ("kind", "low", "high")} for x in row["bands"]]
            validate_bands([Band(**x) for x in b])
            n = len(b)
            for key in ("p_served", "p_market_yes", "best_bid", "best_ask", "market_mid"):
                if len(row[key]) != n:
                    raise ValueError(f"{key} length mismatch in {row['snapshot_id']}")
            floor = floor_value(features)
            snap = {k: row.get(k) for k in TOP_ALLOWED}
            snap.update({k: features.get(k) for k in FEATURE_ALLOWED})
            row_key = f"{row['market']}|{row['snapshot_id']}"
            snap.update(row_key=row_key, date=row["target_date"], block=block_of(row["local_hour"]), n_bands=n,
                        floor=floor, floor_bucket=None if floor is None else math.floor(floor + .5),
                        winner=row["winner"], settlement_high=row["settlement_high"],
                        settlement_bucket=row["settlement_bucket"],
                        settlement_source=row["settlement_source"])
            snaps.append(snap)
            impossible = floor_impossible(b, floor)
            for i, x in enumerate(b):
                bands.append((row_key, i, x["kind"], x["low"], x["high"],
                              row["p_served"][i], row["p_market_yes"][i], row["best_bid"][i],
                              row["best_ask"][i], row["market_mid"][i], int(i == row["winner"]),
                              bool(impossible[i])))
    snaps = pd.DataFrame(snaps)
    for k in ("cutoff_hour", "guidance_impossible_features", "guidance_impossible_sources"):
        snaps[k] = snaps[k].astype("string")
    for k in ("trusted_current_max", "v1_parser_version", "hrrr_issued_at", "nws_grid_issued_at"):
        snaps[k] = snaps[k].astype("float64" if k == "trusted_current_max" else "string")
    bands = pd.DataFrame(bands, columns=["row_key", "band_index", "kind", "low", "high", "p_served",
                                         "p_market_yes", "best_bid", "best_ask", "market_mid",
                                         "is_winner", "floor_impossible"])
    return snaps, bands, after


def build_cache(root=EXTRACT, cache=CACHE, force=False):
    """Hash-verify the extract, parse it once and cache parquet + W under C:\\swarm\\cache."""
    cache = Path(cache)
    receipt_path = cache / "cache_receipt.json"
    verified = verify_extract(root)
    if receipt_path.exists() and not force:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("input", {}).get("sha256") == verified["sha256"] and \
                receipt.get("cache_version") == CACHE_VERSION:
            return receipt
    cache.mkdir(parents=True, exist_ok=True)
    snaps, bands, after = _parse_rows(Path(root) / "guidance_rows.jsonl.gz")
    context = snaps[["row_key", *BAND_CONTEXT]]
    bands = bands.merge(context, on="row_key", how="left", validate="many_to_one")
    with gzip.open(Path(root) / "market_days.jsonl.gz", "rt", encoding="utf-8") as stream:
        days = [json.loads(line) for line in stream]
    admitted = {(d["target_date"], d["market"]) for d in days if d.get("admitted")}
    keys = sorted(set(zip(snaps.date, snaps.market)))
    if set(keys) != admitted:
        raise ValueError("cached market-days differ from admitted market_days.jsonl.gz")
    w = crossed_weights([k[0] for k in keys], [k[1] for k in keys], draws=DRAWS, seed=SEED)
    snaps.to_parquet(cache / "snapshots.parquet", index=False)
    bands.to_parquet(cache / "bands.parquet", index=False)
    np.save(cache / "W.npy", w.astype(np.float64))
    (cache / "W_keys.json").write_text(json.dumps(keys), encoding="utf-8")
    receipt = {"cache_version": CACHE_VERSION, "built_local": datetime.now().isoformat(timespec="seconds"),
               "input": verified, "harness_sha256_at_build": harness_sha256(),
               "rows_cached": len(snaps), "band_rows_cached": len(bands),
               "rows_with_target_after_2026_09_29": sum(after.values()),
               "after_by_date": dict(after), "market_days": len(keys),
               "dates": int(snaps.date.nunique()), "markets": int(snaps.market.nunique()),
               "target_date_range": [snaps.date.min(), snaps.date.max()],
               "W": {"shape": list(w.shape), "draws": DRAWS, "seed": SEED,
                     "method": "missing_information.methods.crossed_weights over sorted (date, market)",
                     "sha256": _sha256(cache / "W.npy")},
               "files": {p: _sha256(cache / p) for p in
                         ("snapshots.parquet", "bands.parquet", "W.npy", "W_keys.json")}}
    receipt_path.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    return receipt


class _Data:
    def __init__(self, cache):
        cache = Path(cache)
        self.receipt = json.loads((cache / "cache_receipt.json").read_text(encoding="utf-8"))
        if self.receipt["rows_with_target_after_2026_09_29"] != 0:
            raise AssertionError("rule 5: rows after 2026-09-29 present in the extract")
        self.snaps = pd.read_parquet(cache / "snapshots.parquet")
        self.bands = pd.read_parquet(cache / "bands.parquet")
        if self.snaps.date.max() > LAST_TARGET_DATE or self.bands.date.max() > LAST_TARGET_DATE:
            raise AssertionError("rule 5: a cached target date is after 2026-09-29")
        self.w = np.load(cache / "W.npy")
        self.keys = [tuple(k) for k in json.loads((cache / "W_keys.json").read_text(encoding="utf-8"))]
        self.key_index = {k: i for i, k in enumerate(self.keys)}
        # bands are stored contiguously per snapshot in snapshot order
        n = self.snaps.n_bands.to_numpy()
        self.offsets = np.concatenate([[0], np.cumsum(n)[:-1]])
        if not (self.bands.row_key.to_numpy()[self.offsets] == self.snaps.row_key.to_numpy()).all():
            raise AssertionError("band table is not contiguous per snapshot")
        self.band_snap = np.repeat(np.arange(len(self.snaps)), n)
        self.snap_pos = pd.Series(np.arange(len(self.snaps)), index=self.snaps.row_key)
        b = self.bands
        y = b.is_winner.to_numpy(float)
        self.y = y
        self.p_served = b.p_served.to_numpy(float)
        self.p_market = b.p_market_yes.to_numpy(float)
        self.se_served = (self.p_served - y) ** 2
        self.se_market = (self.p_market - y) ** 2
        self.tail = (self.se_served > self.se_market) & (np.abs(self.p_served - self.p_market) >= TAIL_GAP)
        self.impossible = b.floor_impossible.to_numpy(bool)
        self.has_floor = self.snaps.floor.notna().to_numpy()


_DATA = {}


def data(cache=CACHE):
    """Full cache (labels and market included). Scoring internals only; hunters never call this."""
    key = str(Path(cache))
    if key not in _DATA:
        if not (Path(cache) / "cache_receipt.json").exists():
            build_cache(cache=cache)
        _DATA[key] = _Data(cache)
    return _DATA[key]


def candidate_inputs(cache=CACHE):
    """The ONLY tables candidate code may read: allow-listed columns, no market and no labels."""
    d = data(cache)
    snaps = d.snaps[list(SNAPSHOT_ALLOWED)].copy()
    bands = d.bands[list(BAND_ALLOWED)].copy()
    for frame in (snaps, bands):
        if FORBIDDEN & set(frame.columns):
            raise LeakageError("allow-list leaked a forbidden column")
    return snaps, bands


def served_candidate(cache=CACHE):
    """Template candidate: served probabilities as a candidate frame (scores to delta 0)."""
    _, bands = candidate_inputs(cache)
    return bands[["row_key", "band_index"]].assign(p=bands.p_served.to_numpy())


def from_rowwise(fn, where=None, cache=CACHE):
    """Build a candidate frame from fn(snap, bands, p_served) -> probabilities or None (fallback).

    ``snap`` is a GuardedDict of allow-listed columns plus ``snap["features"]`` (captured feature
    dict), ``bands`` a list of {kind, low, high}, ``p_served`` a numpy array. ``where`` optionally
    selects snapshots: a boolean mask function over the allow-listed snapshot frame.
    """
    snaps, bands = candidate_inputs(cache)
    d = data(cache)
    mask = np.ones(len(snaps), bool) if where is None else np.asarray(where(snaps), bool)
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p_all = bands.p_served.to_numpy(float)
    records = snaps.to_dict(orient="records")
    out_sid, out_idx, out_p = [], [], []
    for pos in np.flatnonzero(mask):
        rec = records[pos]
        start, n = d.offsets[pos], rec["n_bands"]
        snap = GuardedDict({k: (None if (isinstance(v, float) and math.isnan(v)) or v is pd.NA else v)
                            for k, v in rec.items()})
        snap["features"] = GuardedDict({k: snap[k] for k in FEATURE_ALLOWED})
        blist = [{"kind": kinds[start + i], "low": int(lows[start + i]), "high": int(highs[start + i])}
                 for i in range(n)]
        p = fn(snap, blist, p_all[start:start + n].copy())
        if p is None:
            continue
        p = np.asarray(p, float)
        if p.shape != (n,):
            raise ValueError(f"candidate for {rec['row_key']} has shape {p.shape}, expected ({n},)")
        out_sid.extend([rec["row_key"]] * n)
        out_idx.extend(range(n))
        out_p.extend(p.tolist())
    return pd.DataFrame({"row_key": out_sid, "band_index": out_idx, "p": out_p})


def assert_point_in_time(available_at_utc, captured_at_utc):
    """Rule 1 join guard: every external value must be available at or before the snapshot."""
    a = pd.to_datetime(pd.Series(available_at_utc), utc=True)
    c = pd.to_datetime(pd.Series(captured_at_utc), utc=True)
    if a.isna().any():
        raise AssertionError("rule 1: value without availability evidence (exclude it instead)")
    late = (a.to_numpy() > c.to_numpy())
    if late.any():
        raise AssertionError(f"rule 1: {int(late.sum())} values available after their snapshot")
    return True


# ----------------------------------------------------------------------------- statistics

def _ratio_boot(w, idx, a, b):
    sub = w[:, idx]
    num, den = sub @ a, sub @ b
    return np.divide(num, den, out=np.full(len(num), np.nan), where=den > 0)


def interval(idx, a, b=None, effect=None, cache=CACHE):
    """Ratio-of-sums estimate over market-day cells with a W-based 95% interval.

    ``idx`` are W column positions of the cells, ``a`` per-cell numerators, ``b`` per-cell
    denominators (default 1, i.e. equal market-days). With ``effect``, power and MDE80 from
    81a's ``inference`` are included.
    """
    w = data(cache).w
    a = np.asarray(a, float)
    b = np.ones(len(a)) if b is None else np.asarray(b, float)
    point = float(a.sum() / b.sum()) if b.sum() > 0 else float("nan")
    boot = _ratio_boot(w, np.asarray(idx), a, b)
    if effect is not None:
        out = inference(point, boot, effect)
        out["ci95"] = [float(x) for x in out["ci95"]]
        return out
    finite = boot[np.isfinite(boot)]
    return {"estimate": point, "ci95": np.quantile(finite, [.025, .975]).tolist() if len(finite) else
            [float("nan")] * 2, "valid_draws": int(len(finite))}


def mde80(idx, a, effect=MDE_EFFECT, cache=CACHE):
    """MDE80 (81a definition) for an equal-market-day mean of per-cell values ``a``."""
    return interval(idx, a, effect=effect, cache=cache)["mde80"]


# ----------------------------------------------------------------------------- scoring

def _candidate_vector(candidate, d, unfloored):
    if not isinstance(candidate, pd.DataFrame):
        raise TypeError("candidate must be a DataFrame with columns row_key, band_index, p")
    cols = set(candidate.columns)
    if FORBIDDEN & cols:
        raise LeakageError(f"candidate frame carries forbidden columns {sorted(FORBIDDEN & cols)}")
    if cols != set(CANDIDATE_COLUMNS):
        raise ValueError(f"candidate columns must be exactly {CANDIDATE_COLUMNS}, got {sorted(cols)}")
    if candidate.duplicated(["row_key", "band_index"]).any():
        raise ValueError("duplicate (row_key, band_index) in candidate")
    pos = d.snap_pos.reindex(candidate.row_key.to_numpy()).to_numpy()
    if np.isnan(pos).any():
        raise ValueError("candidate names snapshots that are not in the cache")
    pos = pos.astype(int)
    bi = candidate.band_index.to_numpy(int)
    nb = d.snaps.n_bands.to_numpy()[pos]
    if ((bi < 0) | (bi >= nb)).any():
        raise ValueError("band_index out of range")
    pc = np.full(len(d.bands), np.nan)
    pc[d.offsets[pos] + bi] = candidate.p.to_numpy(float)
    given = ~np.isnan(pc)
    n_given = np.bincount(d.band_snap, weights=given, minlength=len(d.snaps))
    n_bands = d.snaps.n_bands.to_numpy()
    partial = (n_given > 0) & (n_given < n_bands)
    if partial.any():
        raise ValueError(f"{int(partial.sum())} snapshots have probabilities for only some bands")
    provided = n_given == n_bands
    if (pc[given] < 0).any() or not np.isfinite(pc[given]).all():
        raise ValueError("candidate probabilities must be finite and >= 0")
    reason = np.where(provided, "candidate", "absent").astype(object)
    if not unfloored:
        no_floor = provided & ~d.has_floor
        reason[no_floor] = "missing_floor"
        pc[d.impossible & given] = 0.0
    else:
        no_floor = np.zeros(len(d.snaps), bool)
    total = np.bincount(d.band_snap, weights=np.where(given, pc, 0.0), minlength=len(d.snaps))
    zero = provided & ~no_floor & ~(total > 0)
    reason[zero] = "zero_mass_after_floor"
    use = provided & ~no_floor & ~zero
    use_band = use[d.band_snap]
    # renormalise; a vector already summing to 1 within 1e-12 is kept bit-exact (identity checks)
    scale = np.where((total > 0) & (np.abs(total - 1.0) > 1e-12), total, 1.0)
    pc = np.where(use_band, pc / scale[d.band_snap], d.p_served)
    return pc, use, reason


def _snapshot_mean(d, values):
    return np.add.reduceat(values, d.offsets) / d.snaps.n_bands.to_numpy()


def _group_mask(frame, group):
    low, high = next((lo, hi) for name, lo, hi in GROUPS if name == group)
    return frame.local_hour.between(low, high).to_numpy()


def _table(frame, d, cache):
    """Statistics for one population (snapshot frame subset)."""
    cells = frame.groupby(["date", "market"], sort=True)[
        ["served", "market_loss", "cand", "fallback"]].mean().reset_index()
    if not len(cells):
        return {"snapshots": 0, "market_days": 0, "status": "NO_DATA"}
    idx = np.array([d.key_index[(a, b)] for a, b in zip(cells.date, cells.market)])
    s, m, c = (cells[k].to_numpy(float) for k in ("served", "market_loss", "cand"))
    delta = c - s
    gap = s - m
    market_est = float(m.mean())
    interpretable = market_est >= RATIO_MARKET_FLOOR
    per_market = cells.assign(delta=delta).groupby("market").delta.mean()
    out = {"snapshots": int(len(frame)), "market_days": int(len(cells)),
           "date_clusters": int(cells.date.nunique()), "market_clusters": int(cells.market.nunique()),
           "fallback_snapshot_share": float(frame.fallback.mean()),
           "served": interval(idx, s, cache=cache), "market": interval(idx, m, cache=cache),
           "candidate": interval(idx, c, cache=cache),
           "candidate_minus_served": interval(idx, delta, effect=MDE_EFFECT, cache=cache),
           "candidate_minus_market": interval(idx, c - m, cache=cache),
           "served_minus_market": interval(idx, gap, cache=cache),
           "ratio_candidate_to_market": {**interval(idx, c, m, cache=cache), "interpretable": interpretable},
           "ratio_served_to_market": {**interval(idx, s, m, cache=cache), "interpretable": interpretable},
           "gap_closed_share": interval(idx, -delta, gap, cache=cache),
           "per_market_delta": {k: float(v) for k, v in per_market.items()},
           "markets_negative": int((per_market < 0).sum()), "markets_positive": int((per_market > 0).sum()),
           "markets_zero": int((per_market == 0).sum())}
    if not interpretable:
        out["ratio_candidate_to_market"]["note"] = "market Brier < 0.005: ratio not interpretable"
        out["ratio_served_to_market"]["note"] = "market Brier < 0.005: ratio not interpretable"
    return out


def _tail(d, se_c, sel_snap, cache):
    """Candidate effect on the EF 1/1f severity-tail band rows inside the selected snapshots."""
    band_sel = sel_snap[d.band_snap] & d.tail
    if not band_sel.any():
        return {"tail_band_rows": 0, "status": "NO_DATA"}
    b = d.bands.loc[band_sel, ["date", "market"]].copy()
    b["excess"] = (d.se_served - d.se_market)[band_sel]
    b["improve"] = (d.se_served - se_c)[band_sel]
    b["delta"] = (se_c - d.se_served)[band_sel]
    b["one"] = 1.0
    cells = b.groupby(["date", "market"], sort=True)[["excess", "improve", "delta", "one"]].sum().reset_index()
    idx = np.array([d.key_index[(x, y)] for x, y in zip(cells.date, cells.market)])
    return {"tail_band_rows": int(band_sel.sum()), "market_days": int(len(cells)),
            "share_of_tail_excess_removed": interval(idx, cells.improve, cells.excess, cache=cache),
            "mean_delta_per_tail_band_row": interval(idx, cells.delta, cells.one, cache=cache)}


def classify(tables, group):
    """DESIGN section 1 LEAD rule on all-row tables for one block/aggregate."""
    get = lambda s: tables[(group, s, "all_row")]
    t_from, t_before = get("from_20260823"), get("before_20260823")
    if t_from.get("status") == "NO_DATA" or t_before.get("status") == "NO_DATA":
        return {"class": "NO_DATA"}
    d = t_from["candidate_minus_served"]
    est, (lo, hi) = d["estimate"], d["ci95"]
    gap = t_from["served_minus_market"]["estimate"]
    before_est = t_before["candidate_minus_served"]["estimate"]
    conds = {"interval_excludes_0": bool(hi < 0),
             "size": bool(est <= LEAD_LINE or est <= -LEAD_GAP_SHARE * gap),
             "size_detail": {"estimate": est, "twice_81a_line": LEAD_LINE,
                             "minus_5pct_gap": -LEAD_GAP_SHARE * gap, "from_gap": gap},
             "both_strata_same_sign": bool(est < 0 and before_est < 0),
             "strata_estimates": {"before_20260823": before_est, "from_20260823": est},
             "markets_same_sign": bool(t_from["markets_negative"] >= LEAD_MIN_MARKETS),
             "markets_negative_from": t_from["markets_negative"],
             "market_clusters_from": t_from["market_clusters"]}
    lead = all(conds[k] for k in ("interval_excludes_0", "size", "both_strata_same_sign",
                                  "markets_same_sign"))
    if lead:
        cls = "LEAD"
    elif est < 0:
        cls = "WEAK"
    elif lo > 0:
        cls = "HARM"
    else:
        cls = "NULL"
    return {"class": cls, "conditions": conds}


def score(candidate, name="candidate", unfloored=False, where=None, cache=CACHE):
    """Score a candidate frame (row_key, band_index, p) against served and the market.

    ``where`` optionally restricts the SCORED population (mask function over the allow-listed
    snapshot frame, e.g. ``lambda s: s.date <= "2026-09-19"``); default all cached rows.
    Returns a JSON-serialisable dict: tables per group x stratum x population, LEAD/WEAK classes,
    tail rows, fallback counts, sanity flags, HARNESS_SHA256.
    """
    d = data(cache)
    if d.snaps.date.max() > LAST_TARGET_DATE:
        raise AssertionError("rule 5")
    pc, use, reason = _candidate_vector(candidate, d, unfloored)
    se_c = (pc - d.y) ** 2
    frame = d.snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    frame["served"] = _snapshot_mean(d, d.se_served)
    frame["market_loss"] = _snapshot_mean(d, d.se_market)
    frame["cand"] = _snapshot_mean(d, se_c)
    frame["fallback"] = (~use).astype(float)
    scope = np.ones(len(frame), bool) if where is None else np.asarray(
        where(d.snaps[list(SNAPSHOT_ALLOWED)]), bool)
    tables, tails = {}, {}
    for group, _, _ in GROUPS:
        gmask = _group_mask(frame, group) & scope
        for stratum in STRATA:
            smask = gmask if stratum == "pooled" else gmask & (frame.stratum == stratum).to_numpy()
            for population in POPULATIONS:
                pmask = smask if population == "all_row" else smask & use
                t = _table(frame[pmask], d, cache)
                t.update(group=group, stratum=stratum, population=population,
                         label="primary (served fallback)" if population == "all_row" else MATCHED_LABEL)
                tables[(group, stratum, population)] = t
            tails[(group, stratum)] = _tail(d, se_c, smask, cache)
    classes = {g: classify(tables, g) for g, _, _ in GROUPS}
    if unfloored:
        for g in classes:
            classes[g] = {"class": "DIAGNOSTIC_UNFLOORED", "would_be": classes[g]["class"]}
    suspects = [g for g, _, _ in GROUPS
                if tables[(g, "pooled", "all_row")].get("status") != "NO_DATA"
                and tables[(g, "pooled", "all_row")]["candidate"]["estimate"]
                < LEAKAGE_SUSPECT_RATIO * tables[(g, "pooled", "all_row")]["market"]["estimate"]]
    in_scope = scope
    return {"name": name, "HARNESS_SHA256": harness_sha256(), "development": True,
            "unfloored_diagnostic": bool(unfloored), "floor_applied": not unfloored,
            "scored_snapshots": int(in_scope.sum()),
            "rows_with_target_after_2026_09_29": d.receipt["rows_with_target_after_2026_09_29"],
            "max_target_date": str(d.snaps.date[in_scope].max()),
            "reason_counts": dict(Counter(reason[in_scope])),
            "candidate_share": float(use[in_scope].mean()),
            "classes": classes,
            "leakage_suspect_groups": suspects,
            "tables": [tables[k] for k in tables],
            "tail": [{"group": g, "stratum": s, **v} for (g, s), v in tails.items()],
            "input_sha256": d.receipt["input"]["sha256"]}


def table_lookup(result, group, stratum="pooled", population="all_row"):
    return next(t for t in result["tables"] if (t["group"], t["stratum"], t["population"]) ==
                (group, stratum, population))


def markdown(result):
    """Compact markdown summary (all-row primary, matched secondary) for reports."""
    f = lambda x: "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.6f}"
    ci = lambda d: f"{f(d['estimate'])} [{f(d['ci95'][0])}, {f(d['ci95'][1])}]"
    lines = [f"Candidate `{result['name']}` (development) HARNESS_SHA256 `{result['HARNESS_SHA256']}`",
             f"floor applied: {result['floor_applied']}; candidate share {result['candidate_share']:.4f}; "
             f"reasons {result['reason_counts']}; rows after 2026-09-29: "
             f"{result['rows_with_target_after_2026_09_29']}", "",
             "| group | stratum | pop | N md | cand-served [95%] | MDE80 | cand-market [95%] | "
             "ratio to market | gap closed | mkts -/+ |", "|" + "---|" * 10]
    for t in result["tables"]:
        if t.get("status") == "NO_DATA":
            continue
        r = t["ratio_candidate_to_market"]
        ratio = f"{r['estimate']:.3f}" + ("" if r["interpretable"] else " (n.i.)")
        lines.append(f"| {t['group']} | {t['stratum'][:6]} | {t['population']} | {t['market_days']} | "
                     f"{ci(t['candidate_minus_served'])} | {t['candidate_minus_served'].get('mde80') or 0:.6f} | "
                     f"{ci(t['candidate_minus_market'])} | {ratio} | "
                     f"{t['gap_closed_share']['estimate']:+.3f} | "
                     f"{t['markets_negative']}/{t['markets_positive']} |")
    lines += ["", "| group | class | interval<0 | size | strata | markets |", "|---|---|---|---|---|---|"]
    for g, c in result["classes"].items():
        k = c.get("conditions") or {}
        lines.append(f"| {g} | {c['class']} | {k.get('interval_excludes_0', '')} | {k.get('size', '')} | "
                     f"{k.get('both_strata_same_sign', '')} | {k.get('markets_negative_from', '')} |")
    return "\n".join(lines)


def save(result, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result['name']}.score.json"
    path.write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- table facts

def table_facts(cache=CACHE):
    """Served/market ratio, block excess shares and the EF 1/1f tail definition on this table."""
    d = data(cache)
    frame = d.snaps[["date", "market", "stratum", "local_hour", "block"]].copy()
    frame["served"] = _snapshot_mean(d, d.se_served)
    frame["market_loss"] = _snapshot_mean(d, d.se_market)
    frame["excess"] = frame.served - frame.market_loss
    cells = frame.groupby(["date", "market"])[["served", "market_loss"]].mean().reset_index()
    idx = np.array([d.key_index[(a, b)] for a, b in zip(cells.date, cells.market)])
    ratio = interval(idx, cells.served, cells.market_loss, cache=cache)
    snap_sum = frame.groupby("block").excess.sum()
    md_block = frame.groupby(["block", "date", "market"]).excess.mean().groupby("block").sum()
    excess_shares = {"snapshot_weighted": (snap_sum / snap_sum.sum()).to_dict(),
                     "market_day_block_cell_weighted": (md_block / md_block.sum()).to_dict()}
    pos = np.clip(d.se_served - d.se_market, 0, None)
    wt = 1.0 / d.bands.groupby(["date", "market"]).row_key.transform("size").to_numpy()
    tail = {"definition": "band row with served SE > market SE and |p_served - p_market| >= 0.30; "
                          "share of positive excess = sum over tail rows of (SE_served - SE_market) / "
                          "sum over all band rows of max(0, SE_served - SE_market)",
            "band_rows": int(len(d.bands)), "tail_band_rows": int(d.tail.sum()),
            "tail_band_row_share": float(d.tail.mean()),
            "tail_share_of_positive_excess": float(pos[d.tail].sum() / pos.sum()),
            "equal_market_day_tail_band_row_share": float((wt * d.tail).sum() / wt.sum()),
            "equal_market_day_tail_share_of_positive_excess": float((wt * pos)[d.tail].sum() / (wt * pos).sum())}
    return {"served_brier": float(cells.served.mean()), "market_brier": float(cells.market_loss.mean()),
            "served_to_market_ratio": ratio, "block_excess_shares": excess_shares, "tail": tail}


def positive_control(cache=CACHE):
    """111h section 9 control: 81a's C1 on captured v1 features, 06-09 local, targets <= 09-19.

    Reference (docs/roadmap/agent-report-2026-09-111h-guidance-all-hours.md line 199):
    pooled C1 - served = -0.006891 [-0.011894, -0.002688]. Exact reproduction uses 81a's own
    ``summarize`` on the control cells; the W-based interval is reported beside it.
    """
    from tools.research.morning_guidance.candidate import candidates

    def c1(snap, bands, p):
        out, _, reason = candidates(bands, p, snap["features"])
        return out if reason == "eligible" else None

    scope = lambda s: s.local_hour.between(6, 9) & (s.date <= "2026-09-19")
    cand = from_rowwise(c1, where=scope, cache=cache)
    result = score(cand, name="positive_control_81a_C1", where=scope, cache=cache)
    d = data(cache)
    pc, use, _ = _candidate_vector(cand, d, False)
    frame = d.snaps[["date", "market", "local_hour"]].copy()
    frame["delta"] = _snapshot_mean(d, (pc - d.y) ** 2) - _snapshot_mean(d, d.se_served)
    sel = scope(d.snaps).to_numpy()
    cells = frame[sel].groupby(["date", "market"]).delta.mean().reset_index()
    exact = summarize(cells, "delta")
    w_based = table_lookup(result, "06-09")["candidate_minus_served"]
    # identity check: served handed back unfloored must score exactly 0 everywhere
    served = score(served_candidate(cache), name="served_minus_served", unfloored=True, cache=cache)
    served_max = max(max(abs(t["candidate_minus_served"]["estimate"]),
                         *(abs(x) for x in t["candidate_minus_served"]["ci95"]))
                     for t in served["tables"] if t.get("status") != "NO_DATA")
    # floor-only rung: served with the rule-4 floor mask applied (what every candidate inherits)
    floor_only = score(served_candidate(cache), name="served_floored_floor_only", cache=cache)
    reference = {"estimate": -0.006891, "ci95": [-0.011894, -0.002688]}
    ok = (round(exact["estimate"], 6) == reference["estimate"]
          and [round(x, 6) for x in exact["ci95"]] == reference["ci95"])
    return {"reference_111h_line_199": reference, "exact_81a_summarize": exact,
            "w_based_06_09_pooled": w_based, "snapshots": int(sel.sum()),
            "market_days": int(len(cells)), "eligible_snapshots": int((use & sel).sum()),
            "served_minus_served_max_abs": served_max, "pass": bool(ok and served_max == 0.0),
            "control_result": result, "floor_only_result": floor_only}
