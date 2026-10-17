"""Paired date and crossed date x market cluster bootstrap; no IID band resampling."""
from collections import Counter, defaultdict
import math
import random
import statistics

from maker_core.replay.bundle import BundleError


def _quantile(values, q):
    values = sorted(values)
    pos = (len(values) - 1) * q
    i = int(pos)
    return values[i] + (values[min(i+1, len(values)-1)]-values[i]) * (pos-i)


def paired_cells(candidate, baseline, metric="modeled_net_k1"):
    """Sum paired band-day deltas within market/date. Drop incomplete cells whole."""
    left = {(r["date"], r["market_id"], r["condition_id"]): r for r in candidate if r["active_seconds"]}
    right = {(r["date"], r["market_id"], r["condition_id"]): r for r in baseline if r["active_seconds"]}
    if len(left) != sum(bool(r["active_seconds"]) for r in candidate) or len(right) != sum(bool(r["active_seconds"]) for r in baseline):
        raise BundleError("duplicate_score_row")
    sums, bad = defaultdict(float), set()
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key), right.get(key)
        cell = key[:2]
        if (a is None or b is None or a["status"] != "COVERED" or b["status"] != "COVERED"
                or a.get(metric) is None or b.get(metric) is None
                or a["covered_seconds"] != b["covered_seconds"]):
            bad.add(cell)
            continue
        sums[cell] += float(a[metric]) - float(b[metric])
    return {key: value for key, value in sorted(sums.items()) if key not in bad}, sorted(bad)


def cluster_intervals(cells, *, replicates=2000, seed=20260926, check=lambda: None):
    if type(replicates) is not int or not 100 <= replicates <= 5000 or type(seed) is not int:
        raise BundleError("invalid_bootstrap_parameters")
    if len(cells) > 10_000 or any(not math.isfinite(v) for v in cells.values()):
        raise BundleError("invalid_bootstrap_cells")
    dates, markets = sorted({k[0] for k in cells}), sorted({k[1] for k in cells})
    ordered = sorted(cells.items())
    result = {}
    for crossed in (False, True):
        name = "date_x_market" if crossed else "date"
        rng = random.Random(seed + int(crossed))
        draws, empty = [], 0
        if cells:
            for _ in range(replicates):
                check()
                dw = Counter(rng.choices(dates, k=len(dates)))
                mw = Counter(rng.choices(markets, k=len(markets))) if crossed else None
                weighted = [(dw[d] * (mw[m] if crossed else 1), v) for (d, m), v in ordered]
                count = sum(w for w, _ in weighted)
                if count:
                    draws.append(sum(w*v for w, v in weighted) / count)
                else:
                    empty += 1  # Sparse panels can have no intersection; never impute zero.
        powered_clusters = len(dates) >= 10 and (not crossed or len(markets) >= 10)
        se = statistics.stdev(draws) if len(draws) > 1 else None
        result[name] = dict(status="OK" if powered_clusters and len(draws) >= 100 else "UNDERPOWERED",
            date_clusters=len(dates), market_clusters=len(markets), cells=len(cells),
            estimate=sum(cells.values())/len(cells) if cells else None,
            interval_level=.90, interval=[_quantile(draws, .05), _quantile(draws, .95)] if draws else None,
            replicates=replicates, valid_replicates=len(draws), empty_replicates=empty, seed=seed+int(crossed),
            bootstrap_standard_error=se, mde_80_normal_approx=(1.6448536269514722+.8416212335729143)*se if se is not None else None,
            power="NOT_ESTABLISHED; cluster count is a minimum, not a power claim",
            estimand="mean paired total modeled net per complete market/UTC-day",
            method="independent date and market multiplicities" if crossed else "resampled whole dates")
    return result
