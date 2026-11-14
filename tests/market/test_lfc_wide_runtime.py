"""Guards: T114 normal entry refusal, capped hedge exemption and scoring hooks."""
from decimal import Decimal
from types import SimpleNamespace
import pytest

from tests.market.test_reward_quote import inputs
from weather.market.lfc_wide_policy import apply_arm
from weather.market.lfc_wide_runtime import authorize, initialize, observe, posted
from weather.market.mm_stage2_hold import HoldEnd


def band(*, completing=False, prices=('.31', '.62'), mode='wide'):
    rows = []
    journal = SimpleNamespace(record=lambda event, **fields: rows.append(dict(event=event, **fields)))
    result = SimpleNamespace(campaign_policy=SimpleNamespace(raw={'quote_offset_mode': mode}),
        scope={'quote_offset_mode': mode, 'offset_assignment_source': 'policy'},
        pair_state=SimpleNamespace(completing=completing),
        prices=list(map(Decimal, prices)), size=Decimal(20), SIZES=(20,),
        REQUOTE_WINDOW=(Decimal('2.5'), Decimal('4.5')), TRADE_LEGS=(0, 1),
        OFFSET=Decimal('.030'), MIN_REWARD_RATE=Decimal(0), journal=journal,
        submit_snapshot={'quote_inputs': inputs()})
    return result, rows


def test_actual_rounded_order_score_is_bound_to_acknowledged_identity():
    current, rows = band()
    authorize(current, 0, Decimal('.31'), Decimal(20))
    posted(current, 'synthetic-order')
    assert [r['event'] for r in rows] == ['quote_scoring_proposal', 'quote_scoring_order']
    assert rows[1]['order_id'] == 'synthetic-order'
    assert Decimal(rows[1]['scoring_distance_cents']) == Decimal('3.5')
    assert rows[1]['native_leg_reward_score'] == pytest.approx(20/20.25)


def test_boundary_normal_entry_waits_but_completion_keeps_zero_score_cap():
    current, rows = band(prices=('.30', '.61'))
    with pytest.raises(HoldEnd, match='wide_price_wait'):
        authorize(current, 0, Decimal('.30'), Decimal(20))
    assert rows == []
    current.pair_state.completing = True
    authorize(current, 0, Decimal('.30'), Decimal(20))
    assert rows[0]['native_leg_reward_score'] == 0
    assert rows[0]['completion'] is True


def test_normal_requote_changes_only_affected_leg_and_retains_inclusive_band():
    current, _ = band(prices=('.30', '.61'))
    snapshot = current.submit_snapshot
    assert observe(current, snapshot, {'adjusted_mid': '.345'})['requote_legs'] == []
    assert observe(current, snapshot, {'adjusted_mid': '.35'})['requote_legs'] == [0]
    current.pair_state.completing = True
    observation = {'adjusted_mid': '.35', 'requote_legs': [1]}
    assert observe(current, snapshot, observation) == observation


def test_unscored_new_normal_quote_waits_without_tightening():
    current, _ = band()
    current.submit_snapshot['quote_inputs']['reward_max_spread_cents'] = '3'
    observation = observe(current, current.submit_snapshot, {'adjusted_mid': '.38'})
    assert observation['requote_legs'] == []
    assert current.prices == [Decimal('.31'), Decimal('.62')]


def test_standard_runtime_is_inert_and_original_arms_survive_override():
    current, rows = band(mode='standard')
    authorize(current, 0, Decimal('.31'), Decimal(20)); posted(current, 'standard')
    assert rows == []
    original = {'quote_offset_pusd': '0.025', 'quote_arm': 'learning-0.025', 'leg_arm': 'cheap'}
    assert apply_arm({}, '2026-11-20', 'miami', original) is original
    wide = apply_arm({'quote_offset_mode': 'wide'}, '2026-11-20', 'miami', original)
    assert wide['quote_offset_pusd'] == '0.030' and wide['leg_arm'] == 'cheap'
    assert wide['quote_arm'] == 'learning-0.025' and wide['standard_quote_offset_pusd'] == '0.025'


def test_initialize_uses_wide_band_only_for_the_assigned_city():
    current, _ = band()
    chosen = dict(quote_offset_mode='wide', wide_offset_cents='3.0',
        offset_assignment_source='city_quote_offset_assignments', standard_quote_offset_pusd='0.015')
    initialize(current, chosen)
    assert current.scope['requote_distance_cents'] == ['2.5', '4.5']
    assert current.scope['standard_quote_offset_pusd'] == '0.015'
    current.REQUOTE_WINDOW = (Decimal(1), Decimal(3))
    chosen['quote_offset_mode'] = 'standard'
    initialize(current, chosen)
    assert current.REQUOTE_WINDOW == (1, 3)
