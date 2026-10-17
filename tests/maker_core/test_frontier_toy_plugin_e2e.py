"""Item 330 build 3 (d): a non-weather toy plugin replayed end to end through the unchanged core.

The dice plugin is contract-only. Its descriptor, fair value and settlement are sealed into a neutral
bundle and then replayed twice: once through the frozen v2 engine under every policy, and once through
the frontier runner over the whole grid and the three baselines. Nothing in the core knows about dice.

Guards: core domain neutrality: a contract-only non-weather plugin replays through the frozen v2 engine and the
  frontier runner with no core change.
"""
import ast
from datetime import timedelta
from decimal import Decimal as D
import importlib.util
from pathlib import Path

import pytest

from maker_core.contracts import SettlementFact
from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.frontier.grid import BASELINES, GRID
from maker_core.frontier.runner import run
from maker_core.frontier.share_decay import DecayModel
from maker_core.quoting.policy import Book, RewardTerms
from maker_core.replay.bundle import FORMAT, load_bundle, sha256
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import bundle_source, drive, run_plan
from .fixtures.replay_bundle import seal
from .fixtures.toy_dice_domain import T0, ToyDiceDomain

PLUGIN = Path(__file__).parent / "fixtures" / "toy_dice_domain.py"
ZONES = {"dice-sum": "UTC"}
DECAY = DecayModel(5.0, 5.0, 20.0, ())
MINUTES = 30


def _ratchet():
    path = Path(__file__).parents[1] / "operations" / "test_import_architecture.py"
    spec = importlib.util.spec_from_file_location("_frontier_import_ratchet", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.maker_boundary_violations


def toy_bundle(root):
    plugin = ToyDiceDomain()
    market = plugin.describe("dice-sum-8", T0)
    cid, records = market.condition_id, []

    def add(kind, seconds, payload):
        records.append(dict(sequence=len(records), captured_at=(T0 + timedelta(seconds=seconds)).isoformat(),
                            condition_id=cid, kind=kind, payload=plain(payload),
                            payload_sha256=sha256(canonical_bytes(payload)),
                            source_hashes={"toy": sha256(b"toy-dice-synthetic")}))

    add("descriptor", 0, dict(market=plain(market), horizon_days=1))
    add("info_event", 0, {"events": []})
    add("outcome_view", 0, dict(available=True, value=plain(plugin.evaluate(market, T0))))
    add("terms", 0, RewardTerms(T0, D(20), D(5), D(100)))
    for minute in range(MINUTES):
        at = T0 + timedelta(minutes=minute)
        add("coverage", minute * 60, dict(trade_stream_ok=True, valid_until_utc=(at + timedelta(seconds=60)).isoformat()))
        mid = D(".42")
        add("book", minute * 60, Book(at, ((mid - D(".01"), D(75)),), ((mid + D(".01"), D(75)),),
                                      ((1 - mid - D(".01"), D(75)),), ((1 - mid + D(".01"), D(75)),)))
    add("trade", 125, dict(trade_id="t1", outcome="YES", price=".39", size="10",
                           traded_at_utc=(T0 + timedelta(seconds=125)).isoformat(), aggressor_side="SELL"))
    settle_at = market.settle_at_utc
    fact = plugin.resolve(market, settle_at)
    assert isinstance(fact, SettlementFact)
    add("settlement", int((settle_at - T0).total_seconds()), fact)
    root.mkdir()
    manifest = dict(format=FORMAT, day=T0.date().isoformat(), sealed_at=(T0 + timedelta(days=1)).isoformat(),
                    provenance="synthetic", streams=[],
                    conditions=[dict(condition_id=cid, market_id="dice-sum", domain_id="toy_dice",
                                     active_from=T0.isoformat(),
                                     active_until=(settle_at + timedelta(minutes=10)).isoformat())])
    seal(root, manifest, records)
    return bundle_source(load_bundle(root)), fact


def test_toy_plugin_imports_only_contracts():
    source = PLUGIN.read_text(encoding="utf-8")
    assert _ratchet()(source, "fictional_plugin") == []
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            roots.add(node.module)
        elif isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
    assert roots == {"datetime", "decimal", "random", "maker_core.contracts"}


@pytest.mark.parametrize("policy", ("informed-v0", "blind_re1", "no_quote", "clock_only"))
def test_toy_plugin_replays_through_the_frozen_v2_engine(tmp_path, policy):
    source, _ = toy_bundle(tmp_path / "bundle")
    engine = EngineV2(V2Config(policy=policy, hazard_per_minute=.001), run_plan([source]))
    drive([source], [engine], time_zones=ZONES)
    summary = engine.summary()
    assert summary["decisions"] > 0


def test_toy_plugin_runs_through_the_frontier_runner(tmp_path):
    source, fact = toy_bundle(tmp_path / "bundle")
    assert fact.p_yes == 0.0  # seed 8 rolls a 5
    result = run([source], decay=DECAY, hazard_per_minute=.001)
    strategies = result["strategies"]
    assert set(strategies) == set(BASELINES) | {p.label for p in GRID}
    assert result["label"] == "DESCRIPTIVE" and result["days"] == ["2030-03-04"]
    assert strategies["no-quote"]["quoted_seconds"] == 0
    for label in ("blind_re1", "informed-v0", "w1.0-s20-depth_only-hold_to_settlement"):
        assert strategies[label]["quotes"] > 0, label
        assert strategies[label]["reward"]["none"] >= strategies[label]["reward"]["central"] \
            >= strategies[label]["reward"]["full"] > 0
    held = strategies["w1.0-s20-depth_only-hold_to_settlement"]
    assert held["fills"] == 1 and held["filled_shares"] == 10
    assert held["settlement_pnl"] == D("-4.10")  # 10 YES bought at 0.41, settled NO
    assert held["unsettled_shares"] == 0
