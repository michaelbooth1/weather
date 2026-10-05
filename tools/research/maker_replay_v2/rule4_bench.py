"""Measurements for the rule-4 design option (``rule4.py``); fictional fixtures only, one call per process.

``wakes``: wakes per policy and view rule on a day source. ``equivalence``: rule ``now`` vs each other rule
on the same rows, comparing the strict fingerprint, the state streams and the economics. ``s3``: engine
runtime per pass under each view rule on W0's day with real view cadence (``drift`` re-stamps).
"""
from __future__ import annotations

import time

from maker_core.evidence.journal import digest
from maker_core.replay.v2.compaction import compact
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import DaySource, drive, items, record_from_row, run_plan
from maker_core.replay.v2.score import BandDayScorer
from tools.research.maker_replay_v2.bench import HAZARD, differential, fingerprint
from tools.research.maker_replay_v2.rule4 import view_rule
from tools.research.maker_replay_v2.sources import plan_of

POLICIES = ("informed-v0", "no_quote", "blind_re1", "clock_only")


def source(day, rows, form="v0.2"):
    rows = list(rows)
    if form == "v0.2":
        rows = list(compact(rows, day.groups))
    records = [record_from_row(r) for r in rows]
    return DaySource(plan_of(day), lambda: iter(records))


def run(src, policy, rule, *, debug=True):
    with view_rule(rule):
        engine = EngineV2(V2Config(hazard_per_minute=HAZARD, policy=policy, debug=debug, keep=True),
                          run_plan([src]))
        drive([src], [engine])
    return engine


def state_stream(engine):
    """Decisions that change a band's state: HOLDs dropped, per-band repeats of (action, legs, reason) dropped."""
    last, out = {}, []
    for event in engine.decisions:
        d = event.decision
        if d.action == "HOLD":
            continue
        key = (d.action, d.legs, d.reasons)
        if last.get(event.condition_id) == key:
            continue
        last[event.condition_id] = key
        out.append((event.at, event.condition_id, *key))
    return out


def economics(engine):
    """Intervals without the decision reason, plus money: what the scorer and the report read."""
    spans = sorted((i.condition_id, i.start, i.end, i.covered, i.legs, i.share_many, i.rate_per_day, i.reserved,
                    i.inventory_cost, i.evaluation_active) for i in engine.intervals)
    f = fingerprint(engine)
    return dict(spans=digest(_merge(spans)), fills=f["fills"], cash=f["cash"], settlements=f["settlements"],
                legs=f["legs"], inventory=f["inventory"], exclusions=f["exclusions"])


def _merge(spans):
    """Join adjacent spans whose economic fields are equal (a reason change alone splits a span)."""
    out = []
    for s in spans:
        if out and out[-1][0] == s[0] and out[-1][2] == s[1] and out[-1][3:] == s[3:]:
            out[-1] = (s[0], out[-1][1], s[2], *s[3:])
        else:
            out.append(s)
    return out


def wakes(src, rules, policies=POLICIES):
    result = {}
    for policy in policies:
        for rule in (rules if policy == "informed-v0" else ("now",)):
            engine = run(src, policy, rule, debug=False)
            result[f"{policy}/{rule}"] = dict(wakes=engine.wakes, decisions=engine.decision_count,
                                              fills=len(engine.fills))
    return result


def equivalence(src, rules, policies=POLICIES):
    out = {}
    for policy in policies:
        base = run(src, policy, "now")
        b_print, b_stream, b_econ = fingerprint(base), state_stream(base), economics(base)
        for rule in rules:
            other = run(src, policy, rule)
            o_print, o_stream, o_econ = fingerprint(other), state_stream(other), economics(other)
            first = next((i for i, (a, b) in enumerate(zip(b_stream, o_stream)) if a != b),
                         None if len(b_stream) == len(o_stream) else min(len(b_stream), len(o_stream)))
            out[f"{policy}/{rule}"] = dict(
                wakes=[base.wakes, other.wakes], decisions=[base.decision_count, other.decision_count],
                quotes=[sum(1 for e in base.decisions if e.decision.action == "QUOTE"),
                        sum(1 for e in other.decisions if e.decision.action == "QUOTE")],
                fills=[len(base.fills), len(other.fills)],
                strict_fingerprint_equal=b_print == o_print,
                strict_fields_differing=sorted(k for k in b_print if b_print[k] != o_print[k]),
                state_stream_equal=b_stream == o_stream, state_stream_lengths=[len(b_stream), len(o_stream)],
                first_state_difference=None if first is None else dict(
                    now=_show(b_stream, first), rule=_show(o_stream, first)),
                economics_equal=b_econ == o_econ,
                economics_differing=sorted(k for k in b_econ if b_econ[k] != o_econ[k]))
    return out


def _show(stream, i):
    if i >= len(stream):
        return None
    at, cid, action, legs, reasons = stream[i]
    return dict(at=at.isoformat(), condition=cid[:12], action=action, legs=len(legs), reasons=list(reasons))


def reference_differential(src, rule):
    """S5 under a view rule: v2 engine vs the reference schedule, every pass and clock trial."""
    with view_rule(rule):
        result = differential(src, V2Config(hazard_per_minute=HAZARD))
    return dict(divergences=len(result["divergences"]), compared=result.get("compared"))


def s3(day, rows_of, rules, repeats=2):
    started = time.perf_counter()
    src = source(day, rows_of(day))
    batches = list(items(src))
    plan = run_plan([src])
    built = time.perf_counter() - started
    stats = day.stats()
    band_minutes = stats["instantaneous_mean"] * ((day.window[1] - day.window[0]).total_seconds() / 60)
    out = dict(union=len(day.bands), records=sum(len(b) for _, b in batches), build_seconds=round(built, 1),
               views=sum(1 for _, b in batches for i in b if i.kind == "outcome_view"),
               books=sum(1 for _, b in batches for i in b if i.kind == "book"), rules={})
    for rule in rules:
        timings = []
        with view_rule(rule):
            for _ in range(repeats):
                engine = EngineV2(V2Config(hazard_per_minute=HAZARD),
                                  plan, sink=BandDayScorer("informed-v0", "strictly_through", pull_runs=True))
                t0 = time.perf_counter()
                engine.start_day(plan.days[0])
                for at, batch in batches:
                    engine.instant(at, batch)
                engine.finish()
                timings.append(time.perf_counter() - t0)
        out["rules"][rule] = dict(pass_seconds_min=round(min(timings), 3), wakes=engine.wakes,
                                  decisions=engine.decision_count,
                                  wakes_per_band_minute=round(engine.wakes / band_minutes, 3))
    return out

