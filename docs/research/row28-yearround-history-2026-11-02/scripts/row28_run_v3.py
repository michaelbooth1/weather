"""Row 28 runner v3 (lane L59): year-round P3d_N refit, HISTORY-ONLY kill-only prereg.

v2 = row28_run_v1.py plus master's pre-rulings and v1-review rulings of 2026-11-03 (``CLARIFICATION_1.md``):
every ruling is one marked RULING_* constant below. Every HALT fires before the label join (R6).
v3 = v2 plus master's sealed-window rulings 1-2 and the v2 delta-review items N1-N8 (``CLARIFICATION_2.md``):
the section 7 WU reader tests a raw byte prefix before any decode; the runner's own daily_summary reads filter
on a raw line prefix before any split; an output guard scans every output and log for dates; no HALT fires
once a look or final row exists (N1); n is the integrity-restated n (N2); run stamps are ISO basic format.

Frozen prereg: ``prereg_row28.md`` sha256 cb6d4e8d... at tip 2a0b3ffb...; ``FREEZE_RECORD.md`` governs its
Status line. Launched only by ``C:\\t\\L59\\row28\\run_row28_guarded_v3.ps1`` (master ruling 2026-11-03, option 2,
a one-off for row 28; L47 precedent). One stage per invocation (``--stage``); each stage writes its report to
``--out-json`` (and a path/sha256 list of its outputs to ``--out-csv``) and stops:

  controls  -- C-0 (R-A reproduction), C-0b (12-09 / 01-08 records), C-0c (gap blocks vs L9), C-b (empty pool)
  build     -- every record window (bound ``extract_market``), the y-free row frame, NBM tables, pool feature rows
  integrity -- outcome-blind integrity report (drops, caps, imputation, label presence, C-pool control,
               empty pool, S and its 1e-12 check, the section 7 V4->V5 gate); commit it
  labels    -- needs --integrity committed: label join (market and pool), y-free parity, consistency asserts
  look      -- folds 2021-23 only (the integrity-committed kept dates of those folds); per-arm look; commit it
  score     -- needs the look committed: folds 2024-25, statistics, section 8.2 / 8.4 outcomes

Bound code is imported read-only and never edited: ``pooled_residual_model`` (extract_market, covered_years,
pooled_frame, attach_training_nbm, fit_pooled, predictive_distribution, nearest_centre with Rule L),
``feature_model`` (brier_score, log_loss, smoothed_dist), ``ols_floor_ladder`` (NBM corpus, load_nbm,
nbm_at_cutoff), ``free_source_candidates.mg1.predict`` and ``mg_serve_core.mg1_band_probs`` (S), and R-P2's
``station_pool_corpus`` (sha-pinned copy). Hard limits enforced here: no row or label dated after 2025 is used
(the section 7 inputs-only reader alone reaches 2026-01-01..05-26 and HALTs past it), nothing under
C:\\t\\l2\\p2 or any panel store is opened, and every write lands under C:\\t\\L59\\row28\\run.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # no __pycache__ write outside the run root (worktree src, tools copy)

import argparse
import csv
import glob
import gzip
import hashlib
import importlib.util
import json
import math
import os
import pickle
import re
import stat
import statistics
import subprocess
import traceback
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from types import SimpleNamespace

STAGES = ("controls", "build", "integrity", "labels", "look", "score")

# ----------------------------------------------------------------------------- frozen pins
PREREG_SHA256 = "cb6d4e8da0ab5a144a185cf8dbaf777881402ea8a95db99f2a0e98f20a5e132b"
FREEZE_RECORD_SHA256 = "f43110eb7c9dc34122c0f22222e043ea698df86ee41ea163dd7c59e628e2b2a3"
DECIDING_LF_SHA256 = "a2f601baef06dc662bedb710f53392f29da826c0eaede83182311768b3105b29"
DOC_DIR = "docs/research/row28-yearround-history-2026-11-02"
BRANCH = "claude/row28-yearround-history-20261102"
MODULE_SHA256 = {  # bound / reused modules at the freeze tip (equal to origin/master)
    "src/weather/calibration/pooled_residual_model.py": "52c497a95a69c3fbf78dbfe030b3190d93e940f180b81867a241552b3932a170",
    "src/weather/calibration/feature_model.py": "fe0dd4acfdd8724a434e6a6ba891a1c14236b651cb50d614b8b36c6e64ebed61",
    "src/weather/calibration/ols_floor_ladder.py": "6e6d100fb5bb2c9c2d811a681a3a88d9458305ef701ba4b8651be34011c12e8e",
    "src/weather/calibration/feature_model_training_inputs.py": "187e9b537cb4d3a79e2a5502e9322260f0e8ab5f0821416b46c7388069cbf50f",
    "src/weather/calibration/feature_column_allowlist.py": "956ddac245d182f2428da42d61a820c8a2dd455a083f30d86c63fcfe9390ae1d",
    "src/weather/calibration/new_city_corpus.py": "fed8182bb85280676e83223b2806057c2d2368d4824d7190b132b48415e2aaed",
    "src/weather/reporting/scorecards/free_source_candidates/mg1.py": "ad6e524ee103072e7738d78264cf1df855a30b01b43099425d4a1de7ae3d889d",
    "src/weather/model/mg_serve_core.py": "179fcbe495f36f6fd194c1bd0052ed6e150b0f016adbe0f8e9bb6128bd42e5d8",
}
SPC_SHA256 = "d4947cfe1b02c537ec84fca994ef0c1c26572be0251810eb744b421aae09f0b7"  # R-P2 station_pool_corpus.py
L9_CORPUS_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
RA_ROWS_SHA256 = "21cacdaabcf50165da084a748b42a0b862c36c9e1f4b8d4bdb506c07c927f54d"
RA_ROWS_N = 19657
CLASSES_SHA256 = "35d0090dddf7b082c5ce0d777cf488c09bbcf6baead14c786e68c39fbafe1689"
STATIONS_META_SHA256 = "60351c587d626a32d5978576955a5f740b5fbed7694b083abe0b6ea3d0131d67"
STATION_SET_SHA256 = "f757acb7df88065aa861d4d7ea0e02cd78c4b886d734df9c3facaa27d5d01619"
A57_CORPUS_ID = "a57e10a60fce936a98cd8478423b502496afa7347967eaaac1d452e453aad39f"
L48_POOL_BLOCKS_SHA256 = "e15ee14bbd33f2fb7f396208b0843f3b226c8cf57abfe7ebd91b8621d5db3aa3"
L48_RECEIPTS_SHA256 = "daa92d8440abbd1494cfacb427d72683d6968aad57b5bf7534874b50c53b4cd0"
FETCH_MANIFEST_SHA256 = {
    "manifest_nbp.json": "2948b7180f54b0aa413360553d82851a3e3610cf1a3576104422d346259b6f5f",
    "manifest_iem.json": "17aca6d162316aeb4b391cd145ca830578e8191e1a49a878bb6e93ed699ad61f",
    "manifest_nbp_gap.json": "02e5e8cbe67839ff3d8c68de4ea3633d28f97e9f24439078a6dd9010ba501c7b",
    "manifest_iem_gap.json": "bdf84209d1ef99c2cff74caf0b81201b63e873944fd2cb8607dc9277fa9fb402",
}
BLOCK_FILES = {  # fetch-relative path -> the manifest that records its sha256
    "c07": ("nbp\\nbp_station_blocks_c07.jsonl", "manifest_nbp.json"),
    "addon": ("nbp\\nbp_station_blocks_addon_01_00.jsonl", "manifest_nbp.json"),
    "gap": ("nbp\\nbp_station_blocks_gap_c07.jsonl", "manifest_nbp_gap.json"),
}
IEM_LISTS = (("iem\\iem_files_sha256.tsv", "manifest_iem.json"), ("iem_gap_files_sha256.tsv", "manifest_iem_gap.json"))
# PIT corpus sets per season, exactly as the R-A / l2 extractions recorded them (C:\t\l2\argv_extract_*.json,
# argv_janjul.json). PITForecastCorpusUnion refuses overlapping years, so one union of all corpora cannot be built.
SEASON_CORPORA = {
    "aug_sep": ("b455bd53d8f9aab47f57d1fd97250945d687cdf7167d3a3a33738687c902f017",),
    "oct_dec": ("cd0ba2bb004dc89f070ec9b1406e77f38cd2396dedd93ce1b377e727baefe9be",
                "23ac87fa5f058f8eeb7f49f0268f483939d4070f7f65e38063727c6749aa2a8d",
                "74807fbef1ba33ce8cd9c697b839369b1e3f3b7bbca7ebc3ac9f27edf84498cd"),
    "jan_jul": ("3a7034d2cb37f3425748bd4eeca048af85d8fd9bb0ef7a25519982b94ec8a6ba",
                "672a1f57632534076cba99ae2adebcbeb229decb58276d52fda79bd3946f18d2",
                "ece9d1c28454aa41113b022b92ff6600dcb4a5dab44a6851af5d895feea9281e"),
}

US10 = ("atlanta", "austin", "chicago", "dallas", "houston", "los-angeles",
        "miami", "nyc", "san-francisco", "seattle")
DESCRIPTIVE_MARKETS = ("denver",)
SCORED_HOURS = (13, 14, 15, 16)
FOLDS = (2021, 2022, 2023, 2024, 2025)
LOOK_FOLDS = (2021, 2022, 2023)
FINAL_FOLDS = (2024, 2025)
FOLD_DATES = {2021: 61, 2022: 164, 2023: 165, 2024: 120, 2025: 150}
N_DECIDING = 660
N_LOOK = 390
DEV_LAST = date(2025, 12, 31)       # hard limit: dev dates <= 2025
LAST_TRAIN = date(2025, 12, 16)     # fold 2026 (2025-12-17..) is never training and is not built
ARMS = ("A", "B", "C", "D")

FUTILITY = -0.00285
EDGE = 0.0057
KAPPA_FLOOR = 1.318
INFLATION = 1.07
Z_HOLM_WORST = 2.498
Z_XA = 1.960
POWER_ADEQUATE = 0.80
POWER_RULE16 = 0.50
XA_POINT_KILL = -0.0005
CAP_POOLED, CAP_MARKET, CAP_FOLD = 0.010, 0.030, 0.020
IMPUTE_CAP = 0.05
K112_W, K112_LAMBDA, K112_CLIP = 14, 0.25, 3.0
G_FORWARD_DATES = 166
S_TOL = 1e-12
S_SYNTHETIC_ROWS = 50
S_SYNTHETIC_SEED = 20261103
S_TAIL_SIGMAS = 10.0
CONTROL_TOL = 1e-9
FORBIDDEN_ROOTS = (Path(r"C:\t\l2\p2"),)

# ----------------------------------------------------------------------------- rulings (CLARIFICATION_1.md)
# Each master ruling of 2026-11-03 is exactly one constant; the code below reads only these.
RULING_R6_ALL_HALTS_BEFORE_LABEL_JOIN = True   # R6: label PRESENCE counted in stage 2 before blanking; C-pool
#   control (input columns, no y) and the empty-pool recheck run at stage 3; stage 4 only re-asserts them
RULING_R9_TOP_BUCKET_GTE = True                # R9: y >= top bucket K scores as K, identically for S and every arm
RULING_R10_IMPUTE_GROUP = "calendar_month"     # R10: cap per arm x calendar month (MM) pooled over years
RULING_R11_POOL_NO_NBM = "fill_from_normal"    # R11 as acknowledged in C2 (N5): keep the pool row; NaN fh ->
#   the bound NaN path (prm _anchors 476-477) anchors it on the in-fold training mean y; it counts toward C's cap
RULING_F14_PER_MARKET_CI = "ci95_wide"         # F14 / Clarification 1: per-market decisions use the WIDE CI
RULING_F9_SECTION7_GATE = "compute"            # F9: section 7 computed as frozen, inputs only, <= 2026-05-26
RULING_S7_SEALED_LINES = "skip_undecoded"      # see S7 reader: lines dated >= 2026-05-27 are never json-decoded
# v3 (CLARIFICATION_2.md). N1/N2/N5 are master's rulings of 2026-11-03 (adopted / acknowledged).
RULING_C2_S7_RAW_PREFIX = "rb_prefix_before_decode"  # ruling 1: date test on the raw bytes prefix, before any decode
RULING_C2_DAILY_PREFIX = "raw_line_prefix_filter"    # ruling 2: runner's own daily_summary reads filter before split
RULING_C2_OUTPUT_GUARD = "halt_pre_score"            # ruling 2: any non-allowlisted date >= 2026-01-01 in an output
RULING_N1_NO_HALT_AFTER_SCORE = True                 # N1: once look/final rows exist, nothing HALTs; FLAGs only
RULING_N1_STAGE_END_MANIFEST = "flag_classified"     # N1: look/score stage-end manifest diff -> FLAG, classified
RULING_N2_N = "integrity_restated"                   # N2: drops within the caps restate n; later stages assert it
RULING_GUARD_POST_SCORE = "withhold_and_flag"        # pending master: a guard hit after a score withholds + FLAGs
GUARD_FROM = "2026-01-01"            # no date on or after this may appear in an output unless allowlisted
GUARD_SEALED_FROM = "2026-05-27"     # the sealed window starts here (counted separately)
STAGE_READS = {  # junctioned subdirectories each stage reads (declared; the observed guard_read set is added)
    "controls": ("marine_water_contrast", "reanalysis", "training", "wunderground"),
    "build": ("marine_water_contrast", "reanalysis", "training", "wunderground"),
    "integrity": ("wunderground",),
    "labels": ("marine_water_contrast", "reanalysis", "training", "wunderground"),
    "look": ("wunderground",),
    "score": ("wunderground",),
}
# Section 6.3 / 8.4 frozen constants used to restate the MDE and the thresholds at the realised n (N2).
SIGMA_EFF = 0.016304 * (1.318 ** 0.5)
SIGMA_DEC = 0.0240
MDE_MULT = 3.340                      # z 2.498 + z80 0.842
Z80 = 0.842
FROZEN_TABLE_660 = {  # section 6.3 table at n = 660 / look 390: (MDE80, power, futility false-stop)
    "sigma_eff": (0.0026, 1.00, 0.001), "sigma_dec": (0.0033, 1.00, 0.010), "2x_sigma_eff": (0.0052, 0.88, 0.07),
    "3x_sigma_eff": (0.0078, 0.48, 0.16), "4x_sigma_eff": (0.0104, 0.25, 0.23)}

# ----------------------------------------------------------------------------- pinned roots (review R4)
OUT_ROOT_PIN = Path(r"C:\t\L59\row28\run")
MAIN_DATA_PIN = Path(r"C:\Users\Michael\Documents\github\weather\data")
JUNCTIONS = ("marine_water_contrast", "reanalysis", "training", "wunderground")

# ----------------------------------------------------------------------------- section 7 (inputs only)
S7_FIRST = date(2026, 1, 1)
S7_LAST = date(2026, 5, 26)                    # hard cap: anything later HALTs the reader
S7_V5_MD = ("05-06", "05-26")                  # V5.0 window; the same window in the V4 years
S7_V4_YEARS = (2023, 2024, 2025)
S7_REF_LAST = date(2026, 5, 5)                 # V4.3 within-year reference 2026-01-01..05-05 (descriptive)
S7_OBS_LOCAL = "07:00"                         # the last WU obs at or before 07:00 local on the date
S7_SMD_POOLED, S7_SMD_MARKET, S7_MARKETS_MAX = 0.25, 0.5, 3
S7_SD_RATIO = (0.8, 1.25)
L47B_CORPUS_SHA256 = "d59718a746a68d4745895623bae7760d99d95da647228fa3f8b7e389c8810acf"  # 2026 Jan-May 26 NBP 07Z


class Halt(RuntimeError):
    """A prereg HALT (scope "run" or "C") or a refused gate; the stage writes its report and stops."""

    def __init__(self, message, scope="run"):
        super().__init__(message)
        self.scope = scope


# ----------------------------------------------------------------------------- small helpers

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


_OBSERVED_READS = set()


def guard_read(path):
    """Refuse C:\\t\\l2\\p2 and anything that names a panel store. v3: records which junctioned subdirectory
    (if any) the path lies under (N1)."""
    p = Path(path).resolve()
    main = MAIN_DATA_PIN.resolve()
    if main in p.parents:
        _OBSERVED_READS.add(p.relative_to(main).parts[0])
    for root in FORBIDDEN_ROOTS:
        r = root.resolve()
        if p == r or r in p.parents:
            raise Halt(f"forbidden path (never open): {p}")
    if any("panel" in part.lower() for part in p.parts):
        raise Halt(f"forbidden path (panel store): {p}")
    return p


class Writer:
    """Every output goes under out_root; every file written is listed with its sha256.

    v3 (ruling 2): every Writer output is scanned by the output guard BEFORE it is written. Before a score
    exists a hit HALTs and nothing is written; once a look or final row exists (post_score, N1) a hit withholds
    that output (it is not written) and is recorded as a FLAG (RULING_GUARD_POST_SCORE)."""

    def __init__(self, out_root, stage_dir):
        self.out_root = Path(out_root).resolve()
        self.stage_dir = Path(stage_dir).resolve()
        self.written = []
        self.withheld = []
        self.post_score = False
        self.check(self.stage_dir)

    def _guard(self, name, data, obj=None):
        hits = guard_bytes(data)
        if obj is not None:
            hits += guard_obj(obj)
        if not hits:
            return True
        if self.post_score and RULING_GUARD_POST_SCORE == "withhold_and_flag":
            self.withheld.append({"name": name, "hits": dict(hits)})
            return False
        raise Halt(f"output guard: {sum(hits.values())} disallowed date string(s) in {name} {dict(hits)}; not written")

    def text(self, name, data):
        """Raw bytes (jsonl, csv) through the guard; returns the path, or None if withheld (post-score only)."""
        if not self._guard(name, data):
            return None
        p = self.path(name)
        p.write_bytes(data)
        self.note(p)
        return p

    def gz_json(self, name, obj):
        data = json_bytes(obj)
        if not self._guard(name, data):
            return None
        p = self.path(name)
        p.write_bytes(gzip.compress(data, mtime=0))
        self.note(p)
        return p

    def check(self, path):
        p = Path(path).resolve()
        if p != self.out_root and self.out_root not in p.parents:
            raise Halt(f"write outside out_root refused: {p}")
        return guard_read(p)

    def path(self, name):
        return self.check(self.stage_dir / name)

    def note(self, path):
        self.written.append(Path(path).resolve())

    def json(self, name, obj):
        data = json_bytes(obj)
        if not self._guard(name, data, obj):
            return None
        p = self.path(name)
        p.write_bytes(data)
        self.note(p)
        return p

    def pickle_gz(self, name, obj):
        data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        if not self._guard(name, data, obj):
            return None
        p = self.path(name)
        p.write_bytes(gzip.compress(data, mtime=0))
        self.note(p)
        return p


# ----------------------------------------------------------------------------- output guard (ruling 2)
# Every output and every log is scanned for ISO-extended date strings (YYYY-MM-DD, digit-bounded). A date on or
# after GUARD_FROM (2026-01-01) is a hit unless it is in the allowlist: the model's centre LABELS (calendar
# positions written with a nominal 2026 year, from pooled_residual_model's *CENTRES tuples) and section 7's own
# constants (2026-01-01, 2026-05-05, 2026-05-26; all <= 2026-05-26). Logs use NO allowlist (only the mask below). A hit is reported as
# a count per category and file; the matched text itself is never written anywhere.

_GUARD_PATTERN = r"(?<![0-9])(20[0-9]{2}-[01][0-9]-[0-3][0-9])(?![0-9])"
_GUARD_RS = re.compile(_GUARD_PATTERN)
_GUARD_RB = re.compile(_GUARD_PATTERN.encode("ascii"))
_GUARD_ALLOW = frozenset()
# The one masked token: this prereg's folder name (DOC_DIR) carries its own date; it is a path, never data. It is
# removed, as an exact token, before matching (logs included), so paths that name this folder do not trip the guard.
GUARD_MASK_TOKEN = DOC_DIR.rsplit("/", 1)[-1]


def guard_base_allowlist():
    return {S7_FIRST.isoformat(), S7_REF_LAST.isoformat(), S7_LAST.isoformat()}


def set_guard_allowlist(prm):
    global _GUARD_ALLOW
    allow = guard_base_allowlist()
    for name in dir(prm):
        if name.endswith("CENTRES"):
            allow.update(str(c) for c in getattr(prm, name))
    allow.add("2026-12-24")
    _GUARD_ALLOW = frozenset(allow)
    return sorted(_GUARD_ALLOW)


def _guard_count(day, allow, counter):
    if day < GUARD_FROM or day in allow:
        return
    counter["on_or_after_2026_05_27" if day >= GUARD_SEALED_FROM else "in_2026_before_05_27"] += 1


def guard_text(text, allow=None):
    allow = _GUARD_ALLOW if allow is None else allow
    c = Counter()
    text = text.replace(GUARD_MASK_TOKEN, "")
    for m in _GUARD_RS.finditer(text):
        _guard_count(m.group(1), allow, c)
    return c


def guard_bytes(data, allow=None):
    allow = _GUARD_ALLOW if allow is None else allow
    c = Counter()
    data = data.replace(GUARD_MASK_TOKEN.encode("ascii"), b"")
    for m in _GUARD_RB.finditer(data):
        _guard_count(m.group(1).decode("ascii"), allow, c)
    return c


def guard_obj(obj, allow=None):
    """Structural walk (dicts, sequences, DataFrames, Series, Index, ndarrays, dates, objects): catches dates that
    a byte scan of a pickle cannot see (datetime64 columns, concatenated string buffers)."""
    allow = _GUARD_ALLOW if allow is None else allow
    c = Counter()
    stack, seen = [obj], set()
    while stack:
        o = stack.pop()
        if o is None or isinstance(o, (bool, int, float, complex)):
            continue
        if isinstance(o, str):
            c += guard_text(o, allow)
            continue
        if isinstance(o, (bytes, bytearray)):
            c += guard_bytes(bytes(o), allow)
            continue
        if isinstance(o, (date, datetime)):
            c += guard_text(o.isoformat(), allow)
            continue
        if id(o) in seen:
            continue
        seen.add(id(o))
        if isinstance(o, dict):
            stack.extend(o.keys())
            stack.extend(o.values())
        elif isinstance(o, (list, tuple, set, frozenset)):
            stack.extend(o)
        elif hasattr(o, "columns") and hasattr(o, "index") and hasattr(o, "dtypes"):  # DataFrame
            stack.append([str(x) for x in o.columns])
            stack.append(o.index)
            for j in range(o.shape[1]):
                stack.append(o.iloc[:, j])
        elif hasattr(o, "dtype") and hasattr(o, "tolist"):  # Series, Index, ndarray, numpy scalar
            kind = getattr(o.dtype, "kind", "O")
            if kind in "biufc":
                continue
            if kind == "M":
                import numpy as np

                vals = np.asarray(o).astype("datetime64[D]").astype(str).ravel().tolist()
            else:
                vals = o.tolist()
            if isinstance(vals, list):
                try:
                    vals = list(set(vals))
                except TypeError:
                    pass
                stack.extend(vals)
            else:
                stack.append(vals)
        elif hasattr(o, "__dict__"):
            stack.append(vars(o))
        else:
            c += guard_text(repr(o), allow)
    return c


def guard_file(path, allow=None):
    """Counts for one output file: raw bytes (decompressed if .gz) and, for a pickle, the structural walk."""
    name = Path(path).name.lower()
    data = Path(path).read_bytes()
    c = Counter()
    if name.endswith(".gz"):
        try:
            data = gzip.decompress(data)
        except Exception:
            c["unscannable"] += 1
            return c
    c += guard_bytes(data, allow)
    if name.endswith((".pkl.gz", ".pkl", ".pickle")):
        try:
            c += guard_obj(pickle.loads(data), allow)
        except Exception:
            c["unscannable"] += 1
    return c


class GuardedStream:
    """sys.stdout / sys.stderr wrapper (ruling 2, logs): a write holding any date >= 2026-01-01 (no allowlist)
    is withheld and only counted; the launcher re-scans the captured files after the child exits."""

    def __init__(self, inner):
        self.inner = inner
        self.withheld = 0

    def write(self, text):
        if guard_text(str(text), allow=frozenset()):
            self.withheld += 1
            text = "[output guard: one write withheld]\n"
        return self.inner.write(text)

    def flush(self):
        return self.inner.flush()

    def __getattr__(self, name):
        return getattr(self.inner, name)


def out_root_snapshot():
    snap = {}
    if OUT_ROOT_PIN.exists():
        for dirpath, _, filenames in os.walk(OUT_ROOT_PIN):
            for name in filenames:
                p = os.path.join(dirpath, name)
                st = os.stat(p)
                snap[os.path.normcase(p)] = (st.st_size, st.st_mtime_ns)
    return snap


def output_guard_scan(snapshot, exclude):
    """Stage end: every file under the run root that is new or changed since the stage started (the launcher's
    walker.stdout / walker.stderr / receipt.json and this stage's walk.json / walk.csv are excluded: the
    launcher scans its logs after exit, and the report is guarded as an object before it is written)."""
    exclude = {os.path.normcase(str(p)) for p in exclude}
    scanned, hits = 0, {}
    for dirpath, _, filenames in os.walk(OUT_ROOT_PIN):
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            key = os.path.normcase(p)
            if key in exclude:
                continue
            st = os.stat(p)
            if snapshot.get(key) == (st.st_size, st.st_mtime_ns):
                continue
            scanned += 1
            c = guard_file(p)
            rel = os.path.relpath(p, OUT_ROOT_PIN)
            if guard_text(rel):
                c["file_name"] += 1
                rel = "[name withheld by output guard]"
            if c:
                hits[rel] = hits.get(rel, Counter()) + c
    return {"files_scanned": scanned, "files_with_hits": {k: dict(v) for k, v in hits.items()},
            "hits_total": sum(sum(v.values()) for v in hits.values())}


def json_bytes(obj):
    return (json.dumps(obj, indent=1, sort_keys=True, default=_json_default) + "\n").encode("utf-8")


def _json_default(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not serialisable: {type(value)}")


def load_pickle_gz(path):
    with gzip.open(guard_read(path), "rb") as handle:
        return pickle.load(handle)


def read_json(path):
    return json.loads(Path(guard_read(path)).read_text(encoding="utf-8"))


def iso(d):
    return d if isinstance(d, str) else d.isoformat()


def as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def season_year(value):
    d = as_date(value)
    return d.year + 1 if (d.month == 12 and d.day >= 17) else d.year


def in_dec_may(value):
    d = as_date(value)
    return d.month <= 5 or (d.month == 12 and d.day >= 17)


def in_aug_sep(value):
    d = as_date(value)
    return (d.month == 8) or (d.month == 9 and d.day <= 29)


def now():
    """Real local time, ISO 8601 BASIC format (e.g. 20261103T041500.123456-0500): it is not a YYYY-MM-DD string,
    so it never trips the output guard."""
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S.%f%z")


# ----------------------------------------------------------------------------- context

def _is_reparse_point(path):
    return bool(getattr(os.lstat(path), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def check_junctions(repo):
    """Review R4(c): the worktree's data\\ holds exactly the four approved junctions, each resolving to the
    matching main-checkout subdirectory, and nothing else; DATA_ROOT is that data\\."""
    data = repo / "data"
    if _is_reparse_point(data):
        raise Halt(f"{data} itself is a link; only its four subdirectories may be junctions")
    names = sorted(p.name for p in data.iterdir())
    if names != sorted(JUNCTIONS):
        raise Halt(f"{data} holds {names}, not exactly the approved junctions {sorted(JUNCTIONS)}")
    out = {}
    for sub in JUNCTIONS:
        link = data / sub
        target = (MAIN_DATA_PIN / sub).resolve()
        if not _is_reparse_point(link) or link.resolve() != target:
            raise Halt(f"{link} is not a junction to {target}")
        out[sub] = str(target)
    return out


def check_write_roots(cfg):
    """Review R4(a): out_root is pinned; every configured write root lies under it."""
    if Path(cfg["out_root"]).resolve() != OUT_ROOT_PIN.resolve():
        raise Halt(f"out_root {cfg['out_root']} is not the pinned {OUT_ROOT_PIN}")
    if Path(cfg["main_data"]).resolve() != MAIN_DATA_PIN.resolve():
        raise Halt(f"main_data {cfg['main_data']} is not the pinned {MAIN_DATA_PIN}")
    rec = Path(cfg["records_root"]).resolve()
    if OUT_ROOT_PIN.resolve() not in rec.parents:
        raise Halt(f"records_root {rec} is not under {OUT_ROOT_PIN}")


def junction_manifest():
    """Review R4(d): metadata only of every file under the four junctioned subdirectories. No file is opened:
    hashing contents would read sealed and embargoed dates' bytes. v3 (N6): each row is [subdirectory,
    sha256 of the path relative to main data, size, mtime_ns], so no dated path NAME appears in any output."""
    rows = []
    for sub in JUNCTIONS:
        for dirpath, dirnames, filenames in os.walk(MAIN_DATA_PIN / sub):
            dirnames.sort()
            for name in sorted(filenames):
                p = os.path.join(dirpath, name)
                st = os.stat(p)
                key = sha256_bytes(os.path.relpath(p, MAIN_DATA_PIN).encode("utf-8"))
                rows.append([sub, key, int(st.st_size), int(st.st_mtime_ns)])
    rows.sort()
    return rows


def manifest_diff(before, after):
    """N1: classify every differing entry per subdirectory as added, removed, size_changed or mtime_only."""
    b = {(r[0], r[1]): (r[2], r[3]) for r in before}
    a = {(r[0], r[1]): (r[2], r[3]) for r in after}
    by_sub = {sub: Counter() for sub in JUNCTIONS}
    keys = defaultdict(list)
    for k in sorted(set(a) | set(b)):
        if k not in b:
            kind = "added"
        elif k not in a:
            kind = "removed"
        elif a[k][0] != b[k][0]:
            kind = "size_changed"
        elif a[k][1] != b[k][1]:
            kind = "mtime_only"
        else:
            continue
        by_sub[k[0]][kind] += 1
        keys[kind].append([k[0], k[1]])
    count = sum(sum(v.values()) for v in by_sub.values())
    return {"changed": count > 0, "count": count, "by_subdir": {s: dict(v) for s, v in by_sub.items()},
            "hashed_keys": dict(keys)}


def load_context(cfg):
    repo = Path(cfg["repo"]).resolve()
    check_write_roots(cfg)
    for key in ("repo", "main_data", "out_root", "records_root", "spc_module", "pit_corpora", "fetch_dir",
                "l9_corpus", "l48_corpus_root", "rp2_classes", "stations_meta", "ra_rows", "l2_records",
                "l47b_corpus_2026"):
        guard_read(cfg[key])
    if sha256_file(repo / DOC_DIR / "prereg_row28.md") != PREREG_SHA256:
        raise Halt("prereg_row28.md sha256 differs from the frozen cb6d4e8d")
    if sha256_file(repo / DOC_DIR / "FREEZE_RECORD.md") != FREEZE_RECORD_SHA256:
        raise Halt("FREEZE_RECORD.md sha256 differs")
    for rel, sha in MODULE_SHA256.items():
        if sha256_file(repo / rel) != sha:
            raise Halt(f"bound module {rel} differs from its pinned sha256")
    sys.path.insert(0, str(repo / "src"))
    from weather import paths

    # extract_market reads data/ under the importing checkout (wunderground, marine_water_contrast, reanalysis;
    # the PIT corpora by explicit manifest path under training): the four approved junctions to main data.
    if Path(paths.DATA_ROOT) != repo / "data":
        raise Halt(f"DATA_ROOT {paths.DATA_ROOT} is not {repo / 'data'}")
    junctions = check_junctions(repo)
    if OUT_ROOT_PIN.resolve() in Path(paths.DATA_ROOT).resolve().parents or \
            Path(paths.DATA_ROOT).resolve() in OUT_ROOT_PIN.resolve().parents:
        raise Halt("the run root and DATA_ROOT overlap")
    from weather.calibration import feature_model as fm
    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import pooled_residual_model as prm
    from weather.market.market_registry import spec_for_id

    if sha256_file(cfg["spc_module"]) != SPC_SHA256:
        raise Halt("R-P2 station_pool_corpus copy differs from d4947cfe")
    spec = importlib.util.spec_from_file_location("row28_station_pool_corpus", cfg["spc_module"])
    spc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(spc)
    tz = {m: spec_for_id(m).timezone for m in prm.R0_MARKETS}
    icao = {m: spec_for_id(m).icao for m in prm.R0_MARKETS}
    centres = {
        "A": tuple(prm.FORWARD_CENTRES) + tuple(prm.JAN_JUL_CENTRES) + ("2026-12-24",),
        "B": tuple(prm.JAN_JUL_CENTRES[:10]) + ("2026-12-24",),
    }
    centres["C"] = centres["D"] = centres["A"]
    if len(centres["A"]) != 24 or len(centres["B"]) != 11:
        raise Halt("centre sets differ from section 3.2")
    if set(US10) | set(DESCRIPTIVE_MARKETS) != set(prm.R0_MARKETS):
        raise Halt("market set differs from R0_MARKETS")
    return SimpleNamespace(cfg=cfg, repo=repo, prm=prm, fm=fm, l9=l9, spc=spc, tz=tz, icao=icao, centres=centres,
                           junctions=junctions)


def centre_for(ctx, target_date, arm):
    """Section 3.2: bound nearest_centre on the arm's set; Rule L sends Feb 29 to the same year's Feb 28."""
    d = as_date(target_date)
    if d.month == 2 and d.day == 29:
        d = d.replace(day=28)
    return ctx.prm.nearest_centre(d.isoformat(), ctx.centres[arm])


def circular_picks(target_date, centres):
    d = as_date(target_date)
    if d.month == 2 and d.day == 29:
        d = d.replace(day=28)
    ref = date(2001, d.month, d.day)

    def dist(c):
        k = abs((date(2001, int(c[5:7]), int(c[8:10])) - ref).days)
        return min(k, 365 - k)

    best = min(dist(c) for c in centres)
    return {c for c in centres if dist(c) == best}


def manifests_for(ctx, centre):
    root = Path(ctx.cfg["pit_corpora"])
    return [str(guard_read(root / cid / "manifest.json")) for cid in SEASON_CORPORA[ctx.prm.season_of(centre)]]


def all_manifests(ctx):
    return sorted(glob.glob(os.path.join(ctx.cfg["pit_corpora"], "*", "manifest.json")))


def covered(ctx, centre):
    years = ctx.prm.covered_years(centre, manifests_for(ctx, centre))
    if any(int(y) > DEV_LAST.year for y in years):
        raise Halt(f"centre {centre}: a covered year is after 2025 ({years})")
    return [int(y) for y in years]


def verify_prev(cfg, name, expect_status=("PASS",)):
    prev = cfg["prev"][name]
    path = guard_read(prev["path"])
    if sha256_file(path) != prev["sha256"]:
        raise Halt(f"previous-stage report {name} sha256 differs from the RUN_LOG value")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") not in expect_status:
        raise Halt(f"previous stage {name} status {report.get('status')} is not {expect_status}")
    return report, Path(path).parent


def verify_committed_gate(ctx, commit, rel_path, run_file):
    """Order (b): the gate file is committed on the pushed branch and equals the run file byte for byte."""
    repo = str(ctx.repo)

    def git(*args):
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, check=False)

    if git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        raise Halt(f"gate commit {commit} is not in the repository")
    if git("merge-base", "--is-ancestor", commit, f"origin/{BRANCH}").returncode != 0:
        raise Halt(f"gate commit {commit} is not on origin/{BRANCH} (commit and push it first)")
    blob = git("show", f"{commit}:{rel_path}")
    if blob.returncode != 0:
        raise Halt(f"{rel_path} is absent at {commit}")
    if sha256_bytes(blob.stdout) != sha256_file(run_file):
        raise Halt(f"committed {rel_path} at {commit} differs from the run file {run_file}")
    return {"commit": commit, "path": rel_path, "sha256": sha256_bytes(blob.stdout)}


def deciding_dates(ctx):
    path = ctx.repo / DOC_DIR / "deciding_dates_r4.txt"
    if sha256_file(path) != DECIDING_LF_SHA256:
        raise Halt("deciding_dates_r4.txt sha256 differs from a2f601ba")
    days = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    folds = Counter(season_year(d) for d in days)
    if len(days) != N_DECIDING or dict(folds) != FOLD_DATES or sum(folds[y] for y in LOOK_FOLDS) != N_LOOK:
        raise Halt("deciding dates differ from section 1.1 (n, folds or look)")
    if any(as_date(d) > DEV_LAST for d in days):
        raise Halt("a deciding date is after 2025")
    return days


# ----------------------------------------------------------------------------- frames and NBM

def frame_diff(a, b, keys, tol):
    """Key-aligned, NaN-aware comparison of two frames; reports counts and maxima only (no values)."""
    import numpy as np

    a = a.sort_values(keys).reset_index(drop=True)
    b = b.sort_values(keys).reset_index(drop=True)
    out = {"rows": [int(len(a)), int(len(b))], "columns_only_left": sorted(set(a.columns) - set(b.columns)),
           "columns_only_right": sorted(set(b.columns) - set(a.columns))}
    same_keys = len(a) == len(b) and all((a[k].astype(str).to_numpy() == b[k].astype(str).to_numpy()).all()
                                         for k in keys)
    out["identical_keys"] = bool(same_keys)
    worst = {}
    if same_keys:
        for col in sorted(set(a.columns) & set(b.columns)):
            x, y = a[col], b[col]
            if x.dtype.kind in "fiub" and y.dtype.kind in "fiub":
                xv, yv = x.to_numpy(float), y.to_numpy(float)
                both_nan = np.isnan(xv) & np.isnan(yv)
                one_nan = np.isnan(xv) ^ np.isnan(yv)
                diff = np.where(both_nan, 0.0, np.abs(xv - yv))
                worst[col] = float("inf") if one_nan.any() else float(np.nanmax(diff)) if len(diff) else 0.0
            else:
                worst[col] = 0.0 if (x.astype(str).to_numpy() == y.astype(str).to_numpy()).all() else float("inf")
    out["max_abs_diff"] = worst
    out["pass"] = bool(same_keys and not out["columns_only_left"] and not out["columns_only_right"]
                       and all(v <= tol for v in worst.values()))
    return out


def _label_present(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def blank_labels(payload):
    """y-free copy in place, right after unpickling (R6): final_bucket becomes a PRESENCE marker only,
    0.0 if a label is present and NaN if not. No label value survives."""
    for recs in payload["records"].values():
        for rec in recs:
            rec["final_bucket"] = 0.0 if _label_present(rec.get("final_bucket")) else float("nan")
    return payload


def market_frame(ctx, files, with_labels):
    """pooled_frame over the given record files, reduced to the serve-parity inputs (forward_training_frame)."""
    prm = ctx.prm
    payloads, meta = [], []
    for path in files:
        payload = prm.load_records(Path(path).parent, *Path(path).name[len("records_"):-len(".pkl.gz")].rsplit("_", 1))
        if not with_labels:
            blank_labels(payload)
        payloads.append(payload)
        meta.append({"market": payload["market"], "centre": payload["centre"], "file": Path(path).name,
                     "bucket_space": [int(b) for b in payload["bucket_space"]]})
    frame, _ = prm.pooled_frame(payloads, prm.station_coordinates(prm.R0_MARKETS))
    del payloads
    drop = [c for c in frame.columns if c.startswith("x_") and c not in prm.DEV_KEEP_X]
    frame = frame.drop(columns=drop)
    for col in prm.DEV_KEEP_X:
        if col not in frame.columns:
            raise Halt(f"{col} is not a common record feature")
    frame = frame.rename(columns={"centre": "payload_centre"}).drop(columns=["season"])
    if not with_labels:
        if not set(frame["y"].dropna().unique()) <= {0.0}:
            raise Halt("y-free frame holds a label value")
        frame["y_present"] = frame["y"].notna()
        frame = frame.drop(columns=["y"])
    return frame, meta


def write_filtered_blocks(writer, src, name, months):
    """A copy of a blocks file restricted to the given months (gap blocks: Jun 1 - Jul 31 only, section 3.3b)."""
    out = writer.path(name)
    kept = 0
    with open(guard_read(src), encoding="utf-8") as fin, open(out, "w", encoding="utf-8", newline="\n") as fout:
        for line in fin:
            if not line.strip():
                continue
            rec = json.loads(line)
            if as_date(rec["utc_date"]) > DEV_LAST:
                raise Halt(f"block after 2025 in {src}")
            if as_date(rec["utc_date"]).month in months:
                fout.write(line.rstrip("\r\n") + "\n")
                kept += 1
    writer.note(out)
    return out, kept


def nbm_rows_index(path, cycle="07"):
    """{(market, date): (last_modified, mean, sd)} for one cycle of an L9-format NBM rows file."""
    out = {}
    with open(guard_read(path), encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            if r.get("cycle") != cycle or not r.get("available") or r.get("mean") is None:
                continue
            if as_date(r["target_date"]) > DEV_LAST:
                raise Halt(f"NBM row after 2025 in {path}")
            lm = datetime.fromisoformat(r["last_modified"].replace("Z", "+00:00"))
            out[(r["market_id"], r["target_date"])] = (lm, float(r["mean"]), r.get("sd"))
    return out


def merged_table(ctx, paths):
    """load_nbm over several L9-format files; no (market, date, cycle) may appear twice (section 3.3b)."""
    table = defaultdict(list)
    seen = set()
    for path in paths:
        part = ctx.l9.load_nbm(guard_read(path))
        for key, entries in part.items():
            if as_date(key[1]) > DEV_LAST:
                raise Halt(f"NBM entry after 2025: {key}")
            for entry in entries:
                k = (key[0], key[1], entry[0])
                if k in seen:
                    raise Halt(f"duplicate NBM (market, date, cycle) {k}")
                seen.add(k)
                table[key].append(entry)
    return table


def fetch_file(ctx, key):
    rel, manifest_name = BLOCK_FILES[key]
    fetch = Path(ctx.cfg["fetch_dir"])
    manifest = verify_fetch_manifest(ctx, manifest_name)
    entry = manifest["files"][rel]
    path = guard_read(fetch / rel)
    if sha256_file(path) != entry["sha256"]:
        raise Halt(f"{rel} sha256 differs from {manifest_name}")
    return path


def verify_fetch_manifest(ctx, name):
    path = guard_read(Path(ctx.cfg["fetch_dir"]) / name)
    if sha256_file(path) != FETCH_MANIFEST_SHA256[name]:
        raise Halt(f"{name} sha256 differs from the freeze record")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_iem_files(ctx):
    """Every row-28 IEM file against its manifest's file list (sha256 per file)."""
    fetch = Path(ctx.cfg["fetch_dir"])
    n = 0
    for rel, manifest_name in IEM_LISTS:
        manifest = verify_fetch_manifest(ctx, manifest_name)
        listing = guard_read(fetch / rel)
        if sha256_file(listing) != manifest["files_list_sha256"]:
            raise Halt(f"{rel} sha256 differs from {manifest_name} files_list_sha256")
        for line in listing.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            if sha256_file(guard_read(fetch / parts[0])) != parts[-1].strip():
                raise Halt(f"IEM file {parts[0]} differs from its listed sha256")
            n += 1
    return n


def verify_l48_raw(ctx, pool):
    root = Path(ctx.cfg["l48_corpus_root"])
    receipts = guard_read(root / "receipts_iem.jsonl")
    if sha256_file(receipts) != L48_RECEIPTS_SHA256:
        raise Halt("L48 receipts_iem.jsonl differs from the a57e10a6 manifest")
    want = {icao.lower() for icao in pool}
    n = 0
    for line in receipts.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        p = Path(r["file"])
        if p.parts[-3].lower() not in want or not p.exists():
            continue
        if sha256_file(guard_read(p)) != r["sha256"]:
            raise Halt(f"L48 raw file {p} differs from its receipt")
        n += 1
    return n


def merge_iem(src_station_dir, dst_station_dir):
    """Merge one station's season/gap CSVs per report type, dropping exact duplicate lines (window overlaps)."""
    counts = {}
    for kind in ("routine", "special"):
        seen, out, header = set(), defaultdict(list), None
        for tag in ("season", "gap"):
            for year in FOLDS:
                src = Path(src_station_dir) / kind / f"{tag}{year}.csv"
                if not src.exists():
                    continue
                lines = guard_read(src).read_text(encoding="utf-8").splitlines()
                if not lines:
                    continue
                if header is None:
                    header = lines[0]
                elif lines[0] != header:
                    raise Halt(f"IEM header differs in {src}")
                for line in lines[1:]:
                    if line and line not in seen:
                        seen.add(line)
                        out[year].append(line)
        dst = Path(dst_station_dir) / kind
        dst.mkdir(parents=True, exist_ok=True)
        for year, lines in out.items():
            (dst / f"{year}.csv").write_bytes((header + "\n" + "\n".join(lines) + "\n").encode("utf-8"))
        counts[kind] = sum(len(v) for v in out.values())
    return counts


def daily_prefix_re(i_date):
    """Raw-line shape: exactly i_date unquoted fields, then the YYYY-MM-DD local_date field (wu_history.py
    write_daily_summary 450-486: csv.DictWriter, local_date the 2nd field after schema_version)."""
    return re.compile(rb"\A(?:[^,\"\r\n]*,){%d}([0-9]{4}-[0-9]{2}-[0-9]{2})," % i_date)


def wu_daily(ctx, market, with_high):
    """{local_date: row_count} (and the WU high when with_high) for dates <= 2025-12-31 only.

    v3 (ruling 2, N4): the file is read in binary, line by line. The header gives the local_date position; each
    data line's date is tested on its raw prefix BEFORE any split or decode, and a line dated after 2025-12-31 is
    skipped (counted only). Only kept lines are decoded and csv-split. The sha256 returned is over the header
    and the kept lines only (raw bytes as read), never over the whole file."""
    data = Path(ctx.cfg["main_data"])
    path = guard_read(data / "wunderground" / ctx.icao[market].lower() / "daily" / "daily_summary.csv")
    return wu_daily_file(path, with_high)


def wu_daily_file(path, with_high):
    out = {}
    h = hashlib.sha256()
    skipped = 0
    cap = DEV_LAST.isoformat().encode("ascii")
    with open(path, "rb") as handle:
        head = handle.readline()
        h.update(head)
        header = next(csv.reader([head.decode("utf-8")]))
        i_date, i_rows = header.index("local_date"), header.index("row_count")
        i_high = header.index("max_temp_bucket_native") if with_high else None
        shape = daily_prefix_re(i_date)
        for raw in handle:
            if not raw.strip():
                continue
            m = shape.match(raw)
            if m is None:
                raise Halt(f"daily_summary line without the local_date prefix shape in {path}")
            if m.group(1) > cap:
                skipped += 1
                continue
            h.update(raw)
            row = next(csv.reader([raw.decode("utf-8")]))
            day = row[i_date]
            rows = int(float(row[i_rows])) if row[i_rows] else 0
            if with_high:
                try:
                    high = float(row[i_high])
                except (TypeError, ValueError):
                    high = None
                out[day] = (rows, high)
            else:
                out[day] = rows
    return out, {"kept_lines_sha256": h.hexdigest(), "kept_lines": len(out), "skipped_after_2025": skipped,
                 "basis": "sha256 over the header line and the kept (<= 2025-12-31) raw lines, as read"}


def wu_min_rows():
    from weather.backtesting.settlement_io import COMPLETE_DAY_MIN_ROWS

    if COMPLETE_DAY_MIN_ROWS != 18:
        raise Halt("COMPLETE_DAY_MIN_ROWS is not 18 (section 5)")
    return COMPLETE_DAY_MIN_ROWS


# ----------------------------------------------------------------------------- the arm path

def fit_and_score(ctx, train, val, buckets, shifts=None, top_gte=False):
    """P3d_N_fix fit on ``train`` and per-row scores of ``val`` (R-P2 ``_score_arm`` form, extended).

    ``shifts`` maps a row key to arm D's K112 shift; D shares A's fit and scale and moves only the mean.
    ``top_gte`` (scored rows only, RULING_R9): y above the top bucket K scores as K. Controls keep the bound form.
    Returns {(market, date, hour): {"brier", "log", "yhat", "s", "y_gt_top"[, "D_brier", "D_log", "D_shift"]}}.
    """
    import numpy as np

    prm, fm = ctx.prm, ctx.fm
    fitted = prm.fit_pooled(train, market_id=False, doy=True, raw_columns=False, bias_by="season")
    out = {}
    for market in sorted(val["market"].unique()):
        part = val[val["market"] == market].reset_index(drop=True)
        yhat, X = fitted["mean"].predict(part)
        gap = np.nan_to_num(yhat - part["F"].to_numpy(float), nan=0.0)
        s = np.maximum(prm.MIN_SCALE, fitted["scale"].predict(np.column_stack([X, gap])) * math.sqrt(math.pi / 2))
        train_y = [int(v) for v in train.loc[train["market"] == market, "y"]]
        p_clim = fm.smoothed_dist(train_y, buckets[market], alpha=0.10)
        for i in range(len(part)):
            key = (market, str(part.at[i, "target_date"])[:10], int(part.at[i, "hour"]))
            floor = float(part["F"].iat[i])
            dist = prm.predictive_distribution(float(yhat[i]), float(s[i]), floor, fitted["z"], buckets[market], p_clim)
            actual = int(part.at[i, "y"])
            top = max(buckets[market])
            y_gt_top = actual > top
            if top_gte and RULING_R9_TOP_BUCKET_GTE:
                actual = min(actual, top)
            row = {"brier": fm.brier_score(dist, actual), "log": fm.log_loss(dist, actual),
                   "yhat": float(yhat[i]), "s": float(s[i]), "y_gt_top": bool(y_gt_top)}
            if shifts is not None:
                shift = float(shifts.get(key, 0.0))
                dist_d = prm.predictive_distribution(float(yhat[i]) - shift, float(s[i]), floor, fitted["z"],
                                                     buckets[market], p_clim)
                row.update({"D_brier": fm.brier_score(dist_d, actual), "D_log": fm.log_loss(dist_d, actual),
                            "D_shift": shift})
            out[key] = row
    return out


def with_arm_centres(ctx, frame, arm):
    out = frame.copy()
    out["centre"] = [centre_for(ctx, d, arm) for d in out["target_date"]]
    out["season"] = [ctx.prm.season_of(c) for c in out["centre"]]
    return out


def arm_training(frame, arm, hour, fold):
    days = frame["target_date"].astype(str)
    mask = (frame["hour"] == hour) & (frame["sy"] != fold) & (days <= LAST_TRAIN.isoformat())
    if arm == "B":
        mask &= days.map(in_dec_may)
    return frame[mask].reset_index(drop=True)


def arm_buckets(payload_buckets, train):
    """Section 3.6: union of contributing payloads' bucket_space plus [min, max] of the fold's training labels."""
    out = {}
    for market, part in train.groupby("market"):
        space = set()
        for centre in part["payload_centre"].unique():
            space |= set(payload_buckets[(market, centre)])
        ys = part["y"].to_numpy(float)
        space |= set(range(int(ys.min()), int(ys.max()) + 1))
        out[market] = sorted(space)
    return out


# ----------------------------------------------------------------------------- statistics (section 6.1)

PHI = NormalDist().cdf


def contrast_stats(series):
    """series: {date: d}. Point, SD, rho (row-109 formula on calendar-adjacent same-season-year pairs),
    kappa (AR floor 1.318), kappa_block3, kappa_wide, SEs, CIs, p, realised power (section 8.4)."""
    dates = sorted(series)
    n = len(dates)
    if n < 3:
        return {"n": n, "degenerate": True}
    xs = [series[d] for d in dates]
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    pairs = [(series[a], series[b]) for a, b in zip(dates, dates[1:])
             if (as_date(b) - as_date(a)).days == 1 and season_year(a) == season_year(b)]
    u = [p[0] - mean for p in pairs]
    v = [p[1] - mean for p in pairs]
    den = math.sqrt(sum(i * i for i in u) * sum(j * j for j in v))
    rho = sum(i * j for i, j in zip(u, v)) / den if den > 0 else 0.0
    kappa_ar = (1 + rho) / (1 - rho) if rho < 1 else float("inf")
    kappa = max(kappa_ar, KAPPA_FLOOR)
    blocks = []
    by_sy = defaultdict(list)
    for d in dates:
        by_sy[season_year(d)].append(series[d])
    for vals in by_sy.values():
        for i in range(0, len(vals), 3):
            chunk = vals[i:i + 3]
            blocks.append((sum(chunk) / len(chunk), len(chunk)))
    wsum = sum(w for _, w in blocks)
    mbar = sum(m * w for m, w in blocks) / wsum
    var_w = sum(w * (m - mbar) ** 2 for m, w in blocks) / wsum
    se2_block = var_w / len(blocks)
    se2_iid = sd * sd / n
    kappa_b3 = se2_block / se2_iid if se2_iid > 0 else float("inf")
    kappa_wide = max(kappa, kappa_b3)
    se = sd * math.sqrt(kappa / n)
    se_wide = sd * math.sqrt(kappa_wide / n)
    z = mean / se if se > 0 else float("inf")
    p = 2.0 * (1.0 - PHI(abs(z)))
    se_power = INFLATION * se_wide
    return {
        "n": n, "point": mean, "sd": sd, "rho": rho, "pairs": len(pairs), "kappa_ar": kappa_ar, "kappa": kappa,
        "kappa_block3": kappa_b3, "blocks": len(blocks), "kappa_wide": kappa_wide, "se": se, "se_wide": se_wide,
        "z": z, "p": p, "ci95": [mean - 1.96 * se, mean + 1.96 * se],
        "ci95_wide": [mean - 1.96 * se_wide, mean + 1.96 * se_wide],
        "se_wide_x1.07": se_power, "sigma_hat": sd * math.sqrt(kappa), "sigma_hat_wide": sd * math.sqrt(kappa_wide),
        "power_xs": PHI(EDGE / se_power - Z_HOLM_WORST) if se_power > 0 else 1.0,
        "power_xa": PHI(EDGE / se_power - Z_XA) if se_power > 0 else 1.0,
    }


def daily_contrast(rows, left, right, markets=US10):
    """d(t): per-date mean over the given markets' rows (hours 13-16) of left - right."""
    acc = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r["market"] in markets and r.get(left) is not None and r.get(right) is not None:
            a = acc[r["date"]]
            a[0] += r[left] - r[right]
            a[1] += 1
    return {d: s / k for d, (s, k) in acc.items()}


def fold_means(series):
    acc = defaultdict(list)
    for d, v in series.items():
        acc[season_year(d)].append(v)
    return {y: sum(v) / len(v) for y, v in sorted(acc.items())}


def contrast_block(rows, left, right):
    pooled = contrast_stats(daily_contrast(rows, left, right))
    per_market = {m: contrast_stats(daily_contrast(rows, left, right, markets=(m,))) for m in US10}
    folds = fold_means(daily_contrast(rows, left, right))
    return {"pooled": pooled, "per_market": per_market, "folds": folds,
            "folds_positive": sum(1 for v in folds.values() if v > 0)}


def holm(pvalues, alpha=0.05):
    order = sorted(pvalues, key=lambda a: (pvalues[a], a))
    passed, k = {}, len(order)
    still = True
    for i, arm in enumerate(order):
        threshold = alpha / (k - i)
        ok = still and pvalues[arm] <= threshold
        passed[arm] = {"p": pvalues[arm], "threshold": threshold, "rejected": ok}
        still = ok
    return passed


# ----------------------------------------------------------------------------- stage 1: controls

def stage_controls(ctx, cfg, w):
    prm, spc = ctx.prm, ctx.spc
    records = w.check(cfg["records_root"])
    if records.exists() and any(records.iterdir()):
        raise Halt(f"records root {records} is not empty at the controls stage")
    report = {"started": now()}
    # Coverage per centre: the season corpus set must cover exactly what all corpora cover (the deciding list's
    # basis, scripts/row28_deciding_dates_r4.py), so the build reaches every deciding window.
    every = all_manifests(ctx)
    cov = {}
    for centre in ctx.centres["A"]:
        mine, alls = covered(ctx, centre), [int(y) for y in prm.covered_years(centre, every)]
        if mine != alls:
            raise Halt(f"centre {centre}: season corpora cover {mine}, all corpora {alls}")
        cov[centre] = mine
    report["covered_years"] = cov

    from weather.sources.forecast_training_corpus import CorpusVerificationError

    def extract(centres):
        out, failed = {}, []
        for centre in centres:
            years = cov[centre]
            for market in prm.R0_MARKETS:
                try:
                    path, info = prm.extract_market(market, centre, manifests_for(ctx, centre), records,
                                                    training_years=years)
                except CorpusVerificationError as exc:
                    failed.append([market, centre, str(exc)])
                    continue
                w.note(path)
                out[path.name] = sha256_file(path)
        return out, failed

    # C-0: the row-28 build call on the R-A centres, then R-A's LOYO reproduced to 1e-9 (section 3.5).
    shas, failed = extract(prm.AUG_SEP_CENTRES)
    if failed:
        raise Halt(f"C-0 extraction failed closed: {failed}")
    if sha256_file(cfg["ra_rows"]) != RA_ROWS_SHA256:
        raise Halt("R-A loyo_rows.jsonl sha256 differs")
    base, buckets, base_stats, records_frame = spc.base_frame(records, guard_read(cfg["l9_corpus"]))
    mine = {}
    for hour in prm.WINDOW_HOURS:
        at_hour = base[base["hour"] == hour]
        for year in sorted(at_hour["year"].unique()):
            train = at_hour[at_hour["year"] != year].reset_index(drop=True)
            val = at_hour[at_hour["year"] == year].reset_index(drop=True)
            for (m, d, h), r in fit_and_score(ctx, train, val, buckets).items():
                mine[(h, m, d)] = r
            print(f"C-0 h{hour:02d} held {year} done", flush=True)
    ra = {}
    with open(guard_read(cfg["ra_rows"]), encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            ra[(r["hour"], r["market"], r["date"])] = (r["P3d_N_fix_brier"], r["P3d_N_fix_log"])
    same = set(ra) == set(mine)
    worst_b = max((abs(mine[k]["brier"] - ra[k][0]) for k in mine if k in ra), default=float("inf"))
    worst_l = max((abs(mine[k]["log"] - ra[k][1]) for k in mine if k in ra), default=float("inf"))
    report["C_0"] = {"ra_rows": len(ra), "rows": len(mine), "identical_keys": same, "max_abs_diff_brier": worst_b,
                     "max_abs_diff_log": worst_l, "base_train_nbm": base_stats,
                     "pass": same and len(ra) == RA_ROWS_N and worst_b <= CONTROL_TOL and worst_l <= CONTROL_TOL}
    l2 = Path(cfg["l2_records"])

    def centre_files(root, centre):
        return [guard_read(prm.records_path(root, m, centre)) for m in prm.R0_MARKETS]

    keys = ["market", "payload_centre", "hour", "target_date"]
    a_mine, _ = market_frame(ctx, [f for c in prm.AUG_SEP_CENTRES for f in centre_files(records, c)], True)
    a_l2, _ = market_frame(ctx, [f for c in prm.AUG_SEP_CENTRES for f in centre_files(l2, c)], True)
    report["C_0"]["records_vs_l2_descriptive"] = frame_diff(a_mine, a_l2, keys, CONTROL_TOL)
    del a_mine, a_l2
    if not report["C_0"]["pass"]:
        raise Halt(f"C-0 failed: {report['C_0']}")

    # C-0b: 12-09 and 01-08 rebuilt by the same call reproduce C:\t\l2\records (y, F, fh, every x_*), 1e-9.
    shas_b, failed_b = extract(("2026-12-09", "2026-01-08"))
    if failed_b:
        raise Halt(f"C-0b extraction failed closed: {failed_b}")
    shas.update(shas_b)
    report["C_0b"] = {}
    for centre in ("2026-12-09", "2026-01-08"):
        # Full pooled_frame on each side (all x_* columns kept), compared per centre; counts only are reported.
        payload_mine = [prm.load_records(records, m, centre) for m in prm.R0_MARKETS]
        payload_l2 = [prm.load_records(l2, m, centre) for m in prm.R0_MARKETS]
        coords = prm.station_coordinates(prm.R0_MARKETS)
        f_mine, _ = prm.pooled_frame(payload_mine, coords)
        f_l2, _ = prm.pooled_frame(payload_l2, coords)
        report["C_0b"][centre] = frame_diff(f_mine, f_l2, ["market", "centre", "hour", "target_date"], CONTROL_TOL)
        del payload_mine, payload_l2, f_mine, f_l2
    if not all(v["pass"] for v in report["C_0b"].values()):
        raise Halt(f"C-0b failed: {report['C_0b']}")

    # C-0c: gap-fetch market blocks equal L9's block_sha256 on the overlap (Oct 3 - Dec 16), byte for byte.
    report["C_0c"] = spc.control_cd_blocks(fetch_file(ctx, "gap"), guard_read(cfg["l9_corpus"]))
    if not report["C_0c"]["pass"]:
        raise Halt(f"C-0c failed: {report['C_0c']}")

    # C-b: the row-28 arm-C path with an empty pool equals the arm-A path (R-A base, h07, held-out 2021).
    _, market_class = spc.load_rp2_classes(guard_read(cfg["rp2_classes"]))
    at_hour = base[base["hour"] == 7]
    train = at_hour[at_hour["year"] != 2021].reset_index(drop=True)
    val = at_hour[at_hour["year"] == 2021].reset_index(drop=True)
    a_rows = fit_and_score(ctx, train, val, buckets)
    c_rows = {}
    import pandas as pd

    for cls in sorted(set(market_class.values())):
        part = val[val["market"].isin([m for m, c in market_class.items() if c == cls])].reset_index(drop=True)
        if not len(part):
            continue
        empty = base.iloc[0:0]
        train_c = pd.concat([train, empty[train.columns.intersection(empty.columns)]], ignore_index=True)
        c_rows.update(fit_and_score(ctx, train_c, part, buckets))
    worst = max(abs(c_rows[k]["brier"] - a_rows[k]["brier"]) for k in a_rows) if set(a_rows) == set(c_rows) \
        else float("inf")
    report["C_b"] = {"rows": len(a_rows), "max_abs_diff": worst, "pass": worst == 0.0}
    # Section 5.2: a C-b failure HALTs arm C only; the other arms proceed.
    report["halted_arms"] = [] if report["C_b"]["pass"] else ["C"]

    report["records_sha256"] = shas
    report["status"] = "PASS"
    return report


# ----------------------------------------------------------------------------- stage 2: build (no label is used)

def stage_build(ctx, cfg, w):
    import pandas as pd

    prm, spc, l9 = ctx.prm, ctx.spc, ctx.l9
    controls, _ = verify_prev(cfg, "controls")
    records = w.check(cfg["records_root"])
    report = {"started": now()}
    for name, sha in controls["records_sha256"].items():
        if sha256_file(records / name) != sha:
            raise Halt(f"control record {name} changed since the controls stage")

    from weather.sources.forecast_training_corpus import CorpusVerificationError

    failed, shas = [], dict(controls["records_sha256"])
    for centre in ctx.centres["A"]:
        years = covered(ctx, centre)
        if years != controls["covered_years"][centre]:
            raise Halt(f"covered years for {centre} changed since the controls stage")
        if not years:
            failed += [[m, centre, "no covered year"] for m in prm.R0_MARKETS]
            continue
        for market in prm.R0_MARKETS:
            path = prm.records_path(records, market, centre)
            if path.exists():
                if path.name not in shas:
                    raise Halt(f"unexpected record file {path}")
                continue
            try:
                path, _ = prm.extract_market(market, centre, manifests_for(ctx, centre), records, training_years=years)
            except CorpusVerificationError as exc:
                failed.append([market, centre, str(exc)])
                continue
            w.note(path)
            shas[path.name] = sha256_file(path)
            print(f"extracted {market} centre#{ctx.centres['A'].index(centre)}", flush=True)
    report["records_sha256"] = shas
    report["extract_failed_closed"] = failed
    report["halted_arms"] = list(controls.get("halted_arms", []))

    # y-free row frame: labels are blanked right after unpickling (the bound builder itself stores y).
    files = sorted(records / name for name in shas)
    frame, meta = market_frame(ctx, files, with_labels=False)
    days = frame["target_date"].astype(str)
    if (days > DEV_LAST.isoformat()).any():
        raise Halt("a record row is dated after 2025")
    report["rows_fold_2026_not_built"] = int((days > LAST_TRAIN.isoformat()).sum())
    frame = frame[days <= LAST_TRAIN.isoformat()].reset_index(drop=True)
    # R6: label PRESENCE only (counted before blanking, by blank_labels); never a value.
    report["label_presence"] = {"rows": int(len(frame)), "rows_without_label": int((~frame["y_present"]).sum())}
    w.pickle_gz("frame_noy_raw.pkl.gz", frame)
    w.json("payload_meta.json", meta)

    # Market NBM (section 3.3b): L9 1ae4bf52 (Aug-Sep, Oct 3 - Dec 16) + c07 + 01Z/00Z add-on + gap Jun-Jul only.
    if sha256_file(cfg["l9_corpus"]) != L9_CORPUS_SHA256:
        raise Halt("L9 NBM corpus sha256 differs")
    gap_junjul, kept = write_filtered_blocks(w, fetch_file(ctx, "gap"), "gap_blocks_jun_jul.jsonl", (6, 7))
    nbm_dir = w.path("nbm_market_new")
    l9._nbm_corpus_command(SimpleNamespace(blocks=[str(fetch_file(ctx, "c07")), str(fetch_file(ctx, "addon")),
                                                   str(gap_junjul)], out_dir=str(nbm_dir)))
    new_rows = nbm_dir / "nbm_pit_corpus_rows.jsonl"
    w.note(new_rows)
    w.note(nbm_dir / "manifest.json")
    table = merged_table(ctx, [cfg["l9_corpus"], new_rows])
    cycles = []
    for market, day, hour in zip(frame["market"], frame["target_date"], frame["hour"]):
        cycles.append(l9.nbm_at_cutoff(table, market, str(day)[:10], int(hour), ctx.tz[market])[1])
    inputs, stats = prm.attach_training_nbm(frame, table, l9.nbm_at_cutoff, ctx.tz)
    inputs["nbm_cycle"] = cycles
    inputs["sy"] = [season_year(d) for d in inputs["target_date"]]
    w.pickle_gz("frame_inputs.pkl.gz", inputs)
    report["market_nbm"] = {"gap_jun_jul_records": kept, "train_nbm": stats,
                            "new_corpus_rows_sha256": sha256_file(new_rows)}

    # Pool feature rows (arm C), hours 13-16 on arm A's training dates; Aug-Sep from the frozen R-P2 inputs.
    station_set = read_json(Path(cfg["l48_corpus_root"]) / "station_set.json")
    if sha256_file(Path(cfg["l48_corpus_root"]) / "station_set.json") != STATION_SET_SHA256:
        raise Halt("station_set.json differs")
    if sha256_file(cfg["stations_meta"]) != STATIONS_META_SHA256:
        raise Halt("stations meta differs")
    pool = list(station_set["survivors"])
    meta_st = read_json(cfg["stations_meta"])
    station_class, _ = spc.load_rp2_classes(guard_read(cfg["rp2_classes"]))
    missing = [s for s in pool if s not in station_class]
    if missing:
        raise Halt(f"pool stations without an R-P2 class: {missing[:5]}")
    report["iem_files_verified"] = verify_iem_files(ctx)
    report["l48_raw_files_verified"] = verify_l48_raw(ctx, pool)
    l48_blocks = guard_read(Path(cfg["l48_corpus_root"]) / "nbp_station_blocks_pool.jsonl")
    if sha256_file(l48_blocks) != L48_POOL_BLOCKS_SHA256:
        raise Halt("L48 pool blocks differ")
    merged_root = w.path("pool_iem")
    iem_root = Path(cfg["fetch_dir"]) / "iem" / "raw" / "iem"
    merge_counts = {s: merge_iem(iem_root / s.lower(), merged_root / s.lower()) for s in pool}
    for p in sorted(merged_root.rglob("*.csv")):
        w.note(p)
    tz_pool = {s: meta_st[s]["tz"] for s in pool}
    nbm_pool = []
    for path in (fetch_file(ctx, "c07"), fetch_file(ctx, "addon"), fetch_file(ctx, "gap"), l48_blocks):
        nbm_pool += spc.nbm_pool_rows(path, tz_pool)
    seen = Counter((r["market_id"], r["target_date"], r["cycle"]) for r in nbm_pool)
    dups = [k for k, v in seen.items() if v > 1]
    if dups:
        raise Halt(f"duplicate pool NBM (station, date, cycle): {dups[:5]}")
    if any(as_date(r["target_date"]) > DEV_LAST for r in nbm_pool):
        raise Halt("pool NBM row after 2025")
    nbm_pool_path = w.text("pool_nbm_rows.jsonl",
                           "".join(json.dumps(r, sort_keys=True) + "\n" for r in nbm_pool).encode("utf-8"))
    del nbm_pool
    pool_table = l9.load_nbm(nbm_pool_path)
    a_dates = sorted(set(frame["target_date"].astype(str)))
    l48_raw = Path(cfg["l48_corpus_root"]) / "raw" / "iem"
    from weather.calibration import new_city_corpus as ncc

    rows, ctrl, drops = [], [], defaultdict(Counter)
    for icao in pool:
        cand = spc.station_candidate(icao, meta_st[icao]["tz"])
        zone = cand.spec.tz
        lat, lon, elev = float(meta_st[icao]["lat"]), float(meta_st[icao]["lon"]), float(meta_st[icao]["elev_m"])
        rep_l48 = spc.station_all_reports(l48_raw, cand)
        rep_mine = spc.station_all_reports(merged_root, cand)
        # R6: pool label PRESENCE (label_complete) per date, before any join; the label values computed by the
        # venue-rule routine are discarded on the spot and never stored.
        aug_sep, _ = spc.station_labels(l48_raw, cand)
        routine, special = spc.station_files(merged_root, icao)
        recs, _ = ncc.venue_routine_records(routine, special, cand, last_date=LAST_TRAIN.isoformat())
        other = ncc.daily_labels(recs, cand, last_date=LAST_TRAIN.isoformat())
        complete = {k: bool(v and v["label_complete"]) for k, v in aug_sep.items()}
        complete.update({k: bool(v and v["label_complete"]) for k, v in other.items() if not in_aug_sep(k)})
        del aug_sep, recs, other

        def feature_row(key, hour, reports, centre, fill=False):
            F, cur = spc.cutoff_features(reports, key, hour, zone)
            if F is None:
                return None, "no_report_before_cutoff"
            fh, cycle = l9.nbm_at_cutoff(pool_table, icao, key, hour, meta_st[icao]["tz"])
            if fh is None:
                if not fill:
                    return None, "no_nbm"
                # R11 (frozen 4.1a / 3.3b): fill from forecast as attach_training_nbm does (it keeps the
                # record's forecast_high). A pool station has no PIT forecast_high, so the filled anchor is NaN
                # and the bound model anchors the row on its fitted normal (pooled_residual_model.py 476-477).
                fh, cycle = float("nan"), None
            doy = as_date(key).timetuple().tm_yday
            return {"market": icao, "centre": centre, "season": prm.season_of(centre), "hour": hour,
                    "target_date": key, "year": as_date(key).year, "F": float(F), "fh": float(fh),
                    "lat": lat, "lon": lon, "elev": elev, "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                    "doy_cos": math.cos(2 * math.pi * doy / 365.25), "x_high_so_far": float(F),
                    "x_current_temp": float(cur), "nbm_cycle": cycle,
                    "y_complete": complete.get(key, False)}, None

        fill = RULING_R11_POOL_NO_NBM == "fill_from_normal"
        for key in a_dates:
            reports = rep_l48 if in_aug_sep(key) else rep_mine
            centre = centre_for(ctx, key, "C")
            for hour in SCORED_HOURS:
                row, why = feature_row(key, hour, reports, centre, fill=fill)
                if row is None:
                    drops[key[:7]][why] += 1
                else:
                    rows.append(row)
                    drops[key[:7]]["kept_imputed" if row["nbm_cycle"] is None else "kept"] += 1
        # Control rows: spc.build's own Aug-Sep h07-12 rows from the same frozen inputs, under R-P2's frozen rule
        # (no NBM -> dropped, as a57e10a6 was built); compared at stage integrity on input columns (R6).
        for day in spc.season_dates():
            key = day.isoformat()
            for hour in spc.HOURS:
                row, _ = feature_row(key, hour, rep_l48, prm.nearest_centre(key), fill=False)
                if row is not None:
                    ctrl.append(row)
        print(f"pool features {icao} rows={len(rows)}", flush=True)
    w.pickle_gz("pool_noy.pkl.gz", pd.DataFrame(rows))
    w.pickle_gz("pool_ctrl_noy.pkl.gz", pd.DataFrame(ctrl))
    report["pool"] = {"stations": len(pool), "rows": len(rows), "ctrl_rows": len(ctrl),
                      "rows_label_complete": sum(1 for r in rows if r["y_complete"]),
                      "ctrl_rows_label_complete": sum(1 for r in ctrl if r["y_complete"]),
                      "by_month": {k: dict(v) for k, v in sorted(drops.items())}, "iem_merge": merge_counts}
    report["status"] = "PASS"
    return report


# ----------------------------------------------------------------------------- section 7 reader (inputs only)
# A separate reader, capped at S7_LAST = 2026-05-26 (review R1). Every value it returns is asserted <= S7_LAST
# (Halt otherwise). It reads only: the L47b 2026 NBP 07Z rows (TXN mean, TXNSD; inputs), the build stage's
# 2023-25 07Z rows, and WU hourly observations at <= 07:00 local. It never reads a label or any score.

# Ruling 1 / N3: the WU hourly WRITER is wu_history.py write_hourly_partitions, line 442:
#   handle.write(json.dumps(row, sort_keys=True) + "\n")
# with row = normalize_observation(...) (wu_history.py 763-812, the dict at 780-812; rows without local_date are dropped at 410-413). Sorted, the keys before
# local_date are exactly: clouds, condition, dewpoint_c, dewpoint_native, heat_index_c, heat_index_native,
# humidity, icon; local_time follows local_date directly (no writer key sorts between them). json.dumps uses
# ", " and ": " separators and ensure_ascii, so every line starts with this fixed shape. The test below runs on
# the raw undecoded bytes; a line without the shape HALTs.
_S7_SCALAR = rb'(?:null|true|false|-?(?:[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?|Infinity)|NaN|"(?:[^"\\]|\\.)*")'
_S7_PREFIX_KEYS = (b"clouds", b"condition", b"dewpoint_c", b"dewpoint_native", b"heat_index_c",
                   b"heat_index_native", b"humidity", b"icon")
_S7_PREFIX_RB = re.compile(
    rb"\A\{" + rb", ".join(b'"' + k + b'": ' + _S7_SCALAR for k in _S7_PREFIX_KEYS)
    + rb', "local_date": "([0-9]{4}-[0-9]{2}-[0-9]{2})", "local_time": "([0-9]{2}:[0-9]{2})", ')


def s7_date(value):
    d = as_date(value)
    if d > S7_LAST:
        raise Halt(f"section 7 reader: {d} is after {S7_LAST}")
    return d


def s7_in_window(day):
    return S7_V5_MD[0] <= day[5:] <= S7_V5_MD[1]


def s7_nbm_2026(cfg):
    """{(market, date): (mean, sd)} from the L47b 2026 corpus (07Z, 2026-01-01..05-26)."""
    path = guard_read(cfg["l47b_corpus_2026"])
    if sha256_file(path) != L47B_CORPUS_SHA256:
        raise Halt("L47b corpus_2026.jsonl sha256 differs")
    out = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            d = s7_date(r["target_date"])
            if d < S7_FIRST or r.get("cycle") != "07":
                raise Halt(f"section 7: unexpected L47b row {r.get('market_id')} {d} cycle {r.get('cycle')}")
            if r.get("available") and r.get("mean") is not None:
                out[(r["market_id"], d.isoformat())] = (float(r["mean"]), None if r.get("sd") is None else float(r["sd"]))
    return out


def s7_wu_obs07(cfg, icao, year, month, first, last):
    """{local_date: WU temp_native} for the last observation at or before 07:00 local, first..last.

    v3 (ruling 1, N3): the month file is opened in "rb" and read line by line as raw bytes. Each line's date is
    tested on its raw byte prefix (_S7_PREFIX_RB, from the writer's key order) BEFORE any split or decode. A line
    dated after S7_LAST (only the 2026-05 file has such lines: 05-27..05-31) is skipped: nothing from it is
    parsed, retained or logged; it adds one to the count. Only in-window lines at or before 07:00 are decoded."""
    if RULING_C2_S7_RAW_PREFIX != "rb_prefix_before_decode" or RULING_S7_SEALED_LINES != "skip_undecoded":
        raise Halt("unknown section 7 reader ruling")
    path = Path(cfg["main_data"]) / "wunderground" / icao / "hourly" / f"year={year}" / f"month={month:02d}" \
        / "observations.jsonl"
    out, skipped = {}, 0
    if not path.is_file():
        return out, skipped
    cap = S7_LAST.isoformat().encode("ascii")
    lo, hi = first.encode("ascii"), last.encode("ascii")
    obs_cut = S7_OBS_LOCAL.encode("ascii")
    with open(guard_read(path), "rb") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            m = _S7_PREFIX_RB.match(raw)
            if m is None:
                raise Halt(f"section 7: a WU line without the writer's prefix shape in {path}")
            if m.group(1) > cap:
                del m, raw
                skipped += 1
                continue
            day_b, time_b = m.group(1), m.group(2)
            if not (lo <= day_b <= hi) or time_b > obs_cut:
                continue
            day, hhmm = day_b.decode("ascii"), time_b.decode("ascii")
            r = json.loads(raw.decode("utf-8"))
            if s7_date(r["local_date"]).isoformat() != day or r.get("local_time") != hhmm:
                raise Halt(f"section 7: prefix and record disagree in {path}")
            if r.get("temperature_unit") != "F":
                raise Halt(f"section 7: non-F WU row in {path}")
            if r.get("temp_native") is None:
                continue
            if day not in out or hhmm >= out[day][0]:
                out[day] = (hhmm, float(r["temp_native"]))
    return {d: v for d, (_, v) in out.items()}, skipped


def _smd(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    den = math.sqrt((statistics.variance(a) + statistics.variance(b)) / 2)
    return (statistics.fmean(a) - statistics.fmean(b)) / den if den > 0 else None


def section7_gate(ctx, cfg, build_dir):
    """Section 7 V4->V5 gate as frozen: (NBP07 TXN mean - WU obs at 07 local) and TXNSD, V5.0 2026-05-06..05-26
    against the same window in 2023-25; 2026-01-01..05-05 (V4.3) is the within-year reference (descriptive)."""
    if RULING_F9_SECTION7_GATE != "compute":
        raise Halt(f"unknown RULING_F9_SECTION7_GATE {RULING_F9_SECTION7_GATE}")
    v4_idx = nbm_rows_index(Path(build_dir) / "nbm_market_new" / "nbm_pit_corpus_rows.jsonl", "07")
    v5_idx = s7_nbm_2026(cfg)
    if {m for m, _ in v5_idx} - set(ctx.prm.R0_MARKETS):
        raise Halt("section 7: L47b holds markets outside R0_MARKETS")
    groups = {g: {m: {"x": [], "sd": []} for m in US10} for g in ("V5", "V4", "V43_ref")}
    sealed_skipped = 0
    for m in US10:
        icao = ctx.icao[m].lower()
        obs = {}
        for year in S7_V4_YEARS:
            part, k = s7_wu_obs07(cfg, icao, year, 5, f"{year}-{S7_V5_MD[0]}", f"{year}-{S7_V5_MD[1]}")
            obs.update(part)
            sealed_skipped += k
        for month in range(1, 6):
            part, k = s7_wu_obs07(cfg, icao, 2026, month, S7_FIRST.isoformat(), S7_LAST.isoformat())
            obs.update(part)
            sealed_skipped += k
        for (mk, day), (_, mean, sd) in v4_idx.items():
            if mk == m and int(day[:4]) in S7_V4_YEARS and s7_in_window(day) and day in obs:
                groups["V4"][m]["x"].append(mean - obs[day])
                if sd is not None:
                    groups["V4"][m]["sd"].append(float(sd))
        for (mk, day), (mean, sd) in v5_idx.items():
            if mk != m or day not in obs:
                continue
            g = "V5" if s7_in_window(day) else ("V43_ref" if as_date(day) <= S7_REF_LAST else None)
            if g is None:
                continue
            groups[g][m]["x"].append(mean - obs[day])
            if sd is not None:
                groups[g][m]["sd"].append(sd)

    def pooled(g, key):
        return [v for m in US10 for v in groups[g][m][key]]

    def ratio(a, b):
        return statistics.median(a) / statistics.median(b) if a and b and statistics.median(b) > 0 else None

    smd_pooled = _smd(pooled("V5", "x"), pooled("V4", "x"))
    sd_ratio = ratio(pooled("V5", "sd"), pooled("V4", "sd"))
    per_market = {m: {"n_v5": len(groups["V5"][m]["x"]), "n_v4": len(groups["V4"][m]["x"]),
                      "smd": _smd(groups["V5"][m]["x"], groups["V4"][m]["x"]),
                      "txnsd_median_ratio": ratio(groups["V5"][m]["sd"], groups["V4"][m]["sd"])} for m in US10}
    over = [m for m, v in per_market.items() if v["smd"] is not None and abs(v["smd"]) > S7_SMD_MARKET]
    reasons = []
    if smd_pooled is None or sd_ratio is None:
        reasons.append("not computable: an empty group")
    else:
        if abs(smd_pooled) > S7_SMD_POOLED:
            reasons.append(f"pooled |SMD| {abs(smd_pooled):.4f} > {S7_SMD_POOLED}")
        if not (S7_SD_RATIO[0] <= sd_ratio <= S7_SD_RATIO[1]):
            reasons.append(f"pooled TXNSD median ratio {sd_ratio:.4f} outside {list(S7_SD_RATIO)}")
    if len(over) > S7_MARKETS_MAX:
        reasons.append(f"{len(over)} of 10 markets exceed |SMD| > {S7_SMD_MARKET}")
    return {
        "result": "FLAG" if reasons else "PASS", "reasons": reasons, "governs": "section 9 only, never the verdict",
        "smd_pooled": smd_pooled, "txnsd_median_ratio_pooled": sd_ratio, "markets_over": over,
        "per_market": per_market,
        "n": {g: len(pooled(g, "x")) for g in groups}, "n_txnsd": {g: len(pooled(g, "sd")) for g in groups},
        "reference_v43_descriptive": {"smd_v5_vs_v43": _smd(pooled("V5", "x"), pooled("V43_ref", "x")),
                                      "txnsd_median_ratio_v5_vs_v43": ratio(pooled("V5", "sd"), pooled("V43_ref", "sd"))},
        "obs_rule": f"last WU observation at or before {S7_OBS_LOCAL} local on the date",
        "sealed_lines_skipped_undecoded": sealed_skipped, "cap": S7_LAST.isoformat(),
        "l47b_corpus_sha256": L47B_CORPUS_SHA256,
    }


def restate_power(n, n_look):
    """N2: section 6.3's MDE80 / power / futility table and section 8.4's thresholds at the restated n, by the
    frozen formulas only. The same formulas at n = 660 / 390 must reproduce the frozen table (self-check)."""
    def table(nn, nl):
        out = {}
        for name, sigma in (("sigma_eff", SIGMA_EFF), ("sigma_dec", SIGMA_DEC), ("2x_sigma_eff", 2 * SIGMA_EFF),
                            ("3x_sigma_eff", 3 * SIGMA_EFF), ("4x_sigma_eff", 4 * SIGMA_EFF)):
            se = INFLATION * sigma / math.sqrt(nn)
            se_look = sigma / math.sqrt(nl)
            out[name] = {"sigma": sigma, "mde80_x1.07": MDE_MULT * se, "power_at_edge_x1.07": PHI(EDGE / se - Z_HOLM_WORST),
                         "futility_false_stop_look": 1.0 - PHI((FUTILITY + EDGE) / se_look)}
        return out

    frozen = table(N_DECIDING, N_LOOK)
    for name, (mde, power, fut) in FROZEN_TABLE_660.items():
        got = frozen[name]
        if abs(got["mde80_x1.07"] - mde) > 0.00005 or abs(got["power_at_edge_x1.07"] - power) > 0.005 \
                or abs(got["futility_false_stop_look"] - fut) > 0.005:
            raise Halt(f"section 6.3 self-check: the frozen formulas do not reproduce the table row {name}")
    se_xs = EDGE / (Z_HOLM_WORST + Z80)
    se_xa = EDGE / (Z_XA + Z80)
    se_r16 = EDGE / Z_HOLM_WORST

    def sig(se_thr):
        s = se_thr * math.sqrt(n) / INFLATION
        return {"sigma_hat": s, "x_sigma_eff": s / SIGMA_EFF}

    return {"n": n, "n_look": n_look, "frozen_n": N_DECIDING, "frozen_n_look": N_LOOK, "table_6_3": table(n, n_look),
            "thresholds_8_4": {"se_wide_xs_adequate": se_xs, "se_wide_xa_adequate": se_xa, "se_wide_rule16": se_r16,
                               "sigma_hat_xs_adequate": sig(se_xs), "sigma_hat_xa_adequate": sig(se_xa),
                               "sigma_hat_rule16": sig(se_r16)},
            "formulas": "SE = 1.07*sigma/sqrt(n); MDE80 = 3.340*SE; power = Phi(0.0057/SE - 2.498); futility "
                        "false-stop = 1 - Phi(0.00285/(sigma/sqrt(n_look))); sigma_hat thresholds = SE_thr*sqrt(n)/1.07"}


def precheck_folds(ctx, folds, kept_rows, market):
    """N1: before any fit, every kept (fold, hour) set has exactly its built rows (no HALT once a score exists)."""
    frame = with_arm_centres(ctx, market, "A")
    want = defaultdict(set)
    for r in kept_rows:
        if season_year(r["date"]) in folds:
            want[(season_year(r["date"]), r["hour"])].add((r["market"], r["date"]))
    for fold in folds:
        for hour in SCORED_HOURS:
            sel = want[(fold, hour)]
            part = frame[(frame["hour"] == hour) & (frame["sy"] == fold)]
            n = sum(1 for m, t in zip(part["market"], part["target_date"]) if (m, str(t)[:10]) in sel)
            if n != len(sel):
                raise Halt(f"fold {fold} h{hour}: {len(sel)} kept rows but {n} built rows (pre-score check)")


# ----------------------------------------------------------------------------- stage 3: integrity (outcome-blind)

def stage_integrity(ctx, cfg, w):
    import numpy as np
    import pandas as pd

    prm, l9 = ctx.prm, ctx.l9
    build, build_dir = verify_prev(cfg, "build")
    report = {"started": now()}
    for name in ("frame_inputs.pkl.gz", "pool_noy.pkl.gz", "pool_ctrl_noy.pkl.gz", "payload_meta.json"):
        listed = build["outputs_sha256"].get(str(Path(build_dir) / name))
        if listed is None or sha256_file(Path(build_dir) / name) != listed:
            raise Halt(f"build output {name} differs from the build report")
    frame = load_pickle_gz(Path(build_dir) / "frame_inputs.pkl.gz")
    pool = load_pickle_gz(Path(build_dir) / "pool_noy.pkl.gz")
    ctrl_noy = load_pickle_gz(Path(build_dir) / "pool_ctrl_noy.pkl.gz")
    payload_meta = read_json(Path(build_dir) / "payload_meta.json")
    # Review R5: no label column anywhere in this stage's inputs (presence flags only, per R6).
    for name, cols in (("frame_inputs", frame.columns), ("pool_noy", pool.columns), ("pool_ctrl_noy", ctrl_noy.columns),
                       ("payload_meta", {k for p in payload_meta for k in p})):
        bad = sorted({"y", "final_bucket", "label_native", "label"} & set(cols))
        if bad:
            raise Halt(f"the integrity stage received labels in {name}: {bad}")
    if any(set(p) != {"market", "centre", "file", "bucket_space"} for p in payload_meta):
        raise Halt("payload_meta.json holds keys other than market, centre, file, bucket_space")
    days = deciding_dates(ctx)
    min_rows = wu_min_rows()
    # R6: a built row without a label HALTs the whole run here, before any join (presence only).
    missing_label = int((~frame["y_present"].astype(bool)).sum())
    report["label_presence"] = {"rows": int(len(frame)), "rows_without_label": missing_label}
    if RULING_R6_ALL_HALTS_BEFORE_LABEL_JOIN and missing_label:
        raise Halt(f"{missing_label} built rows have no label (R6 presence check)")

    # Section 3.2: wrap-free = wrap-aware picks, Rule L pick for 2024-02-29 is 02-22, in every arm.
    wrap = {}
    for arm in ARMS:
        bad = [d for d in days if centre_for(ctx, d, arm) not in circular_picks(d, ctx.centres[arm])]
        train_days = sorted(set(frame["target_date"].astype(str)))
        bad_train = [d for d in train_days if centre_for(ctx, d, arm) not in circular_picks(d, ctx.centres[arm])]
        wrap[arm] = {"deciding_differ": len(bad), "training_differ": len(bad_train),
                     "rule_l_2024_02_29": centre_for(ctx, "2024-02-29", arm)}
        if bad or centre_for(ctx, "2024-02-29", arm) != "2026-02-22":
            raise Halt(f"section 3.2 wrap / Rule L assertion failed in arm {arm}: {bad[:5]}")
    report["wrap_rule_l"] = wrap

    # Section 3.3: exactly one row per (market, target_date, hour).
    dup = frame.duplicated(["market", "target_date", "hour"]).sum()
    report["duplicate_keys"] = int(dup)
    if dup:
        raise Halt(f"{dup} duplicate (market, target_date, hour) keys")

    # Scored rows and drops (section 5.2): every US10 market-hour of the 660 dates (Denver descriptive).
    new_rows = Path(build_dir) / "nbm_market_new" / "nbm_pit_corpus_rows.jsonl"
    idx07 = nbm_rows_index(new_rows, "07")
    by_key = {(m, str(d)[:10], int(h)): i for i, (m, d, h) in
              enumerate(zip(frame["market"], frame["target_date"], frame["hour"]))}
    wu = {}
    for m in prm.R0_MARKETS:
        wu[m], info = wu_daily(ctx, m, with_high=False)
        report.setdefault("wu_daily_kept_lines", {})[m] = info  # N4(b): never a whole-file hash
    kept, drops = [], []
    for d in days:
        for m in US10 + DESCRIPTIVE_MARKETS:
            for h in SCORED_HOURS:
                key = (m, d, h)
                reason = None
                i = by_key.get(key)
                if i is None:
                    reason = "no_built_row"
                elif wu[m].get(d, 0) < min_rows:
                    reason = "wu_partial_or_missing"
                else:
                    entry = idx07.get((m, d))
                    cutoff = l9._cutoff_instant(as_date(d), h, ctx.tz[m])
                    if entry is None or entry[0] > cutoff or entry[2] is None:
                        reason = "no_07z_by_cutoff"
                    elif not (math.isfinite(frame.at[i, "F"]) and math.isfinite(frame.at[i, "x_current_temp"])):
                        reason = "missing_F_or_current_temp"
                    elif frame.at[i, "nbm_cycle"] != "07" or abs(frame.at[i, "fh"] - entry[1]) > 0:
                        raise Halt(f"scored row {key}: anchor is not the 07Z mean")
                (drops if reason else kept).append({"market": m, "date": d, "hour": h, "reason": reason})
    us_drops = [r for r in drops if r["market"] in US10]
    total = len(days) * len(US10) * len(SCORED_HOURS)
    share_pooled = len(us_drops) / total
    share_market = {m: sum(1 for r in us_drops if r["market"] == m) / (len(days) * len(SCORED_HOURS)) for m in US10}
    share_fold = {y: sum(1 for r in us_drops if season_year(r["date"]) == y) / (FOLD_DATES[y] * 40) for y in FOLDS}
    report["drops"] = {"us10_total_market_hours": total, "us10_dropped": len(us_drops),
                       "by_reason": dict(Counter(r["reason"] for r in us_drops)),
                       "share_pooled": share_pooled, "share_market": share_market, "share_fold": share_fold,
                       "denver_dropped": len(drops) - len(us_drops), "rows": drops}
    if share_pooled > CAP_POOLED or max(share_market.values()) > CAP_MARKET or max(share_fold.values()) > CAP_FOLD:
        raise Halt(f"section 5.2 cap breached: pooled {share_pooled}, markets {share_market}, folds {share_fold}")
    kept_us = [r for r in kept if r["market"] in US10]
    kept_dates = sorted({r["date"] for r in kept_us})
    report["kept"] = {"us10_rows": len(kept_us), "denver_rows": len(kept) - len(kept_us), "n_dates": len(kept_dates),
                      "folds": dict(Counter(season_year(d) for d in kept_dates)),
                      "look_dates": sum(1 for d in kept_dates if season_year(d) in LOOK_FOLDS),
                      "dates": kept_dates}
    report["realised_population"] = {
        arm: {str(h): sum(1 for r in kept_us if r["hour"] == h) for h in SCORED_HOURS} for arm in ARMS}
    # N2 (master, 2026-11-03, per frozen 5.2): drops within the caps restate n; the restated n, the look n (the
    # kept dates of folds 2021-23) and the date list are committed here, before any score, with the MDE and the
    # 8.4 thresholds recomputed at that n by the frozen formulas. Later stages assert against this list and n.
    if RULING_N2_N != "integrity_restated":
        raise Halt(f"unknown RULING_N2_N {RULING_N2_N}")
    if not set(kept_dates) <= set(days):
        raise Halt("a kept date is not a deciding date")
    report["restated"] = restate_power(len(kept_dates), report["kept"]["look_dates"])

    # Arm C empty pool (section 5.2; HALTs C only): label-complete pool rows per (class, hour, fold). R6: this
    # is the recheck the v1 runner made after the join; presence (y_complete) makes it pre-join.
    station_class, market_class = ctx.spc.load_rp2_classes(guard_read(cfg["rp2_classes"]))
    pool = pool.assign(cls=pool["market"].map(station_class), sy=[season_year(d) for d in pool["target_date"]])
    pool_train = pool[pool["y_complete"].astype(bool)] if RULING_R6_ALL_HALTS_BEFORE_LABEL_JOIN else pool
    empty = []
    counts = {}
    for cls in sorted(set(market_class[m] for m in US10)):
        for h in SCORED_HOURS:
            for y in FOLDS:
                n = int(((pool_train["cls"] == cls) & (pool_train["hour"] == h) & (pool_train["sy"] != y)).sum())
                counts[f"{cls}|{h}|{y}"] = n
                if n == 0:
                    empty.append([cls, h, y])
    report["pool_rows_by_class_hour_fold"] = counts
    halted = set(build.get("halted_arms", [])) | ({"C"} if empty else set())
    report["pool_empty"] = empty

    # C-pool control (C only; R6 at stage 3): the rebuilt Aug-Sep h07-12 rows equal a57e10a6 on its input
    # columns, 1e-9. a57's label column is dropped on load and never compared or stored.
    a57, _ = ctx.spc.load_pool_frame(guard_read(Path(cfg["l48_corpus_root"]) / "corpora" / A57_CORPUS_ID))
    in_cols = sorted((set(a57.columns) & set(ctrl_noy.columns)) - {"y", "y_complete", "y_present"})
    a57 = a57[in_cols]
    ctrl_in = ctrl_noy[ctrl_noy["y_complete"].astype(bool)][in_cols]
    report["C_pool_control"] = frame_diff(ctrl_in, a57, ["market", "target_date", "hour"], CONTROL_TOL)
    report["C_pool_control"]["columns_compared"] = in_cols
    del a57, ctrl_in
    if not report["C_pool_control"]["pass"]:
        halted.add("C")
    halted = sorted(halted)

    # Imputation cap (section 3.3b; R10): fill-from-forecast share per arm x calendar month (MM), pooled over
    # years, hours 13-16 training rows; arm C adds its label-complete pool rows (R11: filled rows count).
    # The YYYY-MM breakdown is descriptive.
    train = frame[frame["hour"].isin(SCORED_HOURS)]
    tdays = train["target_date"].astype(str)
    imputed = train["nbm_cycle"].isna()
    pool_days = pool_train["target_date"].astype(str)
    pool_imp = pool_train["nbm_cycle"].isna()

    def shares_by(width_from, width_to):
        out = {}
        for arm in ARMS:
            sel = tdays.map(in_dec_may) if arm == "B" else pd.Series(True, index=train.index)
            key = tdays.str[width_from:width_to]
            tot = key[sel].value_counts().to_dict()
            imp = key[sel & imputed].value_counts().to_dict()
            if arm == "C":
                pk = pool_days.str[width_from:width_to]
                for k, c in pk.value_counts().items():
                    tot[k] = tot.get(k, 0) + int(c)
                for k, c in pk[pool_imp].value_counts().items():
                    imp[k] = imp.get(k, 0) + int(c)
            out[arm] = {k: {"rows": int(tot[k]), "imputed": int(imp.get(k, 0)),
                            "share": float(imp.get(k, 0) / tot[k])} for k in sorted(tot)}
        return out

    by_month = shares_by(5, 7)
    by_ym = shares_by(0, 7)
    if RULING_R10_IMPUTE_GROUP != "calendar_month":
        raise Halt(f"unknown RULING_R10_IMPUTE_GROUP {RULING_R10_IMPUTE_GROUP}")
    report["imputation"] = {"cap_basis": "arm x calendar month (MM), pooled over years", "by_calendar_month": by_month,
                            "by_year_month_descriptive": by_ym}
    # N5 (acknowledged in C2): rows with NaN fh take the bound fill-from-normal path (prm _anchors 476-477); count
    # per calendar month, pool rows (arm C) and market training rows (hours 13-16) separately.
    fh_nan_market = train["fh"].isna()
    fh_nan_pool = pool_train["fh"].isna()
    n5 = {}
    for k, c in tdays[fh_nan_market].str[5:7].value_counts().items():
        n5.setdefault(k, {"market_rows": 0, "pool_rows": 0})["market_rows"] = int(c)
    for k, c in pool_days[fh_nan_pool].str[5:7].value_counts().items():
        n5.setdefault(k, {"market_rows": 0, "pool_rows": 0})["pool_rows"] = int(c)
    report["fill_from_normal_by_calendar_month"] = {k: n5[k] for k in sorted(n5)}
    worst = max((v["share"] for arm in by_month.values() for v in arm.values()), default=0.0)
    if worst > IMPUTE_CAP:
        raise Halt(f"section 3.3b imputation cap breached ({worst:.4f})")

    # Comparator S (section 2): MG-1 on (07Z mean, max(TXNSD, 1), floor F); mg1.predict vs mg1_band_probs, 1e-12.
    from weather.model import mg_serve_core
    from weather.reporting.scorecards.free_source_candidates import mg1

    def s_inputs(rows_in):
        snaps, bands = [], []
        for r in rows_in:
            mu, sd, F, avail, cap = r["mu"], r["sd"], r["F"], r["avail"], r["cap"]
            B = math.floor(F + 0.5)
            K = max(B, math.ceil(mu + S_TAIL_SIGMAS * max(sd, 1.0)))
            snaps.append({"row_key": r["row_key"], "v2_mean": mu, "v2_stddev": sd, "floor": F,
                          "v2_available_at": avail, "captured_at_utc": cap})
            for j, k in enumerate(range(B, K + 1)):
                bands.append({"row_key": r["row_key"], "band_index": j, "kind": "gte" if k == K else "exact",
                              "low": float(k), "high": float(k)})
        return pd.DataFrame(snaps), pd.DataFrame(bands)

    def s_check(rows_in):
        snaps, bands = s_inputs(rows_in)
        pred = mg1.predict(snaps, bands)
        merged = bands.merge(pred, on=["row_key", "band_index"], how="left")
        worst_s, dists = 0.0, {}
        info = {r["row_key"]: r for r in rows_in}
        for key, g in merged.groupby("row_key", sort=False):
            r = info[key]
            B = math.floor(r["F"] + 0.5)
            ref = mg_serve_core.mg1_band_probs(g["kind"].to_numpy(), g["low"].to_numpy(), g["high"].to_numpy(),
                                               B, r["mu"], max(r["sd"], 1.0))
            p = g["p"].to_numpy(float)
            if np.isnan(p).any():
                raise Halt(f"S: mg1.predict returned no prediction for {key}")
            worst_s = max(worst_s, float(np.max(np.abs(p - ref))))
            dists[key] = [[int(k), float(v)] for k, v in zip(g["low"].to_numpy(int), p)]
        return worst_s, dists

    rng = np.random.default_rng(S_SYNTHETIC_SEED)
    synth = []
    for j in range(S_SYNTHETIC_ROWS):
        mu = float(rng.uniform(20, 100))
        synth.append({"row_key": f"synthetic|{j}", "mu": mu, "sd": float(rng.uniform(0.3, 6.0)),
                      "F": float(rng.uniform(mu - 15, mu + 5)), "avail": "2024-01-01T07:30:00+00:00",
                      "cap": "2024-01-01T18:00:00+00:00"})
    worst_synth, _ = s_check(synth)
    scored = []
    for r in kept:
        i = by_key[(r["market"], r["date"], r["hour"])]
        lm, mu, sd = idx07[(r["market"], r["date"])]
        cap = l9._cutoff_instant(as_date(r["date"]), r["hour"], ctx.tz[r["market"]])
        scored.append({"row_key": f"{r['market']}|{r['date']}|{r['hour']}", "mu": mu, "sd": float(sd),
                       "F": float(frame.at[i, "F"]), "avail": lm.isoformat(), "cap": cap.isoformat()})
    worst_scored, dists = s_check(scored)
    report["S_check"] = {"synthetic_rows": S_SYNTHETIC_ROWS, "max_abs_diff_synthetic": worst_synth,
                         "scored_rows": len(scored), "max_abs_diff_scored": worst_scored,
                         "pass": worst_synth <= S_TOL and worst_scored <= S_TOL}
    if not report["S_check"]["pass"]:
        raise Halt(f"section 2 S check failed: {report['S_check']}")
    sp = w.pickle_gz("s_dist.pkl.gz", dists)
    kp = w.json("kept_rows.json", kept)  # with report["kept"]["dates"]: the integrity-committed list (N2)
    report["s_dist_sha256"] = sha256_file(sp)
    report["kept_rows_sha256"] = sha256_file(kp)
    # Section 7 (F9): inputs only, computed and committed before any arm score; gates section 9 only.
    report["v5_gate_section7"] = section7_gate(ctx, cfg, build_dir)
    report["halted_arms"] = halted
    report["status"] = "PASS"
    return report


# ----------------------------------------------------------------------------- stage 4: labels

def stage_labels(ctx, cfg, w):
    import pandas as pd

    prm, spc = ctx.prm, ctx.spc
    integrity, integrity_dir = verify_prev(cfg, "integrity")
    build, build_dir = verify_prev(cfg, "build")
    report = {"started": now(), "integrity_gate": verify_committed_gate(
        ctx, cfg["integrity_commit"], f"{DOC_DIR}/run/integrity_report.json", Path(integrity_dir) / "walk.json")}
    records = Path(cfg["records_root"])
    for name, sha in build["records_sha256"].items():
        if sha256_file(records / name) != sha:
            raise Halt(f"record {name} changed since the build stage")
    for name in ("frame_noy_raw.pkl.gz", "frame_inputs.pkl.gz", "pool_noy.pkl.gz"):
        listed = build["outputs_sha256"].get(str(Path(build_dir) / name))
        if listed is None or sha256_file(Path(build_dir) / name) != listed:
            raise Halt(f"build output {name} differs from the build report")
    raw_noy = load_pickle_gz(Path(build_dir) / "frame_noy_raw.pkl.gz")
    inputs = load_pickle_gz(Path(build_dir) / "frame_inputs.pkl.gz")
    labelled, _ = market_frame(ctx, sorted(records / n for n in build["records_sha256"]), with_labels=True)
    labelled = labelled[labelled["target_date"].astype(str) <= LAST_TRAIN.isoformat()].reset_index(drop=True)
    keys = ["market", "payload_centre", "hour", "target_date"]
    # Consistency asserts only: under R6 every HALT condition was decided at stage 3 from presence, so none of
    # these can fire unless the inputs changed (sha-checked above) or the code is wrong.
    presence = labelled.assign(y_present=labelled["y"].notna())
    parity = frame_diff(presence.drop(columns=["y"]), raw_noy, keys, 0.0)
    report["y_free_parity"] = parity
    if not parity["pass"]:
        raise Halt("labelled frame differs from the y-free frame outside y (or label presence differs)")
    y = labelled.set_index(["market", "target_date", "hour"])["y"]
    market = inputs.join(y, on=["market", "target_date", "hour"])
    if market["y"].isna().any():
        raise Halt("a built row has no label (stage 3 presence check disagrees)")
    w.pickle_gz("market_frame_y.pkl.gz", market)

    # Pool labels: venue rule, label_complete only; Aug-Sep from the frozen L48 inputs, other months from row 28's.
    from weather.calibration import new_city_corpus as ncc

    station_set = read_json(Path(cfg["l48_corpus_root"]) / "station_set.json")
    meta_st = read_json(cfg["stations_meta"])
    pool_noy = load_pickle_gz(Path(build_dir) / "pool_noy.pkl.gz")
    l48_raw = Path(cfg["l48_corpus_root"]) / "raw" / "iem"
    merged_root = Path(build_dir) / "pool_iem"
    labels = {}
    counts = Counter()
    for icao in station_set["survivors"]:
        cand = spc.station_candidate(icao, meta_st[icao]["tz"])
        aug_sep, _ = spc.station_labels(l48_raw, cand)
        routine, special = spc.station_files(merged_root, icao)
        recs, _ = ncc.venue_routine_records(routine, special, cand, last_date=LAST_TRAIN.isoformat())
        other = ncc.daily_labels(recs, cand, last_date=LAST_TRAIN.isoformat())
        for k, v in aug_sep.items():
            labels[(icao, k)] = v
        for k, v in other.items():
            if not in_aug_sep(k):
                labels[(icao, k)] = v

    def attach(frame):
        ys, keep = [], []
        for icao, key, flag in zip(frame["market"], frame["target_date"], frame["y_complete"]):
            lab = labels.get((icao, key))
            ok = bool(lab and lab["label_complete"])
            if ok != bool(flag):
                raise Halt(f"pool label completeness for {icao} {key} differs from the stage-2 presence flag")
            keep.append(ok)
            ys.append(float(lab["label_native"]) if ok else float("nan"))
            counts["label_complete" if ok else "label_incomplete"] += 1
        out = frame.assign(y=ys)[keep].reset_index(drop=True)
        return out

    pool_y = attach(pool_noy)
    report["pool_label_counts"] = dict(counts)
    # R6: the C-pool control and the empty-pool check ran at stage 3 (integrity report). N7: this stage has
    # consistency HALTs only; they cannot fire unless inputs changed (sha-checked) or a code bug.
    halted = list(integrity.get("halted_arms", []))
    pool_y = pool_y.assign(sy=[season_year(d) for d in pool_y["target_date"]])
    w.pickle_gz("pool_frame_y.pkl.gz", pool_y)
    report["halted_arms"] = sorted(set(halted))
    report["status"] = "PASS"
    return report


# ----------------------------------------------------------------------------- stages 5 and 6: scoring

def k112_inputs(ctx, cfg, build_dir):
    """d = NBP07 mean - WU high per (market, date) on available dates (07Z present, complete WU day)."""
    idx = {}
    for path in (cfg["l9_corpus"], Path(build_dir) / "nbm_market_new" / "nbm_pit_corpus_rows.jsonl"):
        for key, (lm, mean, sd) in nbm_rows_index(path, "07").items():
            if key in idx:
                raise Halt(f"duplicate 07Z market value {key}")
            idx[key] = mean
    min_rows = wu_min_rows()
    d = {}
    for m in ctx.prm.R0_MARKETS:
        daily, _ = wu_daily(ctx, m, with_high=True)
        for day, (rows, high) in daily.items():
            if rows >= min_rows and high is not None and (m, day) in idx:
                d[(m, day)] = idx[(m, day)] - high
    return d


def k112_b_train(d):
    """b_train per (market, fold): mean d over Aug 1 - Sep 29 of the fold's training years (frozen K112)."""
    out = {}
    for fold in FOLDS:
        acc = defaultdict(list)
        for (m, day), v in d.items():
            if int(day[:4]) != fold and int(day[:4]) in FOLDS and in_aug_sep(day):
                acc[m].append(v)
        for m, vals in acc.items():
            out[(m, fold)] = sum(vals) / len(vals)
    return out


def k112_shift(d, b_train, market, target, fold):
    t = as_date(target)
    recent = []
    for k in range(1, 2 * K112_W + 1):
        v = d.get((market, (t - timedelta(days=k)).isoformat()))
        if v is not None:
            recent.append(v)
        if len(recent) == K112_W:
            break
    if len(recent) < K112_W or (market, fold) not in b_train:
        return 0.0
    b = sum(recent) / len(recent) - b_train[(market, fold)]
    return K112_LAMBDA * max(-K112_CLIP, min(K112_CLIP, b))


def score_folds(ctx, cfg, folds, arms, kept_rows, s_dist, market, pool, payload_meta, build_dir):
    import pandas as pd

    spc = ctx.spc
    payload_buckets = {(p["market"], p["centre"]): p["bucket_space"] for p in payload_meta}
    station_class, market_class = spc.load_rp2_classes(guard_read(cfg["rp2_classes"]))
    frames = {arm: with_arm_centres(ctx, market, arm) for arm in ("A", "B")}
    pool_a = with_arm_centres(ctx, pool, "C")
    d112 = k112_inputs(ctx, cfg, build_dir) if "D" in arms else {}
    b112 = k112_b_train(d112) if "D" in arms else {}
    pool_cls = pool_a["market"].map(station_class)
    # Only this stage's folds are ever held out (section 8.1 m11: folds 2024-25 wait for the committed look).
    want = defaultdict(set)
    for r in kept_rows:
        if season_year(r["date"]) in folds:
            want[(season_year(r["date"]), r["hour"])].add((r["market"], r["date"]))
    rows = []
    for fold in folds:
        for hour in SCORED_HOURS:
            sel = want[(fold, hour)]

            def val_of(frame):
                mask = (frame["hour"] == hour) & (frame["sy"] == fold)
                part = frame[mask]
                keep = [(m, str(t)[:10]) in sel for m, t in zip(part["market"], part["target_date"])]
                return part[keep].reset_index(drop=True)

            out = {}
            train_a = arm_training(frames["A"], "A", hour, fold)
            buckets_a = arm_buckets(payload_buckets, train_a)
            val_a = val_of(frames["A"])
            if len(val_a) != len(sel):  # unreachable after precheck_folds on the same inputs (N1): a code bug
                raise RuntimeError(f"fold {fold} h{hour}: {len(sel)} kept rows but {len(val_a)} built rows")
            shifts = None
            if "D" in arms:
                shifts = {(m, str(t)[:10], hour): k112_shift(d112, b112, m, t, fold)
                          for m, t in zip(val_a["market"], val_a["target_date"])}
            out["A"] = fit_and_score(ctx, train_a, val_a, buckets_a, shifts=shifts, top_gte=True)
            if "B" in arms:
                train_b = arm_training(frames["B"], "B", hour, fold)
                out["B"] = fit_and_score(ctx, train_b, val_of(frames["B"]), arm_buckets(payload_buckets, train_b),
                                         top_gte=True)
            if "C" in arms:
                out["C"] = {}
                for cls in sorted(set(market_class.values())):
                    part = val_a[val_a["market"].isin([m for m, c in market_class.items() if c == cls])]
                    if not len(part):
                        continue
                    extra = pool_a[(pool_a["hour"] == hour) & (pool_a["sy"] != fold) & (pool_cls == cls)]
                    extra = extra[extra["target_date"].astype(str) <= LAST_TRAIN.isoformat()]
                    train_c = pd.concat([train_a, extra[train_a.columns.intersection(extra.columns)]],
                                        ignore_index=True)
                    out["C"].update(fit_and_score(ctx, train_c, part.reset_index(drop=True), buckets_a, top_gte=True))
            y_of = {(m, str(t)[:10]): int(v) for m, t, v in zip(val_a["market"], val_a["target_date"], val_a["y"])}
            for (m, t) in sorted(sel):
                key = (m, t, hour)
                actual = y_of[(m, t)]
                dist_s = {k: p for k, p in s_dist[f"{m}|{t}|{hour}"]}
                top_s = max(dist_s)  # S's gte bucket K (section 2 support B..K)
                actual_s = min(actual, top_s) if RULING_R9_TOP_BUCKET_GTE else actual
                row = {"fold": fold, "hour": hour, "market": m, "date": t, "y": actual,
                       "S": ctx.fm.brier_score(dist_s, actual_s), "S_log": ctx.fm.log_loss(dist_s, actual_s),
                       "S_y_gt_top": actual > top_s, "S_y_below_B": actual < min(dist_s),
                       "A": out["A"][key]["brier"], "A_log": out["A"][key]["log"], "A_yhat": out["A"][key]["yhat"],
                       "A_y_gt_top": out["A"][key]["y_gt_top"]}
                if "D" in arms:
                    row.update({"D": out["A"][key]["D_brier"], "D_log": out["A"][key]["D_log"],
                                "D_shift": out["A"][key]["D_shift"]})
                for arm in ("B", "C"):
                    if arm in arms:
                        row[arm] = out[arm][key]["brier"]
                        row[f"{arm}_log"] = out[arm][key]["log"]
                        row[f"{arm}_y_gt_top"] = out[arm][key]["y_gt_top"]
                rows.append(row)
            print(f"scored fold {fold} h{hour:02d} arms {''.join(arms)} rows={len(sel)}", flush=True)
    return rows


def load_scoring_inputs(cfg):
    integrity, integrity_dir = verify_prev(cfg, "integrity")
    labels, labels_dir = verify_prev(cfg, "labels")
    build, build_dir = verify_prev(cfg, "build")
    kept_path = Path(integrity_dir) / "kept_rows.json"
    s_path = Path(integrity_dir) / "s_dist.pkl.gz"
    if sha256_file(kept_path) != integrity["kept_rows_sha256"] or sha256_file(s_path) != integrity["s_dist_sha256"]:
        raise Halt("integrity outputs changed")
    for name in ("market_frame_y.pkl.gz", "pool_frame_y.pkl.gz"):
        if sha256_file(Path(labels_dir) / name) != labels["outputs_sha256"][str(Path(labels_dir) / name)]:
            raise Halt(f"labels output {name} changed")
    halted = set(labels.get("halted_arms", [])) | set(integrity.get("halted_arms", []))
    if "A" in halted:  # review R8 / section 4.3: no reference arm -> C and D are HALTED too (look and score)
        halted |= {"C", "D"}
    return SimpleNamespace(
        integrity=integrity, labels=labels, build=build, build_dir=build_dir,
        kept=json.loads(kept_path.read_text(encoding="utf-8")), s_dist=load_pickle_gz(s_path),
        market=load_pickle_gz(Path(labels_dir) / "market_frame_y.pkl.gz"),
        pool=load_pickle_gz(Path(labels_dir) / "pool_frame_y.pkl.gz"),
        payload_meta=read_json(Path(build_dir) / "payload_meta.json"),
        halted=halted)


def existing_under_run_root(name):
    return sorted(str(p.resolve()) for p in OUT_ROOT_PIN.rglob(name))


def top_bucket_counts(rows, arms):
    """R9, descriptive: scored rows with y above the top bucket (expected 0), per arm and S."""
    out = {"S": sum(1 for r in rows if r.get("S_y_gt_top")), "S_y_below_B": sum(1 for r in rows if r.get("S_y_below_B"))}
    for arm in arms:
        if arm == "D":
            continue  # D shares A's bucket space and y
        out[arm] = sum(1 for r in rows if r.get(f"{arm}_y_gt_top"))
    return out


def stage_look(ctx, cfg, w):
    # Review R3(iii): no look or final rows may exist anywhere under the run root before the look runs.
    prior = existing_under_run_root("look_rows.jsonl") + existing_under_run_root("final_rows.jsonl")
    if prior:
        raise Halt(f"look refused: scored rows already exist under {OUT_ROOT_PIN}: {prior}")
    s = load_scoring_inputs(cfg)
    report = {"started": now()}
    arms = [a for a in ARMS if a not in s.halted]
    # N2: the look set is defined by FOLDS (2021-23): the integrity-committed kept dates of those folds; its size
    # is the restated look n. Checked BEFORE any score (N1), as is every kept row's built row.
    restated = s.integrity["restated"]
    kept_look = {d for d in s.integrity["kept"]["dates"] if season_year(d) in LOOK_FOLDS}
    rows_look = {r["date"] for r in s.kept if r["market"] in US10 and season_year(r["date"]) in LOOK_FOLDS}
    if rows_look != kept_look or len(kept_look) != restated["n_look"]:
        raise Halt(f"look set: kept rows {len(rows_look)} dates, committed list {len(kept_look)}, "
                   f"restated look n {restated['n_look']}")
    precheck_folds(ctx, LOOK_FOLDS, s.kept, s.market)
    rows = score_folds(ctx, cfg, LOOK_FOLDS, arms, s.kept, s.s_dist, s.market, s.pool, s.payload_meta, s.build_dir)
    w.post_score = True  # N1: from here nothing HALTs; FLAGs only
    flags = []
    days = sorted(deciding_dates(ctx))
    report["first_390_equal_look_folds_descriptive"] = set(days[:N_LOOK]) == kept_look
    scored = {r["date"] for r in rows if r["market"] in US10}
    if scored != kept_look:
        flags.append(f"scored look dates {len(scored)} differ from the committed look list {len(kept_look)}")
    if any(season_year(r["date"]) not in LOOK_FOLDS or r["fold"] not in LOOK_FOLDS for r in rows):
        flags.append("a look row lies outside folds 2021-23")
    rp = w.text("look_rows.jsonl", "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8"))
    report["top_bucket_y_gt_top_descriptive"] = top_bucket_counts(rows, arms)
    look = {}
    for arm in ARMS:
        if arm in s.halted:
            look[arm] = {"status": "HALTED"}
            continue
        st = contrast_stats(daily_contrast(rows, arm, "S"))
        st["futile"] = st["point"] > FUTILITY
        st["power_info_look_n_uninflated"] = PHI(EDGE / st["se_wide"] - Z_HOLM_WORST) if st["se_wide"] > 0 else 1.0
        look[arm] = st
    report["look"] = look
    report["look_rows_sha256"] = sha256_file(rp) if rp is not None else None
    report["look_n_dates"] = len({r["date"] for r in rows if r["market"] in US10})
    report["restated_look_n"] = restated["n_look"]
    report["post_score_flags"] = flags
    report["status"] = "PASS"
    return report


def stage_score(ctx, cfg, w):
    s = load_scoring_inputs(cfg)
    look, look_dir = verify_prev(cfg, "look")
    report = {"started": now(), "look_gate": verify_committed_gate(
        ctx, cfg["look_commit"], f"{DOC_DIR}/run/look_result.json", Path(look_dir) / "walk.json")}
    look_rows_path = Path(look_dir) / "look_rows.jsonl"
    # Review R3, no re-run: no final rows anywhere yet, and the only look rows are the committed look's.
    if existing_under_run_root("final_rows.jsonl"):
        raise Halt(f"score refused: final rows already exist under {OUT_ROOT_PIN}")
    if existing_under_run_root("look_rows.jsonl") != [str(look_rows_path.resolve())]:
        raise Halt("score refused: look rows exist other than the committed look's")
    if sha256_file(look_rows_path) != look["look_rows_sha256"]:
        raise Halt("look rows changed since the look stage")
    look_rows = [json.loads(line) for line in look_rows_path.read_text(encoding="utf-8").splitlines() if line]
    # N1/N2: the n check runs at the START, before score_folds: the kept rows equal the integrity-committed list
    # and the restated n; the committed look covered exactly that list's 2021-23 dates.
    restated = s.integrity["restated"]
    kept_dates = sorted({r["date"] for r in s.kept if r["market"] in US10})
    if kept_dates != sorted(s.integrity["kept"]["dates"]) or len(kept_dates) != restated["n"] \
            or s.integrity["kept"]["n_dates"] != restated["n"]:
        raise Halt(f"kept rows ({len(kept_dates)} dates) differ from the integrity-committed list / restated n "
                   f"{restated['n']}")
    if {r["date"] for r in look_rows if r["market"] in US10} != {d for d in kept_dates if season_year(d) in LOOK_FOLDS}:
        raise Halt("the committed look rows do not cover exactly the committed 2021-23 kept dates")
    futile = {a for a, v in look["look"].items() if v.get("futile")}
    halted = set(s.halted)  # A -> C, D cascade applied in load_scoring_inputs (R8)
    arms = [a for a in ARMS if a not in halted and (a == "A" or a not in futile)]
    precheck_folds(ctx, FINAL_FOLDS, s.kept, s.market)
    rows = score_folds(ctx, cfg, FINAL_FOLDS, arms, s.kept, s.s_dist, s.market, s.pool, s.payload_meta, s.build_dir)
    w.post_score = True  # N1: from here nothing HALTs; FLAGs only
    flags = []
    rp = w.text("final_rows.jsonl", "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8"))
    all_rows = look_rows + rows
    keys = Counter((r["market"], r["date"], r["hour"]) for r in all_rows)
    if any(v > 1 for v in keys.values()) or len(keys) != len(s.kept):
        flags.append("scored rows do not match the integrity kept set")
    if any(season_year(r["date"]) not in FINAL_FOLDS or r["fold"] not in FINAL_FOLDS for r in rows):
        flags.append("a final row lies outside folds 2024-25")
    complete = {a for a in arms}  # scored on all folds
    stats = {}
    for arm in ARMS:
        if arm in complete:
            stats[arm] = {"vs_S": contrast_block(all_rows, arm, "S")}
            if arm in ("C", "D") and "A" in complete:
                stats[arm]["vs_A"] = contrast_block(all_rows, arm, "A")
            for name, block in stats[arm].items():
                n = block["pooled"].get("n")
                if n != restated["n"]:  # N1/N2: after scoring this is a FLAG; the HALT check ran at the start
                    flags.append(f"arm {arm} {name}: realised n {n} differs from the restated n {restated['n']}")
    report["top_bucket_y_gt_top_descriptive"] = top_bucket_counts(all_rows, sorted(complete))
    pvals = {a: (stats[a]["vs_S"]["pooled"]["p"] if a in stats and a not in futile and a not in halted else 1.0)
             for a in ARMS}
    holm_res = holm(pvals)
    outcomes = {}
    for arm in ARMS:
        if arm in halted:
            outcomes[arm] = {"outcome": "HALTED"}
            continue
        if arm in futile:
            outcomes[arm] = {"outcome": "FUTILE", "look": look["look"][arm]}
            continue
        xs = stats[arm]["vs_S"]
        crossing, fs_xs, fs_xa = [], [], []
        if xs["pooled"]["point"] > FUTILITY:
            crossing.append("X-S point > -0.00285")
        if any(v[RULING_F14_PER_MARKET_CI][0] > 0 for v in xs["per_market"].values() if not v.get("degenerate")):
            crossing.append("a per-market X-S 95% CI (wide) lies above 0")
        holm_pass = holm_res[arm]["rejected"] and xs["pooled"]["point"] < 0
        if not holm_pass:
            fs_xs.append("X-S fails Holm")
        if xs["folds_positive"] > 2:
            fs_xs.append("more than 2 of 5 folds have X-S d > 0")
        xa = stats[arm].get("vs_A")
        if arm in ("C", "D"):
            if xa["pooled"]["point"] >= XA_POINT_KILL:
                crossing.append("X-A point >= -0.0005")
            if any(v[RULING_F14_PER_MARKET_CI][0] > 0 for v in xa["per_market"].values() if not v.get("degenerate")):
                crossing.append("a per-market X-A 95% lower bound (wide) > 0")
            if xa["pooled"]["ci95_wide"][1] >= 0:
                fs_xa.append("X-A wide 95% upper bound >= 0")
            if xa["folds_positive"] > 1:
                fs_xa.append("more than 1 of 5 folds have X-A d > 0")
        power_xs = xs["pooled"]["power_xs"]
        power_xa = xa["pooled"]["power_xa"] if xa else None
        if crossing:
            outcome = "KILL"
        elif (fs_xs and power_xs >= POWER_ADEQUATE) or (fs_xa and power_xa is not None and power_xa >= POWER_ADEQUATE):
            outcome = "KILL"
        elif fs_xs or fs_xa:
            outcome = "INCONCLUSIVE-UNDERPOWERED"
        else:
            outcome = "SURVIVES-history"
        band = ("adequate (>= 0.80)" if power_xs >= POWER_ADEQUATE else
                "0.50-0.80 (rule 16 met)" if power_xs >= POWER_RULE16 else "< 0.50 (rule-16 failure flagged)")
        g = min(-EDGE, -2 * 1.96 * xs["pooled"]["sigma_hat"] / math.sqrt(G_FORWARD_DATES))
        outcomes[arm] = {"outcome": outcome, "crossing": crossing, "failure_to_show_xs": fs_xs,
                         "failure_to_show_xa": fs_xa, "holm": holm_res[arm], "power_xs": power_xs,
                         "power_xa": power_xa, "power_band_xs": band, "G": g, "n": xs["pooled"]["n"],
                         "n_xa": xa["pooled"]["n"] if xa else None,
                         "point": xs["pooled"]["point"], "se_wide_x1.07": xs["pooled"]["se_wide_x1.07"],
                         "kappa": xs["pooled"]["kappa"], "kappa_block3": xs["pooled"]["kappa_block3"],
                         "kappa_wide": xs["pooled"]["kappa_wide"]}
    survivors = [a for a, o in outcomes.items() if o["outcome"] == "SURVIVES-history"]
    passing = [a for a in survivors if outcomes[a]["point"] <= outcomes[a]["G"]]
    report["stats"] = stats
    report["holm"] = holm_res
    report["outcomes"] = outcomes
    report["selection_section_8_3"] = {"survivors": survivors, "passing_G": passing,
                                       "candidate": min(passing, key=lambda a: outcomes[a]["point"]) if passing else None}
    report["denver_descriptive"] = {a: contrast_stats(daily_contrast(all_rows, a, "S", markets=DESCRIPTIVE_MARKETS))
                                    for a in complete}
    report["not_implemented_descriptive"] = ["S_bound (section 2)", "hours 07-12 vs the L6 stack (section 4.4)",
                                             "fold 2026 / V5.0 sliver (not built, section 1.1)"]
    report["per_market_ci_basis"] = ("decisions use ci95_wide (kappa_wide on the market's own series, "
                                     "Clarification 1); ci95 (kappa only) is descriptive")
    report["final_rows_sha256"] = sha256_file(rp) if rp is not None else None
    report["restated_n"] = restated["n"]
    report["post_score_flags"] = flags
    report["status"] = "PASS"
    return report


STAGE_FUNCS = {"controls": stage_controls, "build": stage_build, "integrity": stage_integrity,
               "labels": stage_labels, "look": stage_look, "score": stage_score}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", required=True, choices=STAGES)
    ap.add_argument("--roots", required=True, help="the stage's config JSON (sha256 recorded by the launcher)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--expect-sha", required=True)
    # Ruling 2 (logs): stdout and stderr pass through the guard from the first byte.
    out_stream, err_stream = GuardedStream(sys.stdout), GuardedStream(sys.stderr)
    sys.stdout, sys.stderr = out_stream, err_stream
    a = ap.parse_args(argv)
    own = sha256_file(__file__)
    if own != a.expect_sha.lower():
        print(f"REFUSED: runner sha256 {own} differs from --expect-sha", file=sys.stderr)
        return 3
    cfg = json.loads(Path(a.roots).read_text(encoding="utf-8"))
    if cfg.get("stage") != a.stage:
        print(f"REFUSED: config is for stage {cfg.get('stage')}, not {a.stage}", file=sys.stderr)
        return 3
    out_json, out_csv = Path(a.out_json).resolve(), Path(a.out_csv).resolve()
    # Review R4(a)/(b): the pinned run root only; if the Writer cannot be set up, nothing at all is written.
    try:
        if out_json.parent != out_csv.parent:
            raise Halt("--out-json and --out-csv are in different directories")
        if Path(cfg.get("out_root", "")).resolve() != OUT_ROOT_PIN.resolve():
            raise Halt(f"config out_root is not {OUT_ROOT_PIN}")
        writer = Writer(OUT_ROOT_PIN, out_json.parent)
    except Exception as exc:
        print(f"REFUSED: no writer ({exc!r}); nothing written", file=sys.stderr)
        return 12
    snapshot = out_root_snapshot()
    report = {"runner": "row28_run_v3", "runner_sha256": own, "stage": a.stage, "config_sha256": sha256_file(a.roots),
              "prereg_sha256": PREREG_SHA256, "rulings": {k: v for k, v in globals().items() if k.startswith("RULING_")},
              "start": now()}
    code = 0
    before = None
    try:
        # Review R4(d): metadata manifest of the junctioned subdirectories before and after the stage.
        before = junction_manifest()
        if writer.gz_json("junction_manifest_before.json.gz", before) is None:
            raise Halt("junction manifest withheld by the output guard")
        report["junction_manifest_before_sha256"] = sha256_bytes(json_bytes(before))
        report["junction_manifest_files"] = len(before)
        for name, prev in (cfg.get("prev") or {}).items():
            prev_after = json.loads(Path(guard_read(prev["path"])).read_text(encoding="utf-8")).get(
                "junction_manifest_after_sha256")
            if prev_after != report["junction_manifest_before_sha256"]:
                raise Halt(f"junctioned data changed since stage {name} ended")
        ctx = load_context(cfg)
        report["output_guard_allowlist"] = set_guard_allowlist(ctx.prm)
        report["junctions"] = ctx.junctions
        report.update(STAGE_FUNCS[a.stage](ctx, cfg, writer))
    except Halt as exc:
        if writer.post_score and RULING_N1_NO_HALT_AFTER_SCORE:  # N1: never a HALT once a score exists
            report.update({"status": "ERROR", "reason": "raised after a score existed (not a HALT, N1): " + str(exc)})
            code = 11
        else:
            report.update({"status": "HALT", "halt_scope": exc.scope, "reason": str(exc)})
            code = 10
    except Exception as exc:  # fail closed: the report says why; the launcher marks the run PARTIAL
        report.update({"status": "ERROR", "reason": repr(exc), "traceback": traceback.format_exc()})
        code = 11
    post_stage = a.stage in ("look", "score") and RULING_N1_STAGE_END_MANIFEST == "flag_classified"
    try:
        after = junction_manifest()
        writer.gz_json("junction_manifest_after.json.gz", after)
        report["junction_manifest_after_sha256"] = sha256_bytes(json_bytes(after))
        read = sorted(set(STAGE_READS[a.stage]) | (_OBSERVED_READS & set(JUNCTIONS)))
        report["junction_subdirs_read"] = {"declared": list(STAGE_READS[a.stage]),
                                           "observed_guard_read": sorted(_OBSERVED_READS), "union": read}
        if before is not None:
            diff = manifest_diff(before, after)
            report["manifest_diff"] = diff
            report["manifest_changed"] = diff["changed"]
            if diff["changed"]:
                material = [sub for sub in read if any(diff["by_subdir"][sub].get(k) for k in
                                                       ("added", "removed", "size_changed"))]
                if post_stage:
                    # N1: FLAG for master. mtime-only: noted, the result stands. A size change, or a file added or
                    # removed, in a subdirectory this stage read: arm results are INPUT-CHANGED; master rules
                    # before any verdict is recorded.
                    report["manifest_flag"] = {"diff_count": diff["count"], "input_changed_subdirs": material,
                                               "classification": "INPUT-CHANGED" if material else "mtime-only/unread"}
                    if material:
                        report["arm_results_label"] = "INPUT-CHANGED (master rules before any verdict is recorded)"
                        for key in ("outcomes", "look"):
                            for v in (report.get(key) or {}).values():
                                if isinstance(v, dict):
                                    v["input_changed"] = True
                else:
                    report.update({"status": "HALT", "halt_scope": "run",
                                   "reason": f"junctioned data changed during the stage ({diff['count']} entries "
                                             f"differ; material in {material}); " + str(report.get("reason", ""))})
                    code = 10
    except Exception as exc:
        report.update({"status": "ERROR", "reason": f"after-manifest failed: {exc!r}; " + str(report.get("reason", ""))})
        code = 11
    # Ruling 2: the output guard at stage end, over every new or changed file under the run root and the logs.
    post = writer.post_score
    try:
        og = output_guard_scan(snapshot, [out_json, out_csv, out_json.parent / "walker.stdout",
                                          out_json.parent / "walker.stderr", out_json.parent / "receipt.json"])
        og.update({"writes_withheld": writer.withheld, "log_writes_withheld": {"stdout": out_stream.withheld,
                                                                               "stderr": err_stream.withheld},
                   "pattern": _GUARD_PATTERN, "from": GUARD_FROM, "post_score": post})
        n_hits = og["hits_total"] + len(writer.withheld) + out_stream.withheld + err_stream.withheld
        og["result"] = "HIT" if n_hits else "CLEAN"
        report["output_guard"] = og
        if n_hits:
            if post and RULING_GUARD_POST_SCORE == "withhold_and_flag":
                report["output_guard_flag"] = f"{n_hits} guard hit(s) after a score existed: FLAG for master (N1)"
            else:
                report.update({"status": "HALT", "halt_scope": "run",
                               "reason": f"output guard: {n_hits} hit(s); " + str(report.get("reason", ""))})
                code = 10
    except Exception as exc:
        report.update({"status": "ERROR", "reason": f"output guard failed: {exc!r}; " + str(report.get("reason", ""))})
        code = 11
    report["end"] = now()
    written = writer.written if writer else []
    report["outputs_sha256"] = {str(p): sha256_file(p) for p in written}
    # The report itself: any top-level value holding a disallowed date is withheld (never written) and counted.
    withheld_keys = [k for k in list(report) if k != "output_guard" and guard_obj(report[k])]
    if withheld_keys:
        for k in withheld_keys:
            report[k] = "[withheld by output guard]"
        report.setdefault("output_guard", {})["report_keys_withheld"] = withheld_keys
        if not (post and RULING_GUARD_POST_SCORE == "withhold_and_flag"):
            report["status"] = "HALT"
            report["halt_scope"] = "run"
            code = 10
    out_json.write_bytes(json_bytes(report))
    with open(out_csv, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("path,sha256\n")
        for p, sha in sorted(report["outputs_sha256"].items()):
            handle.write(f"{'[withheld by output guard]' if guard_text(p) else p},{sha}\n")
    print(json.dumps({"stage": a.stage, "status": report.get("status")}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
