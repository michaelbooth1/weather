from dataclasses import replace
from decimal import Decimal as D

import pytest
from maker_core.contracts import InfoEvent
from maker_core.evidence.journal import plain
from maker_core.quoting.policy import Book
from maker_core.replay.baselines import matched_clock
from maker_core.replay.engine import replay, ReplayConfig
from maker_core.replay.parity import compare_journal
from maker_core.replay.score import score
from .fixtures.replay_scenario import Scenario
from .test_re1_parity import FIXTURES


def test_no_quote_scores_zero_only_on_covered_minutes(tmp_path):
    s = Scenario(markets=("a",), minutes=2)
    s.book("a", 0)
    result = replay([s.bundle(tmp_path/"b")], ReplayConfig(policy="no_quote"))
    r, = score(result)
    assert not result.fills
    assert r["reward_k1"] == r["cash_hours"] == 0
    assert r["pulled_minute_fraction"] == 1
    assert r["excluded_seconds"] == 60
    assert r["modeled_net_k1"] is None


def test_clock_control_matches_fraction_without_event_labels(tmp_path):
    s = Scenario(markets=("a",), minutes=30)
    for minute in range(30):
        s.book("a", minute*60)
    s.add("a", "info_event", 300, dict(events=[InfoEvent("new_high", None, s.at(300), s.at(300),
           (s.cid("a"),), 1, None, "pull", active_until_utc=s.at(900))]))
    s.view("a", 960)
    b = [s.bundle(tmp_path/"b")]
    config = ReplayConfig(hazard_per_minute=0)
    informed = replay(b, config)
    clock, match = matched_clock(b, config, informed)
    assert match["status"] == "MATCHED"
    assert abs(match["actual"]-match["target"]) <= match["tolerance"]
    assert not any("INFO_PULL" in d.decision.reasons for d in clock.decisions)
    assert any("CLOCK_ONLY_PULL" in d.decision.reasons for d in clock.decisions)


@pytest.mark.parametrize("record", FIXTURES, ids=lambda r: f"attempt-{r['attempt']}")
def test_recorded_prices_through_event_engine(tmp_path, record):
    s = Scenario(markets=("a",), minutes=1)
    raw, size = record["quote_inputs"], D(record["size"])
    s.book("a", 0)
    def levels(name):
        return tuple((D(str(v["price"])), D(str(v["size"]))) for v in raw[name])
    s.add("a", "book", 0, Book(s.start, *(levels(k) for k in ("yes_bids", "yes_asks", "no_bids", "no_asks"))))
    desc = replace(s.descriptors["a"], tick=D(str(raw["tick"])))
    s.add("a", "descriptor", 0, dict(market=plain(desc), horizon_days=2))
    s.terms("a", 0, D(str(raw["reward_min_size"])), D(str(raw["reward_rate_per_day"])),
            D(str(raw["reward_max_spread_cents"])))
    result = replay([s.bundle(tmp_path/"b")], ReplayConfig(policy="blind_re1", initial_cash=D(200),
                    wallet_cap=D(200), event_cap=D(150), order_cap=size*D(".8"), band_cap=size))
    quote = next(e.decision for e in result.decisions if e.decision.action == "QUOTE")
    assert [leg.price for leg in quote.legs] == list(map(D, record["expected_prices"]))
    assert all(leg.size == size for leg in quote.legs)
    if record["first_minute_prices"] is not None:
        assert [leg.price for leg in quote.legs] == list(map(D, record["first_minute_prices"]))


def test_trace_comparator_rejects_missing_terminal_event(tmp_path):
    s = Scenario(markets=("a",), minutes=1)
    s.book("a", 0)
    r = replay([s.bundle(tmp_path/"b")], ReplayConfig(policy="blind_re1"))
    expected = [dict(at=e.at, condition_id=e.condition_id, decision=plain(e.decision)) for e in r.decisions]
    assert compare_journal(r, expected)["status"] == "PASS"
    assert compare_journal(r, expected[:-1])["status"] == "FAIL"
