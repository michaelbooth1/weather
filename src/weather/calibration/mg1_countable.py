r"""MG-1 outcome-blind countability (owner-approved Clarification 4, 2026-11-06).

Research only. The primary uses the latest unique event's admitted material coverage, closed/one-winner
metadata and the look-morning R24 frozen label key, never WU reconciliation or the winning band's identity.
A date counts iff at least one support market-day qualifies. A missing row is pending; multiple event slugs are
non-countable. Pending is false in the final mask. Report mode emits date statuses and provenance only.

Both modes require frozen key metadata; P1/P2 may use immutable mg1-countability-* preview freezes, leaving
the one mg1 look freeze for P3 after 45 dates are ready. Before metadata exists they refuse. No CSV,
label, price or panel is parsed. The final writer alone freezes the old promotion flags separately for the
NONDECIDING sensitivity within the primary population. It writes mg1_countable/2 once through write_countable,
binding the exact freeze receipt and ledger hashes, with the Clarification 1 caveats null with a reason.

Refuses before P1 (2026-11-14), before 45 primary dates exist in frozen keys, when MG1_LAST needs extension,
or for a final list before 2026-11-30 / two local days after the actual 45th date. MG1_LAST never shortens.

    python -m weather.calibration.mg1_countable --ledger-root <frozen ledgers> --label-freeze <receipt> [--final --out <file>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
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
COUNTABLE, NON_COUNTABLE, PENDING = "countable", "non_countable", "pending"
CAVEAT_REASON = "no outcome-blind source is wired for this flag (R11 unresolved); null by ruling"
PREVIEW_LOOK_PREFIX = "mg1-countability-"


class CountableRefused(RuntimeError):
    """Nothing was written."""

    exit_code = 2


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_sha256():
    return sha256_file(__file__)


def support_markets():
    """MG-1's support markets under the owner's A1 constant (``mg1_look.support_markets``)."""
    from weather.calibration import mg1_look

    return tuple(mg1_look.support_markets())


def ended_at(day):
    """The instant ``day`` has ended in every support market (``mg1_look.settled_at``)."""
    from weather.calibration import mg1_look

    return mg1_look.settled_at(day, support_markets())


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


def market_day_flags(ledger_root, days, markets, label_keys, *, sensitivity_flags=None):
    """Primary flags from coverage, closed/one-winner metadata and frozen label keys (Clarification 4).

    No winner identity, bucket or reconciliation status enters the primary. Only the final writer requests
    ``sensitivity_flags``: the old promotion flags, frozen separately for NONDECIDING reporting at the look.
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
            latest = None
            slugs = events.get(day, set())
            if not slugs:
                flags[(market, day)] = None
            elif len(slugs) > 1:
                flags[(market, day)] = False
            else:
                latest = sl.current_ledger_label(rows, next(iter(slugs)))
                reconciliation = (latest or {}).get("polymarket_reconciliation") or {}
                winners = reconciliation.get("winning_markets")
                flags[(market, day)] = bool(
                    latest and latest.get("material_coverage_grade") in sl.MATERIAL_COUNTABLE_COVERAGE_GRADES
                    and reconciliation.get("event_closed") is True
                    and isinstance(winners, list) and len(winners) == 1
                    and day in label_keys[market])
            if sensitivity_flags is not None:
                # This branch never selects a date or a primary row. Freeze only the intersection; a legacy
                # true flag cannot admit a market-day rejected by the primary.
                sensitivity_flags[(market, day)] = (flags[(market, day)] is True
                                                    and latest.get("promotion_countable") is True)
    return flags, shas


def frozen_keys(label_freeze, now, *, allow_preview=False):
    """Validate the R24 freeze and key metadata without calling a label reader or parsing a CSV."""
    from weather.calibration import mg1_look

    try:
        raw = json.loads(Path(label_freeze).read_text(encoding="utf-8"))
        through = datetime.fromisoformat(raw["through"]).date()
        frozen = datetime.fromisoformat(raw["frozen_at_utc"].replace("Z", "+00:00"))
        if frozen.tzinfo is None or frozen > now:
            raise CountableRefused("the label freeze is future-dated or lacks a timezone")
        look_id = raw.get("look_id")
        expected = (look_id if allow_preview and isinstance(look_id, str)
                    and look_id.startswith(PREVIEW_LOOK_PREFIX) else mg1_look.FREEZE_LOOK_ID)
        freeze = mg1_look.read_freeze_receipt(label_freeze, through, mg1_look.settled_at(through), look_id=expected)
        mg1_look.label_key_check(freeze, [])  # consistency checks, with no countable population yet
    except (OSError, KeyError, TypeError, ValueError, mg1_look.MG1LookRefused) as exc:
        raise CountableRefused(f"frozen label keys unavailable: {exc}") from exc
    return {m: set(freeze["keys"][m][mg1_look.FREEZE_LABEL_KEYS]) for m in support_markets()}, freeze


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


def report(*, ledger_root, label_freeze, now=None):
    """Report mode: per-date status only, the required MG1_LAST and the ledger shas."""
    from weather.calibration import mg1_look

    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    if now < NOT_BEFORE_UTC:
        raise CountableRefused(f"MG-1 countability opens at {NOT_BEFORE_UTC.isoformat()} (R11 (3), P1)")
    d0, recorded_last = _window()
    keys, freeze = frozen_keys(label_freeze, now, allow_preview=True)
    days = [d for d in _ended_dates(d0, now) if d.isoformat() <= freeze["through"]]
    if not days:
        raise CountableRefused(f"no date from D0 {d0} has ended in every support market")
    markets = support_markets()
    flags, shas = market_day_flags(ledger_root, days, markets, keys)
    statuses = [(d, date_status(flags, d.isoformat(), markets)) for d in days]
    counted, required = plan(statuses, d0, mg1_look.N_DATES)
    return {
        "schema": REPORT_SCHEMA, "run_utc": now.isoformat(), "d0": d0.isoformat(),
        "through": days[-1].isoformat(),
        "rule": "Clarification 4: admitted coverage, closed/one winner, frozen label key; "
                "at least one support market-day",
        "support_market_count": len(markets),
        "dates": [{"date": d.isoformat(), "status": s} for d, s in statuses],
        "counts": {k: sum(1 for _, s in statuses if s == k) for k in (COUNTABLE, NON_COUNTABLE, PENDING)},
        "countable_reached": len(counted), "required_mg1_last": required.isoformat(),
        "recorded_mg1_last": recorded_last.isoformat(), "extend_mg1_last": required > recorded_last,
        "ledger_sha256": shas, "label_freeze_receipt_sha256": freeze["sha256"],
        "module_sha256": module_sha256(), "host": socket.gethostname(),
    }


def final_rows(*, ledger_root, label_freeze, now=None):
    """``(rows, ledger_shas)``: the ``write_countable`` rows from D0 through the 45th countable date, masked."""
    from weather.calibration import mg1_look

    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    if now < NOT_BEFORE_UTC:
        raise CountableRefused(f"MG-1 countability opens at {NOT_BEFORE_UTC.isoformat()} (R11 (3), P1)")
    d0, recorded_last = _window()
    keys, freeze = frozen_keys(label_freeze, now)
    days = [d for d in _ended_dates(d0, now) if d.isoformat() <= freeze["through"]]
    markets = support_markets()
    sensitivity = {}
    flags, shas = market_day_flags(ledger_root, days, markets, keys, sensitivity_flags=sensitivity)
    statuses = [(d, date_status(flags, d.isoformat(), markets)) for d in days]
    counted, _ = plan(statuses, d0, mg1_look.N_DATES)
    if len(counted) < mg1_look.N_DATES:
        raise CountableRefused(f"only {len(counted)} countable dates among the ended dates; no final list yet")
    last = counted[-1]
    if last > recorded_last:
        raise CountableRefused(f"the 45th countable date {last} is after the recorded MG1_LAST {recorded_last}: "
                               "extend the window first (R11 (4))")
    try:
        mg1_look.look_timing_check(last, now)
    except mg1_look.MG1LookRefused as exc:
        raise CountableRefused(str(exc)) from exc
    rows = [{"date": d.isoformat(), "markets": {m: flags.get((m, d.isoformat())) is True for m in markets},
             "sensitivity_markets": {m: sensitivity.get((m, d.isoformat())) is True for m in markets},
             "parser_v2_verified": None, "shadow_stage_captured": None,
             "caveat_reasons": {"parser_v2_verified": CAVEAT_REASON, "shadow_stage_captured": CAVEAT_REASON}}
            for d, _ in statuses if d <= last]
    return rows, shas


def final(*, ledger_root, label_freeze, out, now=None):
    """--final (P3): write the masked list once through ``mg1_look.write_countable``."""
    from weather.calibration import mg1_look

    if Path(out).exists():
        raise CountableRefused(f"{out} exists: the final list is written once")
    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    try:
        freeze_sha = sha256_file(label_freeze)
    except OSError as exc:
        raise CountableRefused(f"frozen label keys unavailable: {exc}") from exc
    rows, shas = final_rows(ledger_root=ledger_root, label_freeze=label_freeze, now=now)
    if sha256_file(label_freeze) != freeze_sha:
        raise CountableRefused("the label freeze receipt changed while constructing the final mask")
    try:
        sha = mg1_look.write_countable(out, rows, label_freeze_receipt_sha256=freeze_sha, ledger_sha256=shas)
    except mg1_look.MG1LookRefused as exc:
        raise CountableRefused(f"write_countable refused: {exc}") from exc
    return {"status": "ok", "out": str(out), "sha256": sha, "dates": len(rows), "last": rows[-1]["date"],
            "run_utc": now.isoformat(), "ledger_sha256": shas, "module_sha256": module_sha256(),
            "host": socket.gethostname()}


def build_parser():
    parser = argparse.ArgumentParser(prog=f"python -m weather.calibration.{NAME}", description=__doc__.split("\n")[0])
    parser.add_argument("--ledger-root", required=True)
    parser.add_argument("--label-freeze", required=True,
                        help="R24 freeze receipt; report also accepts mg1-countability-* previews; keys only")
    parser.add_argument("--final", action="store_true", help="write the mg1_countable/2 list (P3)")
    parser.add_argument("--out", help="the final list's path (with --final)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.final:
            if not args.out:
                raise CountableRefused("--final needs --out")
            result = final(ledger_root=args.ledger_root, label_freeze=args.label_freeze, out=args.out)
        else:
            result = report(ledger_root=args.ledger_root, label_freeze=args.label_freeze)
    except CountableRefused as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return exc.exit_code
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
