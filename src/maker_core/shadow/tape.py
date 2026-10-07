"""Per-minute quotes tape: exact input projections and a daily sealed journal.

The tape is a ``maker_core.evidence.journal`` chain, one file per UTC day and
run, closed by a ``terminal`` record and a create-only seal holding the whole
file SHA-256. Each ``minute`` record carries, per condition, the exact policy
inputs (projection invertible to the same ``DecisionInputs``), the decision, the
guard outcome of every would-quote leg and the hypothetical resting legs.
It records proposals, never orders. Paths are explicit caller inputs.
"""
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import secrets

from maker_core.contracts import InfoEvent, MarketDescriptor, OutcomeView, Unavailable
from maker_core.evidence.journal import Journal, plain, verify_journal, write_new
from maker_core.quoting.policy import (Book, DecisionInputs, ExposureLimit, Portfolio, QuoteLeg,
                                       RewardTerms, blind_re1, informed_v0)

TAPE_SCHEMA = "maker_core.shadow_tape.v0.1"
SEAL_SCHEMA = "maker_core.shadow_tape_seal.v0.1"
PROFILES = {p.name: p for p in (informed_v0, blind_re1)}
D = Decimal


def _time(value):
    return None if value is None else datetime.fromisoformat(value)


def _levels(rows):
    return tuple((D(price), D(size)) for price, size in rows)


def market_projection(market):
    """Plain market with ``outcomes`` in place of the guard-scrubbed token mapping."""
    row = plain(market)
    row["outcomes"] = row.pop("outcome_tokens")
    return row


def market_from(row):
    row = dict(row)
    row["outcome_tokens"] = row.pop("outcomes")
    for name in ("tick", "min_order_size"):
        row[name] = D(row[name])
    for name in ("close_at_utc", "settle_at_utc"):
        row[name] = _time(row[name])
    return MarketDescriptor(**row)


def fair_value_projection(value):
    kind = "view" if isinstance(value, OutcomeView) else "unavailable"
    if not isinstance(value, (OutcomeView, Unavailable)):
        raise TypeError("fair_value_must_be_view_or_unavailable")
    return {"type": kind, **plain(value)}


def fair_value_from(row):
    row = dict(row)
    kind = row.pop("type")
    for name in ("as_of_utc", "valid_until_utc"):
        if name in row:
            row[name] = _time(row[name])
    return OutcomeView(**row) if kind == "view" else Unavailable(**row)


def event_from(row):
    row = dict(row)
    for name in ("scheduled_at_utc", "observed_at_utc", "detected_at_utc", "active_until_utc"):
        row[name] = _time(row.get(name))
    row["affects"] = tuple(row["affects"])
    return InfoEvent(**row)


def inputs_projection(inputs):
    if PROFILES.get(inputs.profile.name) != inputs.profile:
        raise ValueError("unregistered_profile")
    row = {f.name: plain(getattr(inputs, f.name)) for f in fields(inputs)
           if f.name not in ("market", "fair_value", "profile")}
    row.update(market=market_projection(inputs.market), fair_value=fair_value_projection(inputs.fair_value),
               profile=inputs.profile.name)
    return row


def inputs_from(row):
    """Exact inverse of ``inputs_projection``; the digest of the result equals the recorded input hash."""
    book = dict(row["book"])
    book = Book(_time(book["as_of_utc"]), *(_levels(book[k]) for k in ("yes_bids", "yes_asks", "no_bids", "no_asks")),
                post_only_available=book["post_only_available"])
    terms = row["terms"]
    if terms is not None:
        terms = RewardTerms(_time(terms["as_of_utc"]), D(terms["min_size"]), D(terms["max_spread_cents"]),
                            D(terms["rate_per_day"]))
    p = dict(row["portfolio"])
    exposures = tuple(ExposureLimit(e["factor"], D(e["loading"]), D(e["used"]), D(e["cap"]))
                      for e in p.pop("exposures"))
    for name in ("cash", "reserved_elsewhere", "band_cap", "order_cap", "wallet_used", "wallet_cap",
                 "event_used", "event_cap"):
        p[name] = D(p[name])
    return DecisionInputs(
        market=market_from(row["market"]), now=_time(row["now"]), book=book, terms=terms,
        fair_value=fair_value_from(row["fair_value"]), portfolio=Portfolio(**p, exposures=exposures),
        horizon_days=row["horizon_days"], events=tuple(event_from(e) for e in row["events"]),
        profile=PROFILES[row["profile"]], hazard_per_minute=row["hazard_per_minute"],
        adverse_markout=row["adverse_markout"],
        existing=tuple(QuoteLeg(x["outcome"], D(x["price"]), D(x["size"])) for x in row["existing"]),
        fill_seen=row["fill_seen"], last_requote_at=_time(row["last_requote_at"]),
        previous_fair_value=row["previous_fair_value"])


def decision_projection(decision):
    return plain(decision)


class TapeWriter:
    """One journal per UTC day for this run; a day roll writes terminal + seal, then opens the next day."""

    def __init__(self, directory, *, clock, scope, run_id=None):
        self.directory, self.clock = Path(directory), clock
        self.scope = dict(scope, tape_schema=TAPE_SCHEMA)
        self.run_id = run_id or clock().strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
        self.journal, self.day, self.minutes = None, None, 0
        self.sealed = []

    def _open(self, day):
        path = self.directory / f"{day}-{self.run_id}.tape.jsonl"
        self.journal = Journal(path, clock=self.clock, scope=dict(self.scope, utc_day=day, run_id=self.run_id),
                               mode="public_shadow")
        self.day, self.minutes = day, 0

    def _roll(self, day):
        if self.day is not None and day < self.day:
            raise ValueError("tape_day_regressed")
        if self.day != day:
            if self.journal is not None:
                self.close("utc_day_closed")
            self._open(day)

    def record(self, event, minute_utc, **payload):
        self._roll(minute_utc.date().isoformat())
        if event == "minute":
            self.minutes += 1
        return self.journal.record(event, minute_utc=minute_utc, **payload)

    def close(self, reason):
        if self.journal is None:
            return None
        journal, path = self.journal, self.journal.path
        journal.record("terminal", reason=reason, minutes=self.minutes)
        journal.close()
        raw = path.read_bytes()
        rows = verify_journal(path)
        seal = {"schema_version": SEAL_SCHEMA, "tape": path.name, "utc_day": self.day, "run_id": self.run_id,
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "records": len(rows),
                "final_line_sha256": hashlib.sha256(raw.splitlines(keepends=True)[-1]).hexdigest()}
        write_new(path.with_name(path.name.replace(".tape.jsonl", ".seal.json")), seal)
        self.sealed.append(seal)
        self.journal = None
        return seal


def sealed_tapes(directory, day):
    """Verified rows of every sealed tape of ``day``; unsealed tapes are listed, never read."""
    directory, tapes, unsealed = Path(directory), [], []
    for path in sorted(directory.glob(f"{day}-*.tape.jsonl")):
        seal_path = path.with_name(path.name.replace(".tape.jsonl", ".seal.json"))
        if not seal_path.is_file():
            unsealed.append(path.name)
            continue
        seal = json.loads(seal_path.read_bytes())
        if seal.get("schema_version") != SEAL_SCHEMA or seal.get("tape") != path.name or seal.get("utc_day") != day:
            raise ValueError("tape_seal_mismatch")
        rows = verify_journal(path, expected_digest=seal["sha256"])
        if rows[0]["scope"].get("tape_schema") != TAPE_SCHEMA:
            raise ValueError("unsupported_tape_schema")
        tapes.append({"tape": path.name, "sha256": seal["sha256"], "rows": rows})
    return tapes, unsealed


__all__ = ["SEAL_SCHEMA", "TAPE_SCHEMA", "TapeWriter", "decision_projection", "inputs_from",
           "inputs_projection", "market_projection", "sealed_tapes"]
