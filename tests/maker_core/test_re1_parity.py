"""Recorded quote-price parity, not a claim of full runtime/venue replay."""
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path
import pytest

from maker_core.contracts import Unavailable
from maker_core.quoting.policy import Book, RewardTerms, blind_re1, decide

FIXTURES = json.loads((Path(__file__).parent / "fixtures/re1_price_parity.json").read_text())


@pytest.mark.parametrize("record", FIXTURES, ids=lambda r: f"attempt-{r['attempt']}")
def test_recorded_quote_prices_through_blind_profile(inputs, record):
    raw = record["quote_inputs"]
    def levels(name):
        return tuple((D(str(v["price"])), D(str(v["size"]))) for v in raw[name])
    size = D(record["size"])
    i = replace(inputs, profile=blind_re1,
                book=Book(inputs.now, *(levels(k) for k in ("yes_bids", "yes_asks", "no_bids", "no_asks"))),
                terms=RewardTerms(inputs.now, D(str(raw["reward_min_size"])),
                                  D(str(raw["reward_max_spread_cents"])), D(str(raw["reward_rate_per_day"]))),
                market=replace(inputs.market, tick=D(str(raw["tick"]))),
                portfolio=replace(inputs.portfolio, order_cap=size * D('.8'), band_cap=size),
                fair_value=Unavailable("historical blind profile", inputs.now))
    d = decide(i)
    assert d.action == "QUOTE", d.reasons
    assert tuple(leg.price for leg in d.legs) == tuple(map(D, record["expected_prices"]))
    assert all(leg.size == size for leg in d.legs)
    if record["first_minute_prices"] is not None:
        assert tuple(leg.price for leg in d.legs) == tuple(map(D, record["first_minute_prices"]))


def test_parity_evidence_is_bounded_and_available():
    assert len(FIXTURES) == 12
    assert sum(r["first_minute_prices"] is not None for r in FIXTURES) == 8
    for r in FIXTURES:
        assert len(r["source_journal_sha256"]) == len(r["source_selection_sha256"]) == 64


@pytest.mark.parametrize("attempt", range(1, 13))
def test_full_minute_journal_replay_skeleton(attempt):
    # 110c forbids account/production reads. A later authorized export must
    # supply sanitized DecisionInputs per minute plus the recorded expectation:
    # action (HOLD/requote), each replacement leg/price, and terminal end reason.
    # Replay each frame with decide(), carry its existing legs to the next frame,
    # compare every minute, then assert the final recorded end reason. Do not
    # silently substitute first-minute fixtures for these absent journals.
    pytest.skip(f"attempt {attempt}: full-minute account journal export unavailable in fixture-only 110c")
