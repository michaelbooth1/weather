r"""Item 343b: the durable offline year-round refit of row 28's candidate B (research and shadow only).

Row 28's candidate **B** is the season-matched P3d_N_fix refit: it trains on Dec 17 - May 31 rows only, with the
centre set ``JAN_JUL_CENTRES[:10] + ("2026-12-24",)`` (``prereg_row28.md`` sha256 cb6d4e8d..., sections 3.2 and 4).
This module ports the fit half of row 28's frozen runner ``row28_run_v12.py`` (sha256 9e97c892...) into library
code and adds a shadow emitter on captured inputs. Design: ``docs/research/item343b-yearround-module-design-
2026-11-03.md`` (accepted by master 2026-11-03, with the BUILD GO rulings below). It serves nothing.

Commands (offline; admitted on the workstation by ``scripts\ops\workstation_heavy.ps1 -Kind weather_heavy``):

* ``fit --arm B --config <cfg.json> --records-root <dir>``: builds the record windows through the bound
  ``extract_market`` (into the REQUIRED ``--records-root``, outside the repository as the bound extractor
  requires; master review 2026-11-03: a CLI argument, never a config key, env var or committed path), fits B's forward state
  (fold 2026: every B row dated at or before 2025-12-16, no season-year held out) and writes ``p3d_n_state.pkl``,
  its sidecar and ``fit_manifest.json`` write-once under ``data/yearround_refit/row28_B/<fit_id>/``. It then
  copies the three files into the never-cleaned archive ``C:\archive\row28b-forward-state\<fit_id>\`` and
  verifies each copy sha-equal (master ruling 1).
* ``emit``: B's shadow distributions for one weekly batch of the forward window, ``as_of_capture`` inputs only
  (master Q-W). It prints ``shadow_rows_sha256`` and ``emit_receipt_sha256`` for the same-day hand-off to master.
* ``equivalence``: the module against the frozen v12 runner (loaded in-process by sha) on a new records root:
  (a) records payload shas against the frozen path/sha list and the y-free frame against v12's ``market_frame``,
  (b) every training row-key set (arms A and B, hours 13-16, folds 2021-2025 and B's fold 2026), (c) fits and
  predictions. Mode ``state_sha`` (the default, master Q-E via L59: the frozen rows keep no per-row yhat/s for B)
  compares a v12 re-fit's state sha and serve outputs to 1e-12; mode ``per_row`` also compares a label-free
  per-row yhat/s extract. No Brier, log loss, label or price is compared or written.

Master's BUILD GO rulings (2026-11-03), as built:

* Q-S: ``fit_kind`` is ``"forward"`` with BOTH guards: ``emit`` refuses a state whose sha is any sha in MG-2's
  ``release-binding.json``, and ``fit`` refuses to write a state whose sha is the bound P3d_N ``c6cc39f7...``.
* Q-G: v12's date-token output guard is not ported. Instead: hard date bounds in code (``fit`` refuses a training
  row outside :data:`TRAINING_WINDOW`; ``emit`` refuses a date outside :data:`EMISSION_WINDOW`, the forward
  receipt's window or the batch), and a static ratchet plus a sentinel test that this module imports no label or
  price reader (venue labels, the settlement ledger, CLOB or price modules).
* Q-W: after-the-fact emission on the workstation; no daily task and no Scheduler change. The state is frozen
  before :data:`FROZEN_BEFORE_UTC`; weekly batches from 12-21.
* Leap day (ruling 3): v12 KEEPS the 2024-02-29 training row and MAPS only its centre, by Rule L, to the same
  year's Feb 28 (``centre_for``, row28_run_v12.py:1595-1600, applied by ``with_arm_centres`` at 2004-2008; the
  wrap check ``circular_picks`` at 1603-1606 maps it the same way). Its doy and every other field keep the real
  date (``pooled_residual_model.pooled_frame``). :func:`centre_for` reproduces that exactly; the training
  row-key-set sha in equivalence (b) is the proof. ``emit`` refuses a Feb 29 target (the forward window has
  none; MG-2's ``nearest_centre`` has no Rule L).
* The module is never imported by a capture loop (runtime refusal below, and an AST ratchet in the tests).

Master's review rulings (2026-11-03, L16 review), each a hard refusal BY NAME:

* Records: a fail-closed extract or a centre with no covered year refuses fit, freeze and equivalence; a reused
  records root needs this module's source sha, the full expected record set and equality with the union of the
  config's ``frozen_records_lists`` (``(path, pinned sha)`` pairs; overlap, duplicates or a wrong count refuse).
  A records root under any reparse point (junction or symlink) or any checkout's ``data`` folder is refused.
* A silent None is a defect: ``fit`` refuses a (market, date) whose ``wu_hourly`` source is empty, or a date with
  no NBM for any market; ``emit`` refuses a batch (market, date) with no captured snapshot, NBM or METAR replay.
* Equivalence FAILS (never skips) when ``frozen_new_nbm_rows_sha256`` is absent, when a record is built but not
  listed or listed but not built, or when any compare covers fewer rows than expected (``per_row`` needs every row;
  ``state_sha`` needs the state sha AND full serve and trainer coverage). Nothing compared never passes.
* ``emit`` reads the snapshots with a ``target_date`` filter after a row-group-statistics refusal, and refuses
  when a serve helper's source sha (:data:`SERVE_HELPERS`) differs from the one the fit recorded.

Second fix (L16 re-review and master rulings, 2026-11-03):

* F1, whole-file pins: ``emit`` refuses by name when this module's source sha, or the sha of a file in
  :data:`EMIT_PINNED_MODULES`, differs from the fit manifest. The forward state is therefore frozen only at the
  FINAL module sha (after ``--hours`` lands); any later module change refuses emission by design.
* F2: ``fit`` requires ``frozen_records_lists`` and refuses the retired single-list keys by name.
* F3: the fit's hard checks never filter or alter the bound training set: (a) each WU-hourly column needs a finite
  value on every (market, date); (b) every (market, date) of the record windows' calendar grid needs a scored-hour
  row; (c) the pooled per-month cap stays the refusing rule and per-(market, month) counts are reported only;
  (d) ``emit`` writes a named hole record (with a reason) for each batch (market, date) that emitted 0 rows.
* F6: a snapshot ``target_date`` outside :data:`SNAPSHOT_TARGET_DATE_TYPES` refuses by name. F7: a records root
  inside any checkout (an ancestor holding ``.git``) refuses. F8: ``source_presence`` goes into the fit manifest
  and the emit receipt.
* Disclosure, inherited unchanged from bound MG-2: the NBM anchor is asymmetric. Training reads ``nbm_at_cutoff``
  at h:00; serving reads ``usable_v2_mean`` at capture time. The module reproduces both sides as bound.

Forward-prereg fields (design note section 6, as amended by master): ``candidate_id`` (``row28_B``), ``module``,
``module_source_sha256``, ``fit_kind`` (``forward``), ``fit_manifest_sha256``, ``state_sha256``,
``state_sidecar_sha256``, ``state_schema`` (``mg2_p3d_n_state/1``), ``arm``, ``centres``, ``season_of``, ``hours``,
``markets`` (US10; Denver out: :data:`EMIT_MARKETS`; Denver rows stay in the pooled TRAINING set exactly as in v12,
:data:`TRAINING_MARKETS`), ``training_window``, ``training_rows_sha256``, ``bucket_space_sha256``,
``upstream_sha256``, ``sklearn_version``, ``conversion`` and ``late_report`` (copied from the bound state),
``train_F_source`` / ``serve_F_source``, ``scored_window`` (2026-12-17..2027-01-30) and ``emission_window``
(2026-12-17..2027-05-31) named separately, ``coverage_window``, ``input_modes`` (``as_of_capture``),
``forward_receipt_sha256``, ``shadow_rows_sha256`` / ``emit_receipt_sha256`` per batch,
``equivalence_report_sha256``, ``frozen_before_utc`` and ``archive_dir``. The state's provenance cannot carry the
fit-manifest sha (the manifest carries the state sha); it carries the fit id and the training row-key sha.

Outside serving, capture, release and trading; refuses a production importer and (through ``mg2_p3d_n``) the
capture host. Heavy imports are lazy; importing the module does no I/O beyond that refusal.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import json
import math
import os
import pickle
import re
import shutil
import stat
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

MODULE = "weather.calibration.yearround_refit"
CANDIDATE_ID = "row28_B"
FIT_KIND = "forward"
ARMS = ("A", "B")
FIT_ARMS = ("B",)
TRAINING_MARKETS = ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
                    "san-francisco", "seattle")  # prm.R0_MARKETS: v12 pools all 11 in every fit
REQUIRED_FIT_MARKETS = TRAINING_MARKETS  # the forward fit refuses unless every v12 training market has rows
EMIT_MARKETS = ("atlanta", "austin", "chicago", "dallas", "houston", "los-angeles", "miami", "nyc",
                "san-francisco", "seattle")  # US10; Denver is out of the forward test
SCORED_HOURS = (13, 14, 15, 16)
FOLDS = (2021, 2022, 2023, 2024, 2025)
FORWARD_FOLD = 2026
DEV_LAST = date(2025, 12, 31)
LAST_TRAIN = date(2025, 12, 16)
TRAINING_WINDOW = ("2020-12-17", "2025-12-16")  # season-years 2021-2025 (prereg 1.1: 2020-12 is not in the corpus)
SCORED_WINDOW = ("2026-12-17", "2027-01-30")
EMISSION_WINDOW = ("2026-12-17", "2027-05-31")
COVERAGE_WINDOW = ("12-17", "05-31")
FROZEN_BEFORE_UTC = "2026-12-17T00:00:00+00:00"
BATCH_MAX_DAYS = 7
INPUT_MODES = ("as_of_capture",)
IMPUTE_CAP = 0.05
TRAIN_F_SOURCE = "wu_hourly"
# master 2026-11-03: a silent None is a defect. The state's bound feature set (FIT_KWARGS raw_columns=False, so
# pooled_residual_model.MeanModel uses F, the LEVEL_COLUMNS present in the frame, fh and the registry/anchor
# columns, pooled_residual_model.py:482-498/511) maps to these input sources; fit and emit refuse BY NAME when a
# source is absent or empty for a row's (market, date).
TRAIN_SOURCE_COLUMNS = {"wu_hourly": ("F", "x_high_so_far", "x_current_temp"), "nbm": ("fh",)}
EMIT_SOURCES = ("captured_snapshots", "captured_nbm", "captured_metar_replay")
# master review 2026-11-03 (ruling 5): the serve-path helpers emit relies on. Their inspect.getsource sha256 is
# recorded in the fitted state's provenance; emit refuses by name when any differs at emission time.
SERVE_HELPERS = (("weather.calibration.mg2_p3d_n", "serve_distribution"),
                 ("weather.calibration.mg2_p3d_n", "as_of_capture"),
                 ("weather.calibration.mg2_p3d_n", "scan_replay_as_of"),
                 ("weather.calibration.mg2_p3d_n", "_observations"),
                 ("weather.calibration.mg2_p3d_n", "convert_observation"),
                 ("weather.calibration.mg2_p3d_n", "nearest_centre"),
                 ("weather.calibration.yearround_refit", "_replay_dirs"))
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
# master second-fix ruling F1 (2026-11-03): whole-file pins at emit. Emit refuses by name when this module's
# source sha or either of these files' sha differs from the fit manifest's record, so the forward state is frozen
# only at the FINAL module sha and any later module change refuses emission by design.
EMIT_PINNED_MODULES = ("src/weather/calibration/mg2_p3d_n.py", "src/weather/calibration/r0_ols_floor_devfit.py")
LEGACY_CONFIG_KEYS = ("frozen_records_list", "frozen_records_list_sha256")
SNAPSHOT_TARGET_DATE_TYPES = ("date32[day]", "string", "large_string")
HOLES = "holes.jsonl"
REFUSED_MARKER = "REFUSED"  # written into a fit dir on any refusal after the dir exists (L16 re-check, 11-03)
SERVE_F_SOURCE = "captured_metar"
TOLERANCE = 1e-12
FRAME_TOLERANCE = 1e-9
THREADS = "10"

STATE_SCHEMA = "mg2_p3d_n_state/1"
FIT_MANIFEST_SCHEMA = "yearround_refit_fit_manifest/1"
SHADOW_RECEIPT_SCHEMA = "yearround_refit_shadow_receipt/1"
EQUIVALENCE_SCHEMA = "yearround_refit_equivalence/1"
FORWARD_RECEIPT_SCHEMA = "yearround_refit_forward_receipt/1"
RECORDS_MANIFEST_SCHEMA = "yearround_refit_records_manifest/1"
RECORDS_MANIFEST = "records_manifest.json"
FIT_MANIFEST = "fit_manifest.json"
SHADOW_ROWS = "shadow_rows.jsonl"
EMIT_RECEIPT = "emit_receipt.json"
EQUIVALENCE_REPORT = "equivalence_report.json"
GRID_HOLES_SCHEMA = "yearround_refit_grid_holes/1"
DECLARED_ABSENT_SCHEMA = "yearround_refit_declared_absent/1"
DECLARED_ABSENT_REASON = "source_absent_final"
GRID_HOLE_CLASSES = ("march_1", "us_spring_forward_sunday", "other")
# WU-store booleans in grid-holes (master Option A, 2026-11-04): the store's writer puts local_date second
# (wu_history.write_daily_summary); nothing dated on or after the cutoff is ever handed to a parser
WU_DAILY_HEADER_PREFIX = "schema_version,local_date,temperature_unit,row_count,"
WU_READ_CUTOFF = "2026-09-30"
WU_HOURLY_LAST_MONTH = "2025-12"
WU_HISTORY_MIN_ROW_COUNT = 20  # model_constants.HISTORY_MIN_ROW_COUNT, the field model_climatology tests
FALL_BACK_YEARS = (2020, 2021, 2022, 2023, 2024, 2025)  # the history seasons' US fall-back Sundays
WU_STORE_CAVEAT = ("the WU store is live main data: these booleans describe the store at read time, not the "
                   "store when the frozen corpus was built")
_DATE_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}")
_PLAIN_FIRST_FIELD = re.compile(r"[0-9A-Za-z._-]*")
GRID_HOLES_FILE = "grid_holes.json"
TRAINING_GRID_HOLES_FILE = "training_grid_holes.json"  # the equivalence run's uncapped names-only hole list
GRID_HOLES_EXPECTED = {"expected_market_dates": 7315, "holes": 81}  # the accepted 11-04 report 64eed04b

BOUND_P3D_N_STATE_SHA256 = "c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780"
FROZEN_RUNNER_SHA256 = "9e97c892936842e79b3d6279aa88979da8cf79fb09bd3b269b4726b2dfd1025b"
RELEASE_BINDING_REL = "docs/research/mg2-composite-binding-2026-10-25/release-binding.json"
ARCHIVE_ROOT = Path(r"C:\archive\row28b-forward-state")
FORBIDDEN_ROOTS = (Path(r"C:\t\l2\p2"),)

# v12's pinned inputs (row28_run_v12.py 99-150), the subset the A/B fit path reads.
SEASON_CORPORA = {
    "aug_sep": ("b455bd53d8f9aab47f57d1fd97250945d687cdf7167d3a3a33738687c902f017",),
    "oct_dec": ("cd0ba2bb004dc89f070ec9b1406e77f38cd2396dedd93ce1b377e727baefe9be",
                "23ac87fa5f058f8eeb7f49f0268f483939d4070f7f65e38063727c6749aa2a8d",
                "74807fbef1ba33ce8cd9c697b839369b1e3f3b7bbca7ebc3ac9f27edf84498cd"),
    "jan_jul": ("3a7034d2cb37f3425748bd4eeca048af85d8fd9bb0ef7a25519982b94ec8a6ba",
                "672a1f57632534076cba99ae2adebcbeb229decb58276d52fda79bd3946f18d2",
                "ece9d1c28454aa41113b022b92ff6600dcb4a5dab44a6851af5d895feea9281e"),
}
FETCH_MANIFEST_SHA256 = {
    "manifest_nbp.json": "2948b7180f54b0aa413360553d82851a3e3610cf1a3576104422d346259b6f5f",
    "manifest_nbp_gap.json": "02e5e8cbe67839ff3d8c68de4ea3633d28f97e9f24439078a6dd9010ba501c7b",
}
BLOCK_FILES = {  # fetch-relative path -> the manifest that records its sha256
    "c07": ("nbp\\nbp_station_blocks_c07.jsonl", "manifest_nbp.json"),
    "addon": ("nbp\\nbp_station_blocks_addon_01_00.jsonl", "manifest_nbp.json"),
    "gap": ("nbp\\nbp_station_blocks_gap_c07.jsonl", "manifest_nbp_gap.json"),
}
GAP_MONTHS = (6, 7)
L9_CORPUS_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
PINNED_MODULE_SHA256 = {  # v12 MODULE_SHA256 (row28_run_v12.py 81-90), the modules on the fit and serve paths
    "src/weather/calibration/pooled_residual_model.py": "52c497a95a69c3fbf78dbfe030b3190d93e940f180b81867a241552b3932a170",
    "src/weather/calibration/feature_model.py": "fe0dd4acfdd8724a434e6a6ba891a1c14236b651cb50d614b8b36c6e64ebed61",
    "src/weather/calibration/ols_floor_ladder.py": "6e6d100fb5bb2c9c2d811a681a3a88d9458305ef701ba4b8651be34011c12e8e",
    "src/weather/calibration/feature_model_training_inputs.py": "187e9b537cb4d3a79e2a5502e9322260f0e8ab5f0821416b46c7388069cbf50f",
    "src/weather/calibration/feature_column_allowlist.py": "956ddac245d182f2428da42d61a820c8a2dd455a083f30d86c63fcfe9390ae1d",
    "src/weather/model/mg_serve_core.py": "179fcbe495f36f6fd194c1bd0052ed6e150b0f016adbe0f8e9bb6128bd42e5d8",
}
# master review 2026-11-03 (deviation 2): the emit loop calls MG-2's private ``_replay_index`` read-only, so its
# source is pinned; any change to it refuses here (``_modules``) and fails the pin test loudly.
REPLAY_INDEX_SOURCE_SHA256 = "25c20aa1e0a87ae0f33286f9ee65523cc26632f906ad833c41343b976bd174a0"
RECORDED_MODULES = ("src/weather/calibration/mg2_p3d_n.py", "src/weather/calibration/r0_ols_floor_devfit.py",
                    "src/weather/calibration/r0_ols_floor_challenger.py")
FIT_KWARGS = {"market_id": False, "doy": True, "raw_columns": False, "bias_by": "season"}  # v12 1977

_PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                        "weather.trading", "weather.capture", "weather.sources", "weather.execution",
                        "maker_core", "app")
# An emit input column naming a label, settlement, outcome or price is refused before any row is read.
FORBIDDEN_INPUT_COLUMN = re.compile(r"label|settl|price|outcome|bid|ask|brier|pnl|ledger|final_bucket|^y$", re.I)
_SHA_RE = re.compile(r"\b[0-9a-f]{64}\b")
_RECORD_NAME = re.compile(r"^records_(.+)_(\d{4}-\d{2}-\d{2})\.pkl\.gz$")


class YearroundRefused(RuntimeError):
    """An input, a bound or a guard refuses the fit, the emission or the equivalence run."""


def _refuse_production_import():
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _PRODUCTION_PREFIXES):
            raise ImportError(f"{MODULE} is research-only; imported from {name}")
        frame = frame.f_back
    from weather.calibration import mg2_p3d_n  # noqa: F401  (its import refuses on the capture host)


_refuse_production_import()


# ----------------------------------------------------------------------------- small helpers

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def payload_sha256(path):
    """The sha256 of a records file's DECOMPRESSED payload (v8's identity: gzip stamps the header MTIME)."""
    h = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(obj):
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))


def as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def season_year(value):
    """Prereg 3.4: season-year Y runs Dec 17 (Y-1) .. Dec 16 (Y) (v12 1447-1449)."""
    d = as_date(value)
    return d.year + 1 if (d.month == 12 and d.day >= 17) else d.year


def in_dec_may(value):
    """B's training and coverage months, Dec 17 - May 31, by target_date (v12 1452-1454)."""
    d = as_date(value)
    return d.month <= 5 or (d.month == 12 and d.day >= 17)


def guard_path(path):
    """Refuse ``C:\\t\\l2\\p2`` and anything that names a panel store; return the resolved path."""
    p = Path(path).resolve()
    for root in FORBIDDEN_ROOTS:
        r = root.resolve()
        if p == r or r in p.parents:
            raise YearroundRefused(f"forbidden path (never open): {p}")
    if any("panel" in part.lower() for part in p.parts):
        raise YearroundRefused(f"forbidden path (panel store): {p}")
    return p


def utc_now():
    return datetime.now(timezone.utc)


def state_root():
    """The write-once root of every fit, emission and equivalence output (``data/yearround_refit``)."""
    from weather.paths import data_path

    return data_path("yearround_refit")


def _under_state_root(path):
    root = state_root().resolve()
    p = Path(path).resolve()
    if root not in p.parents:
        raise YearroundRefused(f"output {p} is not under {root}")
    return p


def _new_dir(path):
    p = _under_state_root(path)
    if p.exists():
        raise YearroundRefused(f"refusing to reuse {p} (write-once)")
    p.mkdir(parents=True)
    return p


def _write_json(path, obj):
    blob = (json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n").encode("utf-8")
    if Path(path).exists():
        raise YearroundRefused(f"refusing to overwrite {path}")
    Path(path).write_bytes(blob)
    return sha256_bytes(blob)


def _read_verified(path, sha, what):
    p = guard_path(path)
    blob = p.read_bytes()
    if sha256_bytes(blob) != sha:
        raise YearroundRefused(f"{what} sha256 differs from the given {sha}")
    return blob


def repo_root():
    from weather.paths import REPO_ROOT

    return Path(REPO_ROOT)


def module_source_sha256():
    return sha256_file(Path(__file__))


def upstream_shas():
    """Pinned modules must equal v12's pins in the importing checkout; the recorded ones are listed by sha."""
    root = repo_root()
    out = {}
    for rel, sha in PINNED_MODULE_SHA256.items():
        got = sha256_file(root / rel)
        if got != sha:
            raise YearroundRefused(f"bound module {rel} differs from its pinned sha256")
        out[rel] = got
    for rel in RECORDED_MODULES:
        out[rel] = sha256_file(root / rel)
    return out


def release_binding_shas():
    """Every 64-hex sha named anywhere in MG-2's release-binding.json (read only)."""
    path = repo_root() / RELEASE_BINDING_REL
    if not path.is_file():
        raise YearroundRefused(f"{RELEASE_BINDING_REL} is missing; the release-binding guard cannot run")
    return set(_SHA_RE.findall(path.read_text(encoding="utf-8").lower()))


def refuse_bound_sha(sha, *, where):
    """Q-S: a yearround state may never carry the bound P3d_N sha or any sha in release-binding.json."""
    if sha == BOUND_P3D_N_STATE_SHA256:
        raise YearroundRefused(f"{where}: the state sha equals the bound P3d_N state {BOUND_P3D_N_STATE_SHA256}")
    if sha in release_binding_shas():
        raise YearroundRefused(f"{where}: the state sha {sha} is listed in {RELEASE_BINDING_REL}")


def helper_source_shas():
    """{"module.function": sha256 of inspect.getsource} for every SERVE_HELPERS entry (ruling 5)."""
    import importlib
    import inspect

    out = {}
    for module, name in SERVE_HELPERS:
        func = getattr(importlib.import_module(module), name)
        out[f"{module}.{name}"] = hashlib.sha256(inspect.getsource(func).encode("utf-8")).hexdigest()
    return out


def refuse_changed_helpers(recorded):
    """Emit-time check: the serve helpers' sources equal those recorded in the frozen state."""
    if not isinstance(recorded, dict) or set(recorded) != {f"{m}.{n}" for m, n in SERVE_HELPERS}:
        raise YearroundRefused("the state records no complete helper_source_sha256 set (ruling 5)")
    now = helper_source_shas()
    changed = sorted(k for k in now if now[k] != recorded[k])
    if changed:
        raise YearroundRefused(f"serve helper source differs from the frozen state's record: {changed}")


def refuse_changed_sources(manifest):
    """F1: this module's source and the EMIT_PINNED_MODULES must equal the fit manifest's record (by name)."""
    changed = []
    if manifest.get("module_source_sha256") != module_source_sha256():
        changed.append(MODULE)
    recorded = manifest.get("upstream_sha256") or {}
    now = upstream_shas()
    changed += [rel for rel in EMIT_PINNED_MODULES if recorded.get(rel) != now[rel]]
    if changed:
        raise YearroundRefused(f"source differs from the fit manifest's record (whole-file pin): {changed}")


def refuse_legacy_config(cfg):
    """F2: the single-list keys are retired; they are refused by name, never silently ignored."""
    legacy = [k for k in LEGACY_CONFIG_KEYS if k in cfg]
    if legacy:
        raise YearroundRefused(f"retired config key(s) {legacy}: use frozen_records_lists ([path, sha256] pairs)")


def replay_index_source_sha256(p3):
    """sha256 of ``inspect.getsource(mg2_p3d_n._replay_index)`` (the one private function the emit loop uses)."""
    import inspect

    return hashlib.sha256(inspect.getsource(p3._replay_index).encode("utf-8")).hexdigest()


def _modules():
    from weather.calibration import feature_model as fm
    from weather.calibration import mg2_p3d_n as p3
    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import pooled_residual_model as prm

    if tuple(prm.R0_MARKETS) != TRAINING_MARKETS or p3.STATE_SCHEMA != STATE_SCHEMA:
        raise YearroundRefused("the bound market set or state schema differs from this module's pins")
    if replay_index_source_sha256(p3) != REPLAY_INDEX_SOURCE_SHA256:
        raise YearroundRefused("mg2_p3d_n._replay_index differs from its pinned source sha256")
    return SimpleNamespace(prm=prm, fm=fm, l9=l9, p3=p3)


# ----------------------------------------------------------------------------- centres (prereg 3.2, Rule L)

def centre_sets(prm):
    out = {"A": tuple(prm.FORWARD_CENTRES) + tuple(prm.JAN_JUL_CENTRES) + ("2026-12-24",),
           "B": tuple(prm.JAN_JUL_CENTRES[:10]) + ("2026-12-24",)}
    if len(out["A"]) != 24 or len(out["B"]) != 11 or not set(out["B"]) <= set(out["A"]):
        raise YearroundRefused("centre sets differ from prereg section 3.2")
    return out


def centre_for(prm, centres, target_date):
    """Bound ``nearest_centre`` on the arm's set; Rule L sends Feb 29 to the same year's Feb 28 (v12 1595-1600)."""
    d = as_date(target_date)
    if d.month == 2 and d.day == 29:
        d = d.replace(day=28)
    return prm.nearest_centre(d.isoformat(), centres)


def circular_picks(target_date, centres):
    """The wrap-aware nearest centres (v12 1603-1615), Rule L applied the same way."""
    d = as_date(target_date)
    if d.month == 2 and d.day == 29:
        d = d.replace(day=28)
    ref = date(2001, d.month, d.day)

    def dist(c):
        k = abs((date(2001, int(c[5:7]), int(c[8:10])) - ref).days)
        return min(k, 365 - k)

    best = min(dist(c) for c in centres)
    return {c for c in centres if dist(c) == best}


def wrap_check(prm, dates, centres):
    """Section 3.2: the wrap-free pick is a wrap-aware nearest centre on every date; returns the dates checked."""
    days = sorted({str(d)[:10] for d in dates})
    for day in days:
        if centre_for(prm, centres, day) not in circular_picks(day, centres):
            raise YearroundRefused(f"wrap-free and wrap-aware centre picks differ on {day}")
    return len(days)


def season_map(prm, centres):
    out = {}
    for c in centres:
        season = prm.season_of(c)
        if out.setdefault(c[5:7], season) != season:
            raise YearroundRefused(f"centre month {c[5:7]} maps to two seasons")
    return out


# ----------------------------------------------------------------------------- inputs (v12 load_context subset)

def manifests_for(cfg, prm, centre):
    root = Path(cfg["pit_corpora"])
    return [str(guard_path(root / cid / "manifest.json")) for cid in SEASON_CORPORA[prm.season_of(centre)]]


def covered(cfg, prm, centre):
    years = prm.covered_years(centre, manifests_for(cfg, prm, centre))
    if any(int(y) > DEV_LAST.year for y in years):
        raise YearroundRefused(f"centre {centre}: a covered year is after 2025")
    return [int(y) for y in years]


def verify_fetch_manifest(cfg, name):
    path = guard_path(Path(cfg["fetch_dir"]) / name)
    if sha256_file(path) != FETCH_MANIFEST_SHA256[name]:
        raise YearroundRefused(f"{name} sha256 differs from the row-28 freeze record")
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_file(cfg, key):
    rel, manifest_name = BLOCK_FILES[key]
    entry = verify_fetch_manifest(cfg, manifest_name)["files"][rel]
    path = guard_path(Path(cfg["fetch_dir"]) / rel)
    if sha256_file(path) != entry["sha256"]:
        raise YearroundRefused(f"{rel} sha256 differs from {manifest_name}")
    return path


def filtered_blocks(src, dst, months):
    """A copy of a blocks file restricted to the given months (the gap blocks: Jun-Jul only, section 3.3b)."""
    kept = 0
    with open(guard_path(src), encoding="utf-8") as fin, open(dst, "w", encoding="utf-8", newline="\n") as fout:
        for line in fin:
            if not line.strip():
                continue
            rec = json.loads(line)
            if as_date(rec["utc_date"]) > DEV_LAST:
                raise YearroundRefused(f"NBM block after 2025 in {src}")
            if as_date(rec["utc_date"]).month in months:
                fout.write(line.rstrip("\r\n") + "\n")
                kept += 1
    return kept


def build_new_nbm_rows(l9, blocks, out_dir):
    """L9's bound ``nbm-corpus`` parser (v12 2313-2314) over the row-28 block files; returns the rows file."""
    l9._nbm_corpus_command(SimpleNamespace(blocks=[str(b) for b in blocks], out_dir=str(out_dir)))
    return Path(out_dir) / "nbm_pit_corpus_rows.jsonl"


def merged_table(l9, paths):
    """``load_nbm`` over several L9-format files; no (market, date, cycle) twice (section 3.3b, v12 1798-1812)."""
    table = defaultdict(list)
    seen = set()
    for path in paths:
        for key, entries in l9.load_nbm(guard_path(path)).items():
            if as_date(key[1]) > DEV_LAST:
                raise YearroundRefused(f"NBM entry after 2025: {key[0]}")
            for entry in entries:
                k = (key[0], key[1], entry[0])
                if k in seen:
                    raise YearroundRefused(f"duplicate NBM (market, date, cycle) {k}")
                seen.add(k)
                table[key].append(entry)
    return table


# ----------------------------------------------------------------------------- records and the row frame

def _label_present(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def market_frame(prm, files, with_labels):
    """``pooled_frame`` over the record files, reduced to the serve-parity inputs (v12 1737-1761)."""
    payloads, meta = [], []
    for path in files:
        market, centre = Path(path).name[len("records_"):-len(".pkl.gz")].rsplit("_", 1)
        payload = prm.load_records(Path(path).parent, market, centre)
        if not with_labels:
            for recs in payload["records"].values():
                for rec in recs:
                    rec["final_bucket"] = 0.0 if _label_present(rec.get("final_bucket")) else float("nan")
        payloads.append(payload)
        meta.append({"market": payload["market"], "centre": payload["centre"], "file": Path(path).name,
                     "bucket_space": [int(b) for b in payload["bucket_space"]]})
    frame, _ = prm.pooled_frame(payloads, prm.station_coordinates(prm.R0_MARKETS))
    del payloads
    frame = frame.drop(columns=[c for c in frame.columns if c.startswith("x_") and c not in prm.DEV_KEEP_X])
    for col in prm.DEV_KEEP_X:
        if col not in frame.columns:
            raise YearroundRefused(f"{col} is not a common record feature")
    frame = frame.rename(columns={"centre": "payload_centre"}).drop(columns=["season"])
    if not with_labels:
        if not set(frame["y"].dropna().unique()) <= {0.0}:
            raise YearroundRefused("the y-free frame holds a label value")
        frame["y_present"] = frame["y"].notna()
        frame = frame.drop(columns=["y"])
    return frame, meta


def _is_reparse_point(path):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def check_records_root(records_root):
    """Refuse a records root under any reparse point (junction or symlink) or inside any checkout.

    Master review 2026-11-03 (ruling 2): a root reached through a junction can write into another tree (a
    worktree's ``data\\training`` junction writes the main checkout). Every component of the absolute, unresolved
    path is checked for a reparse point; then every ancestor of the resolved path named ``data`` whose parent
    holds ``.git``, and (F7) every ancestor that itself holds ``.git`` (a checkout or worktree root), refuses.
    """
    raw = Path(os.path.abspath(records_root))
    for part in (raw, *raw.parents):
        if _is_reparse_point(part):
            raise YearroundRefused(f"the records root lies under a reparse point (junction or symlink): {part}")
    resolved = raw.resolve()
    for part in (resolved, *resolved.parents):
        if part.name.lower() == "data" and (part.parent / ".git").exists():
            raise YearroundRefused(f"the records root lies under a checkout's data folder: {part}")
        if (part / ".git").exists():  # F7: inside any checkout or worktree at all, its root included
            raise YearroundRefused(f"the records root lies inside a checkout (it holds .git): {part}")
    return guard_path(resolved)


def records_root_arg(records_root, cfg):
    """The records root comes only from the required ``--records-root`` argument (master review 2026-11-03)."""
    if "records_root" in cfg:
        raise YearroundRefused("records_root is a required CLI argument (--records-root), not a config key")
    if not records_root:
        raise YearroundRefused("--records-root is required")
    return check_records_root(records_root)


def record_centres(prm):
    """The centres whose record windows are built: every A centre (v12 stage_build 2269)."""
    return centre_sets(prm)["A"]


def record_markets(prm):
    """The markets whose record windows are built: the bound R0 set (v12 stage_build 2276)."""
    return tuple(prm.R0_MARKETS)


def expected_record_names(prm, records):
    return sorted(prm.records_path(records, m, c).name for c in record_centres(prm) for m in record_markets(prm))


def refuse_incomplete_records(manifest):
    """Ruling 1: any fail-closed extract or skipped centre refuses by name (fit, freeze and equivalence)."""
    failed = manifest.get("extract_failed_closed") or []
    if failed:
        shown = ", ".join(f"{e['market']} {e['centre']} ({e['reason']})" for e in failed[:5])
        raise YearroundRefused(f"{len(failed)} record extract(s) failed closed or were skipped: {shown}"
                               f"{' ...' if len(failed) > 5 else ''}")
    empty = sorted(c for c, years in (manifest.get("covered_years") or {}).items() if not years)
    if empty:
        raise YearroundRefused(f"centre(s) with no covered year: {empty}")


def refuse_records_not_frozen(ours, frozen):
    """The records list must equal the frozen list exactly: payload shas, nothing missing, nothing extra."""
    rec = compare_records(ours, frozen)
    if not rec["pass"]:
        raise YearroundRefused(f"the records differ from the frozen records list: {rec}")
    return rec


def build_records(cfg, prm, records_root):
    """Every A-centre record window through the bound ``extract_market`` (v12 stage_build 2267-2289).

    A records root with a ``records_manifest.json`` is reused only when (ruling 1) its module sha equals this
    module's, it has no fail-closed or skipped entry, its file set is exactly the expected one, every payload sha
    matches, and it equals the config's frozen records list (which a reuse requires). A root holding files but no
    manifest is refused (a partial build). A fresh build that fails closed anywhere writes its manifest as
    evidence and then refuses. Returns (files, manifest).
    """
    from weather.sources.forecast_training_corpus import CorpusVerificationError

    records = check_records_root(records_root)
    prm.require_output_outside_repo(records)
    manifest_path = records / RECORDS_MANIFEST
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != RECORDS_MANIFEST_SCHEMA:
            raise YearroundRefused("records manifest schema differs")
        if manifest.get("module_source_sha256") != module_source_sha256():
            raise YearroundRefused("the reused records root was built by a different module source sha256")
        refuse_incomplete_records(manifest)
        if sorted(manifest["files"]) != expected_record_names(prm, records):
            raise YearroundRefused("the reused records root's file set differs from the expected record windows")
        for name, entry in manifest["files"].items():
            if payload_sha256(records / name) != entry["payload_sha256"]:
                raise YearroundRefused(f"record {name} differs from its records manifest")
        present = sorted(p.name for p in records.glob("records_*.pkl.gz"))
        if present != sorted(manifest["files"]):
            raise YearroundRefused("the records root holds files outside its records manifest")
        if not cfg.get("frozen_records_lists"):
            raise YearroundRefused("a reused records root needs the frozen records lists (path and sha) to verify")
        refuse_records_not_frozen({n: e["payload_sha256"] for n, e in manifest["files"].items()},
                                  frozen_records_union(cfg, prm))
        return sorted(records / n for n in manifest["files"]), manifest
    if records.exists() and any(records.iterdir()):
        raise YearroundRefused(f"{records} holds files but no {RECORDS_MANIFEST} (a partial build); use a new root")
    files, failed, years_by_centre = {}, [], {}
    for centre in record_centres(prm):
        years = covered(cfg, prm, centre)
        years_by_centre[centre] = years
        if not years:
            failed += [{"market": m, "centre": centre, "reason": "no covered year"} for m in record_markets(prm)]
            continue
        for market in record_markets(prm):
            try:
                path, _ = prm.extract_market(market, centre, manifests_for(cfg, prm, centre), records,
                                             training_years=years)
            except CorpusVerificationError as exc:
                failed.append({"market": market, "centre": centre, "reason": type(exc).__name__})
                continue
            files[path.name] = {"sha256": sha256_file(path), "payload_sha256": payload_sha256(path)}
            print(f"extracted {market} {centre}", flush=True)
    manifest = {"schema": RECORDS_MANIFEST_SCHEMA, "files": files, "extract_failed_closed": failed,
                "covered_years": years_by_centre, "module_source_sha256": module_source_sha256()}
    _write_json(manifest_path, manifest)
    refuse_incomplete_records(manifest)
    return sorted(records / n for n in files), manifest


def training_frame(cfg, mods, files, nbm_dir):
    """v12's labelled market frame (stage_build 2295-2327 then stage_labels 2928-2944), in v12's row order.

    The y-free frame gets the market NBM anchor; the labels are joined on (market, target_date, hour) exactly as
    v12 joins them. Returns (frame, payload_buckets, report).
    """
    prm, l9 = mods.prm, mods.l9
    labelled, meta = market_frame(prm, files, with_labels=True)
    days = labelled["target_date"].astype(str)
    if (days > DEV_LAST.isoformat()).any():
        raise YearroundRefused("a record row is dated after 2025")
    report = {"rows_fold_2026_not_built": int((days > LAST_TRAIN.isoformat()).sum())}
    labelled = labelled[days <= LAST_TRAIN.isoformat()].reset_index(drop=True)
    frame = labelled.drop(columns=["y"]).assign(y_present=labelled["y"].notna())
    if sha256_file(guard_path(cfg["l9_corpus"])) != L9_CORPUS_SHA256:
        raise YearroundRefused("L9 NBM corpus sha256 differs")
    nbm_dir = _under_state_root(nbm_dir)
    nbm_dir.mkdir(parents=True, exist_ok=False)
    gap = nbm_dir / "gap_blocks_jun_jul.jsonl"
    kept = filtered_blocks(fetch_file(cfg, "gap"), gap, GAP_MONTHS)
    new_rows = build_new_nbm_rows(l9, [fetch_file(cfg, "c07"), fetch_file(cfg, "addon"), gap], nbm_dir / "new")
    table = merged_table(l9, [cfg["l9_corpus"], new_rows])
    tz = {m: _timezone(m) for m in prm.R0_MARKETS}
    cycles = [l9.nbm_at_cutoff(table, m, str(d)[:10], int(h), tz[m])[1]
              for m, d, h in zip(frame["market"], frame["target_date"], frame["hour"])]
    inputs, stats = prm.attach_training_nbm(frame, table, l9.nbm_at_cutoff, tz)
    inputs["nbm_cycle"] = cycles
    inputs["sy"] = [season_year(d) for d in inputs["target_date"]]
    y = labelled.set_index(["market", "target_date", "hour"])["y"]
    out = inputs.join(y, on=["market", "target_date", "hour"])
    if out["y"].isna().any():
        raise YearroundRefused("a built row has no label")
    report.update({"rows": int(len(out)), "gap_jun_jul_records": kept, "train_nbm": dict(stats),
                   "new_nbm_rows_sha256": sha256_file(new_rows), "gap_blocks_sha256": sha256_file(gap)})
    payload_buckets = {(p["market"], p["centre"]): p["bucket_space"] for p in meta}
    return out, payload_buckets, report


def _timezone(market):
    from weather.market.market_registry import spec_for_id

    return spec_for_id(market).timezone


# ----------------------------------------------------------------------------- arm rows (v12 2004-2029)

def with_arm_centres(prm, centres, frame, arm):
    out = frame.copy()
    out["centre"] = [centre_for(prm, centres[arm], d) for d in out["target_date"]]
    out["season"] = [prm.season_of(c) for c in out["centre"]]
    return out


def arm_rows(frame, arm, hour, fold):
    """The fold's training rows: the hour, the other season-years, dated at or before 2025-12-16; B adds Dec-May."""
    days = frame["target_date"].astype(str)
    mask = (frame["hour"] == hour) & (frame["sy"] != fold) & (days <= LAST_TRAIN.isoformat())
    if arm == "B":
        mask &= days.map(in_dec_may)
    return frame[mask].reset_index(drop=True)


def arm_buckets(payload_buckets, train):
    """Section 3.6: contributing payloads' bucket_space plus [min, max] of the fold's training labels."""
    out = {}
    for market, part in train.groupby("market"):
        space = set()
        for centre in part["payload_centre"].unique():
            space |= set(payload_buckets[(market, centre)])
        ys = part["y"].to_numpy(float)
        space |= set(range(int(ys.min()), int(ys.max()) + 1))
        out[market] = sorted(space)
    return out


def check_training_window(train):
    days = train["target_date"].astype(str)
    if len(days) and (days.min() < TRAINING_WINDOW[0] or days.max() > TRAINING_WINDOW[1]):
        raise YearroundRefused(f"a training row lies outside the prereg training_window {TRAINING_WINDOW}")


def row_keys_sha256(train):
    """sha256 over the training rows' keys in frame order (the fit depends on row order)."""
    lines = [f"{m}|{c}|{h}|{str(d)[:10]}|{a}" for m, c, h, d, a in
             zip(train["market"], train["payload_centre"], train["hour"], train["target_date"], train["centre"])]
    return sha256_bytes("\n".join(lines).encode("utf-8"))


class SourceAbsent(YearroundRefused):
    """An input source of the bound feature set is absent or empty for a row's (market, date)."""


def _refuse_absent(source, keys, n_dates, grain="(market, date)"):
    shown = ", ".join(" ".join(str(x) for x in k) for k in keys[:5])
    raise SourceAbsent(f"input source {source!r} is absent or empty for {len(keys)} {grain} of "
                       f"{n_dates}: {shown}{' ...' if len(keys) > 5 else ''}")


def refuse_absent_training_sources(frame, arm):
    """Refuse by name a (market, date) of the fit's training rows whose source is entirely missing.

    The fit's rows are ``arm_rows`` for the scored hours (any fold). ``wu_hourly`` is absent for a (market, date)
    and scored hour when any one of F, x_high_so_far and x_current_temp has no finite value on it (F3(a), hour
    grain). ``nbm`` is absent for a DATE when no
    market has an NBM mean on it: per-(market, date) NBM gaps stay the pre-registered section 3.3b imputation,
    counted and capped by ``imputation_shares`` / IMPUTE_CAP. A pure precondition: it raises or returns counts.
    """
    import numpy as np

    days = frame["target_date"].astype(str).str[:10]
    mask = frame["hour"].isin(SCORED_HOURS) & (days <= LAST_TRAIN.isoformat())
    if arm == "B":
        mask &= days.map(in_dec_may)
    rows = frame[mask].assign(_d=days[mask])
    if rows.empty:
        raise SourceAbsent("the fit has no training rows at all")
    groups = rows.groupby(["market", "_d"], sort=True)
    cols = [c for c in TRAIN_SOURCE_COLUMNS["wu_hourly"] if c in rows]
    if len(cols) != len(TRAIN_SOURCE_COLUMNS["wu_hourly"]):
        raise SourceAbsent(f"input source 'wu_hourly' columns are absent from the frame: "
                           f"{sorted(set(TRAIN_SOURCE_COLUMNS['wu_hourly']) - set(cols))}")
    finite = rows[cols].apply(lambda c: np.isfinite(c.to_numpy(float)))
    # F3(a), hour grain (master 2026-11-04): the h13-16 fits are separate models, so EACH named column needs a
    # finite value on every (market, date, scored hour) that has rows; one finite column or hour is not enough
    wu = finite.groupby([rows["market"], rows["_d"], rows["hour"].astype(int)]).any().all(axis=1)
    missing = [k for k, ok in wu.items() if not ok]
    if missing:
        _refuse_absent("wu_hourly", missing, int(len(wu)), grain="(market, date, hour)")
    fh_ok = np.isfinite(rows["fh"].to_numpy(float))
    by_date = pd_series(fh_ok, rows["_d"]).groupby(level=0).any()
    missing = [("all markets", d) for d, ok in by_date.items() if not ok]
    if missing:
        _refuse_absent("nbm", missing, len(by_date))
    return {"wu_hourly_market_dates": int(groups.ngroups), "wu_hourly_market_date_hours": int(len(wu)),
            "nbm_dates": int(len(by_date)),
            "rows_missing_any_wu_hourly_value": int((~rows[cols].apply(
                lambda c: np.isfinite(c.to_numpy(float))).all(axis=1)).sum())}


def expected_training_grid(prm, covered_years, arm, markets=None):
    """F3(b): every (market, date) the fit's rows must cover: the record windows of each centre's covered years.

    The windows are ``prm.window_days(centre, year)`` for the centres and years the records manifest lists, cut to
    the training window and (arm B) to Dec 17 - May 31, for every required fit market.
    """
    days = set()
    for centre, years in (covered_years or {}).items():
        for year in years:
            for day in prm.window_days(centre, int(year)):
                iso = day.isoformat()
                if TRAINING_WINDOW[0] <= iso <= LAST_TRAIN.isoformat() and (arm != "B" or in_dec_may(iso)):
                    days.add(iso)
    return {(m, d) for m in (REQUIRED_FIT_MARKETS if markets is None else markets) for d in days}


def training_grid_holes(frame, expected):
    """The expected (market, date) with no scored-hour row in the frame (sorted)."""
    days = frame["target_date"].astype(str).str[:10]
    have = set(zip(frame.loc[frame["hour"].isin(SCORED_HOURS), "market"].astype(str),
                   days[frame["hour"].isin(SCORED_HOURS)]))
    return sorted(expected - have)


def _us_spring_forward(day):
    """The second Sunday of March: the US start of daylight saving time (every market here is a US station)."""
    return day.month == 3 and day.weekday() == 6 and 8 <= day.day <= 14


def _in_forward_scored_window(day):
    """Dec 17 .. Jan 30 by calendar day: the forward scored window's days in any year."""
    return (day.month == 12 and day.day >= 17) or (day.month == 1 and day.day <= 30)


def grid_hole_names(holes, expected_n):
    """A NAMES-ONLY account of calendar-grid holes: each (market, date), counts and the date classes. No values."""
    named = [{"market": m, "target_date": d} for m, d in sorted(holes)]
    classes = {"march_1": [], "us_spring_forward_sunday": [], "other": []}
    for m, d in sorted(holes):
        day = as_date(d)
        cls = "march_1" if (day.month, day.day) == (3, 1) else (
            "us_spring_forward_sunday" if _us_spring_forward(day) else "other")
        classes[cls].append(f"{m} {d}")
    days = {d for _, d in holes}
    return {"expected_market_dates": int(expected_n), "holes": len(named), "names": named,
            "per_market": dict(sorted(Counter(m for m, _ in holes).items())),
            "by_class": {k: {"count": len(v), "names": v} for k, v in classes.items()},
            "feb_29_holes": sorted(f"{m} {d}" for m, d in holes if d[5:] == "02-29"),
            "has_2024_02_29": "2024-02-29" in days, "has_2024_03_01": "2024-03-01" in days,
            "in_forward_window": any(_in_forward_scored_window(as_date(d)) for d in days),
            "in_forward_window_names": sorted(f"{m} {d}" for m, d in holes if _in_forward_scored_window(as_date(d)))}


def load_declared_absent(path, sha):
    """The master-ruled ``source_absent_final`` grid-hole records (sha-pinned JSON), or refuse by name.

    Each record names a (market, date), its class, the cause cite and the ruling; nothing else. A duplicate, an
    unknown market, class or reason, or a record without a cause or ruling refuses.
    """
    body = json.loads(_read_verified(path, sha, "declared-absent records"))
    if body.get("schema") != DECLARED_ABSENT_SCHEMA or not isinstance(body.get("records"), list) or not body["records"]:
        raise YearroundRefused(f"declared-absent records need schema {DECLARED_ABSENT_SCHEMA} and a non-empty list")
    keys = []
    for rec in body["records"]:
        if set(rec) != {"market", "target_date", "reason", "class", "cause", "ruling"}:
            raise YearroundRefused(f"declared-absent record has keys {sorted(rec)}")
        if rec["reason"] != DECLARED_ABSENT_REASON or rec["class"] not in GRID_HOLE_CLASSES:
            raise YearroundRefused(f"declared-absent record {rec['market']} {rec['target_date']}: reason must be "
                                   f"{DECLARED_ABSENT_REASON!r} and class one of {GRID_HOLE_CLASSES}")
        if rec["market"] not in TRAINING_MARKETS or not str(rec["cause"]).strip() or not str(rec["ruling"]).strip():
            raise YearroundRefused(f"declared-absent record {rec['market']} {rec['target_date']}: unknown market or "
                                   "no cause cite or ruling")
        keys.append((rec["market"], as_date(rec["target_date"]).isoformat()))
    if len(set(keys)) != len(keys):
        raise YearroundRefused("declared-absent records name a (market, date) twice")
    return {"records": set(keys), "sha256": sha, "by_class": dict(sorted(Counter(r["class"] for r in body["records"])
                                                                           .items()))}


def refuse_training_grid_holes(frame, expected, declared=None):
    """F3(b), a HARD check: a hole in the calendar grid refuses by name (never filtered or filled).

    An EMPTY expected grid (no covered years recorded) refuses too: it would pass vacuously. ``declared``
    (``load_declared_absent``) names master-ruled holes that are accepted as ``source_absent_final``: every
    declared record must be a real hole, and any hole it does not name still refuses. The rows are unchanged.
    """
    if not expected:
        raise SourceAbsent("input source 'training_calendar_grid' is empty: the records manifest lists no covered "
                           "year in the training window")
    holes = training_grid_holes(frame, expected)
    named = set() if declared is None else set(declared["records"])
    not_holes = sorted(named - set(holes))
    if not_holes:
        shown = ", ".join(f"{m} {d}" for m, d in not_holes[:5])
        raise YearroundRefused(f"{len(not_holes)} declared-absent record(s) are not grid holes: {shown}")
    undeclared = [k for k in holes if k not in named]
    if undeclared:
        _refuse_absent("training_calendar_grid", undeclared, len(expected))
    out = {"expected_market_dates": len(expected), "holes": len(holes) - len(named)}
    if declared is not None:
        out["declared_absent"] = {"records": len(named), "sha256": declared["sha256"], "by_class": declared["by_class"],
                                  "names": [f"{m} {d}" for m, d in sorted(named)]}
    return out


def pd_series(values, index):
    import pandas as pd

    return pd.Series(values, index=pd.Index(index.to_numpy(), name="d"))


def imputation_shares(frame, arm):
    """Section 3.3b / R10: fill-from-forecast share per calendar month, hours 13-16 (counts only)."""
    train = frame[frame["hour"].isin(SCORED_HOURS)]
    days = train["target_date"].astype(str)
    if arm == "B":
        keep = days.map(in_dec_may)
        train, days = train[keep], days[keep]
    month = days.str[5:7]
    total = month.value_counts().to_dict()
    imputed = month[train["nbm_cycle"].isna()].value_counts().to_dict()
    return {k: {"rows": int(total[k]), "imputed": int(imputed.get(k, 0)),
                "share": float(imputed.get(k, 0) / total[k])} for k in sorted(total)}


def imputation_by_market_month(frame, arm):
    """F3(c): the section 3.3b fill-from-forecast counts per (market, calendar month), REPORTED ONLY.

    The refusing rule stays the pooled per-month cap of ``imputation_shares`` (the frozen spec); no per-market
    refusal exists, so the bound training set cannot change through this.
    """
    train = frame[frame["hour"].isin(SCORED_HOURS)]
    days = train["target_date"].astype(str)
    if arm == "B":
        keep = days.map(in_dec_may)
        train, days = train[keep], days[keep]
    key = train["market"].astype(str) + "|" + days.str[5:7]
    total = key.value_counts().to_dict()
    imputed = key[train["nbm_cycle"].isna()].value_counts().to_dict()
    out = {k: {"rows": int(total[k]), "imputed": int(imputed.get(k, 0)),
               "share": float(imputed.get(k, 0) / total[k])} for k in sorted(total)}
    return {"cap_rule": "pooled per calendar month (reported only per market)", "by_market_month": out,
            "max_share": max((v["share"] for v in out.values()), default=0.0),
            "over_cap": sorted(k for k, v in out.items() if v["share"] > IMPUTE_CAP)}


def training_source_checks(frame, arm, covered_years, prm, holes_path=None):
    """Equivalence-side report of the fit's hard checks (F3(a), F3(b)) and F3(c) counts: names and counts only.

    ``holes_path`` (optional) receives the UNCAPPED names-only hole list (``grid_hole_names``); its sha is reported.
    """
    out = {}
    try:
        out["source_presence"] = refuse_absent_training_sources(frame, arm)
    except SourceAbsent as exc:
        out["source_presence"] = {"refused": str(exc)}
    expected = expected_training_grid(prm, covered_years, arm)
    holes = training_grid_holes(frame, expected)
    out["calendar_grid"] = {"expected_market_dates": len(expected), "empty": not expected, "holes": len(holes),
                            "first_holes": [f"{m} {d}" for m, d in holes[:5]]}
    if holes_path is not None:
        out["calendar_grid"]["holes_file"] = str(holes_path)
        out["calendar_grid"]["holes_file_sha256"] = _write_json(holes_path, grid_hole_names(holes, len(expected)))
    out["imputation_by_market_month"] = imputation_by_market_month(frame, arm)
    return out


def fit_hour(prm, train):
    """The fit half of v12's ``fit_and_score`` (1976-1984) in the shape ``state_from_fits`` takes."""
    fitted = prm.fit_pooled(train, **FIT_KWARGS)
    train_y = {m: [int(v) for v in train.loc[train["market"] == m, "y"]] for m in sorted(train["market"].unique())}
    return {"fit": fitted, "train_y": train_y}


def trainer_predict(mods, fitted, train_y, buckets, part):
    """Trainer-side yhat, s and distribution on held-out rows (v12 1980-1990; no label is read)."""
    import numpy as np

    prm, fm = mods.prm, mods.fm
    out = []
    for market in sorted(part["market"].unique()):
        rows = part[part["market"] == market].reset_index(drop=True)
        yhat, X = fitted["mean"].predict(rows)
        gap = np.nan_to_num(yhat - rows["F"].to_numpy(float), nan=0.0)
        s = np.maximum(prm.MIN_SCALE, fitted["scale"].predict(np.column_stack([X, gap])) * math.sqrt(math.pi / 2))
        p_clim = fm.smoothed_dist(train_y[market], buckets[market], alpha=0.10)
        for i in range(len(rows)):
            dist = prm.predictive_distribution(float(yhat[i]), float(s[i]), float(rows["F"].iat[i]), fitted["z"],
                                               buckets[market], p_clim)
            out.append(((market, str(rows.at[i, "target_date"])[:10], int(rows.at[i, "hour"])),
                        float(yhat[i]), float(s[i]), dist))
    return out


def arm_state(mods, frame, payload_buckets, arm, fold, *, hours=SCORED_HOURS, provenance, conversion=None,
              late_report=None, fit=fit_hour):
    """One ``mg2_p3d_n_state/1`` for (arm, fold) over ``hours``, plus its row-key and bucket identities."""
    prm, p3 = mods.prm, mods.p3
    centres = centre_sets(prm)
    framed = with_arm_centres(prm, centres, frame, arm)
    fits, buckets, info = {}, None, {"rows": {}, "training_rows_sha256": {}}
    for hour in hours:
        train = arm_rows(framed, arm, hour, fold)
        check_training_window(train)
        wrap_check(prm, train["target_date"], centres[arm])
        b = arm_buckets(payload_buckets, train)
        if buckets is not None and b != buckets:
            raise YearroundRefused(f"arm {arm} fold {fold}: the bucket space differs across hours; one state "
                                   "cannot hold it (needs a ruling)")
        buckets = b
        fits[(hour, None)] = fit(prm, train)
        info["rows"][hour] = int(len(train))
        info["training_rows_sha256"][hour] = row_keys_sha256(train)
    state = p3.state_from_fits(
        fits, buckets, frame_columns=set(frame.columns), markets=[m for m in prm.R0_MARKETS if m in buckets],
        centres=list(centres[arm]),
        season_of=season_map(prm, centres[arm]), coords=prm.station_coordinates(prm.R0_MARKETS), fit_kind=FIT_KIND,
        provenance=provenance, conversion=conversion, late_report=late_report)
    problems = p3.state_problems(state)
    if problems:
        raise YearroundRefused(f"state problems: {problems}")
    info["bucket_space_sha256"] = canonical_sha(buckets)
    info["training_rows_sha256_all"] = canonical_sha(info["training_rows_sha256"])
    return state, info


def bound_hooks(mods, cfg):
    """conversion and late_report of the bound P3d_N state (loaded by its sha; only these two dicts are read)."""
    bound = mods.p3.load_state(guard_path(cfg["bound_state"]), BOUND_P3D_N_STATE_SHA256, forward=True)
    return copy.deepcopy(bound["conversion"]), copy.deepcopy(bound["late_report"])


def _versions():
    import numpy
    import pandas
    import sklearn

    return {"sklearn": sklearn.__version__, "numpy": numpy.__version__, "pandas": pandas.__version__}


# ----------------------------------------------------------------------------- fit

def archive_copy(fit_dir, fit_id, names, archive_root=None):
    """Copy the frozen files into the never-cleaned WS archive and verify each copy sha-equal (ruling 1)."""
    root = Path(archive_root or ARCHIVE_ROOT)
    dest = root / fit_id
    if dest.exists():
        raise YearroundRefused(f"archive directory {dest} already exists (write-once)")
    dest.mkdir(parents=True)
    out = {}
    for name in names:
        src_sha = sha256_file(Path(fit_dir) / name)
        shutil.copyfile(Path(fit_dir) / name, dest / name)
        if sha256_file(dest / name) != src_sha:
            raise YearroundRefused(f"archive copy of {name} is not sha-equal")
        out[name] = src_sha
    return str(dest), out


def archive_add(fit_dir, archive_dir, name):
    """Copy one more frozen file into an existing archive directory, write-once, and verify it sha-equal."""
    dest = Path(archive_dir) / name
    if dest.exists():
        raise YearroundRefused(f"archive file {dest} already exists (write-once)")
    src_sha = sha256_file(Path(fit_dir) / name)
    shutil.copyfile(Path(fit_dir) / name, dest)
    if sha256_file(dest) != src_sha:
        raise YearroundRefused(f"archive copy of {name} is not sha-equal")
    return src_sha


def verify_archive(fit_dir, archive_dir, names):
    """Re-verify an archived fit: every file present in both places and sha-equal."""
    return {name: sha256_file(Path(archive_dir) / name) == sha256_file(Path(fit_dir) / name) for name in names}


def freeze_state(p3, state, out_dir):
    """Q-S: refuse the bound P3d_N sha (and any release-binding sha) BEFORE anything is written; then write once."""
    sha = sha256_bytes(pickle.dumps(state, protocol=4))  # the exact bytes write_state writes
    refuse_bound_sha(sha, where="fit")
    written = p3.write_state(state, out_dir)
    if written != sha:
        raise YearroundRefused("write_state's sha differs from the state's bytes")
    return sha


def fit(cfg, arm="B", now=None, *, records_root, declared_absent=None, declared_absent_sha=None):
    if arm not in FIT_ARMS:
        raise YearroundRefused(f"only arm(s) {FIT_ARMS} have a forward fit")
    refuse_legacy_config(cfg)
    if bool(declared_absent) != bool(declared_absent_sha):
        raise YearroundRefused("--declare-absent needs --declare-absent-sha (and the reverse)")
    declared = load_declared_absent(declared_absent, declared_absent_sha) if declared_absent else None
    if not cfg.get("frozen_records_lists"):  # F2: a fresh fit needs the frozen lists too, never only on reuse
        raise YearroundRefused("fit requires frozen_records_lists ([path, sha256] pairs) in the config")
    now = now or utc_now()
    if now >= datetime.fromisoformat(FROZEN_BEFORE_UTC):
        raise YearroundRefused(f"the forward state must be frozen before {FROZEN_BEFORE_UTC}")
    fit_id = now.strftime("%Y%m%dT%H%M%SZ")
    out = _new_dir(state_root() / CANDIDATE_ID / fit_id)
    try:
        return _fit_in(cfg, arm, now, fit_id, out, records_root, declared=declared)
    except Exception as exc:  # a partial fit dir is never mistaken for a fit: it carries a REFUSED marker
        try:
            _write_json(out / REFUSED_MARKER, {"refused": True, "reason": type(exc).__name__, "message": str(exc),
                                               "refused_utc": utc_now().isoformat()})
        except Exception as marker_exc:  # the ORIGINAL refusal is what propagates; the marker failure is noted
            exc.add_note(f"the {REFUSED_MARKER} marker could not be written: {marker_exc!r}")
        raise exc


def _fit_in(cfg, arm, now, fit_id, out, records_root, declared=None):
    mods = _modules()
    upstream = upstream_shas()
    conversion, late_report = bound_hooks(mods, cfg)
    files, records_manifest = build_records(cfg, mods.prm, records_root_arg(records_root, cfg))
    refuse_records_not_frozen({n: e["payload_sha256"] for n, e in records_manifest["files"].items()},
                              frozen_records_union(cfg, mods.prm))
    frame, payload_buckets, build_report = training_frame(cfg, mods, files, out / "work_nbm")
    source_presence = refuse_absent_training_sources(frame, arm)
    source_presence["calendar_grid"] = refuse_training_grid_holes(  # the check path only: rows and state unchanged
        frame, expected_training_grid(mods.prm, records_manifest.get("covered_years"), arm), declared=declared)
    by_market_month = imputation_by_market_month(frame, arm)
    shares = imputation_shares(frame, arm)
    if max((v["share"] for v in shares.values()), default=0.0) > IMPUTE_CAP:
        raise YearroundRefused("section 3.3b imputation cap breached")
    versions = _versions()
    provenance = {"candidate": CANDIDATE_ID, "shadow_only": True, "module": MODULE,
                  "module_source_sha256": module_source_sha256(), "fit_id": fit_id, "arm": arm,
                  "fold": FORWARD_FOLD, "upstream_sha256": upstream, "bound_hooks_state_sha256":
                  BOUND_P3D_N_STATE_SHA256, "sklearn_version": versions["sklearn"],
                  "helper_source_sha256": helper_source_shas()}
    state, info = arm_state(mods, frame, payload_buckets, arm, FORWARD_FOLD, provenance=provenance,
                            conversion=conversion, late_report=late_report)
    if tuple(state["markets"]) != tuple(REQUIRED_FIT_MARKETS):
        raise YearroundRefused("the forward fit lacks training rows for a v12 training market")
    sha = freeze_state(mods.p3, state, out)
    centres = centre_sets(mods.prm)[arm]
    manifest = {
        "schema": FIT_MANIFEST_SCHEMA, "candidate_id": CANDIDATE_ID, "arm": arm, "fit_kind": FIT_KIND,
        "fit_id": fit_id, "fitted_at_utc": now.isoformat(), "frozen_before_utc": FROZEN_BEFORE_UTC,
        "module": MODULE, "module_source_sha256": module_source_sha256(), "upstream_sha256": upstream,
        "versions": versions, "sklearn_version": versions["sklearn"], "state_schema": STATE_SCHEMA,
        "state_sha256": sha, "state_sidecar_sha256": sha256_file(out / mods.p3.STATE_SIDECAR),
        "centres": list(centres), "season_of": season_map(mods.prm, centres), "hours": list(SCORED_HOURS),
        "markets": list(EMIT_MARKETS), "training_markets": list(TRAINING_MARKETS),
        "training_window": list(TRAINING_WINDOW), "training_rows": info["rows"],
        "training_rows_sha256": info["training_rows_sha256_all"],
        "training_rows_sha256_by_hour": info["training_rows_sha256"],
        "bucket_space_sha256": info["bucket_space_sha256"], "scored_window": list(SCORED_WINDOW),
        "emission_window": list(EMISSION_WINDOW), "coverage_window": list(COVERAGE_WINDOW),
        "input_modes": list(INPUT_MODES), "train_F_source": TRAIN_F_SOURCE, "serve_F_source": SERVE_F_SOURCE,
        "conversion": conversion, "late_report": late_report, "hooks_from_state_sha256": BOUND_P3D_N_STATE_SHA256,
        "imputation_by_calendar_month": shares, "imputation_by_market_month": by_market_month,
        "source_presence": source_presence, "build": build_report,
        "records_payload_sha256": {n: e["payload_sha256"] for n, e in records_manifest["files"].items()},
        "extract_failed_closed": records_manifest["extract_failed_closed"],
        "archive_dir": str(ARCHIVE_ROOT / fit_id),
    }
    # the state and sidecar are archived (and verified) BEFORE the manifest is written, so a refused archive leaves
    # no manifest; the manifest then joins the same archive directory, verified too
    archive_dir, archived = archive_copy(out, fit_id, (mods.p3.STATE_FILE, mods.p3.STATE_SIDECAR))
    manifest_sha = _write_json(out / FIT_MANIFEST, manifest)
    archived[FIT_MANIFEST] = archive_add(out, archive_dir, FIT_MANIFEST)
    return {"fit_dir": str(out), "state_sha256": sha, "state_sidecar_sha256": manifest["state_sidecar_sha256"],
            "fit_manifest_sha256": manifest_sha, "archive_dir": archive_dir, "archive_sha256": archived}


# ----------------------------------------------------------------------------- emit (as_of_capture only)

def _replay_dirs(replay_root):
    """(market slug, target date, folder) of every event folder under ``replay_root/snapshots``."""
    pattern = re.compile(r"^highest-temperature-in-(.+)-on-([a-z]+)-(\d+)-(\d{4})$")
    months = {m: i for i, m in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september",
         "october", "november", "december"), start=1)}
    for folder in sorted(Path(replay_root, "snapshots").iterdir()):
        match = pattern.match(folder.name)
        if not match:
            continue
        slug, month, day, year = match.groups()
        yield slug, date(int(year), months[month], int(day)), folder


def shadow_rows(state, snaps, replay_root, first, last, markets, in_coverage=in_dec_may, presence=None,
                hour_presence=None):
    """[(market, snapshot_id, target_date, row_key, distribution)] plus stats; MG-2 ``emit_rows``' gate.

    The row gate is ``mg2_p3d_n.emit_rows`` with ``inputs="as_of_capture"`` (cutoff hour in the intraday set,
    local hour >= cutoff, a usable captured NBM mean, a replay observation with high_so_far and current_temp),
    with ``in_coverage`` in place of rule C5's 08-01..12-16 gate. With C5's gate it equals ``emit_rows``.
    ``presence`` (optional dict) receives, per (market, date) of the gated rows, the counts that
    ``refuse_absent_emit_sources`` reads, counting only the state's fitted hours (master Q1(a), 2026-11-04: an
    as-of-capture input trimmed to the last scored hour must not refuse by construction); ``hour_presence``
    (optional dict) receives per (market, date, state hour) the gated and emitted counts that ``emit_holes`` reads.
    The returned rows and stats are unchanged.
    """
    from zoneinfo import ZoneInfo

    import pandas as pd

    from weather.calibration import mg2_p3d_n as p3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.model.model_constants import INTRADAY_CUTOFF_HOURS

    hours = {int(h) for h in INTRADAY_CUTOFF_HOURS}
    state_hours = {int(h) for h in state["hours"]}
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    rows, stats, used = [], {}, {}
    for market in markets:
        spec = spec_for_id(market)
        tz = ZoneInfo(spec.timezone)
        folders, indexes, cache = {}, {}, {}
        for slug, target, folder in _replay_dirs(replay_root):
            if slug != market or not (first <= target <= last):
                continue
            folders[target.isoformat()] = (target, folder)
        m = stats.setdefault(market, {"emitted": 0, "outside_cutoff_hours": 0, "local_hour_before_cutoff": 0,
                                      "outside_training_coverage": 0, "coverage_fallback": [],
                                      "no_usable_nbm": 0, "no_replay_observation": 0, "missing_metar_feature": 0,
                                      "no_fit_for_hour": 0, "replay_hours": 0, "inputs": "as_of_capture"})
        m["replay_hours"] = len(folders)
        for row in snaps[snaps.market == market].itertuples(index=False):
            try:
                hour = int(str(row.cutoff_hour))
            except ValueError:
                hour = None
            if hour not in hours:
                m["outside_cutoff_hours"] += 1
                continue
            if int(row.local_hour) < hour:
                m["local_hour_before_cutoff"] += 1
                continue
            key = (str(row.target_date)[:10], hour)
            if not in_coverage(key[0]):
                m["outside_training_coverage"] += 1
                m["coverage_fallback"].append(getattr(row, "row_key", None) or row.snapshot_id)
                continue
            tally = htally = None
            if hour_presence is not None and hour in state_hours:
                htally = hour_presence.setdefault((market, key[0], hour), {"gated": 0, "emitted": 0})
                htally["gated"] += 1
            if presence is not None and hour in state_hours:  # Q1(a): the emitter gates on its fitted hours
                tally = presence.setdefault((market, key[0]), {"gated": 0, "nbm": 0, "replay_folder": False,
                                                              "observation": 0})
                tally["gated"] += 1
                tally["replay_folder"] = key[0] in folders
            nbm = float(row.nbm_usable)
            if not math.isfinite(nbm):
                m["no_usable_nbm"] += 1
                continue
            rec = None
            if key[0] in folders:
                target, folder = folders[key[0]]
                if key[0] not in indexes:
                    # read-only use of MG-2's replay index (the public as_of_capture / scan_replay_as_of take it)
                    indexes[key[0]] = p3._replay_index(folder, target, tz)
                    used[folder.name] = folder
                at_local = pd.Timestamp(row.captured_at_utc).tz_convert("UTC").to_pydatetime().astimezone(tz)
                entry = p3.as_of_capture(indexes[key[0]], at_local)
                if entry is not None:
                    ck = (key[0], entry[1], hour)
                    if ck not in cache:
                        cache[ck] = p3.scan_replay_as_of(folder, target, tz, hour, at_local, spec.display_unit,
                                                         indexes[key[0]])
                    rec = cache[ck]
            if tally is not None:
                tally["nbm"] += 1
            if rec is None:
                m["no_replay_observation"] += 1
                continue
            if tally is not None and rec["high_so_far"] is not None and rec["current_temp"] is not None:
                tally["observation"] += 1
            if rec["high_so_far"] is None or rec["current_temp"] is None:
                m["missing_metar_feature"] += 1
                continue
            dist = p3.serve_distribution(state, market=market, target_date=key[0], hour=hour, nbm_mean=nbm,
                                         high_so_far=rec["high_so_far"], current_temp=rec["current_temp"])
            if dist is None:
                m["no_fit_for_hour"] += 1
                continue
            rows.append((market, row.snapshot_id, key[0], getattr(row, "row_key", None), dist))
            m["emitted"] += 1
            if htally is not None:
                htally["emitted"] += 1
    return rows, stats, used


def refuse_absent_emit_sources(snaps, presence, first, last, markets, in_coverage=in_dec_may):
    """Refuse by name a batch (market, date) whose captured source is absent or empty (master 2026-11-03).

    ``captured_snapshots``: no snapshot row at all for an emission market on a batch date in coverage.
    ``captured_metar_replay``: rows passed the hour gates at one of the state's fitted hours (master Q1(a),
    2026-11-04; not the 7..20 intraday set) but the date has no replay folder, or no such row found an observation
    with high_so_far and current_temp. ``captured_nbm``: no such gated row had a usable NBM mean. Fail-closed at
    the state hours; a state hour with no gated row is a named hole (``emit_holes``).
    Per-row drops inside a present source stay counted in the receipt's stats.
    """
    days = snaps["target_date"].astype(str).str[:10]
    have = set(zip(snaps["market"].astype(str), days))
    want = [(m, (first + timedelta(days=i)).isoformat()) for m in markets
            for i in range((last - first).days + 1) if in_coverage((first + timedelta(days=i)).isoformat())]
    missing = [k for k in want if k not in have]
    if missing:
        _refuse_absent("captured_snapshots", missing, len(want))
    gated = {k: v for k, v in presence.items() if v["gated"]}
    for source, bad in (("captured_metar_replay", [k for k, v in gated.items() if not v["replay_folder"]]),
                        ("captured_nbm", [k for k, v in gated.items() if not v["nbm"]]),
                        ("captured_metar_replay", [k for k, v in gated.items() if v["nbm"] and not v["observation"]])):
        if bad:
            _refuse_absent(source, sorted(bad), len(gated))
    return {"market_dates": len(want), "gated_market_dates": len(gated)}


def emit_holes(hour_presence, first, last, markets, hours, in_coverage=in_dec_may):
    """F3(d), hour grain: a NAMED hole per batch (market, date, state hour) in coverage that emitted 0 rows.

    The batch is not refused for a hole (master rulings 2026-11-03/04); the forward prereg's countability rules
    decide its effect. Reasons say what was measured: ``no_gated_snapshot_at_hour`` (no snapshot with this cutoff
    hour reached the local-hour gate) or ``gated_but_not_served`` (gated snapshots at this hour, none served).
    """
    holes = []
    for market in markets:
        for i in range((last - first).days + 1):
            day = (first + timedelta(days=i)).isoformat()
            if not in_coverage(day):
                continue
            for hour in sorted(int(h) for h in hours):
                tally = hour_presence.get((market, day, hour)) or {"gated": 0, "emitted": 0}
                if tally["emitted"]:
                    continue
                reason = "gated_but_not_served" if tally["gated"] else "no_gated_snapshot_at_hour"
                holes.append({"market": market, "target_date": day, "hour": hour, "rows": 0, "reason": reason})
    return holes


def _stat_day(value):
    return value.isoformat()[:10] if hasattr(value, "isoformat") else str(value)[:10]


def read_snapshots(path, first=None, last=None):
    """The captured snapshot layout's label-free columns; any label, settlement or price column refuses.

    With a batch (``first``, ``last``; ruling 4) the row-group statistics of ``target_date`` are checked BEFORE
    any row is read: a row group without statistics, or whose range leaves the batch, refuses (slice the layout
    to the batch). The read then carries a pyarrow ``target_date`` filter, so no out-of-batch row is read.
    """
    import pyarrow.parquet as pq

    from weather.calibration.mg2_p3d_n import SNAPSHOT_COLUMNS

    path = guard_path(path)
    names = list(pq.read_schema(path).names)
    bad = [n for n in names if FORBIDDEN_INPUT_COLUMN.search(n)]
    if bad:
        raise YearroundRefused(f"the snapshot input carries label, settlement or price columns: {bad}")
    missing = [c for c in SNAPSHOT_COLUMNS if c not in names]
    if missing:
        raise YearroundRefused(f"the snapshot input lacks {missing}")
    if first is None and last is None:
        return pq.read_table(path, columns=list(SNAPSHOT_COLUMNS)).to_pandas()
    kind = pq.read_schema(path).field("target_date").type
    if str(kind) not in SNAPSHOT_TARGET_DATE_TYPES:  # F6: a named refusal, never an ArrowNotImplementedError
        raise YearroundRefused(f"snapshot target_date has type {kind}; only {SNAPSHOT_TARGET_DATE_TYPES} are read")
    first, last = as_date(first).isoformat(), as_date(last).isoformat()
    meta = pq.ParquetFile(path).metadata
    col = names.index("target_date")
    for i in range(meta.num_row_groups):
        st = meta.row_group(i).column(col).statistics
        if st is None or not st.has_min_max:
            raise YearroundRefused(f"snapshot row group {i} has no target_date statistics; rewrite the layout")
        if _stat_day(st.min) < first or _stat_day(st.max) > last:
            raise YearroundRefused(f"snapshot row group {i} lies outside the batch window {first}..{last}; "
                                   "slice the layout to the batch")
    lo, hi = (as_date(first), as_date(last)) if "date" in str(kind) else (first, last + "\uffff")
    table = pq.read_table(path, columns=list(SNAPSHOT_COLUMNS),
                          filters=[("target_date", ">=", lo), ("target_date", "<=", hi)])
    return table.to_pandas()


def check_window(first, last, receipt_window, today):
    if first > last:
        raise YearroundRefused("first is after last")
    lo, hi = as_date(EMISSION_WINDOW[0]), as_date(EMISSION_WINDOW[1])
    if first < lo or last > hi:
        raise YearroundRefused(f"the batch lies outside the emission window {EMISSION_WINDOW}")
    if first < as_date(receipt_window[0]) or last > as_date(receipt_window[1]):
        raise YearroundRefused("the batch lies outside the forward receipt's window")
    if (last - first).days + 1 > BATCH_MAX_DAYS:
        raise YearroundRefused(f"a batch spans at most {BATCH_MAX_DAYS} days")
    if last >= today:
        raise YearroundRefused("emission is after the fact: the batch must end before today")
    day = first
    while day <= last:
        if day.month == 2 and day.day == 29:
            raise YearroundRefused("a Feb 29 target date needs a ruling (MG-2's nearest_centre has no Rule L)")
        day += timedelta(days=1)


def load_forward_receipt(path, sha, *, state_sha, manifest_sha):
    receipt = json.loads(_read_verified(path, sha, "forward receipt"))
    if receipt.get("schema") != FORWARD_RECEIPT_SCHEMA or receipt.get("candidate_id") != CANDIDATE_ID:
        raise YearroundRefused("the forward receipt is not a row28_B forward receipt")
    if receipt.get("state_sha256") != state_sha or receipt.get("fit_manifest_sha256") != manifest_sha:
        raise YearroundRefused("the forward receipt does not name this state and fit manifest")
    if not _SHA_RE.fullmatch(str(receipt.get("forward_prereg_sha256", ""))):
        raise YearroundRefused("the forward receipt has no forward prereg sha256")
    if not isinstance(receipt.get("owner_approval"), str) or not receipt["owner_approval"].strip():
        raise YearroundRefused("the forward receipt has no owner approval record")
    window = receipt.get("window")
    if not (isinstance(window, list) and len(window) == 2):
        raise YearroundRefused("the forward receipt has no window")
    if as_date(window[0]) < as_date(EMISSION_WINDOW[0]) or as_date(window[1]) > as_date(EMISSION_WINDOW[1]):
        raise YearroundRefused("the forward receipt's window lies outside the emission window")
    return receipt


def emit(*, state_path, state_sha, fit_manifest, fit_manifest_sha, forward_receipt, forward_receipt_sha,
         snapshots, replay_root, first, last, inputs="as_of_capture", today=None):
    if inputs not in INPUT_MODES:
        raise YearroundRefused(f"emit takes {INPUT_MODES} inputs only (master Q-W)")
    first, last = as_date(first), as_date(last)
    for beside in {Path(fit_manifest).parent, Path(state_path).parent}:
        if (beside / REFUSED_MARKER).exists():
            raise YearroundRefused(f"{beside} holds a {REFUSED_MARKER} marker: it is a refused fit, never a fit")
    manifest = json.loads(_read_verified(fit_manifest, fit_manifest_sha, "fit manifest"))
    if manifest.get("schema") != FIT_MANIFEST_SCHEMA or manifest.get("candidate_id") != CANDIDATE_ID:
        raise YearroundRefused("not a row28_B fit manifest")
    if manifest.get("state_sha256") != state_sha:
        raise YearroundRefused("the fit manifest does not name this state")
    if datetime.fromisoformat(manifest["fitted_at_utc"]) >= datetime.fromisoformat(FROZEN_BEFORE_UTC):
        raise YearroundRefused(f"the state was not frozen before {FROZEN_BEFORE_UTC}")
    refuse_changed_sources(manifest)  # whole-file pins BEFORE any state is unpickled (L16 re-check, 11-03)
    refuse_bound_sha(state_sha, where="emit")
    receipt = load_forward_receipt(forward_receipt, forward_receipt_sha, state_sha=state_sha,
                                   manifest_sha=fit_manifest_sha)
    check_window(first, last, receipt["window"], today or datetime.now().astimezone().date())
    mods = _modules()
    state = mods.p3.load_state(guard_path(state_path), state_sha, forward=True)
    prov = state["provenance"]
    if prov.get("candidate") != CANDIDATE_ID or prov.get("shadow_only") is not True:
        raise YearroundRefused("the state is not a shadow-only row28_B state")
    if _versions()["sklearn"] != manifest.get("sklearn_version"):
        raise YearroundRefused("the sklearn version differs from the fit's (the HGB pickle pin)")
    refuse_changed_helpers(prov.get("helper_source_sha256"))
    snaps = read_snapshots(snapshots, first, last)
    days = snaps["target_date"].astype(str).str[:10]
    if len(days) and (days.min() < first.isoformat() or days.max() > last.isoformat()):
        raise YearroundRefused("a snapshot row lies outside the batch window; slice the layout to the batch")
    shadow_dir = state_root() / CANDIDATE_ID / manifest["fit_id"] / "shadow" / f"{first:%Y%m%d}_{last:%Y%m%d}"
    if shadow_dir.exists():
        raise YearroundRefused(f"{shadow_dir} already exists (write-once)")
    presence, hour_presence = {}, {}
    rows, stats, used = shadow_rows(state, snaps, guard_path(replay_root), first, last, EMIT_MARKETS,
                                    presence=presence, hour_presence=hour_presence)
    source_presence = refuse_absent_emit_sources(snaps, presence, first, last, EMIT_MARKETS)
    holes = emit_holes(hour_presence, first, last, EMIT_MARKETS, state["hours"])
    out = _new_dir(shadow_dir)
    body = "".join(mods.p3.jsonl_line(m, sid, t, d) for m, sid, t, _, d in rows).encode("utf-8")
    (out / SHADOW_ROWS).write_bytes(body)
    shadow_sha = sha256_bytes(body)
    holes_body = "".join(json.dumps(h, sort_keys=True) + "\n" for h in holes).encode("utf-8")
    (out / HOLES).write_bytes(holes_body)
    receipt_out = {
        "schema": SHADOW_RECEIPT_SCHEMA, "candidate_id": CANDIDATE_ID, "fit_id": manifest["fit_id"],
        "state_sha256": state_sha, "fit_manifest_sha256": fit_manifest_sha,
        "forward_receipt_sha256": forward_receipt_sha, "snapshots_sha256": sha256_file(guard_path(snapshots)),
        "replay_sha256": {name: sha256_file(f / "replay_inputs.jsonl") for name, f in sorted(used.items())},
        "first": first.isoformat(), "last": last.isoformat(), "inputs": inputs, "markets": list(EMIT_MARKETS),
        "module_source_sha256": module_source_sha256(), "upstream_sha256": upstream_shas(),
        "serve_F_source": SERVE_F_SOURCE, "rows": len(rows), "stats": stats, "shadow_rows_sha256": shadow_sha,
        "holes": len(holes), "hole_records": holes, "holes_sha256": sha256_bytes(holes_body),
        "source_presence": source_presence,
        "imputation_by_market_month": manifest.get("imputation_by_market_month"),
    }
    receipt_sha = _write_json(out / EMIT_RECEIPT, receipt_out)
    return {"out_dir": str(out), "rows": len(rows), "holes": len(holes), "shadow_rows_sha256": shadow_sha,
            "emit_receipt_sha256": receipt_sha}


# ----------------------------------------------------------------------------- equivalence (design 2.3)

def load_frozen_runner(path, sha):
    """The frozen v12 runner, imported in-process only after its sha check."""
    import importlib.util

    _read_verified(path, sha, "frozen runner")
    spec = importlib.util.spec_from_file_location("yearround_refit_frozen_runner", guard_path(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen_records_list(path, sha):
    """{records basename: payload_sha256} from one frozen path/sha list (columns path, sha256, payload_sha256).

    Only ``records_*.pkl.gz`` rows are kept; a duplicate record name in the list refuses.
    """
    text = _read_verified(path, sha, "frozen records list").decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None or list(reader.fieldnames)[:3] != ["path", "sha256", "payload_sha256"]:
        raise YearroundRefused(f"frozen records list {path} is not a path,sha256,payload_sha256 list")
    out = {}
    for row in reader:
        name = Path(str(row["path"]).replace("\\", "/")).name
        if _RECORD_NAME.match(name):
            if name in out:
                raise YearroundRefused(f"frozen records list {path} names {name} twice")
            out[name] = str(row["payload_sha256"]).strip().lower()
    return out


def frozen_records_lists(sources, expected=None):
    """The union of several frozen lists, given as (path, pinned sha) pairs (master amended ruling 2, 2026-11-03).

    Each list keeps only ``records_*.pkl.gz`` rows. A record named in two lists, or twice in one, refuses; so
    does a union whose count differs from ``expected``.
    """
    if not sources:
        raise YearroundRefused("no frozen records list was given")
    union = {}
    for entry in sources:
        path, sha = (entry["path"], entry["sha256"]) if isinstance(entry, dict) else entry
        if not _SHA_RE.fullmatch(str(sha)):
            raise YearroundRefused(f"frozen records list {path} has no pinned sha256")
        part = frozen_records_list(path, sha)
        overlap = sorted(set(part) & set(union))
        if overlap:
            raise YearroundRefused(f"frozen records lists overlap on {len(overlap)} record(s): {overlap[:3]}")
        union.update(part)
    if expected is not None and len(union) != expected:
        raise YearroundRefused(f"the frozen records union holds {len(union)} records, expected {expected}")
    return union


def frozen_records_union(cfg, prm):
    """The config's ``frozen_records_lists`` union, required to hold every expected record window (24 x 11)."""
    return frozen_records_lists(cfg.get("frozen_records_lists"),
                                expected=len(record_centres(prm)) * len(record_markets(prm)))


def compare_records(ours, frozen):
    """Exact equality with the frozen list (ruling 3): a record missing on EITHER side fails, as does any differ."""
    listed = sorted(set(ours) & set(frozen))
    differ = [n for n in listed if ours[n] != frozen[n]]
    out = {"compared": len(listed), "equal": len(listed) - len(differ), "differ": len(differ),
           "frozen_not_built": len(set(frozen) - set(ours)), "built_not_listed": len(set(ours) - set(frozen))}
    out["pass"] = bool(listed) and not differ and not out["frozen_not_built"] and not out["built_not_listed"]
    return out


def reference_frame(ref, ctx, mods, files, nbm_new_rows, cfg):
    """v12's own path, in-process: its market_frame, merged_table and season_year, then the bound attach."""
    prm, l9 = mods.prm, mods.l9
    noy, meta = ref.market_frame(ctx, files, with_labels=False)
    noy = noy[noy["target_date"].astype(str) <= ref.LAST_TRAIN.isoformat()].reset_index(drop=True)
    table = ref.merged_table(ctx, [cfg["l9_corpus"], nbm_new_rows])
    tz = {m: _timezone(m) for m in prm.R0_MARKETS}
    cycles = [l9.nbm_at_cutoff(table, m, str(d)[:10], int(h), tz[m])[1]
              for m, d, h in zip(noy["market"], noy["target_date"], noy["hour"])]
    inputs, _ = prm.attach_training_nbm(noy, table, l9.nbm_at_cutoff, tz)
    inputs["nbm_cycle"] = cycles
    inputs["sy"] = [ref.season_year(d) for d in inputs["target_date"]]
    labelled, _ = ref.market_frame(ctx, files, with_labels=True)
    labelled = labelled[labelled["target_date"].astype(str) <= ref.LAST_TRAIN.isoformat()].reset_index(drop=True)
    y = labelled.set_index(["market", "target_date", "hour"])["y"]
    return inputs.join(y, on=["market", "target_date", "hour"]), noy, meta


def frame_compare(a, b, keys, tol):
    """Key-aligned comparison of two frames, NaN-aware for numeric AND string columns; counts and maxima only.

    Missing equals missing ONLY at the same key-aligned position; missing on one side and a value on the other
    is a difference (``inf``) for numeric and string columns alike (master review 2026-11-03, deviation 5).

    v12's ``frame_diff`` compares non-numeric columns through ``astype(str)``; under pandas 3's string dtype a
    missing value stays missing, so an identical column with a missing ``nbm_cycle`` would read as different.
    """
    import numpy as np
    import pandas as pd

    a = a.sort_values(keys, kind="mergesort").reset_index(drop=True)
    b = b.sort_values(keys, kind="mergesort").reset_index(drop=True)
    out = {"rows": [int(len(a)), int(len(b))], "columns_only_left": sorted(set(a.columns) - set(b.columns)),
           "columns_only_right": sorted(set(b.columns) - set(a.columns))}
    same = len(a) == len(b) and all((a[k].astype(object).map(str).to_numpy() == b[k].astype(object).map(str)
                                     .to_numpy()).all() for k in keys)
    out["identical_keys"] = bool(same)
    worst = {}
    if same:
        for col in sorted(set(a.columns) & set(b.columns)):
            x, y = a[col], b[col]
            if x.dtype.kind in "fiub" and y.dtype.kind in "fiub":
                xv, yv = x.to_numpy(float), y.to_numpy(float)
                both, one = np.isnan(xv) & np.isnan(yv), np.isnan(xv) ^ np.isnan(yv)
                diff = np.where(both, 0.0, np.abs(xv - yv))
                worst[col] = float("inf") if one.any() else (float(np.max(diff)) if len(diff) else 0.0)
            else:
                xm, ym = pd.isna(x).to_numpy(), pd.isna(y).to_numpy()
                equal = (xm == ym).all() and (x[~xm].astype(object).map(str).to_numpy()
                                              == y[~ym].astype(object).map(str).to_numpy()).all()
                worst[col] = 0.0 if equal else float("inf")
    out["max_abs_diff"] = worst
    out["pass"] = bool(same and not out["columns_only_left"] and not out["columns_only_right"]
                       and all(v <= tol for v in worst.values()))
    return out


def _dist_diff(a, b):
    keys = set(a) | set(b)
    return max((abs(float(a.get(k, 0.0)) - float(b.get(k, 0.0))) for k in keys), default=0.0), set(a) != set(b)


def synthetic_serve_rows(markets=None, hours=None):
    """Fixed serve inputs on the METAR T-group grid in the emission window (no captured value is read)."""
    markets = EMIT_MARKETS if markets is None else markets
    hours = SCORED_HOURS if hours is None else hours
    rows = []
    first = as_date(EMISSION_WINDOW[0])
    for i, market in enumerate(markets):
        for k in range(0, 166, 21):
            day = first + timedelta(days=k + i)
            for hour in hours:
                t = 100 + 7 * i + hour + k % 13
                f = 32 + 9 * t / 50
                rows.append({"market": market, "target_date": day.isoformat(), "hour": hour,
                             "nbm_mean": f + 1.5, "high_so_far": f, "current_temp": 32 + 9 * (t - 4) / 50})
    return rows


def _serve_compare(p3, state_a, state_b, rows):
    worst, mismatch, compared = 0.0, 0, 0
    for r in rows:
        a = p3.serve_distribution(state_a, **r)
        b = p3.serve_distribution(state_b, **r)
        if a is None or b is None:
            mismatch += 1
            continue
        d, m = _dist_diff(a, b)
        worst, mismatch, compared = max(worst, d), mismatch + int(m), compared + 1
    return worst, mismatch, compared


def _serve_vs(served, dist):
    """(max abs difference, mismatch) of a served distribution against a reference; None is a mismatch (F5)."""
    if served is None or dist is None:
        return 0.0, True
    d, m = _dist_diff(served, dist)
    return d, bool(m)


def _forward_trainer_compare(mods, state, fits_ref, buckets_ref, rows):
    """Serve on the round-tripped state against the in-process trainer fit on the converted inputs."""
    import pandas as pd

    p3, prm = mods.p3, mods.prm
    worst, compared, mismatch = 0.0, 0, 0
    for r in rows:
        served = p3.serve_distribution(state, **r)
        if served is None:  # F5: a None served distribution is a mismatch, never a TypeError
            mismatch += 1
            continue
        hs = p3.convert_observation(r["high_so_far"], state)
        ct = p3.convert_observation(r["current_temp"], state)
        tdate = as_date(r["target_date"])
        centre = centre_for(prm, state["centres"], tdate)
        lat, lon, elev = state["coords"][r["market"]]
        doy = tdate.timetuple().tm_yday
        part = pd.DataFrame([{"market": r["market"], "centre": centre, "season": prm.season_of(centre),
                              "hour": r["hour"], "target_date": tdate.isoformat(), "F": float(hs),
                              "fh": float(r["nbm_mean"]), "lat": lat, "lon": lon, "elev": elev,
                              "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                              "doy_cos": math.cos(2 * math.pi * doy / 365.25), "x_high_so_far": float(hs),
                              "x_current_temp": float(ct), "market_code": float(prm.R0_MARKETS.index(r["market"]))}])
        entry = fits_ref[(r["hour"], None)]
        ((_, _, _), _, _, dist), = trainer_predict(mods, entry["fit"], entry["train_y"], buckets_ref, part)
        d, m = _serve_vs(served, dist)
        worst, mismatch, compared = max(worst, d), mismatch + int(m), compared + 1
    return worst, compared, mismatch


def read_frozen_rows(path, sha):
    """Mode ``per_row``: a LABEL-FREE extract (fold, hour, market, date and ``<arm>_yhat`` / ``<arm>_s`` only)."""
    text = _read_verified(path, sha, "frozen per-row extract").decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    allowed = re.compile(r"^(fold|hour|market|date|[AB]_yhat|[AB]_s)$")
    bad = [c for c in reader.fieldnames or [] if not allowed.match(c)]
    if bad:
        raise YearroundRefused(f"the per-row extract carries columns outside the label-free set: {bad}")
    return list(reader)


def equivalence(cfg, *, records_root, frozen_runner, frozen_runner_sha, mode="state_sha", frozen_rows=None,
                frozen_rows_sha=None,
                now=None, fit=fit_hour):
    if mode not in ("state_sha", "per_row"):
        raise YearroundRefused(f"unknown equivalence mode {mode!r}")
    if mode == "per_row" and not (frozen_rows and frozen_rows_sha):
        raise YearroundRefused("mode per_row needs --frozen-rows and --frozen-rows-sha")
    refuse_legacy_config(cfg)
    if not cfg.get("frozen_records_lists"):  # refused before any directory or record is written
        raise YearroundRefused("equivalence requires frozen_records_lists ([path, sha256] pairs) in the config")
    records = records_root_arg(records_root, cfg)
    if records.exists() and any(records.iterdir()):
        raise YearroundRefused("the equivalence run needs a NEW records root")
    mods = _modules()
    prm, p3 = mods.prm, mods.p3
    frozen_union = frozen_records_union(cfg, prm)  # a malformed list refuses before any write
    now = now or utc_now()
    out = _new_dir(state_root() / CANDIDATE_ID / "equivalence" / now.strftime("%Y%m%dT%H%M%SZ"))
    report = {"schema": EQUIVALENCE_SCHEMA, "candidate_id": CANDIDATE_ID, "mode": mode,
              "module_source_sha256": module_source_sha256(), "upstream_sha256": upstream_shas(),
              "frozen_runner_sha256": frozen_runner_sha, "versions": _versions(), "started_utc": now.isoformat(),
              "tolerance": TOLERANCE, "frame_tolerance": FRAME_TOLERANCE}
    ref = load_frozen_runner(frozen_runner, frozen_runner_sha)
    centres = centre_sets(prm)
    ctx = SimpleNamespace(cfg=cfg, prm=prm, fm=mods.fm, l9=mods.l9, centres=dict(centres, C=centres["A"],
                                                                                   D=centres["A"]))
    passes = []

    # (a) build
    files, records_manifest = build_records(cfg, prm, records)
    ours = {n: e["payload_sha256"] for n, e in records_manifest["files"].items()}
    rec = compare_records(ours, frozen_union)
    report["records"] = rec
    passes.append(("records", rec["pass"]))
    frame, payload_buckets, build_report = training_frame(cfg, mods, files, out / "work_nbm")
    new_rows = out / "work_nbm" / "new" / "nbm_pit_corpus_rows.jsonl"
    want = cfg.get("frozen_new_nbm_rows_sha256")
    report["new_nbm_rows"] = {"sha256": build_report["new_nbm_rows_sha256"], "frozen_sha256_given": bool(want),
                              "equal_to_frozen": bool(want) and build_report["new_nbm_rows_sha256"] == want}
    passes.append(("new_nbm_rows", report["new_nbm_rows"]["equal_to_frozen"]))  # ruling 3: absent FAILS
    ref_frame, ref_noy, _ = reference_frame(ref, ctx, mods, files, new_rows, cfg)
    our_noy, _ = market_frame(prm, files, with_labels=False)
    our_noy = our_noy[our_noy["target_date"].astype(str) <= LAST_TRAIN.isoformat()].reset_index(drop=True)
    keys = ["market", "payload_centre", "hour", "target_date"]
    report["y_free_frame"] = frame_compare(our_noy, ref_noy, keys, FRAME_TOLERANCE)
    report["input_frame"] = frame_compare(frame.drop(columns=["y"]), ref_frame.drop(columns=["y"]),
                                          keys, FRAME_TOLERANCE)  # labels are not compared (design 2.3)
    passes += [("y_free_frame", report["y_free_frame"]["pass"]), ("input_frame", report["input_frame"]["pass"])]
    # the fit's hard checks F3(a)/(b) and the F3(c) counts on the bound inputs, REPORTED (not a pass check)
    report["training_source_checks"] = training_source_checks(frame, "B", records_manifest.get("covered_years"), prm,
                                                              holes_path=out / TRAINING_GRID_HOLES_FILE)

    # (b) row sets and (c) fits
    per_row = {}
    if mode == "per_row":
        for r in read_frozen_rows(frozen_rows, frozen_rows_sha):
            per_row[(int(r["fold"]), int(r["hour"]), r["market"], r["date"])] = r
    sets, fits_out = [], []
    worst_ref = defaultdict(float)
    for arm in ARMS:
        framed = with_arm_centres(prm, centres, frame, arm)
        framed_ref = ref.with_arm_centres(ctx, ref_frame, arm)
        for fold in FOLDS + ((FORWARD_FOLD,) if arm == "B" else ()):
            hour_fits, hour_buckets = {}, {}
            for hour in SCORED_HOURS:
                train = arm_rows(framed, arm, hour, fold)
                train_ref = ref.arm_training(framed_ref, arm, hour, fold)
                check_training_window(train)
                b, b_ref = arm_buckets(payload_buckets, train), ref.arm_buckets(payload_buckets, train_ref)
                entry = {"arm": arm, "fold": fold, "hour": hour, "rows": [int(len(train)), int(len(train_ref))],
                         "ordered_keys_equal": row_keys_sha256(train) == row_keys_sha256(train_ref),
                         "buckets_equal": b == b_ref, "training_rows_sha256": row_keys_sha256(train)}
                entry["pass"] = entry["ordered_keys_equal"] and entry["buckets_equal"]
                sets.append(entry)
                passes.append((f"row_set:{arm}:{fold}:{hour}", entry["pass"]))
                fit_m = fit(prm, train)
                fit_r = {"fit": prm.fit_pooled(train_ref, **FIT_KWARGS),
                         "train_y": {m: [int(v) for v in train_ref.loc[train_ref["market"] == m, "y"]]
                                     for m in sorted(train_ref["market"].unique())}}
                hour_fits[hour], hour_buckets[hour] = (fit_m, fit_r), (b, b_ref)
                if fold == FORWARD_FOLD:
                    continue
                val = framed[(framed["hour"] == hour) & (framed["sy"] == fold)
                             & framed["market"].isin(EMIT_MARKETS)].drop(columns=["y"]).reset_index(drop=True)
                mine = trainer_predict(mods, fit_m["fit"], fit_m["train_y"], b, val)
                theirs = trainer_predict(mods, fit_r["fit"], fit_r["train_y"], b_ref, val)
                state_h = p3.state_from_fits({(hour, None): fit_m}, b, frame_columns=set(frame.columns),
                                             markets=[m for m in prm.R0_MARKETS if m in b],
                                             centres=list(centres[arm]),
                                             season_of=season_map(prm, centres[arm]),
                                             coords=prm.station_coordinates(prm.R0_MARKETS), fit_kind=FIT_KIND,
                                             provenance={"equivalence": True})
                feb29 = int(val["target_date"].astype(str).str[5:10].eq("02-29").sum())
                c = {"arm": arm, "fold": fold, "hour": hour, "mode": mode, "rows": len(mine),
                     "expected_rows": int(len(val)), "rows_reference": len(theirs), "trainer_compared": 0,
                     "expected_serve": int(len(val)) - feb29, "serve_compared": 0, "max_abs_yhat": 0.0,
                     "max_abs_s": 0.0, "max_abs_dist": 0.0, "max_abs_serve": 0.0, "bucket_set_mismatch": 0,
                     "feb29_serve_skipped": 0, "serve_mismatch": 0, "per_row_compared": 0,
                     "per_row_s_compared": 0, "max_abs_per_row_yhat": 0.0, "max_abs_per_row_s": 0.0}
                if [k for k, *_ in mine] != [k for k, *_ in theirs]:
                    c["row_keys_differ"] = True
                for (key, yh, s, dist), (_, yh_r, s_r, dist_r) in zip(mine, theirs):
                    c["trainer_compared"] += 1
                    c["max_abs_yhat"] = max(c["max_abs_yhat"], abs(yh - yh_r))
                    c["max_abs_s"] = max(c["max_abs_s"], abs(s - s_r))
                    d, m = _dist_diff(dist, dist_r)
                    c["max_abs_dist"], c["bucket_set_mismatch"] = max(c["max_abs_dist"], d), c["bucket_set_mismatch"] + m
                    market, day, h = key
                    if day[5:10] == "02-29":
                        c["feb29_serve_skipped"] += 1
                    else:
                        row = val[(val["market"] == market) & (val["target_date"].astype(str) == day)].iloc[0]
                        served = p3.serve_distribution(state_h, market=market, target_date=day, hour=h,
                                                       nbm_mean=float(row["fh"]), high_so_far=float(row["F"]),
                                                       current_temp=float(row["x_current_temp"]))
                        d, m = _serve_vs(served, dist_r)
                        if served is None:
                            c["serve_mismatch"] += 1
                        else:
                            c["max_abs_serve"] = max(c["max_abs_serve"], d)
                            c["serve_mismatch"] += int(m)
                            c["serve_compared"] += 1
                    frozen = per_row.get((fold, h, market, day))
                    if frozen and frozen.get(f"{arm}_yhat") not in (None, ""):
                        c["per_row_compared"] += 1
                        c["max_abs_per_row_yhat"] = max(c["max_abs_per_row_yhat"],
                                                        abs(yh - float(frozen[f"{arm}_yhat"])))
                    if frozen and frozen.get(f"{arm}_s") not in (None, ""):
                        c["per_row_s_compared"] += 1
                        c["max_abs_per_row_s"] = max(c["max_abs_per_row_s"], abs(s - float(frozen[f"{arm}_s"])))
                # every compare covers ALL rows against counts fixed before comparing; none passes with 0
                c["coverage_complete"] = (c["expected_rows"] > 0 and c["rows"] == c["rows_reference"]
                                          == c["trainer_compared"] == c["expected_rows"]
                                          and c["feb29_serve_skipped"] == feb29
                                          and c["serve_compared"] == c["expected_serve"] > 0)
                c["pass"] = (c["coverage_complete"] and not c.get("row_keys_differ") and c["bucket_set_mismatch"] == 0
                             and c["serve_mismatch"] == 0
                             and max(c["max_abs_yhat"], c["max_abs_s"], c["max_abs_dist"], c["max_abs_serve"])
                             <= TOLERANCE)
                if mode == "per_row":
                    c["pass"] = (c["pass"] and c["per_row_compared"] == c["rows"] == c["per_row_s_compared"]
                                 and max(c["max_abs_per_row_yhat"], c["max_abs_per_row_s"]) <= TOLERANCE)
                for k in ("max_abs_yhat", "max_abs_s", "max_abs_dist", "max_abs_serve"):
                    worst_ref[k] = max(worst_ref[k], c[k])
                fits_out.append(c)
                passes.append((f"fit:{arm}:{fold}:{hour}", c["pass"]))
            if fold == FORWARD_FOLD:
                report["forward"] = _forward_equivalence(mods, cfg, out, arm, centres, frame, hour_fits,
                                                         hour_buckets)
                passes.append(("forward", report["forward"]["pass"]))
    report["row_sets"] = sets
    report["fits"] = fits_out
    report["max_abs"] = dict(worst_ref)
    if mode == "state_sha" and "forward" not in report:
        passes.append(("forward", False))  # STATE-SHA mode cannot pass without its forward state compare
    report["failed_checks"] = [name for name, ok in passes if not ok]
    report["pass"] = bool(passes) and not report["failed_checks"]
    report["status"] = "PASS" if report["pass"] else "FAIL"
    report_sha = _write_json(out / EQUIVALENCE_REPORT, report)
    return {"out_dir": str(out), "status": report["status"], "equivalence_report_sha256": report_sha}


def _forward_equivalence(mods, cfg, out, arm, centres, frame, hour_fits, hour_buckets):
    """B's fold-2026 state: module fit vs v12 re-fit (state sha and serve to 1e-12), then a write/load round trip."""
    prm, p3 = mods.prm, mods.p3
    conversion, late_report = bound_hooks(mods, cfg)
    b = hour_buckets[SCORED_HOURS[0]]
    if any(hour_buckets[h] != b for h in SCORED_HOURS):
        return {"pass": False, "reason": "bucket space differs across hours or from the reference"}
    kw = dict(frame_columns=set(frame.columns), markets=[m for m in prm.R0_MARKETS if m in b[0]],
              centres=list(centres[arm]),
              season_of=season_map(prm, centres[arm]), coords=prm.station_coordinates(prm.R0_MARKETS),
              fit_kind=FIT_KIND, provenance={"candidate": CANDIDATE_ID, "shadow_only": True, "equivalence": True},
              conversion=conversion, late_report=late_report)
    state_m = p3.state_from_fits({(h, None): hour_fits[h][0] for h in SCORED_HOURS}, b[0], **kw)
    state_r = p3.state_from_fits({(h, None): hour_fits[h][1] for h in SCORED_HOURS}, b[1], **kw)
    sha_m = sha256_bytes(pickle.dumps(state_m, protocol=4))
    sha_r = sha256_bytes(pickle.dumps(state_r, protocol=4))
    rows = synthetic_serve_rows(markets=[m for m in EMIT_MARKETS if m in state_m["markets"]])
    expected = len(rows)  # fixed before any compare (ruling 4 per mode: counts asserted, none passes with 0)
    serve_max, serve_mismatch, serve_n = _serve_compare(p3, state_m, state_r, rows)
    sha_written = p3.write_state(state_m, out / "forward_state")
    loaded = p3.load_state(out / "forward_state" / p3.STATE_FILE, sha_written, forward=True)
    rt_max, rt_mismatch, rt_n = _serve_compare(p3, state_m, loaded, rows)
    trainer_fits = {(h, None): hour_fits[h][1] for h in SCORED_HOURS}
    trainer_max, trainer_n, trainer_mismatch = _forward_trainer_compare(mods, loaded, trainer_fits, b[1], rows)
    result = {"state_sha256_module": sha_m, "state_sha256_reference": sha_r, "state_sha_equal": sha_m == sha_r,
              "serve_rows": len(rows), "max_abs_serve": serve_max, "serve_bucket_mismatch": serve_mismatch,
              "round_trip_sha_equal": sha_written == sha_m, "max_abs_round_trip": rt_max,
              "round_trip_bucket_mismatch": rt_mismatch, "max_abs_trainer": trainer_max,
              "expected_rows": expected, "serve_compared": serve_n, "round_trip_compared": rt_n,
              "trainer_compared": trainer_n, "trainer_mismatch": trainer_mismatch}
    result["coverage_complete"] = expected > 0 and serve_n == rt_n == trainer_n == expected
    result["pass"] = (result["coverage_complete"] and result["state_sha_equal"] and result["round_trip_sha_equal"]
                      and serve_mismatch == 0 and rt_mismatch == 0 and trainer_mismatch == 0
                      and max(serve_max, rt_max, trainer_max) <= TOLERANCE)
    return result


# ----------------------------------------------------------------------------- grid-holes (check-only)

def verify_existing_records_root(cfg, prm, records):
    """The read-only half of ``build_records``' reuse checks, for a check-only reader of an EXISTING root.

    The manifest must exist (nothing is ever built here), have no fail-closed or skipped entry, hold exactly the
    expected record windows with matching payload shas and nothing else, and equal the config's frozen records
    union. Its builder's module sha is reported, not required: the frozen union is the integrity check.
    """
    manifest_path = records / RECORDS_MANIFEST
    if not manifest_path.is_file():
        raise YearroundRefused(f"grid-holes reads an existing records root only: {records} has no {RECORDS_MANIFEST}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != RECORDS_MANIFEST_SCHEMA:
        raise YearroundRefused("records manifest schema differs")
    refuse_incomplete_records(manifest)
    if sorted(manifest["files"]) != expected_record_names(prm, records):
        raise YearroundRefused("the records root's file set differs from the expected record windows")
    for name, entry in manifest["files"].items():
        if payload_sha256(records / name) != entry["payload_sha256"]:
            raise YearroundRefused(f"record {name} differs from its records manifest")
    if sorted(p.name for p in records.glob("records_*.pkl.gz")) != sorted(manifest["files"]):
        raise YearroundRefused("the records root holds files outside its records manifest")
    refuse_records_not_frozen({n: e["payload_sha256"] for n, e in manifest["files"].items()},
                              frozen_records_union(cfg, prm))
    return sorted(records / n for n in manifest["files"]), manifest


def grid_holes(cfg, *, records_root, out, expected=None):
    """Check-only: the NAMES of B's calendar-grid holes on an existing, frozen-equal records root (master 11-04).

    Reads the records with ``market_frame(with_labels=False)`` (each label is masked to presence at load), cut to
    ``LAST_TRAIN``, and asserts that the frame holds no label column. It writes ONE names-only file under ``out``,
    a NEW directory outside every checkout, and nothing else; it touches no fit, state or emit path. It refuses
    unless the grid and hole counts equal ``expected`` (default ``GRID_HOLES_EXPECTED``, the accepted report).
    """
    refuse_legacy_config(cfg)
    if not cfg.get("frozen_records_lists"):
        raise YearroundRefused("grid-holes requires frozen_records_lists ([path, sha256] pairs) in the config")
    want = dict(GRID_HOLES_EXPECTED if expected is None else expected)
    records = records_root_arg(records_root, cfg)
    out = check_records_root(out)  # no reparse point on the path, not inside any checkout or its data folder
    if out.exists():
        raise YearroundRefused(f"refusing to reuse {out} (write-once)")
    mods = _modules()
    prm = mods.prm
    prm.require_output_outside_repo(out)
    files, manifest = verify_existing_records_root(cfg, prm, records)
    frame, _ = market_frame(prm, files, with_labels=False)
    if "y" in frame.columns or "y_present" not in frame.columns:
        raise YearroundRefused("grid-holes needs the label-free frame (no y column)")
    frame = frame[frame["target_date"].astype(str).str[:10] <= LAST_TRAIN.isoformat()].reset_index(drop=True)
    grid = expected_training_grid(prm, manifest.get("covered_years"), "B")
    holes = training_grid_holes(frame, grid)
    got = {"expected_market_dates": len(grid), "holes": len(holes)}
    if got != want:
        raise YearroundRefused(f"grid-holes self-check: {got} differs from the expected {want}")
    body = {"schema": GRID_HOLES_SCHEMA, "candidate_id": CANDIDATE_ID, "arm": "B",
            "module_source_sha256": module_source_sha256(),
            "records_manifest_module_sha256": manifest.get("module_source_sha256"),
            "records_root": str(records), "frame_rows": int(len(frame)), **grid_hole_names(holes, len(grid))}
    spring_forward = [(m, d) for m, d in holes if _us_spring_forward(as_date(d))]
    others = [(m, d, "march_1" if as_date(d).month == 3 and as_date(d).day == 1 else "other")
              for m, d in holes if not _us_spring_forward(as_date(d))]
    body["wu_store_checks"] = wu_store_checks(spring_forward, REQUIRED_FIT_MARKETS, other_holes=others)
    out.mkdir(parents=True)
    path = out / GRID_HOLES_FILE
    sha = _write_json(path, body)
    return {"out_file": str(path), "sha256": sha, "holes": body["holes"],
            "expected_market_dates": body["expected_market_dates"], "in_forward_window": body["in_forward_window"],
            "has_2024_02_29": body["has_2024_02_29"], "has_2024_03_01": body["has_2024_03_01"],
            "by_class_counts": {k: v["count"] for k, v in body["by_class"].items()}}


# ----------------------------------------------------------------------------- WU-store booleans (grid-holes)

def us_fall_back_sunday(year):
    """The first Sunday of November: the US end of daylight saving time."""
    day = date(int(year), 11, 1)
    return day + timedelta(days=(6 - day.weekday()) % 7)


def _wu_market_root(market):
    from weather.market.market_registry import spec_for_id

    return guard_path(spec_for_id(market).data_root)


def _daily_date_token(line):
    """The local_date token of one daily_summary line: the text between the first and second comma, nothing else.

    The first field (schema_version) must be plain text; the line is never split past the date token.
    """
    first, sep, rest = line.partition(",")
    if not sep or not _PLAIN_FIRST_FIELD.fullmatch(first) or not _DATE_TOKEN.fullmatch(rest[:10]) or rest[10:11] != ",":
        raise YearroundRefused("a daily_summary line has no plain schema_version field and local_date token")
    return rest[:10]


def wu_daily_presence(path, dates):
    """Per date: ``daily_row_present``, ``row_count`` and ``row_count_ge_20``, by date token (master Option A).

    The header must begin with ``WU_DAILY_HEADER_PREFIX``. Each line is compared by its date token only; the scan
    STOPS at the first token on or after ``WU_READ_CUTOFF`` (that line and every later one are never parsed) and
    REFUSES on a descending token. Only a target date's line is csv-parsed, and only its ``row_count`` is converted
    (``int(row_count or 0)``, as model_climatology does); every other field stays an uninterpreted string.
    """
    want = {str(d) for d in dates}
    if any(d >= WU_READ_CUTOFF for d in want):
        raise YearroundRefused(f"a WU-store date is on or after {WU_READ_CUTOFF}")
    out = {d: {"daily_row_present": False, "row_count": None, "row_count_ge_20": False} for d in sorted(want)}
    if not Path(path).is_file():
        return out
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        header = handle.readline()
        if not header.startswith(WU_DAILY_HEADER_PREFIX):
            raise YearroundRefused(f"{path}: the header does not begin {WU_DAILY_HEADER_PREFIX!r}")
        row_count_at = WU_DAILY_HEADER_PREFIX.split(",").index("row_count")
        previous = ""
        for line in handle:
            token = _daily_date_token(line)
            if token >= WU_READ_CUTOFF:
                break
            if token < previous:
                raise YearroundRefused(f"{path}: the date tokens descend (the file is not date-sorted)")
            previous = token
            if token in want:
                field = next(csv.reader([line]))[row_count_at]
                count = int(field or 0)
                out[token] = {"daily_row_present": True, "row_count": count,
                              "row_count_ge_20": count >= WU_HISTORY_MIN_ROW_COUNT}
    return out


def wu_hourly_presence(root, dates):
    """Per date: whether the month's hourly file holds a line with the raw text ``"local_date": "<date>"``.

    Only each target date's own month file is opened (never after ``WU_HOURLY_LAST_MONTH``); no line is parsed.
    """
    out = {}
    for d in sorted({str(x) for x in dates}):
        if d[:7] > WU_HOURLY_LAST_MONTH:
            raise YearroundRefused(f"an hourly WU month after {WU_HOURLY_LAST_MONTH} is never opened")
        path = Path(root) / "hourly" / f"year={d[:4]}" / f"month={d[5:7]}" / "observations.jsonl"
        needle = f'"local_date": "{d}"'
        present = False
        if path.is_file():
            with path.open("r", encoding="utf-8") as handle:
                present = any(needle in line for line in handle)
        out[d] = present
    return out


def wu_store_checks(spring_forward_holes, markets, other_holes=()):
    """Spring-forward grid holes (a refusal refuses), every other grid hole with its class (report-only, master
    R-a 2026-11-04) and every market's fall-back Sundays (report-only). The same Option A bounds read them all."""
    fall_back = [us_fall_back_sunday(y).isoformat() for y in FALL_BACK_YEARS]
    holes_by_market, others_by_market = defaultdict(list), defaultdict(dict)
    for m, d in spring_forward_holes:
        holes_by_market[m].append(d)
    for m, d, cls in other_holes:
        others_by_market[m][d] = cls
    spring, other, fall = [], [], []
    for market in sorted(set(markets) | set(holes_by_market) | set(others_by_market)):
        root = _wu_market_root(market)
        dates = sorted(set(holes_by_market[market]) | set(others_by_market[market]) | set(fall_back))
        try:
            daily = wu_daily_presence(root / "daily" / "daily_summary.csv", dates)
            hourly = wu_hourly_presence(root, dates)
        except YearroundRefused as exc:
            if holes_by_market[market]:
                raise
            other += [{"market": market, "target_date": d, "class": c, "refused": str(exc)}
                      for d, c in sorted(others_by_market[market].items())]
            fall += [{"market": market, "target_date": d, "refused": str(exc)} for d in fall_back]
            continue
        for d in dates:
            entry = {"market": market, "target_date": d, **daily[d], "hourly_row_present": hourly[d]}
            if d in holes_by_market[market]:
                spring.append(entry)
            if d in others_by_market[market]:
                other.append({**entry, "class": others_by_market[market][d]})
            if d in fall_back:
                fall.append(dict(entry))
    return {"caveat": WU_STORE_CAVEAT, "spring_forward_holes": spring, "other_holes_report_only": other,
            "fall_back_sundays_report_only": fall}


# ----------------------------------------------------------------------------- CLI

_REFUSED_FLAGS = ("--live", "--execute", "--place", "--cancel", "--promote")


def _parser():
    parser = argparse.ArgumentParser(prog=MODULE, description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fit", help="fit B's forward state (write-once) and archive it")
    f.add_argument("--arm", choices=FIT_ARMS, required=True)
    f.add_argument("--config", required=True)
    f.add_argument("--config-sha", required=True)
    f.add_argument("--records-root", required=True)
    f.add_argument("--declare-absent", help="master-ruled source_absent_final grid-hole records (JSON)")
    f.add_argument("--declare-absent-sha")
    e = sub.add_parser("emit", help="one weekly shadow batch on captured inputs (as_of_capture)")
    for name in ("--state", "--state-sha", "--fit-manifest", "--fit-manifest-sha", "--forward-receipt",
                 "--forward-receipt-sha", "--snapshots", "--replay-root", "--first", "--last"):
        e.add_argument(name, required=True)
    e.add_argument("--inputs", choices=INPUT_MODES, default="as_of_capture")
    q = sub.add_parser("equivalence", help="the module against the frozen v12 runner (design 2.3)")
    q.add_argument("--config", required=True)
    q.add_argument("--config-sha", required=True)
    q.add_argument("--records-root", required=True)
    q.add_argument("--frozen-runner", required=True)
    q.add_argument("--frozen-runner-sha", default=FROZEN_RUNNER_SHA256)
    q.add_argument("--mode", choices=("state_sha", "per_row"), default="state_sha")
    q.add_argument("--frozen-rows")
    q.add_argument("--frozen-rows-sha")
    g = sub.add_parser("grid-holes", help="check-only: the names of B's calendar-grid holes (names only, no values)")
    g.add_argument("--config", required=True)
    g.add_argument("--config-sha", required=True)
    g.add_argument("--records-root", required=True)
    g.add_argument("--out", required=True)
    return parser


def _config(path, sha):
    return json.loads(_read_verified(path, sha, "config"))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a.split("=", 1)[0] in _REFUSED_FLAGS for a in argv):
        raise SystemExit(f"{MODULE} has no live, execute, place, cancel or promote path")
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[var] = THREADS  # v12 H4: pinned before numpy or sklearn is imported (the imports are lazy)
    args = _parser().parse_args(argv)
    if args.command == "fit":
        result = fit(_config(args.config, args.config_sha), arm=args.arm, records_root=args.records_root,
                     declared_absent=args.declare_absent, declared_absent_sha=args.declare_absent_sha)
    elif args.command == "emit":
        result = emit(state_path=args.state, state_sha=args.state_sha, fit_manifest=args.fit_manifest,
                      fit_manifest_sha=args.fit_manifest_sha, forward_receipt=args.forward_receipt,
                      forward_receipt_sha=args.forward_receipt_sha, snapshots=args.snapshots,
                      replay_root=args.replay_root, first=args.first, last=args.last, inputs=args.inputs)
    elif args.command == "grid-holes":
        result = grid_holes(_config(args.config, args.config_sha), records_root=args.records_root, out=args.out)
        print(json.dumps(result, indent=1, sort_keys=True))
        return 4 if result["in_forward_window"] else 0  # a hole in Dec 17..Jan 30 is a STOP for master
    else:
        if args.frozen_runner_sha != FROZEN_RUNNER_SHA256:
            raise SystemExit("the frozen runner must be row28_run_v12.py 9e97c892...")
        result = equivalence(_config(args.config, args.config_sha), records_root=args.records_root,
                             frozen_runner=args.frozen_runner,
                             frozen_runner_sha=args.frozen_runner_sha, mode=args.mode, frozen_rows=args.frozen_rows,
                             frozen_rows_sha=args.frozen_rows_sha)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
