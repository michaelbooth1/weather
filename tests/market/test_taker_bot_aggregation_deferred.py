import pytest

from weather.market.taker_bot_aggregation import DeferredTakerPayload, TakerRunAggregation


def test_deferred_payload_exposes_bounded_scored_row_iterator_until_closed():
    aggregation = TakerRunAggregation()
    aggregation.scored_rows.append({"strategy_id": "probe", "net_pnl_usdc": 1.25})
    aggregation.commit()
    payload = DeferredTakerPayload({"summary": {}}, aggregation)

    assert list(payload.iter_scored_rows()) == [
        {"net_pnl_usdc": 1.25, "strategy_id": "probe"}
    ]

    payload.close()
    with pytest.raises(RuntimeError, match="closed"):
        list(payload.iter_scored_rows())

