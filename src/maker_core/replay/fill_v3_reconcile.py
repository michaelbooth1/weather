"""DESCRIPTIVE own-session reconciliation of the replay fill rules (item 330 build 1). Never a decision gate.

**Not durable evidence until registered:** the output id ``SCHEMA`` is not in the schema registry yet (item 330
build 1 note); no output of this module is kept as evidence before that registration lands.

It replays journaled own quotes (RE-1 session journals today; the LFC journals once their adapter is added)
leg by leg against the 88a prints and books in replay bundles, and reports predicted against actual own fills:

- **Journal adapter.** ``read_journal`` accepts only the row stream the RE-1 attended writer emits
  (``weather.market.re1_attended.Session`` over ``mm_stage2_hold.HoldJournal`` on
  ``codex/re1-wallet-200-20260923``, tip ``2b9a0ca9e``): every row carries exactly the writer's envelope, the
  sequence is contiguous, the ``previous_sha256`` chain holds, every event name is one the writer emits, every
  event this module reads has the writer's field shape, and the last row is ``terminal`` with no unknown submit.
  Anything else refuses with a code; nothing is skipped silently.
- **Legs** come from the session journal: a ``submit_request`` acknowledged by an ``ok`` ``submit_response`` rests
  from that acknowledgement until its cancel response, cleanup cancel, terminal order, GTD expiry, full fill or
  the session's last row, whichever is first.
- **Token outcomes** (YES/NO per token) come from the journal's own order and fill rows, or from an explicit
  declaration (``--token-outcomes TOKEN=YES``). The scope's token order alone proves nothing, so a journal with
  neither refuses (``token_outcomes_unproven``).
- **Predictions** per leg, over the prints of its condition with ``ack <= traded_at <= end``: the v2 rule under
  both bounds (the frozen ``fill_model.match`` applied print by print to the leg's remaining size, without the
  replay's first-fill end) and the v3 queue rule (``fill_v3.deplete``) with ``q_ahead`` from the last 88a book
  captured before the acknowledgement. This is a leg-level replay of the fill rules, not of the decision kernel:
  the decisions are the journaled ones.
- **c_at / c_thr** follow the LFC pre-registration §1 definitions: prints on the leg's token at exactly our bid /
  strictly below it while the leg rests. Attribution is this module's choice (§1 fixes no window): each own fill
  goes to the one eligible print nearest in time inside ``fill_at - FILL_MATCH_SECONDS <= traded_at <= fill_at +
  FILL_PRINT_SKEW_SECONDS``, ties to the earlier print. Each ratio is reported with N and a **nominal** exact
  Clopper-Pearson 95 % interval (``cp95_nominal``) that treats prints as independent units (success: the print
  carries an attributed own fill). Prints within one leg are not independent, so the interval is nominal, not a
  coverage claim. c_at is also reported by ``q_ahead`` tercile.
- **No pooling.** LFC pre-registration §8: nothing here is pooled with replay or shadow results.

Refusals, in code and before any outcome is read:

- every journal timestamp, every leg's local quote date and every bundle day passes ``fill_v3_embargo.check``
  (purpose 'descriptive'): the reserved window 2026-09-30..2026-10-15 is refused; a bundle day also passes
  ``export_gate.read_permitted`` before any stream is opened;
- **panel exclusion:** a leg resting on a local quote date inside the shadow/panel window (2026-10-16..2026-11-13)
  is kept only when its band-day ``(condition_id, local_quote_date)`` is in the LFC ``panel_exclusions.jsonl``
  (those band-days are removed from every panel, so reading them reads no panel). Any such leg without an
  exclusion file refuses the run; a leg whose band-day is not excluded is dropped before its fills, prints or
  books are read. A descriptive ``EngineV3`` run applies the same rule (``fill_v3.check_panel``).
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
from maker_core.replay.fill_v3_embargo import PANEL_FIRST, PANEL_LAST, check as embargo_check, local_dates
from maker_core.replay.payloads import Book, Trade, decode

# Research output id, deliberately not in registry form: registering it edits a capture-imported registry
# module, which is roll-sensitive. Register it in a quiet-window change before the output becomes durable.
SCHEMA = "maker-fill-v3-reconcile/0.1"
LABEL = "DESCRIPTIVE"
PURPOSE = "descriptive"
# Attribution window (this module's choice; LFC §1 defines the ratios, not a window). A fill follows the print
# that caused it, so the window looks back FILL_MATCH_SECONDS from the journal's fill time and forward only
# FILL_PRINT_SKEW_SECONDS: an allowance for the clock difference between the 88a ``traded_at`` (venue time) and
# the session host's ``recorded_at_utc`` (local clock). A print later than that cannot have caused the fill.
FILL_MATCH_SECONDS = 120
FILL_PRINT_SKEW_SECONDS = 5
EXCLUSION_FIELDS = ("appended_utc", "condition_ids", "event_slug", "local_quote_date", "session_id")
OUTCOMES = {"yes": "YES", "no": "NO"}
ZERO = Decimal(0)
NO_POOLING = ("LFC pre-registration section 8: these descriptive ratios are never pooled with replay or shadow "
              "results and change nothing except through its pre-declared triggers.")
INTERVAL_NOTE = ("cp95_nominal is an exact Clopper-Pearson 95 % interval that treats prints as independent units; "
                 "prints within one leg are not independent, so it is nominal, not a coverage claim.")


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


# -- the RE-1 journal shape -------------------------------------------------------------------------------
# Mirrors codex/re1-wallet-200-20260923 (tip 2b9a0ca9e): HoldJournal.record writes ROW_ENVELOPE plus the event's
# fields; Session.call(name) writes ``<name>_request`` (request=...) and ``<name>_response`` (response=...);
# cleanup's recover(name) writes ``<name>_unavailable``. A writer change that adds an event makes this adapter
# refuse until the event is classified here.
ROW_ENVELOPE = ("event", "kind", "previous_sha256", "recorded_at_utc", "schema_version", "sequence")
CALL_NAMES = ("accrual", "cancel", "cancel_order_read", "fill_order", "final_accrual", "final_balances", "geoblock",
              "initial_balances", "initial_open_orders", "initial_positions", "open_orders", "opening_snapshot",
              "order", "scoring", "submit", "submit_snapshot")
RECOVER_NAMES = ("cleanup_cancel", "cleanup_cancel_all", "cleanup_open_orders", "terminal_order",
                 "terminal_positions", "terminal_trades")
CANCEL_EVENTS = ("cancel_response", "cleanup_cancel_response", "cleanup_cancel_all_response")
READ_EVENTS = frozenset({"opened", "submit_request", "submit_response", "terminal_order", "fill", "terminal",
                         *CANCEL_EVENTS})
IGNORED_EVENTS = frozenset({
    "selection", "missing_sample", "opening_market_snapshot", "submit_market_snapshot", "market_snapshot",
    "minute", "minute_missed", "user_events", "unmatched_trade_event", "fill_order_unavailable",
    "read_unavailable", "heartbeat_request", "heartbeat_response", "heartbeat_unavailable",
    "heartbeat_v1_acknowledgment", "sdk_request", "sdk_response", "wire_request", "signed_order_book",
    "cleanup_cancel_request", "cleanup_cancel_all_request", "cleanup_open_orders", "terminal_positions",
    "terminal_trades",
    *(name + suffix for name in CALL_NAMES for suffix in ("_request", "_response")),
    *(name + "_unavailable" for name in RECOVER_NAMES)}) - READ_EVENTS
SUBMIT_REQUEST_FIELDS = ("expiration", "post_only", "price", "side", "size", "token_id")
FILL_FORMS = (("rows", "user_event"), ("user_event",), ("order",))
CREDIT_EVENT_TYPES = ("trade", "trade_pending")  # user events that carry order_id and fill_size
# No fill size of their own: a FAILED trade ("rejected", mm_official_adapter), transport fallbacks, order events.
NO_CREDIT_EVENT_TYPES = ("rejected", "unmatched_trade_event", "failed_trade_event", "order", "canceled")


def _first(payload, *names):
    """The writer's ``_value``: the first present, non-empty field."""
    for name in names:
        value = payload.get(name)
        if value is not None and value != "":
            return value
    return None


def _object(value, code):
    if not isinstance(value, dict):
        raise ReconcileError(code)
    return value


def _check_shape(row):
    """Refuse a read event whose fields differ from the writer's."""
    event = row["event"]
    fields = {k: v for k, v in row.items() if k not in ROW_ENVELOPE}
    if event == "opened":
        if not {"mode", "scope"} <= set(fields):
            raise ReconcileError("opened_shape")
        _object(fields["scope"], "journal_scope")
    elif event == "submit_request":
        request = _object(fields.get("request"), "submit_request_shape")
        if set(fields) != {"request"} or tuple(sorted(request)) != SUBMIT_REQUEST_FIELDS:
            raise ReconcileError("submit_request_shape")
    elif event == "submit_response":
        if set(fields) != {"response"}:
            raise ReconcileError("submit_response_shape")
        _object(fields["response"], "submit_response_shape")
    elif event in CANCEL_EVENTS:
        allowed = {"response", "order_id"} if event == "cleanup_cancel_response" else {"response"}
        response = _object(fields.get("response"), "cancel_response_shape")
        canceled = response.get("canceled")
        if (not {"response"} <= set(fields) <= allowed or not isinstance(canceled, list)
                or not all(isinstance(oid, str) and oid for oid in canceled)):
            raise ReconcileError("cancel_response_shape")
    elif event == "terminal_order":
        order = _object(fields.get("order"), "terminal_order_shape")
        if (set(fields) != {"order"} or not isinstance(order.get("id"), str) or not order["id"]
                or not isinstance(order.get("status"), str)):
            raise ReconcileError("terminal_order_shape")
    elif event == "fill":
        if tuple(sorted(fields)) not in FILL_FORMS:
            raise ReconcileError("fill_shape")
        if "user_event" in fields:
            user = _object(fields["user_event"], "fill_user_event_shape")
            kind = user.get("event_type")
            if kind in CREDIT_EVENT_TYPES:
                if (user.get("official_event_type") != "trade" or not isinstance(user.get("order_id"), str)
                        or not user["order_id"]):
                    raise ReconcileError("fill_user_event_shape")
                _d(user.get("fill_size"))
            elif kind not in NO_CREDIT_EVENT_TYPES:
                raise ReconcileError("fill_user_event_shape")
        if "rows" in fields and not (isinstance(fields["rows"], list)
                                     and all(isinstance(r, dict) for r in fields["rows"])):
            raise ReconcileError("fill_shape")
        if "order" in fields:
            _object(fields["order"], "fill_shape")
    elif event == "terminal":
        if fields.get("unknown_submit") is not False:
            raise ReconcileError("journal_unknown_submit")
    else:
        raise ReconcileError("journal_unknown_event")


def parse_journal_rows(raw: bytes) -> list:
    """(at, row) per line, refusing anything the RE-1 writer would not have written.

    Every ``recorded_at_utc`` passes the embargo before any envelope, shape or content check."""
    lines = raw.splitlines(keepends=True)
    rows = []
    for line in lines:
        if not line.strip():
            raise ReconcileError("journal_blank_line")
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ReconcileError("journal_line_not_json") from exc
        if not isinstance(row, dict):
            raise ReconcileError("journal_row_not_object")
        at = _utc(row.get("recorded_at_utc"))
        embargo_check(at, PURPOSE)
        rows.append((at, row))
    if not rows:
        raise ReconcileError("journal_without_opened")
    previous, schema = None, rows[0][1].get("schema_version")
    for index, ((_, row), line) in enumerate(zip(rows, lines)):
        if not set(ROW_ENVELOPE) <= set(row) or row["kind"] != "journal" or not isinstance(row["event"], str):
            raise ReconcileError("journal_row_envelope")
        if not isinstance(schema, str) or not schema or row["schema_version"] != schema:
            raise ReconcileError("journal_schema_version")
        if type(row["sequence"]) is not int or row["sequence"] != index:
            raise ReconcileError("journal_sequence")
        if row["previous_sha256"] != previous:
            raise ReconcileError("journal_chain_broken")
        previous = hashlib.sha256(line).hexdigest()
        if row["event"] in READ_EVENTS:
            _check_shape(row)
        elif row["event"] not in IGNORED_EVENTS:
            raise ReconcileError("journal_unknown_event")
        if (row["event"] == "opened") != (index == 0):
            raise ReconcileError("journal_without_opened")
    if rows[-1][1]["event"] != "terminal" or any(r["event"] == "terminal" for _, r in rows[:-1]):
        raise ReconcileError("journal_without_terminal")
    return rows


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


def read_journal(path, token_outcomes=None) -> Session:
    """Parse one RE-1 session journal (``parse_journal_rows``) into its legs.

    ``token_outcomes`` ({token_id: 'YES' | 'NO'}) declares outcomes the journal itself does not prove."""
    raw = Path(path).read_bytes()
    rows = parse_journal_rows(raw)
    scope = rows[0][1]["scope"]
    condition = str(scope.get("condition_id") or "").lower()
    tokens = scope.get("token_ids")
    if (not condition or not isinstance(tokens, list) or len(tokens) != 2
            or not all(isinstance(t, str) and t for t in tokens) or len(set(tokens)) != 2):
        raise ReconcileError("journal_scope")
    outcomes = _token_outcomes(rows, tokens, token_outcomes)
    legs, pending = {}, None
    for at, row in rows:
        event = row["event"]
        if event == "submit_request":
            if pending is not None:
                raise ReconcileError("submit_request_without_response")
            pending = row["request"]
        elif event == "submit_response":
            if pending is None:
                raise ReconcileError("submit_response_without_request")
            response = row["response"]
            request, pending = pending, None
            oid = str(_first(response, "id", "order_id", "orderID") or "")
            ok = _first(response, "ok", "success")
            if not oid:
                if ok is True:
                    raise ReconcileError("submit_ok_without_order_id")
                continue  # a refused submit: no order exists, so no leg
            if ok is not True:
                raise ReconcileError("submit_response_ambiguous")
            if str(response.get("status", "")).lower() != "live":
                raise ReconcileError("submit_response_not_live")
            if str(request["side"]).upper() != "BUY" or request["post_only"] is not True:
                raise ReconcileError("unsupported_leg_side_or_not_post_only")
            token = str(request["token_id"])
            if token not in outcomes:
                raise ReconcileError("leg_token_outside_scope")
            leg = Leg(oid, token, outcomes[token], condition, _d(request["price"]), _d(request["size"]), at)
            expiration = int(request["expiration"] or 0)
            if expiration > 0:
                leg.expires_at = datetime.fromtimestamp(expiration, tz=timezone.utc)
            if oid in legs:
                raise ReconcileError("duplicate_order_id")
            legs[oid] = leg
        elif event in CANCEL_EVENTS:
            for oid in row["response"]["canceled"]:
                if oid in legs:
                    legs[oid].close(at, "canceled")
        elif event == "terminal_order":
            order = row["order"]
            if order["id"] in legs and order["status"].upper() != "LIVE":
                legs[order["id"]].close(at, "terminal_" + order["status"].lower())
    if pending is not None:
        raise ReconcileError("submit_request_without_response")
    last = rows[-1][0]
    for leg in legs.values():
        if leg.expires_at is not None:
            leg.close(leg.expires_at, "expired")
        leg.close(last, "session_end")
    return Session(Path(path).parent.name, hashlib.sha256(raw).hexdigest(), condition, list(legs.values()),
                   rows, last)


def _token_outcomes(rows, tokens, declared=None):
    """token_id -> YES/NO from the journal's own order and fill rows, plus any explicit declaration.

    The scope's token order proves nothing: with neither a journal proof nor a declaration this refuses."""
    seen = {}

    def note(token, outcome):
        if token in tokens and outcome is not None:
            if seen.setdefault(token, outcome) != outcome:
                raise ReconcileError("conflicting_token_outcome")

    for _, row in rows:
        items = []
        if row["event"] == "terminal_order":
            items.append(row["order"])
        elif row["event"] == "fill":
            items.extend(row.get("rows") or ())
            if isinstance(row.get("order"), dict):
                items.append(row["order"])
            event = row.get("user_event") or {}
            items.append({"token_id": event.get("clob_token_id"), "outcome": event.get("outcome")})
        for item in items:
            note(str(_first(item, "token_id", "asset_id")), OUTCOMES.get(str(item.get("outcome", "")).lower()))
    for token, outcome in (declared or {}).items():
        if outcome not in ("YES", "NO"):
            raise ReconcileError("token_outcome_value")
        if token not in tokens:
            raise ReconcileError("token_outcome_outside_scope")
        note(token, outcome)
    if not seen:
        raise ReconcileError("token_outcomes_unproven")
    token = min(seen)  # any proven token fixes both: the other is its complement
    other = tokens[1] if token == tokens[0] else tokens[0]
    result = {token: seen[token], other: "NO" if seen[token] == "YES" else "YES"}
    if any(result[t] != o for t, o in seen.items()):
        raise ReconcileError("conflicting_token_outcome")
    return result


def attach_fills(session: Session, legs) -> None:
    """Read own fills for the admitted ``legs`` only: credit-bearing ``fill`` user events (``fill_size``), then
    any terminal ``size_matched`` residual. Other fill evidence (order events, rejected, unmatched or failed trade
    events, order reads) carries no fill size of its own and is covered by the terminal residual.

    A terminal ``size_matched`` below the credited fills (a ``trade_pending`` that later failed) refuses
    (``credited_exceeds_size_matched``): the journal then contradicts itself about the leg's fills."""
    wanted = {leg.order_id: leg for leg in legs}
    matched = {}
    for at, row in session.rows:
        if row["event"] == "fill":
            event = row.get("user_event") or {}
            oid = str(event.get("order_id") or "")
            if event.get("event_type") in CREDIT_EVENT_TYPES and oid in wanted:
                wanted[oid].fills.append((at, _d(event["fill_size"]), "fill_event"))
        elif row["event"] == "terminal_order":
            order = row["order"]
            if order["id"] in wanted:
                matched[order["id"]] = (at, _d(order.get("size_matched") or 0))
    for oid, (at, size) in matched.items():
        leg = wanted[oid]
        residual = size - sum((s for _, s, _ in leg.fills), ZERO)
        if residual < 0:
            raise ReconcileError("credited_exceeds_size_matched")
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
                "N": self.n, "k_prints_with_own_fill": self.k, "cp95_nominal": clopper_pearson(self.k, self.n)}


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


def attribute_fills(fills, prints) -> list:
    """The own-fill size attributed to each print (aligned with ``prints``, sorted by ``(traded_at, trade_id)``).

    Each fill goes to the one print with minimum ``|traded_at - fill_at|`` inside ``fill_at - FILL_MATCH_SECONDS
    <= traded_at <= fill_at + FILL_PRINT_SKEW_SECONDS``; ties go to the earlier print. A fill with no print in
    its window stays unattributed."""
    attributed = [ZERO] * len(prints)
    for fill_at, fill_size, _ in fills:
        best = None
        for index, trade in enumerate(prints):
            delta = (trade.traded_at - fill_at).total_seconds()
            if -FILL_MATCH_SECONDS <= delta <= FILL_PRINT_SKEW_SECONDS:
                key = abs(delta), trade.traded_at, index
                if best is None or key < best:
                    best = key
        if best is not None:
            attributed[best[2]] += fill_size
    return attributed


def _lfc_ratios(leg, trades, at_ratio, thr_ratio):
    """LFC §1 ratios on the leg's token: prints at / strictly below our bid, each fill attributed once."""
    prints = [t for t in trades if t.outcome == leg.outcome and t.price <= leg.price]
    filled_before = ZERO
    for trade, own in zip(prints, attribute_fills(leg.fills, prints)):
        remaining = leg.size - filled_before
        if remaining <= 0:
            continue
        ratio = at_ratio if trade.price == leg.price else thr_ratio
        ratio.add(own, min(trade.size, remaining))
        filled_before += own


def terciles(values):
    """Rank cut points (ceil(n/3), ceil(2n/3)) over sorted values; ties stay in the lower tercile."""
    ordered = sorted(values)
    if not ordered:
        return None
    n = len(ordered)
    return ordered[math.ceil(n / 3) - 1], ordered[math.ceil(2 * n / 3) - 1]


def reconcile(journals, bundles, *, time_zone_name, exclusions_path=None, token_outcomes=None) -> dict:
    zone = time_zone(time_zone_name)
    exclusions = None if exclusions_path is None else load_panel_exclusions(exclusions_path)
    sessions = [read_journal(path, token_outcomes) for path in journals]
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
    at_all, thr_all = Ratio(), Ratio()
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
        _lfc_ratios(leg, trades, leg_at, thr_all)
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
            "no_pooling": NO_POOLING, "interval_note": INTERVAL_NOTE, "time_zone": time_zone_name,
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


def parse_token_outcomes(values) -> dict | None:
    """``TOKEN_ID=YES|NO`` declarations as {token_id: outcome}; None when there are none."""
    result = {}
    for value in values:
        token, sep, outcome = str(value).partition("=")
        if not sep or not token or outcome.upper() not in ("YES", "NO"):
            raise ReconcileError("token_outcome_value")
        if result.setdefault(token, outcome.upper()) != outcome.upper():
            raise ReconcileError("conflicting_token_outcome")
    return result or None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m maker_core.replay.fill_v3_reconcile",
                                     description="DESCRIPTIVE own-session reconciliation of the replay fill rules.")
    parser.add_argument("--journal", type=Path, action="append", required=True, help="session journal.jsonl")
    parser.add_argument("--bundle", type=Path, action="append", required=True, help="replay bundle directory")
    parser.add_argument("--time-zone", required=True, help="IANA zone of the sessions' markets (local quote date)")
    parser.add_argument("--panel-exclusions", type=Path, help="LFC panel_exclusions.jsonl (required for legs "
                                                              "on 2026-10-16..2026-11-13 local dates)")
    parser.add_argument("--token-outcomes", action="append", default=[], metavar="TOKEN_ID=YES|NO",
                        help="declare a token's outcome when the journal does not prove it (repeatable)")
    parser.add_argument("--output", type=Path, required=True, help="new JSON file (never overwritten)")
    args = parser.parse_args(argv)
    result = reconcile(args.journal, args.bundle, time_zone_name=args.time_zone,
                       exclusions_path=args.panel_exclusions, token_outcomes=parse_token_outcomes(args.token_outcomes))
    with args.output.open("xb") as handle:
        handle.write(encode(result))
    print(json.dumps({"label": LABEL, "legs": len(result["legs"]), "c_at": result["c_at"],
                      "c_thr": result["c_thr"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
