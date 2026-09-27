"""Frozen five-minute move avoidance endpoint; consumes replay traces, performs no IO."""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
import random
import statistics

from maker_core.replay.bundle import BundleError
from maker_core.replay.inference import _quantile

COUNT_FIELDS = ("opportunities", "large_moves", "informed_pulled", "clock_pulled",
                "informed_removed", "clock_removed")
MINUTE = timedelta(minutes=1)


def _counts():
    return dict.fromkeys(COUNT_FIELDS, 0)


def _ratio(counts):
    a, b = counts["informed_pulled"], counts["clock_pulled"]
    x, y = counts["informed_removed"], counts["clock_removed"]
    return (x * b) / (a * y) if a and b and y else None


def ratio_intervals(cells, *, replicates=2000, seed=20260926, check=lambda: None):
    """Paired counts, summed with cluster multiplicities, never mean cell ratios."""
    if type(replicates) is not int or not 100 <= replicates <= 5000 or type(seed) is not int:
        raise BundleError("invalid_bootstrap_parameters")
    if len(cells) > 10_000:
        raise BundleError("invalid_bootstrap_cells")
    for counts in cells.values():
        if (set(counts) != set(COUNT_FIELDS)
                or any(type(v) is not int or v < 0 for v in counts.values())
                or counts["large_moves"] > counts["opportunities"]
                or any(counts[p + "_pulled"] > counts["opportunities"]
                       or counts[p + "_removed"] > min(counts[p + "_pulled"], counts["large_moves"])
                       for p in ("informed", "clock"))):
            raise BundleError("invalid_pull_counts")
    # Empty cells must not inflate effective cluster counts.
    cells = {k: v for k, v in sorted(cells.items()) if v["opportunities"]}
    dates, markets = sorted({k[0] for k in cells}), sorted({k[1] for k in cells})
    total = {f: sum(c[f] for c in cells.values()) for f in COUNT_FIELDS}
    estimate = _ratio(total)
    result = {}
    for crossed in (False, True):
        rng = random.Random(seed + int(crossed))
        draws, empty, undefined = [], 0, 0
        for _ in range(replicates):
            check()
            dw = Counter(rng.choices(dates, k=len(dates)))
            mw = Counter(rng.choices(markets, k=len(markets))) if crossed else None
            counts = _counts()
            for (d, m), values in cells.items():
                weight = dw[d] * (mw[m] if crossed else 1)
                for field in COUNT_FIELDS:
                    counts[field] += weight * values[field]
            ratio = _ratio(counts)
            if not counts["opportunities"]:
                empty += 1
            elif ratio is None:
                undefined += 1
            else:
                draws.append(ratio)
        enough = len(dates) >= 10 and len(markets) >= 10 and len(draws) >= 100
        se = statistics.stdev(draws) if len(draws) > 1 else None
        result["date_x_market" if crossed else "date"] = dict(
            status="UNIDENTIFIED" if estimate is None else "OK" if enough else "UNDERPOWERED",
            date_clusters=len(dates), market_clusters=len(markets), cells=len(cells), estimate=estimate,
            interval_level=.9, interval=[_quantile(draws, .05), _quantile(draws, .95)] if draws else None,
            replicates=replicates, valid_replicates=len(draws), empty_replicates=empty,
            undefined_replicates=undefined, omitted_replicates=empty + undefined, seed=seed + int(crossed),
            bootstrap_standard_error=se,
            mde_80_normal_approx=(1.6448536269514722 + .8416212335729143) * se if se is not None else None,
            power="NOT_ESTABLISHED; cluster count is a minimum, not a power claim",
            estimand="ratio of large moves removed per pulled minute on paired opportunities",
            method="independent date and market multiplicities" if crossed else "resampled whole dates")
    return result


class _Spans:
    def __init__(self, result):
        self.rows = defaultdict(list)
        self.covered = defaultdict(list)
        for span in result.spans:
            self.rows[span.condition_id].append(span)
        self.starts, self.covered_starts = {}, {}
        for cid, rows in self.rows.items():
            rows.sort(key=lambda s: s.start)
            self.starts[cid] = [s.start for s in rows]
            previous = None
            for span in rows:
                if span.start >= span.end or (previous is not None and span.start < previous):
                    raise BundleError("overlapping_or_invalid_pull_spans")
                previous = span.end
                if not (span.covered and span.evaluation_active):
                    continue
                runs = self.covered[cid]
                if runs and runs[-1][1] == span.start:
                    runs[-1] = (runs[-1][0], span.end)
                else:
                    runs.append((span.start, span.end))
            self.covered_starts[cid] = [s for s, _ in self.covered[cid]]

    def at(self, cid, at):
        i = bisect_right(self.starts.get(cid, ()), at) - 1
        if i >= 0:
            span = self.rows[cid][i]
            if span.start <= at < span.end:
                return span
        return None

    def covers(self, cid, start, end):
        i = bisect_right(self.covered_starts.get(cid, ()), start) - 1
        # Endpoint must itself be in an active covered span (half-open intervals).
        return i >= 0 and end < self.covered[cid][i][1]


class _Midpoints:
    def __init__(self, books):
        self.points = defaultdict(list)
        for at, cid, book in books:
            if not book.yes_bids or not book.yes_asks or not timedelta(0) <= at - book.as_of_utc <= MINUTE:
                continue
            bid, ask = max(p for p, _ in book.yes_bids), min(p for p, _ in book.yes_asks)
            if bid <= ask:
                self.points[cid].append((at, (bid + ask) / 2, book.as_of_utc))
        self.times = {}
        for cid, points in self.points.items():
            points.sort(key=lambda p: p[0])  # Stable: retain capture sequence for equal-time books.
            self.times[cid] = [p[0] for p in points]

    def endpoints(self, cid, at):
        points, times = self.points[cid], self.times.get(cid, ())
        i = bisect_right(times, at) - 1
        while i >= 0 and at - times[i] <= MINUTE:
            if at - points[i][2] <= MINUTE:
                break
            i -= 1
        if i < 0 or at - times[i] > MINUTE:
            return None, "MISSING_START_MIDPOINT"
        target = at + timedelta(minutes=5)
        j = bisect_left(times, target)
        if j == len(times) or times[j] - target > timedelta(seconds=120):
            return None, "MISSING_END_MIDPOINT"
        return (points[i][1], points[j][1], times[j]), None


def pull_efficiency(informed, clock, aggregate_match, *, replicates=2000, seed=20260926, check=lambda: None):
    """No policy reruns or exposure rematching; late decisions never earn earlier credit."""
    if (informed.config.policy != "informed-v0" or clock.config.policy != "clock_only"
            or informed.config.fill_bound != clock.config.fill_bound
            or informed.input_hashes != clock.input_hashes or informed.books != clock.books):
        raise BundleError("unpaired_pull_traces")
    left, right = _Spans(informed), _Spans(clock)
    marks = _Midpoints(informed.books)
    rows, excluded, excluded_rows = {}, Counter(), defaultdict(Counter)
    candidates = 0
    # Union of declared active minutes; missing one policy cannot hide a minute.
    for cid in sorted(left.rows.keys() | right.rows.keys()):
        ranges = sorted((s.start, s.end) for index in (left, right) for s in index.rows[cid] if s.evaluation_active)
        until = None
        for start, end in ranges:
            at = start.replace(second=0, microsecond=0)
            if at < start:
                at += MINUTE
            if until is not None:
                at = max(at, until)
            while at < end:
                check()
                candidates += 1
                if candidates > min(informed.config.max_events, clock.config.max_events):
                    raise BundleError("pull_opportunity_cap")
                a, b = left.at(cid, at), right.at(cid, at)
                market = (a or b).market_id
                if a and b and a.market_id != b.market_id:
                    raise BundleError("pull_cluster_identity_mismatch")
                key = (at.date().isoformat(), market, cid)
                endpoint, reason = marks.endpoints(cid, at)
                if endpoint is not None:
                    before, after, stop = endpoint
                    if not (left.covers(cid, at, stop) and right.covers(cid, at, stop)):
                        reason = "UNCOVERED_HORIZON"
                if reason:
                    excluded[reason] += 1
                    excluded_rows[key][reason] += 1
                else:
                    counts = rows.setdefault(key, _counts())
                    move = abs(after - before) >= Decimal("0.05")
                    counts["opportunities"] += 1
                    counts["large_moves"] += int(move)
                    for policy, span in (("informed", a), ("clock", b)):
                        pulled = not span.legs
                        counts[policy + "_pulled"] += int(pulled)
                        counts[policy + "_removed"] += int(pulled and move)
                at += MINUTE
            until = at if until is None else max(until, at)
    cells = defaultdict(_counts)
    for (day, market, _), counts in sorted(rows.items()):
        for field in COUNT_FIELDS:
            cells[day, market][field] += counts[field]
    totals = {field: sum(c[field] for c in cells.values()) for field in COUNT_FIELDS}
    intervals = ratio_intervals(cells, replicates=replicates, seed=seed, check=check)
    ratio = _ratio(totals)
    difference = abs(totals["informed_pulled"] - totals["clock_pulled"])
    matched = aggregate_match.get("status") == "MATCHED" and difference <= 1
    reasons = []
    if not matched:
        reasons.append("UNMATCHED")
    if ratio is None:
        reasons.append("UNIDENTIFIED")
    if any(e["date_clusters"] < 10 or e["market_clusters"] < 10
           or e["valid_replicates"] < 100 or e["interval"] is None for e in intervals.values()):
        reasons.append("UNDERPOWERED")
    status = reasons[0] if reasons else "HURDLE_MET" if ratio >= 2 else "HURDLE_NOT_MET"
    return dict(status=status, reasons=reasons, fill_bound=informed.config.fill_bound,
        candidates=candidates, counts=totals, ratio=ratio,
        efficiencies={p: totals[p + "_removed"] / totals[p + "_pulled"] if totals[p + "_pulled"] else None
                      for p in ("informed", "clock")},
        exposure_match=dict(status="MATCHED" if matched else "UNMATCHED",
                            aggregate_status=aggregate_match.get("status"), pulled_count_difference=difference,
                            tolerance_minutes=1),
        intervals=intervals, exclusions=dict(sorted(excluded.items())),
        band_days=[dict(date=d, market_id=m, condition_id=c, **counts) for (d, m, c), counts in sorted(rows.items())],
        excluded_band_days=[dict(date=d, market_id=m, condition_id=c, reasons=dict(sorted(counts.items())))
                            for (d, m, c), counts in sorted(excluded_rows.items())])
