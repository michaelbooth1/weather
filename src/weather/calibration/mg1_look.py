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

The MG-1 scoring (pre-registration sections 4 and 6, Clarification 1) is ``score``, run by ``main run``. Its
sha256 is re-registered in ``MG1_CONFIRMATION_ENTRY_POINTS`` by a reviewed edit. ``score`` reads, in this order:
the rule, the countable-date list, the label-free layout (snapshots and bands; ``screen_inputs`` refuses any label
or price column); it builds the MG-1 vector (``free_source_candidates.mg1.predict``, whose sha the receipt records)
and runs every outcome-blind VOID check; only then does ``join_outcomes`` read the labels and capture-time prices.
Every exit after that first join writes the result and the receipt (a verdict, a VOID, or ABORTED).
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
                  "completed_at_utc", "result", "mg1_py_sha256", "repo_commit", "host", "body_sha256")


class MG1LookRefused(RuntimeError):
    """The MG-1 look refused before reading anything, or its receipt cannot be written."""


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

    def finish(self, *, result, dates, root=None):
        """Write the receipt (mode "x") at the fixed path for the rule and return its path."""
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
                   "host": socket.gethostname()}
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
# Section 4 "US11", section 7 "the fixed 11-market support". PROVISIONAL (A1): the pre-registration never lists
# them; these are B-1's ten plus Denver, which settles on KDEN from 2026-10-23 while MG-1 reads KBKF guidance.
MARKETS = ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
           "san-francisco", "seattle")
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


def read_countable(path):
    """The counted dates (section 3, Clarification 1 sections 1-3) and the per-date reporting caveats.

    ``mg1_countable/1``: ``{"schema", "dates": [{"date", "promotion_countable", "parser_v2_verified",
    "shadow_stage_captured"}]}``, written by master (who owns the countability check), one row per calendar date
    from D0 through the 45th countable date. No label or price is in it. PROVISIONAL (A3): its source and format.
    """
    body = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(body, dict) or body.get("schema") != COUNTABLE_SCHEMA:
        raise MG1LookRefused(f"the countable-date list is not {COUNTABLE_SCHEMA}")
    try:
        rows = [{"date": date.fromisoformat(str(r["date"])), "countable": r["promotion_countable"],
                 "parser_v2_verified": r["parser_v2_verified"], "shadow_stage_captured": r["shadow_stage_captured"]}
                for r in body["dates"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise MG1LookRefused(f"the countable-date list is malformed: {exc}") from exc
    if any(not isinstance(r["countable"], bool) for r in rows):
        raise MG1LookRefused("promotion_countable must be true or false on every date")
    for key in ("parser_v2_verified", "shadow_stage_captured"):
        if any(r[key] not in (True, False, None) for r in rows):
            raise MG1LookRefused(f"{key} must be true, false or null on every date")
    start, last = window.window()
    if last is None:
        raise MG1LookRefused("the MG-1 window is not recorded: there is no 45th date to count to")
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
    if counted[-1] > last:  # MG1_LAST may only move later, and must move before a later date is scored
        raise MG1LookRefused(f"the 45th countable date {counted[-1]} is after the recorded MG1_LAST {last}: "
                             "the window must be extended first")
    return counted, rows


def settled_at(last_date):
    """The latest US11 market-local midnight after the 45th date. PROVISIONAL (A4): "has settled" read as "has
    ended in every market"; the labels' own availability is checked when they are joined."""
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    day = last_date + timedelta(days=1)
    return max(datetime.combine(day, dtime(0), ZoneInfo(MARKET_TZ[m])).astimezone(timezone.utc) for m in MARKETS)


def read_inputs(layout_root, counted):
    """The label-free snapshots and bands on the counted dates and US11 markets (no label or price is opened)."""
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    root = Path(layout_root)
    snaps = pd.read_parquet(root / data.SNAPSHOTS_FILE)
    bands = pd.read_parquet(root / data.BANDS_FILE)
    data.screen_inputs(snaps, bands)
    keep = {d.isoformat() for d in counted}
    snaps = snaps[snaps.market.astype(str).isin(MARKETS) & snaps.date.astype(str).isin(keep)].reset_index(drop=True)
    if snaps.row_key.duplicated().any():
        raise MG1LookRefused("the layout repeats a row_key")
    bands = bands[bands.row_key.isin(set(snaps.row_key))].reset_index(drop=True)
    return snaps, bands, {"snapshots_sha256": sha256_file(root / data.SNAPSHOTS_FILE),
                          "bands_sha256": sha256_file(root / data.BANDS_FILE)}


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


def outcome_blind_checks(snaps, bands, frame, shadow=None):
    """Section 6's VOID conditions that read no outcome, plus the coverage and fallback reasons."""
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
        # PROVISIONAL (A6): counted on the snapshots MG-1 actually used; the finite-v2 rows it rejected as
        # unavailable at capture are disclosed, not voided.
        "pit": {"pass": int((used & after).sum()) == 0 and int((used & period).sum()) == 0,
                "used_available_after_capture": int((used & after).sum()),
                "used_period_not_maximum": int((used & period).sum()),
                "disclosed_finite_v2_available_after_capture": int((finite_v2 & after).sum()),
                "disclosed_used_status_not_available": int((used & status).sum())},
    }
    if "v2_parser_version" in s:
        bad = int((used & (pd.to_numeric(s.v2_parser_version, errors="coerce").to_numpy(float) != PARSER_VERSION))
                  .sum())
        checks["parser"] = {"pass": bad == 0, "used_parser_not_2": bad, "status": "checked"}
    else:
        checks["parser"] = {"pass": False, "used_parser_not_2": None, "status": "no v2_parser_version column"}
    checks["replay"] = replay_check(frame, shadow)
    # PROVISIONAL (A7): no code can prove the absence of an earlier outcome join; master attests it in the look log.
    checks["window_leakage"] = {"pass": True, "status": "attested in the look log by master; not provable in code"}
    reasons = {str(k): int(v) for k, v in zip(*np.unique(reasons_by, return_counts=True))}
    return checks, reasons


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


def load_outcomes(labels, market, snaps, bands):
    """The look's only outcome read (called through ``Look.join_outcomes``): venue labels and capture-time prices.

    Labels: ``row_key, winner`` for every scored snapshot. Prices: ``row_key, band_index, p_market_yes``; a
    snapshot is priced when every band has a finite price. PROVISIONAL (A2, A9): their source, and that unpriced
    snapshots stay in the primary (which reads no price) and leave only the market-relative quantities.
    """
    import numpy as np
    import pandas as pd

    lab = pd.read_parquet(labels, columns=["row_key", "winner"])
    mkt = pd.read_parquet(market, columns=["row_key", "band_index", "p_market_yes"])
    shas = {"labels_sha256": sha256_file(labels), "market_sha256": sha256_file(market)}
    lab = lab[lab.row_key.isin(set(snaps.row_key))]
    if lab.row_key.duplicated().any():
        raise MG1LookRefused("the labels repeat a row_key")
    missing = int((~snaps.row_key.isin(set(lab.row_key))).sum())
    if missing:
        raise MG1LookRefused(f"{missing} scored snapshots have no label")
    price = mkt.set_index(["row_key", "band_index"]).p_market_yes
    p = price.reindex(pd.MultiIndex.from_arrays([bands.row_key, bands.band_index])).to_numpy(float)
    ok = pd.Series(np.isfinite(p), index=bands.row_key.to_numpy()).groupby(level=0).all()
    priced = ok.reindex(snaps.row_key).fillna(False).to_numpy(bool)
    filled = pd.DataFrame({"row_key": bands.row_key.to_numpy(), "band_index": bands.band_index.to_numpy(int),
                           "p_market_yes": np.where(np.isfinite(p), p, 0.0)})
    return lab, filled, priced, shas


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
    for market in MARKETS:
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


def decide(primary, per_market, gap, crossed_estimate):
    """Section 4's pass rule and section 6's falsifiers 1-4 on the primary (no VOID here)."""
    est, (low, up) = primary["estimate"], primary["ci95"]
    negative = sorted(m for m, r in per_market.items() if r["mean_delta"] is not None and r["mean_delta"] < 0)
    bar = None if gap is None else -MATERIALITY * gap  # PROVISIONAL (A5): the bar as written, whatever gap's sign
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
    # PROVISIONAL (A12): the crossed point estimate is the same equal-cell mean as the fixed-market one, so
    # falsifier 4 can trigger only through a difference in population; it is evaluated as written.
    if crossed_estimate is not None and (crossed_estimate > 0) != (est > 0) and est != 0:
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
    decision = decide(primary["fixed_market"], per_market, gap, primary["crossed"]["estimate"])
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


def score(*, rule, layout_root, countable, labels, market, out, shadow=None, serving_changes=(), now=None,
          root=None):
    """The single MG-1 look. Refusals before the first outcome join read no label or price and spend nothing."""
    import pandas as pd

    look = Look(rule)
    counted, rows = read_countable(countable)
    now = now or _now_utc()
    _, last = window.window()
    if now.date() <= last:
        raise MG1LookRefused(f"the recorded MG-1 window (last {last}) has not closed")
    settled = settled_at(counted[-1])
    if now < settled:
        raise MG1LookRefused(f"the 45th countable date {counted[-1]} has not ended in every market "
                             f"(until {settled.isoformat()})")
    out = Path(out)
    result = out / RESULT
    if result.exists():
        raise MG1LookRefused(f"{result} already exists: MG-1 has exactly one look")
    changes = sorted({date.fromisoformat(str(d)) for d in serving_changes})
    snaps, bands, input_shas = read_inputs(layout_root, counted)
    frame = mg1_vector(snaps, bands)
    checks, reasons = outcome_blind_checks(snaps, bands, frame, shadow)
    base = {"schema": RESULT_SCHEMA, "mg1_rule_sha256": look.rule_sha256, "entry_sha256": module_sha256(),
            "counted_dates": {"count": len(counted), "first": counted[0].isoformat(),
                              "last": counted[-1].isoformat()},
            "not_countable": [r["date"].isoformat() for r in rows if not r["countable"]],
            "clarification_1_caveats": {r["date"].isoformat(): {"parser_v2_verified": r["parser_v2_verified"],
                                                                "shadow_stage_captured": r["shadow_stage_captured"]}
                                        for r in rows if r["countable"]},
            "inputs": {**input_shas, "countable_sha256": sha256_file(countable),
                       "mg1_frame_rows": int(len(frame))},
            "markets": list(MARKETS), "outcome_blind_checks": checks, "coverage_reasons": reasons,
            "served_releases": served_releases(snaps), "serving_changes": [d.isoformat() for d in changes],
            "outcomes_opened": False}
    try:
        lab, mkt, priced, shas = look.join_outcomes(load_outcomes, labels, market, snaps, bands)
        base["outcomes_opened"] = True
        base["inputs"].update(shas)
        table = _table(snaps, bands, lab, mkt)
        p, reason = _reasons(table, frame)
        if pd.Series(reason).value_counts().to_dict() != reasons:
            raise MG1LookRefused("the fallback reasons changed once outcomes were joined")
        rows_out = score_rows(table, p, reason == "candidate", priced, changes)
        payload = {**base, **rows_out, "decision": _verdict(checks, rows_out["decision"])}
    except BaseException as exc:
        if look.looked_at_utc is None:
            raise
        payload = {**base, "decision": {"verdict": "ABORTED", "error": f"{type(exc).__name__}: {exc}"}}
        _write_result(result, payload)
        look.finish(result=result, dates=[d.isoformat() for d in counted], root=root)
        raise
    _write_result(result, payload)
    return look.finish(result=result, dates=[d.isoformat() for d in counted], root=root), payload


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
    run.add_argument("--labels", required=True, help="venue labels (row_key, winner); read only at the join")
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
        path, payload = score(rule=args.rule, layout_root=args.layout, countable=args.countable, labels=args.labels,
                              market=args.market, out=args.out, shadow=args.shadow,
                              serving_changes=args.serving_change)
    except MG1LookRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"receipt": str(path), "decision": payload["decision"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
