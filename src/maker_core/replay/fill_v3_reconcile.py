"""DESCRIPTIVE own-session reconciliation of the replay fill rules (item 330 build 1). Never a decision gate.

It replays journaled own quotes (RE-1 session journals today; the LFC journals once their adapter is added)
leg by leg against the 88a prints and books in replay bundles, and reports predicted against actual own fills:

- **Legs** come from the session journal: a ``submit_request`` acknowledged by an ``ok`` ``submit_response`` rests
  from that acknowledgement until its cancel response, cleanup cancel, terminal order, GTD expiry, full fill or
  the session's last row, whichever is first.
- **Predictions** per leg, over the prints of its condition with ``ack <= traded_at <= end``: the v2 rule under
  both bounds (the frozen ``fill_model.match`` applied print by print to the leg's remaining size, without the
  replay's first-fill end) and the v3 queue rule (``fill_v3.deplete``) with ``q_ahead`` from the last 88a book
  captured before the acknowledgement. This is a leg-level replay of the fill rules, not of the decision kernel:
  the decisions are the journaled ones.
- **c_at / c_thr** follow the LFC pre-registration definitions (and ``lfc_analysis``): prints on the leg's token
  at exactly our bid / strictly below it while the leg rests; an own fill is attributed to a print within 120 s;
  the share ratio is reported with N and an exact Clopper-Pearson 95 % interval treating prints as units
  (success: the print carries an attributed own fill). c_at is also reported by ``q_ahead`` tercile.
- **No pooling.** LFC pre-registration §8: nothing here is pooled with replay or shadow results.

Refusals, in code and before any outcome is read:

- every journal timestamp, every leg's local quote date and every bundle day passes ``fill_v3_embargo.check``
  (purpose 'descriptive'): the reserved window 2026-09-30..2026-10-15 is refused; a bundle day also passes
  ``export_gate.read_permitted`` before any stream is opened;
- **panel exclusion:** a leg resting on a local quote date inside the shadow/panel window (2026-10-16..2026-11-13)
  is kept only when its band-day ``(condition_id, local_quote_date)`` is in the LFC ``panel_exclusions.jsonl``
  (those band-days are removed from every panel, so reading them reads no panel). Any such leg without an
  exclusion file refuses the run; a leg whose band-day is not excluded is dropped before its fills, prints or
  books are read.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path

from maker_core.quoting.policy import QuoteLeg
from maker_core.replay import export_gate
from maker_core.replay.bundle import MAX_MANIFEST_BYTES, regular_path, time_zone
from maker_core.replay.bundle_v02 import load_any
from maker_core.replay.fill_model import BOUNDS, match
from maker_core.replay.fill_v3 import VERSION, Print, deplete, eligibility, q_ahead
from maker_core.replay.fill_v3_embargo import RESERVED_LAST, SCORED_EMBARGO_LAST, check as embargo_check
from maker_core.replay.payloads import Book, Trade, decode

# Research output id, deliberately not in registry form: registering it edits a capture-imported registry
# module, which is roll-sensitive. Register it in a quiet-window change before the output becomes durable.
SCHEMA = "maker-fill-v3-reconcile/0.1"
LABEL = "DESCRIPTIVE"
PURPOSE = "descriptive"
FILL_MATCH_SECONDS = 120
PANEL_FIRST = RESERVED_LAST + timedelta(days=1)
PANEL_LAST = SCORED_EMBARGO_LAST
EXCLUSION_FIELDS = ("appended_utc", "condition_ids", "event_slug", "local_quote_date", "session_id")
OUTCOMES = {"yes": "YES", "no": "NO"}
ZERO = Decimal(0)
NO_POOLING = ("LFC pre-registration section 8: these descriptive ratios are never pooled with replay or shadow "
              "results and change nothing except through its pre-declared triggers.")


class ReconcileError(ValueError):
    """A malformed or inadmissible input; the message is a stable code."""


def _d(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ReconcileError("invalid_number") from exc
    if not result.is_finite():
        raise ReconcileError("invalid_number")
    return result


def _utc(value) -> datetime:
    if not isinstance(value, str):
        raise ReconcileError("invalid_timestamp")
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReconcileError("invalid_timestamp") from exc
    if at.tzinfo is None or at.utcoffset() is None:
        raise ReconcileError("naive_timestamp")
    return at.astimezone(timezone.utc)


# -- journals ---------------------------------------------------------------------------------------------
@dataclass
class Leg:
    order_id: str
    token_id: str
    outcome: str
    condition_id: str
    price: Decimal
    size: Decimal
    acked_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    expires_at: datetime | None = None
    fills: list = field(default_factory=list)  # [(at, size, source)], attached only after admission

    def close(self, at, why):
        if self.ended_at is None or at < self.ended_at:
            self.ended_at, self.end_reason = at, why


@dataclass
class Session:
    name: str
    sha256: str
    condition_id: str
    legs: list
    rows: list  # every parsed row; fills are read from it only by ``attach_fills``
    last_at: datetime


def read_journal(path) -> Session:
    """Parse one RE-1-shaped session journal. Every ``recorded_at_utc`` passes the embargo as it is parsed."""
    raw = Path(path).read_bytes()
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ReconcileError("journal_row_not_object")
        at = _utc(row.get("recorded_at_utc"))
        embargo_check(at, PURPOSE)
        rows.append((at, row))
    if not rows or rows[0][1].get("event") != "opened":
        raise ReconcileError("journal_without_opened")
    scope = rows[0][1].get("scope") or {}
    condition = str(scope.get("condition_id") or "").lower()
    tokens = [str(t) for t in scope.get("token_ids") or ()]
    if not condition or len(tokens) != 2 or len(set(tokens)) != 2:
        raise ReconcileError("journal_scope")
    outcomes = _token_outcomes(rows, tokens)
    legs, pending = {}, None
    for at, row in rows:
        event = row.get("event")
        if event == "submit_request":
            pending = row.get("request") or {}
        elif event == "submit_response":
            response = row.get("response") or {}
            request, pending = pending, None
            oid = str(response.get("order_id") or "")
            if not oid or request is None or response.get("ok") is not True:
                continue
            if str(request.get("side", "")).upper() != "BUY" or request.get("post_only") is not True:
                raise ReconcileError("unsupported_leg_side_or_not_post_only")
            token = str(request.get("token_id"))
            if token not in outcomes:
                raise ReconcileError("leg_token_outside_scope")
            leg = Leg(oid, token, outcomes[token], condition, _d(request["price"]), _d(request["size"]), at)
            expiration = int(request.get("expiration") or 0)
            if expiration > 0:
                leg.expires_at = datetime.fromtimestamp(expiration, tz=timezone.utc)
            if oid in legs:
                raise ReconcileError("duplicate_order_id")
            legs[oid] = leg
        elif event in ("cancel_response", "cleanup_cancel_response", "cleanup_cancel_ours_response"):
            for oid in (row.get("response") or {}).get("canceled") or ():
                if str(oid) in legs:
                    legs[str(oid)].close(at, "canceled")
        elif event == "terminal_order":
            order = row.get("order") or {}
            oid = str(order.get("id") or "")
            if oid in legs and str(order.get("status", "")).upper() != "LIVE":
                legs[oid].close(at, "terminal_" + str(order.get("status", "")).lower())
    last = rows[-1][0]
    for leg in legs.values():
        if leg.expires_at is not None:
            leg.close(leg.expires_at, "expired")
        leg.close(last, "session_end")
    return Session(Path(path).parent.name, hashlib.sha256(raw).hexdigest(), condition, list(legs.values()),
                   rows, last)


def _token_outcomes(rows, tokens):
    """token_id -> YES/NO from the journal's own order rows; scope order (YES, NO) only where none says."""
    seen = {}
    for _, row in rows:
        items = []
        if row.get("event") == "terminal_order":
            items.append(row.get("order") or {})
        elif row.get("event") == "fill":
            items.extend(row.get("rows") or ())
            event = row.get("user_event") or {}
            items.append({"token_id": event.get("clob_token_id"), "outcome": event.get("outcome")})
        for item in items:
            token, outcome = str(item.get("token_id")), OUTCOMES.get(str(item.get("outcome", "")).lower())
            if token in tokens and outcome is not None:
                if seen.setdefault(token, outcome) != outcome:
                    raise ReconcileError("conflicting_token_outcome")
    if not seen:
        return {tokens[0]: "YES", tokens[1]: "NO"}
    token = min(seen)  # any proven token fixes both: the other is its complement
    other = tokens[1] if token == tokens[0] else tokens[0]
    result = {token: seen[token], other: "NO" if seen[token] == "YES" else "YES"}
    if any(result[t] != o for t, o in seen.items()):
        raise ReconcileError("conflicting_token_outcome")
    return result


def attach_fills(session: Session, legs) -> None:
    """Read own fills for the admitted ``legs`` only: ``fill`` rows, then any terminal ``size_matched`` residual."""
    wanted = {leg.order_id: leg for leg in legs}
    matched = {}
    for at, row in session.rows:
        if row.get("event") == "fill":
            event = row.get("user_event") or {}
            oid = str(event.get("order_id") or "")
            if oid in wanted:
                wanted[oid].fills.append((at, _d(event.get("fill_size")), "fill_event"))
        elif row.get("event") == "terminal_order":
            order = row.get("order") or {}
            oid = str(order.get("id") or "")
            if oid in wanted:
                matched[oid] = (at, _d(order.get("size_matched") or 0))
    for oid, (at, size) in matched.items():
        leg = wanted[oid]
        residual = size - sum((s for _, s, _ in leg.fills), ZERO)
        if residual > 0:
            leg.fills.append((at, residual, "terminal_size_matched"))
    for leg in legs:
        leg.fills.sort(key=lambda f: f[0])
        total = ZERO
        for at, size, _ in leg.fills:
            total += size
            if total >= leg.size:
                leg.close(at, "filled")
                break


# -- panel exclusion --------------------------------------------------------------------------------------
def load_panel_exclusions(path) -> frozenset:
    """Band-days ``(condition_id, local_quote_date)`` of an LFC ``panel_exclusions.jsonl``; malformed refuses."""
    raw = Path(path).read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ReconcileError("exclusion_file_truncated")
    result = set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ReconcileError("exclusion_line_not_json") from exc
        if not isinstance(row, dict) or tuple(sorted(row)) != EXCLUSION_FIELDS:
            raise ReconcileError("exclusion_fields")
        day, conditions = row["local_quote_date"], row["condition_ids"]
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ReconcileError("exclusion_date") from exc
        if not isinstance(conditions, list) or not conditions or not all(isinstance(c, str) and c for c in conditions):
            raise ReconcileError("exclusion_conditions")
        result.update((c.lower(), day) for c in conditions)
    return frozenset(result)


def local_dates(start: datetime, end: datetime, zone) -> tuple:
    first, last = start.astimezone(zone).date(), end.astimezone(zone).date()
    return tuple((first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1))


def admit(legs, zone, exclusions):
    """Split legs into (kept, dropped-with-reason) before any outcome read; refuse what may not be read at all."""
    kept, dropped = [], []
    for leg in legs:
        days = local_dates(leg.acked_at, leg.ended_at, zone)
        for day in days:
            embargo_check(day, PURPOSE)
        in_panel = [d for d in days if PANEL_FIRST.isoformat() <= d <= PANEL_LAST.isoformat()]
        if in_panel:
            if exclusions is None:
                raise ReconcileError("panel_exclusions_required")
            if any((leg.condition_id, d) not in exclusions for d in in_panel):
                dropped.append((leg, "PANEL_BAND_DAY_NOT_EXCLUDED"))
                continue
        kept.append(leg)
    return kept, dropped


# -- 88a bundles ------------------------------------------------------------------------------------------
@dataclass
class Market:
    books: list = field(default_factory=list)  # [(captured_at, Book)] in capture order
    trades: dict = field(default_factory=dict)  # trade_id -> Trade


def bundle_day(directory) -> date:
    """The manifest's UTC day, read under the manifest cap, before any stream is opened."""
    path = regular_path(Path(directory)) / "bundle.json"
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ReconcileError("bundle_manifest_too_large")
    value = json.loads(path.read_bytes())
    day = value.get("day") if isinstance(value, dict) else None
    try:
        parsed = date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise ReconcileError("bundle_day") from exc
    if parsed.isoformat() != day:
        raise ReconcileError("bundle_day")
    return parsed


def read_bundle(directory, conditions, markets) -> date:
    """Admit one replay bundle's books and prints for ``conditions`` into ``markets``; return its UTC day.

    The day passes the v3 embargo and the replay-v2 panel read gate before any stream is opened."""
    day = embargo_check(bundle_day(directory), PURPOSE)
    export_gate.read_permitted(day)
    bundle = load_any(Path(directory))
    records = bundle.records() if callable(bundle.records) else bundle.records
    for record in records:
        if record.kind not in ("book", "trade"):
            continue
        cid = str(record.condition_id).lower()
        if cid not in conditions:
            continue
        value = decode(record)
        market = markets.setdefault(cid, Market())
        if record.kind == "book" and isinstance(value, Book):
            market.books.append((record.captured_at, value))
        elif isinstance(value, Trade):
            embargo_check(value.traded_at, PURPOSE)
            previous = market.trades.setdefault(value.trade_id, value)
            if previous != value:
                raise ReconcileError("conflicting_duplicate_trade")
    return day


# -- statistics -------------------------------------------------------------------------------------------
def _binomial_cdf(k, n, p):
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    base = math.lgamma(n + 1)
    return min(1.0, sum(math.exp(base - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
                        for i in range(k + 1)))


def _solve(f, target, increasing):
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if (f(mid) < target) == increasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(k: int, n: int, alpha: float = 0.05):
    """Exact two-sided (1 - alpha) interval for k successes in n trials; None when n is 0."""
    if type(k) is not int or type(n) is not int or not 0 <= k <= n:
        raise ReconcileError("clopper_pearson_counts")
    if n == 0:
        return None
    lower = 0.0 if k == 0 else _solve(lambda p: 1 - _binomial_cdf(k - 1, n, p), alpha / 2, True)
    upper = 1.0 if k == n else _solve(lambda p: _binomial_cdf(k, n, p), alpha / 2, False)
    return [round(lower, 6), round(upper, 6)]


class Ratio:
    def __init__(self):
        self.numerator = self.denominator = ZERO
        self.n = self.k = 0

    def add(self, attributed, denominator):
        self.numerator += min(attributed, denominator)
        self.denominator += denominator
        self.n += 1
        self.k += attributed > 0

    def report(self):
        return {"ratio": None if self.denominator == 0 else _fmt(self.numerator / self.denominator),
                "N": self.n, "k_prints_with_own_fill": self.k, "cp95": clopper_pearson(self.k, self.n)}


def _fmt(value):
    return format(value.quantize(Decimal("0.000001")).normalize(), "f") if isinstance(value, Decimal) else value


# -- reconciliation ---------------------------------------------------------------------------------------
def _leg_book(market, leg):
    before = [book for captured, book in market.books if captured < leg.acked_at and book.as_of_utc < leg.acked_at]
    return before[-1] if before else None


def _v2_prediction(leg, trades, bound):
    remaining = leg.size
    for trade in trades:
        if remaining <= 0:
            break
        found = match((QuoteLeg(leg.outcome, leg.price, remaining),), trade, bound)
        if found is not None:
            remaining -= found[1]
    return leg.size - remaining


def _lfc_ratios(leg, trades, at_ratio, thr_ratio, used):
    """lfc_analysis's attribution on the leg's token: prints at/below our bid, fills within 120 s, used once."""
    filled_before = ZERO
    for trade in trades:
        if trade.outcome != leg.outcome or trade.price > leg.price:
            continue
        remaining = leg.size - filled_before
        if remaining <= 0:
            continue
        attributed = ZERO
        for index, (fill_at, fill_size, _) in enumerate(leg.fills):
            key = leg.order_id, index
            if key not in used and abs((fill_at - trade.traded_at).total_seconds()) <= FILL_MATCH_SECONDS:
                used.add(key)
                attributed += fill_size
        ratio = at_ratio if trade.price == leg.price else thr_ratio
        ratio.add(attributed, min(trade.size, remaining))
        filled_before += attributed


def terciles(values):
    """Rank cut points (ceil(n/3), ceil(2n/3)) over sorted values; ties stay in the lower tercile."""
    ordered = sorted(values)
    if not ordered:
        return None
    n = len(ordered)
    return ordered[math.ceil(n / 3) - 1], ordered[math.ceil(2 * n / 3) - 1]


def reconcile(journals, bundles, *, time_zone_name, exclusions_path=None) -> dict:
    zone = time_zone(time_zone_name)
    exclusions = None if exclusions_path is None else load_panel_exclusions(exclusions_path)
    sessions = [read_journal(path) for path in journals]
    admitted, dropped = [], []
    for session in sessions:
        kept, out = admit(session.legs, zone, exclusions)
        attach_fills(session, kept)
        admitted.extend(kept)
        dropped.extend(out)
    markets, days = {}, set()
    conditions = {leg.condition_id for leg in admitted}
    for directory in bundles:
        days.add(read_bundle(directory, conditions, markets))
    rows = []
    at_all, thr_all, used = Ratio(), Ratio(), set()
    per_leg_at = {}
    for leg in sorted(admitted, key=lambda leg: (leg.acked_at, leg.order_id)):
        span = {leg.acked_at.date() + timedelta(days=n) for n in range((leg.ended_at.date() - leg.acked_at.date()).days + 1)}
        actual = sum((size for _, size, _ in leg.fills), ZERO)
        row = {"order_id": leg.order_id, "outcome": leg.outcome, "price": _fmt(leg.price), "size": _fmt(leg.size),
               "acked_at_utc": leg.acked_at.isoformat(), "ended_at_utc": leg.ended_at.isoformat(),
               "end_reason": leg.end_reason, "actual_filled": _fmt(actual)}
        if not span <= days:
            row["status"] = "NO_BUNDLE_DAY"
            rows.append(row)
            continue
        market = markets.get(leg.condition_id, Market())
        trades = sorted((t for t in market.trades.values() if leg.acked_at <= t.traded_at <= leg.ended_at),
                        key=lambda t: (t.traded_at, t.trade_id))
        queue = q_ahead(_leg_book(market, leg), leg)
        prints = []
        for trade in trades:
            kind = eligibility(QuoteLeg(leg.outcome, leg.price, leg.size), trade)
            if kind is not None:
                prints.append(Print(trade.traded_at, kind, trade.size))
        row["status"] = "RECONCILED" if queue is not None else "NO_BOOK_BEFORE_ACK"
        row["q_ahead"] = None if queue is None else _fmt(queue)
        row["eligible_prints"] = {"at": sum(p.kind == "at" for p in prints), "thr": sum(p.kind == "thr" for p in prints)}
        row["predicted"] = {bound: _fmt(_v2_prediction(leg, trades, bound)) for bound in BOUNDS}
        row["predicted"][VERSION] = None if queue is None else _fmt(deplete(leg.size, queue, prints).total)
        leg_at = Ratio()
        _lfc_ratios(leg, trades, leg_at, thr_all, used)
        per_leg_at[leg.order_id] = (queue, leg_at)
        at_all.n += leg_at.n
        at_all.k += leg_at.k
        at_all.numerator += leg_at.numerator
        at_all.denominator += leg_at.denominator
        rows.append(row)
    cuts = terciles([queue for queue, _ in per_leg_at.values() if queue is not None])
    by_tercile = {}
    if cuts is not None:
        for name in ("T1", "T2", "T3"):
            by_tercile[name] = Ratio()
        for queue, ratio in per_leg_at.values():
            if queue is None:
                continue
            bucket = by_tercile["T1" if queue <= cuts[0] else "T2" if queue <= cuts[1] else "T3"]
            bucket.n += ratio.n
            bucket.k += ratio.k
            bucket.numerator += ratio.numerator
            bucket.denominator += ratio.denominator
    models = list(BOUNDS) + [VERSION]
    reconciled = [r for r in rows if r["status"] == "RECONCILED"]
    comparison = {}
    for model in models:
        table = {"both": 0, "predicted_only": 0, "actual_only": 0, "neither": 0}
        for r in reconciled:
            predicted, actual = Decimal(r["predicted"][model]) > 0, Decimal(r["actual_filled"]) > 0
            table["both" if predicted and actual else "predicted_only" if predicted else
                  "actual_only" if actual else "neither"] += 1
        comparison[model] = {"legs": table,
                             "predicted_shares": _fmt(sum((Decimal(r["predicted"][model]) for r in reconciled), ZERO)),
                             "actual_shares": _fmt(sum((Decimal(r["actual_filled"]) for r in reconciled), ZERO))}
    reasons = {}
    for _, why in dropped:
        reasons[why] = reasons.get(why, 0) + 1
    return {"schema_version": SCHEMA, "label": LABEL, "descriptive_only": True, "fill_v3_version": VERSION,
            "no_pooling": NO_POOLING, "time_zone": time_zone_name,
            "journals": [{"session": s.name, "sha256": s.sha256} for s in sessions],
            "bundle_days": sorted(d.isoformat() for d in days),
            "legs": rows, "dropped_before_outcome_read": dict(sorted(reasons.items())),
            "predicted_vs_actual": comparison,
            "c_at": at_all.report(), "c_thr": thr_all.report(),
            "q_ahead_tercile_cuts": None if cuts is None else [_fmt(c) for c in cuts],
            "c_at_by_q_ahead_tercile": {k: v.report() for k, v in by_tercile.items()}}


def encode(result) -> bytes:
    return (json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
            + "\n").encode("utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m maker_core.replay.fill_v3_reconcile",
                                     description="DESCRIPTIVE own-session reconciliation of the replay fill rules.")
    parser.add_argument("--journal", type=Path, action="append", required=True, help="session journal.jsonl")
    parser.add_argument("--bundle", type=Path, action="append", required=True, help="replay bundle directory")
    parser.add_argument("--time-zone", required=True, help="IANA zone of the sessions' markets (local quote date)")
    parser.add_argument("--panel-exclusions", type=Path, help="LFC panel_exclusions.jsonl (required for legs "
                                                              "on 2026-10-16..2026-11-13 local dates)")
    parser.add_argument("--output", type=Path, required=True, help="new JSON file (never overwritten)")
    args = parser.parse_args(argv)
    result = reconcile(args.journal, args.bundle, time_zone_name=args.time_zone,
                       exclusions_path=args.panel_exclusions)
    with args.output.open("xb") as handle:
        handle.write(encode(result))
    print(json.dumps({"label": LABEL, "legs": len(result["legs"]), "c_at": result["c_at"],
                      "c_thr": result["c_thr"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
