"""Synthetic campaign economic selection and complete rate-25 execution path.

Guards: owner B051 changes only the LFC share/rate/depth screens; RE-1 stays frozen.
"""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import hashlib
from types import SimpleNamespace

import pytest

from tests.market.stage2_fakes import CONDITION, TOKENS
from tests.market.test_lfc_pilot import Clock, events, snapshot
from tests.market.test_lfc_pilot import setup as pilot_session
from weather.market import lfc_cli, lfc_constants as LFC
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import digest
from weather.market.mm_stage2_selection import PublicBooks, select_table, validate_selection
from weather.market.re1_attended import HoldEnd, observe
from weather.market.reward_quote import QuoteRefused, price_reward_quote, price_sized_reward_quote


def band(*, rate='100', depth=None, share=None):
    clock = Clock()
    snap = snapshot(clock)
    values = snap['quote_inputs']
    values['reward_rate_per_day'] = rate
    if depth is not None:
        for key in ('yes_bids', 'yes_asks', 'no_bids', 'no_asks'):
            values[key] = [dict(values[key][0], size=str(depth))]
    if share is not None:
        quote = price_sized_reward_quote(**values, size=20)
        factor = Decimal(str(quote.own_q_min * (1 / share - 1) / quote.competing_q_many))
        for key in ('yes_bids', 'yes_asks', 'no_bids', 'no_asks'):
            values[key] = [dict(r, size=str(Decimal(r['size']) * factor)) for r in values[key]]
    target = (clock.now() + timedelta(days=1)).date()
    return dict(market_id='denver', market_timezone=REGISTRY['denver'].timezone,
                target_date=target.isoformat(), condition_id=CONDITION, token_ids=list(TOKENS),
                snapshot=snap, event_slug=event_slug_for_date(target, 'denver'), event_condition_ids=[CONDITION])


def selection(candidate, *, campaign=True):
    kwargs = dict(treatment=LFC.TREATMENT, ledger={'L': '0', 'L_resting': '0'}, held_conditions=[]) if campaign else {}
    return select_table([candidate], now=Clock().now(), available_collateral='100', **kwargs)


@pytest.mark.parametrize('case,refusal', [('share', 'predicted_below_two'),
                                        ('rate', 'reward_terms_outside_treatment'), ('depth', 'thin_book_depth')])
def test_economic_relaxations_are_campaign_only(case, refusal):
    candidate = band(rate='40', share=.03) if case == 'share' else band(rate='25') if case == 'rate' else band(depth=30)
    campaign = selection(candidate)
    assert campaign['selected_condition_id'] == CONDITION, campaign['rows'][0]['refusal']
    assert campaign['rows'][0]['quote']['size'] == '20'
    if case == 'share':
        assert campaign['rows'][0]['quote']['share_many'] == pytest.approx(.03)
    legacy = selection(candidate, campaign=False)
    assert legacy['selected_condition_id'] is None
    assert legacy['rows'][0]['refusal'] == refusal


@pytest.mark.parametrize('rate', ['0', '-1'])
def test_campaign_still_requires_positive_reward(rate):
    table = selection(band(rate=rate))
    assert table['selected_condition_id'] is None
    assert table['rows'][0]['refusal'] == 'reward_terms_outside_treatment'


def test_default_quote_and_observation_keep_re1_rate_floor():
    snap = band(rate='25')['snapshot']
    with pytest.raises(QuoteRefused, match='reward_terms_outside_treatment'):
        price_reward_quote(**snap['quote_inputs'])
    with pytest.raises(TypeError):
        price_reward_quote(**snap['quote_inputs'], min_reward_rate=LFC.MIN_REWARD_RATE)
    with pytest.raises(HoldEnd, match='reward_rate_or_terms'):
        observe(snap, ['.33', '.64'])
    quote = price_sized_reward_quote(**snap['quote_inputs'], size=20, min_reward_rate=LFC.MIN_REWARD_RATE)
    assert quote.size == 20
    assert observe(snap, [quote.yes_buy, quote.no_buy], min_reward_rate=LFC.MIN_REWARD_RATE)['per_minute_many'] > 0


@pytest.mark.parametrize('campaign', [True, False])
def test_public_discovery_uses_the_profile_rate_floor(monkeypatch, campaign):
    monkeypatch.setattr('weather.market.mm_stage2_selection.REGISTRY', {'denver': REGISTRY['denver']})

    class OfflineBooks(PublicBooks):
        def get(self, url, **kwargs):
            slug = url.rsplit('/', 1)[1]
            condition = '0x' + hashlib.sha256(slug.encode()).hexdigest()
            return {'slug': slug, 'markets': [{'conditionId': condition, 'clobTokenIds': list(TOKENS),
                                               'outcomes': ['Yes', 'No']}]}

        def reward(self, condition, **kwargs):
            return {'condition_id': condition, 'rewards_min_size': 20, 'rewards_max_spread': 3,
                    'total_daily_rate': 25}

        def snapshot(self, condition, tokens, **kwargs):
            result = band(rate='25')['snapshot']
            result.update(condition_id=condition, token_ids=list(tokens))
            return result

    kwargs = dict(treatment=LFC.TREATMENT, ledger={'L': '0', 'L_resting': '0'}, held_conditions=[]) if campaign else {}
    table = OfflineBooks(clock=Clock().now).selection(available_collateral='100', **kwargs)
    assert bool(table['selected_condition_id']) is campaign
    assert len(table['rows']) == (3 if campaign else 0)


def test_rate_25_selection_go_and_requote_have_no_default_40_refusal(tmp_path):
    table = selection(band(rate='25'))
    validate_selection(table, expected_sha256=digest(table), condition_id=CONDITION,
                       token_ids=TOKENS, now=Clock().now(), allow_sized=True)
    session, venue, clock, _ = pilot_session(tmp_path, table=table)
    original = venue.snapshot

    def moved_book(*args, **kwargs):
        result = original(*args, **kwargs)
        shift = Decimal('.03') if clock.seconds >= 60 else Decimal(0)
        raw = venue.memory.public_input['quote_inputs']
        for side in ('yes', 'no'):
            delta = shift if side == 'yes' else -shift
            for direction in ('bids', 'asks'):
                key = side + '_' + direction
                result['quote_inputs'][key] = [dict(r, price=str(Decimal(r['price']) + delta)) for r in raw[key]]
        return result

    venue.snapshot = moved_book
    result = session.run(rehearsal_seconds=180)
    assert result['reason'] == 'fixed_end' and result['cleanup_ok'], result
    assert result['requotes'] >= 1 and result['submits'] >= 4
    assert len(venue.calls) == result['submits']
    assert all(r['snapshot']['quote_inputs']['reward_rate_per_day'] == '25'
               for r in events(session, 'submit_market_snapshot'))
    assert not venue.open_orders()


def test_preflight_and_live_selector_keep_the_campaign_treatment(monkeypatch, tmp_path):
    table = selection(band(rate='25'))
    calls = []

    class Public:
        def selection(self, **kwargs):
            calls.append(kwargs)
            return deepcopy(table)

    monkeypatch.setattr(lfc_cli, 'LfcPublicBooks', Public)
    monkeypatch.setattr(lfc_cli, 'held_conditions', lambda *_a: [])
    ledger = SimpleNamespace(figures=lambda: {'L': '0', 'L_resting': '0'})
    _, select = lfc_cli._selector(SimpleNamespace(session0=False), root=tmp_path, ledger=ledger)
    selected = select({'available_collateral': '100'})
    assert selected['selected_condition_id'] == CONDITION
    assert calls[0]['treatment'] == LFC.TREATMENT
