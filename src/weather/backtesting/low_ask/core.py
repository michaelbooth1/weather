"""Deterministic received-time policy and limited-cash paper ledger.

All return values are private to the unattended process. Only the runner may
persist them, through the public-key seal. No I/O or client object is accepted.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo

from weather.market.metar_reports import parse_metar
from weather.market.venue_settlement_rules import settlement_bucket

from .contracts import (CAPS, CITIES, SHARES, canonical, digest, exact, identity,
                        instant, iso, number, require, schedule, sha)


def event_check(event: dict) -> None:
    exact(event, "city family target_date event_id received_utc rule_received_utc rule_sha256 "
          "rule_status source station unit zone rounding parser_sha256 fallback_required "
          "source_verified active bins")
    city, _ = identity(event)
    zone, station, unit = CITIES[city]
    require((event["zone"], event["unit"]) == (zone, unit), "rule_zone_unit")
    # A dated source/station change is a skipped opportunity, never a registry fallback.
    require(isinstance(event["event_id"], str) and bool(event["event_id"]), "event_identity")
    for key in ("rule_sha256", "parser_sha256"):
        sha(event[key])
    for key in ("received_utc", "rule_received_utc"):
        instant(event[key])
    for key in ("fallback_required", "source_verified", "active"):
        require(type(event[key]) is bool, "event_boolean")
    require(isinstance(event["bins"], list) and 1 <= len(event["bins"]) <= 100, "bins")
    tokens = set()
    for band in event["bins"]:
        exact(band, "band_id yes_token lower upper lower_closed upper_closed tick min_size")
        require(all(isinstance(band[k], str) and band[k] for k in ("band_id", "yes_token")), "bin_identity")
        require(band["yes_token"] not in tokens, "duplicate_token")
        tokens.add(band["yes_token"])
        require(type(band["lower_closed"]) is bool and type(band["upper_closed"]) is bool, "bin_boundary")
        lower = None if band["lower"] is None else number(band["lower"])
        upper = None if band["upper"] is None else number(band["upper"])
        require(lower is None or upper is None or lower <= upper, "bin_order")
        require(0 < number(band["tick"]) <= 1 and number(band["min_size"]) > 0, "venue_size_tick")


def running_minimum(event: dict, observations: list[dict], cut: datetime):
    """Retain all first-seen reports; replace only the same source report key.

    Local hours mean distinct wall-clock hours (the repeated DST hour counts
    once). Revisions with identical source sequence and different raw bytes are
    ambiguous. A correction received later than cut cannot affect this call.
    """
    zone = ZoneInfo(event["zone"])
    city, day = identity(event)
    source = event["source"]
    if (event["rule_status"] != "reviewed" or not event["source_verified"]
            or (event["fallback_required"] and source != "wu_intraday")
            or event["rounding"] != "ties_to_higher_integer"
            or source not in {"metar_routine", "wu_intraday"}
            or (source == "metar_routine" and event["station"] != CITIES[city][1])):
        return None, "source_rule"
    selected = {}
    first_seen = {}
    for row in observations:
        received = instant(row["received_utc"])
        if received > cut or row["event_id"] != event["event_id"]:
            continue
        observed = instant(row["observed_utc"])
        if observed > cut or observed.astimezone(zone).date() != day:
            continue
        if row["source"] != source or row["station"] != event["station"]:
            continue
        require(row["parser_sha256"] == event["parser_sha256"], "parser_binding")
        require(row["report_key"] == iso(observed), "report_key")
        if source == "metar_routine":
            parsed = parse_metar(row["raw"], observed - timedelta(seconds=1),
                                 observed + timedelta(seconds=1), receipt_time=received,
                                 station_ids=(event["station"],))
            if parsed.report_kind == "SPECI":
                continue
        raw_key = (row["report_key"], tuple(row["raw"].split()))
        known_receipt = first_seen.setdefault(raw_key, received)
        require(known_receipt == received, "first_seen_identity")
        rank = (received, row["source_sequence"])
        old = selected.get(row["report_key"])
        if old is not None and old[0] == rank:
            require(old[1] == row, "ambiguous_revision")
        if old is None or rank > old[0]:
            selected[row["report_key"]] = rank, row
    values = []
    for _, row in selected.values():
        observed = instant(row["observed_utc"])
        if row["status"] != "valid":
            return None, "observation_defect"
        if source == "metar_routine":
            parsed = parse_metar(row["raw"], observed - timedelta(seconds=1),
                                 observed + timedelta(seconds=1),
                                 receipt_time=instant(row["received_utc"]),
                                 station_ids=(event["station"],))
            if not parsed.routine:
                continue
            if parsed.station != event["station"] or parsed.observation_time != observed or parsed.temperature_c is None:
                return None, "observation_defect"
            value = Decimal(settlement_bucket(parsed.temperature_c, event["unit"]))
        else:
            # WU adapter may emit only received station prints in native units.
            require(row["native_value"] is not None, "wu_print")
            value = (number(row["native_value"]) + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)
        values.append((observed, value))
    hours = {t.astimezone(zone).hour for t, _ in values}
    if len(hours) < 12 or not hours.intersection(range(6)) or not hours.intersection(range(6, 12)):
        return None, "observation_coverage"
    if cut - max(t for t, _ in values) > timedelta(minutes=90):
        return None, "observation_stale"
    return min(v for _, v in values), None


def select_band(event: dict, value: Decimal):
    matches = []
    for band in event["bins"]:
        lower, upper = band["lower"], band["upper"]
        if lower is not None and (value < number(lower) or (value == number(lower) and not band["lower_closed"])):
            continue
        if upper is not None and (value > number(upper) or (value == number(upper) and not band["upper_closed"])):
            continue
        matches.append(band)
    return matches[0] if len(matches) == 1 else None


def heartbeat_ok(rows: list[dict], token: str, start: datetime, end: datetime) -> bool:
    times = sorted({instant(r["received_utc"]) for r in rows
                    if r["yes_token"] == token and r["ok"] and instant(r["received_utc"]) <= end})
    before = [t for t in times if t <= start]
    if not before or start - before[-1] > timedelta(seconds=90):
        return False
    trail = [before[-1], *(t for t in times if start < t <= end), end]
    if any(b - a > timedelta(seconds=90) for a, b in zip(trail, trail[1:])):
        return False
    return not any(r["yes_token"] == token and not r["ok"]
                   and start <= instant(r["received_utc"]) <= end for r in rows)


def candidate(event: dict, rows: dict, cut: datetime, hour: int, latency: Decimal, as_of: datetime):
    base = {"city": event["city"], "target_date": event["target_date"], "cut": hour,
            "decision_utc": iso(cut), "event_id": event["event_id"], "status": "skip"}
    if max(instant(event["received_utc"]), instant(event["rule_received_utc"])) > cut:
        return dict(base, reason="late_event_rule"), None
    value, reason = running_minimum(event, rows["observations"], cut)
    if reason:
        return dict(base, reason=reason), None
    band = select_band(event, value)
    if band is None:
        return dict(base, reason="ambiguous_band"), None
    if number(band["min_size"]) > SHARES:
        return dict(base, reason="minimum_size"), None
    start = cut + timedelta(seconds=float(latency))
    end = start + timedelta(seconds=60)
    books = [b for b in rows["books"] if b["event_id"] == event["event_id"]
             and b["yes_token"] == band["yes_token"] and b["full"]
             and start <= instant(b["received_utc"]) <= min(end, as_of)]
    if not books:
        return dict(base, status="pending" if as_of < end else "skip", reason="book_missing"), None
    # First full receipt is final even when stale, invalid, expensive or too small.
    book = min(books, key=lambda b: (instant(b["received_utc"]), b["sequence"]))
    executed = instant(book["received_utc"])
    lag = executed - instant(book["response_utc"])
    if (not book["active"] or not book["integrity_ok"] or lag < timedelta(0) or lag > timedelta(seconds=2)
            or abs(instant(book["exchange_utc"]) - instant(book["response_utc"])) > timedelta(seconds=1)
            or not heartbeat_ok(rows["heartbeats"], band["yes_token"], cut - timedelta(seconds=60), executed)):
        return dict(base, reason="book_integrity"), None
    if any(not r["ok"] and r["book_id"] == book["book_id"] and instant(r["received_utc"]) <= executed
           for r in rows.get("integrity", [])):
        return dict(base, reason="book_integrity"), None
    asks = [(number(p), number(s)) for p, s in book["asks"]]
    if not asks:
        return dict(base, reason="no_ask"), None
    ask, size = asks[0]
    if ask % number(band["tick"]) != 0:
        return dict(base, reason="tick"), None
    if ask + Decimal("0.01") >= 1:
        return dict(base, reason="price_limit"), None
    if size < SHARES:
        return dict(base, reason="partial_fill_refused"), None
    fee = Decimal("0.05") * ask * (1 - ask)
    reserve = Decimal("0.01")  # Exactly five at best ask: depth walk is zero.
    cost = SHARES * (ask + fee + reserve)
    return dict(base, status="candidate", execution_utc=iso(executed),
                book_id=book["book_id"], band_id=band["band_id"], yes_token=band["yes_token"],
                ask=str(ask), displayed_size=str(size), fee_per_share=str(fee),
                reserve_per_share=str(reserve), cost=str(cost), shares=str(SHARES),
                rule_sha256=event["rule_sha256"]), book


def simulate(rows: dict, *, as_of: datetime, latency_seconds: Decimal) -> dict:
    """Replay a cumulative manifest in global UTC order. No reset between dates.

    Resolution cash is available only at max(venue effective time, capture
    receipt time). Corrections can debit cash; negative cash blocks new fills.
    The total cap limits cash at risk, including gains, to $300.
    """
    require(latency_seconds >= 30, "latency_floor")
    events = {}
    for event in rows["events"]:
        event_check(event)
        key = identity(event)
        require(key not in events, "duplicate_city_day")
        events[key] = event
    indexed = {role: defaultdict(list) for role in ("observations", "books", "heartbeats", "integrity")}
    for role, groups in indexed.items():
        for row in rows[role]:
            groups[row["event_id"]].append(row)
    decisions, pending = [], []
    for city, day, hour, cut in schedule(as_of):
        event = events.get((city, day))
        if event is None:
            decisions.append({"city": city, "target_date": day.isoformat(), "cut": hour,
                              "decision_utc": iso(cut), "status": "skip", "reason": "event_missing"})
            continue
        event_rows = {role: groups[event["event_id"]] for role, groups in indexed.items()}
        decision, book = candidate(event, event_rows, cut, hour, latency_seconds, as_of)
        if book is None:
            decisions.append(decision)
        else:
            pending.append(decision)
    pending.sort(key=lambda d: (instant(d["execution_utc"]), d["city"], d["cut"]))
    resolutions = sorted((r for r in rows["resolutions"] if instant(r["received_utc"]) <= as_of),
                         key=lambda r: (max(instant(r["received_utc"]), instant(r["effective_utc"])),
                                        r["event_id"], r["revision"]))
    cash, locked = Decimal(CAPS["total"]), Decimal(0)
    used, band_locked, daily_cost = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    positions, latest, resolution_index = [], {}, 0

    def settle(until):
        nonlocal cash, locked, resolution_index
        while resolution_index < len(resolutions):
            row = resolutions[resolution_index]
            available = max(instant(row["received_utc"]), instant(row["effective_utc"]))
            if available > until:
                break
            resolution_index += 1
            key = (row["event_id"], row["yes_token"])
            previous = latest.get(key)
            require(previous is None or row["revision"] > previous["revision"], "resolution_order")
            latest[key] = row
            if not row["final"]:
                continue
            for position in positions:
                if (position["event_id"], position["yes_token"]) != key:
                    continue
                payout = SHARES * number(row["payout_per_share"])
                cash += payout - number(position.get("paid", "0"))
                position["paid"] = str(payout)
                position["resolution_utc"] = iso(available)
                position["resolution_sha256"] = row["evidence_sha256"]
                if position["status"] == "filled":
                    locked -= number(position["cost"])
                    band_locked[key] -= number(position["cost"])
                position["status"] = "resolved"

    for decision in pending:
        executed = instant(decision["execution_utc"])
        settle(executed)
        cost = number(decision["cost"])
        key = (decision["event_id"], decision["yes_token"])
        daily_key = (*key, decision["target_date"])
        reason = None
        if key in latest:
            reason = "already_resolving"
        elif used[decision["book_id"]] + SHARES > number(decision["displayed_size"]):
            reason = "depth_reuse"
        elif (cost > number(CAPS["order"]) or band_locked[key] + cost > number(CAPS["band"])
              or daily_cost[daily_key] + cost > number(CAPS["band_day"])):
            reason = "market_cap"
        elif cash < cost or locked + cost > number(CAPS["total"]):
            reason = "cash_cap"
        if reason:
            decision.update(status="skip", reason=reason)
        else:
            cash -= cost
            locked += cost
            used[decision["book_id"]] += SHARES
            band_locked[key] += cost
            daily_cost[daily_key] += cost
            decision["status"] = "filled"
            positions.append(decision)
        decisions.append(decision)
    settle(as_of)
    defects = {r["book_id"] for r in rows["integrity"] if not r["ok"] and instant(r["received_utc"]) <= as_of}
    doubtful = 0
    for position in positions:
        if position["book_id"] in defects:
            position["integrity_defect"] = True
            doubtful += 1
        # Unknown or doubtful payouts are ZERO in the conservative final panel.
        final = latest.get((position["event_id"], position["yes_token"]), {}).get("final", False)
        if not final and position["status"] == "resolved":
            position["integrity_defect"] = True
            doubtful += 1
        paid = Decimal(0) if position.get("integrity_defect") else number(position.get("paid", "0"))
        position["conservative_net"] = str(paid - number(position["cost"]))
    decisions.sort(key=lambda d: (d["target_date"], d["city"], d["cut"]))
    result = {"decisions": decisions, "cash": str(cash), "locked": str(locked),
              "unresolved": sum(p["status"] == "filled" for p in positions),
              "doubtful_fills": doubtful,
              "net_lower": str(sum((number(p["conservative_net"]) for p in positions), Decimal(0)))}
    result["replay_sha256"] = digest(canonical(result))
    return result
