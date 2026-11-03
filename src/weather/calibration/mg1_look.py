r"""MG-1 confirmation look: the registered entry point and the look receipt it writes (``mg1_look_receipt/1``).

Research only. Rule B-1 (sections 4, 9; VOID 5) reads MG-1's look receipt before anything else, and compares the
transfer instant against the instant the receipt records. This module is the only writer of that receipt, so no
field of it is typed by hand.

How a look uses it (``python -m weather.calibration.mg1_look``, registered by module name and source sha256 in
``weather.mg1_reserved_window.MG1_CONFIRMATION_ENTRY_POINTS``):

* ``Look(rule)`` checks that the MG-1 pre-registration bytes hash to the signed ``MG1_RULE_SHA256`` and that neither
  the start marker nor the receipt for that rule exists under ``data/mg1_look/`` (``weather.paths``).
* ``look.join_outcomes(loader, ...)`` is the only way the look obtains an outcome. Its first call refuses unless the
  running ``__main__`` is the registered entry point at its registered sha, then stamps ``looked_at_utc`` from the
  clock and writes ``started-<rule_sha256>.json`` (mode "x") BEFORE ``loader`` runs. A second look for the rule is
  refused from then on, even if the first one crashes.
* ``look.finish(result=..., dates=...)`` writes ``receipt-<rule_sha256>.json`` (mode "x"): the format accepted by
  master on 2026-10-26 (R3), plus ``body_sha256`` over the canonical JSON of every other field.
* ``receipt_problems(path)`` is what B-1's VOID 5 runs: the schema, the body sha, the signed rule, the entry point
  registered at the recorded sha, and the file's bytes equal to the receipt at the fixed path for its rule.

The fixed path is per checkout (``data/`` is local), so the looks run from the production root and the receipt and
markers are copied into the repository record the same day (B-1 clarification of 2026-10-26).

The MG-1 scoring (pre-registration sections 4 and 6, Clarifications 1 and 2) is ``score``, run by ``main run``.
Its sha256 is re-registered in ``MG1_CONFIRMATION_ENTRY_POINTS`` by a reviewed edit. ``score`` reads, in this
order:

1. the rule and the countable-date list (``mg1_countable/1``, per-market flags);
2. the R24 label freeze receipt (A4: refused until it exists, after the 45th date has ended in every scored market;
   only file hashes are read);
3. the label-free layout (snapshots and bands; ``screen_inputs`` refuses any label or price column).

Non-countable market-days are dropped from the layout (A3). Then come the holds, which consume nothing:

- a countable market-day with no layout rows;
- a used row whose ``v2_status`` is not "available" (A6).

It then builds the MG-1 vector (``free_source_candidates.mg1.predict``, whose sha the receipt records) and runs
every outcome-blind VOID check. Only then does ``join_outcomes`` read the labels (``read_venue_labels`` on the
frozen copy, A2) and the capture-time prices. A label the reader refuses masks that market-day (T2). Every exit
after that first join writes the result and the receipt (a verdict, a VOID, or ABORTED).

The owner's open questions A1, A5 and A12 are one constant each (``A1_DENVER_SCORED``, ``A5_BAR``,
``A12_FALSIFIER_4``). Both branches of each are built, and the result records the values in force.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import socket
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather import mg1_reserved_window as window
from weather import paths

MODULE = "weather.calibration.mg1_look"
RECEIPT_SCHEMA = "mg1_look_receipt/1"
STARTED_SCHEMA = "mg1_look_started/1"
# docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md at 02c410a5, signed 2026-10-04T16:10Z.
MG1_RULE_SHA256 = "b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665"
MG1_FILE = "src/weather/reporting/scorecards/free_source_candidates/mg1.py"
LOOK_ROOT = paths.data_path("mg1_look")
RECEIPT_FIELDS = ("schema", "entry_point", "mg1_rule_sha256", "window", "dates_scored", "looked_at_utc",
                  "completed_at_utc", "result", "mg1_py_sha256", "repo_commit", "host", "label_freeze_receipt_sha256",
                  "body_sha256")


class MG1LookRefused(RuntimeError):
    """The MG-1 look refused before reading anything, or its receipt cannot be written."""


class MG1LookHeld(MG1LookRefused):
    """An outcome-blind hold before the first join (MG-1 Clarification 2): nothing was consumed; master rules."""


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_sha256():
    return sha256_file(__file__)


def receipt_path(rule_sha256):
    return Path(LOOK_ROOT) / f"receipt-{rule_sha256}.json"


def started_path(rule_sha256):
    return Path(LOOK_ROOT) / f"started-{rule_sha256}.json"


def body_sha256(receipt):
    body = {key: value for key, value in receipt.items() if key != "body_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def head_commit(root=None):
    out = subprocess.run(["git", "-C", str(root or paths.REPO_ROOT), "rev-parse", "HEAD"], capture_output=True,
                         text=True, check=True)
    return out.stdout.strip()


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _now_utc():
    return datetime.now(timezone.utc)


def _write_x(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise MG1LookRefused(f"{path} already exists: MG-1 has exactly one look") from exc


class Look:
    """One MG-1 look. Construct, obtain every outcome through ``join_outcomes``, then ``finish``."""

    def __init__(self, rule):
        self.rule_sha256 = sha256_file(rule)
        if self.rule_sha256 != MG1_RULE_SHA256:
            raise MG1LookRefused(f"the MG-1 rule {rule} hashes to {self.rule_sha256}, not the signed "
                                 f"{MG1_RULE_SHA256}")
        for path in (started_path(self.rule_sha256), receipt_path(self.rule_sha256)):
            if path.exists():
                raise MG1LookRefused(f"{path} already exists: MG-1 has exactly one look")
        # A7 (MG-1 Clarification 2): the code-side half of the window-leakage attestation. Neither the start marker
        # nor the receipt existed when this look began; master's look-log attestation covers the rest.
        self.absence = {"started_marker": str(started_path(self.rule_sha256)),
                        "receipt": str(receipt_path(self.rule_sha256)), "both_absent": True,
                        "checked_at_utc": _utc_now()}
        self.looked_at_utc = None
        self.receipt = None

    def join_outcomes(self, loader, *args, **kwargs):
        """Return ``loader(*args, **kwargs)``; the first call stamps ``looked_at_utc`` before ``loader`` runs."""
        if self.receipt is not None:
            raise MG1LookRefused("the look has finished; no outcome is read after its receipt")
        if self.looked_at_utc is None:
            entry = window.registered_confirmation_entry()
            if entry != MODULE:
                raise MG1LookRefused(f"the running entry point {entry!r} is not the registered MG-1 look {MODULE}")
            stamped = _utc_now()
            _write_x(started_path(self.rule_sha256), {"schema": STARTED_SCHEMA, "mg1_rule_sha256": self.rule_sha256,
                                                      "looked_at_utc": stamped, "entry_sha256": module_sha256()})
            self.looked_at_utc = stamped
        return loader(*args, **kwargs)

    def finish(self, *, result, dates, root=None, label_freeze_receipt_sha256=None):
        """Write the receipt (mode "x") at the fixed path for the rule and return its path.

        ``label_freeze_receipt_sha256`` is the R24 freeze receipt the look read its labels through (A2)."""
        if self.looked_at_utc is None:
            raise MG1LookRefused("no outcome was joined through join_outcomes: there is no look to record")
        if self.receipt is not None:
            raise MG1LookRefused("the look receipt is already written")
        days = sorted({date.fromisoformat(str(d)).isoformat() for d in dates})
        if not days:
            raise MG1LookRefused("the look scored no date")
        start, last = window.window()
        root = Path(root or paths.REPO_ROOT)
        receipt = {"schema": RECEIPT_SCHEMA,
                   "entry_point": {"module": MODULE, "source_sha256": module_sha256()},
                   "mg1_rule_sha256": self.rule_sha256,
                   "window": {"d0": start.isoformat(), "last": last.isoformat() if last else None},
                   "dates_scored": {"count": len(days), "first": days[0], "last": days[-1]},
                   "looked_at_utc": self.looked_at_utc, "completed_at_utc": _utc_now(),
                   "result": {"path": str(Path(result).resolve()), "sha256": sha256_file(result)},
                   "mg1_py_sha256": sha256_file(root / MG1_FILE), "repo_commit": head_commit(root),
                   "host": socket.gethostname(), "label_freeze_receipt_sha256": label_freeze_receipt_sha256}
        receipt["body_sha256"] = body_sha256(receipt)
        path = receipt_path(self.rule_sha256)
        _write_x(path, receipt)
        self.receipt = receipt
        return path


def receipt_problems(path):
    """What B-1's VOID 5 checks about a receipt before comparing instants; ``[]`` when it is a written receipt."""
    path = Path(path) if path else None
    if path is None or not path.is_file():
        return [f"MG-1 look receipt {path} does not exist"]
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"MG-1 look receipt {path} is unreadable: {exc}"]
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        return [f"MG-1 look receipt schema is not {RECEIPT_SCHEMA}"]
    problems = []
    missing = [key for key in RECEIPT_FIELDS if key not in receipt]
    if missing:
        problems.append(f"MG-1 look receipt lacks {missing}")
    if receipt.get("body_sha256") != body_sha256(receipt):
        problems.append("MG-1 look receipt body_sha256 does not match its fields (edited by hand)")
    if receipt.get("mg1_rule_sha256") != MG1_RULE_SHA256:
        problems.append("MG-1 look receipt does not name the signed MG-1 rule")
    entry = receipt.get("entry_point") or {}
    registered = window.MG1_CONFIRMATION_ENTRY_POINTS.get(entry.get("module"))
    if entry.get("module") != MODULE or not registered or registered != entry.get("source_sha256"):
        problems.append("MG-1 look receipt was not written by the registered entry point at its registered sha")
    fixed = receipt_path(MG1_RULE_SHA256)
    if not fixed.is_file() or sha256_file(fixed) != sha256_file(path):
        problems.append(f"MG-1 look receipt bytes differ from the written receipt at {fixed}")
    return problems


# ----------------------------------------------------------------------------- the MG-1 scoring (section 4)
#
# Every constant below is the pre-registration's (section and line cited); those marked PROVISIONAL implement a
# reading that lane L8 flagged to master as ambiguous (A1..A14 in the scoring note) and must be ruled on before the
# look. Nothing here was sized or chosen on any reserved date: the tests are synthetic.

RESULT = "mg1_look_result.json"
RESULT_SCHEMA = "mg1_look_result/1"
COUNTABLE_SCHEMA = "mg1_countable/1"
# Section 4 "US11", section 7 "the fixed 11-market support": B-1's ten plus Denver, which settles on KDEN from
# 2026-10-23 while MG-1 reads KBKF guidance. Whether Denver stays in is A1 (``A1_DENVER_SCORED``).
MARKETS = ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
           "san-francisco", "seattle")
# Owner questions, open (MG-1 Clarification 2 section 3). Each has exactly one constant here, and both branches
# are built and tested. The owner's answer is a one-line change, recorded in a dated note before the look. Until
# then each keeps the behaviour of 1179f990d.
A1_DENVER_SCORED = True        # A1: True keeps Denver in the support and the scored markets (KDEN labels from
#                                the cutover, read with model_scoring=False); False drops Denver from both
A5_BAR = "as_written"          # A5: "as_written" bar = -0.05 * gap; "magnitude" bar = -0.05 * |gap|
A12_FALSIFIER_4 = "point"      # A12: "point" = the crossed point estimate has the opposite sign; "interval" = the
#                                crossed 95% interval lies entirely on the opposite side of 0
OWNER_CHOICES = {"A1_DENVER_SCORED": (True, False), "A5_BAR": ("as_written", "magnitude"),
                 "A12_FALSIFIER_4": ("point", "interval")}
# R24 freeze receipt (weather.backtesting.venue_label_audit ``freeze --look mg1``, R24 paragraph 3). The schema
# string is the venue_labels schema family's; it is pinned by a test once that module lands.
FREEZE_RECEIPT_SCHEMA = "venue_label_freeze_receipt_v1"
FREEZE_LOOK_ID = "mg1"
FREEZE_FILES = ("label_csv", "manifest", "wu_daily_summary")
MARKET_TZ = {"atlanta": "America/New_York", "miami": "America/New_York", "nyc": "America/New_York",
             "austin": "America/Chicago", "chicago": "America/Chicago", "dallas": "America/Chicago",
             "houston": "America/Chicago", "denver": "America/Denver", "los-angeles": "America/Los_Angeles",
             "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
N_DATES = 45                      # section 3: 45 promotion-countable dates from D0, no skipping
PRIMARY = ("00-16", 0, 16)        # section 4: local 00:00-16:59
DRAWS = 2000                      # section 4: multinomial date bootstrap, 2,000 draws
SEED = 20261004                   # section 4: seed 20261004 (fixed-market, date-clustered)
CROSSED_SEED = 20260921           # section 4 reported: "81a's statistics, seed 20260921" (the scorecard's Table.w)
MIN_NEGATIVE_MARKETS = 8          # section 4: >= 8/11 markets with a negative per-market mean delta
MATERIALITY = 0.05                # section 4: estimate <= -5% of the window's own 00-16 served - market gap
COVERAGE_MIN = 0.90               # section 6 VOID: 00-16 MG-1 coverage below 90% of snapshots
REPLAY_TOLERANCE = 1e-12          # section 6 VOID: replay reproduces the shadow vector to 1e-12
PARSER_VERSION = 2                # section 6 VOID: a parser version other than 2 on any eligible row
TAIL_GAP = 0.30                   # section 4 reported tail lens, EF 10 table definition (A11)
REPORTED_GROUPS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16),
                   ("15-16", 15, 16), ("17-23", 17, 23), ("all", 0, 23))
KNOWN_COST = "15-16"              # section 1 / section 4: the known development cost, never a gate
SERVED_RELEASE_COLUMNS = ("served_release_id", "release_id", "model_version")  # PROVISIONAL (A10)
VOID_CONDITIONS = {
    "pit": "an MG-1 input with availability after captured_at_utc, or v2_period_kind other than maximum",
    "coverage": "00-16 MG-1 coverage below 90% of snapshots",
    "replay": "captured-input replay does not reproduce the shadow vector on 100% of snapshots to 1e-12",
    "window_leakage": "before the look an MG-1 or guidance-read-family vector was joined to an outcome on a "
                      "reserved date, or MG-1 was modified",
    "parser": "a parser version other than 2 on an eligible row",
}


def owner_constants():
    """The owner-question constants in force (A1, A5, A12); refuses a value outside the two built branches."""
    values = {"A1_DENVER_SCORED": A1_DENVER_SCORED, "A5_BAR": A5_BAR, "A12_FALSIFIER_4": A12_FALSIFIER_4}
    for name, value in values.items():
        if value not in OWNER_CHOICES[name] or (name == "A1_DENVER_SCORED" and not isinstance(value, bool)):
            raise MG1LookRefused(f"{name} = {value!r} is not one of the built branches {OWNER_CHOICES[name]}")
    return values


def support_markets():
    """The US11 support and scored markets under A1: all 11, or the ten without Denver."""
    owner_constants()
    return MARKETS if A1_DENVER_SCORED else tuple(m for m in MARKETS if m != "denver")


def _parse_countable(body):
    """``mg1_countable/1`` rows checked for structure, D0, no skipping and the 45th countable date (no window)."""
    if not isinstance(body, dict) or body.get("schema") != COUNTABLE_SCHEMA:
        raise MG1LookRefused(f"the countable-date list is not {COUNTABLE_SCHEMA}")
    support = set(support_markets())
    try:
        rows = [{"date": date.fromisoformat(str(r["date"])), "countable": r["promotion_countable"],
                 "markets": dict(r["markets"]), "parser_v2_verified": r["parser_v2_verified"],
                 "shadow_stage_captured": r["shadow_stage_captured"],
                 "caveat_reasons": dict(r.get("caveat_reasons") or {})}
                for r in body["dates"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise MG1LookRefused(f"the countable-date list is malformed: {exc}") from exc
    for r in rows:
        if not isinstance(r["countable"], bool):
            raise MG1LookRefused("promotion_countable must be true or false on every date")
        if set(r["markets"]) != support or any(not isinstance(v, bool) for v in r["markets"].values()):
            raise MG1LookRefused(f"{r['date']}: markets must give true or false for exactly the support "
                                 f"{sorted(support)} (A1, A3)")
        if r["countable"] != any(r["markets"].values()):  # A3: D counts iff >= 1 support market-day counts
            raise MG1LookRefused(f"{r['date']}: promotion_countable must be true iff some support market-day is")
        for key in ("parser_v2_verified", "shadow_stage_captured"):
            if r[key] not in (True, False, None):
                raise MG1LookRefused(f"{key} must be true, false or null on every date")
        if any(k not in ("parser_v2_verified", "shadow_stage_captured") or not isinstance(v, str)
               for k, v in r["caveat_reasons"].items()):
            raise MG1LookRefused("caveat_reasons may only give a text reason for a caveat")
    start, _ = window.window()
    days = [r["date"] for r in rows]
    if not days or days[0] != start:
        raise MG1LookRefused(f"the countable-date list does not start at D0 {start}")
    if any(b - a != timedelta(days=1) for a, b in zip(days, days[1:])):
        raise MG1LookRefused("the countable-date list skips or repeats a calendar date (section 3: no skipping)")
    counted = [r["date"] for r in rows if r["countable"]]
    if len(counted) != N_DATES:
        raise MG1LookRefused(f"{len(counted)} countable dates, not {N_DATES}")
    if not rows[-1]["countable"]:
        raise MG1LookRefused("the list runs past the 45th countable date")
    return counted, rows


def read_countable(path):
    """The counted dates (section 3, Clarifications 1 and 2), the per-market flags and the reporting caveats.

    ``mg1_countable/1``: ``{"schema", "dates": [{"date", "promotion_countable", "markets": {market: bool},
    "parser_v2_verified", "shadow_stage_captured", "caveat_reasons"?}]}``. Master writes it with
    ``write_countable``, since master owns the countability check (A3). It holds one row per calendar date from D0
    through the 45th countable date, and no label or price. A date counts iff at least one support market-day
    has the ledger's promotion_countable true (R11 (1)), and section 4 scores only the countable market-days.
    """
    counted, rows = _parse_countable(json.loads(Path(path).read_text(encoding="utf-8")))
    _, last = window.window()
    if last is None:
        raise MG1LookRefused("the MG-1 window is not recorded: there is no 45th date to count to")
    if counted[-1] > last:  # MG1_LAST may only move later, and must move before a later date is scored
        raise MG1LookRefused(f"the 45th countable date {counted[-1]} is after the recorded MG1_LAST {last}: "
                             "the window must be extended first")
    return counted, rows


def write_countable(path, dates):
    """Write ``mg1_countable/1`` once (mode "x") and return its sha256 (R11 Head 2's ``--final``).

    ``dates``: one mapping per calendar date from D0, in order, with ``date``, ``markets`` ({support market:
    promotion_countable}), ``parser_v2_verified`` and ``shadow_stage_captured`` (true, false or null), and
    optionally ``caveat_reasons`` (why a caveat is null). ``promotion_countable`` is derived (A3). The list must
    end at the 45th countable date. Checking it against MG1_LAST is the look's job, not the writer's.
    """
    if Path(path).exists():
        raise MG1LookRefused(f"{path} already exists: the countable-date list is written once")
    rows = []
    for r in dates:
        row = {"date": str(r["date"]), "markets": {str(k): v for k, v in dict(r["markets"]).items()},
               "parser_v2_verified": r.get("parser_v2_verified"),
               "shadow_stage_captured": r.get("shadow_stage_captured")}
        row["promotion_countable"] = any(v is True for v in row["markets"].values())
        if r.get("caveat_reasons"):
            row["caveat_reasons"] = dict(r["caveat_reasons"])
        rows.append(row)
    body = {"schema": COUNTABLE_SCHEMA, "dates": rows}
    _parse_countable(json.loads(json.dumps(body)))
    _write_x(path, body)
    return sha256_file(path)


def market_day_flags(rows):
    """{(date iso, market): promotion_countable} over the counted dates (the A3 mask)."""
    return {(r["date"].isoformat(), m): flag for r in rows if r["countable"] for m, flag in r["markets"].items()}


def settled_at(last_date, markets=None):
    """The latest market-local midnight after the 45th date over the scored markets (A4's first half)."""
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    day = last_date + timedelta(days=1)
    return max(datetime.combine(day, dtime(0), ZoneInfo(MARKET_TZ[m])).astimezone(timezone.utc)
               for m in (markets or support_markets()))


def read_freeze_receipt(path, last_date, settled):
    """A4's second half and A2's source: the R24 look-morning label freeze, checked by file hashes only.

    The receipt (``venue_label_freeze_receipt_v1``, ``freeze --look mg1``) must:

    - exist and be for this look;
    - run through the 45th date;
    - have been frozen after that date ended in every scored market;
    - give, for every scored market, the frozen label CSV, manifest and WU daily summary at their recorded sha256
      (both copies matching their manifest).

    The files sit under the receipt's own folder in the label reader's ``label_root`` layout. No label value is
    read here.
    """
    p = Path(path) if path else None
    if p is None or not p.is_file():
        raise MG1LookRefused(f"the R24 label freeze receipt {path} does not exist: the look waits for it (A4)")
    try:
        receipt = json.loads(p.read_text(encoding="utf-8"))
        through = date.fromisoformat(str(receipt["through"]))
        frozen = datetime.fromisoformat(str(receipt["frozen_at_utc"]).replace("Z", "+00:00"))
        entries = receipt["markets"]
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise MG1LookRefused(f"the label freeze receipt is unreadable: {exc}") from exc
    if receipt.get("schema_version") != FREEZE_RECEIPT_SCHEMA or receipt.get("look_id") != FREEZE_LOOK_ID:
        raise MG1LookRefused(f"the label freeze receipt is not a {FREEZE_RECEIPT_SCHEMA} freeze for look "
                             f"{FREEZE_LOOK_ID!r}")
    if through < last_date:
        raise MG1LookRefused(f"the label freeze runs through {through}, before the 45th date {last_date}")
    if frozen.tzinfo is None or frozen < settled:
        raise MG1LookRefused(f"the labels were frozen at {frozen.isoformat()}, before the 45th date ended in every "
                             f"scored market ({settled.isoformat()})")
    root = p.parent
    files = {}
    for market in support_markets():
        entry = entries.get(market) if isinstance(entries, dict) else None
        if not isinstance(entry, dict):
            raise MG1LookRefused(f"the label freeze has no entry for {market}")
        if not (entry.get("label_csv_matches_manifest") is True and entry.get("wu_daily_summary_matches_manifest")
                is True):
            raise MG1LookRefused(f"the frozen {market} label files do not match their manifest")
        local = {"label_csv": root / market / "daily" / "daily_summary.csv",
                 "manifest": root / market / "manifest.json",
                 "wu_daily_summary": root / market / "wu" / "daily_summary.csv"}
        for name in FREEZE_FILES:
            want = (entry.get(name) or {}).get("sha256")
            if not want or not local[name].is_file() or sha256_file(local[name]) != want:
                raise MG1LookRefused(f"the frozen {market} {name} is missing or differs from the freeze receipt")
        files[market] = local
    return {"path": str(p), "sha256": sha256_file(p), "through": through.isoformat(),
            "frozen_at_utc": frozen.isoformat(), "files": files}


def read_inputs(layout_root, rows):
    """The label-free snapshots and bands of the countable market-days (no label or price is opened).

    Non-countable market-days are dropped here, before any join (A3, R11 (2)). A countable market-day with no
    layout rows is a hole, which holds the look before ``looked_at_utc`` is stamped (key-only; nothing is
    consumed).
    """
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    root = Path(layout_root)
    snaps = pd.read_parquet(root / data.SNAPSHOTS_FILE)
    bands = pd.read_parquet(root / data.BANDS_FILE)
    data.screen_inputs(snaps, bands)
    flags = market_day_flags(rows)
    keys = list(zip(snaps.date.astype(str), snaps.market.astype(str)))
    snaps = snaps[[flags.get(k) is True for k in keys]].reset_index(drop=True)
    if snaps.row_key.duplicated().any():
        raise MG1LookRefused("the layout repeats a row_key")
    present = set(zip(snaps.date.astype(str), snaps.market.astype(str)))
    holes = sorted(k for k, flag in flags.items() if flag and k not in present)
    if holes:
        raise MG1LookHeld(f"held: {len(holes)} countable market-days have no layout rows (first {holes[0]}); "
                          "nothing was consumed (A3 hole check)")
    bands = bands[bands.row_key.isin(set(snaps.row_key))].reset_index(drop=True)
    mask = {"countable_market_days": sum(1 for f in flags.values() if f),
            "masked_market_days": sum(1 for f in flags.values() if not f)}
    return snaps, bands, {"snapshots_sha256": sha256_file(root / data.SNAPSHOTS_FILE),
                          "bands_sha256": sha256_file(root / data.BANDS_FILE), "market_day_mask": mask}


def _table(snaps, bands, labels, market):
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    layout = data.Layout(snaps=snaps, bands=bands, labels=labels, market=market, manifest_sha256="mg1-look",
                         file_sha256={}, label_source="mg1 look outcomes")
    return sc.Table(layout, sorted(set(snaps.date.astype(str))))


def _placeholder_outcomes(snaps, bands):
    """Outcome-free stand-ins (winner 0, price 0) so the scorecard's ``candidate_vector`` can give its fallback
    reasons before any outcome is read; those reasons depend on no label or price. Never scored."""
    import pandas as pd

    labels = pd.DataFrame({"row_key": snaps.row_key.to_numpy(), "winner": 0})
    market = pd.DataFrame({"row_key": bands.row_key.to_numpy(), "band_index": bands.band_index.to_numpy(int),
                           "p_market_yes": 0.0})
    return labels, market


def mg1_vector(snaps, bands):
    """MG-1's raw band vector (``free_source_candidates.mg1.predict``, the receipted ``mg1.py``)."""
    from weather.reporting.scorecards.free_source_candidates import mg1

    return mg1.predict(snaps, bands)


def outcome_blind_checks(snaps, bands, frame, shadow=None, absence=None):
    """Section 6's VOID conditions that read no outcome, the A6 status count, and the fallback reasons (counts and
    per row_key)."""
    import numpy as np
    import pandas as pd

    table = _table(snaps, bands, *_placeholder_outcomes(snaps, bands))
    _, reasons_by = _reasons(table, frame)
    used = reasons_by == "candidate"
    h = table.local_hour
    morning = (h >= PRIMARY[1]) & (h <= PRIMARY[2])
    coverage = float(used[morning].mean()) if morning.any() else 0.0
    s = table.snaps
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(s.captured_at_utc, utc=True, errors="coerce")
    after = ~(avail <= cap).fillna(False).to_numpy(bool)
    period = (s.v2_period_kind.astype(str) != "maximum").to_numpy(bool) if "v2_period_kind" in s else \
        np.ones(len(s), bool)
    status = (s.v2_status.astype(str) != "available").to_numpy(bool) if "v2_status" in s else np.ones(len(s), bool)
    finite_v2 = (np.isfinite(pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float))
                 & np.isfinite(pd.to_numeric(s.v2_stddev, errors="coerce").to_numpy(float)))
    checks = {
        "coverage": {"pass": coverage >= COVERAGE_MIN, "share_00_16": coverage,
                     "snapshots_00_16": int(morning.sum()), "used_00_16": int((used & morning).sum())},
        # A6 (a): counted on the snapshots MG-1 actually used; the finite-v2 rows it rejected as unavailable at
        # capture are disclosed, not voided. A used row whose v2_status is not "available" holds the look before
        # the join (``score``), with this count only; master rules from it.
        "pit": {"pass": int((used & after).sum()) == 0 and int((used & period).sum()) == 0,
                "used_available_after_capture": int((used & after).sum()),
                "used_period_not_maximum": int((used & period).sum()),
                "disclosed_finite_v2_available_after_capture": int((finite_v2 & after).sum()),
                "used_status_not_available": int((used & status).sum()),
                "status_column": "v2_status" in s},
    }
    if "v2_parser_version" in s:
        bad = int((used & (pd.to_numeric(s.v2_parser_version, errors="coerce").to_numpy(float) != PARSER_VERSION))
                  .sum())
        checks["parser"] = {"pass": bad == 0, "used_parser_not_2": bad, "status": "checked"}
    else:
        checks["parser"] = {"pass": False, "used_parser_not_2": None, "status": "no v2_parser_version column"}
    checks["replay"] = replay_check(frame, shadow)
    # A7 (b): no code can prove the absence of an earlier outcome join. Master attests it in the look log, and the
    # look records that neither its start marker nor its receipt existed when it began.
    checks["window_leakage"] = {"pass": True, "status": "attested in the look log by master; not provable in code",
                                "marker_and_receipt_absent_at_start": absence}
    reasons = {str(k): int(v) for k, v in zip(*np.unique(reasons_by, return_counts=True))}
    return checks, reasons, dict(zip(s.row_key.astype(str), reasons_by))


def _reasons(table, frame):
    """The scorecard vector (rule-4 floor mask, renormalise, served fallback) and each snapshot's reason."""
    import numpy as np

    p, _ = table.candidate_vector(frame)
    given = set(frame.row_key)
    has = np.array([k in given for k in table.snaps.row_key], bool)
    total = np.zeros(len(table.snaps))
    if len(frame):
        pos = table.snap_pos.reindex(frame.row_key.to_numpy()).to_numpy().astype(int)
        flat = np.full(len(table.bands), 0.0)
        flat[table.offsets[pos] + frame.band_index.to_numpy(int)] = frame.p.to_numpy(float)
        flat[table.impossible] = 0.0
        total = np.bincount(table.band_snap, weights=flat, minlength=len(table.snaps))
    reason = np.where(~has, "absent", np.where(~table.has_floor, "missing_floor",
                                                np.where(total > 0, "candidate", "zero_mass_after_floor")))
    return p, reason.astype(object)


def replay_check(frame, shadow):
    """Section 6 replay: the captured shadow vector equals MG-1 recomputed from the stored inputs to 1e-12.

    PROVISIONAL (A8): with no captured shadow vector (Clarification 1 sets aside section 3 (c), so its capture is
    a reporting caveat) the check is reported as not applicable and does not void.
    """
    import numpy as np
    import pandas as pd

    if shadow is None:
        return {"pass": True, "status": "not applicable: no captured shadow vector (Clarification 1 section 2)"}
    a = frame.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    b = pd.read_parquet(shadow, columns=["row_key", "band_index", "p"]).sort_values(
        ["row_key", "band_index"]).reset_index(drop=True)
    same = (len(a) == len(b) and (a.row_key.to_numpy() == b.row_key.to_numpy()).all()
            and (a.band_index.to_numpy() == b.band_index.to_numpy()).all())
    diff = float(np.abs(a.p.to_numpy(float) - b.p.to_numpy(float)).max()) if same and len(a) else (
        0.0 if same else math.inf)
    return {"pass": bool(same and diff <= REPLAY_TOLERANCE), "status": "checked", "max_abs": diff,
            "same_keys": bool(same), "shadow_sha256": sha256_file(shadow)}


def winner_band(bands_of_snapshot, bucket):
    """The band index holding the integer native label bucket (lte: k <= high; gte: k >= low; else low..high)."""
    hits = []
    for kind, low, high, index in bands_of_snapshot:
        if kind == "lte":
            inside = bucket <= high
        elif kind == "gte":
            inside = bucket >= low
        else:
            inside = low <= bucket <= high
        if inside:
            hits.append(int(index))
    if len(hits) != 1:
        raise MG1LookRefused(f"a label bucket falls in {len(hits)} bands of its snapshot's ladder, not one")
    return hits[0]


def load_venue_labels(freeze, snaps, read_through):
    """A2 (b): the venue labels of the scored market-days, read only from the R24 frozen copy.

    The labels come through ``read_venue_labels`` with ``read_through`` set to the 45th date and
    ``allow_reserved_window=True``. Denver is read with ``model_scoring=False`` when A1 keeps it in (KDEN from the
    cutover). Returns ``{(date iso, market): label_bucket}`` and ``{(date iso, market): refusal reason}``.
    """
    from weather.backtesting.venue_label_reader import read_venue_labels

    buckets, refusals = {}, {}
    for market in support_markets():
        days = sorted(set(snaps.date.astype(str)[snaps.market.astype(str) == market]))
        if not days:
            continue
        files = freeze["files"][market]
        records, refused = read_venue_labels(
            market, days, read_through=read_through, allow_reserved_window=True,
            model_scoring=market != "denver", label_root=Path(freeze["path"]).parent,
            wu_daily_summary=files["wu_daily_summary"], venue_label_csv=files["label_csv"])
        if set(records) | set(refused) != set(days) or set(records) & set(refused):
            raise MG1LookRefused(f"the label reader did not answer every {market} date exactly once")
        buckets.update({(d, market): int(r["label_bucket"]) for d, r in records.items()})
        refusals.update({(d, market): str(reason) for d, reason in refused.items()})
    return buckets, refusals


def load_outcomes(freeze, market, snaps, bands, read_through):
    """The look's only outcome read (called through ``Look.join_outcomes``): venue labels and capture-time prices.

    Labels: ``load_venue_labels`` on the frozen copy, with each label bucket mapped to its snapshot's band index.
    A market-day the reader refuses is masked: its snapshots are dropped and the refusal is disclosed, never a
    VOID (T2).

    Prices: ``row_key, band_index, p_market_yes``. A snapshot is priced when every band has a finite price.
    Unpriced snapshots stay in the primary, which reads no price, and are left out of only the market-relative
    quantities (A9 (a); the priced share is disclosed).

    Returns ``(labels, prices, priced, shas, keep, masked)``. ``keep`` is the boolean over ``snaps`` of the
    snapshots still scored.
    """
    import numpy as np
    import pandas as pd

    buckets, refusals = load_venue_labels(freeze, snaps, read_through)
    keys = list(zip(snaps.date.astype(str), snaps.market.astype(str)))
    keep = np.array([k in buckets for k in keys], bool)
    kept = snaps[keep]
    ladder = {}
    for row in bands[bands.row_key.isin(set(kept.row_key))].itertuples(index=False):
        ladder.setdefault(row.row_key, []).append((str(row.kind), row.low, row.high, row.band_index))
    lab = pd.DataFrame({"row_key": kept.row_key.to_numpy(),
                        "winner": [winner_band(ladder.get(rk, []), buckets[(d, mk)])
                                   for rk, d, mk in zip(kept.row_key, kept.date.astype(str), kept.market.astype(str))]})
    mkt = pd.read_parquet(market, columns=["row_key", "band_index", "p_market_yes"])
    shas = {"label_freeze_receipt_sha256": freeze["sha256"], "market_sha256": sha256_file(market)}
    kept_bands = bands[bands.row_key.isin(set(kept.row_key))].reset_index(drop=True)
    price = mkt.set_index(["row_key", "band_index"]).p_market_yes
    if price.index.duplicated().any():
        raise MG1LookRefused("the capture-time prices repeat a (row_key, band_index)")
    p = price.reindex(pd.MultiIndex.from_arrays([kept_bands.row_key, kept_bands.band_index])).to_numpy(float)
    ok = pd.Series(np.isfinite(p), index=kept_bands.row_key.to_numpy()).groupby(level=0).all()
    priced = ok.reindex(kept.row_key).fillna(False).to_numpy(bool)
    filled = pd.DataFrame({"row_key": kept_bands.row_key.to_numpy(), "band_index": kept_bands.band_index.to_numpy(int),
                           "p_market_yes": np.where(np.isfinite(p), p, 0.0)})
    masked = {"market_days": len(refusals), "snapshots": int((~keep).sum()),
              "by_reason": {r: sum(1 for v in refusals.values() if v == r) for r in sorted(set(refusals.values()))},
              "market_days_masked": sorted(f"{d}:{mk}" for d, mk in refusals)}
    return lab, filled, priced, shas, keep, masked


def _fixed_weights(table):
    from weather.reporting.scorecards import dev_scorecard as sc

    dates = [k[0] for k in table.keys]
    return sc.crossed_weights(dates, ["all"] * len(dates), draws=DRAWS, seed=SEED)


def _interval(w, values):
    import numpy as np

    from weather.reporting.scorecards import dev_scorecard as sc

    return sc.ratio_interval(w, values, np.ones(len(values)))


def _contrast(table, wf, a, b, mask):
    """a - b over equal (date, market) cells on ``mask``: fixed-market (seed 20261004) and crossed intervals."""
    idx, ca = table.cells(a, mask)
    _, cb = table.cells(b, mask)
    if not len(idx):
        return None
    d = ca - cb
    return {"n_snapshots": int(mask.sum()), "n_market_days": int(len(idx)),
            "n_dates": len({table.keys[i][0] for i in idx}), "mean_a": float(ca.mean()), "mean_b": float(cb.mean()),
            "fixed_market": _interval(wf[:, idx], d), "crossed": _interval(table.w[:, idx], d)}


def _per_market(table, a, b, mask):
    out = {}
    for market in support_markets():
        idx, ca = table.cells(a, mask & (table.markets == market))
        _, cb = table.cells(b, mask & (table.markets == market))
        out[market] = {"n_market_days": int(len(idx)), "mean_delta": float((ca - cb).mean()) if len(idx) else None}
    return out


def _above_0(row):
    low = None if row is None else row["fixed_market"]["ci95"][0]
    return bool(low is not None and low > 0)


def _mask(table, lo, hi):
    return (table.local_hour >= lo) & (table.local_hour <= hi)


def tail_lens(table, p_mg1, mask):
    """EF tail lens on the window's own band rows: served SE > market SE and |p_served - p_market| >= 0.30."""
    import numpy as np

    sel = mask[table.band_snap]
    se_s, se_m = (table.p_served - table.y) ** 2, (table.p_market - table.y) ** 2
    se_c = (p_mg1 - table.y) ** 2
    tail = sel & (se_s > se_m) & (np.abs(table.p_served - table.p_market) >= TAIL_GAP)
    excess = np.clip(se_s - se_m, 0.0, None)
    total = float(excess[sel].sum())
    return {"definition": "band rows with served SE > market SE and |p_served - p_market| >= 0.30 (EF 10)",
            "band_rows": int(sel.sum()), "tail_rows": int(tail.sum()),
            "tail_share": float(tail.sum() / sel.sum()) if sel.any() else None,
            "tail_share_of_positive_excess": float(excess[tail].sum() / total) if total > 0 else None,
            "mg1_minus_served_se_tail": float((se_c - se_s)[tail].sum()),
            "mg1_minus_served_se_non_tail": float((se_c - se_s)[sel & ~tail].sum())}


def materiality_bar(gap):
    """Section 4: estimate <= -5% of the window's own 00-16 served - market gap. A5 (owner question, open):
    ``as_written`` uses the gap's sign, so a gap <= 0 makes the bar >= 0; ``magnitude`` uses |gap|."""
    if gap is None:
        return None
    return -MATERIALITY * (abs(gap) if owner_constants()["A5_BAR"] == "magnitude" else gap)


def crossed_disagrees(est, crossed):
    """Falsifier 4. A12 (owner question, open): ``point`` compares the crossed point estimate's sign with the
    fixed-market one. Under equal-cell weights the two are the same mean, so this cannot fire. ``interval`` fires
    when the crossed 95% interval lies entirely on the other side of 0 from the fixed-market estimate."""
    if isinstance(crossed, dict):
        c_est, c_ci = crossed.get("estimate"), crossed.get("ci95") or [None, None]
    else:
        c_est, c_ci = crossed, [None, None]
    if owner_constants()["A12_FALSIFIER_4"] == "interval":
        c_low, c_up = c_ci
        return bool(est != 0 and c_low is not None and c_up is not None
                    and ((est < 0 and c_low > 0) or (est > 0 and c_up < 0)))
    return bool(c_est is not None and (c_est > 0) != (est > 0) and est != 0)


def decide(primary, per_market, gap, crossed):
    """Section 4's pass rule and section 6's falsifiers 1-4 on the primary (no VOID here). ``crossed`` is the
    crossed row ({estimate, ci95}) or its point estimate."""
    est, (low, up) = primary["estimate"], primary["ci95"]
    negative = sorted(m for m, r in per_market.items() if r["mean_delta"] is not None and r["mean_delta"] < 0)
    bar = materiality_bar(gap)
    conditions = {"upper_bound_below_0": up is not None and up < 0,
                  "markets_negative": len(negative) >= MIN_NEGATIVE_MARKETS,
                  "material": bar is not None and est <= bar}
    falsifiers = []
    if est >= 0 or up is None or up >= 0:
        falsifiers.append("1 route closed")
    if not conditions["material"]:
        falsifiers.append("2 immaterial")
    if not conditions["markets_negative"]:
        falsifiers.append("3 not fleet-wide")
    if crossed_disagrees(est, crossed):
        falsifiers.append("4 crossed disagreement")
    verdict = "PASS" if all(conditions.values()) and "4 crossed disagreement" not in falsifiers else "NOT_PASS"
    return {"verdict": verdict, "estimate": est, "ci95": [low, up], "conditions": conditions,
            "markets_negative": negative, "n_markets_negative": len(negative), "materiality_bar": bar,
            "served_minus_market_gap_00_16": gap, "falsifiers": falsifiers}


def score_rows(table, p_mg1, used, priced, segments=()):
    """The primary, the decision inputs and every section 4 reported quantity."""
    import numpy as np

    wf = _fixed_weights(table)
    b_c, b_s, b_m = table.brier(p_mg1), table.brier(table.p_served), table.brier(table.p_market)
    morning = _mask(table, PRIMARY[1], PRIMARY[2])
    primary = _contrast(table, wf, b_c, b_s, morning)
    per_market = _per_market(table, b_c, b_s, morning)
    gap_row = _contrast(table, wf, b_s, b_m, morning & priced)
    gap = None if gap_row is None else gap_row["fixed_market"]["estimate"]
    decision = decide(primary["fixed_market"], per_market, gap, primary["crossed"])
    reported = {}
    for name, lo, hi in REPORTED_GROUPS:
        row = _contrast(table, wf, b_c, b_s, _mask(table, lo, hi))
        if row is not None and name == KNOWN_COST:
            row["label"] = "known development cost (section 1), never a gate"
        reported[name] = row
    harm = {"all_hours_interval_above_0": _above_0(reported["all"]),
            "evening_17_23_interval_above_0": _above_0(reported["17-23"])}
    decision["falsifier_5"] = {"no_all_row_serving_proposal": harm["all_hours_interval_above_0"],
                               "evening_harm": harm["evening_17_23_interval_above_0"],
                               "note": "no hour gate may be added post hoc (section 6)"}
    matched = _contrast(table, wf, b_c, b_s, morning & used)
    if matched is not None:
        matched["label"] = "selected on availability"
    market_rel = {}
    for name, lo, hi in (PRIMARY,) + REPORTED_GROUPS:
        mask = _mask(table, lo, hi) & priced
        idx, c = table.cells(b_c, mask)
        if not len(idx):
            continue
        _, s = table.cells(b_s, mask)
        _, m = table.cells(b_m, mask)
        market_rel[name] = {"n_market_days": int(len(idx)), "brier_market": float(m.mean()),
                            "ratio_mg1_to_market": float(c.sum() / m.sum()) if m.sum() > 0 else None,
                            "ratio_served_to_market": float(s.sum() / m.sum()) if m.sum() > 0 else None,
                            "mg1_minus_market": _interval(wf[:, idx], c - m)}
    seg = {}
    for change in segments:  # section 2: pre/post segments for a serving change inside the window
        day = np.array([k >= change.isoformat() for k in table.snaps.date.astype(str)], bool)
        seg[change.isoformat()] = {"pre": _contrast(table, wf, b_c, b_s, morning & ~day),
                                   "post": _contrast(table, wf, b_c, b_s, morning & day)}
    return {"primary": primary, "decision": decision, "per_market": per_market, "reported": reported,
            "matched_rows": matched, "market_relative": market_rel,
            "tail_lens_00_16": tail_lens(table, p_mg1, morning & priced), "serving_change_segments": seg,
            "priced_snapshot_share": float(priced.mean()) if len(priced) else None}


def served_releases(snaps):
    """Section 4 reported: served release ids (the first release column the layout carries)."""
    for column in SERVED_RELEASE_COLUMNS:
        if column in snaps:
            counts = snaps[column].astype(str).value_counts()
            return {"column": column, "counts": {str(k): int(v) for k, v in counts.items()}}
    return {"column": None, "counts": {}, "status": "the layout carries no served release column"}


def _verdict(checks, decision):
    voids = sorted(k for k in VOID_CONDITIONS if not checks[k]["pass"])
    if voids:
        return {"verdict": "VOID", "conditions": voids, "reasons": {k: VOID_CONDITIONS[k] for k in voids},
                "note": "no pass and no fail; the dates are spent and are not re-run (section 6)"}
    return decision


def score(*, rule, layout_root, countable, label_freeze, market, out, shadow=None, serving_changes=(), now=None,
          root=None):
    """The single MG-1 look. Refusals and holds before the first outcome join read no label or price and spend
    nothing."""
    import pandas as pd

    owners = owner_constants()
    look = Look(rule)
    counted, rows = read_countable(countable)
    now = now or _now_utc()
    _, last = window.window()
    if now.date() <= last:
        raise MG1LookRefused(f"the recorded MG-1 window (last {last}) has not closed")
    settled = settled_at(counted[-1])
    if now < settled:
        raise MG1LookRefused(f"the 45th countable date {counted[-1]} has not ended in every scored market "
                             f"(until {settled.isoformat()})")
    freeze = read_freeze_receipt(label_freeze, counted[-1], settled)  # A4: finality and the R24 freeze
    out = Path(out)
    result = out / RESULT
    if result.exists():
        raise MG1LookRefused(f"{result} already exists: MG-1 has exactly one look")
    changes = sorted({date.fromisoformat(str(d)) for d in serving_changes})
    snaps, bands, input_shas = read_inputs(layout_root, rows)  # A3 mask and hole check (a hole holds)
    frame = mg1_vector(snaps, bands)
    checks, reasons, reason_of = outcome_blind_checks(snaps, bands, frame, shadow, look.absence)
    bad_status = checks["pit"]["used_status_not_available"]
    if bad_status:
        raise MG1LookHeld(f"held: {bad_status} used rows have a v2_status other than \"available\"; nothing was "
                          "consumed (A6)")
    base = {"schema": RESULT_SCHEMA, "mg1_rule_sha256": look.rule_sha256, "entry_sha256": module_sha256(),
            "owner_constants": owners,
            "counted_dates": {"count": len(counted), "first": counted[0].isoformat(),
                              "last": counted[-1].isoformat()},
            "not_countable": [r["date"].isoformat() for r in rows if not r["countable"]],
            "clarification_1_caveats": {r["date"].isoformat(): {"parser_v2_verified": r["parser_v2_verified"],
                                                                "shadow_stage_captured": r["shadow_stage_captured"],
                                                                **({"reasons": r["caveat_reasons"]}
                                                                   if r["caveat_reasons"] else {})}
                                        for r in rows if r["countable"]},
            "inputs": {**input_shas, "countable_sha256": sha256_file(countable),
                       "label_freeze": {k: freeze[k] for k in ("path", "sha256", "through", "frozen_at_utc")},
                       "mg1_frame_rows": int(len(frame))},
            "markets": list(support_markets()), "outcome_blind_checks": checks, "coverage_reasons": reasons,
            "served_releases": served_releases(snaps), "serving_changes": [d.isoformat() for d in changes],
            "outcomes_opened": False}
    finish = {"dates": [d.isoformat() for d in counted], "root": root,
              "label_freeze_receipt_sha256": freeze["sha256"]}
    try:
        lab, mkt, priced, shas, keep, masked = look.join_outcomes(load_outcomes, freeze, market, snaps, bands,
                                                                  counted[-1])
        base["outcomes_opened"] = True
        base["inputs"].update(shas)
        base["label_masked"] = masked  # T2: refused labels mask their market-day, never a VOID
        kept = snaps[keep].reset_index(drop=True)
        kept_bands = bands[bands.row_key.isin(set(kept.row_key))].reset_index(drop=True)
        table = _table(kept, kept_bands, lab, mkt)
        p, reason = _reasons(table, frame[frame.row_key.isin(set(kept.row_key))])
        if [reason_of[str(k)] for k in table.snaps.row_key] != list(reason):
            raise MG1LookRefused("the fallback reasons changed once outcomes were joined")
        priced = pd.Series(priced, index=kept.row_key.to_numpy()).reindex(table.snaps.row_key).to_numpy(bool)
        rows_out = score_rows(table, p, reason == "candidate", priced, changes)
        payload = {**base, **rows_out, "decision": _verdict(checks, rows_out["decision"])}
    except BaseException as exc:
        if look.looked_at_utc is None:
            raise
        payload = {**base, "decision": {"verdict": "ABORTED", "error": f"{type(exc).__name__}: {exc}"}}
        _write_result(result, payload)
        look.finish(result=result, **finish)
        raise
    _write_result(result, payload)
    return look.finish(result=result, **finish), payload


def _write_result(path, payload):
    from weather.reporting.scorecards import dev_scorecard as sc

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(sc.canonical_bytes(payload))


def build_parser():
    parser = argparse.ArgumentParser(prog=f"python -m {MODULE}", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-receipt", help="run B-1 VOID 5's receipt checks on a receipt (reads no outcome)")
    check.add_argument("--receipt", required=True)
    run = sub.add_parser("run", help="the single MG-1 look (pre-registration sections 4 and 6)")
    run.add_argument("--rule", required=True, help="the signed MG-1 pre-registration")
    run.add_argument("--layout", required=True, help="the label-free window layout (snapshots and bands)")
    run.add_argument("--countable", required=True, help=f"the {COUNTABLE_SCHEMA} countable-date list")
    run.add_argument("--label-freeze", required=True,
                     help="the R24 freeze receipt (frozen/mg1/freeze_receipt.json); labels are read only at the join")
    run.add_argument("--market", required=True, help="capture-time prices; read only at the join")
    run.add_argument("--out", required=True)
    run.add_argument("--shadow", help="the captured nbm_v2_guidance_read_v1 shadow vector, when it exists")
    run.add_argument("--serving-change", action="append", default=[], help="a serving-change date (section 2)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "check-receipt":
        problems = receipt_problems(args.receipt)
        print(json.dumps({"receipt": args.receipt, "problems": problems}, indent=1))
        return 1 if problems else 0
    try:
        path, payload = score(rule=args.rule, layout_root=args.layout, countable=args.countable,
                              label_freeze=args.label_freeze, market=args.market, out=args.out, shadow=args.shadow,
                              serving_changes=args.serving_change)
    except MG1LookRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"receipt": str(path), "decision": payload["decision"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
