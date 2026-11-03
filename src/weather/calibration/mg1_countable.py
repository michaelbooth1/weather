r"""MG-1 countability, counts-only (master ruling R11 Head 2; 2026-11-03 rulings A3 and T5).

Host, research only. Master runs it under the lease: P1 (2026-11-14) and P2 (11-27) in report mode, P3 (the
first admitted morning at least two days after the 45th date) with ``--final``. It reads only the settlement
ledger's stored ``promotion_countable`` (latest revision per market-date, ``settlement_ledger``'s readers) for
the support markets ``mg1_look.MARKETS`` (A1 is the owner's open question; the support set is that one
constant). It never reads a label, a price, a settlement value or a panel.

* **Date rule (R11 (1), A3).** Local date D counts toward MG-1's 45 iff at least one support market-day has
  ``promotion_countable`` true in the ledger's latest revision. A market-day with no ledger row is *pending*;
  a market-day with rows for more than one event is not countable. A date with no countable market-day and at
  least one pending one is pending; pending counts as non-countable in ``--final`` (DL:226).
* **Report mode** prints, per calendar date from D0 through the latest date that has ended in every support
  market, its status only (``countable`` / ``non_countable`` / ``pending``), the required ``MG1_LAST``, whether
  the recorded ``MG1_LAST`` must move, each market ledger's sha256 and the run time. Nothing per market.
* **--final** writes the ``mg1_countable/1`` list (``mg1_look.read_countable``'s format) from D0 through the
  45th countable date with ``markets{m: bool}`` per date (true iff that market-day is countable; pending is
  false) and both Clarification 1 caveats, which have no wired outcome-blind source and are therefore null with
  a recorded reason. It goes through ``mg1_look.write_countable`` (the L8 scoring head) and refuses until that
  head has landed.

Refusals: before 2026-11-14T00:00Z, on a date that has not ended in every support market, on a final list
whose 45th date is after the recorded ``MG1_LAST`` (extend first, R11 (4)), and on ``--final`` earlier than two
days after the 45th date.

    python -m weather.calibration.mg1_countable --ledger-root <settlements root> [--final --out <file>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

_PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                        "weather.trading", "weather.capture", "weather.sources", "weather.execution",
                        "maker_core", "app")


def _refuse_production_import():
    """Fail closed when imported from a production package."""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.mg1_countable is research-only; imported from {name}")
        frame = frame.f_back


_refuse_production_import()

from weather.schema_families import schema_version  # noqa: E402

NAME = "mg1_countable"
REPORT_SCHEMA = schema_version("mg1_countable_report")
NOT_BEFORE_UTC = datetime(2026, 11, 14, tzinfo=timezone.utc)  # R11 (3): P1, after the panel closed
FINAL_MIN_DAYS_AFTER = 2  # R11 (3): P3 runs at least two days after the 45th date
COUNTABLE, NON_COUNTABLE, PENDING = "countable", "non_countable", "pending"
CAVEAT_REASON = "no outcome-blind source is wired for this flag (R11 unresolved); null by ruling"


class CountableRefused(RuntimeError):
    """Nothing was written."""

    exit_code = 2


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_sha256():
    return sha256_file(__file__)


def support_markets():
    from weather.calibration import mg1_look

    return tuple(mg1_look.MARKETS)


def market_tz():
    from weather.calibration import mg1_look

    return {m: mg1_look.MARKET_TZ[m] for m in support_markets()}


def ended_at(day):
    """The instant ``day`` has ended in every support market."""
    from zoneinfo import ZoneInfo

    nxt = day + timedelta(days=1)
    return max(datetime.combine(nxt, time(0), ZoneInfo(tz)).astimezone(timezone.utc) for tz in market_tz().values())


def _jsonl_rows(raw):
    rows = []
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def market_day_flags(ledger_root, days, markets):
    """Per (market, ISO date): True / False from the latest revision, or None (pending: no ledger row).

    Each market ledger is read once from bytes whose sha256 is returned. Only ``event_slug``, ``target_date``,
    ``revision_number`` and ``promotion_countable`` are used.
    """
    from weather.backtesting import settlement_ledger as sl

    wanted = {d.isoformat() for d in days}
    flags, shas = {}, {}
    for market in markets:
        path = sl.ledger_path_for_market(market, ledger_root)
        if not path.is_file():
            raise CountableRefused(f"settlement ledger missing for {market}: {path}")
        raw = path.read_bytes()
        shas[market] = hashlib.sha256(raw).hexdigest()
        rows = [r for r in _jsonl_rows(raw) if str(r.get("target_date") or "")[:10] in wanted]
        events = {}
        for r in rows:
            events.setdefault(str(r.get("target_date"))[:10], set()).add(r.get("event_slug"))
        for day in sorted(wanted):
            slugs = events.get(day, set())
            if not slugs:
                flags[(market, day)] = None
            elif len(slugs) > 1:
                flags[(market, day)] = False
            else:
                latest = sl.current_ledger_label(rows, next(iter(slugs)))
                flags[(market, day)] = bool(latest) and latest.get("promotion_countable") is True
    return flags, shas


def date_status(flags, day, markets):
    """A3: countable iff at least one support market-day is countable; else pending if any is pending."""
    values = [flags.get((m, day)) for m in markets]
    if any(v is True for v in values):
        return COUNTABLE
    return PENDING if any(v is None for v in values) else NON_COUNTABLE


def plan(statuses, d0, n_dates):
    """``(counted, required_last)``: the countable dates (at most ``n_dates``) and the date MG1_LAST must reach.

    When fewer than ``n_dates`` dates have counted, every later date is assumed countable (the earliest
    possible 45th date); pending counts as non-countable.
    """
    counted = [d for d, s in statuses if s == COUNTABLE][:n_dates]
    if len(counted) == n_dates:
        return counted, counted[-1]
    last_seen = statuses[-1][0] if statuses else d0 - timedelta(days=1)
    return counted, last_seen + timedelta(days=n_dates - len(counted))


def _window():
    from weather import mg1_reserved_window as w

    start, last = w.window()
    if last is None:
        raise CountableRefused("the MG-1 window is not recorded")
    return start, last


def _ended_dates(start, now):
    days, day = [], start
    while ended_at(day) <= now:
        days.append(day)
        day += timedelta(days=1)
    return days


def report(*, ledger_root, now=None):
    """Report mode: per-date status only, the required MG1_LAST and the ledger shas."""
    from weather.calibration import mg1_look

    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    if now < NOT_BEFORE_UTC:
        raise CountableRefused(f"MG-1 countability opens at {NOT_BEFORE_UTC.isoformat()} (R11 (3), P1)")
    d0, recorded_last = _window()
    days = _ended_dates(d0, now)
    if not days:
        raise CountableRefused(f"no date from D0 {d0} has ended in every support market")
    markets = support_markets()
    flags, shas = market_day_flags(ledger_root, days, markets)
    statuses = [(d, date_status(flags, d.isoformat(), markets)) for d in days]
    counted, required = plan(statuses, d0, mg1_look.N_DATES)
    return {
        "schema": REPORT_SCHEMA, "run_utc": now.isoformat(), "d0": d0.isoformat(),
        "through": days[-1].isoformat(), "rule": "A3: at least one support market-day promotion_countable",
        "support_market_count": len(markets),
        "dates": [{"date": d.isoformat(), "status": s} for d, s in statuses],
        "counts": {k: sum(1 for _, s in statuses if s == k) for k in (COUNTABLE, NON_COUNTABLE, PENDING)},
        "countable_reached": len(counted), "required_mg1_last": required.isoformat(),
        "recorded_mg1_last": recorded_last.isoformat(), "extend_mg1_last": required > recorded_last,
        "ledger_sha256": shas, "module_sha256": module_sha256(), "host": socket.gethostname(),
    }


def final_body(*, ledger_root, now=None):
    """The ``mg1_countable/1`` body from D0 through the 45th countable date, with per-market masks."""
    from weather.calibration import mg1_look

    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    if now < NOT_BEFORE_UTC:
        raise CountableRefused(f"MG-1 countability opens at {NOT_BEFORE_UTC.isoformat()} (R11 (3), P1)")
    d0, recorded_last = _window()
    days = _ended_dates(d0, now)
    markets = support_markets()
    flags, shas = market_day_flags(ledger_root, days, markets)
    statuses = [(d, date_status(flags, d.isoformat(), markets)) for d in days]
    counted, required = plan(statuses, d0, mg1_look.N_DATES)
    if len(counted) < mg1_look.N_DATES:
        raise CountableRefused(f"only {len(counted)} countable dates among the ended dates; no final list yet")
    last = counted[-1]
    if last > recorded_last:
        raise CountableRefused(f"the 45th countable date {last} is after the recorded MG1_LAST {recorded_last}: "
                               "extend the window first (R11 (4))")
    if now.date() < last + timedelta(days=FINAL_MIN_DAYS_AFTER):
        raise CountableRefused(f"--final runs at least {FINAL_MIN_DAYS_AFTER} days after the 45th date {last}")
    rows = []
    for d, s in statuses:
        if d > last:
            break
        rows.append({"date": d.isoformat(), "promotion_countable": s == COUNTABLE,
                     "parser_v2_verified": None, "shadow_stage_captured": None,
                     "markets": {m: flags.get((m, d.isoformat())) is True for m in markets}})
    return {
        "schema": mg1_look.COUNTABLE_SCHEMA, "dates": rows,
        "caveats": {"parser_v2_verified": CAVEAT_REASON, "shadow_stage_captured": CAVEAT_REASON},
        "rule": "A3: at least one support market-day promotion_countable; pending counts as non-countable",
        "support_markets": list(markets), "ledger_root": str(ledger_root), "ledger_sha256": shas,
        "written_at_utc": now.isoformat(), "writer": {"module": f"weather.calibration.{NAME}",
                                                      "source_sha256": module_sha256(),
                                                      "host": socket.gethostname()},
    }


def final(*, ledger_root, out, now=None):
    """--final: write the list through ``mg1_look.write_countable`` (refuses until the L8 head has landed)."""
    from weather.calibration import mg1_look

    writer = getattr(mg1_look, "write_countable", None)
    if writer is None:
        raise CountableRefused("mg1_look.write_countable is absent: the L8 scoring head has not landed")
    if Path(out).exists():
        raise CountableRefused(f"{out} exists: the final list is written once")
    body = final_body(ledger_root=ledger_root, now=now)
    writer(out, body)
    return {"status": "ok", "out": str(out), "sha256": sha256_file(out), "dates": len(body["dates"]),
            "last": body["dates"][-1]["date"]}


def build_parser():
    parser = argparse.ArgumentParser(prog=f"python -m weather.calibration.{NAME}", description=__doc__.split("\n")[0])
    parser.add_argument("--ledger-root", required=True)
    parser.add_argument("--final", action="store_true", help="write the mg1_countable/1 list (P3)")
    parser.add_argument("--out", help="the final list's path (with --final)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.final:
            if not args.out:
                raise CountableRefused("--final needs --out")
            result = final(ledger_root=args.ledger_root, out=args.out)
        else:
            result = report(ledger_root=args.ledger_root)
    except CountableRefused as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return exc.exit_code
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
