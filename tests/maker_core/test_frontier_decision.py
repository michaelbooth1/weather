"""Item 330 build 4 (b): the informed-v1 frontier decision rule on synthetic per-cluster runner totals.

Guards: the frontier decision rule (net pUSD per capture-day cluster decides and cents per quoted minute is only
  reported, a pre-declared quoted-minutes floor, an intersection-union statistic (observed min over the
  baselines, null row max over the baselines, per-pair centred) that holds level at the least-favourable
  configuration, Westfall-Young step-down max-T, Holm and a 2-day moving-block bootstrap reported only, an
  owner-signed margin, the full-bound guard, the exit fee only on resting_sell points, NO_GO default) is
  deterministic given its seed and pinned by a golden digest.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import random

import pytest

from maker_core.frontier import decision
from maker_core.frontier.decision import PROPOSED_RULE, DecisionRefused, DecisionRule, evaluate, event_day
from maker_core.frontier.grid import BASELINES, GRID, GRID_HASH

RULE = replace(PROPOSED_RULE, replicates=199, seed=7, min_effect_pusd_per_cluster=0.0)
STRONG = GRID[4].label  # a hold_to_settlement point
assert GRID[4].inventory == "hold_to_settlement" and GRID[5].inventory == "resting_sell"
GOLDEN_DIGEST = "118b8d8bcca8abe73a618d45b531549c8003ab2d3641abdf5e46f9b1b59ff801"
GOLDEN_PROPOSED_RESULT_DIGEST = "7650a08cba1e92f360ab7034a79eaf877bac8249a05d59038a8dfaa4caff5caa"
GOLDEN_PROPOSED_RULE_DIGEST = "87de64bd51992826b4b631934a75e51c6aec514c58483c79aaf00035ebfd6d03"


def totals(net_central, minutes, *, full=None, fills=0, adverse=0.0):
    full = net_central - .002 if full is None else full
    return {"reward": {"none": net_central + .003 + adverse, "central": net_central + adverse,
                       "full": full + adverse},
            "adverse_cost": adverse, "filled_shares": D(fills), "quoted_seconds": minutes * 60.0}


def clusters(k=12, seed=3, strong=STRONG, lift=.01, overrides=None):
    """``k`` clusters; every point earns noise around zero except ``strong``, which earns ``lift`` pUSD/min more."""
    rng = random.Random(seed)
    out = {}
    for c in range(k):
        strategies = {"no-quote": totals(0.0, 0.0), "blind_re1": totals(rng.gauss(-.002, .004) * 60, 60),
                      "informed-v0": totals(0.0, 0.0)}
        for p in GRID:
            minutes = 60 + rng.randrange(30)
            per_minute = rng.gauss(0, .004) + (lift if p.label == strong else 0.0)
            strategies[p.label] = totals(per_minute * minutes, minutes)
        for label, value in (overrides or {}).items():
            strategies[label] = value(c)
        out[(date(2027, 1, 1) + timedelta(days=c)).isoformat()] = {
            "grid_hash": GRID_HASH, "decay": "d" * 64, "fill_model_binding": "binding", "label": "DESCRIPTIVE",
            "registration_sha256": None, "strategies": strategies}
    return out


def row(result, label):
    return next(r for r in result["points"] if r["strategy"] == label)


def test_golden_winner_and_digest():
    result = evaluate(clusters(), RULE)
    assert result["verdict"] == "WINNER" and result["winner"] == STRONG
    assert result["cluster_count"] == 12 and result["reasons"] == []
    strong = row(result, STRONG)
    assert all(strong["conditions"].values())
    assert strong["p_westfall_young"] <= RULE.alpha
    assert result["digest"] == GOLDEN_DIGEST


def test_proposed_rule_parameters_and_digest_are_pinned():
    spec = PROPOSED_RULE.spec()
    assert spec["parameters"] == {
        "replicates": 9999, "seed": 20261114, "cluster_unit": "capture_day", "alpha": .05,
        "min_effect_pusd_per_cluster": None, "min_quoted_minutes_per_cluster": 60.0,
        "exit_fee_per_filled_share": .0125, "max_cost_unavailable_share": .02, "max_cost_unavailable_share_per_cluster": .10,
        "sensitivity_block_length": 2,
        "decision_bound": "central", "guard_bound": "full",
        "min_clusters": 10, "baselines": list(BASELINES)}
    assert spec["metric"] == "net_pusd_per_capture_day" and spec["exit_fee_applies_to"] == "resting_sell"
    assert PROPOSED_RULE.digest() == GOLDEN_PROPOSED_RULE_DIGEST


def test_the_unsigned_margin_never_lets_a_point_win():
    result = evaluate(clusters(), PROPOSED_RULE)
    assert (result["verdict"], result["winner"]) == ("NO_GO", None)
    assert result["reasons"] == ["margin_unsigned", "no_point_passes_all_conditions"]
    strong = row(result, STRONG)
    assert strong["conditions"]["westfall_young"] and not strong["conditions"]["min_effect"]
    assert result["digest"] == GOLDEN_PROPOSED_RESULT_DIGEST


def test_deterministic_given_the_seed_and_order_of_clusters():
    data = clusters()
    one = evaluate(data, RULE)
    two = evaluate(dict(reversed(list(data.items()))), RULE)
    assert one["digest"] == two["digest"]
    assert evaluate(data, replace(RULE, seed=8))["digest"] != one["digest"]


def test_every_rule_parameter_enters_the_digest():
    base = RULE.digest()
    for change in (dict(replicates=299), dict(seed=8), dict(alpha=.01), dict(min_effect_pusd_per_cluster=.03),
                   dict(min_effect_pusd_per_cluster=None), dict(min_quoted_minutes_per_cluster=30.0),
                   dict(exit_fee_per_filled_share=.01), dict(max_cost_unavailable_share=0.0),
                   dict(max_cost_unavailable_share_per_cluster=.2),
                   dict(sensitivity_block_length=3), dict(decision_bound="none"), dict(guard_bound="central"),
                   dict(min_clusters=11)):
        assert replace(RULE, **change).digest() != base, change


@pytest.mark.parametrize("change,reason", [
    (dict(replicates=10), "replicates_too_few"), (dict(cluster_unit="event_day"), "unknown_cluster_unit"),
    (dict(alpha=0), "alpha_out_of_range"), (dict(min_effect_pusd_per_cluster=-1), "min_effect_pusd_per_cluster_invalid"),
    (dict(min_quoted_minutes_per_cluster=-1), "min_quoted_minutes_per_cluster_invalid"),
    (dict(decision_bound="max"), "unknown_bound"), (dict(min_clusters=1), "min_clusters_invalid"),
    (dict(max_cost_unavailable_share=1.5), "max_cost_unavailable_share_invalid"),
    (dict(max_cost_unavailable_share_per_cluster=-.1), "max_cost_unavailable_share_per_cluster_invalid"),
    (dict(sensitivity_block_length=1), "sensitivity_block_length_invalid"),
    (dict(baselines=("no-quote",)), "rule_requires_all_baselines"),
])
def test_rule_parameters_are_validated(change, reason):
    with pytest.raises(DecisionRefused, match=reason):
        replace(RULE, **change)


# -- round 3 regressions -------------------------------------------------------------------------------------
def test_a_sparse_quoter_with_the_best_cents_per_minute_does_not_win():
    """Pooled cents per quoted minute picked the thinnest quoter. The winner is now the largest net per capture
    day among eligible points, and a point under the quoted-minutes floor cannot win at all."""
    thin, broad = GRID[4].label, GRID[8].label
    data = clusters(lift=0.0, overrides={
        thin: lambda c: totals(.05 * (1 + .01 * c), 1.0),          # 5 c/min, but one minute a day: 0.05 pUSD/day
        broad: lambda c: totals(.012 * 90 * (1 + .01 * c), 90.0),  # 1.2 c/min over 90 minutes: 1.08 pUSD/day
    })
    result = evaluate(data, RULE)
    thin_row, broad_row = row(result, thin), row(result, broad)
    assert thin_row["cents_per_quoted_minute"]["central"] > broad_row["cents_per_quoted_minute"]["central"]
    assert not thin_row["conditions"]["eligible_quoted_minutes"]
    assert result["winner"] == broad
    no_floor = evaluate(data, replace(RULE, min_quoted_minutes_per_cluster=0.0))
    assert row(no_floor, thin)["conditions"]["eligible_quoted_minutes"] and no_floor["winner"] == broad


def test_the_statistic_is_the_minimum_over_every_baseline():
    """No best baseline is re-chosen per resample: T_j is the smallest per-baseline T, so a point that clearly
    beats no-quote but not blind_re1 is not significant."""
    def rich_blind(c):
        return totals(.6 + (.05 if c % 2 else -.05), 60)

    def close_to_blind(c):
        return totals(.6 + (.05 if c % 3 else -.06), 70)

    data = clusters(lift=0.0, overrides={"blind_re1": rich_blind, STRONG: close_to_blind})
    result = evaluate(data, RULE)
    for r in result["points"]:
        assert r["t"] == min(r["t_vs_baseline"].values())
        assert set(r["delta_vs_baseline"]) == set(BASELINES)
    strong = row(result, STRONG)
    assert strong["t_vs_baseline"]["no-quote"] > 5 and strong["t_vs_baseline"]["blind_re1"] < 2
    assert not strong["conditions"]["westfall_young"] and result["winner"] != STRONG


def test_the_exit_fee_is_charged_only_on_resting_sell_points():
    hold, resting = GRID[4], GRID[5]
    data = clusters(lift=0.0, overrides={p.label: (lambda c: totals(.6, 60, fills=20)) for p in (hold, resting)})
    result = evaluate(data, RULE)
    assert row(result, hold.label)["net_pusd_per_cluster"]["central"] == pytest.approx(.6)
    assert row(result, resting.label)["net_pusd_per_cluster"]["central"] == pytest.approx(.6 - .0125 * 20)
    assert row(result, hold.label)["exit_fee_per_filled_share"] == 0.0
    assert decision.exit_fee("blind_re1", RULE) == 0.0


def test_no_quoted_minutes_is_ineligible_not_zero():
    data = clusters(lift=0.0, overrides={STRONG: lambda c: totals(-.3, 0.0)})
    result = evaluate(data, replace(RULE, min_quoted_minutes_per_cluster=0.0))
    strong = row(result, STRONG)
    assert strong["cents_per_quoted_minute"]["central"] is None
    assert not strong["conditions"]["eligible_quoted_minutes"]
    assert result["baselines"]["no-quote"]["cents_per_quoted_minute"]["central"] is None
    assert decision.cents_per_quoted_minute([-1.0], [0.0]) is None


# -- round 4 regressions -------------------------------------------------------------------------------------
def _one_null_pair(rng, k=12):
    """One point j: j - blind_re1 has mean 0 (the null pair); j - no-quote (+1) and j - informed-v0 (+2) are far
    positive, with the pairs only partly correlated: the intersection-union least-favourable configuration."""
    point = GRID[0].label
    out = {}
    for c in range(k):
        blind, noise, informed = rng.gauss(1.0, .3), rng.gauss(0.0, .3), rng.gauss(-1.0, .3)
        out[(date(2027, 1, 1) + timedelta(days=c)).isoformat()] = {
            "grid_hash": GRID_HASH, "decay": "d" * 64, "fill_model_binding": "binding", "label": "DESCRIPTIVE",
            "registration_sha256": None, "strategies": {
                "no-quote": totals(0.0, 0.0), "blind_re1": totals(blind, 60), "informed-v0": totals(informed, 60),
                point: totals(blind + noise, 70)}}
    return out


def test_the_intersection_union_test_holds_level_with_one_null_pair():
    """Round 4 (A): with one pair at the null and two far positive, the min over pairs in the null row put the
    null quantile below the single pair's, so the old rule rejected about 19% of the time at alpha 0.05 (400
    seeded datasets, B = 199). The max over pairs in the null row holds level (about 6.5%, the small-K
    bootstrap's own slack)."""
    rng = random.Random(5)
    rule = replace(PROPOSED_RULE, replicates=199, min_effect_pusd_per_cluster=0.0)
    sims = 400
    rejections = sum(evaluate(_one_null_pair(rng), rule)["points"][0]["p_westfall_young"] <= rule.alpha
                     for _ in range(sims))
    assert rejections / sims <= .10
    assert PROPOSED_RULE.spec()["statistic"] == "observed_min_over_baselines_null_max_over_baselines_bootstrap_scaled_centred"


def test_the_block_bootstrap_is_reported_and_never_decides(monkeypatch):
    """Round 4 (D): the 2-day moving-block bootstrap is a sensitivity. Even a degenerate block scheme (every
    resample one cluster, so no evidence) leaves the verdict, the winner and the deciding p-values unchanged."""
    data = clusters()
    base = evaluate(data, RULE)
    assert all("block_sensitivity" in r for r in base["points"])
    assert row(base, STRONG)["block_sensitivity"]["p_westfall_young"] <= 1.0

    def degenerate(rule, k):
        for _ in range(rule.replicates):
            yield [k] + [0] * (k - 1)

    monkeypatch.setattr(decision, "_block_resamples", degenerate)
    broken = evaluate(data, RULE)
    assert row(broken, STRONG)["block_sensitivity"]["p_westfall_young"] == 1.0
    assert (broken["verdict"], broken["winner"]) == (base["verdict"], base["winner"]) == ("WINNER", STRONG)
    assert [r["p_westfall_young"] for r in broken["points"]] == [r["p_westfall_young"] for r in base["points"]]
    longer = evaluate(data, replace(RULE, sensitivity_block_length=4))
    assert (longer["verdict"], longer["winner"]) == (base["verdict"], base["winner"])


def test_moving_blocks_cover_k_clusters_in_consecutive_runs():
    rule = replace(RULE, replicates=99)
    for weights in decision._block_resamples(rule, 7):
        assert sum(weights) == 7 and len(weights) == 7


# -- unchanged behaviour ---------------------------------------------------------------------------------------
def test_significant_point_below_the_margin_is_no_go():
    result = evaluate(clusters(), replace(RULE, min_effect_pusd_per_cluster=1000.0))
    strong = row(result, STRONG)
    assert strong["conditions"]["westfall_young"] and not strong["conditions"]["min_effect"]
    assert result["verdict"] == "NO_GO" and result["winner"] is None
    assert result["reasons"] == ["no_point_passes_all_conditions"]


def test_full_bound_guard_blocks_a_point_that_loses_under_full_reaction():
    def losing_under_full(c):
        return totals(.01 * 60 + c * 1e-4, 60, full=-1.0)
    result = evaluate(clusters(lift=0.0, overrides={STRONG: losing_under_full}), RULE)
    strong = row(result, STRONG)
    assert strong["conditions"]["westfall_young"] and strong["conditions"]["min_effect"]
    assert not strong["conditions"]["full_bound_non_negative"]
    assert result["winner"] != STRONG


def test_too_few_clusters_is_no_go_even_with_a_strong_point():
    result = evaluate(clusters(k=5, lift=.05), RULE)
    assert result["verdict"] == "NO_GO" and result["reasons"] == ["underpowered_clusters"]


def test_identical_clusters_carry_no_evidence():
    data = clusters(k=12)
    first = next(iter(data.values()))
    same = {key: first for key in data}
    result = evaluate(same, RULE)
    assert all(r["t"] == 0.0 and not r["conditions"]["westfall_young"] for r in result["points"])
    assert result["verdict"] == "NO_GO"


def test_holm_is_only_reported():
    result = evaluate(clusters(), RULE)
    for r in result["points"]:
        assert r["p_westfall_young"] >= r["p_marginal"] - 1e-12
        assert "holm" not in "".join(r["conditions"])


def test_westfall_young_is_monotone_down_the_t_order():
    result = evaluate(clusters(), RULE)
    ordered = sorted(result["points"], key=lambda r: -r["t"])
    values = [r["p_westfall_young"] for r in ordered]
    assert values == sorted(values)


def test_adverse_cost_enters_the_metric():
    data = clusters(overrides={STRONG: lambda c: totals(.54, 60, adverse=.06, fills=20)})
    result = evaluate(data, RULE)
    assert row(result, STRONG)["net_pusd_per_cluster"]["central"] == pytest.approx(.54)
    assert row(result, STRONG)["cents_per_quoted_minute"]["central"] == pytest.approx(100 * .54 / 60)


@pytest.mark.parametrize("mutate,reason", [
    (lambda d: d[min(d)].update(decay="e" * 64), "clusters_disagree_on_decay"),
    (lambda d: d[min(d)]["strategies"].pop(GRID[0].label), "clusters_disagree_on_strategies"),
    (lambda d: d[min(d)].update(fill_model_binding="other"), "clusters_disagree_on_fill_model_binding"),
])
def test_inconsistent_clusters_are_refused(mutate, reason):
    data = clusters()
    mutate(data)
    with pytest.raises(DecisionRefused, match=reason):
        evaluate(data, RULE)


def test_event_day_is_the_target_date_of_a_local_midnight_close():
    for offset in (-11, -10, -5, 0, 8, 11, 12):
        local_midnight = datetime(2026, 11, 2, tzinfo=timezone(timedelta(hours=offset)))
        assert event_day(local_midnight) == date(2026, 11, 1)
    # outside (-12, +12] the rule no longer names the target date
    assert event_day(datetime(2026, 11, 2, tzinfo=timezone(timedelta(hours=-12)))) == date(2026, 11, 2)
    with pytest.raises(DecisionRefused, match="naive_close"):
        event_day(datetime(2026, 11, 2))


def test_decision_module_is_pure():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(decision.__file__).read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert names <= {"__future__", "array", "dataclasses", "datetime", "decimal", "math", "random", "typing",
                     "maker_core"}


def test_the_promotion_block_se_reuses_the_decision_moving_blocks():
    """Round 6 (2): prereg §10.5a's block SE is the SD (n - 1) of the means of ``_block_resamples`` (moving
    2-day blocks, seed + 1, ``replicates`` draws, no wrap), deterministic, and zero for a constant series."""
    rule = replace(PROPOSED_RULE, replicates=499)
    values = [((7 * i) % 11) - 3.0 for i in range(28)]
    means = [sum(w * v for w, v in zip(weights, values)) / 28 for weights in decision._block_resamples(rule, 28)]
    centre = sum(means) / len(means)
    expected = (sum((m - centre) ** 2 for m in means) / (len(means) - 1)) ** .5
    assert decision.mean_se_moving_block(values, rule) == pytest.approx(expected, rel=1e-12)
    assert decision.mean_se_moving_block(values, rule) == decision.mean_se_moving_block(values, rule)
    assert decision.mean_se_moving_block([2.0] * 28, rule) == pytest.approx(0, abs=1e-12)
    assert PROPOSED_RULE.sensitivity_block_length == 2 and PROPOSED_RULE.replicates == 9999
    with pytest.raises(DecisionRefused, match="block_se_needs_two_days"):
        decision.mean_se_moving_block([1.0], rule)
