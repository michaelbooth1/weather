"""The informed-v1 frontier decision rule (item 330 build 4). Pure: no IO, no clock, deterministic given the seed.

It reads the runner's per-strategy totals for each **cluster** (one runner result per UTC capture day, built by
the CLI) and returns one verdict, ``WINNER`` or ``NO_GO``. It grants no authority; a winner is a candidate for the
shadow profile described in item 330, nothing more.

**Net.** For strategy s, decay bound b and cluster c, net modelled P&L in pUSD is

    N_b(s, c) = reward_b - adverse_cost - exit_fee(s) * filled_shares

where ``adverse_cost`` is the runner's filled shares times max(0.0043, the fill-cost provider's markout upper
bound). ``exit_fee(s)`` is ``exit_fee_per_filled_share`` (0.0125: the weather taker fee ``0.05 p (1 - p)`` at its
p = 0.5 maximum, a bound on flattening a fill as a taker; makers pay 0, EF §10o) for a ``resting_sell`` grid
point and 0 for a ``hold_to_settlement`` point and for the baselines, which hold. It is conservative for a
point's own net and **not** for a paired difference against a baseline.

**Primary unit (decides).** Mean net pUSD per cluster, ``m_b(s) = sum_c N_b(s, c) / K``: equivalently the total
net over the panel divided by its K capture days. A strategy that quotes thinly earns little in total, so the
unit does not reward sparse quoting. ``no-quote`` is 0. The decision bound is ``central``.

**Reported only.** Net cents per quoted minute, ``100 * sum_c N(s, c) / (sum_c quoted_seconds(s, c) / 60)``;
``None`` (not 0) when s never quoted.

**Eligibility.** A grid point quoting fewer than ``min_quoted_minutes_per_cluster * K`` minutes over the panel
cannot win (pre-declared floor), whatever its statistic.

**Inference.** A paired cluster bootstrap. The cluster unit is the UTC **capture day** (``capture_day``): every
band quoted that day, at horizon 1 or 2, is in it, so two horizons of one event never sit in different
clusters, and each cluster is a fully observed day. ``replicates`` resamples of the K clusters with
replacement are drawn by ``random.Random(seed).choices`` and shared by every strategy.

- For each grid point j and baseline k, ``delta_jk = m(j) - m(k)``; ``se_jk`` is the bootstrap standard
  deviation of ``delta*_jk``.
- **Intersection-union statistic.** The observed ``T_j = min_k delta_jk / se_jk``: a point must beat **every**
  baseline, so no best baseline is re-chosen per resample. A pair with ``se_jk`` at most ``SE_FLOOR``
  contributes 0 (no variation across clusters is no evidence).
- **Null row: the max, not the min.** ``T*_j = max_k (delta*_jk - mean(delta*_jk)) / se_jk``. Under
  intersection-union the least-favourable null is ONE pair at the null with the others far positive; the
  observed min then equals that pair's statistic, and its null tail is bounded by the max over pairs of the
  centred draws, so ``max_j max_k`` bounds every configuration (the min of centred draws would sit below a
  single pair's quantile and over-reject). Westfall-Young, the marginal p-values and Holm all use this row.
  T is a bootstrap-scaled, centred statistic whose p-values are bootstrap tail frequencies; it is not a
  studentized (pivotal) bootstrap.
- **Family-wise control (decides).** Westfall-Young step-down max-T, one-sided, over all grid points. With T
  sorted descending, ``p_(r) = (1 + #{b : max_{l >= r} T*_(l),b >= T_(r)}) / (B + 1)``, made monotone
  non-decreasing down the order.
- **Holm (disclosed sensitivity, never decides)** on the marginal p-values ``(1 + #{b : T*_j,b >= T_j}) / (B + 1)``.

**Serial dependence (sensitivity only).** Capture days are serially dependent (a band is quoted on two consecutive
days, and weather regimes persist). A pre-declared moving-block bootstrap (``sensitivity_block_length`` = 2
consecutive **observed** clusters in key order, so a missing capture day joins its neighbours into one block;
the same statistic and null row) is reported beside the main p-values. Block starts are uniform, so the first
and last clusters are under-weighted (each sits in fewer blocks). It **never
decides**: the verdict reads only the i.i.d. cluster bootstrap.

**Cost coverage (bound here, enforced by the CLI).** ``max_cost_unavailable_share`` is the largest share of
fill-cost decisions without a provider markout (which fall back to the 0.0043 floor) that a scored read
accepts over the panel, and ``max_cost_unavailable_share_per_cluster`` the largest on any one capture day (a
pooled bound alone lets one day at 50% holes pass). Both live in the rule so the digest binds them;
``evaluate`` does not read them.

**Winner.** Among eligible points that pass all three conditions, the one with the largest primary metric
(central):

1. Westfall-Young adjusted p <= ``alpha``;
2. ``min_k delta_jk >= min_effect_pusd_per_cluster`` (the owner signs the margin; while it is ``None`` no point
   passes, reason ``margin_unsigned``);
3. the point's own primary metric under the ``full`` competitor-response bound is >= 0.

Ties go to canonical grid order. With no passing point, or fewer than ``min_clusters`` clusters, the verdict is
``NO_GO``. ``DecisionRule`` carries every parameter the preregistration fixes; ``DecisionRule.digest()`` is the
value of its ``Decision rule digest:`` line.
"""
from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import math
import random
from typing import Mapping

from maker_core.evidence.journal import digest
from maker_core.frontier.grid import BASELINES, GRID, GridPoint
from maker_core.frontier.share_decay import BOUNDS

RULE_VERSION = "maker-core.frontier-decision.2"
RESULT_FORMAT = "maker-core.frontier-decision-result.2"
CLUSTER_UNITS = ("capture_day",)
VERDICTS = ("WINNER", "NO_GO")
EVENT_DAY_OFFSET = timedelta(hours=12)
SE_FLOOR = 1e-12  # pUSD per cluster; a bootstrap SD at or below it is float noise, so that pair's T is 0


class DecisionRefused(ValueError):
    """The inputs cannot be decided under this rule."""


def _nonnegative(name, value, *, optional=False):
    if optional and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise DecisionRefused(name + "_invalid")


@dataclass(frozen=True)
class DecisionRule:
    replicates: int = 9999
    seed: int = 20261114
    cluster_unit: str = "capture_day"
    alpha: float = 0.05
    min_effect_pusd_per_cluster: float | None = None  # the margin: an owner-signature field, unset until signed
    min_quoted_minutes_per_cluster: float = 60.0  # eligibility floor: total quoted minutes >= this times K
    exit_fee_per_filled_share: float = 0.0125  # resting_sell points only
    max_cost_unavailable_share: float = 0.02  # PROPOSED, pooled; score refuses above it (enforced by the CLI)
    max_cost_unavailable_share_per_cluster: float = 0.10  # PROPOSED, any one capture day; same enforcement
    sensitivity_block_length: int = 2  # moving-block bootstrap, reported only
    decision_bound: str = "central"
    guard_bound: str = "full"
    min_clusters: int = 10
    baselines: tuple = BASELINES

    def __post_init__(self):
        if type(self.replicates) is not int or self.replicates < 99:
            raise DecisionRefused("replicates_too_few")
        if type(self.seed) is not int:
            raise DecisionRefused("seed_must_be_int")
        if self.cluster_unit not in CLUSTER_UNITS:
            raise DecisionRefused("unknown_cluster_unit")
        if isinstance(self.alpha, bool) or not isinstance(self.alpha, (int, float)) or not 0 < self.alpha < 1:
            raise DecisionRefused("alpha_out_of_range")
        _nonnegative("min_effect_pusd_per_cluster", self.min_effect_pusd_per_cluster, optional=True)
        _nonnegative("min_quoted_minutes_per_cluster", self.min_quoted_minutes_per_cluster)
        _nonnegative("exit_fee_per_filled_share", self.exit_fee_per_filled_share)
        for name in ("max_cost_unavailable_share", "max_cost_unavailable_share_per_cluster"):
            _nonnegative(name, getattr(self, name))
            if getattr(self, name) > 1:
                raise DecisionRefused(name + "_invalid")
        if type(self.sensitivity_block_length) is not int or self.sensitivity_block_length < 2:
            raise DecisionRefused("sensitivity_block_length_invalid")
        if self.decision_bound not in BOUNDS or self.guard_bound not in BOUNDS:
            raise DecisionRefused("unknown_bound")
        if type(self.min_clusters) is not int or self.min_clusters < 2:
            raise DecisionRefused("min_clusters_invalid")
        if tuple(self.baselines) != BASELINES:
            raise DecisionRefused("rule_requires_all_baselines")

    @property
    def margin_signed(self) -> bool:
        return self.min_effect_pusd_per_cluster is not None

    def spec(self) -> dict:
        out = asdict(self)
        out["baselines"] = list(self.baselines)
        return {"version": RULE_VERSION, "metric": "net_pusd_per_capture_day",
                "reported": "net_cents_per_quoted_minute",
                "statistic": "observed_min_over_baselines_null_max_over_baselines_bootstrap_scaled_centred",
                "sensitivity_block": "moving_block_consecutive_capture_days_reported_only",
                "family": "westfall_young_stepdown_maxT_one_sided", "sensitivity": "holm_marginal_bootstrap",
                "selection": "max_primary_metric_among_eligible_passing",
                "exit_fee_applies_to": "resting_sell", "bootstrap": "paired_cluster_python_random_choices",
                "parameters": out}

    def digest(self) -> str:
        return digest(self.spec())


PROPOSED_RULE = DecisionRule()


def event_day(close_at_utc: datetime) -> date:
    """The event day of a market: the UTC date of its close minus 12 hours.

    Weather markets close at the local midnight after the target date; for a UTC offset in (-12 h, +12 h] this
    is the target date. A naive instant is refused.
    """
    if not isinstance(close_at_utc, datetime) or close_at_utc.tzinfo is None or close_at_utc.utcoffset() is None:
        raise DecisionRefused("naive_close")
    return (close_at_utc.astimezone(timezone.utc) - EVENT_DAY_OFFSET).date()


def _float(value) -> float:
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DecisionRefused("nonfinite_total")
    return float(value)


def _strategies(result) -> Mapping:
    strategies = result.get("strategies") if isinstance(result, Mapping) else None
    if not isinstance(strategies, Mapping):
        raise DecisionRefused("runner_result_required")
    return strategies


def exit_fee(strategy, rule) -> float:
    """The per-filled-share exit fee bound for ``strategy``: only a ``resting_sell`` grid point pays it."""
    if isinstance(strategy, GridPoint) and strategy.inventory == "resting_sell":
        return rule.exit_fee_per_filled_share
    return 0.0


def _cell(totals, fee, bound):
    """(net pUSD under ``bound``, quoted minutes) for one strategy in one cluster."""
    net = _float(totals["reward"][bound]) - _float(totals["adverse_cost"]) - fee * _float(totals["filled_shares"])
    return net, _float(totals["quoted_seconds"]) / 60


def cents_per_quoted_minute(nets, minutes):
    """Reported only: ``None`` when the strategy never quoted (ineligible, never 0)."""
    den = sum(minutes)
    return 100 * sum(nets) / den if den > 0 else None


def _sd(m2, n):
    return math.sqrt(max(0.0, m2 / (n - 1)))


def _holm(pvalues: Mapping[str, float], order) -> dict:
    ranked = sorted(order, key=lambda label: (pvalues[label], order.index(label)))
    m, running, out = len(ranked), 0.0, {}
    for i, label in enumerate(ranked):
        running = max(running, min(1.0, (m - i) * pvalues[label]))
        out[label] = running
    return out


def _resamples(rule, k):
    """The ``replicates`` i.i.d. resample weight vectors (cluster counts), regenerated identically per call."""
    rng = random.Random(rule.seed)
    for _ in range(rule.replicates):
        weights = [0] * k
        for index in rng.choices(range(k), k=k):
            weights[index] += 1
        yield weights


def _block_resamples(rule, k):
    """Moving-block resamples over the clusters in key (date) order: blocks of ``sensitivity_block_length``
    consecutive clusters, starts drawn uniformly, concatenated and cut to K. Sensitivity only."""
    length = min(rule.sensitivity_block_length, k)
    rng = random.Random(rule.seed + 1)
    for _ in range(rule.replicates):
        weights, drawn = [0] * k, 0
        while drawn < k:
            start = rng.randrange(k - length + 1)
            for index in range(start, min(start + length, start + k - drawn)):
                weights[index] += 1
                drawn += 1
        yield weights


def _inference(draws, rule, series, names, points, delta, k):
    """(se, pair t, t, Westfall-Young p, marginal p, Holm) for one resampling scheme (module doc)."""
    pairs = list(delta)
    mean, m2 = dict.fromkeys(pairs, 0.0), dict.fromkeys(pairs, 0.0)
    count = 0
    for count, weights in enumerate(draws(rule, k), start=1):  # Welford: identical draws give SD 0
        sample = {s: sum(w * n for w, n in zip(weights, series[s]) if w) / k for s in names}
        for pair in pairs:
            d = sample[pair[0]] - sample[pair[1]]
            step = d - mean[pair]
            mean[pair] += step / count
            m2[pair] += step * (d - mean[pair])
    se = {p: _sd(m2[p], count) for p in pairs}
    pair_t = {p: (delta[p] / se[p] if se[p] > SE_FLOOR else 0.0) for p in pairs}
    t = {j: min(pair_t[j, base] for base in rule.baselines) for j in points}
    null = []
    for weights in draws(rule, k):  # the same draws again
        sample = {s: sum(w * n for w, n in zip(weights, series[s]) if w) / k for s in names}
        row = array("d")
        for j in points:
            row.append(max(((sample[j] - sample[base] - mean[j, base]) / se[j, base]
                            if se[j, base] > SE_FLOOR else 0.0) for base in rule.baselines))
        null.append(row)
    # Westfall-Young step-down max-T (one-sided); ties in T keep canonical grid order.
    order = sorted(range(len(points)), key=lambda i: (-t[points[i]], i))
    exceed = [0] * len(order)
    for row in null:  # successive maxima from the bottom of the order
        acc = -math.inf
        for r in range(len(order) - 1, -1, -1):
            acc = max(acc, row[order[r]])
            if acc >= t[points[order[r]]]:
                exceed[r] += 1
    wy, running = {}, 0.0
    for r, i in enumerate(order):
        running = max(running, (1 + exceed[r]) / (count + 1))
        wy[points[i]] = running
    marginal = {j: (1 + sum(1 for row in null if row[i] >= t[j])) / (count + 1) for i, j in enumerate(points)}
    return se, pair_t, t, wy, marginal, _holm(marginal, points)


def evaluate(clusters: Mapping[str, Mapping], rule: DecisionRule = PROPOSED_RULE) -> dict:
    """The verdict over per-cluster runner results (``{cluster key: runner result}``); see the module doc."""
    if not isinstance(rule, DecisionRule):
        raise DecisionRefused("decision_rule_required")
    keys = sorted(clusters)
    if not keys:
        raise DecisionRefused("no_clusters")
    results = [clusters[k] for k in keys]
    identity = {}
    for field in ("grid_hash", "decay", "fill_model_binding", "label", "registration_sha256"):
        values = {r.get(field) for r in results}
        if len(values) != 1:
            raise DecisionRefused("clusters_disagree_on_" + field)
        identity[field] = values.pop()
    labels = set(_strategies(results[0]))
    if any(set(_strategies(r)) != labels for r in results):
        raise DecisionRefused("clusters_disagree_on_strategies")
    if not set(rule.baselines) <= labels:
        raise DecisionRefused("missing_baseline")
    by_label = {p.label: p for p in GRID}
    points = [p.label for p in sorted(by_label[label] for label in labels if label in by_label)]
    if not points or len(points) + len(rule.baselines) != len(labels):
        raise DecisionRefused("unknown_or_missing_grid_points")
    names = list(rule.baselines) + points
    fees = {s: exit_fee(by_label.get(s, s), rule) for s in names}
    cells = {b: {s: [_cell(_strategies(r)[s], fees[s], b) for r in results] for s in names} for b in BOUNDS}
    nets = {b: {s: [c[0] for c in cells[b][s]] for s in names} for b in BOUNDS}
    minutes = {s: [c[1] for c in cells[rule.decision_bound][s]] for s in names}
    k = len(keys)
    primary = {b: {s: sum(nets[b][s]) / k for s in names} for b in BOUNDS}
    central = primary[rule.decision_bound]
    pairs = [(j, base) for j in points for base in rule.baselines]
    delta = {(j, base): central[j] - central[base] for j, base in pairs}
    series = nets[rule.decision_bound]

    se, pair_t, t, wy, marginal, holm = _inference(_resamples, rule, series, names, points, delta, k)
    _, _, block_t, block_wy, block_marginal, _ = _inference(_block_resamples, rule, series, names, points, delta, k)

    enough = k >= rule.min_clusters
    floor = rule.min_quoted_minutes_per_cluster * k
    table, passing = [], []
    for j in points:
        worst = min(delta[j, base] for base in rule.baselines)
        eligible = sum(minutes[j]) >= floor and sum(minutes[j]) > 0
        conditions = {"eligible_quoted_minutes": eligible, "westfall_young": wy[j] <= rule.alpha,
                      "min_effect": rule.margin_signed and worst >= rule.min_effect_pusd_per_cluster,
                      "full_bound_non_negative": primary[rule.guard_bound][j] >= 0}
        if enough and all(conditions.values()):
            passing.append(j)
        table.append({
            "strategy": j, "net_pusd_per_cluster": {b: primary[b][j] for b in BOUNDS},
            "net_pusd_total": {b: primary[b][j] * k for b in BOUNDS},
            "cents_per_quoted_minute": {b: cents_per_quoted_minute(nets[b][j], minutes[j]) for b in BOUNDS},
            "quoted_minutes": sum(minutes[j]), "exit_fee_per_filled_share": fees[j],
            "delta_vs_baseline": {base: delta[j, base] for base in rule.baselines},
            "se_vs_baseline": {base: se[j, base] for base in rule.baselines},
            "t_vs_baseline": {base: pair_t[j, base] for base in rule.baselines},
            "min_delta_vs_baselines": worst, "t": t[j], "p_westfall_young": wy[j], "p_marginal": marginal[j],
            "p_holm_sensitivity": holm[j], "holm_significant_sensitivity": holm[j] <= rule.alpha,
            "block_sensitivity": {"t": block_t[j], "p_westfall_young": block_wy[j],
                                  "p_marginal": block_marginal[j]},
            "conditions": conditions})
    winner = max(passing, key=lambda j: (central[j], -points.index(j))) if passing else None
    reasons = []
    if not enough:
        reasons.append("underpowered_clusters")
    if not rule.margin_signed:
        reasons.append("margin_unsigned")
    if winner is None and enough:
        reasons.append("no_point_passes_all_conditions")
    result = {
        "format": RESULT_FORMAT, "rule": rule.spec(), "decision_rule_digest": rule.digest(), **identity,
        "clusters": keys, "cluster_count": k, "quoted_minutes_floor": floor,
        "baselines": {b: {"net_pusd_per_cluster": {x: primary[x][b] for x in BOUNDS},
                          "cents_per_quoted_minute": {x: cents_per_quoted_minute(nets[x][b], minutes[b])
                                                      for x in BOUNDS},
                          "quoted_minutes": sum(minutes[b])} for b in rule.baselines},
        "points": table, "verdict": "WINNER" if winner else "NO_GO", "winner": winner, "reasons": reasons,
    }
    result["digest"] = digest(result)
    return result
