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
    python -m tools.research.released_window.rodc_released_p0 parity --out C:\t\l16\rodc\<new>
    python -m tools.research.released_window.rodc_released_p0 parity2 --out C:\t\l16\rodc\<new>
    python -m tools.research.released_window.rodc_released_p0 rehearse-to-table --out C:\t\l16\rodc-rehearse\<new> \
        --coef <fit out>\coef.json --coef-sha <sha256 of coef.json> \
        --parity <parity2 out>\parity2_receipt.json --parity-sha <its sha256>
    python -m tools.research.released_window.rodc_released_p0 look --out C:\t\l16\rodc-look2\<new> \
        <the same --coef / --coef-sha / --parity / --parity-sha> --approval "<LOOK2_APPROVAL, exactly>"

Master's 2026-10-31 rulings: every stage also checks the pin identity (ruling 1); ``parity`` is the pre-look,
outcome-free train/serve parity of the lows (ruling 4) whose ``parity_limited`` flags the look appends to the
affected arm's label. Clarification 2 (``CLARIFICATION2_SHA256``) then rules: C-c keeps the frozen statistic with
exact identities, the m < EPS count and a non-deciding all-m >= EPS sensitivity that turns an unreproduced KILL into
UNRESOLVED; the serve-side 30..125 F filter is a defect, so the look uses the trainer's rule (none, hence the
physical bound >= -40) through a scoped override, and reads only the ``parity2`` receipt; Denver is excluded from
both arms (US10); the projected power at the US10 N is printed and recorded before any Delta. Clarification 3
(``CLARIFICATION3_SHA256``): look1 refused at C-g before any statistic, so C-g compares both sides on the WU whole
scale, ``rehearse-to-table`` runs the look2 front and stops before ``sc.Table``, and look2 lives under a new guard
root with a pinned approval. It is the only repair; there is no look3. Clarification 3a
(``CLARIFICATION3A_SHA256``) amends point 1 after rehearsal r1: inside C-g only, the reference high is the
point-in-time running maximum of the layout's high_so_far over all captures of the same (market, date) at or before
this capture instant (EF 1k ``-09-70a``/``-09-71a``: high_so_far is not a running maximum), on the WU whole scale;
the layout-wide decrease counts are disclosed in the C-g control. No arm input or scored value changes.

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
CLARIFICATION2_PATH = "docs/research/rodc-released-p0-2026-10-31/clarification_2.md"
CLARIFICATION2_SHA256 = "cec81d4fa556866a162e47ee990385f5c471973ced9a1fd35a93d98deef182c2"
CLARIFICATION3_PATH = "docs/research/rodc-released-p0-2026-10-31/clarification_3.md"
CLARIFICATION3_SHA256 = "e9664e4ab24b1ad7ea98324bd0e9ca2013a32f1e86db0f9f82e6d10dc1c0465c"
CLARIFICATION3A_PATH = "docs/research/rodc-released-p0-2026-10-31/clarification_3a.md"
CLARIFICATION3A_SHA256 = "fcb31f6ea6351d1fba1bf7b271a751abca6eab4ecdca8b430f245f16faf0321a"

OUT_ROOT = Path(r"C:\t\l16\rodc")
LOOK_RECEIPT = "look_receipt.json"
LOOK_STARTED = "look_started.json"        # exclusive-created before the release layout is loaded
# Clarification 3: look1 refused at C-g before any statistic; one bounded repair, look2 under a new guard root.
LOOK2_ROOT = Path(r"C:\t\l16\rodc-look2")
REHEARSE_ROOT = Path(r"C:\t\l16\rodc-rehearse")
REHEARSE_RECEIPT = "rehearse_receipt.json"
LOOK1_MARKER_SHA256 = "1f3ee224f8a1775f4360a00543e7a7fbf91a75c7af11ea6344529cbf204d8b93"
LOOK1_REFUSAL_LOG_SHA256 = "68755c85f13da8edbf88758368147c563f9c222bf7cc6f0deb40ebc78b7c871d"
LOOK2_APPROVAL = ("master 10-31 R-ODC row 103 look2: one bounded C-g WU-scale repair (Clarification 3) after look1 "
                  "refused at C-g before any statistic; rehearsal PASS required; no look3")
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
    "src/weather/model/model_climatology.py": "a4eeabf191b7cd2326005ad10c2ea9ef81d32d0a",   # trainer rule (none)
    "src/weather/model/observed_running_max.py": "a141ff3b55e21c097621a9ec21695da1efecc570",
    "src/weather/market/market_registry.py": "c6c8b143a9ded1462ccf6bd32738fa025db4ecdc",
    "tools/research/released_window/served_market_blocks.py": "86b4652c5ac03de43d289ae4cc1e3d6e82544dbf",
}

# Master's ruling 1 (2026-10-31) on the vendored pin blobs, checked at the start of every stage.
# (a) The two observed_running_max functions used here are source-identical between master's a141ff3b and the
#     pin 8bb0f9563's blob 40c84103: sha256 of inspect.getsource, hashes taken from `git cat-file blob 40c84103`.
ORM_PIN_BLOB = "40c8410309dd28a72676f023822bc60f23ed4cd4"
ORM_PIN_SOURCE_SHA256 = {
    "metar_observation_local_time": "50910790030fd49ce0d5dc1b3bb335a4db40ff8bbe37a4b494177ed492116365",
    "row_obs_time_local": "74621d68e98156ad1208628015e48e8e4ac434eb9a005e5fff08cdd1a0803404",
}
ORM_PIN_GROUP_RE = r"\b(\d{2})(\d{2})(\d{2})Z\b"     # the module constant metar_observation_local_time reads
# (b) The loyo_screen constants read from pooled_residual_model a7f9124f equal the pin's (blob 5e991078).
PRM_PIN_BLOB = "5e991078071f7296ae4cc4010e5d0ebfc4c2003c"
PRM_PIN_CONSTANTS = {
    "BOOTSTRAP_DRAWS": 2000,
    "BOOTSTRAP_SEED": 20261024,
    "R0_MARKETS": ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
                   "san-francisco", "seattle"),
}

# Ruling 4: train/serve parity of the lows (history only, outcome-free, recorded, not deciding by itself).
METAR_HISTORY = Path(r"C:\Users\Michael\Documents\github\weather\data\metar")   # IEM ASOS, read only
PARITY_RECEIPT = "parity_receipt.json"
PARITY_MAE_MAX, PARITY_BIAS_MAX = 0.5, 0.3      # deg F; beyond either, in any market, the arm is parity-limited
PARITY_SUFFIX = " [parity-limited; kill scope: this construction only]"
PARITY2_RECEIPT = "parity2_receipt.json"

# Clarification 2 point 2: the serve-side temperature rule. The frozen odc rule (feature_store's 30..125 F) is
# ruled a defect; the trainer path has no plausibility rule, so the look keeps every finite value >= -40 (native;
# -40 F = -40 C). Applied in this driver only, as a scoped override of the predicate odc_metar_features calls.
SERVE_RULE_FROZEN, SERVE_RULE_OFF, SERVE_RULE_TRAINER = "frozen_30F_125F", "filter_off", "trainer_physical_m40"
SERVE_RULES = (SERVE_RULE_FROZEN, SERVE_RULE_OFF, SERVE_RULE_TRAINER)
LOOK_SERVE_RULE = SERVE_RULE_TRAINER
PHYSICAL_LOWER_NATIVE = -40.0
TRAINER_PLAUSIBILITY = {
    "rule": "none in the trainer path; native-unit physical bound: keep finite values >= -40 (F = C), no upper bound",
    "trainer_path": [
        {"file": "src/weather/model/model_climatology.py", "function": "ClimatologyMixin.historical_target_cache",
         "blob": "a4eeabf191b7cd2326005ad10c2ea9ef81d32d0a",
         "sha256": "2d69cb04616fddd29b77c4387fa1cf6bc1d708c96883ebffb711fe15b0c4f43d"},
        {"file": "src/weather/model/feature_store.py", "function": "row_temp_native",
         "blob": "c11b3ca94747b3c1603cbbff9c4eebd4ad83cb4a"},
        {"file": "src/weather/calibration/ols_floor_ladder.py", "function": "overnight_lows",
         "blob": "eedd3d32f5044cf797ba0b053afec83d580974be",
         "sha256": "6e6d100fb5bb2c9c2d811a681a3a88d9458305ef701ba4b8651be34011c12e8e"},
    ],
}
ODC_FROZEN_BLOB = "1cc4d565468bf4959137a8f6f6cec5b10adfce24"   # odc_metar_features.py at 0e11b018f (row 72)

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
# Denver: R-ODC as frozen in row 72 (KDEN vs KBKF); X13 by Clarification 2 point 2(d) (master's amendment).
ARM_UNCOVERED_MARKETS = {ARM_RODC: frozenset({"denver"}), ARM_X13: frozenset()}   # the fit (coef 24bdb0a6) as run
ARM_EXCLUDED_MARKETS = {ARM_RODC: frozenset({"denver"}), ARM_X13: frozenset({"denver"})}   # look and parity: US10
# Parity comparisons per arm: (serve-side METAR feature, trainer-cache column).
ARM_PARITY = {ARM_RODC: (("odc_low_so_far", "low_so_far"),),
              ARM_X13: (("x13_low_so_far", "low_so_far"), ("low_prev_evening", "low_prev_evening"))}
MIN_FIT_ROWS = 30

MIN_DATES, MIN_SNAPS = 10, 1000            # row 80's coverage floor
DELTA_EDGE = 0.2236                       # sqrt(0.05), EXHAUSTION_REGISTER section 6
ROW80_SE = 0.034993730047793145           # row 80's wider per-date SE (label receipt 235736c9)
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
LABEL_UNRESOLVED_EPS = "UNRESOLVED (EPS-path sensitive)"
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
    for rel, want in ((RULE_PATH, RULE_SHA256), (CLARIFICATION_PATH, CLARIFICATION_SHA256),
                      (CLARIFICATION2_PATH, CLARIFICATION2_SHA256), (CLARIFICATION3_PATH, CLARIFICATION3_SHA256),
                      (CLARIFICATION3A_PATH, CLARIFICATION3A_SHA256)):
        got = sha256_file(Path(tree) / rel)
        if got != want:
            raise Refused(f"refused: {rel} sha256 {got} is not the pinned {want}")
        out[rel] = got
    return out


def check_pin_identity(orm=None, prm=None):
    """Ruling 1: (a) the observed_running_max functions this driver uses are source-identical to the pin's;
    (b) the loyo_screen constants from pooled_residual_model equal the pin's values. Refuses on any mismatch."""
    import inspect

    if orm is None:
        from weather.model import observed_running_max as orm
    if prm is None:
        from weather.calibration import pooled_residual_model as prm
    got = {fn: hashlib.sha256(inspect.getsource(getattr(orm, fn)).encode("utf-8")).hexdigest()
           for fn in ORM_PIN_SOURCE_SHA256}
    bad = {fn: g for fn, g in got.items() if g != ORM_PIN_SOURCE_SHA256[fn]}
    if bad:
        raise Refused(f"refused: observed_running_max functions differ from pin blob {ORM_PIN_BLOB}: {bad}")
    if orm.METAR_OBSERVATION_GROUP_RE.pattern != ORM_PIN_GROUP_RE:
        raise Refused("refused: METAR_OBSERVATION_GROUP_RE differs from the pin")
    consts = {k: getattr(prm, k, None) for k in PRM_PIN_CONSTANTS}
    consts = {k: tuple(v) if isinstance(v, (list, tuple)) else v for k, v in consts.items()}
    if consts != PRM_PIN_CONSTANTS:
        raise Refused(f"refused: pooled_residual_model constants {consts} are not the pin's {PRM_PIN_CONSTANTS}")
    return {"orm_pin_blob": ORM_PIN_BLOB, "orm_source_sha256": got, "prm_pin_blob": PRM_PIN_BLOB,
            "prm_constants": {k: list(v) if isinstance(v, tuple) else v for k, v in consts.items()}}


def stage_guards():
    """Every stage's start: origin, clean tree, blobs, rule files, pin identity (ruling 1)."""
    return {"origin": check_origin(), "code": require_clean(code_state()), "blobs": check_blobs(),
            "rules": check_rule_files(), "pin_identity": check_pin_identity()}


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p))).rstrip("\\/")


def _under(path, root):
    a, b = _norm(path), _norm(root)
    return a == b or a.startswith(b + os.sep)


def loaded_weather_files(modules=None):
    """{name: __file__} of every loaded ``weather.*`` submodule (the package itself excluded)."""
    modules = sys.modules if modules is None else modules
    return {n: str(m.__file__) for n, m in sorted(modules.items())
            if n.startswith("weather.") and getattr(m, "__file__", None)}


def check_origin(tree=TREE, environ=None, cwd=None, weather_file=None, submodule_files=None):
    """The editable-.pth trap: PYTHONPATH must be exactly <tree>\\src and cwd the tree; ``weather`` is either the
    tree's repo-root shim (<tree>\\weather\\__init__.py, which prepends <tree>\\src\\weather to ``__path__``) or
    <tree>\\src\\weather; and every loaded ``weather.*`` submodule resolves under <tree>\\src."""
    environ = os.environ if environ is None else environ
    cwd = os.getcwd() if cwd is None else cwd
    if weather_file is None:
        import weather
        import weather.calibration  # noqa: F401  (a real submodule, so the shim's __path__ is exercised)
        weather_file = weather.__file__
    submodule_files = loaded_weather_files() if submodule_files is None else submodule_files
    src = Path(tree) / "src"
    pp = environ.get("PYTHONPATH")
    if pp is None or _norm(pp) != _norm(src):
        raise Refused(f"refused: PYTHONPATH is {pp!r}, not {src}")
    if _norm(cwd) != _norm(tree):
        raise Refused(f"refused: cwd {cwd} is not the run tree {tree}")
    shim = Path(tree) / "weather" / "__init__.py"
    wf = Path(weather_file).resolve()
    if not (_norm(wf) == _norm(shim.resolve()) or _under(wf, src.resolve())):
        raise Refused(f"refused: weather imported from {weather_file}, not this tree's shim or {src}")
    if not submodule_files:
        raise Refused("refused: no weather submodule loaded to check")
    stray = {n: f for n, f in submodule_files.items() if not _under(Path(f).resolve(), src.resolve())}
    if stray:
        raise Refused(f"refused: weather submodules imported from outside {src}: {dict(list(stray.items())[:3])}")
    return {"tree": str(tree), "pythonpath": pp, "cwd": str(cwd), "weather_file": str(weather_file),
            "weather_submodules_checked": len(submodule_files)}


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
    prior = sorted(str(p) for name in (LOOK_STARTED, LOOK_RECEIPT) for p in root.glob(f"*/{name}")) \
        if root.is_dir() else []
    if prior:
        raise Refused(f"refused: a look already ran ({prior[0]}); there is no second look")
    return True


def check_look2_guard(look2_root=None, rodc_root=None):
    """Clarification 3 point 4: refuses when any look_* file exists under the look2 root, or when anything other
    than look1's marker (by sha256) exists under ``rodc_root/*/look_*``. Read-only."""
    look2_root = Path(LOOK2_ROOT if look2_root is None else look2_root)
    rodc_root = Path(OUT_ROOT if rodc_root is None else rodc_root)
    in_look2 = sorted(str(q) for q in look2_root.rglob("look_*")) if look2_root.is_dir() else []
    if in_look2:
        raise Refused(f"refused: a look2 already started ({in_look2[0]}); there is no look3")
    found = sorted(rodc_root.glob("*/look_*")) if rodc_root.is_dir() else []
    others = [str(q) for q in found if q.name != LOOK_STARTED or sha256_file(q) != LOOK1_MARKER_SHA256]
    if others or len(found) > 1:
        raise Refused(f"refused: {others or [str(q) for q in found]} under {rodc_root} is not look1's marker alone")
    return {"look2_root": str(look2_root), "rodc_root": str(rodc_root),
            "look1_marker": str(found[0]) if found else None,
            "look1_marker_sha256": LOOK1_MARKER_SHA256 if found else None}


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
    if isinstance(x, np.bool_):
        return bool(x)
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
    g = stage_guards()
    origin, state, blobs, rules = g["origin"], g["code"], g["blobs"], g["rules"]
    out = check_out_dir(args.out)
    from weather.calibration import ols_floor_ladder as lad

    cache_dir = Path(args.cache_dir)
    cache_files = {f"cache_{m}_{c}.json": sha256_file(cache_dir / f"cache_{m}_{c}.json")
                   for m in US11 for c in OCTDEC_CENTRES}
    cf = control_cf(cache_dir, args.l3_dir)
    caches = lad.load_caches(cache_dir, US11, OCTDEC_CENTRES)
    coef, n_samples = fit_coefficients(caches)
    pl = placebo_beta(caches)
    after = check_origin()
    out.mkdir(parents=True)
    coef_payload = {"schema": SCHEMA + "/coef", "ledger_row": LEDGER_ROW, "arms": coef, "hours": list(HOURS),
                    "centres": list(OCTDEC_CENTRES), "markets": list(US11), "min_fit_rows": MIN_FIT_ROWS,
                    "history_last": HISTORY_LAST.isoformat(), "base": "L3 ols_floor in sample per (market, "
                    "centre, hour); BASE_FEATURES forecast_high, high_so_far, current_temp; impute fc",
                    "cache_sha256": cache_files, "residual_rows": n_samples}
    coef_sha = write_exclusive(out / "coef.json", coef_payload)
    receipt = {"schema": SCHEMA + "/fit", "ledger_row": LEDGER_ROW, "stage": "fit", "origin": origin,
               "origin_after_imports": after, "pin_identity": g["pin_identity"], "code": state, "blobs": blobs, "rules": rules, "module_sha256": sha256_file(__file__),
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


_ACTIVE_RULE = [SERVE_RULE_FROZEN]


def serve_plausible(value, unit, rule=None):
    """The serve-side temperature predicate under ``rule`` (default: the active one)."""
    from weather.model.feature_store import plausible_native_temperature

    rule = _ACTIVE_RULE[0] if rule is None else rule
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(v):
        return False
    if rule == SERVE_RULE_FROZEN:
        return bool(plausible_native_temperature(v, unit))
    if rule == SERVE_RULE_OFF:
        return True
    if rule == SERVE_RULE_TRAINER:
        return v >= PHYSICAL_LOWER_NATIVE
    raise Refused(f"refused: unknown serve temperature rule {rule!r}")


@contextlib.contextmanager
def serve_rule(rule):
    """Scoped in-process override (Clarification 2 point 2): ``odc_metar_features.kept_rows`` and ``x13_lows``
    use ``rule``'s predicate; the frozen module file is not touched and its name is restored on exit."""
    from weather.calibration import odc_metar_features as odc

    if rule not in SERVE_RULES:
        raise Refused(f"refused: unknown serve temperature rule {rule!r}")
    saved, saved_rule = odc.plausible_native_temperature, _ACTIVE_RULE[0]
    odc.plausible_native_temperature = lambda value, unit: serve_plausible(value, unit, rule)
    _ACTIVE_RULE[0] = rule
    try:
        yield {"rule": rule, "patched": "weather.calibration.odc_metar_features.plausible_native_temperature"}
    finally:
        odc.plausible_native_temperature = saved
        _ACTIVE_RULE[0] = saved_rule


def x13_lows(metar, *, target_date, tz, unit, cutoff_hour, now):
    """(low_so_far, low_prev_evening) through ``ols_floor_ladder.overnight_lows`` on the captured METAR rows of D
    and D-1 with an instant <= the capture (and <= h:00 on D), as (minute_of_day, temperature) in memory. Each
    temperature is rounded with ``wu_whole_f(v, "half_up")`` as arm 1 is, because the trainer rows are WU whole
    degrees (master review of ad94217fd, fix 2)."""
    from weather.calibration import ols_floor_ladder as lad
    from weather.model.feature_store import row_temp_native
    from weather.model.mg_serve_core import wu_whole_f

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
        if not math.isfinite(v) or not serve_plausible(v, unit):
            continue
        rec = {"minute_of_day": t.hour * 60 + t.minute, "temp_native": float(wu_whole_f(v, "half_up"))}
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
            "n_rows": f["n_rows"], "n_implausible": implausible_count(d, kept, unit), "skipped": f["skipped"]}


def implausible_count(metar, kept, unit, rule=SERVE_RULE_FROZEN):
    """Kept-window rows (by their index in ``metar``) whose finite numeric temperature ``rule`` rejects; the
    default counts what the frozen odc filter drops (below 30 F, above 125 F) under any active rule."""
    from weather.model.feature_store import row_temp_native

    rows = (metar or {}).get("rows") or []
    n = 0
    for _, i, _, _ in kept:
        try:
            v = float(row_temp_native(rows[i]))
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and not serve_plausible(v, unit, rule):
            n += 1
    return n


def below_count(metar, kept, bound):
    """Kept-window rows with a finite temperature below ``bound`` (native)."""
    from weather.model.feature_store import row_temp_native

    rows = (metar or {}).get("rows") or []
    n = 0
    for _, i, _, _ in kept:
        try:
            v = float(row_temp_native(rows[i]))
        except (TypeError, ValueError):
            continue
        n += bool(math.isfinite(v) and v < bound)
    return n


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


def _finite(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _instant_groups(rows):
    """rows: [(captured, key, raw)] of one (market, date) -> lists of rows sharing one capture instant, in capture
    order (ties broken by str(key) inside an instant; an instant is one group, so the result is tie-insensitive)."""
    rows = sorted(rows, key=lambda r: (r[0], str(r[1])))
    groups = []
    for r in rows:
        if groups and groups[-1][0][0] == r[0]:
            groups[-1].append(r)
        else:
            groups.append([r])
    return groups


def running_max_reference(captures):
    """Clarification 3a point 1: ``captures`` is an iterable of (key, market, date, captured, raw high_so_far).
    Returns {key: wu_whole_f(max raw high_so_far over every capture of the same (market, date) at or before this
    capture instant, "half_up")}, None when no finite value exists yet. Captures sharing an instant see each other
    (all are known at that instant). Rounding is monotone, so this equals the running maximum of the whole values."""
    from weather.model.mg_serve_core import wu_whole_f

    by_cell = defaultdict(list)
    for key, market, day, captured, raw in captures:
        by_cell[(str(market), str(day))].append((captured, key, _finite(raw)))
    ref = {}
    for rows in by_cell.values():
        best = None
        for group in _instant_groups(rows):
            for _, _, raw in group:
                if raw is not None:
                    best = raw if best is None else max(best, raw)
            whole = wu_whole_f(best, "half_up") if best is not None else None
            for _, key, _ in group:
                ref[key] = whole
    return ref


def high_so_far_decreases(captures):
    """Clarification 3a point 2 (disclosure only, no threshold): per market, the snapshots whose high_so_far is
    below the maximum over strictly earlier capture instants of the same (market, date), and the (market, date)
    cells with at least one, on the raw T-group scale and on the WU whole scale."""
    from weather.model.mg_serve_core import wu_whole_f

    by_cell = defaultdict(list)
    for key, market, day, captured, raw in captures:
        by_cell[(str(market), str(day))].append((captured, key, _finite(raw)))
    out = {}
    for scale in ("raw", "wu_whole"):
        per = defaultdict(lambda: {"snapshots": 0, "snapshots_below_earlier": 0, "cells": 0,
                                   "cells_with_decrease": 0})
        for (market, _), rows in sorted(by_cell.items()):
            rec, best, hit = per[market], None, False
            rec["snapshots"] += len(rows)
            rec["cells"] += 1
            for group in _instant_groups(rows):
                vals = [r for _, _, r in group if r is not None]
                if scale == "wu_whole":
                    vals = [wu_whole_f(v, "half_up") for v in vals]
                if best is not None:
                    n = sum(1 for v in vals if v < best - 1e-9)
                    rec["snapshots_below_earlier"] += n
                    hit = hit or n > 0
                if vals:
                    best = max(vals) if best is None else max(best, max(vals))
            rec["cells_with_decrease"] += int(hit)
        out[scale] = {m: dict(per[m]) for m in sorted(per)}
        out[f"total_{scale}"] = {k: sum(v[k] for v in per.values())
                                 for k in ("snapshots", "snapshots_below_earlier", "cells", "cells_with_decrease")}
    return out


def control_cg(snaps_feats, reference=None):
    """C-g (label-free): odc ``check_bounds`` per (market, date) over the last snapshot of each hour, and
    low_so_far <= the reference high wherever both exist. Clarification 3 point 1: both sides on the WU whole scale.
    Clarification 3a point 1: the reference high is the point-in-time running maximum of the layout's high_so_far
    over all captures of the same (market, date) at or before this capture (``running_max_reference``; ``reference``
    is {row_key: whole}, built from every layout capture by ``look_front``; without it, from ``snaps_feats`` alone).
    A low above that running maximum still refuses. This touches no arm input and no scored value. The counts of
    what the frozen raw-high comparison and the Clarification 3 own-snapshot comparison would have refused are
    recorded; ``check_bounds`` never drops or flags a snapshot."""
    from weather.calibration import odc_metar_features as odc
    from weather.model.mg_serve_core import wu_whole_f

    keyed = [(s.get("row_key", i), s) for i, s in enumerate(snaps_feats)]
    if reference is None:
        reference = running_max_reference((k, s["market"], s["date"], s["captured"], s.get("high_so_far"))
                                          for k, s in keyed)
    by_cell, by_cell_raw = defaultdict(dict), defaultdict(dict)
    violations, raw_snaps, own_snaps, lifted = [], 0, 0, 0
    for key, s in sorted(keyed, key=lambda ks: (ks[1]["captured"], str(ks[0]))):
        if key not in reference:
            raise Refused(f"refused: C-g has no running-maximum reference for {key}")
        f = s["feats"]
        low = f.get("odc_low_so_far")
        raw = _finite(s.get("high_so_far"))
        own = wu_whole_f(raw, "half_up") if raw is not None else None
        ref = reference[key]
        if ref is not None and own is not None and ref > own + odc.TOL:
            lifted += 1
        if low is not None and raw is not None and low > raw + odc.TOL:
            raw_snaps += 1
        if low is not None and own is not None and low > own + odc.TOL:
            own_snaps += 1
        if low is not None and ref is not None and low > ref + odc.TOL:
            violations.append((s["market"], s["date"], s["local_hour"], "layout_high_so_far_running_max_wu_whole",
                               low, ref))
        base = {"low_so_far": low, "current_temp": f.get("current_temp")}
        by_cell[(s["market"], s["date"])][s["local_hour"]] = dict(base, high_so_far=ref)
        by_cell_raw[(s["market"], s["date"])][s["local_hour"]] = dict(base, high_so_far=raw)
    checked, refused = 0, []
    for cell, by_hour in sorted(by_cell.items()):
        try:
            checked += odc.check_bounds(by_hour)
        except odc.OdcMetarRefused as exc:
            refused.append((cell, str(exc)))
    raw_cells = 0
    for cell, by_hour in sorted(by_cell_raw.items()):
        try:
            odc.check_bounds(by_hour)
        except odc.OdcMetarRefused:
            raw_cells += 1
    if violations or refused:
        raise Refused(f"refused: C-g feature bounds failed: {violations[:3]} {refused[:3]}")
    return {"cells": len(by_cell), "hours_checked": checked, "scale": "wu_whole_f half_up on both sides",
            "reference": "point-in-time running max of layout high_so_far per (market, date), WU whole (C3a)",
            "snapshots_reference_above_own_high": lifted,
            "own_snapshot_wu_whole_would_refuse": own_snaps,
            "frozen_raw_high_would_refuse": {"snapshots_low_above_raw_high": raw_snaps,
                                             "cells_check_bounds_refuses": raw_cells,
                                             "snapshots_dropped_or_flagged": 0},
            "verdict": "PASS"}


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
    pl_bitwise = None
    for seed in sw.PLACEBO_SEEDS:
        pl, _ = sw.disagreement_placebo(t, c, seed)
        if pl_bitwise is None:
            pl_bitwise = int(np.count_nonzero(pl != expected))
        if len(pl):
            pl_err = max(pl_err, float(np.max(np.abs(pl - expected))))
            if unclipped.any():
                pl_err_unclipped = max(pl_err_unclipped, float(np.max(np.abs(pl - m)[unclipped])))
    ok = c_err <= C_C_TOL and pl_err <= C_C_TOL
    if not ok:
        raise Refused(f"refused: C-c zero-tilt identity failed (c {c_err}, placebo {pl_err})")
    return {"max_abs_c_minus_m": c_err, "max_abs_placebo_minus_clip_renorm_m": pl_err,
            "max_abs_placebo_minus_m_unclipped_snapshots": pl_err_unclipped,
            "bands_bitwise_unequal": {"candidate_vs_m": int(np.count_nonzero(c != m)),
                                      "placebo_seed0_vs_clip_renorm_m": pl_bitwise, "bands": int(len(m))},
            "snapshots_with_m_below_eps": int(clipped_snap.sum()), "snapshots": int(len(t.snaps)),
            "tolerance": C_C_TOL, "ruling": CC_PATH_RULING, "verdict": "PASS"}


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


def all_m_ok(t):
    """Per snapshot: True when every band has m >= EPS (Clarification 2 point 1)."""
    from weather.calibration import market_blend as mb

    below = np.bincount(t.band_snap, weights=(t.p_market < mb.EPS).astype(float), minlength=len(t.snaps))
    return below == 0


def eps_sensitivity(arm, values, t, geo, score_dates, donors, res):
    """Non-deciding: Delta and the D3 interval on the arm's population restricted to snapshots whose every band
    has m >= EPS; the same c and placebos as ``p0_candidate`` (its pooled Delta is reproduced first)."""
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

    def sums(mask):
        band = mask[t.band_snap]
        return (sw.date_sums((c - t.p_market)[band], e[band], didx[band], nd),
                [sw.date_sums((p - t.p_market)[band], e[band], didx[band], nd) for p in pls])

    full_c, full_pl = sums(pop)
    if res.get("testable"):
        whole = sw.paired_delta(full_c, full_pl, sw.boot_counts(nd))
        if abs(whole["delta"] - res["p0"]["delta"]) > 1e-12:
            raise Refused(f"refused: {arm} EPS sensitivity does not reproduce the pooled Delta")
    sub = pop & all_m_ok(t)
    sc_, sp = sums(sub)
    n_dates, n_snaps = int((sc_[0] > 0).sum()), int(sub.sum())
    out = {"population_snapshots": n_snaps, "population_dates": n_dates,
           "dropped_snapshots_m_below_eps": int(pop.sum()) - n_snaps}
    if n_dates < MIN_DATES or n_snaps < MIN_SNAPS:
        out.update(testable=False, p_one_sided=1.0)
        return out
    iv = wider_interval(sc_, sp, nd)
    out.update(testable=True, p_one_sided=iv["p_one_sided"], d3=iv)
    return out


def eps_guard(label, sens_label):
    """Clarification 2 point 1: a full-set KILL that the all-m>=EPS sensitivity does not reproduce is UNRESOLVED."""
    if label == LABEL_KILL and sens_label != LABEL_KILL:
        return LABEL_UNRESOLVED_EPS
    return label


def row80_population():
    """Row 80's population snapshot count from its archived rows (sha-checked)."""
    rows_p = ROW80_ARCHIVE / "outputs" / "look" / "rows.jsonl"
    if sha256_file(rows_p) != ROW80_ROWS_SHA256:
        raise Refused("refused: row 80 rows sha mismatch")
    return sum(int(json.loads(x)["n_snapshots"]) for x in rows_p.read_text(encoding="utf-8").splitlines()
               if x.strip())


def projected_power(n_arm, n_row80, se_row80=ROW80_SE):
    """Clarification 2 point 3: Phi(edge / SE - 1.96), SE = row 80's wider SE * sqrt(N_row80 / N_arm)."""
    from weather.calibration import c3_kill_tier as c3

    if not n_arm:
        return {"n_arm": n_arm, "n_row80": n_row80, "se_projected": None, "power": None}
    se = se_row80 * math.sqrt(n_row80 / n_arm)
    return {"n_arm": int(n_arm), "n_row80": int(n_row80), "se_row80": se_row80, "se_projected": se,
            "power": float(c3.power_at(DELTA_EDGE, se))}


def check_coverage_floor_live(sw):
    """The row 80 floor (10 dates, 1,000 snapshots) is live in the pin's mr_sweep, which ``p0_candidate`` reads
    as module globals at call time; refuses otherwise."""
    if (sw.MIN_DATES, sw.MIN_SNAPS) != (MIN_DATES, MIN_SNAPS):
        raise Refused(f"refused: mr_sweep coverage floor is {(sw.MIN_DATES, sw.MIN_SNAPS)}, not "
                      f"{(MIN_DATES, MIN_SNAPS)}")
    return {"mr_sweep.MIN_DATES": sw.MIN_DATES, "mr_sweep.MIN_SNAPS": sw.MIN_SNAPS}


def begin_look(out, approval):
    """Marks the single look before the release layout is loaded: refuses unless the look2 guard passes
    (Clarification 3 point 4), creates ``out`` (it must not exist; ``check_out_dir`` checked that) and exclusive-creates
    ``look_started.json``. Its sha256 goes into the look receipt. This is the look's only mkdir."""
    check_look2_guard()
    out = Path(out)
    out.mkdir(parents=True)
    return write_exclusive(out / LOOK_STARTED, {
        "schema": SCHEMA + "/look_started", "ledger_row": LEDGER_ROW, "approval": approval,
        "started_utc": datetime.now(timezone.utc).isoformat()})


def write_look_rows(out, rows_out):
    """The look's rows.jsonl, exclusive-create in the ``out`` that ``begin_look`` made (no mkdir here)."""
    path = Path(out) / "rows.jsonl"
    with path.open("x", encoding="utf-8") as fh:
        for r in rows_out:
            fh.write(json.dumps(r, sort_keys=True, default=_default) + "\n")
    return sha256_file(path)


def write_look_receipt(out, receipt):
    """The look receipt, exclusive-create in the ``out`` that ``begin_look`` made (no mkdir here)."""
    return write_exclusive(Path(out) / LOOK_RECEIPT, receipt)


def stage_look(args):
    """look2 (Clarification 3): the pinned approval, the look2 guard, ``--out`` under ``LOOK2_ROOT``, then the
    shared front (``begin_look`` before the release layout load) and the tail."""
    if args.approval != LOOK2_APPROVAL:
        raise Refused("refused: --approval is not the pinned look2 approval (Clarification 3 point 4)")
    guard = check_look2_guard()
    out = check_out_dir(args.out, LOOK2_ROOT)
    ctx = look_front(args, out, mark=lambda o: begin_look(o, args.approval))
    ctx["look2_guard"] = guard
    return look_tail(args, ctx, out)


def stage_rehearse(args):
    """Clarification 3 point 3: the exact look2 front (guards, C-a, C-b, C-d, C-e, release layout load, features,
    C-g, power projection), stopping before ``sc.Table``: no sc.Table, C-c or p0_candidate, no Delta, no look_*
    file. Writes only ``rehearse_receipt.json`` below ``REHEARSE_ROOT``."""
    out = check_out_dir(args.out, REHEARSE_ROOT)
    guard = check_look2_guard()
    ctx = look_front(args, out, mark=None)
    guard_after = check_look2_guard()
    out.mkdir(parents=True)
    gd, feats = ctx["gd"], ctx["feats"]
    receipt = {
        "schema": SCHEMA + "/rehearse", "ledger_row": LEDGER_ROW, "stage": "rehearse-to-table",
        "stopped_before": "sc.Table (no C-c, no p0_candidate, no Delta, no look_* marker)",
        "origin": gd["origin"], "origin_after_imports": ctx["after"], "code": gd["code"], "blobs": gd["blobs"],
        "rules": gd["rules"], "pin_identity": gd["pin_identity"], "module_sha256": sha256_file(__file__),
        "coef_sha256": args.coef_sha, "parity_receipt_sha256": args.parity_sha,
        "parity_limited": ctx["parity"]["parity_limited"], "look2_guard": {"before": guard, "after": guard_after},
        "controls": ctx["controls"], "feature_reasons": dict(ctx["reasons"]),
        "clarification_3a": {"c_g_reference": ctx["controls"]["C-g"].get("reference"),
                             "layout_high_so_far_decreases": ctx["controls"]["C-g"].get(
                                 "layout_high_so_far_decreases")},
        "power_projection_us10": ctx["power_projection"], "dates": ctx["dates"],
        "snapshots_dropped_austin_1003": ctx["dropped"], "export_files_hashed": len(ctx["hashed"]),
        "malformed": ctx["malformed"], "override_in_process": ctx["override"], "serve_rule": ctx["serve_override"],
        "serve_rows_outside_frozen_30F_125F": {"count": sum(f.get("n_implausible", 0) for f in feats.values()),
                                               "kept_window_rows": sum(f.get("n_rows", 0) or 0
                                                                       for f in feats.values())},
    }
    sha = write_exclusive(out / REHEARSE_RECEIPT, receipt)
    print(json.dumps({"rehearse_receipt_sha256": sha, "C-g": ctx["controls"]["C-g"],
                      "power_projection_us10": ctx["power_projection"]}, default=_default))
    return receipt


def look_front(args, out, mark=None):
    """The look2 path up to, not including, ``sc.Table``: guards, coef / parity / C-c-path checks, controls C-a,
    C-b, C-d, C-e, ``mark(out)`` (``begin_look`` in the look, None in the rehearsal) before the release layout load,
    the feature loop under the trainer rule, C-g and the US10 power projection. Never builds the r80 table."""
    gd = stage_guards()
    coef = check_coef(args.coef, args.coef_sha)
    parity = check_parity(args.parity, args.parity_sha)
    cc_paths = check_cc_paths()

    import pandas as pd

    from weather.calibration import mr_gate as mg
    from weather.market.market_registry import spec_for_id
    from weather.reporting.scorecards import dev_scorecard_data as data
    from tools.research.released_window import served_market_blocks as smb

    after = check_origin()
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
    look_started_sha = mark(out) if mark is not None else None
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
    with serve_rule(LOOK_SERVE_RULE) as serve_override:      # Clarification 2 point 2(b)
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
            snaps_feats.append({"row_key": str(r.row_key), "market": str(r.market), "date": str(r.date),
                                "local_hour": int(r.local_hour), "captured": captured, "feats": f,
                                "high_so_far": float(hsf)})
    # Clarification 3a: the C-g reference sees every layout capture of the (market, date), not only HOURS.
    all_caps = [(str(r.row_key), str(r.market), str(r.date), _utc(r.captured_at_utc), getattr(r, "high_so_far", None))
                for r in snaps.itertuples(index=False)]
    if any(c[3] is None for c in all_caps):
        raise Refused("refused: a layout capture has no capture time (C-g running-maximum reference)")
    reference = running_max_reference(all_caps)
    controls["C-g"] = control_cg(snaps_feats, reference=reference)
    controls["C-g"]["layout_high_so_far_decreases"] = high_so_far_decreases(all_caps)

    # Clarification 2 point 3: projected power at the US10 N, from features and coefficients only, before any Delta.
    n_row80 = row80_population()
    power_projection = {}
    for arm in ARMS:
        n_arm = 0
        for r in sel.itertuples(index=False):
            k, mk = str(r.row_key), str(r.market)
            if mk in ARM_EXCLUDED_MARKETS[arm] or k not in feats:
                continue
            n_arm += increment(coef["arms"].get(arm, {}).get(f"{mk}|{int(r.local_hour)}"),
                               arm_columns(arm, feats[k])) is not None
        power_projection[arm] = projected_power(n_arm, n_row80)
    print(json.dumps({"power_projection_us10": power_projection}, default=_default), flush=True)
    return {"gd": gd, "after": after, "controls": controls, "lay": lay, "dates": dates, "feats": feats,
            "reasons": reasons, "coef": coef, "parity": parity, "cc_paths": cc_paths, "serve_override": serve_override,
            "power_projection": power_projection, "override": override, "hashed": hashed, "malformed": malformed,
            "dropped": dropped, "look_started_sha": look_started_sha}


def look_tail(args, ctx, out, t=None):
    """From ``sc.Table`` (labels and prices are read from here on) to rows.jsonl and look_receipt.json in the
    ``out`` that ``begin_look`` made. ``t`` is built from ``ctx["lay"]`` unless given (functional test)."""
    from weather.calibration import mr_sweep as sw
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    gd, after, controls, lay, dates = ctx["gd"], ctx["after"], ctx["controls"], ctx["lay"], ctx["dates"]
    origin, state, blobs, rules = gd["origin"], gd["code"], gd["blobs"], gd["rules"]
    feats, reasons, coef, parity, cc_paths = ctx["feats"], ctx["reasons"], ctx["coef"], ctx["parity"], ctx["cc_paths"]
    serve_override, power_projection, override = ctx["serve_override"], ctx["power_projection"], ctx["override"]
    hashed, malformed, dropped, look_started_sha = ctx["hashed"], ctx["malformed"], ctx["dropped"], \
        ctx["look_started_sha"]
    r80_manifest = R80_LAYOUT / data.MANIFEST
    dev_manifest = DEV_LAYOUT / data.MANIFEST

    # The r80 table (labels and prices are read from here on).
    if t is None:
        t = sc.Table(lay, dates)
    geo = sw.band_geometry(t)
    controls["C-c"] = control_cc(t, geo)
    controls["C-e"]["fit_equals_score"] = control_restrict_identity(t)
    sw.MIN_DATES, sw.MIN_SNAPS = MIN_DATES, MIN_SNAPS
    coverage_floor = check_coverage_floor_live(sw)
    score_dates = np.array(dates)
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(t, seed) for seed in sw.PLACEBO_SEEDS}
    keys, hours, markets = t.snaps.row_key.astype(str).to_numpy(), t.local_hour, t.markets
    results, rows_out, pvals, sens_p = {}, [], [], []
    for arm in ARMS:
        g = np.full(len(keys), np.nan)
        for i, (k, h, mk) in enumerate(zip(keys, hours, markets)):
            if int(h) not in HOURS or mk in ARM_EXCLUDED_MARKETS[arm] or k not in feats:
                continue
            inc = increment(coef["arms"].get(arm, {}).get(f"{mk}|{int(h)}"), arm_columns(arm, feats[k]))
            if inc is not None:
                g[i] = inc
        check_coverage_floor_live(sw)
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
        entry["eps_sensitivity"] = eps_sensitivity(arm, geo["mu"] + g, t, geo, score_dates, donors, res)
        sens_p.append(entry["eps_sensitivity"]["p_one_sided"])
        for r in arm_rows:
            rows_out.append(dict(r, arm=arm))
        pvals.append(res["p0"]["p_one_sided"] if res["testable"] else 1.0)
        results[arm] = entry
    adj, reject = bh_table(pvals)
    sens_adj, sens_reject = bh_table(sens_p)
    for (arm, entry), q, rej, sq, srej in zip(results.items(), adj, reject, sens_adj, sens_reject):
        d3 = entry.get("d3") or {}
        lo, hi = (d3.get("ci95_wider") or [None, None])
        entry["bh"] = {"q_value": q, "reject": rej}
        full_label = label_for(entry["result"]["testable"], d3.get("power_at_edge"), hi, lo, rej)
        sens = entry["eps_sensitivity"]
        sd3 = sens.get("d3") or {}
        slo, shi = (sd3.get("ci95_wider") or [None, None])
        sens["bh"] = {"q_value": sq, "reject": srej}
        sens["label"] = label_for(sens["testable"], sd3.get("power_at_edge"), shi, slo, srej)
        entry["full_set_label"] = full_label
        entry["label"] = label_with_parity(eps_guard(full_label, sens["label"]), parity["parity_limited"][arm])
        entry["kill_scope"] = "this construction only" if parity["parity_limited"][arm] else "as registered"
        entry["register_text"] = REGISTER_TEXT[arm]

    if sha256_file(r80_manifest) != R80_LAYOUT_MANIFEST_SHA256 or sha256_file(dev_manifest) != \
            DEV_LAYOUT_MANIFEST_SHA256:
        raise Refused("refused: a layout manifest changed during the run; no receipt")
    write_look_rows(out, rows_out)
    receipt = {
        "schema": SCHEMA + "/look", "ledger_row": LEDGER_ROW, "stage": "look", "approval": args.approval, "origin_after_imports": after,
        "pin_identity": gd["pin_identity"], "parity_receipt_sha256": args.parity_sha,
        "clarification_2": {"serve_rule": serve_override, "trainer_plausibility": TRAINER_PLAUSIBILITY,
                            "arm_excluded_markets": {a: sorted(v) for a, v in ARM_EXCLUDED_MARKETS.items()},
                            "power_projection_us10": power_projection, "coverage_floor_live": coverage_floor},
        "parity_limited": parity["parity_limited"], "cc_paths": cc_paths,
        "serve_rows_outside_frozen_30F_125F": {"count": sum(f.get("n_implausible", 0) for f in feats.values()),
                                        "kept_window_rows": sum(f.get("n_rows", 0) or 0 for f in feats.values())},
        "evidence_class": "kill-only on released dates; no label is an edge claim",
        "origin": origin, "code": state, "blobs": blobs, "rules": rules, "module_sha256": sha256_file(__file__),
        "coef_sha256": args.coef_sha, "r80_layout_manifest_sha256": R80_LAYOUT_MANIFEST_SHA256,
        "dev_layout_manifest_sha256": DEV_LAYOUT_MANIFEST_SHA256, "export_sums_sha256": R80_SUMS_SHA256,
        "export_files_hashed": len(hashed), "malformed": malformed, "override_in_process": override,
        "look_started_sha256": look_started_sha,
        "clarification_3": {"look2_guard": ctx.get("look2_guard"), "look1_marker_sha256": LOOK1_MARKER_SHA256,
                            "look1_refusal_log_sha256": LOOK1_REFUSAL_LOG_SHA256, "approval_pinned": LOOK2_APPROVAL,
                            "c_g_scale": controls.get("C-g", {}).get("scale")},
        "clarification_3a": {"c_g_reference": controls.get("C-g", {}).get("reference"),
                             "layout_high_so_far_decreases": controls.get("C-g", {}).get(
                                 "layout_high_so_far_decreases")},
        "dates": dates, "snapshots_dropped_austin_1003": dropped, "feature_reasons": dict(reasons),
        "controls": controls, "k": len(ARMS), "bh_q": BH_Q, "delta_edge": DELTA_EDGE, "power_min": POWER_MIN,
        "coverage_floor": {"dates": MIN_DATES, "snapshots": MIN_SNAPS}, "mechanism": MECHANISM,
        "arms": results, "rows_sha256": sha256_file(out / "rows.jsonl"),
    }
    receipt_sha = write_look_receipt(out, receipt)
    print(json.dumps({arm: {"label": e["label"], "power": (e.get("d3") or {}).get("power_at_edge"),
                            "ci95_wider": (e.get("d3") or {}).get("ci95_wider")} for arm, e in results.items()}))
    print("receipt", receipt_sha)
    return receipt


# ----------------------------------------------------------------------------- preflight and CLI

# ----------------------------------------------------------------------------- ruling 2: the C-c path audit

CC_PATH_RULING = ("master 10-31 C-c: frozen statistic; exact identities as above; m<EPS count; "
                  "all-m>=EPS sensitivity guards KILL")   # Clarification 2 point 1


def cc_path_audit(sw=None):
    """Which clip / renormalisation each side of the frozen statistic goes through (source read of the pin's
    ``mr_sweep.tilt`` and ``mr_sweep.disagreement_placebo``)."""
    import inspect

    if sw is None:
        from weather.calibration import mr_sweep as sw
    out = {}
    for side, fn in (("candidate", sw.tilt), ("placebo", sw.disagreement_placebo)):
        src = inspect.getsource(fn)
        out[side] = {"function": f"mr_sweep.{fn.__name__}",
                     "source_sha256": hashlib.sha256(src.encode("utf-8")).hexdigest(),
                     "clip_to_eps": "np.clip(" in src and "mb.EPS" in src,
                     "renormalised_to_sum_m": ("geo[\"tot\"]" in src) or ("tot_m / tot_r" in src)}
    out["identical_clip_and_renormalisation"] = (out["candidate"]["clip_to_eps"] == out["placebo"]["clip_to_eps"]
                                                 and out["candidate"]["renormalised_to_sum_m"]
                                                 == out["placebo"]["renormalised_to_sum_m"])
    return out


def check_cc_paths(ruling=None):
    """The frozen pin's candidate and placebo do not share a clip / renormalisation path (the candidate's tilt is
    renormalised to sum(m) with no EPS clip; the placebo is clipped to [EPS, 1] and renormalised to sum(m)). The look
    refuses unless master's ruling is pinned (Clarification 2 point 1: ``CC_PATH_RULING``)."""
    ruling = CC_PATH_RULING if ruling is None else ruling
    audit = cc_path_audit()
    if not audit["identical_clip_and_renormalisation"] and not ruling:
        raise Refused("refused: C-c candidate and placebo do not share the clip / renormalisation path in the "
                      f"frozen mr_sweep ({audit['candidate']['clip_to_eps']} vs {audit['placebo']['clip_to_eps']}); "
                      "awaiting master's ruling")
    return dict(audit, ruling=ruling)


# ----------------------------------------------------------------------------- ruling 4: train/serve parity

def label_with_parity(label, limited):
    return label + PARITY_SUFFIX if limited else label


def check_parity(path, want_sha):
    """The look reads the parity receipt by sha; it refuses when the receipt is missing or differs."""
    if not path or not Path(path).is_file():
        raise Refused(f"refused: the parity receipt {path} is missing")
    if not want_sha or not re.fullmatch(r"[0-9a-f]{64}", str(want_sha)):
        raise Refused("refused: --parity-sha (the recorded sha256 of parity_receipt.json) is required")
    got = sha256_file(path)
    if got != want_sha:
        raise Refused(f"refused: parity receipt sha256 {got} is not --parity-sha {want_sha}")
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    if rec.get("schema") != SCHEMA + "/parity2" or rec.get("ledger_row") != LEDGER_ROW:
        raise Refused("refused: the look reads only this row's parity2 receipt (Clarification 2 point 2)")
    if rec.get("look_serve_rule") != LOOK_SERVE_RULE:
        raise Refused(f"refused: parity2 decided under {rec.get('look_serve_rule')!r}, not {LOOK_SERVE_RULE!r}")
    if rec.get("odc_metar_features_blob") != ODC_FROZEN_BLOB:
        raise Refused("refused: parity2 ran on a changed odc_metar_features.py")
    if rec.get("arm_excluded_markets") != {a: sorted(v) for a, v in ARM_EXCLUDED_MARKETS.items()}:
        raise Refused("refused: parity2's market exclusions are not the look's")
    dec = (rec.get("runs") or {}).get(LOOK_SERVE_RULE) or {}
    if not dec.get("deciding") or dec.get("parity_limited") != rec.get("parity_limited"):
        raise Refused("refused: parity2's flags are not those of its deciding (trainer-rule) table")
    limited = rec.get("parity_limited") or {}
    if set(limited) != set(ARMS) or not all(isinstance(v, bool) for v in limited.values()):
        raise Refused("refused: the parity receipt has no parity_limited flag for every arm")
    return {"parity_limited": limited, "sha256": got}


def read_metar_history(metar_dir, icao, months):
    """{local_date: [serve-form row]} from the IEM ASOS history partitions of ``months`` [(year, month)], each
    partition checked against the station manifest's sha256; plus {partition: sha256}."""
    root = Path(metar_dir) / icao
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    listed = {p["path"]: p["sha256"] for p in manifest.get("partitions") or []}
    by_date, hashed = defaultdict(list), {}
    for y, m in sorted(months):
        rel = f"hourly/year={y}/month={m:02d}/observations.jsonl"
        if rel not in listed:
            continue
        body = (root / rel).read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != listed[rel]:
            raise Refused(f"refused: {icao}/{rel} sha256 differs from its manifest")
        hashed[f"{icao}/{rel}"] = digest
        for line in body.decode("utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("local_date") and r.get("valid_time_local"):
                by_date[r["local_date"]].append({"obs_time": r["valid_time_local"],
                                                 "temp_native": r.get("temp_native"),
                                                 "dewpoint_native": r.get("dewpoint_native")})
    return by_date, hashed


def parity_records(caches, metar_by_market, tz_of, unit_of, hours=HOURS, rule=SERVE_RULE_FROZEN):
    """One record per unique (market, date, hour) of the history caches: the trainer-cache lows and the lows the
    serve code (odc_features, x13_lows) gives on that day's METAR history at cutoff h:00 local, under the serve
    temperature ``rule`` (Clarification 2; the frozen odc rule by default)."""
    with serve_rule(rule):
        return _parity_records(caches, metar_by_market, tz_of, unit_of, hours)


def _parity_records(caches, metar_by_market, tz_of, unit_of, hours):
    from weather.calibration import odc_metar_features as odc

    seen, out, conflicts = {}, [], 0
    for c in caches:
        market = c["market_id"]
        for hour in hours:
            for r in c["hours"].get(str(hour)) or []:
                d = date.fromisoformat(r["date"])
                if d > HISTORY_LAST:
                    raise Refused(f"refused: history cache row {market} {r['date']} after {HISTORY_LAST}")
                key = (market, r["date"], int(hour))
                cache_vals = (r.get("low_so_far"), r.get("low_prev_evening"))
                if key in seen:
                    conflicts += seen[key] != cache_vals
                    continue
                seen[key] = cache_vals
                tz, unit = tz_of[market], unit_of[market]
                metar_rows = metar_by_market[market]
                rows = (metar_rows.get((d - timedelta(days=1)).isoformat(), [])
                        + metar_rows.get(r["date"], []))
                cutoff = datetime.combine(d, time(int(hour), 0), tzinfo=tz)
                metar = {"rows": rows}
                f = odc.odc_features(metar, target_date=d, tz=tz, unit=unit, cutoff_hour=hour, now=cutoff)
                kept, _ = odc.kept_rows(metar, target_date=d, tz=tz, unit=unit, cutoff_hour=hour, now=cutoff)
                lo, lo_prev = x13_lows(metar, target_date=d, tz=tz, unit=unit, cutoff_hour=hour, now=cutoff)
                out.append({"market": market, "date": r["date"], "hour": int(hour),
                            "cache": {"low_so_far": cache_vals[0], "low_prev_evening": cache_vals[1]},
                            "serve": {"odc_low_so_far": f["low_so_far"], "x13_low_so_far": lo,
                                      "low_prev_evening": lo_prev},
                            "kept_rows": len(kept), "implausible": implausible_count(metar, kept, unit),
                            "dropped_by_rule": implausible_count(metar, kept, unit, _ACTIVE_RULE[0]),
                            "below_m40": below_count(metar, kept, PHYSICAL_LOWER_NATIVE)})
    return out, conflicts


def parity_table(records, markets=US11):
    """Per market and comparison: n, MAE, max |diff| and bias (serve METAR - cache), deg F; and the arm flags."""
    comps = sorted({pair for pairs in ARM_PARITY.values() for pair in pairs})
    table = {}
    for mk in markets:
        recs = [r for r in records if r["market"] == mk]
        row = {}
        for serve_col, cache_col in comps:
            diffs = np.array([float(r["serve"][serve_col]) - float(r["cache"][cache_col]) for r in recs
                              if r["serve"][serve_col] is not None and r["cache"][cache_col] is not None], float)
            row[f"{serve_col}-vs-{cache_col}"] = {
                "n": int(len(diffs)), "mae": float(np.mean(np.abs(diffs))) if len(diffs) else None,
                "max_abs": float(np.max(np.abs(diffs))) if len(diffs) else None,
                "bias": float(np.mean(diffs)) if len(diffs) else None}
        kept = sum(r["kept_rows"] for r in recs)
        dropped = sum(r["implausible"] for r in recs)
        row["implausible_below_30F"] = {"dropped": dropped, "kept_window_rows": kept,
                                        "share": dropped / kept if kept else None}
        if recs and "dropped_by_rule" in recs[0]:
            row["dropped_by_rule"] = sum(r["dropped_by_rule"] for r in recs)
            row["below_m40"] = sum(r["below_m40"] for r in recs)
        table[mk] = row
    limited, reasons = {}, {}
    for arm, pairs in ARM_PARITY.items():
        why = []
        for mk in markets:
            if mk in ARM_EXCLUDED_MARKETS[arm]:
                continue
            for serve_col, cache_col in pairs:
                s = table[mk][f"{serve_col}-vs-{cache_col}"]
                if s["n"] == 0:
                    why.append((mk, serve_col, "no_overlap"))
                elif s["mae"] > PARITY_MAE_MAX or abs(s["bias"]) > PARITY_BIAS_MAX:
                    why.append((mk, serve_col, round(s["mae"], 4), round(s["bias"], 4)))
        limited[arm], reasons[arm] = bool(why), why
    return table, limited, reasons


def stage_parity(args):
    """Ruling 4: pre-look, outcome-free train/serve parity of the lows on history <= 2025-12-31 (no labels, no
    prices; the cache ``actual`` column is never read)."""
    g = stage_guards()
    out = check_out_dir(args.out)
    caches, cache_files, tz_of, unit_of, metar_by_market, hashed, icao_of = parity_inputs(args)
    records, conflicts = parity_records(caches, metar_by_market, tz_of, unit_of)
    table, limited, reasons = parity_table(records)
    after = check_origin()
    out.mkdir(parents=True)
    with (out / "parity_rows.jsonl").open("x", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True, default=_default) + "\n")
    tot_kept = sum(r["kept_rows"] for r in records)
    tot_drop = sum(r["implausible"] for r in records)
    receipt = {"schema": SCHEMA + "/parity", "ledger_row": LEDGER_ROW, "stage": "parity", "origin": g["origin"],
               "origin_after_imports": after, "code": g["code"], "blobs": g["blobs"], "rules": g["rules"],
               "pin_identity": g["pin_identity"], "module_sha256": sha256_file(__file__),
               "evidence_class": "pre-look, outcome-free, recorded, not deciding by itself",
               "definition": "serve: odc_features / x13_lows on IEM ASOS METAR history of D and D-1, cutoff and "
                             "capture instant h:00 local on D; cache: L9 trainer rows (WU history), same "
                             "local day and cutoff; diff = serve - cache, deg F",
               "thresholds": {"mae_max": PARITY_MAE_MAX, "abs_bias_max": PARITY_BIAS_MAX},
               "cache_sha256": cache_files, "metar_station": icao_of, "metar_files_sha256": hashed,
               "records": len(records), "cache_centre_conflicts": conflicts,
               "implausible_below_30F_all": {"dropped": tot_drop, "kept_window_rows": tot_kept,
                                             "share": tot_drop / tot_kept if tot_kept else None},
               "table": table, "parity_limited": limited, "parity_reasons": reasons,
               "rows_sha256": sha256_file(out / "parity_rows.jsonl")}
    sha = write_exclusive(out / PARITY_RECEIPT, receipt)
    print(json.dumps({"parity_receipt_sha256": sha, "parity_limited": limited, "reasons": reasons,
                      "implausible_below_30F_all": receipt["implausible_below_30F_all"],
                      "cache_centre_conflicts": conflicts, "records": len(records)}, default=_default))
    return receipt


def stage_parity2(args):
    """Clarification 2 point 2: the one bounded parity rerun on history <= 2025-12-31. Two tables in one run: the
    serve filter OFF (confirms the mechanism, decides nothing) and the look's trainer rule (decides). Denver is
    reported but decides nothing (excluded from both arms)."""
    g = stage_guards()
    out = check_out_dir(args.out)
    caches, cache_files, tz_of, unit_of, metar_by_market, hashed, icao_of = parity_inputs(args)
    runs = {}
    for rule in (SERVE_RULE_OFF, LOOK_SERVE_RULE):
        records, conflicts = parity_records(caches, metar_by_market, tz_of, unit_of, rule=rule)
        table, limited, reasons = parity_table(records)
        runs[rule] = {"records": records, "conflicts": conflicts, "table": table, "limited": limited,
                      "reasons": reasons}
    after = check_origin()
    out.mkdir(parents=True)
    summary = {}
    for rule, run in runs.items():
        name = f"parity2_rows_{rule}.jsonl"
        with (out / name).open("x", encoding="utf-8") as fh:
            for r in run["records"]:
                fh.write(json.dumps(r, sort_keys=True, default=_default) + "\n")
        summary[rule] = {"rows_file": name, "rows_sha256": sha256_file(out / name), "records": len(run["records"]),
                         "cache_centre_conflicts": run["conflicts"], "table": run["table"],
                         "parity_limited": run["limited"], "parity_reasons": run["reasons"],
                         "deciding": rule == LOOK_SERVE_RULE}
    dec = runs[LOOK_SERVE_RULE]
    receipt = {"schema": SCHEMA + "/parity2", "ledger_row": LEDGER_ROW, "stage": "parity2", "origin": g["origin"],
               "origin_after_imports": after, "code": g["code"], "blobs": g["blobs"], "rules": g["rules"],
               "pin_identity": g["pin_identity"], "module_sha256": sha256_file(__file__),
               "evidence_class": "pre-look, outcome-free, recorded; Clarification 2 point 2",
               "definition": "as parity1, under a serve temperature rule; diff = serve - cache, deg F",
               "thresholds": {"mae_max": PARITY_MAE_MAX, "abs_bias_max": PARITY_BIAS_MAX},
               "look_serve_rule": LOOK_SERVE_RULE, "trainer_plausibility": TRAINER_PLAUSIBILITY,
               "odc_metar_features_blob": git_blob_sha(TREE / "src/weather/calibration/odc_metar_features.py"),
               "arm_excluded_markets": {a: sorted(v) for a, v in ARM_EXCLUDED_MARKETS.items()},
               "cache_sha256": cache_files, "metar_station": icao_of, "metar_files_sha256": hashed,
               "runs": summary, "parity_limited": dec["limited"], "parity_reasons": dec["reasons"]}
    sha = write_exclusive(out / PARITY2_RECEIPT, receipt)
    print(json.dumps({"parity2_receipt_sha256": sha, "parity_limited": dec["limited"], "reasons": dec["reasons"],
                      "off_parity_limited": runs[SERVE_RULE_OFF]["limited"],
                      "off_reasons": runs[SERVE_RULE_OFF]["reasons"]}, default=_default))
    return receipt


def parity_inputs(args):
    """The L9 caches and the sha-checked IEM ASOS history partitions every parity stage reads."""
    from weather.calibration import ols_floor_ladder as lad
    from weather.market.market_registry import spec_for_id

    cache_dir = Path(args.cache_dir)
    cache_files = {f"cache_{m}_{c}.json": sha256_file(cache_dir / f"cache_{m}_{c}.json")
                   for m in US11 for c in OCTDEC_CENTRES}
    caches = lad.load_caches(cache_dir, US11, OCTDEC_CENTRES)
    tz_of, unit_of, metar_by_market, hashed, icao_of = {}, {}, {}, {}, {}
    for mk in US11:
        spec = spec_for_id(mk)
        if spec.unit != "F":
            raise Refused(f"refused: {mk} is not a Fahrenheit market")
        tz_of[mk], unit_of[mk], icao_of[mk] = spec.tz, spec.unit, spec.icao.lower()
        months = set()
        for c in caches:
            if c["market_id"] != mk:
                continue
            for rows in c["hours"].values():
                for r in rows:
                    d = date.fromisoformat(r["date"])
                    for x in (d, d - timedelta(days=1)):
                        months.add((x.year, x.month))
        metar_by_market[mk], h = read_metar_history(args.metar_dir, icao_of[mk], months)
        hashed.update(h)
    return caches, cache_files, tz_of, unit_of, metar_by_market, hashed, icao_of


def stage_preflight(args):
    """Origin, clean tree, rule and blob shas, pin identity, imports; reads no data."""
    gd = stage_guards()
    origin, state, blobs, rules = gd["origin"], gd["code"], gd["blobs"], gd["rules"]
    with contextlib.redirect_stdout(sys.stderr):
        from weather.calibration import c3_kill_tier  # noqa: F401
        from weather.calibration import mr_sweep  # noqa: F401
        from weather.calibration import odc_metar_features  # noqa: F401
        from weather.calibration import ols_floor_ladder  # noqa: F401
        from tools.research.released_window import served_market_blocks  # noqa: F401
    after = check_origin()                      # every weather.* module the run imports, now loaded
    out = {"stage": "preflight", "origin": origin, "origin_after_imports": after, "code": state, "rules": rules,
           "pin_identity": gd["pin_identity"],
           "blobs_checked": len(blobs),
           "module_sha256": sha256_file(__file__), "verdict": "PASS"}
    print(json.dumps(out, indent=1, sort_keys=True))
    return out


def build_parser():
    ap = argparse.ArgumentParser(prog="tools.research.released_window.rodc_released_p0",
                                 description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="stage", required=True)
    for name in ("preflight", "fit", "parity", "parity2", "look", "rehearse-to-table"):
        p = sub.add_parser(name)
        if name != "preflight":
            p.add_argument("--out", required=True)
        if name == "fit":
            p.add_argument("--cache-dir", default=str(L9_CACHE))
            p.add_argument("--l3-dir", default=str(L3_OCTDEC))
        if name in ("parity", "parity2"):
            p.add_argument("--cache-dir", default=str(L9_CACHE))
            p.add_argument("--metar-dir", default=str(METAR_HISTORY))
        if name in ("look", "rehearse-to-table"):
            p.add_argument("--coef", required=True)
            p.add_argument("--coef-sha", required=True)
            p.add_argument("--parity", required=True)
            p.add_argument("--parity-sha", required=True)
        if name == "look":
            p.add_argument("--approval", required=True)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        {"preflight": stage_preflight, "fit": stage_fit, "parity": stage_parity, "parity2": stage_parity2,
         "look": stage_look, "rehearse-to-table": stage_rehearse}[args.stage](args)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
