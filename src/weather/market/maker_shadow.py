"""Weather composition and CLI for the public-reads-only maker shadow runner (informed-maker Phase 3).

``run`` discovers local T+1/T+2 weather bands from public Gamma events, then each
minute reads both-token CLOB books and CLOB reward terms, runs ``informed_v0``
through ``maker_core.shadow.runner`` (every would-quote leg through the #180
``OrderGate``) and appends a minute record to a daily sealed tape under
``data/maker_shadow/tapes``, plus (tape v0.2) a record stream of the raw public
replies it read, in replay-bundle row format; ``bundle-day`` writes a closed day's
replay-v2 ``bundle.json`` over those streams. ``score`` checks a closed, non-embargoed UTC day's
sealed tapes against the sealed 88a capture of that day. International
Polymarket public reads only; no credential, order client or scheduled task.
Contract: docs/operations/maker-shadow-runner.md.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from maker_core.contracts import MarketDescriptor, Unavailable
from maker_core.evidence.journal import digest, write_new
from maker_core.runtime.guard import OrderGate
from maker_core.runtime.portfolio_io import read_json
from maker_core.shadow.paper import FILL_RULES, PAPER_CAMPAIGN, PaperLedger
from maker_core.shadow.records import RawRecorder, RecordingReads, bundle_day, records_summary
from maker_core.shadow.runner import ShadowCancelPort, ShadowMarket, ShadowRunner
from maker_core.shadow.score import score_day
from maker_core.shadow.tape import PROFILES, TapeWriter, sealed_tapes
from maker_core.venue.public_feed import FixtureTransport, PublicFeed, UrllibTransport
from weather.market.maker_shadow_panel import MakerEvidencePanel, embargo_reason
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import all_specs
from weather.paths import REPO_ROOT, data_path

CONFIG_SCHEMA = "weather.maker_shadow_config.v0.1"
FIXTURE_SCHEMA = "weather.maker_shadow_fixture.v0.1"
COMPOSITION_VERSION = "weather-maker-shadow-0.1"
DEFAULT_ROOT = data_path("maker_shadow")
CAP_KEYS = ("cash", "band_cap", "order_cap", "wallet_cap", "event_cap")
GUARD_KEYS = ("policy", "latch_dir", "pause_file")
PAPER_KEYS = ("starting_cash_pusd", "bleed_limit_pusd", "fill_rule")


GIT_TIMEOUT_SECONDS = 60
# Mid-minute refresh: one trade poll and both books again per band, so the record stream's 60 s trade coverage
# is continuous and no recorded book ages past the replay engine's 60 s freshness limit. Record stream only:
# the shadow's decision inputs are the minute's own reads.
MID_MINUTE_POLL = timedelta(seconds=30)
# Overrun rule (owner decision N7): the refresh must not delay the next minute's decision. It has a hard deadline,
# REFRESH_MARGIN before the next minute starts, and reads its bands one at a time: a band is started only when
# the clock plus the per-band estimate is within the deadline. The per-band estimate is the longest band read
# measured (monotonic clock) in this refresh and the run's previous one; before a first measurement, and after a
# refresh that read nothing, it is REFRESH_BAND_BOUND (a band's three public GETs at the 5 s transport timeout).
# Only a band read that outlasts its estimate can pass the deadline, so the next decision is late only by that
# excess (one band); such a refresh is recorded as late. A refresh cut short (partial), that read nothing
# (skipped) or that ended late is recorded per minute. Backoff (owner decision N1, 2026-10-09: back off only
# after a LATE refresh): only a refresh that ended late, and so delayed a decision, defers the next attempt, by
# a capped exponential backoff (REFRESH_BACKOFF_MINUTES, by late refreshes since the last full on-time one). A
# clean partial or skip stopped within the deadline and delayed nothing, so the next minute is attempted again;
# it neither raises nor resets the backoff. Only a full refresh that ended within the deadline resets it.
REFRESH_MARGIN = timedelta(seconds=3)
REFRESH_BAND_BOUND = timedelta(seconds=15)
REFRESH_BACKOFF_MINUTES = (1, 2, 4, 8)
REFRESH_SKIPPED = "refresh:skipped_overrun"
REFRESH_PARTIAL = "refresh:partial_overrun"
REFRESH_LATE = "refresh:late_overrun"
REFRESH_BACKOFF = "refresh:skipped_backoff"


class RefreshPlan:
    """The run's refresh state: the previous refresh's longest band read, and the backoff."""

    def __init__(self):
        self.band_estimate = None  # None: REFRESH_BAND_BOUND
        self.late = 0  # late refreshes since the last full on-time refresh (sets the backoff)
        self.resume_at = None  # first minute whose refresh may be attempted again


def mid_minute_refresh(writer, condition_ids, clock, minute, plan, monotonic=None):
    """The mid-minute refresh of ``minute`` under the hard deadline and backoff; updates and returns ``plan``.

    ``clock`` (wall, UTC) decides the deadline; band reads are timed on ``monotonic`` (default
    ``time.monotonic``), so a wall-clock step never feeds the estimate. Lost refresh work is recorded on the
    stream with ``writer.incomplete_refresh(code, minute, refreshed, left)``.
    """
    monotonic = monotonic or time.monotonic
    if plan.resume_at is not None and minute < plan.resume_at:
        writer.incomplete_refresh(REFRESH_BACKOFF, minute, 0, len(condition_ids))
        return plan
    deadline = minute + timedelta(minutes=1) - REFRESH_MARGIN
    carried = plan.band_estimate or REFRESH_BAND_BOUND
    state = {"longest": None, "mark": None, "refreshed": 0, "left": 0}

    def measure():
        if state["mark"] is not None:
            took = timedelta(seconds=max(0.0, monotonic() - state["mark"]))
            state["longest"] = took if state["longest"] is None else max(state["longest"], took)
            state["mark"] = None

    def proceed(remaining):
        """Called before each band read with the bands left (this one included); False stops the refresh."""
        measure()
        if clock() + max(carried, state["longest"] or timedelta(0)) > deadline:
            state["left"] = remaining
            return False
        state["refreshed"] += 1
        state["mark"] = monotonic()
        return True

    writer.poll(condition_ids, proceed=proceed)
    measure()
    plan.band_estimate = state["longest"]
    late = clock() > deadline  # a band read outlasted its estimate
    if state["left"] or late:
        code = REFRESH_LATE if late else REFRESH_PARTIAL if state["refreshed"] else REFRESH_SKIPPED
        writer.incomplete_refresh(code, minute, state["refreshed"], state["left"])
    if late:  # owner decision N1: only a refresh that delayed a decision backs off
        plan.late += 1
        backoff = REFRESH_BACKOFF_MINUTES[min(plan.late, len(REFRESH_BACKOFF_MINUTES)) - 1]
        plan.resume_at = minute + timedelta(minutes=backoff)
    elif state["left"]:  # clean partial or skip, within the deadline: retry next minute, backoff level kept
        plan.resume_at = None
    else:
        plan.late, plan.resume_at = 0, None
    return plan


def code_identity(root=REPO_ROOT):
    """Git commit and dirty flag of the checkout this process runs from, computed once at start.

    Never raises: a missing git or a non-repository is recorded as ``git_commit`` None with an enumerated
    ``git_error``, so the recorder still runs and the tape says the code was not bound. ``git_dirty`` counts
    tracked changes only (untracked runtime files under ``data/`` are ignored by git anyway).
    """
    git = shutil.which("git")
    if git is None:
        return {"git_commit": None, "git_dirty": None, "git_error": "git_unavailable"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    def call(*args):
        return subprocess.run([git, "-C", str(root), *args], capture_output=True, text=True, check=False,
                              timeout=GIT_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL, creationflags=flags)

    try:
        head = call("rev-parse", "--verify", "HEAD^{commit}")
        if head.returncode != 0:
            return {"git_commit": None, "git_dirty": None, "git_error": "git_failed"}
        commit = head.stdout.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            return {"git_commit": None, "git_dirty": None, "git_error": "git_output_invalid"}
        status = call("status", "--porcelain", "--untracked-files=no")
        if status.returncode != 0:
            return {"git_commit": commit, "git_dirty": None, "git_error": "git_status_failed"}
        return {"git_commit": commit, "git_dirty": bool(status.stdout.strip()), "git_error": None}
    except subprocess.TimeoutExpired:
        return {"git_commit": None, "git_dirty": None, "git_error": "git_timeout"}
    except OSError:
        return {"git_commit": None, "git_dirty": None, "git_error": "git_unavailable"}


def _refuse(condition, reason):
    if condition:
        raise ValueError(reason)


def load_config(path):
    config = read_json(path)
    keys = {"schema_version", "profile", "hazard_per_minute", "adverse_markout", "caps", "markets", "horizons",
            "max_conditions", "rediscover_minutes", "guard", "paper"}
    _refuse(not isinstance(config, dict) or config.get("schema_version") != CONFIG_SCHEMA, "invalid_shadow_config")
    guard = config.get("guard")
    # Shadow mode evaluates only its paper campaign book: a wallet book or campaign file is refused.
    _refuse(isinstance(guard, dict) and ({"wallet_book", "campaigns"} & set(guard)), "shadow_mode_refuses_real_wallet_book")
    _refuse(set(config) - keys or not {"schema_version", "profile", "hazard_per_minute", "caps", "guard", "paper"}
            <= set(config), "shadow_config_fields")
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
    _refuse(not isinstance(guard, dict) or set(guard) != set(GUARD_KEYS) or not isinstance(guard["policy"], dict)
            or any(not isinstance(guard[k], str) for k in GUARD_KEYS[1:]), "guard_section_required")
    _refuse(guard["policy"].get("campaign_id") != PAPER_CAMPAIGN, "guard_policy_must_name_paper_campaign")
    paper = config["paper"]
    _refuse(not isinstance(paper, dict) or set(paper) != set(PAPER_KEYS) or paper["fill_rule"] not in FILL_RULES,
            "paper_section_required")
    try:
        cash, limit = Decimal(str(paper["starting_cash_pusd"])), Decimal(str(paper["bleed_limit_pusd"]))
    except InvalidOperation:
        raise ValueError("paper_section_required") from None
    _refuse(not cash.is_finite() or not limit.is_finite() or cash <= 0 or not 0 <= limit <= cash,
            "paper_section_required")
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


def slug_market_ids(specs, now_utc, horizons):
    """Event slug -> registry market id for the slugs ``discover`` asks for (the record stream's market id)."""
    return {event_slug_for_date(now_utc.astimezone(spec.tz).date() + timedelta(days=h), spec.id): spec.id
            for spec in specs for h in horizons}


def local_dates(specs, now_utc):
    """Each market's local date at ``now_utc``."""
    return {spec.id: now_utc.astimezone(spec.tz).date() for spec in specs}


def discovery_due(previous, minute, specs, rediscover_minutes):
    """Rediscover on schedule, at the UTC day change, and at any market's local midnight.

    At a local midnight the bands' local leads change (a T+1 band becomes T+0), so the selection and each
    band's ``horizon_days`` are recomputed, as the replay engine's day roll does (``day_roll.py``,
    ``local_midnight``). ``previous`` is ``(minute, local dates)`` of the last discovery, or None.
    """
    if previous is None:
        return True
    at, dates = previous
    return (minute - at >= timedelta(minutes=rediscover_minutes) or minute.date() != at.date()
            or local_dates(specs, minute) != dates)


def unavailable_fair_value(descriptor, now_utc):
    """The weather maker plugin is not on master: v0 shadow quotes blind width (grade-none caps)."""
    return Unavailable("weather_fair_value_provider_not_integrated", now_utc)


class SimulatedClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


def build_runner(config, feed, clock):
    """Shadow mode: the guard evaluates the paper campaign book, never a wallet book."""
    guard, paper = config["guard"], config["paper"]
    ledger = PaperLedger(starting_cash=paper["starting_cash_pusd"], bleed_limit=paper["bleed_limit_pusd"],
                         start_utc=clock().replace(second=0, microsecond=0), fill_rule=paper["fill_rule"])
    port = ShadowCancelPort()
    gate = OrderGate(state_dir=Path(guard["latch_dir"]), pause_file=Path(guard["pause_file"]), policy=guard["policy"],
                     campaigns=ledger.campaigns, clock=clock, cancel_port=port)
    return ShadowRunner(reads=feed, gate=gate, cancel_port=port, paper=ledger,
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
    feed = RecordingReads(PublicFeed(transport), clock)  # Raw replies are kept for the v0.2 record stream.
    runner = build_runner(config, feed, clock)
    specs = [s for s in all_specs() if config["markets"] is None or s.id in config["markets"]]
    out = Path(args.output_root) if args.output_root else DEFAULT_ROOT / "tapes"
    scope = {"mode": mode, "profile": config["profile"], "config_sha256": digest(config),
             "guard_policy_sha256": digest(config["guard"]["policy"]), "composition": COMPOSITION_VERSION,
             "fair_value": "unavailable:weather_fair_value_provider_not_integrated",
             "hazard_per_minute": config["hazard_per_minute"], "adverse_markout": config["adverse_markout"],
             "caps": config["caps"], "paper": config["paper"], "guard_book": "paper_campaign_book",
             **code_identity()}
    market_ids = {}
    writer = TapeWriter(out, clock=clock, scope=scope, recorder=RawRecorder(feed, market_id=market_ids.get))
    markets, discovered_at, done, reason, last, mid_poll = [], None, 0, "completed", None, None
    refresh_plan = RefreshPlan()
    try:
        while not args.minutes or done < args.minutes:
            minute = clock().replace(second=0, microsecond=0)
            if minute == last:
                if mid_poll is not None and clock() >= mid_poll:
                    mid_poll = None
                    refresh_plan = mid_minute_refresh(
                        writer, [m.descriptor.condition_id for m in markets], clock, minute, refresh_plan)
                    continue
                wake = mid_poll or minute + timedelta(minutes=1)
                time.sleep(max(0.0, (wake - clock()).total_seconds()))
                continue
            if args.stop_file and Path(args.stop_file).exists():
                reason = "stop_file"
                break
            if discovery_due(discovered_at, minute, specs, config["rediscover_minutes"]):
                try:
                    market_ids.update(slug_market_ids(specs, minute, config["horizons"]))
                    markets, universe = discover(feed, specs, minute, horizons=config["horizons"],
                                                 max_conditions=config["max_conditions"])
                    writer.record("universe", minute, **universe)
                except Exception as error:  # Keep the previous universe; the failure is on the tape.
                    writer.record("universe_error", minute, error=type(error).__name__)
                discovered_at = (minute, local_dates(specs, minute))
            feed.poll([m.descriptor.condition_id for m in markets])  # Served once to the paper-fill read.
            writer.record("minute", minute, **runner.step(minute, markets))
            done, last, mid_poll = done + 1, minute, minute + MID_MINUTE_POLL
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
    print(json.dumps({"report": str(out), "agreement": report["agreement"]["status"], "label": report["label"],
                      "code": report["code"]}))
    return 0


def bundle(args):
    """Write a closed UTC day's replay-v2 ``bundle.json`` over its sealed record streams (create-only)."""
    day = date.fromisoformat(args.day).isoformat()
    tape_root = Path(args.tape_root) if args.tape_root else DEFAULT_ROOT / "tapes"
    try:
        # bundle_day verifies every bundled stream against its seal before it writes anything; the summary
        # covers exactly those streams, never an excluded (broken or unsealed) run's.
        path, manifest = bundle_day(tape_root, day, clock=lambda: datetime.now(timezone.utc))
        summary = records_summary(tape_root, day, streams={s["path"] for s in manifest["streams"]})
    except FileExistsError:
        print(json.dumps({"refused": "bundle_exists", "utc_day": day}))
        return 2
    except ValueError as error:  # coded refusals (records.bundle_day); never a traceback
        print(json.dumps({"refused": str(error), "utc_day": day}))
        return 2
    except OSError as error:
        print(json.dumps({"refused": "io_error:" + type(error).__name__, "utc_day": day}))
        return 2
    print(json.dumps({"bundle": str(path), "utc_day": day, "streams": len(manifest["streams"]),
                      "conditions": len(manifest["conditions"]), "gaps": manifest["gaps"],
                      "excluded": manifest["excluded"], "records": summary}))
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
    b = sub.add_parser("bundle-day", help="replay-v2 bundle.json over a closed UTC day's sealed record streams")
    b.add_argument("--day", required=True, help="closed UTC day YYYY-MM-DD")
    b.add_argument("--tape-root", help="tape directory (default data/maker_shadow/tapes)")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return {"run": run, "score": score, "bundle-day": bundle}[args.command](args)
    except ValueError as error:
        print(json.dumps({"refused": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
