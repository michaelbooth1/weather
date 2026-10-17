"""Frozen 110b descriptive estimands; no fitting, selection or promotion gate."""
from collections import defaultdict

import numpy as np


REPLICATES = 10_000
SEED = 110
BIN_EDGES = tuple(i / 10 for i in range(11))


def cluster_weights(cells):
    """Independent date/market multiplicities, multiplied on observed cells.

    Missing Cartesian cells remain missing. The date-only sensitivity uses the
    same date draws. Empty crossed draws are undefined, never zero losses.
    """
    dates = sorted({d for d, _ in cells})
    markets = sorted({m for _, m in cells})
    rng = np.random.default_rng(SEED)
    date_draws = rng.integers(len(dates), size=(REPLICATES, len(dates)))
    market_draws = rng.integers(len(markets), size=(REPLICATES, len(markets)))
    dw = np.stack([(date_draws == dates.index(d)).sum(axis=1) for d, _ in cells], axis=1)
    mw = np.stack([(market_draws == markets.index(m)).sum(axis=1) for _, m in cells], axis=1)
    return dw * mw, dw


def _interval(values):
    valid = values[np.isfinite(values)]
    return {"interval_90": np.quantile(valid, [.05, .95]).tolist() if len(valid) else None,
            "valid_replicates": len(valid), "undefined_replicates": REPLICATES - len(valid)}


def _estimate(numerator, denominator, weights):
    total = float(np.sum(denominator))
    result = {"estimate": float(np.sum(numerator) / total) if total else None}
    for name, w in zip(("crossed", "date_only"), weights):
        n, d = w @ numerator, w @ denominator
        draws = np.divide(n, d, out=np.full(REPLICATES, np.nan), where=d > 0)
        result[name] = _interval(draws)
    return result


def _empty_bins():
    return [dict(lower=BIN_EDGES[i], upper=BIN_EDGES[i + 1], upper_inclusive=i == 9,
                 count=0, date_clusters=0, market_clusters=0, market_days=0, status="UNDERPOWERED",
                 **{name: dict(estimate=None, crossed=_interval(np.array([])), date_only=_interval(np.array([])))
                    for name in ("mean_probability", "observed_yes_frequency", "mean_declared_stdev")})
            for i in range(10)]


def summarize(rows):
    """Rows are selected event-hours with paired band probabilities and labels."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["target_date"], row["market_id"])].append(row)
    cells = sorted(grouped)
    ndate, nmarket = len({d for d, _ in cells}), len({m for _, m in cells})
    result = dict(status="UNDERPOWERED" if min(ndate, nmarket) < 10 else "DESCRIPTIVE",
                  date_clusters=ndate, market_clusters=nmarket, market_days=len(cells),
                  hours=len(rows), band_hours=sum(len(r["bands"]) for r in rows))
    if not cells:
        result.update(brier=None, reliability=_empty_bins(), market_day_scores=[])
        return result
    weights = cluster_weights(cells)
    losses, day_scores = [], []
    for target, market in cells:
        hours = grouped[(target, market)]
        loss = np.mean([[np.mean([(b[key] - b["observed_yes"]) ** 2 for b in h["bands"]])
                         for key in ("probability", "mid")] for h in hours], axis=0)
        losses.append([*loss, loss[0] - loss[1]])
        day_scores.append(dict(target_date=target, market_id=market, hours=len(hours),
                               provider_brier=float(loss[0]), mid_brier=float(loss[1]),
                               paired_difference=float(loss[0] - loss[1])))
    losses = np.asarray(losses)
    result["market_day_scores"] = day_scores
    result["brier"] = {name: _estimate(losses[:, i], np.ones(len(cells)), weights)
                       for i, name in enumerate(("provider", "mid", "provider_minus_mid"))}
    ci = result["brier"]["provider_minus_mid"]["crossed"]["interval_90"]
    result["interpretation"] = ("Difference is not distinguishable from zero; no evidence of improvement."
        if ci is None or ci[0] <= 0 <= ci[1] else
        "Descriptive interval excludes zero; no significance, promotion or live decision is defined.")
    bins = []
    for index in range(10):
        values = np.zeros((len(cells), 4))
        for i, cell in enumerate(cells):
            for row in grouped[cell]:
                for band in row["bands"]:
                    p = band["probability"]
                    # Searching edges avoids float multiplication moving 0.3 below its boundary.
                    b = min(int(np.searchsorted(BIN_EDGES, p, side="right")) - 1, 9)
                    if b == index:
                        values[i] += [1, p, band["observed_yes"], band["stdev"]]
        count = values[:, 0]
        present = [cell for cell, n in zip(cells, count) if n > 0]
        dates, markets = len({d for d, _ in present}), len({m for _, m in present})
        entry = dict(lower=BIN_EDGES[index], upper=BIN_EDGES[index + 1],
                     upper_inclusive=index == 9, count=int(count.sum()),
                     date_clusters=dates, market_clusters=markets, market_days=len(present),
                     status="UNDERPOWERED" if min(dates, markets) < 10 else "DESCRIPTIVE")
        for column, name in enumerate(("mean_probability", "observed_yes_frequency", "mean_declared_stdev"), 1):
            entry[name] = _estimate(values[:, column], count, weights)
        bins.append(entry)
    result["reliability"] = bins
    return result


PRIMARY_SOURCES = ("nbp", "fallback")
# T+1 Amendment 2: tied-knot NBP reads are reported beside, never pooled into, the primary.
TIED_SOURCES = ("nbp_atoms", "nbp_resolution_tails")


def tables(rows):
    result = {f"{source}_lead_{lead}": summarize([r for r in rows if r["source"] == source and r["lead"] == lead])
              for source in PRIMARY_SOURCES + TIED_SOURCES for lead in (1, 2)}
    result["pooled_descriptive"] = summarize([r for r in rows if r["source"] in PRIMARY_SOURCES])
    return result
