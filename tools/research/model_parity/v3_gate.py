"""HARNESS v3 H1: the date gate. Every score or coverage request is decided here, by (family, date).

It replaces hard-coded constants such as ``harness.LAST_TARGET_DATE`` with two sources read at call
time, failing closed when either is missing or unparseable:

1. ``docs/operations/reserved-confirmation-window.md``: the status line. While MG-1's narrow
   reservation is RESERVED and undated, every date on or after its ``D0 >= YYYY-MM-DD`` bound is
   held out from families that read NBM station guidance into band probabilities; once the line is
   dated (``MG-1 D0 = ...`` / ``MG-1 last = ...``), exactly that range is.
2. The forward alpha ledger (``forward_alpha_ledger.jsonl`` beside this file; schema
   ``forward_alpha_ledger/1``), one row per (family, date range) with a status:

   - ``reserved``     nothing may read the range for that family (``scope: all`` also refuses
                      outcome-free coverage counts). An ``open`` row never overrides it.
   - ``closed_by_default``  label/market joins are refused unless an ``open`` row for the
                      requesting family covers the date (the >= 2026-09-30 horizon).
   - ``open``         the range is opened for ``confirmation`` scoring of that family only.
   - ``spent``        the range was already read for the family: development and controls may
                      use it; a confirmation may not.

Purposes: ``coverage`` (outcome-free counts, no label or market file opened), ``development`` and
``control`` (label/market joins on dates nobody has closed), ``confirmation`` (joins only on dates an
``open`` row names for the family, never spent ones).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
WINDOW_PATH = REPO / "docs" / "operations" / "reserved-confirmation-window.md"
LEDGER_PATH = Path(__file__).resolve().parent / "forward_alpha_ledger.jsonl"
LEDGER_SCHEMA = "forward_alpha_ledger/1"

PURPOSES = ("coverage", "development", "control", "confirmation")
JOIN_PURPOSES = ("development", "control", "confirmation")
STATUSES = ("reserved", "closed_by_default", "open", "spent")
SCOPES = ("join", "all")
ANY_FAMILY = "*"
NBM_GUIDANCE_RESERVATION = "mg1_reserved_window"
ROW_FIELDS = {"schema", "row_id", "family", "date_start", "date_end", "status", "scope", "alpha",
              "decided_by", "decided_at", "reason", "source"}
REQUIRED_FIELDS = ROW_FIELDS - {"alpha"}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class GateError(RuntimeError):
    """The gate's sources are missing, malformed or inconsistent: everything is refused."""


class GateRefused(PermissionError):
    """A (family, date) request was refused; ``refusals`` lists every refused date with reasons."""

    def __init__(self, refusals):
        self.refusals = refusals
        head = "; ".join(f"{r['date']} {r['family']}: {', '.join(r['reasons'])}" for r in refusals[:5])
        more = f" (+{len(refusals) - 5} more)" if len(refusals) > 5 else ""
        super().__init__(f"gate refused {len(refusals)} date(s): {head}{more}")


def _iso(value, what):
    if not isinstance(value, str) or not _ISO.match(value):
        raise GateError(f"{what} is not an ISO date: {value!r}")
    date.fromisoformat(value)
    return value


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------------------- window file

def parse_window(text):
    """Return the MG-1 reservation read from the status line, or raise GateError (fail closed).

    Result: ``{"state": "reserved_dated", "start", "end"}``, ``{"state": "reserved_undated",
    "start"}`` (open-ended from the D0 lower bound) or ``{"state": "none"}``.
    """
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("**Status:")), None)
    if start is None:
        raise GateError("reserved-confirmation-window.md has no '**Status:' line")
    para = []
    for line in lines[start:]:          # the status is the whole paragraph, wrapped over lines
        if not line.strip():
            break
        para.append(line.strip())
    status = " ".join(para)
    d0 = re.search(r"MG-1 D0 = (\d{4}-\d{2}-\d{2})", status)
    last = re.search(r"MG-1 last = (\d{4}-\d{2}-\d{2})", status)
    if d0 or last:
        if not (d0 and last):
            raise GateError("status line dates only one MG-1 endpoint")
        start, end = _iso(d0.group(1), "MG-1 D0"), _iso(last.group(1), "MG-1 last")
        if end < start:
            raise GateError("MG-1 last precedes D0")
        return {"state": "reserved_dated", "start": start, "end": end, "status_line": status}
    upper = status.upper()
    if "NOT RESERVED" in upper or "NO WINDOW" in upper:
        return {"state": "none", "status_line": status}
    if "RESERVED" in upper:
        bound = re.search(r"D0 >= (\d{4}-\d{2}-\d{2})", status)
        if not bound:
            raise GateError("RESERVED status line carries neither a dated range nor a 'D0 >=' bound")
        return {"state": "reserved_undated", "start": _iso(bound.group(1), "D0 bound"),
                "status_line": status}
    raise GateError(f"unrecognised reservation status line: {status[:120]!r}")


# ----------------------------------------------------------------------------- ledger

def validate_row(row):
    if not isinstance(row, dict):
        raise GateError("ledger row is not an object")
    missing = REQUIRED_FIELDS - set(row)
    unknown = set(row) - ROW_FIELDS
    if missing or unknown:
        raise GateError(f"ledger row {row.get('row_id')!r}: missing {sorted(missing)} unknown {sorted(unknown)}")
    if row["schema"] != LEDGER_SCHEMA:
        raise GateError(f"ledger row {row['row_id']!r} has schema {row['schema']!r}")
    if row["status"] not in STATUSES or row["scope"] not in SCOPES:
        raise GateError(f"ledger row {row['row_id']!r} has status/scope {row['status']!r}/{row['scope']!r}")
    start, end = _iso(row["date_start"], "date_start"), _iso(row["date_end"], "date_end")
    if end < start:
        raise GateError(f"ledger row {row['row_id']!r} ends before it starts")
    if not isinstance(row["family"], str) or not row["family"]:
        raise GateError(f"ledger row {row['row_id']!r} has no family")
    if row["status"] == "open" and row["family"] == ANY_FAMILY:
        raise GateError("an open row must name one family, never '*'")
    if row.get("alpha") is not None and not (0 < float(row["alpha"]) < 1):
        raise GateError(f"ledger row {row['row_id']!r} alpha out of (0, 1)")
    return row


def read_ledger(path=LEDGER_PATH):
    path = Path(path)
    if not path.exists():
        raise GateError(f"forward alpha ledger is missing: {path}")
    raw = path.read_bytes()
    rows, ids = [], set()
    for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateError(f"ledger line {n} is not JSON: {exc}") from exc
        validate_row(row)
        if row["row_id"] in ids:
            raise GateError(f"duplicate ledger row_id {row['row_id']!r}")
        ids.add(row["row_id"])
        rows.append(row)
    if not rows:
        raise GateError("forward alpha ledger is empty")
    return rows, _sha256_bytes(raw)


def append_row(row, path=LEDGER_PATH):
    """Append one validated row (append-only; never rewrites earlier rows)."""
    validate_row(row)
    path = Path(path)
    existing, _ = read_ledger(path) if path.exists() else ([], None)
    if any(r["row_id"] == row["row_id"] for r in existing):
        raise GateError(f"row_id {row['row_id']!r} already in the ledger")
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
    return row


# ----------------------------------------------------------------------------- the gate

@dataclass
class Decision:
    family: str
    date: str
    purpose: str
    allowed: bool
    reasons: list = field(default_factory=list)


class Gate:
    def __init__(self, window_path=WINDOW_PATH, ledger_path=LEDGER_PATH):
        self.window_path, self.ledger_path = Path(window_path), Path(ledger_path)
        if not self.window_path.exists():
            raise GateError(f"reserved-confirmation-window file is missing: {self.window_path}")
        window_bytes = self.window_path.read_bytes()
        self.window = parse_window(window_bytes.decode("utf-8"))
        self.rows, self.ledger_sha256 = read_ledger(self.ledger_path)
        self.window_sha256 = _sha256_bytes(window_bytes)

    def identity(self):
        return {"window_path": str(self.window_path), "window_sha256": self.window_sha256,
                "window": {k: v for k, v in self.window.items() if k != "status_line"},
                "ledger_path": str(self.ledger_path), "ledger_sha256": self.ledger_sha256,
                "ledger_rows": len(self.rows)}

    def _covering(self, family, day):
        return [r for r in self.rows if r["date_start"] <= day <= r["date_end"]
                and r["family"] in (family, ANY_FAMILY)]

    def decide(self, family, day, purpose, reads_nbm_guidance):
        if purpose not in PURPOSES:
            raise GateError(f"unknown purpose {purpose!r}")
        if not isinstance(reads_nbm_guidance, bool):
            raise GateError("reads_nbm_guidance must be declared True or False")
        if not family or family == ANY_FAMILY:
            raise GateError("a request names exactly one family")
        day = _iso(day, "requested date")
        rows = self._covering(family, day)
        reasons = []
        join = purpose in JOIN_PURPOSES
        for r in rows:
            if r["status"] == "reserved" and (r["scope"] == "all" or join):
                reasons.append(f"reserved by ledger row {r['row_id']}")
        w = self.window
        if reads_nbm_guidance and w["state"] != "none" and join:
            inside = (w["start"] <= day <= w["end"]) if w["state"] == "reserved_dated" else day >= w["start"]
            if inside:
                reasons.append(f"{NBM_GUIDANCE_RESERVATION} ({w['state']}) holds this date against "
                               "NBM-guidance-to-band candidates")
        if join:
            opened = [r for r in rows if r["status"] == "open" and r["family"] == family]
            closed = [r for r in rows if r["status"] == "closed_by_default"]
            spent = [r for r in rows if r["status"] == "spent"]
            if purpose == "confirmation":
                if not opened:
                    reasons.append("confirmation needs an open ledger row for this family and date")
                if spent:
                    reasons.append(f"already spent (ledger row {spent[0]['row_id']})")
            else:
                if closed and not opened:
                    reasons.append(f"closed by default (ledger row {closed[0]['row_id']}); no open row "
                                   "for this family")
                if opened:
                    reasons.append("date is opened for confirmation only; a development or control read "
                                   "would spend it")
        return Decision(family, day, purpose, not reasons, reasons)

    def require(self, family, dates, purpose, reads_nbm_guidance):
        """Decide every date; raise GateRefused listing all refusals, else return the decisions."""
        decisions = [self.decide(family, d, purpose, reads_nbm_guidance) for d in sorted(set(dates))]
        refused = [{"family": x.family, "date": x.date, "purpose": x.purpose, "reasons": x.reasons}
                   for x in decisions if not x.allowed]
        if refused:
            raise GateRefused(refused)
        return Ticket(family, purpose, reads_nbm_guidance, frozenset(x.date for x in decisions),
                      self.identity())


@dataclass(frozen=True)
class Ticket:
    """Proof that the gate allowed ``dates`` for ``family``/``purpose``. Outcome loaders demand one."""
    family: str
    purpose: str
    reads_nbm_guidance: bool
    dates: frozenset
    gate_identity: dict = field(hash=False, compare=False)

    def check(self, dates):
        outside = sorted(set(dates) - set(self.dates))
        if outside:
            raise GateRefused([{"family": self.family, "date": d, "purpose": self.purpose,
                                "reasons": ["date is not on the gate ticket"]} for d in outside])
        return True


def default_gate():
    return Gate(WINDOW_PATH, LEDGER_PATH)
