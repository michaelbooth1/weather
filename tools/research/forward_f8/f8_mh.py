r"""F8-MH: the Oct-Dec "midnight-high" forward screen at local hours 01-06 (ledger row 104, lane L16).

Freeze document ``docs/research/f8-mh-forward-2026-10-31/freeze.md`` (sha256 ``FREEZE_DOC_SHA256``), master's F8-MH
rulings 2026-10-31 (i)-(v). Research tool, not a production dependency. It edits no B-bound file. The B-bound modules
it imports (``mg_serve_core``, ``observed_running_max``, and through the frozen statistic ``dev_scorecard``,
``dev_scorecard_data`` and ``loss_atlas``) are imported READ-ONLY and their file sha256 is checked at import, before
the import, against B's release-binding manifest ``B_MANIFEST_PATH`` (whose own sha256 is pinned in
``B_FORWARD_TEST_DESIGN.md``); any mismatch refuses.

Mechanism (verbatim, master ruling (i)): "after a pre-dawn cooling (midnight high, >= 3°F drop by the cutoff), the
thin 01-06 book keeps mass above H for a daytime recovery that does not come". Falsifier: the market already prices
pre-dawn fronts.

Regime (master rulings (ii) and (iv); the NBM gate G was dropped before any count): t_H <= 01:59 local AND
H - C >= 3 °F, routine METAR only (SPECI excluded), every input present, B's US10 (Denver out), local hours 01-06.

Statistic: the frozen ``mr_sweep.p0_candidate`` (pin 8bb0f9563, vendored unchanged), type C toward H, on the regime
table after a frozen >= 2-regime-date (market, hour) cell pre-filter; D3 = the wider of the date-clustered and the
circular block-3 interval; labels as ``label_for``.

Dates: D0 = the later of (freeze + 1, 2026-11-02) = 2026-11-02; 11-01 is excluded (the DST hour); window
D0..2027-01-25. One look only, on or after PT-1's look (``LOOK_EARLIEST``) and after every claiming look, in the
01-26 window; no interim look. Every function that reads a forward date calls ``require_look_gate`` first.

Stages (only through ``scripts\ops\workstation_heavy.ps1 -Queue`` after main admits the module; cwd = this tree,
``PYTHONPATH=<tree>\src``)::

    python -m tools.research.forward_f8.f8_mh preflight
    python -m tools.research.forward_f8.f8_mh look --out C:\t\l16\f8-look\<new> --layout <root> \
        --layout-manifest-sha <sha256> --export <root> --export-sums-sha <sha256> \
        --approval "<master's look approval>" --claiming-looks-done "B=<sha>;MG1=<sha>;L6G=<sha>;R72=<sha>;PT1=<sha>"

``preflight`` reads no data. ``look`` is the single look; its receipts are exclusive-create. Evidence class: a screen
(method §5 rule 8), never an edge claim.

Clarification 1 (master ruling (b), 2026-10-31, before any forward read;
``docs/research/f8-mh-forward-2026-10-31/clarification_1.md``, pinned by ``CLARIFICATION_1_SHA256``): scope "01-06
book mass above H on cooling nights (midnight-set max, >= 3°F drop), broader than the frontal story"; a KILL closes
the broad version only. Two disclosure splits, non-deciding, under the statistic's ``"disclosure"`` key: hour band
01-03 vs 04-06, and day max equal to H on the WU whole scale or not (OUTCOME-DEFINED, from the labels at the look
only, never a label). The frozen regime and the verdict path are unchanged.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA = "f8_mh_forward/1"
LEDGER_ROW = 104
ARM = "F8-MH"
TREE = Path(__file__).resolve().parents[3]
FREEZE_DOC_PATH = "docs/research/f8-mh-forward-2026-10-31/freeze.md"
FREEZE_DOC_SHA256 = "273c1070df0cb87c9c25366d5f8b37d61b766e2f0f2faa550c633e2a19523316"
S0_SPEC_PATH = "docs/research/f8-mh-forward-2026-10-31/s0_spec.md"
S0_SPEC_SHA256 = "795dd5091fdbaec702bd74ed650748f892e906710869140f3f8e42631ff026e8"
CLARIFICATION_1_PATH = "docs/research/f8-mh-forward-2026-10-31/clarification_1.md"
CLARIFICATION_1_SHA256 = "eef842e8a40da1f9041a038bec6ab6ece6103d16235cb2b58c0231f3e115d260"


class Refused(Exception):
    """A refusal: nothing is read or written past it."""


# ----------------------------------------------------------------------------- B's manifest (read-only imports)

B_MANIFEST_PATH = "docs/research/mg2-composite-binding-2026-10-25/release-binding.json"
B_MANIFEST_SHA256 = "4e4dd97d0b2aa0eae920d6ee5406160ca8f0c16a001ba1615446702554a812fa"  # B_FORWARD_TEST_DESIGN.md l.73
B_IMPORTED = (
    "src/weather/model/mg_serve_core.py",
    "src/weather/model/observed_running_max.py",
    "src/weather/reporting/scorecards/dev_scorecard.py",
    "src/weather/reporting/scorecards/dev_scorecard_data.py",
    "src/weather/reporting/scorecards/loss_atlas.py",
)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_blob_sha(path):
    raw = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()


def b_manifest_files(tree=TREE):
    """The ``files`` map of B's release-binding manifest, after its own sha256 is checked."""
    path = Path(tree) / B_MANIFEST_PATH
    if not path.is_file():
        raise Refused(f"refused: B's manifest {B_MANIFEST_PATH} is missing")
    if sha256_file(path) != B_MANIFEST_SHA256:
        raise Refused(f"refused: B's manifest sha256 is not {B_MANIFEST_SHA256}")
    files = json.loads(path.read_text(encoding="utf-8")).get("files") or {}
    return files


def check_b_manifest(tree=TREE, paths=B_IMPORTED):
    """Every B-bound file this module imports equals B's manifest entry (file sha256); refuses otherwise."""
    files = b_manifest_files(tree)
    got = {}
    for rel in paths:
        if rel not in files:
            raise Refused(f"refused: {rel} is not on B's manifest")
        p = Path(tree) / rel
        if not p.is_file():
            raise Refused(f"refused: B-bound file {rel} is missing")
        got[rel] = sha256_file(p)
        if got[rel] != files[rel]:
            raise Refused(f"refused: B-bound file {rel} sha256 {got[rel]} differs from B's manifest {files[rel]}")
    return {"manifest": B_MANIFEST_PATH, "manifest_sha256": B_MANIFEST_SHA256, "files": got}


def _module_rel(path_text, tree=TREE):
    try:
        return Path(path_text).resolve().relative_to(Path(tree).resolve()).as_posix()
    except (TypeError, ValueError):
        return None


def check_b_imports(tree=TREE):
    """Every loaded module whose file is on B's manifest is the checked tree's file with the manifest sha256."""
    files = b_manifest_files(tree)
    loaded = {}
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if not f or not name.startswith("weather."):
            continue
        tail = "src/" + name.replace(".", "/") + ".py"
        if tail not in files:
            continue
        rel = _module_rel(f, tree)
        if rel != tail:
            raise Refused(f"refused: B-bound module {name} loaded from {f}, not from {tree}")
        sha = sha256_file(f)
        if sha != files[tail]:
            raise Refused(f"refused: loaded B-bound module {name} sha256 {sha} differs from B's manifest")
        loaded[tail] = sha
    return loaded


B_IMPORT_CHECK = check_b_manifest()          # before the B-bound imports below

from weather.model import mg_serve_core as msc            # noqa: E402  (B-bound, read-only)
from weather.model import observed_running_max as orm     # noqa: E402  (B-bound, read-only)

check_b_imports()

# Non-B modules the statistic imports: git blob shas (pin 8bb0f9563 for the three vendored ones; master otherwise).
BLOBS = {
    "src/weather/calibration/mr_sweep.py": "f49e38184d62264f9684922b02b4ca2e8923781b",        # pin 8bb0f9563
    "src/weather/calibration/mr_gate.py": "153dd07c12cd20ca079cb4ee9647f9fce99e40e7",         # pin 8bb0f9563
    "src/weather/calibration/loyo_screen.py": "fd9ea5a7a0c8923042d522512771859746e2d55a",     # pin 8bb0f9563
    "src/weather/calibration/market_blend.py": "4a35e35b04cab11b27dc33c68fc8b85c4b084337",
    "src/weather/calibration/gap_to_market_atlas.py": "ba7ce305f68b1fa66ef0b30bccfa3408f5f13ffd",
    "src/weather/calibration/pooled_residual_model.py": "a7f9124fc6cb42b0307d9e681b4fef4928758b74",
    "src/weather/model/feature_store.py": "c11b3ca94747b3c1603cbbff9c4eebd4ad83cb4a",
    "src/weather/market/market_registry.py": "c6c8b143a9ded1462ccf6bd32738fa025db4ecdc",
}


def check_blobs(tree=TREE):
    bad = {rel: git_blob_sha(Path(tree) / rel) for rel in BLOBS
           if not (Path(tree) / rel).is_file() or git_blob_sha(Path(tree) / rel) != BLOBS[rel]}
    if bad:
        raise Refused(f"refused: pinned module blobs differ: {bad}")
    return dict(BLOBS)


def check_pinned_docs(tree=TREE):
    for rel, sha in ((FREEZE_DOC_PATH, FREEZE_DOC_SHA256), (S0_SPEC_PATH, S0_SPEC_SHA256)):
        p = Path(tree) / rel
        if not p.is_file() or sha256_file(p) != sha:
            raise Refused(f"refused: {rel} is not the frozen file (sha256 {sha})")
    return {FREEZE_DOC_PATH: FREEZE_DOC_SHA256, S0_SPEC_PATH: S0_SPEC_SHA256}


def check_clarifications(tree=TREE):
    p = Path(tree) / CLARIFICATION_1_PATH
    if not p.is_file() or sha256_file(p) != CLARIFICATION_1_SHA256:
        raise Refused(f"refused: {CLARIFICATION_1_PATH} is not the pinned file (sha256 {CLARIFICATION_1_SHA256})")
    return {CLARIFICATION_1_PATH: CLARIFICATION_1_SHA256}


# ----------------------------------------------------------------------------- frozen constants

MARKETS = tuple(m for m in msc.R0_MARKETS if m != "denver")      # B's US10, Denver out
HOURS = (1, 2, 3, 4, 5, 6)
T_H_LAST_MINUTE = 1 * 60 + 59                                    # t_H <= 01:59 local
DROP_F = 3                                                       # H - C >= 3 °F (whole degrees)
WU_RULE = "half_up"
PHYSICAL_F = (-80.0, 140.0)                                      # finiteness bound only; no 30..125 serve filter
MIN_CELL_DATES = 2                                               # frozen (market, hour) cell pre-filter

FREEZE_DATE = date(2026, 10, 31)
D0 = max(date(2026, 11, 2), date.fromordinal(FREEZE_DATE.toordinal() + 1))
EXCLUDED_DATES = frozenset({date(2026, 11, 1)})                  # DST: local hour 01 occurs twice
WINDOW_LAST = date(2027, 1, 25)
LOOK_EARLIEST = date(2027, 1, 27)                                # PT-1's look is on or after 01-27
CLAIMING_LOOKS = ("B", "MG1", "L6G", "R72", "PT1")               # every claim on these dates (freeze §8)
LOOK_ROOT = Path(r"C:\t\l16\f8-look")
LOOK_STARTED = "look_started.json"
LOOK_RECEIPT = "look_receipt.json"

MIN_DATES = 20
MIN_SNAPS = 1000
DELTA_EDGE = math.sqrt(0.05)                                     # 0.2236
POWER_MIN = 0.5
Z95 = 1.959963984540054
BLOCK_SEED, BLOCK_B, BLOCK_LEN = 20261024, 2000, 3

# Power projection reference (freeze §6): row 93 ENS-SD-0006 wider interval on 43 x 11 market-days x 7 hours.
SE_REF = (0.0349 + 0.0219) / (2 * Z95)
REF_MARKET_DAY_HOURS = 43 * 11 * 7
SNAPS_PER_MARKET_HOUR = 23668 / (43 * 11 * 7)
DEFF = 2.0

KILL = "KILL at edge size"
SCREEN = "SCREEN-POSITIVE (descriptive only)"
NOT_KILLED = "NOT KILLED, NOT SCREEN-POSITIVE"
UNTESTABLE = "UNTESTABLE"


# ----------------------------------------------------------------------------- the look gate

_GATE = None
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def parse_claiming_looks(text):
    out = {}
    for part in (text or "").split(";"):
        if part.strip():
            key, _, sha = part.partition("=")
            out[key.strip()] = sha.strip()
    missing = [k for k in CLAIMING_LOOKS if not _HEX64.match(out.get(k, ""))]
    if missing:
        raise Refused(f"refused: no receipt sha256 for the claiming look(s) {missing}")
    return out


def open_look_gate(today, approval, claiming_looks_done):
    """Open the single look: refuses before ``LOOK_EARLIEST`` (PT-1's look), without master's approval or without a
    receipt sha256 for every claiming look. Nothing reads a forward date until this has passed."""
    global _GATE
    if not isinstance(today, date) or today < LOOK_EARLIEST:
        raise Refused(f"refused: the F8-MH look is not before {LOOK_EARLIEST} (PT-1's look); today is {today}")
    if not approval or not str(approval).startswith("master") or ARM not in str(approval):
        raise Refused("refused: the look needs master's approval naming F8-MH")
    looks = parse_claiming_looks(claiming_looks_done)
    _GATE = {"today": today.isoformat(), "approval": str(approval), "claiming_looks": looks}
    return dict(_GATE)


def close_look_gate():
    global _GATE
    _GATE = None


def require_look_gate():
    if _GATE is None:
        raise Refused("refused: a forward date is read only after the look gate opens (open_look_gate)")
    return _GATE


def in_window(d):
    d = d if isinstance(d, date) else date.fromisoformat(str(d))
    return D0 <= d <= WINDOW_LAST and d not in EXCLUDED_DATES


def check_dates(dates):
    """Every date read is a window date; refuses otherwise (no date before D0, 11-01 or after 01-25)."""
    bad = sorted(str(d) for d in dates if not in_window(d))
    if bad:
        raise Refused(f"refused: dates outside D0..01-25 or excluded: {bad[:5]} ({len(bad)})")


# ----------------------------------------------------------------------------- the regime flag (pure)

def _is_speci(row, payload_types):
    raw = str(row.get("raw") or "").strip()
    first = raw.split()[0].upper() if raw else ""
    if first == "SPECI":
        return True
    declared = payload_types.get(raw)
    return declared is not None and str(declared).strip().upper() == "SPECI"


def routine_observations(metar, *, target_date, tz, captured):
    """[(local instant, temp °F)] of the routine (non-SPECI) captured METAR rows observed on ``target_date`` at or
    before ``captured``; one value per instant (a later row at the same instant replaces it, as a correction).
    Observation time: ``observed_running_max.metar_observation_local_time`` (obsTime, else the raw DDHHMMZ group)."""
    metar = metar or {}
    payload = [i for i in (metar.get("raw_payload") or []) if isinstance(i, dict) and i.get("rawOb")]
    obs_times = {str(i["rawOb"]): i["obsTime"] for i in payload if i.get("obsTime") is not None}
    types = {str(i["rawOb"]).strip(): i.get("metarType") for i in payload}
    cap_local = captured.astimezone(tz)
    kept, stats = {}, defaultdict(int)
    for row in metar.get("rows") or []:
        if _is_speci(row, types):
            stats["speci"] += 1
            continue
        value = orm.row_temp_native(row)
        try:
            value = float(value)
        except (TypeError, ValueError):
            stats["no_temp"] += 1
            continue
        if not math.isfinite(value) or not PHYSICAL_F[0] <= value <= PHYSICAL_F[1]:
            stats["no_temp"] += 1
            continue
        instant = orm.metar_observation_local_time(row, tz, obs_times)
        if instant is None:
            stats["untimed"] += 1
            continue
        if instant.date() != target_date:
            stats["other_date"] += 1
            continue
        if instant > cap_local:
            stats["after_capture"] += 1
            continue
        kept[instant] = value
    return sorted(kept.items()), dict(stats)


def regime_from_observations(obs):
    """The F8-MH flag from routine observations [(local instant, °F)] sorted by instant.

    H = the max on WU's whole scale (``mg_serve_core.wu_whole_f``, half up), t_H = the earliest instant whose whole
    value is H, C = the whole value of the latest observation. Regime iff t_H <= 01:59 local and H - C >= 3."""
    if not obs:
        return {"regime": False, "missing": True, "H": None, "C": None, "t_H": None, "n": 0}
    whole = [(t, msc.wu_whole_f(v, WU_RULE)) for t, v in obs]
    if any(w is None for _, w in whole):
        return {"regime": False, "missing": True, "H": None, "C": None, "t_H": None, "n": len(obs)}
    high = max(w for _, w in whole)
    t_high = min(t for t, w in whole if w == high)
    current = whole[-1][1]
    flag = (t_high.hour * 60 + t_high.minute) <= T_H_LAST_MINUTE and (high - current) >= DROP_F
    return {"regime": bool(flag), "missing": False, "H": float(high), "C": float(current),
            "t_H": t_high.isoformat(), "n": len(obs)}


def snapshot_regime(rec, *, market, target_date, local_hour, captured, tz):
    """The flag for one captured snapshot record (``sources.metar.data``). Out of scope (not US10, not 01-06, not a
    window date) is never regime."""
    if market not in MARKETS or int(local_hour) not in HOURS or not in_window(target_date):
        return {"regime": False, "missing": False, "scope": False}
    metar = (((rec or {}).get("sources") or {}).get("metar") or {}).get("data")
    if not isinstance(metar, dict) or captured is None:
        return {"regime": False, "missing": True, "scope": True, "H": None}
    obs, stats = routine_observations(metar, target_date=target_date, tz=tz, captured=captured)
    out = regime_from_observations(obs)
    out.update(scope=True, row_stats=stats)
    return out


# ----------------------------------------------------------------------------- population and power

def cell_prefilter(rows):
    """rows: [{"row_key", "market", "local_hour", "date"}] of regime snapshots. Keeps the (market, hour) cells with
    >= MIN_CELL_DATES distinct regime dates (a cell of one date cannot be deranged across dates)."""
    dates = defaultdict(set)
    for r in rows:
        dates[(r["market"], int(r["local_hour"]))].add(str(r["date"]))
    keep = {k for k, v in dates.items() if len(v) >= MIN_CELL_DATES}
    kept = [r for r in rows if (r["market"], int(r["local_hour"])) in keep]
    return kept, {"cells": len(dates), "cells_kept": len(keep),
                  "dropped_cells": sorted(f"{m}|{h}" for (m, h) in set(dates) - keep),
                  "snapshots_kept": len(kept), "dates_kept": len({r["date"] for r in kept}),
                  "market_day_hours_kept": len({(r["market"], r["date"], int(r["local_hour"])) for r in kept})}


def power_at(edge, se):
    """P(upper 95% bound < edge | true effect 0) = Phi(edge / se - 1.96) (c3_kill_tier.power_at @ b1d8e65fd)."""
    if se is None or not math.isfinite(se) or se <= 0:
        return None
    return 0.5 * (1.0 + math.erf((edge / se - Z95) / math.sqrt(2.0)))


def projected_se(market_day_hours, deff=DEFF):
    if not market_day_hours or market_day_hours <= 0:
        return None
    return SE_REF * math.sqrt(REF_MARKET_DAY_HOURS / market_day_hours) * math.sqrt(deff)


def projected_power(market_day_hours, deff=DEFF):
    return power_at(DELTA_EDGE, projected_se(market_day_hours, deff))


def block_counts(n_dates, b=BLOCK_B, seed=BLOCK_SEED, length=BLOCK_LEN):
    """Circular moving-block bootstrap counts (c3_kill_tier.block_counts @ b1d8e65fd, REV-2), as per-date counts."""
    import numpy as np

    k = -(-n_dates // length)
    starts = np.random.default_rng(seed).integers(n_dates, size=(b, k))
    idx = ((starts[:, :, None] + np.arange(length)) % n_dates).reshape(b, -1)[:, :n_dates]
    return np.stack([np.bincount(r, minlength=n_dates) for r in idx]).astype(float)


def label_for(testable, power, lower, upper, edge=DELTA_EDGE, power_min=POWER_MIN):
    """Freeze §7 order: coverage and in-run power, KILL, SCREEN-POSITIVE, otherwise neither."""
    if not testable or power is None or power < power_min or lower is None or upper is None:
        return UNTESTABLE
    if upper < edge:
        return KILL
    if lower > 0 and upper >= edge:
        return SCREEN
    return NOT_KILLED


# ----------------------------------------------------------------------------- the statistic

def _delta_sd(sw, sums_c, sums_pl, counts):
    import numpy as np

    rho_c = sw.mg._rho(*(counts @ sums_c.T).T)
    j_b = np.arange(len(counts)) % len(sums_pl)
    pl = np.empty(len(counts))
    for j, s in enumerate(sums_pl):
        pl[j_b == j] = sw.mg._rho(*(counts[j_b == j] @ s.T).T)
    d = rho_c - pl
    d = d[np.isfinite(d)]
    return float(np.std(d, ddof=1)) if len(d) > 1 else None


def wider_interval(sw, rows, n_dates):
    """Date-clustered (``mr_sweep.boot_counts``) and circular block-3 intervals through ``mr_sweep.paired_delta``;
    the wider bounds and the larger bootstrap SD."""
    import numpy as np

    sums_c = np.array([r["sums_c"] for r in rows], float).T
    sums_pl = [np.array([r["sums_pl"][j] for r in rows], float).T for j in range(len(sw.PLACEBO_SEEDS))]
    dc_counts, b3_counts = sw.boot_counts(n_dates), block_counts(n_dates)
    dc, b3 = sw.paired_delta(sums_c, sums_pl, dc_counts), sw.paired_delta(sums_c, sums_pl, b3_counts)
    se = [_delta_sd(sw, sums_c, sums_pl, c) for c in (dc_counts, b3_counts)]
    lo = None if None in (dc["ci95"][0], b3["ci95"][0]) else min(dc["ci95"][0], b3["ci95"][0])
    hi = None if None in (dc["ci95"][1], b3["ci95"][1]) else max(dc["ci95"][1], b3["ci95"][1])
    se_w = None if None in se else max(se)
    return {"delta": dc["delta"], "p_one_sided": dc["p_one_sided"], "ci95_date_clustered": dc["ci95"],
            "ci95_block3": b3["ci95"], "ci95_wider": [lo, hi], "se_date_clustered": se[0], "se_block3": se[1],
            "se_wider": se_w, "power_at_edge": power_at(DELTA_EDGE, se_w)}


def run_statistic(t, h_values, score_dates=None, day_max=None, clarification_disclosure=True):
    """The frozen arm on a regime-only table ``t`` (``dev_scorecard.Table`` or an equivalent): type C toward H.
    Returns the result dict with the D3 interval, the label and the non-deciding disclosures.

    ``day_max`` (the labels' settlement high per table snapshot, look only) and ``clarification_disclosure`` feed
    Clarification 1's ``"disclosure"`` key only; they are used after the label is fixed and never reach it."""
    import numpy as np

    from weather.calibration import mr_sweep as sw

    check_b_imports()
    if (sw.MIN_DATES, sw.MIN_SNAPS) != (MIN_DATES, MIN_SNAPS):
        raise Refused(f"refused: mr_sweep floors are {(sw.MIN_DATES, sw.MIN_SNAPS)}, not {(MIN_DATES, MIN_SNAPS)}")
    h = np.asarray(h_values, float)
    if len(h) != len(t.snaps) or not np.isfinite(h).all():
        raise Refused("refused: every regime-table snapshot needs a finite H")
    if score_dates is None:
        score_dates = np.array(sorted(t.snaps.date.astype(str).unique()))
    geo = sw.band_geometry(t)
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(t, seed) for seed in sw.PLACEBO_SEEDS}
    res, _ = sw.p0_candidate(ARM, "C", 1, h, t, t, geo, counts, score_dates, donors)
    rows = res.pop("_rows", None) or []
    out = {"result": res}
    d3 = {}
    if res["testable"]:
        d3 = wider_interval(sw, rows, len(score_dates))
        if abs(d3["delta"] - res["p0"]["delta"]) > 1e-12:
            raise Refused("refused: the D3 rows do not reproduce p0_candidate")
    out["d3"] = d3
    lo, hi = d3.get("ci95_wider") or [None, None]
    out["label"] = label_for(res["testable"], d3.get("power_at_edge"), lo, hi)
    # Non-deciding disclosures: zero tilt (value = the market mean) outside the subset, the same population.
    above = geo["mu"] > h
    subsets = {"market_mean_above_H": above, "market_mean_at_or_below_H": ~above}
    for hour in HOURS:
        subsets[f"hour_{hour:02d}"] = t.local_hour == hour
    for mk in sorted(set(t.markets)):
        subsets[f"market_{mk}"] = t.markets == mk
    disc = {}
    for name, mask in subsets.items():
        if not mask.any():
            disc[name] = {"snapshots": 0}
            continue
        sub, _ = sw.p0_candidate(f"{ARM}:{name}", "C", 1, np.where(mask, h, geo["mu"]), t, t, geo, counts,
                                 score_dates, donors)
        sub.pop("_rows", None)
        disc[name] = {"snapshots": int(mask.sum()), "delta": (sub.get("p0") or {}).get("delta"),
                      "ci95": (sub.get("p0") or {}).get("ci95")}
    out["disclosure_non_deciding"] = disc
    out["control_zero_tilt"] = control_zero_tilt(sw, t, geo, counts, score_dates, donors)
    if clarification_disclosure:
        try:
            out["disclosure"] = clarification_1_disclosure(sw, t, h, geo, counts, score_dates, donors, day_max)
        except Exception as exc:  # noqa: BLE001 - a disclosure problem never stops or changes the look
            out["disclosure"] = {"non_deciding": True, "clarification": CLARIFICATION_1_PATH,
                                 "clarification_sha256": CLARIFICATION_1_SHA256, "error": repr(exc)}
    return out


def _zero_tilt_split(sw, name, mask, h, t, geo, counts, score_dates, donors):
    """Delta with zero tilt (value = the market mean) outside ``mask``, on the same population (freeze §7 method)."""
    import numpy as np

    if not mask.any():
        return {"snapshots": 0, "delta": None, "ci95": None}
    sub, _ = sw.p0_candidate(f"{ARM}:{name}", "C", 1, np.where(mask, h, geo["mu"]), t, t, geo, counts, score_dates,
                             donors)
    sub.pop("_rows", None)
    p0 = sub.get("p0") or {}
    return {"snapshots": int(mask.sum()), "dates": int(len(set(np.asarray(t.snaps.date.astype(str))[mask]))),
            "delta": p0.get("delta"), "ci95": p0.get("ci95")}


def day_max_split_masks(h, day_max):
    """Clarification 1 (b), OUTCOME-DEFINED: day max (WU whole scale, ``wu_whole_f`` half up) equal to H or not.
    A missing or non-finite day max is in neither mask."""
    import numpy as np

    dm = np.asarray(day_max, float)
    whole = np.array([msc.wu_whole_f(v, WU_RULE) if math.isfinite(v) else np.nan for v in dm], float)
    known = np.isfinite(whole)
    eq = known & (whole == np.asarray(h, float))
    return eq, known & ~eq, int((~known).sum())


def clarification_1_disclosure(sw, t, h, geo, counts, score_dates, donors, day_max):
    """Clarification 1 §2, non-deciding: (a) hour band 01-03 vs 04-06; (b) day max == H on the WU whole scale or not
    (outcome-defined, from the labels at the look only). Never a label, filter or gate."""
    import numpy as np

    hours = np.asarray(t.local_hour, int)
    band = {"hours_01_03": (hours >= 1) & (hours <= 3), "hours_04_06": (hours >= 4) & (hours <= 6)}
    out = {"non_deciding": True, "clarification": CLARIFICATION_1_PATH,
           "clarification_sha256": CLARIFICATION_1_SHA256,
           "hour_band": {k: _zero_tilt_split(sw, k, m, h, t, geo, counts, score_dates, donors)
                         for k, m in band.items()}}
    if day_max is None:
        out["day_max_vs_H"] = {"available": False, "outcome_defined": True}
        return out
    if len(day_max) != len(h):
        out["day_max_vs_H"] = {"available": False, "outcome_defined": True, "reason": "length mismatch"}
        return out
    eq, ne, missing = day_max_split_masks(h, day_max)
    out["day_max_vs_H"] = {"available": True, "outcome_defined": True, "missing_day_max": missing,
                           "day_max_eq_H_frontal": _zero_tilt_split(sw, "day_max_eq_H", eq, h, t, geo, counts,
                                                                    score_dates, donors),
                           "day_max_ne_H": _zero_tilt_split(sw, "day_max_ne_H", ne, h, t, geo, counts, score_dates,
                                                            donors)}
    return out


def labels_day_max(lay, row_keys):
    """Look only (after the verdict inputs are fixed): the labels' ``settlement_high`` per row_key, or None when the
    labels carry no such column (Clarification 1 (b) is then recorded unavailable)."""
    require_look_gate()
    if "settlement_high" not in lay.labels.columns:
        return None
    lab = lay.labels.drop_duplicates("row_key").set_index(lay.labels.drop_duplicates("row_key").row_key.astype(str))
    return lab.settlement_high.reindex(list(row_keys)).to_numpy(float)


def control_zero_tilt(sw, t, geo, counts, score_dates, donors):
    """w = 0 identity: the value equal to the market mean gives a zero signal, so the tilted vector c equals the
    market on every band (max |c - m| < 1e-12). Delta itself is not used: with c = m it is undefined."""
    import numpy as np

    res, extra = sw.p0_candidate(f"{ARM}:zero", "C", 1, geo["mu"].copy(), t, t, geo, counts, score_dates, donors)
    if extra is None:
        covered = np.ones(len(t.snaps), bool)
        c_fit = sw.tilt(t, geo, sw.band_signal("C", 1, geo["mu"].copy(), t, geo), covered)[0]
    else:
        c_fit = extra["c_fit"]
    gap = float(np.max(np.abs(np.asarray(c_fit, float) - t.p_market))) if len(t.p_market) else 0.0
    return {"max_abs_c_minus_m": gap, "pass": bool(gap < 1e-12)}


def control_cells(rows):
    """Every regime-table (market, hour) cell has >= MIN_CELL_DATES dates after the pre-filter."""
    dates = defaultdict(set)
    for r in rows:
        dates[(r["market"], int(r["local_hour"]))].add(str(r["date"]))
    bad = sorted(f"{m}|{h}" for (m, h), v in dates.items() if len(v) < MIN_CELL_DATES)
    return {"pass": not bad, "bad_cells": bad}


# ----------------------------------------------------------------------------- forward reads (gated)

SNAP_ID = re.compile(rb'"snapshot_id":\s*"([^"]+)"')


def read_export(root, sums_sha, wanted):
    """Gated. Stream each wanted slug's replay_inputs.jsonl once (hash-checked against the export SHA256SUMS) and
    return {row_key: record}; ``wanted`` maps row_key ("<slug>|<snapshot_id>") to slug."""
    require_look_gate()
    root = Path(root)
    sums = root / "SHA256SUMS"
    if sha256_file(sums) != sums_sha:
        raise Refused(f"refused: export SHA256SUMS is not {sums_sha}")
    listed = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, rel = line.split(None, 1)
            listed[rel.strip().lstrip("*")] = digest
    by_slug = defaultdict(dict)
    for rk, slug in wanted.items():
        by_slug[slug][rk.split("|", 1)[1]] = rk
    recs, malformed = {}, []
    for slug in sorted(by_slug):
        rel = f"data/snapshots/{slug}/replay_inputs.jsonl"
        if rel not in listed:
            malformed.append({"slug": slug, "missing_from_sums": True})
            continue
        h, ids = hashlib.sha256(), by_slug[slug]
        with (root / rel).open("rb") as fh:
            for lineno, line in enumerate(fh, 1):
                h.update(line)
                m = SNAP_ID.search(line)
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
        if h.hexdigest() != listed[rel]:
            raise Refused(f"refused: {rel} sha256 differs from the export SHA256SUMS")
    return recs, malformed


@contextlib.contextmanager
def forward_layout_override(data):
    """Gated, scoped: the dev layout loader's date guards are lifted to WINDOW_LAST inside the look only."""
    require_look_gate()
    saved = (data.DEV_LAST, data.WU_LABEL_RULE_LAST)
    data.DEV_LAST, data.WU_LABEL_RULE_LAST = WINDOW_LAST, WINDOW_LAST
    try:
        yield {"DEV_LAST": WINDOW_LAST.isoformat(), "WU_LABEL_RULE_LAST": WINDOW_LAST.isoformat()}
    finally:
        data.DEV_LAST, data.WU_LABEL_RULE_LAST = saved


def regime_layout(lay, keep_keys):
    """The layout restricted to the kept regime snapshots (bands, labels and prices follow by row_key)."""
    from dataclasses import replace

    keep = lay.snaps.row_key.astype(str).isin(keep_keys)
    snaps = lay.snaps[keep].reset_index(drop=True)
    keys = set(snaps.row_key.astype(str))
    sel = lambda f: f[f.row_key.astype(str).isin(keys)].reset_index(drop=True)  # noqa: E731
    return replace(lay, snaps=snaps, bands=sel(lay.bands), labels=sel(lay.labels), market=sel(lay.market),
                   dates=sorted(snaps.date.astype(str).unique()))


def _utc(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def write_exclusive(path, payload):
    raw = (json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
    with open(path, "xb") as fh:
        fh.write(raw)
    return hashlib.sha256(raw).hexdigest()


def git_state(tree=TREE):
    head = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(tree), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        raise Refused("refused: the run tree has tracked changes")
    return {"head": head}


def guards(tree=TREE):
    return {"b_manifest": check_b_manifest(tree), "b_loaded": check_b_imports(tree), "blobs": check_blobs(tree),
            "docs": check_pinned_docs(tree), "clarifications": check_clarifications(tree), "git": git_state(tree)}


def look(args, today=None):
    """The single look (freeze §4-§7). Refuses before the gate; one look per ``LOOK_ROOT``."""
    import numpy as np

    from weather.market.market_registry import spec_for_id
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    gd = guards()
    gate = open_look_gate(today or date.today(), args.approval, args.claiming_looks_done)
    out = Path(args.out)
    if out.parent.resolve() != LOOK_ROOT.resolve():
        raise Refused(f"refused: --out must be a new folder directly under {LOOK_ROOT}")
    if LOOK_ROOT.exists() and any(LOOK_ROOT.glob(f"*/{LOOK_STARTED}")):
        raise Refused("refused: a look has already started (one look only)")
    out.mkdir(parents=True, exist_ok=False)
    started_sha = write_exclusive(out / LOOK_STARTED, {"schema": SCHEMA + "/look_started", "gate": gate,
                                                       "guards": gd, "at": datetime.now(timezone.utc)})
    if sha256_file(Path(args.layout) / data.MANIFEST) != args.layout_manifest_sha:
        raise Refused("refused: the forward layout manifest sha256 is not the one given")
    with forward_layout_override(data) as override:
        lay = data.load_layout(args.layout, D0, WINDOW_LAST)
    s = lay.snaps
    scope = s[s.market.astype(str).isin(MARKETS) & s.local_hour.astype(int).isin(HOURS)]
    scope = scope[[in_window(d) for d in scope.date.astype(str)]]
    check_dates(set(scope.date.astype(str)))
    wanted = dict(zip(scope.row_key.astype(str), scope.event_slug.astype(str)))
    recs, malformed = read_export(args.export, args.export_sums_sha, wanted)
    flags, reasons, regime_rows = {}, defaultdict(int), []
    for r in scope.itertuples(index=False):
        spec = spec_for_id(str(r.market))
        f = snapshot_regime(recs.get(str(r.row_key)), market=str(r.market), target_date=date.fromisoformat(
            str(r.date)), local_hour=int(r.local_hour), captured=_utc(r.captured_at_utc), tz=spec.tz)
        flags[str(r.row_key)] = f
        reasons["missing" if f.get("missing") else ("regime" if f["regime"] else "not_regime")] += 1
        if f["regime"]:
            regime_rows.append({"row_key": str(r.row_key), "market": str(r.market), "local_hour": int(r.local_hour),
                                "date": str(r.date), "H": f["H"]})
    kept, prefilter = cell_prefilter(regime_rows)
    projection = {"market_day_hours": prefilter["market_day_hours_kept"],
                  "power_deff2": projected_power(prefilter["market_day_hours_kept"])}
    print(json.dumps({"population_rule16": prefilter, "projection": projection}, default=str), flush=True)
    controls = {"cells": control_cells(kept)}
    rlay = regime_layout(lay, {r["row_key"] for r in kept})
    t = sc.Table(rlay, rlay.dates)
    h_by_key = {r["row_key"]: r["H"] for r in kept}
    h = np.array([h_by_key[k] for k in t.snaps.row_key.astype(str)], float)
    try:
        day_max = labels_day_max(rlay, t.snaps.row_key.astype(str))
    except Exception:  # noqa: BLE001 - Clarification 1 (b): a disclosure problem never stops the look
        day_max = None
    stat = run_statistic(t, h, day_max=day_max)
    controls["zero_tilt"] = stat.pop("control_zero_tilt")
    if not all(c["pass"] for c in controls.values()):
        stat["label"] = UNTESTABLE + " (a control failed; master rules, freeze §7 rule (e))"
    receipt = {"schema": SCHEMA + "/look", "ledger_row": LEDGER_ROW, "arm": ARM, "gate": gate, "guards": gd,
               "module_sha256": sha256_file(__file__), "look_started_sha256": started_sha,
               "layout_manifest_sha256": args.layout_manifest_sha, "export_sums_sha256": args.export_sums_sha,
               "override_in_process": override, "malformed": malformed, "flag_reasons": dict(reasons),
               "population_rule16": prefilter, "projection": projection, "controls": controls,
               "window": [D0.isoformat(), WINDOW_LAST.isoformat()], "excluded_dates": sorted(map(str, EXCLUDED_DATES)),
               "edge": DELTA_EDGE, "power_min": POWER_MIN, "statistic": stat,
               "evidence_class": "screen (method §5 rule 8); never an edge claim"}
    sha = write_exclusive(out / LOOK_RECEIPT, receipt)
    print(json.dumps({"label": stat["label"], "receipt_sha256": sha}), flush=True)
    return receipt


def build_parser():
    p = argparse.ArgumentParser(prog="f8_mh", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="stage", required=True)
    sub.add_parser("preflight", help="guards only; reads no data")
    lk = sub.add_parser("look", help="the single look (gated)")
    for name in ("--out", "--layout", "--layout-manifest-sha", "--export", "--export-sums-sha", "--approval",
                 "--claiming-looks-done"):
        lk.add_argument(name, required=True)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.stage == "preflight":
            print(json.dumps(guards(), indent=2, default=str))
            return 0
        look(args)
        return 0
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
