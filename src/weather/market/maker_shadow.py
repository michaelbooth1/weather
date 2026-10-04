"""Weather composition and CLI for the public-reads-only maker shadow runner (informed-maker Phase 3).

``run`` discovers local T+1/T+2 weather bands from public Gamma events, then each
minute reads both-token CLOB books and CLOB reward terms, runs ``informed_v0``
through ``maker_core.shadow.runner`` (every would-quote leg through the #180
``OrderGate``) and appends a minute record to a daily sealed tape under
``data/maker_shadow/tapes``. ``score`` checks a closed, non-embargoed UTC day's
sealed tapes against the sealed 88a capture of that day. International
Polymarket public reads only; no credential, order client or scheduled task.
Contract: docs/operations/maker-shadow-runner.md.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
import time

from maker_core.contracts import MarketDescriptor, Unavailable
from maker_core.evidence.journal import digest, write_new
from maker_core.runtime.guard import OrderGate
from maker_core.runtime.portfolio_io import read_json
from maker_core.shadow.runner import ShadowCancelPort, ShadowMarket, ShadowRunner
from maker_core.shadow.score import score_day
from maker_core.shadow.tape import PROFILES, TapeWriter, sealed_tapes
from maker_core.venue.public_feed import FixtureTransport, PublicFeed, UrllibTransport
from weather.market.maker_shadow_panel import MakerEvidencePanel, embargo_reason
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import all_specs
from weather.paths import data_path

CONFIG_SCHEMA = "weather.maker_shadow_config.v0.1"
FIXTURE_SCHEMA = "weather.maker_shadow_fixture.v0.1"
COMPOSITION_VERSION = "weather-maker-shadow-0.1"
DEFAULT_ROOT = data_path("maker_shadow")
CAP_KEYS = ("cash", "band_cap", "order_cap", "wallet_cap", "event_cap")
GUARD_KEYS = ("policy", "campaigns", "wallet_book", "latch_dir", "pause_file")


def _refuse(condition, reason):
    if condition:
        raise ValueError(reason)


def load_config(path):
    config = read_json(path)
    keys = {"schema_version", "profile", "hazard_per_minute", "adverse_markout", "caps", "markets", "horizons",
            "max_conditions", "rediscover_minutes", "guard"}
    _refuse(not isinstance(config, dict) or config.get("schema_version") != CONFIG_SCHEMA, "invalid_shadow_config")
    _refuse(set(config) - keys or not {"schema_version", "profile", "hazard_per_minute", "caps", "guard"} <= set(config),
            "shadow_config_fields")
    _refuse(config["profile"] not in PROFILES, "unknown_profile")
    hazard, markout = config["hazard_per_minute"], config.get("adverse_markout", 0.0043)
    for value, low in ((hazard, 0.0), (markout, 0.0043)):
        _refuse(isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= 1,
                "invalid_fill_bound")
    caps = config["caps"]
    _refuse(not isinstance(caps, dict) or set(caps) != set(CAP_KEYS), "caps_required")
    try:
        caps = {k: Decimal(str(caps[k])) for k in CAP_KEYS}
    except InvalidOperation:
        raise ValueError("invalid_caps") from None
    _refuse(any(not v.is_finite() or v < 0 for v in caps.values()), "invalid_caps")
    known = {spec.id for spec in all_specs()}
    markets = config.get("markets")
    _refuse(markets is not None and (not isinstance(markets, list) or not set(markets) <= known or not markets),
            "unknown_markets")
    horizons = config.get("horizons", [1, 2])
    _refuse(not isinstance(horizons, list) or not horizons or not set(horizons) <= {0, 1, 2}, "invalid_horizons")
    limits = {"max_conditions": (config.get("max_conditions", 24), 1, 60),
              "rediscover_minutes": (config.get("rediscover_minutes", 15), 1, 120)}
    for name, (value, low, high) in limits.items():
        _refuse(isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high, "invalid_" + name)
    guard = config["guard"]
    _refuse(not isinstance(guard, dict) or set(guard) != set(GUARD_KEYS) or not isinstance(guard["policy"], dict)
            or any(not isinstance(guard[k], str) for k in GUARD_KEYS[1:]), "guard_section_required")
    return {**config, "adverse_markout": markout, "caps": caps, "markets": markets, "horizons": sorted(horizons),
            "max_conditions": limits["max_conditions"][0], "rediscover_minutes": limits["rediscover_minutes"][0]}


def _pair(market):
    tokens, outcomes = market.get("clobTokenIds"), market.get("outcomes")
    tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
    outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
    _refuse(not isinstance(tokens, list) or len(tokens) != 2 or len(set(tokens)) != 2
            or not isinstance(outcomes, list) or sorted(outcomes) != ["No", "Yes"], "no_exact_yes_no_mapping")
    return {"YES": str(tokens[outcomes.index("Yes")]), "NO": str(tokens[outcomes.index("No")])}


def _rewarded(market):
    rows = market.get("clobRewards") or []
    return any(float(row.get("rewardsDailyRate") or 0) > 0 for row in rows if isinstance(row, dict))


def _distance(market):
    try:
        return abs((float(market["bestBid"]) + float(market["bestAsk"])) / 2 - 0.5)
    except (KeyError, TypeError, ValueError):
        return 1.0


def discover(feed, specs, now_utc, *, horizons, max_conditions):
    """Reward-eligible, order-book-enabled weather bands on local T+h dates, nearest-to-even mid first."""
    wanted = {}
    for spec in specs:
        local_today = now_utc.astimezone(spec.tz).date()
        for h in horizons:
            wanted[event_slug_for_date(local_today + timedelta(days=h), spec.id)] = (spec, h)
    slugs, events = sorted(wanted), []
    for start in range(0, len(slugs), 20):
        events.extend(feed.events(slugs[start:start + 20]))
    candidates, refused, found = [], {}, set()
    for event in events:
        spec, horizon = wanted[event["slug"]]
        found.add(event["slug"])
        for market in event.get("markets") or ():
            try:
                _refuse(market.get("closed") or not market.get("active") or market.get("enableOrderBook") is False,
                        "not_open")
                _refuse(not _rewarded(market), "no_current_reward")
                descriptor = MarketDescriptor(
                    domain_id="weather", event_id=event["slug"], condition_id=str(market["conditionId"]).lower(),
                    outcome_tokens=_pair(market),
                    # Provisional: each minute the runner replaces both from the CLOB book it reads.
                    tick=Decimal(str(market.get("orderPriceMinTickSize") or "0.01")),
                    min_order_size=Decimal(str(market.get("orderMinSize") or "5")),
                    neg_risk_group=str(event["id"]) if event.get("negRisk") else None,
                    close_at_utc=datetime.fromisoformat(str(market["endDate"]).replace("Z", "+00:00")),
                    settle_at_utc=None, native_unit=spec.display_unit, plugin_version=COMPOSITION_VERSION,
                    source_hashes={"gamma_event": digest(event)},
                    group_relation="partition" if event.get("negRisk") else None)
                candidates.append((_distance(market), descriptor.condition_id, ShadowMarket(descriptor, horizon)))
            except (KeyError, TypeError, ValueError, InvalidOperation) as error:
                reason = str(error) if isinstance(error, ValueError) and str(error).islower() else type(error).__name__
                refused[reason] = refused.get(reason, 0) + 1
    candidates.sort(key=lambda row: row[:2])
    chosen = [row[2] for row in candidates[:max_conditions]]
    record = {"slugs_requested": len(slugs), "events_missing": sorted(set(slugs) - found),
              "candidates": len(candidates), "selected": [m.descriptor.condition_id for m in chosen],
              "dropped_by_cap": max(0, len(candidates) - max_conditions), "refused": refused,
              "ranking": "|gamma mid - 0.5| then condition id; selection only, never an input to fair value"}
    return chosen, record


def unavailable_fair_value(descriptor, now_utc):
    """The weather maker plugin is not on master: v0 shadow quotes blind width (grade-none caps)."""
    return Unavailable("weather_fair_value_provider_not_integrated", now_utc)


class SimulatedClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


def build_runner(config, feed, clock):
    guard = config["guard"]
    port = ShadowCancelPort()
    gate = OrderGate(state_dir=Path(guard["latch_dir"]), pause_file=Path(guard["pause_file"]), policy=guard["policy"],
                     campaigns=read_json(guard["campaigns"]), clock=clock, cancel_port=port)
    return ShadowRunner(reads=feed, gate=gate, cancel_port=port, wallet_book=lambda: read_json(guard["wallet_book"]),
                        fair_value=unavailable_fair_value, clock=clock, caps=config["caps"],
                        hazard_per_minute=float(config["hazard_per_minute"]),
                        adverse_markout=float(config["adverse_markout"]), profile=PROFILES[config["profile"]])


def run(args):
    config = load_config(args.config)
    if args.stop_file and Path(args.stop_file).exists():
        raise ValueError("stop_file_present_at_start")
    if args.offline_fixture:
        fixture = read_json(args.offline_fixture)
        _refuse(not isinstance(fixture, dict) or fixture.get("schema_version") != FIXTURE_SCHEMA, "invalid_fixture")
        _refuse(not args.minutes, "offline_mode_requires_minutes")
        transport = FixtureTransport(fixture["replies"])
        clock = SimulatedClock(datetime.fromisoformat(fixture["clock_start_utc"]).astimezone(timezone.utc))
        mode = "offline_fixture"
    else:
        transport, clock, mode = UrllibTransport(), (lambda: datetime.now(timezone.utc)), "public_shadow"
    feed = PublicFeed(transport)
    runner = build_runner(config, feed, clock)
    specs = [s for s in all_specs() if config["markets"] is None or s.id in config["markets"]]
    out = Path(args.output_root) if args.output_root else DEFAULT_ROOT / "tapes"
    scope = {"mode": mode, "profile": config["profile"], "config_sha256": digest(config),
             "guard_policy_sha256": digest(config["guard"]["policy"]), "composition": COMPOSITION_VERSION,
             "fair_value": "unavailable:weather_fair_value_provider_not_integrated",
             "hazard_per_minute": config["hazard_per_minute"], "adverse_markout": config["adverse_markout"],
             "caps": config["caps"]}
    writer = TapeWriter(out, clock=clock, scope=scope)
    markets, discovered_at, done, reason, last = [], None, 0, "completed", None
    try:
        while not args.minutes or done < args.minutes:
            minute = clock().replace(second=0, microsecond=0)
            if minute == last:
                time.sleep(max(0.0, (minute + timedelta(minutes=1) - clock()).total_seconds()))
                continue
            if args.stop_file and Path(args.stop_file).exists():
                reason = "stop_file"
                break
            utc_day = minute.date()
            if discovered_at is None or minute - discovered_at[0] >= timedelta(minutes=config["rediscover_minutes"]) \
                    or utc_day != discovered_at[1]:
                try:
                    markets, universe = discover(feed, specs, minute, horizons=config["horizons"],
                                                 max_conditions=config["max_conditions"])
                    writer.record("universe", minute, **universe)
                except Exception as error:  # Keep the previous universe; the failure is on the tape.
                    writer.record("universe_error", minute, error=type(error).__name__)
                discovered_at = (minute, utc_day)
            writer.record("minute", minute, **runner.step(minute, markets))
            done, last = done + 1, minute
            if mode == "offline_fixture":
                clock.now = minute + timedelta(minutes=1)
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        writer.close(reason)
    print(json.dumps({"mode": mode, "minutes": done, "end_reason": reason, "tape_root": str(out),
                      "sealed": writer.sealed}, indent=2, default=str))
    return 0


def score(args):
    day = date.fromisoformat(args.day).isoformat()
    reason = embargo_reason(day)
    if reason:
        # Refused before any tape or 88a byte of the day is opened.
        print(json.dumps({"refused": "embargoed_utc_day", "utc_day": day, "reason": reason}))
        return 2
    if day >= datetime.now(timezone.utc).date().isoformat():
        print(json.dumps({"refused": "utc_day_not_closed", "utc_day": day}))
        return 2
    tape_root = Path(args.tape_root) if args.tape_root else DEFAULT_ROOT / "tapes"
    tapes, unsealed = sealed_tapes(tape_root, day)
    if not tapes:
        print(json.dumps({"refused": "no_sealed_tape", "utc_day": day, "unsealed_tapes": unsealed}))
        return 2
    assets = {asset for t in tapes for r in t["rows"] if r["event"] == "minute"
              for c in r["conditions"] for asset in c["outcomes"].values()}
    panel = MakerEvidencePanel(args.maker_evidence_root or data_path("maker_evidence"), day, assets)
    report = score_day(tapes, panel, utc_day=day, unsealed=unsealed, panel_summary=panel.summary)
    out = Path(args.out) if args.out else DEFAULT_ROOT / "scores" / f"{day}-{digest(report)[:16]}.json"
    write_new(out, report)
    print(json.dumps({"report": str(out), "agreement": report["agreement"]["status"], "label": report["label"]}))
    return 0


def parser():
    p = argparse.ArgumentParser(prog="python -m weather.market.maker_shadow", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="per-minute public-reads-only shadow quotes tape")
    r.add_argument("--config", required=True, help=f"JSON config, schema {CONFIG_SCHEMA}")
    r.add_argument("--minutes", type=int, help="stop after N minutes (required with --offline-fixture)")
    r.add_argument("--output-root", help="tape directory (default data/maker_shadow/tapes)")
    r.add_argument("--stop-file", help="the run stops at the next minute once this file exists")
    r.add_argument("--offline-fixture", help=f"no-network mode: recorded public replies, schema {FIXTURE_SCHEMA}")
    s = sub.add_parser("score", help="nightly diagnostics of a closed UTC day against sealed 88a capture")
    s.add_argument("--day", required=True, help="closed, non-embargoed UTC day YYYY-MM-DD")
    s.add_argument("--tape-root", help="tape directory (default data/maker_shadow/tapes)")
    s.add_argument("--maker-evidence-root", help="88a root holding <day>/<segment>/ (default data/maker_evidence)")
    s.add_argument("--out", help="new report path (default data/maker_shadow/scores/<day>-<hash>.json)")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return run(args) if args.command == "run" else score(args)
    except ValueError as error:
        print(json.dumps({"refused": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
