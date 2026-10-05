"""S3, S5, S7, S8 and S9 for maker replay v2 W3-W5 on fictional fixtures; one measurement per fresh process.

    python -m tools.research.maker_replay_v2.run s3 --out NEW_DIR --union B [--minutes 360]
    python -m tools.research.maker_replay_v2.run s5 --out NEW_DIR [--minutes 90]
    python -m tools.research.maker_replay_v2.run s7 --out NEW_DIR [--union 170] [--minutes 1440]
    python -m tools.research.maker_replay_v2.run s8 --out NEW_DIR [--minutes 120]
    python -m tools.research.maker_replay_v2.run s9 --out NEW_DIR [--days 16]

Engineering plan: docs/research/maker-replay-v2-engineering-plan-DRAFT.md. Every input is fictional
(``sources.ScaledDay``). Heavy: run through ``scripts/ops/workstation_heavy.ps1`` (``weather_heavy``), serially.
"""
from __future__ import annotations

import ctypes
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
import time
import tracemalloc

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.replay.bundle import Bundle, sha256
from maker_core.replay.engine import ReplayConfig, replay
from maker_core.replay.score import score as v1_score
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import drive, items, record_from_row, run_plan
from maker_core.replay.v2.money import ZERO, add, mul, q, sub, total
from maker_core.replay.v2.pipeline import fraction, run_passes
from maker_core.replay.v2.reference import ReferenceEngine
from maker_core.replay.v2.report import build_report, report_bytes
from maker_core.replay.v2.score import BandDayScorer, Books
from tools.research.maker_replay_v2.dense import DenseDay
from tools.research.maker_replay_v2.sources import ScaledDay, materialize, plan_of

DAY = date(2026, 9, 27)  # fictional
HAZARD = .001
# Short S5 windows: one across the 04:00 UTC horizon roll of the New York/Toronto events, one across
# the 10:00 UTC settlements of the rolled bands.
S5_WINDOWS = ((210, "horizon roll 03:30-"), (570, "settlements 09:30-"))


# -- process measurements ------------------------------------------------------------------------------
class _Counters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def working_set():
    """(current, peak) working set bytes of this process (Windows); (None, None) elsewhere."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Counters), ctypes.c_ulong]
        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        if kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize, counters.PeakWorkingSetSize
    except (AttributeError, OSError):
        pass
    return None, None


# -- comparison ------------------------------------------------------------------------------------------
def fingerprint(engine):
    """Everything S5 compares, as digests: decisions, intervals, fills, cash, settlements, final legs."""
    intervals = sorted(engine.intervals, key=lambda i: (i.condition_id, i.start))
    return dict(decisions=engine.decision_sha.hexdigest(), decision_count=engine.decision_count,
                intervals=digest(intervals), interval_count=len(intervals), fills=digest(engine.fills),
                fill_count=len(engine.fills), cash=str(engine.cash),
                settlements=digest(dict(sorted(engine.settlements.items()))),
                legs=digest({cid: s.legs for cid, s in sorted(engine.states.items())}),
                inventory=digest({cid: s.inventory_cost for cid, s in sorted(engine.states.items())}),
                exclusions=engine.exclusions.sha.hexdigest())


def differential(source, config):
    """Run every pass of the pipeline with the v2 engine and with the reference; list every difference."""
    started = time.perf_counter()
    v2 = run_passes([source], replace(config, debug=True, keep=True), engine=EngineV2)
    mid = time.perf_counter()
    ref = run_passes([source], replace(config, keep=True), engine=ReferenceEngine)
    done = time.perf_counter()
    divergences, compared = [], 0
    for bound in v2.passes:
        for policy in v2.passes[bound]:
            a, b = fingerprint(v2.passes[bound][policy].engine), fingerprint(ref.passes[bound][policy].engine)
            compared += 1
            divergences += [dict(bound=bound, policy=policy, field=k) for k in a if a[k] != b[k]]
        ma, mb = canonical_bytes(v2.matches[bound]), canonical_bytes(ref.matches[bound])
        if ma != mb:
            divergences.append(dict(bound=bound, field="clock_match"))
    if len(v2.trials) != len(ref.trials):
        divergences.append(dict(field="clock_trial_count", v2=len(v2.trials), reference=len(ref.trials)))
    for (b1, n1, f1, t1), (b2, n2, f2, t2) in zip(v2.trials, ref.trials):
        compared += 1
        if (b1, n1, f1) != (b2, n2, f2):
            divergences.append(dict(bound=b1, round=n1, field="clock_trial_schedule"))
            continue
        fa, fb = fingerprint(t1.engine), fingerprint(t2.engine)
        divergences += [dict(bound=b1, round=n1, field=k) for k in fa if fa[k] != fb[k]]
    informed = v2.passes["strictly_through"]["informed-v0"].engine
    return dict(engines_compared=compared, clock_trials=len(v2.trials), divergences=divergences,
                matches={b: dict(status=m["status"], attempts=m["attempts"],
                                 fraction=str(m.get("calendar_prefix_fraction"))) for b, m in v2.matches.items()},
                informed_decisions=informed.decision_count,
                quotes={b: {p: sum(d.decision.action == "QUOTE" for d in v2.passes[b][p].engine.decisions)
                            for p in v2.passes[b]} for b in v2.passes},
                fills={b: {p: len(v2.passes[b][p].engine.fills) for p in v2.passes[b]} for b in v2.passes},
                v2_seconds=round(mid - started, 1), reference_seconds=round(done - mid, 1))


def s5(args):
    """W0-shaped windows (horizon roll, settlements) and a quoting-dense window, at each B and T."""
    cases = []
    for union in (12, 40, 170):
        for trades in (2000, 20000):
            days = [(f"w0 {label}{args.minutes} min",
                     ScaledDay(DAY, union=union, trades=trades, start_minute=start, minutes=args.minutes))
                    for start, label in S5_WINDOWS]
            days.append((f"dense 10:00-{args.dense_minutes} min",
                         DenseDay(DAY, union=union, trades=trades, minutes=args.dense_minutes)))
            for label, day in days:
                source, records = materialize(day)
                result = differential(source, V2Config(hazard_per_minute=HAZARD))
                cases.append(dict(union=union, trades=trades, window=label, records=records, **result))
                if result["divergences"]:
                    return dict(measurement="S5", status="MEASURED", cases=cases, pass_=False,
                                stopped="divergence")
    return dict(measurement="S5", status="MEASURED", cases=cases,
                pass_=all(not c["divergences"] for c in cases))


# -- S3 ---------------------------------------------------------------------------------------------------
def s3(args):
    day = ScaledDay(DAY, union=args.union, trades=args.trades, start_minute=0, minutes=args.minutes)
    built = time.perf_counter()
    source, records = materialize(day)
    built = time.perf_counter() - built
    stats = day.stats()
    batches = list(items(source))  # parse and decode once, outside every timed pass
    plan = run_plan([source])
    config = V2Config(hazard_per_minute=HAZARD)

    def one_pass(trace, config=config):
        engine = EngineV2(config, plan, sink=BandDayScorer("informed-v0", "strictly_through", pull_runs=True))
        if trace:
            tracemalloc.start()
        started = time.perf_counter()
        engine.start_day(plan.days[0])
        for at, batch in batches:
            engine.instant(at, batch)
        engine.finish()
        elapsed = time.perf_counter() - started
        peak = None
        if trace:
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
        return engine, elapsed, peak

    timings = []
    for _ in range(args.repeats):
        engine, elapsed, _ = one_pass(False)
        timings.append(round(elapsed, 3))
    _, _, traced_peak = one_pass(True)
    band_minutes = stats["instantaneous_mean"] * args.minutes
    current, peak = working_set()
    return dict(measurement="S3", status="MEASURED", union=args.union, trades=args.trades, minutes=args.minutes,
                fixture=stats, records=records, fixture_build_seconds=round(built, 1),
                pass_seconds=timings, pass_seconds_min=min(timings), engine=engine.summary(),
                wakes_per_band_minute=round(engine.wakes / band_minutes, 3),
                microseconds_per_wake=round(min(timings) / engine.wakes * 1e6, 1),
                book_rows_per_minute=max(1, -(-2 * round(stats["instantaneous_mean"]) // 100)),
                traced_peak_bytes_per_pass=traced_peak, process_working_set_bytes=current,
                process_peak_working_set_bytes=peak,
                book_records=sum(1 for _, batch in batches for i in batch if i.kind == "book"))


# -- S7 ---------------------------------------------------------------------------------------------------
def s7(args):
    day = ScaledDay(DAY, union=args.union, trades=args.trades, start_minute=0, minutes=args.minutes)
    source, records = materialize(day)
    _, base_peak = working_set()
    started = time.perf_counter()
    rounds = []
    run = run_passes([source], V2Config(hazard_per_minute=HAZARD),
                     progress=lambda stage, n: rounds.append((stage, n, round(time.perf_counter() - started, 1))))
    passes_seconds = time.perf_counter() - started
    sidecar = args.out / "sidecar.jsonl"
    report, binding = build_report(run, V2Config(hazard_per_minute=HAZARD), sidecar_path=sidecar)
    raw = report_bytes(report)
    (args.out / "report.json").write_bytes(raw)
    _, peak = working_set()
    return dict(measurement="S7", status="MEASURED", union=args.union, trades=args.trades, minutes=args.minutes,
                fixture=day.stats(), records=records, report_bytes=len(raw), report_sha256=sha256(raw),
                sidecar=binding, report_limit_per_date=1024**3 // 16, sidecar_limit_per_date=8 * 1024**3 // 16,
                report_within=len(raw) < 1024**3 // 16, sidecar_within=binding["bytes"] <= 8 * 1024**3 // 16,
                passes=dict(base=8, clock_trials=len(run.trials), seconds=round(passes_seconds, 1), stages=rounds),
                matches={b: dict(status=m["status"], attempts=m["attempts"]) for b, m in run.matches.items()},
                decision=report["registered_decision"]["status"],
                process_peak_working_set_bytes=peak, peak_before_passes_bytes=base_peak)


# -- S8 ---------------------------------------------------------------------------------------------------
def _quoted(rows):
    pulled, covered = fraction(rows)
    return None if pulled is None else float(1 - pulled), float(covered)


def s8(args):
    """informed-v0 quoted fraction under the v2 schedule and the frozen loop, by B and T, on two fixtures."""
    rows = []
    for kind in ("w0", "dense"):
        for union in (40, 85, 170):
            for trades in (2000, 20000):
                if kind == "w0":
                    day = ScaledDay(DAY, union=union, trades=trades, start_minute=args.start, minutes=args.minutes)
                else:
                    day = DenseDay(DAY, union=union, trades=trades, minutes=args.dense_minutes)
                source, records = materialize(day, "v0.1")
                plan = run_plan([source])
                markets = {c.condition_id: c.market_id for c in plan.days[0].conditions}
                variants = {}
                for name, config in (("v2", V2Config(hazard_per_minute=HAZARD)),):
                    scorer, books = BandDayScorer("informed-v0", "strictly_through"), Books()
                    engine = EngineV2(config, plan, sink=scorer)
                    started = time.perf_counter()
                    drive([source], [engine], observers=(books,))
                    seconds = time.perf_counter() - started
                    quoted, covered = _quoted(scorer.band_days(engine.settlements, books, markets))
                    variants[name] = dict(quoted_fraction=quoted, covered_seconds=covered, seconds=round(seconds, 1),
                                          decisions=engine.decision_count,
                                          quotes=sum(r.quotes for r in scorer.rows.values()))
                frozen = Bundle(day.day, day.end, "synthetic", plan.days[0].conditions,
                                tuple(r for r in source.records()), dict(plan.days[0].input_hashes), 0)
                started = time.perf_counter()
                result = replay((frozen,), ReplayConfig(hazard_per_minute=HAZARD, max_events=2**31 - 1,
                                                        max_outputs=2**31 - 1))
                seconds = time.perf_counter() - started
                quoted, covered = _quoted(v1_score(result))
                variants["frozen_loop"] = dict(quoted_fraction=quoted, covered_seconds=covered,
                                               seconds=round(seconds, 1), decisions=len(result.decisions),
                                               quotes=sum(d.decision.action == "QUOTE" for d in result.decisions))
                rows.append(dict(fixture=kind, union=union, trades=trades, records=records, **variants))
    return dict(measurement="S8", status="MEASURED", w0_window=[args.start, args.minutes],
                dense_window=[600, args.dense_minutes], rows=rows,
                rule="report only; the v2 fraction should not fall with B")


# -- S9 ---------------------------------------------------------------------------------------------------
def adversarial_rows(day, rng_seed):
    """Prints at 1e-4 share resolution, mostly fractional below the 75-share maximum leg, some up to 10^7
    shares, at extreme and mid ticks: every fill cost is exact at 1e-6 only by construction, never by luck."""
    import random
    rng = random.Random(f"s9-{day.day}-{rng_seed}")
    for row in day.rows():
        if row["kind"] == "trade":
            size = D(rng.randrange(1, 10**11 if rng.random() < .1 else 76 * 10**4)).scaleb(-4)
            payload = dict(row["payload"], size=str(size),
                           price=str(D("0.01") * rng.choice((1, 2, 30, 45, 50, 55, 70, 98, 99))))
            row = dict(row, payload=payload, payload_sha256=sha256(canonical_bytes(payload)))
        yield row


def s9(args):
    from maker_core.replay.v2.compaction import compact
    from maker_core.replay.v2.lockstep import DaySource
    sources = []
    for offset in range(args.days):
        # The quoting-dense day, so every policy fills; same conditions every day, so inventory carries.
        day = DenseDay(DAY + timedelta(days=offset), union=args.union, trades=args.trades, minutes=args.minutes)
        records = [record_from_row(r) for r in compact(adversarial_rows(day, offset), day.groups)]
        sources.append(DaySource(plan_of(day), (lambda r: (lambda: iter(r)))(records)))
    big = D(10) ** 12
    config = V2Config(hazard_per_minute=HAZARD, initial_cash=big, band_cap=big, order_cap=big, wallet_cap=big,
                      event_cap=big, factor_cap=big, debug=True)
    plan = run_plan(sources)
    engines = [EngineV2(replace(config, policy=p, fill_bound=b), plan)
               for b in ("strictly_through", "at_price") for p in ("informed-v0", "blind_re1", "no_quote", "clock_only")]
    started = time.perf_counter()
    error = None
    try:
        drive(sources, engines)
    except Exception as exc:  # the measurement reports any trap or mismatch as its result
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    checks = []
    for e in engines:
        fills = total(q(mul(f.price, f.size)) for f in e.fills)
        payouts = ZERO
        for cid, fact in e.settlements.items():
            for f in e.fills:
                if f.condition_id == cid:
                    payouts = add(payouts, q(mul(f.size, D(str(fact.p_yes if f.outcome == "YES" else 1 - fact.p_yes)))))
        expected_cash = q(add(sub(config.initial_cash, fills), payouts))
        held = total(s.inventory_cost for s in e.states.values())
        unsettled = total(q(mul(f.price, f.size)) for f in e.fills if f.condition_id not in e.settlements)
        checks.append(dict(policy=e.config.policy, bound=e.config.fill_bound, fills=len(e.fills),
                           settled_conditions=len(e.settlements), decisions=e.decision_count,
                           cash=str(e.cash), cash_equals_recomputation=e.cash == expected_cash,
                           reserve_equals_recomputation=e.R == total(s.reserve for s in e.states.values()),
                           inventory_equals_recomputation=e.I == held == unsettled,
                           max_fill_shares=str(max((f.size for f in e.fills), default=0))))
    ok = error is None and all(c["cash_equals_recomputation"] and c["reserve_equals_recomputation"]
                               and c["inventory_equals_recomputation"] for c in checks)
    return dict(measurement="S9", status="MEASURED", days=args.days, union=args.union, trades=args.trades,
                minutes_per_day=args.minutes, caps=str(big), debug_recompute_every_decision=True,
                error=error, seconds=round(elapsed, 1), engines=checks, pass_=ok)


MEASUREMENTS = dict(s3=s3, s5=s5, s7=s7, s8=s8, s9=s9)
DEFAULTS = dict(s3=dict(minutes=360, trades=2000), s5=dict(minutes=90, dense_minutes=30), s7=dict(minutes=1440, union=170, trades=2000),
                s8=dict(minutes=60, start=600, dense_minutes=10), s9=dict(minutes=60, days=16))


def add_arguments(parser):
    parser.add_argument("--minutes", type=int)
    parser.add_argument("--start", type=int)
    parser.add_argument("--days", type=int)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--dense-minutes", type=int)


def run(name, args):
    for key, value in DEFAULTS[name].items():
        if getattr(args, key, None) is None:
            setattr(args, key, value)
    result = MEASUREMENTS[name](args)
    if "pass_" in result:
        result["pass"] = result.pop("pass_")
    return result
