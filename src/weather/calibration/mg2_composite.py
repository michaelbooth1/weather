r"""MG-2 composite binding: MG-1 + lane L6's own-observation stack before 13:00, L2's P3d_N after.

Research and shadow only. Nothing in serving, capture, release or Scheduler imports this module; the
import refuses from a production package and on the dedicated capture host (see
``_refuse_production_import``). Forward scoring is by captured-input replay at a frozen code and
coefficient hash; no capture-host serving change is made or needed.

The composite, per snapshot (``SWITCH_HOUR`` = 13, fixed by the rule):

* ``local_hour < 13``: lane L6's own-obs stack over MG-1
  (``weather.reporting.scorecards.free_source_candidates.l6_stack``: mu = v2_mean + a_h + b_h (N - v2_mean)
  at hours 07-12 where the own-obs nowcast N exists; MG-1 exactly otherwise), with N = ``n_own`` built from
  the captured METAR rows (``captured_nowcast``, lane L3's ecd8c9ba6 reader) and served by the frozen
  season-matched L6 own-model state (MG-2 clarification season-L6 2026-10-26 section 3): loaded only at its
  bound sha256 through ``weather.model.mg_serve_core.load_l6_own_state`` and served through
  ``mg_serve_core.l6_own_nowcast``, with no per-run refit, on every date;
* ``local_hour >= 13``: P3d_N, lane L2's pooled residual model anchored on the captured NBM 07Z ``v2_mean``
  with the METAR-only running max as floor and feature (``weather.calibration.mg2_p3d_n``, frozen state);
  MG-1 where P3d_N has no distribution or no mass on a band the rule-4 floor allows.

Floor and calibration are MG-1's: every vector, both halves and the MG-1 comparator, goes through the
dev scorecard's rule-4 floor mask (``Table.candidate_vector``); there is no calibration stage in MG-1,
so there is none here. MG-1 itself falls back to the served vector.

Subcommands (heavy ones run through ``scripts\ops\workstation_heavy.ps1``):

* ``dev``: the composite through the dev scorecard on the dev window (selection evidence only), with the
  component controls and the per-cell deltas used to size the forward look;
* ``freeze``: the frozen L6 coefficients file (stack a_h, b_h on every dev snapshot through 2026-09-29 on the
  captured-METAR nowcasts; their provenance). P3d_N's state is frozen by L2 (``mg2_p3d_n``) and bound
  separately by its file sha;
* ``captured-nowcast``: L6 ``n_own`` from the captured METAR rows for a window, through the frozen L6 state
  named by ``--l6-state`` and ``--l6-state-sha256`` (binding-time inputs, never defaults);
* ``emit``: captured-input replay of the composite for a date range, at the frozen coefficients;
* ``check``: the outcome-blind checks MG-1 section 7 permits (coverage, PIT, replay reproduction, parser
  version); reads no label, settlement, price or market file;
* ``score``: the one forward look. Refuses any target date inside the MG-1 reserved window
  (``weather.mg1_reserved_window``) unless the rule carries a dated owner decision id.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

NAME = "mg2_composite"
SWITCH_HOUR = 13
SCHEMA = "mg2_composite/1"
RULE_BLOCK = "mg2_rule_v1"
DEV_LAST = date(2026, 9, 29)
REPLAY_TOLERANCE = 1e-12
COVERAGE_MIN = 0.90
POST = "p3d_n"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
OWNER_DECISION_ID = re.compile(r"^OD-(\d{4}-\d{2}-\d{2})-[A-Za-z0-9][A-Za-z0-9_.-]*$")
LABEL_FILES = ("labels.parquet", "market.parquet")
FORWARD_PREV_DAY_SOURCE = "bundle prev_day"  # captured_nowcast's prev_day_source on a forward (bundle) run
NOWCASTS_MANIFEST = "nowcasts_manifest.json"
CHECKS = "mg2_checks.json"  # the outcome-blind ``check`` output, beside the emission it checked
# Rule section 7, in order. Every one is recorded by ``score`` as true or false; none may be left unevaluated.
SECTION7_CONDITIONS = ("coverage", "pit", "parser", "replay", "hashes", "nowcast_replay", "p3d_n_replay",
                       "window_leakage")
# Section 7 nowcast replay under the season-L6 clarification (section 3): L3's captured dev serve features
# through the bound state. The window is the captured dev nowcast's (07-30..09-29).
DEV_SERVE_FEATURES_SHA256 = "0d5c30b39e92e4df8d6201769bbf1eb773f2e7e89c6d2a060a04d5bd70990557"
DEV_NOWCAST_WINDOW = ("2026-07-30", "2026-09-29")
# The season-matched dev nowcast pin (clarification season-L6 section 3; B-1 clarification section 6). A code
# constant, not a B-1 block field: ``nowcast_replay_check`` refuses any other pin sha passed on the CLI.
DEV_NOWCAST_PIN_SHA256 = "714fa14e04c416da922803514fea1de8fe64459a0ea543878ddddfd6bc34896a"
# Section 7 P3d_N replay: L2's dev emission dev_P3d_N.jsonl, reproduced by ``mg2_p3d_n control``.
P3D_N_DEV_REFERENCE_SHA256 = "721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec"
MG1_FILE = "src/weather/reporting/scorecards/free_source_candidates/mg1.py"

# Serve parity: every input to a forward MG-2 vector must come from the capture at replay time, with no
# external fetch. Fixed inputs are read from captured replay files; the two inputs below are named by the
# rule. A source id is "captured" only if its reader takes nothing but captured replay inputs.
CAPTURED = "captured"
EXTERNAL = "external_fetch"
SOURCES = {
    # forecast anchor for the post-13 arm (P3d_N; key kept as forecast_high_source)
    "captured_nbm_v2_mean_07z": {
        "input": "forecast_high", "class": CAPTURED,
        "note": "the layout's v2_mean (NBM NBP 07Z cycle of the target date), usable when v2_mean and "
                "v2_stddev are finite and v2_available_at <= captured_at_utc (r0_ols_floor_devfit.usable_v2_mean)"},
    # own-station observations for the L6 n_own nowcast (pre-13)
    "captured_metar_l6_own": {
        "input": "own_obs", "class": CAPTURED,
        "note": "the snapshot's captured METAR rows, usable from observation + 10 min, T-group dewpoint, "
                "previous-day max from D-1's last captured snapshot (captured_nowcast, L3 ecd8c9ba6)"},
    # retired dev sources (arm A and the IEM nowcast); kept so an old rule still classifies as external
    "pit_previous_runs_gfs_seamless_day1": {
        "input": "forecast_high", "class": EXTERNAL,
        "note": "Open-Meteo Previous Runs temperature_2m_previous_day1 (gfs_seamless) from a PIT corpus; "
                "the capture does not hold it (retired with arm A)"},
    "iem_own_station_free_fetch": {
        "input": "own_obs", "class": EXTERNAL,
        "note": "IEM ASOS own-station observations, a later free fetch; not read from the capture"},
}
FIXED_INPUTS = {
    "snapshots_and_bands": "captured replay inputs layout (inputs_snapshots / inputs_bands)",
    "high_so_far_and_current_temp": "captured METAR rows in the replay snapshots (running_max_since_midnight, "
                                    "metar_only; observations_at_cutoff)",
    "mg1_centre_spread_and_floor": "captured NBM v2 guidance and guidance_physical_floor in the snapshots",
}
SOURCE_FIELDS = {"forecast_high": "forecast_high_source", "own_obs": "own_obs_source"}
PENDING = "PENDING"

_PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                        "weather.trading", "weather.capture", "weather.sources", "weather.execution",
                        "maker_core", "app")


class Mg2Refused(RuntimeError):
    """The MG-2 run cannot proceed under the rule, the reservation or the hashes."""


def _refuse_production_import():
    """Fail closed when imported from a production package, or on the capture host."""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.mg2_composite is research-only; imported from {name}")
        frame = frame.f_back
    from weather.calibration import r0_ols_floor_challenger  # noqa: F401  (its import refuses on the capture host)


_refuse_production_import()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


# ----------------------------------------------------------------------------- the rule

def read_rule(path):
    """The rule's raw sha256 and its fenced ``mg2_rule_v1`` key: value block."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
    match = re.search(r"```" + RULE_BLOCK + r"\n(.*?)```", text, re.S)
    if not match:
        raise Mg2Refused(f"rule has no fenced {RULE_BLOCK} block")
    fields = {}
    for line in match.group(1).splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    for key in ("switch_hour", "d0", "n_forward_dates", "owner_decision_id", "l6_coefficients_sha256",
                "p3d_n_state_sha256", "function_sha256", *SOURCE_FIELDS.values()):
        if key not in fields:
            raise Mg2Refused(f"rule block lacks {key}")
    if int(fields["switch_hour"]) != SWITCH_HOUR:
        raise Mg2Refused(f"rule switch_hour {fields['switch_hour']} != code {SWITCH_HOUR}")
    return hashlib.sha256(raw).hexdigest(), fields


def owner_decision(fields):
    """The dated owner decision id, or None. Malformed ids refuse rather than pass."""
    value = fields.get("owner_decision_id", "NONE")
    if value in ("", "NONE"):
        return None
    match = OWNER_DECISION_ID.match(value)
    if not match:
        raise Mg2Refused(f"owner_decision_id {value!r} is not a dated id OD-YYYY-MM-DD-<slug>")
    date.fromisoformat(match.group(1))
    return value


def rule_d0(fields):
    value = fields.get("d0", "UNSET")
    return None if value == "UNSET" else date.fromisoformat(value)


def reserved_end():
    """Last MG-1 reserved date, or None when the window is open-ended (everything from the floor)."""
    from weather import mg1_reserved_window as w

    start, end = w.window()
    return start, end


def score_guard(fields, target_dates, today=None, mg1_look_receipt=None):
    """Refuse a forward look that the reservation, the rule or the one-look clause forbids.

    - every target date must be on or after the rule's D0 (D0 must be set);
    - a target date inside the MG-1 window (``weather.mg1_reserved_window``) needs a dated owner decision
      id in the rule AND a receipt of MG-1's completed look (the look is strictly after MG-1's);
    - the look needs all ``n_forward_dates`` dates.
    """
    d0 = rule_d0(fields)
    if d0 is None:
        raise Mg2Refused("rule d0 is UNSET: no forward look exists")
    days = sorted({date.fromisoformat(str(d)[:10]) for d in target_dates})
    if not days:
        raise Mg2Refused("no target dates")
    if days[0] < d0:
        raise Mg2Refused(f"target date {days[0]} is before D0 {d0}")
    start, end = reserved_end()
    inside = [d for d in days if d >= start and (end is None or d <= end)]
    decision = owner_decision(fields)
    if inside:
        if decision is None:
            raise Mg2Refused(f"{len(inside)} target dates inside the MG-1 reserved window "
                             f"({start}..{end or 'open'}); the rule carries no dated owner decision id")
        if not mg1_look_receipt or not Path(mg1_look_receipt).is_file():
            raise Mg2Refused("owner decision present, but the MG-2 look is strictly after MG-1's look and no "
                             "MG-1 look receipt was given")
        today = today or datetime.now(timezone.utc).date()
        if end is None or today <= end:
            raise Mg2Refused("the MG-1 window has not closed")
    need = int(fields["n_forward_dates"])
    if len(days) != need:
        raise Mg2Refused(f"the look needs exactly {need} forward dates, got {len(days)}")
    return {"d0": d0.isoformat(), "dates": len(days), "inside_mg1_window": len(inside),
            "owner_decision_id": decision}


RELEASE_FILES = (
    "src/weather/calibration/mg2_composite.py",
    "src/weather/calibration/mg2_p3d_n.py",
    "src/weather/calibration/r0_ols_floor_devfit.py",
    "src/weather/reporting/scorecards/free_source_candidates/l6_stack.py",
    "src/weather/reporting/scorecards/free_source_candidates/mg1.py",
    "src/weather/calibration/upstream_obs_screen.py",
    "src/weather/calibration/r0_ols_floor_challenger.py",
    "src/weather/model/observed_running_max.py",
    "src/weather/model/mg_serve_core.py",
    "src/weather/reporting/scorecards/dev_scorecard.py",
    "src/weather/reporting/scorecards/dev_scorecard_data.py",
    "src/weather/reporting/scorecards/loss_atlas.py",
    "src/weather/calibration/mg2_inputs.py",
    "src/weather/calibration/mg2_input_allowlist.py",
    "src/weather/reporting/research/guidance_extract_parser.py",
)


def repo_root():
    return Path(__file__).resolve().parents[3]


def release_hashes(root=None):
    root = Path(root or repo_root())
    return {rel: sha256_file(root / rel) for rel in RELEASE_FILES}


def verify_function(fields):
    """The rule's ``function_sha256`` must be the running ``observed_running_max`` source."""
    from weather.model import observed_running_max

    sha = sha256_file(observed_running_max.__file__)
    if fields.get("function_sha256") != sha:
        raise Mg2Refused(f"running_max_since_midnight source sha {sha} != rule's {fields.get('function_sha256')}")
    return sha


def verify_release(path, rule_sha, fields, root=None):
    """``release-binding.json``: every executed file, the function, the coefficients and the rule."""
    binding = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = []
    if binding.get("rule_sha256") != rule_sha:
        problems.append("rule_sha256")
    for key in ("l6_coefficients_sha256", "p3d_n_state_sha256", *SOURCE_FIELDS.values()):
        if binding.get(key) != fields[key]:
            problems.append(key)
    if binding.get("function_sha256") != fields.get("function_sha256"):
        problems.append("function_sha256")
    running = release_hashes(root)
    for rel, sha in running.items():
        if binding.get("files", {}).get(rel) != sha:
            problems.append(rel)
    if problems:
        raise Mg2Refused(f"release binding mismatch: {problems}")
    return binding


RELEASE_BINDING_SCHEMA = "mg2_release_binding/1"


def served_state_loaders():
    """Served frozen states bound by file sha256 in the release binding: ``<name>_state_sha256`` -> a loader
    ``(path, sha256)`` that refuses unless the file bytes hash to ``sha256`` (and the state's registered schema).

    One entry per served state; a further state (for example a season-matched 13-16 state) is one more entry here,
    with the same field shape, and one more ``SERVED_STATE_FIELDS`` entry in ``b_scorer``.
    """
    return {"l6_state_sha256": load_l6_state}


def bind_release(*, rule, coefficients, p3d_n_state, served_states, out, root=None):
    """Write ``release-binding.json`` from verified loads only; nothing in it is typed by hand.

    The rule's coefficient part and P3d_N state are loaded at the rule's shas (``load_part``,
    ``mg2_p3d_n.load_state`` forward) and the function at the rule's sha (``verify_function``). ``served_states``
    maps every ``served_state_loaders`` field to ``(path, sha256)``; each is loaded through its loader (the L6
    state through ``mg_serve_core.load_l6_own_state``), and the recorded sha is that of the bytes the load
    verified. The file hashes are the running ``RELEASE_FILES``; ``built_at_commit`` is ``HEAD`` when written.
    """
    import subprocess

    from weather.calibration import mg2_p3d_n

    loaders = served_state_loaders()
    if set(served_states) != set(loaders):
        raise Mg2Refused(f"bind-release needs exactly the served states {sorted(loaders)}, got "
                         f"{sorted(served_states)}")
    rule_sha, fields = read_rule(rule)
    for key in ("l6_coefficients_sha256", "p3d_n_state_sha256", "function_sha256", *SOURCE_FIELDS.values()):
        if fields.get(key) in (None, "", PENDING):
            raise Mg2Refused(f"the rule's {key} is not set; nothing to bind")
    load_part(coefficients, "l6", fields["l6_coefficients_sha256"])
    try:
        mg2_p3d_n.load_state(p3d_n_state, fields["p3d_n_state_sha256"], forward=True)
    except mg2_p3d_n.P3dNRefused as exc:
        raise Mg2Refused(str(exc)) from exc
    function_sha = verify_function(fields)
    verified = {}
    for field in sorted(loaders):
        path, sha = served_states[field]
        loaders[field](path, sha)
        verified[field] = sha256_file(path)
        if verified[field] != sha:  # the file changed between the verified load and this read
            raise Mg2Refused(f"{field}: {path} changed while binding")
    root = Path(root or repo_root())
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    binding = {"schema": RELEASE_BINDING_SCHEMA, "rule_sha256": rule_sha, "function_sha256": function_sha,
               "l6_coefficients_sha256": fields["l6_coefficients_sha256"],
               "p3d_n_state_sha256": fields["p3d_n_state_sha256"],
               **{key: fields[key] for key in SOURCE_FIELDS.values()},
               **verified, "files": release_hashes(root),
               "built_at_commit": head.stdout.strip() if head.returncode == 0 else None}
    out = Path(out)
    if out.exists():
        raise Mg2Refused(f"refusing to overwrite {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(binding, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(out), "sha256": sha256_file(out), "rule_sha256": rule_sha, **verified}


def input_parity(fields):
    """Each rule-named input's source and class; ``ok`` only if every input is read from the capture."""
    report = {"fixed": dict(FIXED_INPUTS), "named": {}, "not_captured": []}
    for name, key in SOURCE_FIELDS.items():
        source = fields.get(key, PENDING)
        entry = SOURCES.get(source)
        if entry is not None and entry["input"] != name:
            raise Mg2Refused(f"{key}: source {source} is for {entry['input']}, not {name}")
        klass = entry["class"] if entry else ("pending" if source == PENDING else "unknown")
        report["named"][name] = {"source": source, "class": klass}
        if klass != CAPTURED:
            report["not_captured"].append(name)
    report["ok"] = not report["not_captured"]
    return report


def require_forward_parity(fields):
    """Forward emission and the look: every input from the capture at replay time, no external fetch."""
    report = input_parity(fields)
    if not report["ok"]:
        raise Mg2Refused(f"serve parity: inputs not read from the capture: {report['not_captured']} "
                         f"({ {k: v['source'] for k, v in report['named'].items()} })")
    if fields["p3d_n_state_sha256"] == PENDING:
        raise Mg2Refused("serve parity: the P3d_N state is PENDING (L2's Clarification 3 refit, frozen before D0)")
    return report


# ----------------------------------------------------------------------------- composition

def floor_B(snaps):
    """B = floor(F + 0.5) with F the rule-4 floor (the scorecard's ``FLOOR_FIELDS`` max)."""
    import numpy as np
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    F = snaps[list(data.FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce").max(axis=1, skipna=True)
    F = F.to_numpy(float)
    return np.where(np.isfinite(F), np.floor(F + 0.5), -np.inf)


def distribution_band_frame(dists, bands):
    """{row_key: {bucket: p}} onto bands (``dev_scorecard_data.distribution_predictions`` mapping)."""
    import numpy as np
    import pandas as pd

    b = bands[bands.row_key.isin(set(dists))]
    probs = []
    for rk, kind, low, high in zip(b.row_key, b.kind, b.low, b.high):
        d = dists[rk]
        if kind == "lte":
            probs.append(sum(p for k, p in d.items() if k <= high))
        elif kind == "gte":
            probs.append(sum(p for k, p in d.items() if k >= low))
        else:
            probs.append(sum(p for k, p in d.items() if low <= k <= high))
    return pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int),
                         "p": np.asarray(probs, float)})


def compose(snaps, bands, pre, post, mg1):
    """Per snapshot: ``pre`` before SWITCH_HOUR, ``post`` from it; MG-1 where the half has nothing usable.

    A ``post`` row is usable only when it puts mass on a band the rule-4 floor allows (so the scorecard
    would not drop it to served). Returns (frame, source per row_key).
    """
    import numpy as np
    import pandas as pd

    s = snaps.reset_index(drop=True)
    hour = dict(zip(s.row_key, s.local_hour.astype(int)))
    B = dict(zip(s.row_key, floor_B(s)))
    kind = dict(zip(zip(bands.row_key, bands.band_index.astype(int)), bands.kind))
    high = dict(zip(zip(bands.row_key, bands.band_index.astype(int)), bands.high.astype(float)))

    def usable(frame):
        if frame.empty:
            return set()
        ok = [(kind[(r, i)] == "gte") or (high[(r, i)] >= B[r]) for r, i in zip(frame.row_key, frame.band_index)]
        mass = frame.p.to_numpy(float) * np.asarray(ok, bool)
        tot = pd.Series(mass).groupby(frame.row_key.to_numpy()).sum()
        return set(tot.index[tot.to_numpy() > 0])

    pre_keys = {k for k in set(pre.row_key) if hour.get(k, 99) < SWITCH_HOUR}
    post_keys = {k for k in usable(post) if hour.get(k, -1) >= SWITCH_HOUR}
    mg1_keys = set(mg1.row_key) - pre_keys - post_keys
    parts = [pre[pre.row_key.isin(pre_keys)], post[post.row_key.isin(post_keys)], mg1[mg1.row_key.isin(mg1_keys)]]
    frame = pd.concat(parts, ignore_index=True)
    source = {}
    for k in s.row_key:
        source[k] = ("pre" if k in pre_keys else POST if k in post_keys else "mg1" if k in mg1_keys
                     else "none")
    return frame.sort_values(["row_key", "band_index"]).reset_index(drop=True), source


# ----------------------------------------------------------------------------- dev module contract

def _post_dists(path):
    """{row_key: {bucket: p}} from a P3d_N jsonl (dev only: refuses a row after 2026-09-29)."""
    out = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if date.fromisoformat(row["target_date"]) > DEV_LAST:
                    raise Mg2Refused("P3d_N distributions hold a row after 2026-09-29")
                out[f"{row['market']}|{row['snapshot_id']}"] = {int(float(k)): float(v)
                                                                 for k, v in row["distribution"].items()}
    return out


def fit(train):
    """Dev-scorecard module contract: the L6 stack refits per fold; P3d_N is a fixed historical fit."""
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    path = os.environ["MG2_POST_DISTRIBUTIONS"]
    state = {"l6": l6_stack.fit(train, "n_own", NAME), "post_path": path}
    state["provenance"] = {"rule": NAME, "switch_hour": SWITCH_HOUR, "l6": state["l6"]["provenance"],
                           "post_sha256": sha256_file(path)}
    return state


def predict(state, snaps, bands):
    from weather.reporting.scorecards.free_source_candidates import l6_stack, mg1

    pre = l6_stack.predict(state["l6"], snaps, bands)
    base = mg1.predict(snaps, bands, None)
    dists = _post_dists(state["post_path"])
    keys = set(snaps.row_key)
    post = distribution_band_frame({k: v for k, v in dists.items() if k in keys}, bands)
    frame, _ = compose(snaps, bands, pre, post, base)
    return frame


# ----------------------------------------------------------------------------- dev sizing

DEV_GROUPS = (("00-05", 0, 5), ("06-09", 6, 9), ("07-12", 7, 12), ("10-12", 10, 12), ("00-12", 0, 12),
              ("13-16", 13, 16), ("00-16", 0, 16), ("17-23", 17, 23), ("all", 0, 23)) + tuple(
    (f"h{h:02d}", h, h) for h in range(7, 17))
Z_ALPHA, Z_POWER = 1.959963984540054, 0.8416212335729143


def forward_sizing(cell_dates, cell_delta, n_values, draws=2000, seed=20261025, margin=None):
    """Date-cluster bootstrap SE of the equal-cell mean delta at N forward dates, from dev cells.

    Draws N dates with replacement from the dev dates (each date carries its market cells), and returns,
    per N: se, mde80 (one-sided alpha 0.025), the power at the dev point estimate for superiority
    (upper bound < 0) and, with ``margin``, for non-inferiority (upper bound < margin).
    """
    import numpy as np
    from scipy.stats import norm

    cell_dates = np.asarray(cell_dates)
    delta = np.asarray(cell_delta, float)
    dates, inv = np.unique(cell_dates, return_inverse=True)
    sums = np.bincount(inv, weights=delta)
    counts = np.bincount(inv).astype(float)
    point = float(delta.mean())
    rng = np.random.default_rng(seed)
    out = {"dev_point": point, "dev_dates": int(len(dates)), "dev_cells": int(len(delta)), "per_n": {}}
    for n in n_values:
        pick = rng.integers(0, len(dates), size=(draws, int(n)))
        est = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
        se = float(est.std(ddof=1))
        row = {"se": se, "mde80": (Z_ALPHA + Z_POWER) * se,
               "power_superiority_at_dev_point": float(norm.cdf(-point / se - Z_ALPHA)) if se > 0 else None}
        if margin is not None:
            row["power_noninferiority_at_dev_point"] = float(norm.cdf((margin - point) / se - Z_ALPHA))
            row["power_noninferiority_at_zero"] = float(norm.cdf(margin / se - Z_ALPHA))
        out["per_n"][str(n)] = row
    return out


def dev_run(layout_root, post, nowcasts, out, start="2026-08-01", end="2026-09-29", n_values=(30, 45, 60),
            margin=None):
    """Composite vs MG-1 on the dev window with the scorecard's own machinery (selection evidence only)."""
    import numpy as np
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    os.environ["MG2_POST_DISTRIBUTIONS"] = str(post)
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    l6_stack._CACHE.clear()
    s, e = data.check_range(start, end)
    layout = data.load_layout(layout_root, data.DEV_FIRST, e)
    folds = data.make_folds(layout.dates, s, e)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(layout, scored)
    here = Path(__file__).resolve()
    comp_frame, comp_meta = data.module_predictions(data.CandidateSpec("module", str(here)), layout, folds)
    p_comp, r_comp = table.candidate_vector(comp_frame)
    p_mg1, r_mg1 = table.candidate_vector(loss_atlas.mg1_frame(table))
    l6_path = Path(l6_stack.__file__).with_name("l6_own_candidate.py")
    l6_frame, _ = data.module_predictions(data.CandidateSpec("module", str(l6_path)), layout, folds)
    p_l6, _ = table.candidate_vector(l6_frame)
    a_frame, _ = data.distribution_predictions(data.CandidateSpec("distributions", str(post), "2025-12-31", False),
                                               layout, folds)
    p_a, _ = table.candidate_vector(a_frame)
    from weather.calibration import r0_ols_floor_challenger as l3

    band_hour = table.local_hour[table.band_snap]
    a_used = l3.covered_mask(table, a_frame)[table.band_snap] & (band_hour >= SWITCH_HOUR)
    controls = {
        "pre_equals_l6_max_abs": float(np.abs(p_comp - p_l6)[band_hour < SWITCH_HOUR].max()),
        "post_equals_p3d_n_where_used_max_abs": float(np.abs(p_comp - p_a)[a_used].max()) if a_used.any()
        else 0.0,
        "post_equals_mg1_where_p3d_n_unused_max_abs": float(np.abs(p_comp - p_mg1)[~a_used & (band_hour >= SWITCH_HOUR)].max()),
    }
    bc, bk, bm = table.brier(p_comp), table.brier(p_mg1), table.brier(table.p_market)
    groups = {}
    cells = {}
    gate_groups = {}
    in_gate = ~np.isin(table.markets, GATE_EXCLUDED_MARKETS)
    for name, lo, hi in DEV_GROUPS:
        mask = (table.local_hour >= lo) & (table.local_hour <= hi)
        if name in ("00-16", "13-16"):  # rule §8 C8: the G1/G2 population without the excluded markets
            idx, c = table.cells(bc, mask & in_gate)
            _, k = table.cells(bk, mask & in_gate)
            gate_groups[name] = {"n_cells": int(len(idx)), "excluded_markets": list(GATE_EXCLUDED_MARKETS),
                                 "brier_minus_mg1_date_clustered": sc.ratio_interval(table.w_date[:, idx], c - k,
                                                                                     np.ones(len(idx)))}
        idx, c = table.cells(bc, mask)
        _, k = table.cells(bk, mask)
        _, m = table.cells(bm, mask)
        wd = table.w_date[:, idx]
        ones = np.ones(len(idx))
        groups[name] = {"n_cells": int(len(idx)),
                        "brier_minus_mg1_date_clustered": sc.ratio_interval(wd, c - k, ones),
                        "dR_vs_mg1_date_clustered": sc.ratio_interval(wd, c - k, m),
                        "brier_minus_mg1_crossed": sc.ratio_interval(table.w[:, idx], c - k, ones)}
        cells[name] = ([table.keys[i][0] for i in idx], (c - k).tolist())
    sizing = {g: forward_sizing(cells[g][0], cells[g][1], n_values, margin=margin if g == "00-16" else None)
              for g in ("00-16", "13-16", "00-12", "07-12")}
    payload = {"schema": SCHEMA, "evidence_class": "development (selection evidence only)",
               "population": {"n_dates": len(scored), "first": scored[0], "last": scored[-1],
                              "n_snapshots": int(len(table.snaps))},
               "coverage": {"composite": r_comp, "mg1": r_mg1}, "candidate_meta": comp_meta,
               "controls": controls, "groups": groups, "gate_groups": gate_groups, "sizing": sizing,
               "code_sha256": sha256_file(here), "post_sha256": sha256_file(post),
               "nowcasts_sha256": sha256_file(nowcasts), "layout_manifest_sha256": layout.manifest_sha256}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dev_composite.json").write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    pd.DataFrame({"date": cells["00-16"][0], "delta": cells["00-16"][1]}).to_csv(out / "cells_00_16.csv", index=False)
    pd.DataFrame({"date": cells["13-16"][0], "delta": cells["13-16"][1]}).to_csv(out / "cells_13_16.csv", index=False)
    return payload


# ----------------------------------------------------------------------------- freeze

def freeze(layout_root, nowcasts, out):
    """The frozen L6 coefficients: the stack per hour on the captured-METAR nowcasts, with provenance.

    P3d_N's state is frozen by L2 and bound by its own file sha (``p3d_n_state_sha256``).
    """
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    os.environ["L6_NOWCASTS"] = str(nowcasts)
    l6_stack._CACHE.clear()
    layout = data.load_layout(layout_root, data.DEV_FIRST, DEV_LAST)
    train = {"snapshots": layout.snaps, "bands": layout.bands,
             "labels": layout.labels[["row_key", "date", "market", "winner"]]}
    data.screen_inputs(train["snapshots"], train["bands"])
    l6 = l6_stack.fit(train, "n_own", NAME)
    payload = {"schema": SCHEMA, "switch_hour": SWITCH_HOUR,
               "l6_stack": {"column": "n_own", "trained_through": DEV_LAST.isoformat(),
                            "coef": {str(h): [float(a), float(b), int(n)] for h, (a, b, n) in l6["coef"].items()},
                            "nowcasts_sha256": l6["provenance"]["nowcasts_sha256"],
                            "own_obs_source": "captured_metar_l6_own",
                            "layout_manifest_sha256": layout.manifest_sha256}}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    blob = canonical(payload)
    (out / "mg2_coefficients.json").write_bytes(blob)
    return {"file_sha256": hashlib.sha256(blob).hexdigest(), "path": str(out / "mg2_coefficients.json"),
            **{f"{part}_coefficients_sha256": part_sha(payload[key]) for part, key in COEF_PARTS.items()}}


COEF_PARTS = {"l6": "l6_stack"}


def part_sha(part):
    """sha256 of one coefficient part's canonical JSON (each part is bound by its own sha)."""
    return hashlib.sha256(canonical(part)).hexdigest()


def load_part(path, part, expected_sha):
    """One part of a coefficients file, refused unless its canonical sha256 is the rule's."""
    if expected_sha == PENDING:
        raise Mg2Refused(f"{part} coefficients are PENDING in the rule")
    payload = json.loads(Path(path).read_bytes())
    if COEF_PARTS[part] not in payload:
        raise Mg2Refused(f"{path} has no {COEF_PARTS[part]} part")
    sha = part_sha(payload[COEF_PARTS[part]])
    if sha != expected_sha:
        raise Mg2Refused(f"{part} coefficients sha {sha} != rule's {expected_sha}")
    return payload[COEF_PARTS[part]]


# ----------------------------------------------------------------------------- L6 own-obs nowcast

def _market_series_unasserted(obs, icao, tz):
    """``upstream_obs_screen.market_series`` without its dev-date assertion.

    Forward rows feed only ``prev_dmax`` (the complete previous local date, an observation, never a
    settlement); the target date's own max is never a feature.
    """
    import pandas as pd

    from weather.calibration import upstream_obs_screen as up

    g = obs[(obs.role == "market") & (obs.station == icao[1:])].sort_values("valid_utc").copy()
    g["local_date"] = g.valid_utc.dt.tz_convert(tz).dt.strftime("%Y-%m-%d")
    g["routine"] = up.routine_mask(g)
    g["avail"] = g.valid_utc + pd.Timedelta(minutes=up.MARKET_LAT_MIN)
    g["rmax"] = g.groupby("local_date").temp.cummax()
    rt = g[g.routine]
    day = rt.groupby("local_date").agg(n=("temp", "size"), mx=("temp", "max"))
    mx = day.mx.where(day.n >= up.MIN_ROUTINE)
    return g, pd.Series(up.half_up(mx), index=day.index).dropna()


def nowcast(*, train_root, obs_root, layout_root, first, last, out):
    """L6 ``n_own`` for snapshots in [first, last], exactly ``upstream_obs_screen.serve`` otherwise.

    The own-obs HGB is fitted on the frozen Aug-Sep 2021-25 history of ``train_root`` (the dev extract);
    forward features come from ``obs_root`` (a later free IEM extract), PIT-gated as in L6 (market rows
    usable from valid + 10 min). Run on the dev window with ``obs_root == train_root`` it must reproduce
    the dev ``nowcasts.parquet`` (the replay control).
    """
    import numpy as np
    import pandas as pd

    from weather.calibration import upstream_obs_screen as up

    first, last = date.fromisoformat(str(first)), date.fromisoformat(str(last))
    hist, prov = up.build_history(train_root)
    train = hist[hist.month.isin(up.TRAIN_MONTHS_PRIMARY)].reset_index(drop=True)
    obs, sel, oprov = up.load(obs_root)
    snaps, _ = read_inputs(layout_root)
    snaps = _window(snaps, first, last)
    snaps = snaps[snaps.local_hour.isin(up.HOURS)].reset_index(drop=True)
    frames = []
    for code, icao in enumerate(up.stations(sel)):
        m = sel[icao]
        s = snaps[snaps.station == icao]
        if s.empty:
            continue
        g, dmax = _market_series_unasserted(obs, icao, m["timezone"])
        q = pd.DataFrame({"t_utc": pd.to_datetime(s.captured_at_utc, utc=True).to_numpy(),
                          "local_date": s.date.astype(str).to_numpy()}, index=s.index)
        q["t_utc"] = pd.to_datetime(q.t_utc, utc=True)
        f = up.features(q, obs, m, icao, m["timezone"], code, g, dmax)
        f["row_key"] = s.row_key
        frames.append(f)
    feat = pd.concat(frames)
    feat = feat[np.isfinite(feat.r) & np.isfinite(feat.t)]
    own = up.make_model(up.OWN).fit(train[list(up.OWN)].to_numpy(float), train.y.to_numpy(float))
    up_model = up.make_model(up.OWN + up.UP).fit(train[list(up.OWN + up.UP)].to_numpy(float), train.y.to_numpy(float))
    res = pd.DataFrame({"row_key": feat.row_key.to_numpy(),
                        "n_own": feat.r.to_numpy(float) + own.predict(feat[list(up.OWN)].to_numpy(float)),
                        "n_up": feat.r.to_numpy(float) + up_model.predict(feat[list(up.OWN + up.UP)].to_numpy(float)),
                        "n_ring": feat.n_ring.to_numpy(float)})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "nowcasts.parquet"
    res.to_parquet(path, index=False)
    manifest = {"train": prov, "obs": oprov, "nowcasts_sha256": sha256_file(path), "rows": int(len(res)),
                "train_rows": int(len(train)), "first": first.isoformat(), "last": last.isoformat()}
    (out / "nowcasts_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def _prev_day_last_rows(prev_root, market, slug_day, station, l3):
    """D-1's last captured METAR rows and their capture time, from a verified bundle's
    ``prev_day/<slug>/metar_rows.jsonl`` (None when absent)."""
    from weather.calibration import mg2_input_allowlist as allow

    path = Path(prev_root) / allow.slug_for(market, slug_day) / "metar_rows.jsonl"
    if not path.is_file():
        return None
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = json.loads(line)
    if last is None:
        return None
    cap = datetime.fromisoformat(last["captured_at_utc"])
    rows = [r for r in last.get("rows") or [] if str(r.get("station_id") or station) == station]
    return [p for p in (l3.parse_captured_metar(r.get("raw"), cap) for r in rows) if p is not None], cap


def load_l6_state(path, sha256):
    """The frozen L6 own-model state of the pre-13 arm, loaded only at its bound sha256 (clarification §3).

    ``path`` and ``sha256`` are binding-time inputs (the season-matched state ``l6_own_state_octdec.pkl``);
    neither has a default. The sha must be 64 lowercase hex, so an empty, ``PENDING`` or FILL value refuses
    before the file is opened; ``mg_serve_core.load_l6_own_state`` then refuses unless the file bytes hash to
    it, and checks the schema and the OWN columns.
    """
    from weather.model import mg_serve_core as core

    if not path:
        raise Mg2Refused("the pre-13 arm needs the frozen L6 state path (binding input)")
    if not isinstance(sha256, str) or not SHA256_HEX.fullmatch(sha256):
        raise Mg2Refused(f"the frozen L6 state sha256 must be 64 lowercase hex, got {sha256!r}")
    try:
        return core.load_l6_own_state(path, sha256)
    except (core.ServeCoreError, OSError) as exc:
        raise Mg2Refused(str(exc)) from exc


def l6_nowcast_frame(state, feat):
    """The pre-13 nowcast rows: ``n_own`` = ``mg_serve_core.l6_own_nowcast(state, feat)``, nothing refitted."""
    import numpy as np
    import pandas as pd

    from weather.model import mg_serve_core as core

    return pd.DataFrame({"row_key": feat.row_key.to_numpy(), "n_own": core.l6_own_nowcast(state, feat),
                         "n_up": np.nan, "n_ring": np.nan})


def captured_nowcast(*, layout_root, replay_root, research_root, first, last, out, l6_state, l6_state_sha256,
                     prev_root=None):
    """L6 ``n_own`` from the captured METAR rows: lane L3's captured features, served by the frozen L6 state.

    Same features (L3's ``parse_captured_metar`` with the T-group dewpoint, ``l6_captured_features``: rows usable
    from observation + 10 min) and the previous-day max from D-1's last captured snapshot (``routine_dmax``).
    The model is the frozen state at ``l6_state`` (``load_l6_state``: refused unless its file sha256 equals
    ``l6_state_sha256``), served through ``mg_serve_core.l6_own_nowcast``; there is no per-run refit. Under the
    MG-2 season-L6 clarification (2026-10-26) that state is the season-matched Oct-Dec HGB on every B date.
    ``research_root`` supplies only L6's station selection (the station encoding) and hours. Without
    ``prev_root``, D-1's last snapshot is the last line of D-1's replay folder (the dev semantics); forward it is
    the verified bundle's ``prev_day`` record.
    """
    from collections import defaultdict
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    import numpy as np
    import pandas as pd

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration import upstream_obs_screen as l6

    from weather.model import mg_serve_core as core

    first, last = date.fromisoformat(str(first)), date.fromisoformat(str(last))
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise Mg2Refused(f"output directory {out} must be new or empty")
    state = load_l6_state(l6_state, l6_state_sha256)
    if tuple(l6.OWN) != core.L6_OWN_COLUMNS:
        raise Mg2Refused("upstream_obs_screen.OWN differs from mg_serve_core.L6_OWN_COLUMNS")
    _, sel, _ = l6.load(research_root)
    codes = {icao: code for code, icao in enumerate(l6.stations(sel))}
    snaps = pd.read_parquet(Path(layout_root) / "inputs_snapshots.parquet",
                            columns=["row_key", "station", "market", "date", "local_hour", "snapshot_id"])
    d = snaps.date.astype(str)
    snaps = snaps[(d >= first.isoformat()) & (d <= last.isoformat())]
    station_of = snaps.groupby("market").station.first().to_dict()
    snaps = snaps[snaps.local_hour.isin(l6.HOURS)]
    wanted = {(r.market, r.snapshot_id): (r.row_key, str(r.date)[:10]) for r in snaps.itertuples(index=False)}
    captured, snap_rows, last_rows = defaultdict(dict), defaultdict(list), defaultdict(dict)
    stats = defaultdict(int)
    for market, target, folder in l3._event_folders(replay_root):
        if market not in station_of or not (first - timedelta(days=1) <= target <= last):
            continue
        path = folder / "replay_inputs.jsonl"
        if not path.is_file():
            continue
        station = station_of[market]
        tail = None
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                head = line[:line.find('"sources":')] if '"sources":' in line else line
                sid, _ = l3._json_value_after(head, "snapshot_id")
                cap_s, _ = l3._json_value_after(head, "captured_at_utc")
                if cap_s is None:
                    continue
                cap = datetime.fromisoformat(cap_s)
                tail = (line, cap)
                hit = wanted.get((market, sid))
                if hit is None:
                    continue
                key, local_date = hit
                captured[market][key] = [p for p in (l3.parse_captured_metar(r.get("raw"), cap)
                                                     for r in l3._captured_rows(line, station)) if p is not None]
                snap_rows[market].append((key, cap, local_date))
                stats["snapshots_scanned"] += 1
        if tail is not None and prev_root is None:
            last_rows[market][target.isoformat()] = ([
                p for p in (l3.parse_captured_metar(r.get("raw"), tail[1]) for r in l3._captured_rows(tail[0], station))
                if p is not None], tail[1])
    frames = []
    for market in sorted(snap_rows):
        station = station_of[market]
        tz = ZoneInfo(sel[station]["timezone"])
        prev = {}
        first_cap = {}
        for _, cap, day in snap_rows[market]:
            first_cap[day] = min(cap, first_cap.get(day, cap))
        for day in sorted(first_cap):
            before_day = date.fromisoformat(day) - timedelta(days=1)
            before = before_day.isoformat()
            rows, prev_cap = ((last_rows[market].get(before) or ([], None)) if prev_root is None
                              else (_prev_day_last_rows(prev_root, market, before_day, station, l3) or ([], None)))
            if prev_cap is not None and prev_cap > first_cap[day]:
                # D-1's "last" capture is later than a snapshot of D that would use it: never serve it
                stats["prev_dmax_after_snapshot_days"] += 1
                continue
            value = l3.routine_dmax(rows, tz, before)
            if value is None:
                stats["prev_dmax_missing_days"] += 1
            else:
                prev[day] = value
        frames.append(l3.l6_captured_features(snap_rows[market], captured[market], tz, codes[station], prev))
    feat = pd.concat(frames, ignore_index=True)
    ok = np.isfinite(feat.r) & np.isfinite(feat.t)
    stats["no_usable_row"] = int((~ok).sum())
    feat = feat[ok].reset_index(drop=True)
    res = l6_nowcast_frame(state, feat)
    out.mkdir(parents=True, exist_ok=True)
    res.to_parquet(out / "nowcasts.parquet", index=False)
    feat.to_parquet(out / "serve_features.parquet", index=False)
    manifest = dict(rows=int(len(res)), stats=dict(stats), first=first.isoformat(), last=last.isoformat(),
                    l6_state_sha256=l6_state_sha256, l6_state_provenance=state.get("provenance"),
                    serve_core_sha256=sha256_file(core.__file__),
                    prev_day_source=FORWARD_PREV_DAY_SOURCE if prev_root is not None else "D-1 replay folder, last line",
                    nowcasts_sha256=sha256_file(out / "nowcasts.parquet"),
                    serve_features_sha256=sha256_file(out / "serve_features.parquet"),
                    l3_module_sha256=sha256_file(l3.__file__), l6_module_sha256=sha256_file(l6.__file__))
    (out / NOWCASTS_MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def forward_nowcasts(nowcasts, binding):
    """Forward emission reads only ``captured_nowcast``'s forward output, at the bound L6 state.

    The manifest beside ``nowcasts`` must say the previous-day max came from the verified bundle, its
    ``nowcasts_sha256`` must be the file's, and its ``l6_state_sha256`` must be the release binding's. An IEM
    ``nowcast`` file (no prev_day_source, no L6 state) is refused.
    """
    path = Path(nowcasts).parent / NOWCASTS_MANIFEST
    if not path.is_file():
        raise Mg2Refused(f"forward emission needs {NOWCASTS_MANIFEST} beside the nowcasts")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("prev_day_source") != FORWARD_PREV_DAY_SOURCE:
        raise Mg2Refused(f"forward nowcasts must come from captured_nowcast with --prev-root "
                         f"(prev_day_source {manifest.get('prev_day_source')!r})")
    if manifest.get("nowcasts_sha256") != sha256_file(nowcasts):
        raise Mg2Refused("the nowcasts file is not the one its manifest records")
    bound = binding.get("l6_state_sha256")
    if not isinstance(bound, str) or not SHA256_HEX.fullmatch(bound):
        raise Mg2Refused("the release binding records no l6_state_sha256 (MG-2 clarification season-L6, section 7)")
    if manifest.get("l6_state_sha256") != bound:
        raise Mg2Refused(f"the nowcasts were served by L6 state {manifest.get('l6_state_sha256')!r}, not the bound "
                         f"{bound}")
    return {k: manifest.get(k) for k in ("nowcasts_sha256", "l6_state_sha256", "prev_day_source", "first", "last")}


# ----------------------------------------------------------------------------- emit (captured-input replay)

def read_inputs(layout_root):
    """Snapshots and bands only. Label, settlement and price files are never opened."""
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    root = Path(layout_root)
    snaps = pd.read_parquet(root / data.SNAPSHOTS_FILE)
    bands = pd.read_parquet(root / data.BANDS_FILE)
    data.screen_inputs(snaps, bands)
    return snaps, bands


def _window(snaps, first, last):
    d = snaps.date.astype(str)
    return snaps[(d >= first.isoformat()) & (d <= last.isoformat())].reset_index(drop=True)


VECTORS = "mg2_vectors.parquet"  # last_in_hour: the dev control replay only; never the forward gate (rule §8 C7)
ASOF_VECTORS = "mg2_vectors_asof_capture.parquet"  # as-of-capture: the forward gate (C7) and the market arm (C4)
VECTOR_ROLES = {
    VECTORS: "dev control replay only (last_in_hour, the reproduction check); DESCRIPTIVE on forward rows; never "
             "scored by the forward MG-2 vs MG-1 gate (rule §8 C7)",
    ASOF_VECTORS: "PRIMARY for the forward MG-2 vs MG-1 gate (rule §8 C7, capture-time like MG-1) and for every "
                  "comparison against the market (blend R, edge reads, the formal edge test; C4): no METAR row "
                  "received after the row's own capture time",
}
EMIT_AUDIT = "mg2_emit_audit.json"
# Rule §8 C8: Denver settles on KDEN from the 2026-10-23 events (DECISION_LOG 2026-10-23; STATE_OF_PLAY), while
# MG-1 and MG-2 model KBKF, so Denver leaves the G1/G2 gate population (10 markets). Emission is unchanged.
GATE_EXCLUDED_MARKETS = ("denver",)


def gate_layout(layout):
    """The layout restricted to the gate population (rule §8 C8).

    Every frame (snapshots, bands, labels, market) loses the excluded markets' rows.
    """
    import dataclasses

    keep = set(layout.snaps.row_key[~layout.snaps.market.astype(str).isin(GATE_EXCLUDED_MARKETS)])
    return dataclasses.replace(layout, **{name: getattr(layout, name)[getattr(layout, name).row_key.isin(keep)]
                                          .reset_index(drop=True)
                                          for name in ("snaps", "bands", "labels", "market")})


def require_gate_vectors(vectors):
    """Rule §8 C7: the forward gate scores the as-of-capture vectors of a forward emission, nothing else.

    The file must be named ``ASOF_VECTORS`` and its sha256 must be the ``asof_capture`` vectors sha of the
    forward emit audit beside it, so a renamed last_in_hour file is refused too.
    """
    vectors = Path(vectors)
    if vectors.name != ASOF_VECTORS:
        raise Mg2Refused(f"the forward MG-2 vs MG-1 gate scores {ASOF_VECTORS} (as-of-capture) only; the "
                         f"last_in_hour {VECTORS} is for the dev control replay (rule §8 C7)")
    path = vectors.parent / EMIT_AUDIT
    if not path.is_file() or not vectors.is_file():
        raise Mg2Refused(f"the forward gate needs {ASOF_VECTORS} and its {EMIT_AUDIT} (rule §8 C7)")
    audit = json.loads(path.read_text(encoding="utf-8"))
    asof_sha = (audit.get("asof_capture") or {}).get("vectors_sha256")
    if audit.get("mode") != "forward" or asof_sha != sha256_file(vectors):
        raise Mg2Refused("the gate vectors are not the as-of-capture vectors of a forward emission (rule §8 C7)")
    return audit


def post_records(state, snaps, replay_root, first, last, inputs="last_in_hour"):
    """{row_key: P3d_N distribution} on the captured inputs, plus per-market gate stats (``mg2_p3d_n``)."""
    from weather.calibration import mg2_p3d_n

    rows, stats = mg2_p3d_n.emit_rows(state, snaps, replay_root, first, last,
                                      markets=[m for m in state["markets"] if m in set(snaps.market)],
                                      inputs=inputs)
    return {rk: dist for _m, _sid, _d, rk, dist in rows}, stats


def _write_post(path, dists):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for rk in sorted(dists):
            handle.write(json.dumps({"row_key": rk, "distribution": {str(k): v for k, v in dists[rk].items() if v > 0}},
                                    sort_keys=True) + "\n")


def emit(*, layout_root, replay_root, nowcasts, coefficients, rule, out, first, last, p3d_n_state,
         control=False, release_binding=None):
    """Captured-input replay of the composite for [first, last] at the frozen coefficients and P3d_N state.

    Forward (``control`` False): the rule's D0 must be set, ``first`` >= D0, every input must be read
    from the capture (``require_forward_parity``), the release binding must match and the P3d_N state must
    be a forward fit. Control mode replays dev dates only (<= 2026-09-29); it may load the dev fit, which is
    never bound.
    """
    import pandas as pd

    from weather.calibration import mg2_p3d_n
    from weather.reporting.scorecards.free_source_candidates import l6_stack, mg1

    rule_sha, fields = read_rule(rule)
    first, last = date.fromisoformat(str(first)), date.fromisoformat(str(last))
    nowcasts_manifest = None
    if control:
        if last > DEV_LAST:
            raise Mg2Refused("control replay is for dev dates <= 2026-09-29 only")
    else:
        d0 = rule_d0(fields)
        if d0 is None or first < d0:
            raise Mg2Refused("forward emission needs the rule's D0 set and first >= D0")
        require_forward_parity(fields)
        if not release_binding:
            raise Mg2Refused("forward emission needs the release binding")
        binding = verify_release(release_binding, rule_sha, fields)
        nowcasts_manifest = forward_nowcasts(nowcasts, binding)
    parity = input_parity(fields)
    verify_function(fields)
    coef = {"l6_stack": load_part(coefficients, "l6", fields["l6_coefficients_sha256"])}
    try:
        state = mg2_p3d_n.load_state(p3d_n_state, fields["p3d_n_state_sha256"], forward=not control)
    except mg2_p3d_n.P3dNRefused as exc:
        raise Mg2Refused(str(exc)) from exc
    snaps, bands = read_inputs(layout_root)
    snaps = _window(snaps, first, last)
    bands = bands[bands.row_key.isin(set(snaps.row_key))].reset_index(drop=True)
    if sha256_file(nowcasts) != coef["l6_stack"]["nowcasts_sha256"] and control:
        raise Mg2Refused("control replay must use the frozen dev nowcasts")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    l6_stack._CACHE.clear()
    l6_state = {"column": coef["l6_stack"]["column"],
                "coef": {int(h): (a, b, n) for h, (a, b, n) in coef["l6_stack"]["coef"].items()}}
    pre = l6_stack.predict(l6_state, snaps, bands)
    base = mg1.predict(snaps, bands, None)
    try:
        dists, stats = post_records(state, snaps, replay_root, first, last)
    except mg2_p3d_n.P3dNRefused as exc:
        raise Mg2Refused(str(exc)) from exc
    post = distribution_band_frame(dists, bands)
    frame, source = compose(snaps, bands, pre, post, base)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out / VECTORS, index=False)
    pd.DataFrame({"row_key": list(source), "source": list(source.values())}).to_parquet(
        out / "mg2_sources.parquet", index=False)
    _write_post(out / "mg2_post_distributions.jsonl", dists)
    with open(out / "mg2_post_coverage_fallback.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for market in sorted(stats):
            for rk in stats[market]["coverage_fallback"]:
                handle.write(json.dumps({"market": market, "row_key": rk, "reason": "outside_training_coverage",
                                         "slot": "mg1"}, sort_keys=True) + "\n")
    asof = None
    if not control:  # rule §8 C4: never computed on a dev row
        try:
            asof_dists, asof_stats = post_records(state, snaps, replay_root, first, last, inputs="as_of_capture")
        except mg2_p3d_n.P3dNRefused as exc:
            raise Mg2Refused(str(exc)) from exc
        asof_frame, asof_source = compose(snaps, bands, pre, distribution_band_frame(asof_dists, bands), base)
        asof_frame.to_parquet(out / ASOF_VECTORS, index=False)
        _write_post(out / "mg2_post_distributions_asof_capture.jsonl", asof_dists)
        asof = {"vectors_sha256": sha256_file(out / ASOF_VECTORS), "post_stats": asof_stats,
                "sources": pd.Series(list(asof_source.values())).value_counts().to_dict()}
    audit = {"schema": SCHEMA, "mode": "control" if control else "forward", "first": first.isoformat(),
             "last": last.isoformat(), "rule_sha256": rule_sha,
             "l6_coefficients_sha256": fields["l6_coefficients_sha256"],
             "p3d_n_state_sha256": fields["p3d_n_state_sha256"], "p3d_n_fit_kind": state["fit_kind"],
             "p3d_n_conversion": state["conversion"], "p3d_n_late_report": state["late_report"],
             "input_parity": parity, "code_sha256": sha256_file(__file__),
             "p3d_n_code_sha256": sha256_file(mg2_p3d_n.__file__), "nowcasts_sha256": sha256_file(nowcasts),
             "nowcasts_manifest": nowcasts_manifest,
             "l6_state_sha256": (nowcasts_manifest or {}).get("l6_state_sha256"),
             "outcome_files_opened": [],  # read_inputs opens snapshots and bands only
             "post_stats": stats, "vector_roles": VECTOR_ROLES, "asof_capture": asof,
             "gate_vectors": None if control else ASOF_VECTORS,
             "vectors_sha256": sha256_file(out / VECTORS), "snapshots": int(len(snaps))}
    (out / EMIT_AUDIT).write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


# ----------------------------------------------------------------------------- outcome-blind checks

def outcome_blind_checks(snaps, sources, frame, replayed=None, parser_column="v2_parser_version"):
    """Coverage, PIT, replay reproduction and parser version; no label, settlement or price is read.

    ``replayed``: a second emission of the same inputs; every probability must agree to 1e-12.
    """
    import numpy as np
    import pandas as pd

    s = snaps.reset_index(drop=True)
    src = s.row_key.map(sources).fillna("none")
    h = s.local_hour.astype(int)
    in_00_16 = (h >= 0) & (h <= 16)
    coverage = float((src[in_00_16] != "none").mean()) if in_00_16.any() else 0.0
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(s.captured_at_utc, utc=True, errors="coerce")
    uses_v2 = src.isin(["pre", "mg1"])
    pit_v2 = int((uses_v2 & ~(avail <= cap).fillna(False)).sum())
    period = int((uses_v2 & (s.v2_period_kind.astype(str) != "maximum")).sum())
    checks = {"coverage_00_16": coverage, "coverage_pass": coverage >= COVERAGE_MIN,
              "pit_v2_after_capture": pit_v2, "pit_v2_period_not_maximum": period,
              "pit_pass": pit_v2 == 0 and period == 0, "sources": src.value_counts().to_dict(),
              "nbm_reading_snapshots": int((src != "none").sum())}
    if parser_column in s.columns:
        bad = int((uses_v2 & (pd.to_numeric(s[parser_column], errors="coerce") != 2)).sum())
        checks.update(parser_not_v2=bad, parser_pass=bad == 0, parser_status="checked")
    else:
        checks.update(parser_not_v2=None, parser_pass=False, parser_status=f"UNVERIFIED: no {parser_column} column")
    if replayed is not None:
        a = frame.sort_values(["row_key", "band_index"]).reset_index(drop=True)
        b = replayed.sort_values(["row_key", "band_index"]).reset_index(drop=True)
        same_keys = len(a) == len(b) and (a.row_key.to_numpy() == b.row_key.to_numpy()).all() and \
            (a.band_index.to_numpy() == b.band_index.to_numpy()).all()
        diff = float(np.abs(a.p.to_numpy(float) - b.p.to_numpy(float)).max()) if same_keys and len(a) else (
            0.0 if same_keys else math.inf)
        checks.update(replay_max_abs=diff, replay_pass=bool(same_keys and diff <= REPLAY_TOLERANCE))
    return checks


# ----------------------------------------------------------------------------- the look

def score(*, layout_root, vectors, rule, out, release_binding, mg1_look_receipt=None, today=None):
    """The single forward look (composite minus MG-1 Brier, fixed-market date-clustered). Guarded."""
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    audit = require_gate_vectors(vectors)
    rule_sha, fields = read_rule(rule)
    out = Path(out)
    if (out / "mg2_look.json").exists():
        raise Mg2Refused("the MG-2 look already exists: exactly one look")
    root = Path(layout_root)
    snaps = pd.read_parquet(root / data.SNAPSHOTS_FILE, columns=["row_key", "date"])
    guard = score_guard(fields, snaps.date.astype(str).unique(), today=today, mg1_look_receipt=mg1_look_receipt)
    require_forward_parity(fields)
    verify_release(release_binding, rule_sha, fields)
    verify_function(fields)
    checks = emission_checks(vectors, audit)  # before any label or price file is opened
    layout = data.Layout(snaps=pd.read_parquet(root / data.SNAPSHOTS_FILE),
                         bands=pd.read_parquet(root / data.BANDS_FILE),
                         labels=pd.read_parquet(root / data.LABELS_FILE),
                         market=pd.read_parquet(root / data.MARKET_FILE),
                         manifest_sha256=sha256_file(root / data.MANIFEST), file_sha256={},
                         label_source="layout labels")
    layout = gate_layout(layout)
    days = sorted(layout.snaps.date.astype(str).unique())
    table = sc.Table(layout, days)
    gate_vectors = pd.read_parquet(vectors)
    p_c, r_c = table.candidate_vector(gate_vectors)
    p_k, r_k = table.candidate_vector(loss_atlas.mg1_frame(table))
    rows = sc.score_rows(table, p_c, False, p_k, sc.GROUPS + sc.HOURLY_GROUPS)
    payload = {"schema": SCHEMA, "rule_sha256": rule_sha, "guard": guard, "coverage": {"mg2": r_c, "mg1": r_k},
               "gate": gate_verdict(rows, float(fields["noninferiority_margin_00_16"])),
               "gate_excluded_markets": list(GATE_EXCLUDED_MARKETS),
               "vectors_sha256": sha256_file(vectors), "rows": rows,
               "void_conditions": section7_conditions(layout.snaps, gate_vectors, checks),
               "pre_look_reads": pre_look_reads(audit),
               "checks_sha256": sha256_file(Path(vectors).parent / CHECKS),
               "mg1_look_receipt_sha256": sha256_file(mg1_look_receipt) if mg1_look_receipt else None}
    out.mkdir(parents=True, exist_ok=True)
    (out / "mg2_look.json").write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return payload


def emission_checks(vectors, audit):
    """The outcome-blind ``check`` output beside the gate vectors, bound to that emission's audit."""
    path = Path(vectors).parent / CHECKS
    if not path.is_file():
        raise Mg2Refused(f"the look needs {CHECKS} (the outcome-blind check) beside the gate vectors")
    checks = json.loads(path.read_text(encoding="utf-8"))
    shas = checks.get("emit_audit_vectors_sha256") or []
    if not shas or shas[0] != audit.get("vectors_sha256"):
        raise Mg2Refused(f"{CHECKS} does not check this emission (emit_audit_vectors_sha256)")
    return checks


def section7_conditions(snaps, gate_vectors, checks):
    """Rule section 7 at the look; every ``pass`` is true or false.

    Coverage is recomputed from the gate vectors on the gate population's 00-16 snapshots. PIT, parser, replay,
    nowcast replay, P3d_N replay and window leakage are the bound ``check`` output (a missing flag is false).
    Hashes passed (``verify_release`` and ``verify_function`` refuse otherwise).
    """
    h = snaps.local_hour.astype(int)
    pool = snaps.row_key[(h >= 0) & (h <= 16)]
    share = float(pool.isin(set(gate_vectors.row_key)).mean()) if len(pool) else 0.0

    def flag(key):
        value = checks.get(key)
        return {"pass": value is True, "detail": f"{CHECKS} {key}={value!r}"}

    return {
        "coverage": {"pass": share >= COVERAGE_MIN, "detail": f"as-of-capture vectors on {share:.4f} of 00-16 "
                                                              f"snapshots (minimum {COVERAGE_MIN})"},
        "pit": flag("pit_pass"),
        "parser": flag("parser_pass"),
        "replay": flag("replay_pass"),
        "hashes": {"pass": True, "detail": "verify_release and verify_function passed"},
        "nowcast_replay": flag("nowcast_replay_pass"),
        "p3d_n_replay": flag("p3d_n_replay_pass"),
        "window_leakage": flag("window_leakage_pass"),
    }


def _frame_equal(a, b, key, column):
    import numpy as np

    a = a.sort_values(key).reset_index(drop=True)
    b = b.sort_values(key).reset_index(drop=True)
    return bool(len(a) == len(b) and (a[key].to_numpy() == b[key].to_numpy()).all()
                and np.array_equal(a[column].to_numpy(float), b[column].to_numpy(float), equal_nan=True))


def nowcast_replay_check(replay, pin, pin_sha256, l6_state_sha256):
    """Section 7 nowcast replay: ``captured_nowcast`` run on the dev window at the bound L6 state reproduces the
    season-matched dev nowcast pin (clarification season-L6 section 3) on every row, exactly.

    ``replay`` is that run's output folder. Its reader must have produced L3's captured dev serve features
    (``DEV_SERVE_FEATURES_SHA256``) over ``DEV_NOWCAST_WINDOW`` at ``l6_state_sha256``; ``pin`` must hash to
    ``pin_sha256``, and ``pin_sha256`` must be the recorded ``DEV_NOWCAST_PIN_SHA256``.
    """
    import pandas as pd

    replay = Path(replay)
    problems = []
    path = replay / NOWCASTS_MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not manifest:
        problems.append(f"no {NOWCASTS_MANIFEST} in the replay folder")
    if (manifest.get("first"), manifest.get("last")) != DEV_NOWCAST_WINDOW:
        problems.append(f"window {manifest.get('first')}..{manifest.get('last')} is not the dev window")
    features = replay / "serve_features.parquet"
    feat_sha = sha256_file(features) if features.is_file() else None
    if feat_sha != DEV_SERVE_FEATURES_SHA256 or manifest.get("serve_features_sha256") != feat_sha:
        problems.append(f"serve features {feat_sha} are not L3's captured dev features")
    if not isinstance(l6_state_sha256, str) or not SHA256_HEX.fullmatch(l6_state_sha256) \
            or manifest.get("l6_state_sha256") != l6_state_sha256:
        problems.append(f"replay served L6 state {manifest.get('l6_state_sha256')!r}, not {l6_state_sha256!r}")
    nowcasts = replay / "nowcasts.parquet"
    if not nowcasts.is_file() or manifest.get("nowcasts_sha256") != sha256_file(nowcasts):
        problems.append("the replay nowcasts are not the ones its manifest records")
    if not isinstance(pin_sha256, str) or not SHA256_HEX.fullmatch(pin_sha256) or not Path(pin).is_file() \
            or sha256_file(pin) != pin_sha256:
        problems.append("the dev nowcast pin does not hash to its bound sha256")
    if pin_sha256 != DEV_NOWCAST_PIN_SHA256:
        problems.append(f"nowcast pin sha {pin_sha256!r} is not the recorded dev pin {DEV_NOWCAST_PIN_SHA256}")
    if not problems and not _frame_equal(pd.read_parquet(nowcasts, columns=["row_key", "n_own"]),
                                         pd.read_parquet(pin, columns=["row_key", "n_own"]), "row_key", "n_own"):
        problems.append("the replay n_own differs from the pin")
    return {"pass": not problems, "problems": problems, "pin_sha256": pin_sha256, "l6_state_sha256": l6_state_sha256,
            "replay_nowcasts_sha256": manifest.get("nowcasts_sha256"), "serve_features_sha256": feat_sha}


def p3d_n_replay_check(control_json):
    """Section 7 P3d_N replay: ``mg2_p3d_n control`` reproduced L2's dev emission (``721ae2cd…``) on every row to
    |dp| <= 1e-12."""
    path = Path(control_json)
    record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    c = record.get("comparison") or {}
    problems = []
    if record.get("reference_sha256") != P3D_N_DEV_REFERENCE_SHA256:
        problems.append(f"reference {record.get('reference_sha256')!r} is not L2's dev_P3d_N")
    if c.get("pass") is not True or not (isinstance(c.get("max_abs"), (int, float))
                                         and c["max_abs"] <= REPLAY_TOLERANCE):
        problems.append(f"max |dp| {c.get('max_abs')!r} (pass {c.get('pass')!r})")
    if any(c.get(k) != 0 for k in ("missing", "extra", "bucket_set_mismatch")) or not c.get("rows") \
            or c.get("rows") != c.get("reference_rows"):
        problems.append("not every reference row was reproduced")
    return {"pass": not problems, "problems": problems,
            "control_sha256": sha256_file(path) if path.is_file() else None,
            "rows": c.get("rows"), "max_abs": c.get("max_abs")}


def window_leakage_check(audits, release_binding=None, root=None):
    """Section 7 window leakage before the look: the emissions opened no outcome or price file (so no MG-2 vector
    was joined to an outcome) and MG-1 was not modified.

    MG-1 is unmodified when the running ``mg1.py`` equals the release binding's record (forward) and, without a
    binding, when it equals the committed blob at ``HEAD``.
    """
    import subprocess

    problems = []
    for audit in audits:
        opened = audit.get("outcome_files_opened")
        if opened != []:
            problems.append(f"emission {audit.get('vectors_sha256')} recorded outcome reads {opened!r}")
    root = Path(root or repo_root())
    running = sha256_file(root / MG1_FILE)
    if release_binding:
        bound = (json.loads(Path(release_binding).read_text(encoding="utf-8")).get("files") or {}).get(MG1_FILE)
        reference, against = bound, "release binding"
    else:
        shown = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{MG1_FILE}"], capture_output=True)
        reference = hashlib.sha256(shown.stdout).hexdigest() if shown.returncode == 0 else None
        against = "HEAD"
    if running != reference:
        problems.append(f"mg1.py {running} differs from {against} ({reference})")
    return {"pass": not problems, "problems": problems, "mg1_sha256": running, "mg1_reference": against}


def run_check(*, out, nowcast_replay, nowcast_pin, nowcast_pin_sha256, l6_state_sha256, p3d_n_control, **kw):
    """``check``: emit twice, then every outcome-blind section 7 condition, written to ``mg2_checks.json``."""
    import pandas as pd

    first = emit(out=out, **kw)
    again = emit(out=Path(out) / "_replay", **kw)
    if not kw.get("control"):
        bound = first.get("l6_state_sha256")
        if l6_state_sha256 != bound:
            raise Mg2Refused(f"--l6-state-sha256 {l6_state_sha256!r} is not the bound state {bound!r}")
    snaps, _ = read_inputs(kw["layout_root"])
    snaps = _window(snaps, date.fromisoformat(str(kw["first"])), date.fromisoformat(str(kw["last"])))
    src = pd.read_parquet(Path(out) / "mg2_sources.parquet")
    result = outcome_blind_checks(snaps, dict(zip(src.row_key, src.source)),
                                  pd.read_parquet(Path(out) / VECTORS),
                                  replayed=pd.read_parquet(Path(out) / "_replay" / VECTORS))
    result["emit_audit_vectors_sha256"] = [r["vectors_sha256"] for r in (first, again)]
    nowcast = nowcast_replay_check(nowcast_replay, nowcast_pin, nowcast_pin_sha256, l6_state_sha256)
    p3d = p3d_n_replay_check(p3d_n_control)
    leak = window_leakage_check((first, again), kw.get("release_binding"))
    result.update(nowcast_replay=nowcast, nowcast_replay_pass=nowcast["pass"], p3d_n_replay=p3d,
                  p3d_n_replay_pass=p3d["pass"], window_leakage=leak, window_leakage_pass=leak["pass"])
    (Path(out) / CHECKS).write_text(json.dumps(result, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return result


def pre_look_reads(audit):
    """Outcome or price files opened before the look, as the forward emission recorded them."""
    opened = audit.get("outcome_files_opened")
    if not isinstance(opened, list):
        return ["the forward emission audit does not record its outcome reads"]
    return [str(x) for x in opened]


def gate_verdict(rows, margin):
    """G1: Delta(00-16) upper < margin; G2: Delta(13-16) upper < 0 (pooled ALL, date-clustered)."""
    def upper(block):
        row = next(r for r in rows if r["market"] == "ALL" and r["block"] == block)
        ci = row["model_minus_control_date_clustered"]["ci95"]
        return row["model_minus_control_date_clustered"]["estimate"], ci
    e1, c1 = upper("00-16")
    e2, c2 = upper("13-16")
    g1 = c1[1] is not None and c1[1] < margin
    g2 = c2[1] is not None and c2[1] < 0
    return {"G1_00_16": {"estimate": e1, "ci95": c1, "margin": margin, "pass": bool(g1)},
            "G2_13_16": {"estimate": e2, "ci95": c2, "pass": bool(g2)},
            "verdict": "PASS" if (g1 and g2) else "FAIL"}


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.mg2_composite")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("dev")
    p.add_argument("--layout", required=True)
    p.add_argument("--post", required=True, help="dev P3d_N distributions (jsonl)")
    p.add_argument("--nowcasts", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n", default="30,45,60")
    p.add_argument("--margin", type=float, default=None)
    p = sub.add_parser("freeze")
    p.add_argument("--layout", required=True)
    p.add_argument("--nowcasts", required=True, help="captured-METAR dev nowcasts (captured-nowcast)")
    p.add_argument("--out", required=True)
    for name in ("emit", "check"):
        p = sub.add_parser(name)
        p.add_argument("--layout", required=True)
        p.add_argument("--replay-root", required=True)
        p.add_argument("--nowcasts", required=True)
        p.add_argument("--coefficients", required=True)
        p.add_argument("--p3d-n-state", required=True, help="frozen P3d_N state (p3d_n_state.pkl)")
        p.add_argument("--rule", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--first", required=True)
        p.add_argument("--last", required=True)
        p.add_argument("--control", action="store_true")
        p.add_argument("--release-binding", default=None)
        if name == "check":  # rule section 7: nowcast replay, P3d_N replay (window leakage needs no input)
            p.add_argument("--nowcast-replay", required=True, help="captured-nowcast output on the dev window")
            p.add_argument("--nowcast-pin", required=True, help="season-matched dev nowcast pin (parquet)")
            p.add_argument("--nowcast-pin-sha256", required=True)
            p.add_argument("--l6-state-sha256", required=True, help="the L6 state the replay must have served")
            p.add_argument("--p3d-n-control", required=True, help="mg2_p3d_n control.json")
    p = sub.add_parser("nowcast")
    p.add_argument("--train-root", required=True)
    p.add_argument("--obs-root", required=True)
    p.add_argument("--layout", required=True)
    p.add_argument("--first", required=True)
    p.add_argument("--last", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--control", action="store_true")
    p = sub.add_parser("captured-nowcast", help="L6 n_own from captured METAR rows (L3 ecd8c9ba6 reader)")
    p.add_argument("--layout", required=True)
    p.add_argument("--replay-root", required=True)
    p.add_argument("--research-root", required=True)
    p.add_argument("--first", required=True)
    p.add_argument("--last", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--prev-root", default=None, help="verified bundle prev_day/ (forward); default D-1 replay")
    p.add_argument("--l6-state", required=True, help="frozen L6 own-model state (l6_own_state/1 pickle)")
    p.add_argument("--l6-state-sha256", required=True, help="the state's bound file sha256 (binding input)")
    p = sub.add_parser("bind-release", help="write release-binding.json from verified loads (no hand edit)")
    p.add_argument("--rule", required=True)
    p.add_argument("--coefficients", required=True)
    p.add_argument("--p3d-n-state", required=True)
    p.add_argument("--l6-state", required=True)
    p.add_argument("--l6-state-sha256", required=True)
    p.add_argument("--out", required=True, help="release-binding.json (refused if it exists)")
    p = sub.add_parser("score")
    p.add_argument("--layout", required=True)
    p.add_argument("--vectors", required=True)
    p.add_argument("--rule", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--mg1-look-receipt", default=None)
    p.add_argument("--release-binding", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "dev":
            result = dev_run(args.layout, args.post, args.nowcasts, args.out,
                             n_values=tuple(int(x) for x in args.n.split(",")), margin=args.margin)
            result = {k: result[k] for k in ("population", "coverage", "controls", "groups", "gate_groups",
                                             "sizing")}
        elif args.command == "freeze":
            result = freeze(args.layout, args.nowcasts, args.out)
        elif args.command == "nowcast":
            if not args.control and date.fromisoformat(args.last) <= DEV_LAST:
                raise Mg2Refused("forward nowcast is for dates after 2026-09-29; use --control for dev dates")
            if args.control and date.fromisoformat(args.last) > DEV_LAST:
                raise Mg2Refused("control nowcast is for dev dates <= 2026-09-29 only")
            result = nowcast(train_root=args.train_root, obs_root=args.obs_root, layout_root=args.layout,
                             first=args.first, last=args.last, out=args.out)
        elif args.command == "captured-nowcast":
            result = captured_nowcast(layout_root=args.layout, replay_root=args.replay_root,
                                      research_root=args.research_root, first=args.first, last=args.last,
                                      out=args.out, l6_state=args.l6_state,
                                      l6_state_sha256=args.l6_state_sha256, prev_root=args.prev_root)
        elif args.command == "bind-release":
            result = bind_release(rule=args.rule, coefficients=args.coefficients, p3d_n_state=args.p3d_n_state,
                                  served_states={"l6_state_sha256": (args.l6_state, args.l6_state_sha256)},
                                  out=args.out)
        elif args.command in ("emit", "check"):
            kw = dict(layout_root=args.layout, replay_root=args.replay_root,
                      nowcasts=args.nowcasts, coefficients=args.coefficients, p3d_n_state=args.p3d_n_state,
                      rule=args.rule, first=args.first, last=args.last, control=args.control,
                      release_binding=args.release_binding)
            if args.command == "check":
                result = run_check(out=args.out, nowcast_replay=args.nowcast_replay, nowcast_pin=args.nowcast_pin,
                                   nowcast_pin_sha256=args.nowcast_pin_sha256,
                                   l6_state_sha256=args.l6_state_sha256, p3d_n_control=args.p3d_n_control, **kw)
            else:
                result = emit(out=args.out, **kw)
        else:
            result = score(layout_root=args.layout, vectors=args.vectors, rule=args.rule, out=args.out,
                           release_binding=args.release_binding, mg1_look_receipt=args.mg1_look_receipt)
            result = {"guard": result["guard"], "coverage": result["coverage"], "gate": result["gate"]}
    except Mg2Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
