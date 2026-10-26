"""Live-fill calibration clarification E (small maker pilot) with in-memory fakes only (no network, no orders).

Guards: the six clarification-E values (20 shares per leg, the 15.80 per-order and 19.60 per-band caps, the
Toronto+Denver band universe, R6 dropped for the campaign only, last start 2026-11-20) and that the other signed LFC
limits stay as signed (L budget 100, 8 sessions of 360 minutes, the leg price range, earliest start, 23:50Z hard stop,
RE-1 submit/requote limits, post-only GTD submits); the review follow-ups: a counted session refuses a non-pilot
band itself, and the campaign selection refuses a leg above the 15.80 order cap before session_start (RE-1 unchanged).
"""
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from tests.market.test_lfc_pilot import BASE, Clock, counted_table, snapshot
from tests.market.test_lfc_pilot import setup as pilot_session
from tests.market.stage2_fakes import CONDITION, TOKENS
from weather.market import lfc_constants as LFC
from weather.market import mm_stage2_selection
from weather.market import re1_attended
from weather.market.lfc_pilot import PilotProfile, start_refusals
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_selection import PublicBooks, select_table


def test_clarification_e_values_are_exactly_the_ruling():
    assert LFC.PILOT_SIZE == Decimal('20')
    assert (LFC.PER_ORDER_CAP_PUSD, LFC.PER_BAND_CAP_PUSD) == (Decimal('15.80'), Decimal('19.60'))
    assert LFC.PER_ORDER_CAP_PUSD == Decimal('.79') * LFC.PILOT_SIZE
    assert LFC.PER_BAND_CAP_PUSD == Decimal('.98') * LFC.PILOT_SIZE
    assert PilotProfile().venue_ceiling(20) == (Decimal('15.80'), Decimal('19.60'))
    assert LFC.PILOT_MARKET_IDS == ('denver', 'toronto')
    assert {REGISTRY[m].id for m in LFC.PILOT_MARKET_IDS} == {'denver', 'toronto'}
    assert LFC.PREDICTED_REWARD_FLOOR is None
    assert LFC.LAST_START_LOCAL_DATE == date(2026, 11, 20)


def test_every_other_signed_limit_is_unchanged():
    assert LFC.BUDGET_PUSD == Decimal('100') and LFC.MAX_SESSIONS == 8 and LFC.SESSION_SECONDS == 21600
    assert (LFC.PER_LEG_PRICE_FLOOR, LFC.PER_LEG_PRICE_CEILING) == (Decimal('.17'), Decimal('.80'))
    assert LFC.MIN_FEASIBLE_LEG_SUM == Decimal('.96') and LFC.MIN_FEASIBLE_RESERVE == Decimal('19.2')
    assert LFC.EARLIEST_START_UTC == datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert LFC.HARD_STOP_UTC == time(23, 50) and LFC.OWNER_TIMEZONE == 'America/Toronto'
    assert LFC.SHARE_MANY_RANGE == (Decimal('.15'), Decimal('.70')) and LFC.FOREIGN_CHECK_SECONDS == 30
    assert LFC.RE1_OFFSET == Decimal('.015') and LFC.RE1_REQUOTE_WINDOW == (Decimal('1'), Decimal('3'))
    assert LFC.TREATMENT == 'LFC-40' and LFC.PROTOCOL == 'LFC-live-fill-calibration-v1'
    assert re1_attended.MAX_SUBMITS == 10 and re1_attended.MAX_REQUOTES == 4
    assert LFC.WEATHER_FEE_TYPE == 'weather_fees'


def test_last_start_is_owner_local_2026_11_20():
    assert start_refusals(datetime(2026, 11, 20, 17, tzinfo=timezone.utc)) == []
    assert start_refusals(datetime(2026, 11, 21, 17, tzinfo=timezone.utc)) == ['after_last_start_date']


def test_counted_session_posts_post_only_gtd_at_twenty_within_the_caps(tmp_path):
    session, venue, _, _ = pilot_session(tmp_path)
    assert session.caps(20, '500') == (Decimal('15.80'), Decimal('19.60'))
    assert session.BAND_CEILING == Decimal('19.60')
    result = session.run(rehearsal_seconds=60)
    assert result['submits'] == 2 and venue.calls
    for request in venue.calls:
        assert Decimal(request['size']) == 20 and request['post_only'] is True
        assert Decimal(request['price']) * 20 <= LFC.PER_ORDER_CAP_PUSD
    assert sum(Decimal(r['price']) for r in venue.calls) * 20 <= LFC.PER_BAND_CAP_PUSD


def _band(clock, market_id):
    return dict(market_id=market_id, market_timezone=REGISTRY[market_id].timezone,
                target_date=(clock.now() + timedelta(days=1)).date().isoformat(),
                condition_id=CONDITION, token_ids=list(TOKENS), snapshot=snapshot(clock),
                event_slug=event_slug_for_date((clock.now() + timedelta(days=1)).date(), market_id),
                event_condition_ids=[CONDITION])


def _table(clock, market_id, **kwargs):
    return select_table([_band(clock, market_id)], now=clock.now(), available_collateral='500',
                        ledger={'L': '0', 'L_resting': '0'}, held_conditions=[], **kwargs)


def test_campaign_selects_only_toronto_and_denver_bands():
    clock = Clock()
    for market_id in ('toronto', 'denver'):
        table = _table(clock, market_id, treatment=LFC.TREATMENT)
        assert table['selected_condition_id'] == CONDITION, table['rows'][0]['refusal']
        assert table['pilot_size'] == '20' and table['rows'][0]['quote']['size'] == '20'
    for market_id in sorted(set(REGISTRY) - set(LFC.PILOT_MARKET_IDS)):
        table = _table(clock, market_id, treatment=LFC.TREATMENT)
        assert table['selected_condition_id'] is None
        assert table['rows'][0]['refusal'] == 'lfc_market_outside_pilot'


def test_r6_reward_floor_is_dropped_for_the_campaign_only(monkeypatch):
    clock = Clock()
    real_pilot, real_sized = mm_stage2_selection.pilot_quote, mm_stage2_selection.sized_quote
    low = 1.0 / 360  # predicted_360_minutes = 1.0 < 2
    monkeypatch.setattr(mm_stage2_selection, 'pilot_quote',
                        lambda *a, **k: replace(real_pilot(*a, **k), predicted_per_minute_many=low))
    monkeypatch.setattr(mm_stage2_selection, 'sized_quote',
                        lambda *a, **k: replace(real_sized(*a, **k), predicted_per_minute_many=low))
    table = _table(clock, 'denver', treatment=LFC.TREATMENT)
    assert table['rows'][0]['predicted_360_minutes'] < 2
    assert table['selected_condition_id'] == CONDITION, table['rows'][0]['refusal']
    # RE-1 outside the campaign keeps its own floor.
    re1 = select_table([_band(clock, 'denver')], now=clock.now(), available_collateral='200')
    assert re1['selected_condition_id'] is None and re1['rows'][0]['refusal'] == 'predicted_below_two'


def test_campaign_reader_requests_only_the_pilot_market_events(monkeypatch):
    monkeypatch.setattr(mm_stage2_selection, 'assert_no_ambient_market_registry_override', lambda: None)

    class Books(PublicBooks):
        def __init__(self):
            super().__init__(clock=lambda: BASE)
            self.slugs = []

        def get(self, url, *, checkpoint=lambda: None):
            slug = url.rsplit('/', 1)[-1]
            self.slugs.append(slug)
            return {'slug': slug, 'markets': []}
    books = Books()
    table = books.selection(available_collateral='500', treatment=LFC.TREATMENT,
                            ledger={'L': '0', 'L_resting': '0'}, held_conditions=[])
    assert table['selected_condition_id'] is None and books.slugs
    assert set(books.slugs) <= {event_slug_for_date(BASE.date() + timedelta(days=d), m)
                                for m in LFC.PILOT_MARKET_IDS for d in range(-1, 4)}
    assert any('toronto' in s for s in books.slugs) and any('denver' in s for s in books.slugs)


def test_the_l_gate_still_refuses_above_100_at_twenty(tmp_path):
    table = counted_table(Clock(), figures={'L': '0', 'L_resting': '0'})
    session, venue, _, _ = pilot_session(tmp_path, filled='80.7', table=table)
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'l_budget_refused' and not venue.calls


def test_counted_session_refuses_a_non_pilot_band_itself(tmp_path):
    # Defence in depth: even a table whose selected band is Los Angeles is refused by the session, before the
    # frozen-rule rebuild and before any journal or order.
    table = counted_table(Clock())
    table['rows'][0]['market_id'] = 'los-angeles'
    table['rows'][0]['market_timezone'] = REGISTRY['los-angeles'].timezone
    with pytest.raises(ValueError, match='^lfc_market_outside_pilot$'):
        pilot_session(tmp_path, table=table)
    assert not (tmp_path / 'session' / 'journal.jsonl').exists()


def _leg_patch(monkeypatch, name, no_buy):
    real = getattr(mm_stage2_selection, name)
    monkeypatch.setattr(mm_stage2_selection, name,
                        lambda *a, **k: replace(real(*a, **k), no_buy=Decimal(no_buy)))


def test_campaign_selection_refuses_a_leg_above_the_order_cap_before_session_start(monkeypatch):
    _leg_patch(monkeypatch, 'pilot_quote', '.80')  # 20 x .80 = 16.00 > 15.80
    table = _table(Clock(), 'denver', treatment=LFC.TREATMENT)
    # No selected band means lfc_cli live raises no_qualifying_band before any session_start row.
    assert table['selected_condition_id'] is None
    assert table['rows'][0]['refusal'] == 'lfc_leg_above_order_cap'


def test_campaign_selection_accepts_a_leg_exactly_at_the_order_cap(monkeypatch):
    _leg_patch(monkeypatch, 'pilot_quote', '.79')  # 20 x .79 = 15.80 == cap
    table = _table(Clock(), 'denver', treatment=LFC.TREATMENT)
    assert table['rows'][0]['refusal'] is None and table['selected_condition_id'] == CONDITION
    assert Decimal(table['rows'][0]['quote']['no_buy']) * 20 == LFC.PER_ORDER_CAP_PUSD


def test_re1_selection_with_a_80_leg_is_unchanged(monkeypatch):
    clock = Clock()
    baseline = select_table([_band(clock, 'denver')], now=clock.now(), available_collateral='200')
    _leg_patch(monkeypatch, 'sized_quote', '.80')
    re1 = select_table([_band(clock, 'denver')], now=clock.now(), available_collateral='200')
    assert re1['rows'][0]['refusal'] == baseline['rows'][0]['refusal'] != 'lfc_leg_above_order_cap'
    assert re1['selected_condition_id'] == baseline['selected_condition_id']
    assert re1['rows'][0]['quote']['no_buy'] == '0.80'
