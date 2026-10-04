"""The frozen five-minute pull endpoint, read from run-length intervals (W5; registration draft §7).

Same opportunity set, midpoint rule, horizon-coverage rule, counts, cells, bootstrap and status as
``maker_core.replay.pull_efficiency`` at the exam tree. The difference is the input: the policy's state at
a minute start is read from its run-length intervals ("final resting state at t, carried forward"),
and midpoints come from the shared parse's compact series, so no whole-run span list or book list is held.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict

from maker_core.replay.bundle import BundleError
from maker_core.replay.pull_efficiency import COUNT_FIELDS, _counts, _ratio, ratio_intervals
from maker_core.replay.v2.score import MINUTE_US, US, from_us, us

LARGE_MOVE_MID2 = 100_000  # |after - before| >= 0.05, in (bid + ask) x 1e6 units
END_TOLERANCE_US = 120 * US
HORIZON_US = 5 * MINUTE_US


def candidate_minutes(windows):
    """Minute starts (microseconds) in the union of one condition's windows, as the frozen loop counts them."""
    until = None
    for start, end in sorted((us(a), us(b)) for a, b in windows):
        at = start - start % MINUTE_US
        if at < start:
            at += MINUTE_US
        if until is not None:
            at = max(at, until)
        while at < end:
            yield at
            at += MINUTE_US
        until = at if until is None else max(until, at)


def windows_by_condition(plan):
    result = defaultdict(list)
    for day in plan.days:
        for cid, windows in day.windows.items():
            result[cid].extend(windows)
    return result


def _state(runs, starts, at):
    i = bisect_right(starts, at) - 1
    if i >= 0 and runs[i][0] <= at < runs[i][1]:
        return runs[i]
    return None


def _covers(runs, starts, start, stop):
    i = bisect_right(starts, start) - 1
    return i >= 0 and stop < runs[i][1]


def _endpoint(series, at):
    times, mids, as_of = series
    i = bisect_right(times, at) - 1
    while i >= 0 and at - times[i] <= MINUTE_US:
        if at - as_of[i] <= MINUTE_US:
            break
        i -= 1
    if i < 0 or at - times[i] > MINUTE_US:
        return None, "MISSING_START_MIDPOINT"
    target = at + HORIZON_US
    j = bisect_left(times, target)
    if j == len(times) or times[j] - target > END_TOLERANCE_US:
        return None, "MISSING_END_MIDPOINT"
    return (mids[i], mids[j], times[j]), None


def pull_endpoint(plan, informed, clock, books, aggregate_match, *, max_candidates=2**31,
                  replicates=2000, seed=20260926, check=lambda: None):
    """Counts per band-day and per market/UTC-date cell, the ratio, its bootstrap and the frozen status."""
    if informed.policy != "informed-v0" or clock.policy != "clock_only" or informed.bound != clock.bound:
        raise BundleError("unpaired_pull_traces")
    markets = {c.condition_id: c.market_id for day in plan.days for c in day.conditions}
    rows, excluded, excluded_rows = {}, Counter(), defaultdict(Counter)
    candidates = 0
    empty = ((), (), ())
    for cid, windows in sorted(windows_by_condition(plan).items()):
        a_runs, b_runs = informed.state_runs.get(cid, []), clock.state_runs.get(cid, [])
        a_starts, b_starts = [r[0] for r in a_runs], [r[0] for r in b_runs]
        a_cov, b_cov = informed.covered_runs.get(cid, []), clock.covered_runs.get(cid, [])
        a_cov_starts, b_cov_starts = [r[0] for r in a_cov], [r[0] for r in b_cov]
        series = books.pull.get(cid, empty)
        for at in candidate_minutes(windows):
            check()
            candidates += 1
            if candidates > max_candidates:
                raise BundleError("pull_opportunity_cap")
            a, b = _state(a_runs, a_starts, at), _state(b_runs, b_starts, at)
            if a is None or b is None:
                raise BundleError("pull_state_missing")
            key = (from_us(at).date().isoformat(), markets[cid], cid)
            endpoint, reason = _endpoint(series, at)
            if endpoint is not None:
                before, after, stop = endpoint
                if not (_covers(a_cov, a_cov_starts, at, stop) and _covers(b_cov, b_cov_starts, at, stop)):
                    reason = "UNCOVERED_HORIZON"
            if reason:
                excluded[reason] += 1
                excluded_rows[key][reason] += 1
                continue
            counts = rows.setdefault(key, _counts())
            move = abs(after - before) >= LARGE_MOVE_MID2
            counts["opportunities"] += 1
            counts["large_moves"] += int(move)
            for policy, state in (("informed", a), ("clock", b)):
                pulled = not state[2]
                counts[policy + "_pulled"] += int(pulled)
                counts[policy + "_removed"] += int(pulled and move)
    cells = defaultdict(_counts)
    for (day, market, _), counts in sorted(rows.items()):
        for name in COUNT_FIELDS:
            cells[day, market][name] += counts[name]
    totals = {name: sum(c[name] for c in cells.values()) for name in COUNT_FIELDS}
    intervals = ratio_intervals(cells, replicates=replicates, seed=seed, check=check)
    ratio = _ratio(totals)
    difference = abs(totals["informed_pulled"] - totals["clock_pulled"])
    matched = aggregate_match.get("status") == "MATCHED" and difference <= 1
    reasons = []
    if not matched:
        reasons.append("UNMATCHED")
    if ratio is None:
        reasons.append("UNIDENTIFIED")
    if any(e["date_clusters"] < 10 or e["market_clusters"] < 10 or e["valid_replicates"] < 100
           or e["interval"] is None for e in intervals.values()):
        reasons.append("UNDERPOWERED")
    status = reasons[0] if reasons else "HURDLE_MET" if ratio >= 2 else "HURDLE_NOT_MET"
    return dict(status=status, reasons=reasons, fill_bound=informed.bound, candidates=candidates, counts=totals,
                ratio=ratio,
                efficiencies={p: totals[p + "_removed"] / totals[p + "_pulled"] if totals[p + "_pulled"] else None
                              for p in ("informed", "clock")},
                exposure_match=dict(status="MATCHED" if matched else "UNMATCHED",
                                    aggregate_status=aggregate_match.get("status"),
                                    pulled_count_difference=difference, tolerance_minutes=1),
                intervals=intervals, exclusions=dict(sorted(excluded.items())),
                cells={f"{d}|{m}": dict(date=d, market_id=m, **c) for (d, m), c in sorted(cells.items())},
                band_days=[dict(date=d, market_id=m, condition_id=c, **counts) for (d, m, c), counts in sorted(rows.items())],
                excluded_band_days=[dict(date=d, market_id=m, condition_id=c, reasons=dict(sorted(v.items())))
                                    for (d, m, c), v in sorted(excluded_rows.items())])
