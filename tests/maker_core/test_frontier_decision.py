"""Item 330 build 4 (b): the informed-v1 frontier decision rule on synthetic per-cluster runner totals.

Guards: the frontier decision rule (net cents per quoted minute, paired event-day cluster bootstrap, Westfall-Young
  step-down max-T versus the best baseline, Holm reported only, margin and full-bound guard, NO_GO default) is
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

RULE = replace(PROPOSED_RULE, replicates=199, seed=7)
STRONG = GRID[5].label
GOLDEN_DIGEST = "64d0fc103a5360ff6c075221ffc5cc0ff73d62be8696a36f87b65b08ded6e2fd"
GOLDEN_PROPOSED_RESULT_DIGEST = "49efcd746e7e9beb3c6af64c1fa25f6f3aec4a3e2c4f77c3579d562e55cadf6a"
GOLDEN_PROPOSED_RULE_DIGEST = "3f7b56cdc8a022a580bd70daf372889cc62d92395e4045beb06892703b0aab9e"


def totals(net_central, minutes, *, full=None, fills=0):
    full = net_central - .002 if full is None else full
    return {"reward": {"none": net_central + .003, "central": net_central, "full": full}, "adverse_cost": 0.0,
            "filled_shares": D(fills), "quoted_seconds": minutes * 60.0}


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
    assert result["cluster_count"] == 12 and result["best_baseline"] in BASELINES
    strong = row(result, STRONG)
    assert all(strong["conditions"].values())
    assert strong["p_westfall_young"] <= RULE.alpha
    assert result["digest"] == GOLDEN_DIGEST


def test_proposed_rule_parameters_and_digest_are_pinned():
    spec = PROPOSED_RULE.spec()
    assert spec["parameters"] == {
        "replicates": 9999, "seed": 20261114, "cluster_unit": "event_day", "alpha": .05, "min_effect_cents": .02,
        "exit_fee_per_filled_share": .0125, "decision_bound": "central", "guard_bound": "full", "min_clusters": 10,
        "baselines": list(BASELINES)}
    assert PROPOSED_RULE.digest() == GOLDEN_PROPOSED_RULE_DIGEST


def test_golden_under_the_proposed_rule():
    result = evaluate(clusters(), PROPOSED_RULE)
    assert (result["verdict"], result["winner"]) == ("WINNER", STRONG)
    assert result["digest"] == GOLDEN_PROPOSED_RESULT_DIGEST


def test_deterministic_given_the_seed_and_order_of_clusters():
    data = clusters()
    one = evaluate(data, RULE)
    two = evaluate(dict(reversed(list(data.items()))), RULE)
    assert one["digest"] == two["digest"]
    assert evaluate(data, replace(RULE, seed=8))["digest"] != one["digest"]


def test_every_rule_parameter_enters_the_digest():
    base = RULE.digest()
    for change in (dict(replicates=299), dict(seed=8), dict(alpha=.01), dict(min_effect_cents=.03),
                   dict(exit_fee_per_filled_share=.01), dict(decision_bound="none"), dict(guard_bound="central"),
                   dict(min_clusters=11)):
        assert replace(RULE, **change).digest() != base, change


@pytest.mark.parametrize("change,reason", [
    (dict(replicates=10), "replicates_too_few"), (dict(cluster_unit="utc_day"), "unknown_cluster_unit"),
    (dict(alpha=0), "alpha_out_of_range"), (dict(min_effect_cents=-1), "min_effect_cents_invalid"),
    (dict(decision_bound="max"), "unknown_bound"), (dict(min_clusters=1), "min_clusters_invalid"),
    (dict(baselines=("no-quote",)), "rule_requires_all_baselines"),
])
def test_rule_parameters_are_validated(change, reason):
    with pytest.raises(DecisionRefused, match=reason):
        replace(RULE, **change)


def test_significant_point_below_the_margin_is_no_go():
    result = evaluate(clusters(), replace(RULE, min_effect_cents=1000.0))
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


def test_best_baseline_is_the_comparison_and_holm_is_only_reported():
    def rich_baseline(c):
        return totals(.003 * 60 + c * 1e-4, 60)
    result = evaluate(clusters(overrides={"blind_re1": rich_baseline}), RULE)
    assert result["best_baseline"] == "blind_re1"
    base = result["baselines"]["blind_re1"]["metric_cents_per_quoted_minute"]["central"]
    strong = row(result, STRONG)
    assert strong["delta_vs_best_baseline"] == pytest.approx(strong["metric_cents_per_quoted_minute"]["central"] - base)
    for r in result["points"]:
        assert r["p_westfall_young"] >= r["p_marginal"] - 1e-12
        assert "holm" not in "".join(r["conditions"])


def test_westfall_young_is_monotone_down_the_t_order():
    result = evaluate(clusters(), RULE)
    ordered = sorted(result["points"], key=lambda r: -r["t"])
    values = [r["p_westfall_young"] for r in ordered]
    assert values == sorted(values)


def test_exit_fee_and_adverse_cost_enter_the_metric():
    data = clusters(overrides={STRONG: lambda c: dict(totals(.6, 60), adverse_cost=.06, filled_shares=D(20))})
    result = evaluate(data, RULE)
    expected = 100 * (.6 - .06 - .0125 * 20) / 60
    assert row(result, STRONG)["metric_cents_per_quoted_minute"]["central"] == pytest.approx(expected)


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
    for offset in (-10, -5, 0, 8, 11):
        local_midnight = datetime(2026, 11, 2, tzinfo=timezone(timedelta(hours=offset)))
        assert event_day(local_midnight) == date(2026, 11, 1)
    with pytest.raises(DecisionRefused, match="naive_close"):
        event_day(datetime(2026, 11, 2))


def test_decision_module_is_pure():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(decision.__file__).read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert names <= {"__future__", "dataclasses", "datetime", "decimal", "math", "random", "typing", "maker_core"}
