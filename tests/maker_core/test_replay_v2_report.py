"""Maker replay v2 streaming scorer and per-cell report (W5); fictional fixtures only."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import hashlib
import json

import pytest

from maker_core.replay.engine import ReplayConfig, ReplayResult
from maker_core.replay.score import score as frozen_score
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import drive, run_plan
from maker_core.replay.v2.pipeline import run_passes
from maker_core.replay.v2.report import build_report, report_bytes, small_cluster_bound
from maker_core.replay.v2.score import BandDayScorer, Books
from tools.research.maker_replay_v2.dense import DenseDay
from tools.research.maker_replay_v2.sources import FIXTURE_ZONES, materialize

DAY = date(2026, 9, 27)
CONFIG = V2Config(hazard_per_minute=.001, debug=True)


class _Books:
    def __init__(self):
        self.rows = []

    def instant(self, at, batch):
        self.rows += [(at, i.condition_id, i.value) for i in batch if i.kind == "book" and i.error is None]


@pytest.mark.parametrize("policy", ("informed-v0", "clock_only"))
def test_streaming_band_days_equal_the_frozen_scorer_on_the_same_intervals(policy):
    source, _ = materialize(DenseDay(DAY, union=12, trades=20000, minutes=40))
    plan = run_plan([source])
    scorer, books, frozen_books = BandDayScorer(policy, "strictly_through"), Books(), _Books()
    engine = EngineV2(replace(CONFIG, policy=policy, keep=True), plan, sink=scorer)
    drive([source], [engine], observers=(books, frozen_books), time_zones=FIXTURE_ZONES)
    markets = {c.condition_id: c.market_id for c in plan.days[0].conditions}
    ours = scorer.band_days(engine.settlements, books, markets)
    result = ReplayResult(ReplayConfig(policy=policy), tuple(engine.decisions), tuple(engine.intervals),
                          tuple(engine.fills), (), {}, engine.cash, engine.settlements, tuple(frozen_books.rows))
    theirs = frozen_score(result)
    assert [(r["date"], r["condition_id"]) for r in ours] == [(r["date"], r["condition_id"]) for r in theirs]
    assert sum(r["quotes"] for r in ours) > 0 and (policy != "clock_only" or sum(r["fills"] for r in ours) > 0)
    for a, b in zip(ours, theirs):
        for name in ("active_seconds", "covered_seconds", "excluded_seconds", "pulled_seconds", "quotes",
                     "requotes", "fills", "unresolved_fills", "status"):
            assert a[name] == b[name], name
        for name in ("reward_k1", "nominal_rebate", "settled_inventory_pnl", "cash_hours"):
            assert abs(a[name] - b[name]) <= D("0.000001"), name
        assert str(a["reward_k1"]).count(".") and -a["reward_k1"].as_tuple().exponent == 6
        for horizon, m in a["markouts"].items():
            assert m["missing_fills"] == b["markouts"][horizon]["missing_fills"]
            assert m["pnl"] == b["markouts"][horizon]["pnl"]


def test_report_cells_sidecar_and_clarification_fields(tmp_path):
    source, _ = materialize(DenseDay(DAY, union=12, trades=20000, minutes=30))
    run = run_passes([source], CONFIG, time_zones=FIXTURE_ZONES)
    report, binding = build_report(run, CONFIG, replicates=200, sidecar_path=tmp_path / "sidecar.jsonl")
    raw = (tmp_path / "sidecar.jsonl").read_bytes()
    assert binding["sha256"] == hashlib.sha256(raw).hexdigest() and binding["bytes"] == len(raw)
    assert binding["records"] == raw.count(b"\n") and report["sidecar"] == binding
    passes = [json.loads(line) for line in raw.splitlines() if b'"kind":"pass"' in line]
    assert len(passes) == 8 and all(len(p["decision_sha256"]) == 64 for p in passes)
    primary = report["bounds"]["strictly_through"]
    for policy, cells in primary["scores"].items():
        days = primary["band_days"][policy]
        assert sum(c["covered_seconds"] for c in cells) == sum(r["covered_seconds"] for r in days)
        assert sum(c["reward_k1"] for c in cells) == sum(r["reward_k1"] for r in days)
        assert sum(c["excluded_intervals"] for c in cells) >= run.passes["strictly_through"][policy].scorer.excluded_runs
        assert all(set(c) >= {"modeled_net_k1", "modeled_net_k05", "modeled_net_k03", "exclusion_reasons",
                              "excluded_intervals_sha256", "pulled_seconds", "markouts"} for c in cells)
    assert any("pull" in c for c in primary["scores"]["informed-v0"])
    estimates = primary["intervals"]["no_quote:modeled_net_k03"]["intervals"]
    assert set(estimates["date"]["small_cluster"]) >= {"lower_bound", "clusters", "t_quantile"}
    decision = report["registered_decision"]
    assert decision["status"] in ("UNDERPOWERED", "HURDLE_NOT_MET", "UNMATCHED", "UNIDENTIFIED", "BLOCKED")
    assert set(decision["clarification_3"]) >= {"quote_presence", "economic_mde", "screen"}
    assert report_bytes(report) == report_bytes(build_report(run_passes([source], CONFIG, time_zones=FIXTURE_ZONES), CONFIG,
                                                             replicates=200)[0])  # deterministic


def test_small_cluster_bound_uses_t_with_g_minus_one_degrees():
    bound = small_cluster_bound(dict(date_clusters=14, market_clusters=12, estimate=1.0,
                                     bootstrap_standard_error=.5), "date_x_market")
    assert bound["clusters"] == 12
    assert bound["t_quantile"] == pytest.approx(1.7958848187, rel=1e-9)
    assert bound["lower_bound"] == pytest.approx(1.0 - 1.7958848187 * .5, rel=1e-9)
    assert small_cluster_bound(dict(date_clusters=1, market_clusters=1, estimate=1.0,
                                    bootstrap_standard_error=None), "date")["lower_bound"] is None
