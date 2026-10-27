r"""Rule B-1 scorer: MG-2's as-of-capture vectors against the capture-time market, one forward look.

Research and shadow only. Nothing in serving, capture, release or Scheduler imports this module; the
import refuses from a production package and on the dedicated capture host (``mg2_composite``'s guard).

Rule B-1 (``B_forward_test_design.md``, fenced ``b_rule_v1`` block) pre-registers the estimand:

    Delta = mean over equal (date, market) cells of [Brier(MG-2 as-of-capture) - Brier(market, capture-time)]

on local hours 07-16, 10 fixed markets (Denver excluded), on the snapshots both arms cover, with the
fixed-market date-clustered percentile 95% interval (2,000 draws, seed 20260921; ``Table.w_date``). It is
the dev scorecard's ``score_rows`` ``model_minus_control_date_clustered`` with the market as the control,
restricted to the covered snapshots (``excess_rows``; the equivalence is test-pinned).

Subcommands (heavy ones run through ``scripts\ops\workstation_heavy.ps1``):

* ``control``: the B-1 section (a) positive control on the dev window (07-31..09-29, R-H's files): MG-1
  07-12 excess, L6 07-12 and P3d_N 13-16 capture-time excess (R-H atlas ``ff7ee231...``), and served vs
  market R on the default folds. Writes ``b_control.json`` (the look requires its PASS at this module's sha);
* ``check-rule``: parse a B-1 rule and list its unfilled binding fields (no data is read);
* ``look``: the single forward look. Refuses unless MG-1's look receipt exists (checked first), the MG-1
  window has closed, the rule is filled, the 45th date has settled and the vectors are the as-of-capture
  vectors of a forward emission (MG-2 rule section 8 C7). Section 8 VOID conditions are evaluated before any
  outcome, label or price is opened, except those that need the transfer itself (6 on its contents, 7).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

_PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                        "weather.trading", "weather.capture", "weather.sources", "weather.execution",
                        "maker_core", "app")


def _refuse_production_import():
    """Fail closed when imported from a production package (the capture-host refusal is mg2_composite's)."""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.b_scorer is research-only; imported from {name}")
        frame = frame.f_back


_refuse_production_import()

from weather import paths  # noqa: E402
from weather.calibration import mg2_composite as mg2  # noqa: E402  (its import refuses on the capture host)

NAME = "b_scorer"
SCHEMA = "b_scorer/1"
CONTROL_SCHEMA = "b_control/1"
TRANSFER_SCHEMA = "b_transfer/1"
DROP_LIST_SCHEMA = "b_drop_list/1"
CONSUMED_SCHEMA = "b_look_consumed/1"
RULE_BLOCK = "b_rule_v1"
FILL = "<FILL@BINDING>"
DEV_LAST = date(2026, 9, 29)

# The B-1 block's fixed values, mirrored by the code (the rule must agree with every one).
RULE_CONSTANTS = {
    "rule_id": "B-1",
    "candidate": "mg2_asof_capture",
    "n_dates": "45",
    "markets": "atlanta,austin,chicago,dallas,houston,los-angeles,miami,nyc,san-francisco,seattle",
    "hours_primary": "07-16",
    "interval": "date_clustered_w_date_2000_seed_20260921",
    "alpha_one_sided": "0.025",
    "noninferiority_margin": "0.0027",
    "market_coverage_min": "0.90",
    "min_surviving_dates": "40",
    "labels": "venue_rule_from_2026-10-23",
    "look_after": "mg1_look_receipt_and_window_closed",
}
BOUND_FIELDS = ("mg2_rule_sha256", "mg2_binding_commit", "mg2_release_binding_sha256", "mg2_owner_decision_id",
                "l6_coefficients_sha256", "p3d_n_state_sha256", "function_sha256", "b_scorer_sha256",
                "scorecard_code_sha256", "l6_state_sha256")
# The frozen season-matched L6 own-model state of MG-2's 07-12 arm (MG-2 clarification season-L6 2026-10-26,
# sections 3 and 7): bound in B-1, recorded in MG-2's release binding next to the l6_stack part sha.
L6_STATE_FIELD = "l6_state_sha256"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
COMMIT_HEX = re.compile(r"[0-9a-f]{40}")
OWNER_DECISION = re.compile(r"NONE|OD-\d{4}-\d{2}-\d{2}-[A-Za-z0-9][A-Za-z0-9_.-]*")  # mg2.OWNER_DECISION_ID or NONE
# What a filled bound field must look like; anything else (FILL, "", TBD, a short hash) is unfilled.
BOUND_FORMATS = {key: SHA256_HEX for key in BOUND_FIELDS}
BOUND_FORMATS.update(mg2_binding_commit=COMMIT_HEX, mg2_owner_decision_id=OWNER_DECISION)
RULE_FIELDS = tuple(RULE_CONSTANTS) + BOUND_FIELDS + ("d0", "d0_latest")
MARKETS = tuple(RULE_CONSTANTS["markets"].split(","))
N_DATES = 45
MARGIN = 0.0027
COVERAGE_MIN = 0.90
MIN_SURVIVING = 40
DRAWS = 2000
SEED = 20260921
PRIMARY = ("07-16", 7, 16)
SPLITS = (("07-12", 7, 12), ("13-16", 13, 16))
HOURS = tuple((f"h{h:02d}", h, h) for h in range(7, 17))
GROUPS = (PRIMARY,) + SPLITS + HOURS

VOID_CONDITIONS = {
    1: "an MG-2 void condition (MG-2 rule section 7)",
    2: "a bound hash in B-1 section 1 differs at the look",
    3: "the B-1 section (a) positive control failed or is not receipted at this scorer",
    4: "an outcome, label or price for a B date was read before the look",
    5: "the B read ran before the MG-1 look receipt existed",
    6: "the one-time transfer manifest is missing, altered or covers other dates",
    7: "fewer than 40 of the 45 dates survive the market-coverage drop",
}

TRANSFER_MANIFEST = "b_transfer_manifest.json"
CONSUMED = "b_look_consumed.json"  # written beside the transfer manifest and mg2_look.json when the look starts
# The authoritative one-look marker: a fixed repository-owned path keyed by the B-1 rule sha, so copying the
# inputs to fresh folders and passing a new --out cannot start a second look.
CONSUMED_ROOT = paths.data_path("b_look")
MG1_RECEIPT_TIME = "looked_at_utc"  # the instant inside MG-1's look receipt that VOID 5 compares against
# Market-local day ends for the embargo (B-1 section 9): the 45th date settles when its last market's day ends.
MARKET_TZ = {"atlanta": "America/New_York", "miami": "America/New_York", "nyc": "America/New_York",
             "austin": "America/Chicago", "chicago": "America/Chicago", "dallas": "America/Chicago",
             "houston": "America/Chicago", "los-angeles": "America/Los_Angeles",
             "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
TRANSFER_FILES = ("labels.parquet", "market.parquet")
LOOK = "b_look.json"
RECEIPT = "b_look_receipt.json"
CONTROL = "b_control.json"

# ---- B-1 section (a): R-H's dev inputs and values (C:\t\l2\rungh\atlas\rh_atlas.json, sha RH_ATLAS_SHA256)
RH_ATLAS_SHA256 = "ff7ee23179be2beceb9c7b883ffb3ae37fb9966e1aee7f8ee6df0744ab9fb814"
RH_LAYOUT_MANIFEST_SHA256 = "4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22"
RH_SCORECARD_CODE_SHA256 = "f69071ac5612f022ade56ada764f813c28da79cd0265848c58041115439005c5"
RH_L6_PART_SHA256 = "07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9"
RH_L6_NOWCAST_SHA256 = "3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3"
RH_P3D_SHA256 = ("cd0034b9faec0b687e1184187feeaa39ab151c5f9f8d1c905d3a49a0e7089542",   # 07-12 emission
                 "abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109")   # 13-16 emission
RH_RANGE = ("2026-08-01", "2026-09-29")
RH_TARGETS = {
    "mg1_excess_07_12": 0.011956814488641587,
    "L6_07-12": {"estimate": 0.008135956528900904, "ci95": [0.006233906004057347, 0.010060038207901219],
                 "n_snapshots": 28754, "n_market_days": 626},
    "P3d_N_13-16": {"estimate": 0.008269683656955082, "ci95": [0.006818617461659041, 0.009805276253433063],
                    "n_snapshots": 18574, "n_market_days": 626},
}
# The values B-1 section (a) quotes, and their tolerance.
B1_QUOTED = {"mg1_excess_07_12": (0.011957, 1e-6), "L6_07-12": (0.0081, [0.0062, 0.0101], 4),
             "served_R": ({"all": 1.774, "00-16": 1.526}, 3)}
REPRODUCTION_TOLERANCE = 1e-9


class BRefused(RuntimeError):
    """The B look or control cannot run under Rule B-1 (nothing was read, nothing is spent)."""


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_sha256():
    return sha256_file(__file__)


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, payload):
    Path(path).write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")


# ----------------------------------------------------------------------------- the rule

def read_rule(path):
    """The rule's raw sha256 and its fenced ``b_rule_v1`` block; every fixed value must equal the code's."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
    blocks = re.findall(r"```" + RULE_BLOCK + r"\n(.*?)```", text, re.S)
    if len(blocks) != 1:
        raise BRefused(f"rule must carry exactly one fenced {RULE_BLOCK} block (found {len(blocks)})")
    fields = {}
    for line in blocks[0].splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            if key.strip() in fields:
                raise BRefused(f"rule block repeats {key.strip()}")
            fields[key.strip()] = value.strip()
    missing = [k for k in RULE_FIELDS if k not in fields]
    if missing:
        raise BRefused(f"rule block lacks {missing}")
    unknown = sorted(set(fields) - set(RULE_FIELDS))
    if unknown:
        raise BRefused(f"rule block carries unknown keys {unknown}")
    wrong = {k: fields[k] for k, v in RULE_CONSTANTS.items() if fields[k] != v}
    if wrong:
        raise BRefused(f"rule values differ from the scorer's: {wrong}")
    d0, latest = date.fromisoformat(fields["d0"]), date.fromisoformat(fields["d0_latest"])
    if d0 > latest:
        raise BRefused(f"rule d0 {d0} is after d0_latest {latest}")
    return hashlib.sha256(raw).hexdigest(), fields


def unfilled(fields):
    """Bound fields that are not filled: anything but 64 lowercase hex (40 for the commit, a dated decision id
    or NONE for the owner decision), so FILL, "", TBD or a short hash all count."""
    return [k for k in BOUND_FIELDS
            if not isinstance(fields.get(k), str) or not BOUND_FORMATS[k].fullmatch(fields[k])]


def l6_state_problems(fields, release_binding):
    """The bound L6 state sha: 64 lowercase hex, and equal to the one MG-2's release binding records.

    The binding must be ``mg2_composite bind-release`` output (``RELEASE_BINDING_SCHEMA``), whose
    ``l6_state_sha256`` is the sha that ``load_l6_own_state`` verified, so two machine-written values meet here.
    """
    value = fields.get(L6_STATE_FIELD) or ""
    if not SHA256_HEX.fullmatch(value):
        return [L6_STATE_FIELD]
    binding = _json(release_binding)
    if binding.get("schema") != mg2.RELEASE_BINDING_SCHEMA:
        return [f"{L6_STATE_FIELD} (the MG-2 release binding is not bind-release output)"]
    if binding.get(L6_STATE_FIELD) != value:
        return [f"{L6_STATE_FIELD} (MG-2 release binding)"]
    return []


# ----------------------------------------------------------------------------- the estimand

def excess_rows(table, p_arm, covered, groups=GROUPS, per_market=True):
    """Arm minus market Brier per group on the covered snapshots: equal snapshots within a (date, market)
    cell, then equal cells; ``delta`` is date-clustered (``Table.w_date``), ``crossed`` the crossed date x
    market interval (reported, never decides), ``R`` the arm / market Brier ratio (date-clustered)."""
    import numpy as np

    from weather.reporting.scorecards import dev_scorecard as sc

    b_arm, b_mkt = table.brier(p_arm), table.brier(table.p_market)
    hours = table.local_hour
    rows = []
    markets = [sc.ALL_MARKETS] + (sorted(set(table.markets)) if per_market else [])
    for market in markets:
        for name, lo, hi in groups:
            mask = covered & (hours >= lo) & (hours <= hi)
            if market != sc.ALL_MARKETS:
                mask = mask & (table.markets == market)
            if not mask.any():
                continue
            idx, c = table.cells(b_arm, mask)
            _, m = table.cells(b_mkt, mask)
            ones = np.ones(len(idx))
            wd = table.w_date[:, idx]
            row = {"market": market, "group": name, "n_snapshots": int(mask.sum()), "n_market_days": int(len(idx)),
                   "n_dates": len({table.keys[i][0] for i in idx}), "brier_arm": float(c.mean()),
                   "brier_market": float(m.mean()), "delta": sc.ratio_interval(wd, c - m, ones),
                   "R": sc.ratio_interval(wd, c, m)}
            if market == sc.ALL_MARKETS:
                row["crossed"] = sc.ratio_interval(table.w[:, idx], c - m, ones)
            rows.append(row)
    return rows


def _row(rows, group, market="ALL"):
    return next((r for r in rows if r["group"] == group and r["market"] == market), None)


def decide(rows, margin=MARGIN):
    """B-1 section 6 on Delta(07-16) [L, U] (date-clustered 95%, one-sided 0.025 each side)."""
    primary = _row(rows, PRIMARY[0])
    ci = None if primary is None else primary["delta"].get("ci95")
    if (not ci or len(ci) != 2 or any(v is None or not math.isfinite(float(v)) for v in ci)
            or float(ci[0]) > float(ci[1])):
        return {"verdict": "VOID", "label": None, "reason": f"degenerate primary interval {ci!r}"}
    low, up = primary["delta"]["ci95"]
    split_low = {}
    for name, _, _ in SPLITS:
        r = _row(rows, name)
        split_low[name] = None if r is None else r["delta"]["ci95"][0]
    split_worse = any(v is not None and v > 0 for v in split_low.values())
    out = {"estimate": primary["delta"]["estimate"], "ci95": [low, up], "split_lower_bounds": split_low,
           "margin": margin}
    if up < 0 and not split_worse:
        out.update(verdict="PASS", label="edge")
    elif low > 0:
        out.update(verdict="FAIL", label="kill_edge_claim")
    else:
        out.update(verdict="INCONCLUSIVE", label="NOT-WORSE" if up < margin else None)
    return out


def void_result(conditions):
    return {"verdict": "VOID", "conditions": sorted(conditions),
            "reasons": {str(k): VOID_CONDITIONS[k] + (f": {v}" if v else "")
                        for k, v in sorted(conditions.items())}}


# ----------------------------------------------------------------------------- the look

def _utc(value):
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(f"{value!r} has no UTC offset")
    return moment.astimezone(timezone.utc)


def embargo_end(last_date):
    """The instant the 45th date has ended in every B market: the latest market-local midnight after it."""
    from zoneinfo import ZoneInfo

    day = date.fromisoformat(str(last_date)) + timedelta(days=1)
    return max(datetime.combine(day, time(0), ZoneInfo(MARKET_TZ[m])).astimezone(timezone.utc) for m in MARKETS)


def rule_marker(rule_sha):
    """The fixed marker for this B-1 rule: ``data/b_look/consumed-<rule_sha256>.json``."""
    return Path(CONSUMED_ROOT) / f"consumed-{rule_sha}.json"


def consumed_markers(transfer, mg2_look):
    """The look's input-side markers: beside the transfer manifest and beside mg2_look.json."""
    found = [Path(transfer) / CONSUMED, Path(mg2_look).parent / CONSUMED]
    return list(dict.fromkeys(p.resolve() for p in found))


def look_guard(*, rule, mg1_look_receipt, out, transfer=None, mg2_look=None, vectors=None, layout_root=None,
               drop_list=None, today=None, now=None):
    """Every refusal that comes before anything is read; then the look is consumed.

    Order: MG-1's look receipt FIRST, then the rule, the window, one look (the output and the consumed markers),
    the gate vectors (MG-2 rule section 8 C7), the look date set, the embargo (the latest market-local end of the
    45th date) and the drop list. Only then are the consumed markers written: first the fixed
    ``data/b_look/consumed-<rule_sha256>.json`` (mode "x"), then beside the transfer manifest and mg2_look.json, so
    a re-run with a new ``--out``, another drop list or copied inputs is refused.
    ``today`` and ``now`` are for tests; ``today`` alone stands for the last second of that UTC day.
    """
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    if not mg1_look_receipt or not Path(mg1_look_receipt).is_file() or Path(mg1_look_receipt).stat().st_size == 0:
        raise BRefused("MG-1's look receipt does not exist: B never reads before MG-1's look (B-1 sections 4, 9)")
    rule_sha, fields = read_rule(rule)
    gaps = unfilled(fields)
    if gaps:
        raise BRefused(f"rule fields are {FILL} or malformed: {gaps}")
    if now is None:
        now = (datetime.combine(today, time(23, 59, 59), timezone.utc) if today is not None
               else datetime.now(timezone.utc))
    today = now.astimezone(timezone.utc).date()
    start, end = mg2.reserved_end()
    if end is None or today <= end:
        raise BRefused(f"the recorded MG-1 window ({start}..{end or 'open'}) has not closed")
    if (Path(out) / LOOK).exists() or (Path(out) / RECEIPT).exists():
        raise BRefused("the B look already exists: exactly one look")
    if None in (transfer, mg2_look, vectors, layout_root, drop_list):
        raise BRefused("the look needs the transfer, mg2_look, vectors, layout and drop list")
    fixed = rule_marker(rule_sha)
    if fixed.exists():
        raise BRefused(f"the B look for rule {rule_sha} was already consumed ({fixed}): exactly one look")
    markers = consumed_markers(transfer, mg2_look)
    spent = [str(m) for m in markers if m.exists()]
    if spent:
        raise BRefused(f"the B look was already consumed ({spent}): exactly one look")
    mg2.require_gate_vectors(vectors)  # MG-2 rule section 8 C7: as-of-capture vectors of a forward emission
    look_dates = sorted(pd.read_parquet(Path(layout_root) / data.SNAPSHOTS_FILE, columns=["date"])
                        .date.astype(str).unique())
    if len(look_dates) != N_DATES:
        raise BRefused(f"the MG-2 look layout holds {len(look_dates)} dates, not {N_DATES}")
    settled = embargo_end(look_dates[-1])
    if now < settled:
        raise BRefused(f"embargo: the 45th date {look_dates[-1]} has not ended in every market (until "
                       f"{settled.isoformat()})")
    drops = _json(drop_list)
    if drops.get("schema") != DROP_LIST_SCHEMA:
        raise BRefused(f"drop list schema {drops.get('schema')!r} != {DROP_LIST_SCHEMA}")
    marker = {"schema": CONSUMED_SCHEMA, "rule_sha256": rule_sha, "b_scorer_sha256": module_sha256(),
              "out": str(Path(out).resolve()), "drop_list_sha256": sha256_file(drop_list),
              "consumed_at_utc": datetime.now(timezone.utc).isoformat()}
    fixed.parent.mkdir(parents=True, exist_ok=True)
    for path in [fixed, *markers]:  # the fixed marker first: it is the authority
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(json.dumps(marker, indent=1, sort_keys=True))
        except FileExistsError as exc:
            raise BRefused(f"the B look was already consumed ({path}): exactly one look") from exc
    return rule_sha, fields, today, look_dates, drops


def bound_hash_problems(fields, *, mg2_rule, release_binding, mg2_look, vectors, root=None):
    """B-1 section 1 hashes at the look (VOID condition 2). Reads no outcome."""
    from weather.reporting.scorecards import dev_scorecard as sc

    problems = []
    mg2_sha, mg2_fields = mg2.read_rule(mg2_rule)
    if mg2_sha != fields["mg2_rule_sha256"]:
        problems.append("mg2_rule_sha256")
    if sha256_file(release_binding) != fields["mg2_release_binding_sha256"]:
        problems.append("mg2_release_binding_sha256")
    if not COMMIT_HEX.fullmatch(fields["mg2_binding_commit"]):
        problems.append("mg2_binding_commit")
    else:
        problems += binding_commit_problems(fields["mg2_binding_commit"], release_binding, root=root)
    if (mg2.owner_decision(mg2_fields) or "NONE") != fields["mg2_owner_decision_id"]:
        problems.append("mg2_owner_decision_id")
    for key in ("l6_coefficients_sha256", "p3d_n_state_sha256", "function_sha256"):
        if mg2_fields.get(key) != fields[key]:
            problems.append(key)
    problems += l6_state_problems(fields, release_binding)
    problems += emit_audit_problems(fields, vectors)
    if mg2.rule_d0(mg2_fields) != date.fromisoformat(fields["d0"]):
        problems.append("d0 (MG-2 rule)")
    try:
        mg2.verify_release(release_binding, mg2_sha, mg2_fields, root=root)
        mg2.verify_function(mg2_fields)
    except mg2.Mg2Refused as exc:
        problems.append(f"release: {exc}")
    if module_sha256() != fields["b_scorer_sha256"]:
        problems.append("b_scorer_sha256")
    if sc.code_sha256() != fields["scorecard_code_sha256"]:
        problems.append("scorecard_code_sha256")
    look = _json(mg2_look)
    if look.get("rule_sha256") != mg2_sha:
        problems.append("mg2_look.rule_sha256")
    if look.get("vectors_sha256") != sha256_file(vectors):
        problems.append("mg2_look.vectors_sha256")
    return problems


def binding_commit_problems(commit, release_binding, root=None):
    """``mg2_binding_commit`` must hold exactly the code the release binding hashes: each bound file's blob at
    that commit has the binding's sha256 (the repository pins LF, so blob bytes are the working bytes)."""
    import subprocess

    root = Path(root or mg2.repo_root())
    files = _json(release_binding).get("files") or {}
    if not files:
        return ["mg2_binding_commit: the release binding lists no files"]
    problems = []
    for rel, sha in sorted(files.items()):
        proc = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{rel}"], capture_output=True,
                              timeout=60, check=False)
        if proc.returncode != 0:
            problems.append(f"mg2_binding_commit: {rel} is absent at {commit}")
        elif hashlib.sha256(proc.stdout).hexdigest() != sha:
            problems.append(f"mg2_binding_commit: {rel} at {commit} is not the bound file")
    return problems


def emit_audit_problems(fields, vectors):
    """The forward emission audit beside the gate vectors: its coefficients, P3d_N state, nowcasts and the L6
    state behind those nowcasts are the bound ones (the nowcasts manifest is ``mg2.captured_nowcast``'s)."""
    path = Path(vectors).parent / mg2.EMIT_AUDIT
    if not path.is_file():
        return ["emit audit missing"]
    audit = _json(path)
    problems = []
    for key in ("l6_coefficients_sha256", "p3d_n_state_sha256"):
        if audit.get(key) != fields[key]:
            problems.append(f"emit audit {key}")
    manifest = audit.get("nowcasts_manifest") or {}
    if not audit.get("nowcasts_sha256") or audit.get("nowcasts_sha256") != manifest.get("nowcasts_sha256"):
        problems.append("emit audit nowcasts_sha256")
    if manifest.get("prev_day_source") != mg2.FORWARD_PREV_DAY_SOURCE:
        problems.append("emit audit nowcasts prev_day_source")
    if manifest.get(L6_STATE_FIELD) != fields[L6_STATE_FIELD] or audit.get(L6_STATE_FIELD) != fields[L6_STATE_FIELD]:
        problems.append(f"emit audit {L6_STATE_FIELD}")
    return problems


def mg2_void_problems(mg2_look):
    """VOID 1: MG-2's own section 7 results, as ``mg2.score`` recorded them in mg2_look.json.

    Every condition in ``mg2.SECTION7_CONDITIONS`` must be recorded and pass; a missing, null or false result
    is VOID (a condition that was not evaluated never passes).
    """
    conditions = _json(mg2_look).get("void_conditions")
    if not isinstance(conditions, dict) or not conditions:
        return ["mg2_look.json records no section 7 condition results"]
    problems = [f"{name}: not recorded" for name in mg2.SECTION7_CONDITIONS if name not in conditions]
    return problems + [f"{name}: {(entry or {}).get('detail') if isinstance(entry, dict) else entry}"
                       for name, entry in sorted(conditions.items())
                       if not isinstance(entry, dict) or entry.get("pass") is not True]


def pre_look_read_problems(mg2_look):
    """VOID 4: outcome or price reads before the look, as ``mg2.score`` recorded them in mg2_look.json."""
    reads = _json(mg2_look).get("pre_look_reads")
    if not isinstance(reads, list):
        return ["mg2_look.json records no pre-look read list"]
    return [str(r) for r in reads]


def receipt_time_problems(manifest, mg1_look_receipt):
    """VOID 5: the manifest binds this MG-1 look receipt by sha256, and the transfer is after the instant the
    receipt itself records (``looked_at_utc``), never after a file time."""
    if manifest.get("mg1_look_receipt_sha256") != sha256_file(mg1_look_receipt):
        return ["the transfer manifest does not bind this MG-1 look receipt (mg1_look_receipt_sha256)"]
    try:
        looked = _utc(_json(mg1_look_receipt)[MG1_RECEIPT_TIME])
        moved = _utc(manifest["transferred_at_utc"])
    except (KeyError, TypeError, ValueError) as exc:
        return [f"no comparable instant ({MG1_RECEIPT_TIME} in the receipt, transferred_at_utc): {exc}"]
    if moved <= looked:
        return [f"transfer {moved.isoformat()} is not after the MG-1 look {looked.isoformat()}"]
    return []


def control_problems(path, fields):
    """VOID condition 3: a PASS control receipt at this scorer and scorecard."""
    if not path or not Path(path).is_file():
        return ["no control receipt"]
    receipt = _json(path)
    problems = []
    if receipt.get("schema") != CONTROL_SCHEMA or receipt.get("verdict") != "PASS":
        problems.append(f"control verdict {receipt.get('verdict')!r}")
    if receipt.get("b_scorer_sha256") != fields["b_scorer_sha256"]:
        problems.append("control ran at another scorer sha")
    if receipt.get("scorecard_code_sha256") != fields["scorecard_code_sha256"]:
        problems.append("control ran at another scorecard sha")
    return problems


def read_manifest(transfer):
    """The transfer manifest (no label or price file is opened here), or None when missing or malformed."""
    path = Path(transfer) / TRANSFER_MANIFEST
    if not path.is_file():
        return None, "manifest missing"
    manifest = _json(path)
    if manifest.get("schema") != TRANSFER_SCHEMA:
        return None, f"manifest schema {manifest.get('schema')!r}"
    if sorted((manifest.get("files") or {})) != sorted(TRANSFER_FILES):
        return None, "manifest files"
    try:
        rows = [(date.fromisoformat(r["date"]), bool(r["promotion_countable"])) for r in manifest["dates"]]
        datetime.fromisoformat(str(manifest["transferred_at_utc"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"manifest malformed: {exc}"
    return manifest, rows


def manifest_problems(manifest, rows, look_dates, d0):
    """Condition 6 on the manifest: input-countable dates from D0 in order, through the 45th countable date only."""
    if manifest is None:
        return [rows]
    problems = []
    days = [d for d, _ in rows]
    if days != sorted(set(days)):
        problems.append("dates not strictly increasing")
    if days and days[0] < d0:
        problems.append(f"a date before D0 {d0}")
    countable = [d for d, c in rows if c]
    if len(countable) != N_DATES:
        problems.append(f"{len(countable)} countable dates, not {N_DATES}")
    if rows and not rows[-1][1]:
        problems.append("dates after the 45th countable date")
    if [d.isoformat() for d in countable] != list(look_dates):
        problems.append("countable dates differ from MG-2's look date set")
    return problems


def transfer_files(transfer, manifest):
    """Labels and capture-time prices, each verified against the manifest (condition 6 on alteration)."""
    import io

    import pandas as pd

    frames, problems = {}, []
    for name in TRANSFER_FILES:
        path = Path(transfer) / name
        if not path.is_file():
            problems.append(f"{name} missing")
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][name]:
            problems.append(f"{name} altered")
            continue
        frames[name] = pd.read_parquet(io.BytesIO(raw))
    return frames, problems


def priced_snapshots(bands, market):
    """Per row_key: True when every band carries a finite capture-time ``p_market_yes``."""
    import numpy as np
    import pandas as pd

    price = market.set_index(["row_key", "band_index"]).p_market_yes
    p = price.reindex(pd.MultiIndex.from_arrays([bands.row_key, bands.band_index])).to_numpy(float)
    ok = pd.Series(np.isfinite(p), index=bands.row_key.to_numpy())
    return ok.groupby(level=0).all()


def market_coverage(snaps, priced):
    """Per date: share of the 10 markets' 07-16 snapshots with a capture-time price on every band."""
    s = snaps[snaps.market.astype(str).isin(MARKETS) & snaps.local_hour.between(7, 16)]
    ok = priced.reindex(s.row_key).fillna(False).to_numpy(bool)
    out = {}
    for d, flag in zip(s.date.astype(str), ok):
        n, k = out.get(d, (0, 0))
        out[d] = (n + 1, k + int(flag))
    return {d: {"snapshots": n, "priced": k, "share": k / n} for d, (n, k) in sorted(out.items())}


def build_table(snaps, bands, labels, market, keep_dates):
    """The scored Table: the 10 markets, the surviving dates, the snapshots the market arm covers."""
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    priced = priced_snapshots(bands, market)
    s = snaps[snaps.market.astype(str).isin(MARKETS) & snaps.date.astype(str).isin(keep_dates)]
    s = s[priced.reindex(s.row_key).fillna(False).to_numpy(bool)].reset_index(drop=True)
    keys = set(s.row_key)
    layout = data.Layout(snaps=s, bands=bands[bands.row_key.isin(keys)].reset_index(drop=True),
                         labels=labels[labels.row_key.isin(keys)].reset_index(drop=True),
                         market=market[market.row_key.isin(keys)].reset_index(drop=True),
                         manifest_sha256="b-transfer", file_sha256={}, label_source="b transfer")
    return sc.Table(layout, sorted(keep_dates))


def arm(table, frame):
    """The arm's scorecard vector (rule-4 floor mask) and the snapshots it covers (no served fallback)."""
    from weather.calibration import r0_ols_floor_challenger as l3

    return l3._vector(table, frame)


def log_pool_secondary(table, p, covered, dates):
    """B-1 section 7: walk-forward log-pool weight w on 07-16 (MODEL_IMPROVEMENT_METHOD section 3 rung 4) with
    the w = 0 identity, a date-deranged placebo and the floor-only control. No alpha; descriptive."""
    import numpy as np

    from weather.calibration import market_blend as mb

    hours = table.local_hour
    mask = covered & (hours >= PRIMARY[1]) & (hours <= PRIMARY[2])
    cell_dates = [k[0] for k in table.keys]
    cell_markets = [k[1] for k in table.keys]

    def walk(vector):
        values = mb.grid_cell_values(table, table.p_market, vector, {"07-16": mask})["07-16"][0]
        w_by = mb.walk_forward_w(values, cell_dates, cell_markets, sorted(dates))
        w = {d: v[0] for d, v in w_by.items()}
        blend = mb.pool(table.p_market, vector, mb.w_per_band(table, w, hours=range(7, 17)), table.impossible,
                        table.band_snap, len(table.snaps))
        return mb.w_summary(w), _row(excess_rows(table, blend, mask, (PRIMARY,), False), PRIMARY[0])

    w, row = walk(p)
    placebo_p, placebo_meta = mb.placebo_vector(table, p)
    pw, prow = walk(placebo_p)
    floor = mb.pool(table.p_market, table.p_market, 0.0, table.impossible, table.band_snap, len(table.snaps),
                    force_floor=True)
    return {"label": "descriptive (no alpha)", "w": w, "blend_vs_market": row,
            "w0_identity": mb.w0_identity(table, p),
            "placebo": {"meta": placebo_meta, "w": pw, "blend_vs_market": prow},
            "floor_only_vs_market": _row(excess_rows(table, floor, mask, (PRIMARY,), False), PRIMARY[0]),
            "market_blend_sha256": sha256_file(mb.__file__), "finite_cells": int(np.isfinite(table.brier(p)).sum())}


def look(*, rule, mg2_rule, release_binding, layout_root, vectors, mg2_look, transfer, drop_list, control_receipt,
         mg1_look_receipt, out, lih_vectors=None, today=None, now=None, root=None):
    """The single B look (B-1 sections 5, 6, 8, 9). Writes ``b_look.json`` and ``b_look_receipt.json``.

    ``look_guard`` consumes the look before anything is read. From then on every exit writes the receipt: a
    verdict, a VOID, or ABORTED when an exception escapes (re-raised after the receipt is written).
    """
    from weather.reporting.scorecards import dev_scorecard as sc

    rule_sha, fields, today, look_dates, drops = look_guard(
        rule=rule, mg1_look_receipt=mg1_look_receipt, out=out, transfer=transfer, mg2_look=mg2_look,
        vectors=vectors, layout_root=layout_root, drop_list=drop_list, today=today, now=now)
    out = Path(out)
    state = {"outcomes_opened": False,
             "base": {"schema": SCHEMA, "rule_sha256": rule_sha, "b_scorer_sha256": module_sha256(),
                      "scorecard_code_sha256": None, "inputs": {}, "today": today.isoformat()}}
    try:
        out.mkdir(parents=True, exist_ok=True)
        state["base"]["scorecard_code_sha256"] = sc.code_sha256()
        return _look_body(fields=fields, look_dates=look_dates, drops=drops, mg2_rule=mg2_rule,
                          release_binding=release_binding, layout_root=layout_root, vectors=vectors,
                          mg2_look=mg2_look, transfer=transfer, drop_list=drop_list,
                          control_receipt=control_receipt, mg1_look_receipt=mg1_look_receipt, out=out,
                          lih_vectors=lih_vectors, root=root, state=state)
    except BaseException as exc:
        payload = {**state["base"], "outcomes_opened": state["outcomes_opened"],
                   "decision": {"verdict": "ABORTED", "label": None, "error": f"{type(exc).__name__}: {exc}"}}
        _finish(out, payload, mg2_look)
        raise


def _look_body(*, fields, look_dates, drops, mg2_rule, release_binding, layout_root, vectors, mg2_look, transfer,
               drop_list, control_receipt, mg1_look_receipt, out, lih_vectors, root, state):
    import pandas as pd

    voids = {}
    mg2_voids = mg2_void_problems(mg2_look)
    if mg2_voids:
        voids[1] = mg2_voids
    hashes = bound_hash_problems(fields, mg2_rule=mg2_rule, release_binding=release_binding, mg2_look=mg2_look,
                                 vectors=vectors, root=root)
    if hashes:
        voids[2] = hashes
    ctl = control_problems(control_receipt, fields)
    if ctl:
        voids[3] = ctl
    reads = pre_look_read_problems(mg2_look)
    if reads:
        voids[4] = reads
    manifest, rows = read_manifest(transfer)
    if manifest is not None:
        late = receipt_time_problems(manifest, mg1_look_receipt)
        if late:
            voids[5] = late
    m_problems = manifest_problems(manifest, rows, look_dates, date.fromisoformat(fields["d0"]))
    dropped = sorted(str(d) for d in drops.get("dropped", []))
    if not set(dropped) <= set(look_dates):
        m_problems = list(m_problems) + ["the drop list names a date outside the look date set"]
    if m_problems:
        voids[6] = m_problems
    surviving = [d for d in look_dates if d not in set(dropped)]
    base = {**state["base"], "look_dates": [look_dates[0], look_dates[-1], len(look_dates)],
            "dropped": dropped, "surviving_dates": len(surviving),
            "inputs": {"vectors_sha256": sha256_file(vectors), "mg2_look_sha256": sha256_file(mg2_look),
                       "mg1_look_receipt_sha256": sha256_file(mg1_look_receipt),
                       "transfer_manifest_sha256": (sha256_file(Path(transfer) / TRANSFER_MANIFEST)
                                                    if manifest is not None else None),
                       "drop_list_sha256": sha256_file(drop_list),
                       "control_receipt_sha256": sha256_file(control_receipt) if Path(control_receipt).is_file()
                       else None, "release_binding_sha256": sha256_file(release_binding)}}
    state["base"] = base
    if voids:  # no label or price file has been opened
        return _finish(out, {**base, "decision": void_result(voids), "outcomes_opened": False}, mg2_look)

    state["outcomes_opened"] = True
    frames, f_problems = transfer_files(transfer, manifest)
    labels, market = frames.get("labels.parquet"), frames.get("market.parquet")
    snaps, bands = mg2.read_inputs(layout_root)
    if labels is not None and market is not None:
        if sorted(set(labels.date.astype(str))) != sorted(d.isoformat() for d, _ in rows):
            f_problems.append("transfer labels cover dates other than the manifest's")
        if not set(market.row_key) <= set(labels.row_key):
            f_problems.append("transfer prices cover rows the labels do not")
    if f_problems:
        return _finish(out, {**base, "decision": void_result({6: f_problems}), "outcomes_opened": True}, mg2_look)
    coverage = market_coverage(snaps, priced_snapshots(bands, market))
    recomputed = sorted(d for d in look_dates if coverage.get(d, {"share": 0.0})["share"] < COVERAGE_MIN)
    base["drop_list_check"] = {"recomputed_from_transfer": recomputed, "agrees": recomputed == dropped,
                               "coverage": coverage}
    late_voids = {}
    if recomputed != dropped:
        late_voids[6] = f"the drop list {dropped} is not the coverage drop recomputed from the transfer {recomputed}"
    if len(surviving) < MIN_SURVIVING:
        late_voids[7] = f"{len(surviving)} surviving"
    if late_voids:
        return _finish(out, {**base, "decision": void_result(late_voids), "outcomes_opened": True}, mg2_look)

    table = build_table(snaps, bands, labels, market, surviving)
    p, covered, reasons = arm(table, pd.read_parquet(vectors))
    rows_b = excess_rows(table, p, covered)
    payload = {**base, "outcomes_opened": True, "coverage": reasons, "rows": rows_b, "decision": decide(rows_b),
               "secondary": {"log_pool": log_pool_secondary(table, p, covered, surviving)}}
    if lih_vectors:
        p_l, cov_l, _ = arm(table, pd.read_parquet(lih_vectors))
        payload["secondary"]["last_in_hour"] = {"label": "descriptive", "vectors_sha256": sha256_file(lih_vectors),
                                                "rows": excess_rows(table, p_l, cov_l, GROUPS, False)}
    return _finish(out, payload, mg2_look)


def _finish(out, payload, mg2_look):
    """``b_look.json`` and the one look receipt holding MG-2's gate and B's verdict with every hash."""
    out.mkdir(parents=True, exist_ok=True)
    _write(out / LOOK, payload)
    try:
        gate = _json(mg2_look).get("gate")
    except (OSError, ValueError, AttributeError):
        gate = None
    receipt = {"schema": SCHEMA, "kind": "look_receipt", "mg2_look_sha256": sha256_file(mg2_look), "mg2_gate": gate,
               "b_look_sha256": sha256_file(out / LOOK), "b_decision": payload["decision"],
               "rule_sha256": payload["rule_sha256"], "b_scorer_sha256": payload["b_scorer_sha256"],
               "scorecard_code_sha256": payload["scorecard_code_sha256"], "inputs": payload["inputs"]}
    _write(out / RECEIPT, receipt)
    return payload


# ----------------------------------------------------------------------------- positive control (dev)

def _close(a, b, tol=REPRODUCTION_TOLERANCE):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


SECTION7_REPLAYS = ("nowcast_replay_pass", "p3d_n_replay_pass", "window_leakage_pass")


def section7_rehearsal(mg2_checks):
    """The rehearsal's ``mg2_composite check`` output: the three MG-2 section 7 replays, each true or false.

    A null or missing result refuses (an unevaluated condition is VOID 1 at the look, so the control proves the
    check computes all three).
    """
    path = Path(mg2_checks) if mg2_checks else None
    if path is None or not path.is_file():
        raise BRefused("the control needs the rehearsal's mg2_checks.json")
    checks = _json(path)
    values = {key: checks.get(key) for key in SECTION7_REPLAYS}
    unevaluated = [key for key, value in values.items() if not isinstance(value, bool)]
    if unevaluated:
        raise BRefused(f"mg2_checks.json leaves MG-2 section 7 conditions unevaluated: {unevaluated}")
    return {"path": str(path), "sha256": sha256_file(path), **values,
            "emit_audit_vectors_sha256": checks.get("emit_audit_vectors_sha256")}


def control(*, layout, coefficients, nowcasts, p3d_files, out, mg2_checks):
    """B-1 section (a) on R-H's dev inputs (07-31..09-29 layout; no date after 09-29 is opened).

    ``mg2_checks`` is the 09-28 rehearsal's ``mg2_composite check`` output; the receipt records its three section 7
    replays (each must be true or false) beside the positive control.
    """
    import numpy as np
    import pandas as pd

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out = Path(out)
    if (out / CONTROL).exists():
        raise BRefused(f"refusing to overwrite {out / CONTROL}")
    rehearsal = section7_rehearsal(mg2_checks)
    problems = []
    if sha256_file(nowcasts) != RH_L6_NOWCAST_SHA256:
        problems.append("L6 nowcasts")
    if sorted(sha256_file(f) for f in p3d_files) != sorted(RH_P3D_SHA256):
        problems.append("P3d_N emissions")
    part = mg2.load_part(coefficients, "l6", RH_L6_PART_SHA256)
    if sc.code_sha256() != RH_SCORECARD_CODE_SHA256:
        problems.append("scorecard code")
    if problems:
        raise BRefused(f"control inputs are not R-H's: {problems}")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    state = {"coef": {int(h): tuple(v) for h, v in part["coef"].items()}, "column": part["column"]}
    start, end = data.check_range(*RH_RANGE)
    lay = data.load_layout(layout, data.DEV_FIRST, end)
    if lay.manifest_sha256 != RH_LAYOUT_MANIFEST_SHA256:
        raise BRefused(f"layout manifest {lay.manifest_sha256} is not R-H's")
    folds = data.make_folds(lay.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)

    ctl = sc.Table(lay, scored)
    p_mg1, _, _ = l3._vector(ctl, loss_atlas.mg1_frame(ctl))
    _, e = ctl.cells(ctl.brier(p_mg1) - ctl.brier(ctl.p_market), (ctl.local_hour >= 7) & (ctl.local_hour <= 12))
    mg1_excess = float(e.mean())
    served = {r["block"]: r["gap_ratio"]["estimate"] for r in sc.score_rows(ctl, ctl.p_served, True)
              if r["market"] == sc.ALL_MARKETS and r["block"] in ("all", "00-16")}
    del ctl

    dates = sorted(d for d in {str(x) for x in lay.dates} if RH_RANGE[0] <= d <= RH_RANGE[1])
    table = sc.Table(lay, dates)
    if not np.array_equal(table.w_date, l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)):
        raise BRefused("Table.w_date is not R-H's date weights")
    out.mkdir(parents=True, exist_ok=True)
    combined = out / "dev_P3d_N_fix_07_16.jsonl"
    combined.write_bytes(b"".join(Path(f).read_bytes() for f in p3d_files))
    p_fix, cov_fix, r_fix = arm(table, l3._candidate_frame(str(combined), table, lay, folds, data)[0])
    snaps_floor = table.snaps.assign(floor=table.snaps[list(data.FLOOR_FIELDS)].apply(
        pd.to_numeric, errors="coerce").max(axis=1))
    p_l6, cov_l6, r_l6 = arm(table, l6_stack.predict(state, snaps_floor, table.bands))
    common = cov_fix & cov_l6
    l6 = _row(excess_rows(table, p_l6, common, (SPLITS[0],), False), "07-12")
    p3d = _row(excess_rows(table, p_fix, common, (SPLITS[1],), False), "13-16")
    in10 = np.isin(table.markets, MARKETS)
    ten = {"L6_07-12": _row(excess_rows(table, p_l6, common & in10, (SPLITS[0],), False), "07-12"),
           "P3d_N_13-16": _row(excess_rows(table, p_fix, common & in10, (SPLITS[1],), False), "13-16")}

    quoted, tol = B1_QUOTED["mg1_excess_07_12"]
    checks = {"mg1_excess_07_12_rh": _close(mg1_excess, RH_TARGETS["mg1_excess_07_12"]),
              "mg1_excess_07_12_b1": _close(mg1_excess, quoted, tol)}
    for name, got in (("L6_07-12", l6), ("P3d_N_13-16", p3d)):
        want = RH_TARGETS[name]
        checks[f"{name}_rh"] = bool(
            got is not None and _close(got["delta"]["estimate"], want["estimate"])
            and all(_close(a, b) for a, b in zip(got["delta"]["ci95"], want["ci95"]))
            and got["n_snapshots"] == want["n_snapshots"] and got["n_market_days"] == want["n_market_days"])
    est, ci, digits = B1_QUOTED["L6_07-12"]
    checks["L6_07-12_b1"] = bool(l6 is not None and round(l6["delta"]["estimate"], digits) == est
                                 and [round(x, digits) for x in l6["delta"]["ci95"]] == ci)
    want_r, digits = B1_QUOTED["served_R"]
    checks["served_R_b1"] = all(served.get(b) is not None and round(served[b], digits) == v for b, v in want_r.items())
    payload = {"schema": CONTROL_SCHEMA, "verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
               "observed": {"mg1_excess_07_12": mg1_excess, "served_R": served, "L6_07-12": l6, "P3d_N_13-16": p3d},
               "descriptive_10_markets": ten, "targets": RH_TARGETS, "b1_quoted": B1_QUOTED,
               "coverage": {"P3d_N_fix": r_fix, "L6": r_l6, "common": int(common.sum())},
               "population": {"scored_dates_ctl": [scored[0], scored[-1], len(scored)],
                              "dates": [dates[0], dates[-1], len(dates)], "n_market_days": len(table.keys)},
               "b_scorer_sha256": module_sha256(), "scorecard_code_sha256": sc.code_sha256(),
               "rh_atlas_sha256": RH_ATLAS_SHA256, "mg2_section7_rehearsal": rehearsal,
               "inputs": {"layout_manifest_sha256": lay.manifest_sha256, "l6_part_sha256": RH_L6_PART_SHA256,
                          "nowcasts_sha256": RH_L6_NOWCAST_SHA256,
                          "p3d_files": {str(f): sha256_file(f) for f in p3d_files}}}
    combined.unlink()
    _write(out / CONTROL, payload)
    return payload


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.b_scorer")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("control", help="B-1 section (a) positive control on the dev window")
    c.add_argument("--layout", required=True)
    c.add_argument("--coefficients", required=True)
    c.add_argument("--nowcasts", required=True)
    c.add_argument("--p3d", nargs=2, required=True, help="R-H's 07-12 and 13-16 P3d_N_fix emissions")
    c.add_argument("--mg2-checks", required=True, help="the 09-28 rehearsal's mg2_composite check output")
    c.add_argument("--out", required=True)
    r = sub.add_parser("check-rule", help="parse a B-1 rule; list unfilled binding fields")
    r.add_argument("--rule", required=True)
    k = sub.add_parser("look", help="the single forward look (guarded)")
    for name in ("rule", "mg2-rule", "release-binding", "layout", "vectors", "mg2-look", "transfer", "drop-list",
                 "control-receipt", "mg1-look-receipt", "out"):
        k.add_argument(f"--{name}", required=True)
    k.add_argument("--lih-vectors", help="last_in_hour vectors (descriptive secondary only)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "control":
            result = control(layout=args.layout, coefficients=args.coefficients, nowcasts=args.nowcasts,
                             p3d_files=args.p3d, out=args.out, mg2_checks=args.mg2_checks)
            print(json.dumps({"verdict": result["verdict"], "checks": result["checks"]}, indent=1))
            return 0 if result["verdict"] == "PASS" else 7
        if args.command == "check-rule":
            sha, fields = read_rule(args.rule)
            print(json.dumps({"rule_sha256": sha, "unfilled": unfilled(fields)}, indent=1))
            return 0
        result = look(rule=args.rule, mg2_rule=args.mg2_rule, release_binding=args.release_binding,
                      layout_root=args.layout, vectors=args.vectors, mg2_look=args.mg2_look, transfer=args.transfer,
                      drop_list=args.drop_list, control_receipt=args.control_receipt,
                      mg1_look_receipt=args.mg1_look_receipt, out=args.out,
                      lih_vectors=args.lih_vectors)
        print(json.dumps(result["decision"], indent=1, default=str))
        return 0
    except (BRefused, mg2.Mg2Refused) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
