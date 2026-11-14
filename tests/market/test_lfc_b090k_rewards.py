"""Guards: B090-K dual reward views, condition/day de-duplication and zero estimate capital credit."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_repost import fixture
from tests.market.test_lfc_rewards_record import accrual_fixture, activity, page, START, CONDITION, MAKER
from weather.market.lfc_capital import ASSET, CapitalBook
from weather.market.lfc_f2_reward_estimate import (account_context, remember_account_context,
    retained_summary, summary, venue_observations)
from weather.market.lfc_recording_io import strict_json, write_new
from weather.market.lfc_rewards_record import record_rewards
from weather.market.mm_stage2_hold import digest
from weather.market.re1_payout_evidence import ASSET_MARKERS


DAY = START.date().isoformat()


def scope_ledger(*, two_sessions=False, unacked=False):
    sessions = {'first': {'start': {'recorded_at_utc': START.isoformat(), 'condition_id': CONDITION},
                           'legs': ['quote'], 'end': {}}}
    legs = {'quote': {'condition_id': CONDITION, 'order_id': None if unacked else 'campaign-order'}}
    if two_sessions:
        sessions['second'] = {'start': dict(sessions['first']['start']), 'legs': ['repost'], 'end': {}}
        legs['repost'] = {'condition_id': CONDITION, 'order_id': 'campaign-repost'}
    return SimpleNamespace(sessions=sessions, legs=legs, rows=[{'maker_address': MAKER}],
        our_order_ids=lambda: {leg['order_id'] for leg in legs.values() if leg['order_id']})


def response(day=DAY, conditions=(CONDITION,), amount='1.25'):
    assets = list(ASSET_MARKERS)
    rows = [dict(maker_address=MAKER, condition_id=condition, asset_address=asset, date=day,
                 earnings=amount if asset == ASSET else '2.5', asset_rate='7')
            for condition in conditions for asset in assets]
    totals = [dict(maker_address=MAKER, asset_address=asset, date=day,
                   earnings=str(sum(float(row['earnings']) for row in rows if row['asset_address'] == asset)), asset_rate='7')
              for asset in assets]
    return {'day': day, 'rows': rows, 'total_earnings': totals}


def observations(*, amount='1.25', lag=0):
    return venue_observations(response(amount=amount), condition=CONDITION, maker=MAKER,
        observed_at_utc=(START + timedelta(days=lag, hours=12)).isoformat(),
        receipt_sha256=str(lag) * 64, record_pass=lag)


def test_condition_day_counted_once_across_legs_attempts_and_receipt_passes():
    ledger = scope_ledger(two_sessions=True)
    rows = observations() + observations(lag=1) + observations(amount='1.5', lag=2)
    rails = summary(ledger, ledger.sessions, observations=rows + rows)
    estimate = rails['campaign_estimate']
    assert estimate['estimated_native'] is None and estimate['estimated_pusd_native'] == 1_500_000
    assert len(estimate['entries']) == 2 and len(estimate['observations_by_pass']) == 6
    assert estimate['entries'][0]['campaign_session_ids'] == ['first', 'second']
    assert estimate['capital_credit_native'] == rails['strict_attributable']['recognized_native'] == 0
    assert estimate['booked_as_income'] is False and estimate['actually_paid_native'] is None
    assert all(row['cash_asset']['asset_address'] != ASSET or row['amount_native'] == 1_500_000 for row in estimate['entries'])


def test_unquoted_intent_never_claims_condition_day_earnings():
    ledger = scope_ledger(unacked=True)
    estimate = summary(ledger, ledger.sessions, observations=observations())['campaign_estimate']
    assert estimate['entries'] == [] and estimate['estimated_native'] == 0


def test_missing_is_unknown_and_recorded_zero_is_zero():
    ledger = scope_ledger()
    missing = summary(ledger, ledger.sessions)['campaign_estimate']
    zero = summary(ledger, ledger.sessions, observations=observations(amount='0'))['campaign_estimate']
    assert missing['estimated_native'] is None and missing['missing_condition_days']
    assert zero['estimated_pusd_native'] == 0 and zero['complete_condition_day_coverage']
    assert not zero['entries'][0]['clean_scope_proven']


def test_native_estimate_never_multiplies_by_asset_rate_or_merges_assets():
    rows = observations()
    assert {row['cash_asset']['symbol']: row['amount_native'] for row in rows} == {'pUSD': 1_250_000, 'USDC.e': 2_500_000}
    rails = summary(scope_ledger(), ['first'], observations=rows)
    assert rails['campaign_estimate']['estimated_native'] is None
    assert rails['campaign_estimate']['estimated_pusd_native'] == 1_250_000
    assert len(rails['campaign_estimate']['asset_estimates']) == 2


def test_usdc_venue_estimate_keeps_its_units_and_does_not_fabricate_pusd():
    payload = response()
    payload['rows'] = [row for row in payload['rows'] if row['asset_address'] != ASSET]
    payload['total_earnings'] = [row for row in payload['total_earnings'] if row['asset_address'] != ASSET]
    rows = venue_observations(payload, condition=CONDITION, maker=MAKER,
        observed_at_utc=(START + timedelta(hours=12)).isoformat(), receipt_sha256='a' * 64)
    rails = summary(scope_ledger(), ['first'], observations=rows)
    estimate = rails['campaign_estimate']
    assert estimate['estimated_native'] == 2_500_000 and estimate['cash_asset'] != ASSET
    assert estimate['estimated_pusd_native'] is None and estimate['capital_credit_native'] == 0
    assert rails['strict_attributable']['recognized_native'] == 0


@pytest.mark.parametrize('role', ['maker', 'taker', 'order'])
def test_other_own_activity_is_flagged_for_exact_earned_day(role):
    ledger = scope_ledger()
    read = {'maker_address': MAKER, 'ended_at_utc': (START + timedelta(hours=15)).isoformat(),
            'trades': [], 'open_orders': []}
    if role == 'order':
        read['open_orders'] = [{'id': 'owner-order', 'market': CONDITION, 'created_at': int(START.timestamp())}]
    else:
        trade = {'id': 'owner-trade', 'condition_id': CONDITION, 'matched_at': START.isoformat(),
                 'trader_side': role.upper(), 'maker_orders': [], 'taker_order_id': 'owner-order'}
        if role == 'maker':
            trade['maker_orders'] = [{'order_id': 'owner-order', 'maker_address': MAKER.upper()}]
        read['trades'] = [trade]
    context = account_context(ledger, read)
    entry = summary(ledger, ['first'], observations=observations(), contexts=[context])['campaign_estimate']['entries'][0]
    assert entry['other_own_activity_detected'] and entry['other_own_order_ids'] == ['owner-order']
    assert entry['other_own_trade_ids'] == ([] if role == 'order' else ['owner-trade'])
    assert entry['flag'] == 'other_own_activity' and not entry['clean_scope_proven']


@pytest.mark.parametrize('when', [START - timedelta(microseconds=1), START + timedelta(days=1)])
def test_other_day_and_counterparty_do_not_contaminate_campaign_day(when):
    ledger = scope_ledger()
    read = {'maker_address': MAKER, 'ended_at_utc': (START + timedelta(days=2)).isoformat(), 'open_orders': [],
        'trades': [{'id': 'other-day', 'condition_id': CONDITION, 'matched_at': when.isoformat(), 'trader_side': 'MAKER',
                    'maker_orders': [{'maker_address': MAKER, 'order_id': 'other-day-order'},
                                     {'maker_address': 'counterparty', 'order_id': 'foreign'}]}]}
    entry = summary(ledger, ['first'], observations=observations(), contexts=[account_context(ledger, read)])['campaign_estimate']['entries'][0]
    assert entry['other_own_activity_detected'] is False
    assert entry['flag'] == 'none_observed_history_incomplete' and not entry['order_history_complete']


def test_campaign_peer_order_is_not_owner_contamination_and_unknown_time_is_named():
    ledger = scope_ledger(two_sessions=True)
    read = {'maker_address': MAKER, 'ended_at_utc': START.isoformat(), 'open_orders': [], 'trades': [
        {'id': 'own', 'condition_id': CONDITION, 'trader_side': 'TAKER', 'taker_order_id': 'campaign-repost'},
        {'id': 'unknown-time', 'condition_id': CONDITION, 'trader_side': 'TAKER', 'taker_order_id': 'owner-order'}]}
    context = account_context(ledger, read)
    assert len(context['touches']) == 1
    entry = summary(ledger, ledger.sessions, observations=observations(), contexts=[context])['campaign_estimate']['entries'][0]
    assert entry['other_own_activity_detected'] is None and entry['other_own_touch_date_unknown']


def test_d1_d2_real_record_replay_keeps_payment_ids_separate_and_does_not_add_passes(tmp_path, monkeypatch):
    venue, journal, clock = accrual_fixture(monkeypatch)
    for lag in (1, 2):
        record_rewards(tmp_path, DAY, maker=MAKER, conditions=[CONDITION], venue=venue, journal=journal,
            clock=lambda lag=lag: START + timedelta(days=lag, hours=2), get=lambda *args: page([activity()]))
    ledger = scope_ledger()
    rails, hashes = retained_summary(tmp_path, ledger, ['first'])
    estimate = rails['campaign_estimate']
    assert estimate['estimated_native'] is None and estimate['estimated_pusd_native'] == 1_250_000
    assert [row['record_pass'] for row in estimate['d1_d2_receipts']] == [1, 2]
    assert len(estimate['observations_by_pass']) == 4 and len(estimate['payment_candidates']) == 1
    payment = estimate['payment_candidates'][0]
    assert payment['record_passes'] == [1, 2] and payment['candidate_earned_dates'] == [DAY]
    assert payment['earned_date'] is None and payment['earned_date_link_verified'] is False
    assert payment['transaction_hash'] == activity()['transaction_hash']
    assert len(hashes) == 2 and rails['strict_attributable']['recognized_native'] == 0


def test_one_asset_d1_receipt_proves_estimate_without_qualifying_strict_income(tmp_path, monkeypatch):
    from weather.market import lfc_rewards_record as recorder, re1_transport
    from weather.market.lfc_settlement_record import retained
    from weather.market.re1_attended import SecretGuard
    from weather.market.re1_payout_evidence import ReadJournal
    clock = lambda: START + timedelta(days=1, hours=2)
    journal = ReadJournal(SecretGuard(), clock)
    payload = response()
    payload['rows'] = [row for row in payload['rows'] if row['asset_address'] != ASSET]
    payload['total_earnings'] = [row for row in payload['total_earnings'] if row['asset_address'] != ASSET]
    class Transport:
        def request(self, method, host, path, params):
            reply = {'data': payload['rows'], 'next_cursor': 'LTE='} if path.endswith('/user') else payload['total_earnings']
            journal.record('sdk_response', path=path, status=200, **retained(json.dumps(reply).encode()))
            return reply
    monkeypatch.setattr(re1_transport, 'condition_configurations', lambda condition, journal: [])
    venue = SimpleNamespace(client=recorder.AccrualClient(Transport(), 2))
    record = record_rewards(tmp_path, DAY, maker=MAKER, conditions=[CONDITION], venue=venue,
        journal=journal, clock=clock, get=lambda *args: page())
    assert record['accruals'][0]['source']['complete'] is False
    rails, hashes = retained_summary(tmp_path, scope_ledger(), ['first'])
    assert rails['campaign_estimate']['estimated_native'] == 2_500_000
    assert rails['campaign_estimate']['estimated_pusd_native'] is None
    assert rails['strict_attributable']['recognized_native'] == 0 and hashes
    # An incomplete flag cannot authorize invented normalized earnings.
    path = tmp_path / 'rewards' / (DAY + '-d1.json')
    bad = strict_json(path.read_bytes()); bad['accruals'][0]['accruals'][0]['venue_amount'] = '99999'
    path.write_text(json.dumps(bad))
    refused, _ = retained_summary(tmp_path, scope_ledger(), ['first'])
    assert refused['campaign_estimate']['estimated_native'] is None


def test_context_recording_failure_cannot_change_account_read_or_money(tmp_path):
    ledger = scope_ledger()
    read = {'maker_address': MAKER, 'ended_at_utc': START.isoformat(), 'open_orders': [], 'trades': []}
    def failed(*args):
        raise OSError('fixture disk failure')
    runtime = SimpleNamespace(state=SimpleNamespace(ledger=ledger, root=tmp_path, save=failed))
    before = deepcopy(read)
    remember_account_context(runtime, read)
    assert read == before and runtime.reward_estimate_gaps == {'account_reward_context_unavailable'}


def test_validated_own_stream_trade_flags_owner_touch_before_rest_is_available():
    from weather.market.lfc_f2_reward_estimate import capture_stream_context
    ledger = scope_ledger()
    retained = []
    band = SimpleNamespace(ledger=ledger, condition=CONDITION, reward_context={}, reward_estimate_gaps=set(),
        journal=SimpleNamespace(record=lambda event, **fields: retained.append((event, fields))))
    capture_stream_context(band, [{'official_event_type': 'trade', 'condition_id': CONDITION,
        'order_id': 'owner-order', 'trade_id': 'owner-trade', 'exchange_match_time': START.isoformat()}])
    entry = summary(ledger, ['first'], observations=observations(),
        contexts=[{'touches': list(band.reward_context.values())}])['campaign_estimate']['entries'][0]
    assert entry['other_own_activity_detected'] and entry['other_own_trade_ids'] == ['owner-trade']
    assert retained[0][0] == 'campaign_reward_context' and not band.reward_estimate_gaps


def test_actual_daily_economics_and_terminal_projection_record_both_views(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    conditions = tuple(band.condition for band in controller.bands)
    for raw in account.raws:
        raw.accrual = lambda day: response(day, conditions, amount='.125')
    capital = CapitalBook(ledger).figures()
    result = controller.run()
    assert result['cleanup_ok'], result
    row = status.finish(success=True)['economics']['measured']['rewards']
    assert row['strict_attributable']['recognized_native'] == 0
    assert row['campaign_estimate']['estimated_pusd_native'] == 250_000
    assert row['actually_paid_native'] is None
    assert CapitalBook(ledger).figures() == capital
    for band in controller.bands:
        prediction = strict_json((band.directory / 'prediction.json').read_bytes())
        assert len(prediction['reward_estimates']) == 4 and prediction['reward_estimate_gaps'] == []
    rails, hashes = retained_summary(tmp_path, ledger, [band.session_id for band in controller.bands])
    assert rails['campaign_estimate']['estimated_pusd_native'] == 250_000 and len(hashes) == 2


def test_supplement_and_final_decision_inputs_keep_owner_flag_and_both_rails(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign import Mutexes
    from tests.market.test_lfc_f2_evidence import runtime_at_controller
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_campaign_proof import local_money_proof
    from weather.market.lfc_campaign_policy import parse_policy
    from weather.market.lfc_f2_economics import publish_supplements
    from weather.market.lfc_f2_final import snapshot
    from weather.market.lfc_f2_pinb import example_policy
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, _, _ = fixture(tmp_path, enrolled=True)
        account.fills_enabled = False
        conditions = tuple(band.condition for band in controller.bands)
        for raw in account.raws:
            raw.accrual = lambda day: response(day, conditions, amount='.125')
        assert controller.run()['cleanup_ok']
        outcome = status.finish(success=True)
        runtime = runtime_at_controller(controller, account, status, ledger, clock, monkeypatch)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id=controller.attempt_id, outcome=outcome)
        runtime.save_result(account.claim, {'session_id': controller.session_id, 'outcome': outcome,
            'private_evidence_directory': controller.directory.relative_to(tmp_path).as_posix(),
            'unknown_submit': False, 'evidence_complete': True, 'inventory_proven': True, 'local_money_proof': local})
        remember_account_context(runtime, {'maker_address': MAKER, 'ended_at_utc': clock.now().isoformat(),
            'open_orders': [{'id': 'owner-order', 'market': conditions[0]}], 'trades': []})
        capital = CapitalBook(ledger).figures()
        original = (controller.directory / 'prediction.json').read_bytes()
        publish_supplements(runtime)
        supplements = list(runtime.control_root.parent.glob(controller.session_id + '.e-*.json'))
        assert len(supplements) == 1
        row = strict_json(supplements[0].read_bytes())
        rails = row['decision_page_inputs']['rewards']
        assert rails == {key: row['measured']['rewards'][key] for key in ('strict_attributable', 'campaign_estimate')}
        assert rails['campaign_estimate']['estimated_pusd_native'] == 250_000
        assert any(entry['other_own_activity_detected'] for entry in rails['campaign_estimate']['entries'])
        assert rails['strict_attributable']['recognized_native'] == 0
        publish_supplements(runtime)
        assert len(list(runtime.control_root.parent.glob(controller.session_id + '.e-*.json'))) == 1
        final = snapshot(ledger, parse_policy(example_policy()), root=tmp_path,
                         now=datetime(2026, 12, 28, 23, tzinfo=timezone.utc), state=runtime.state)
        assert final['decision_page_inputs']['rewards']['learning_and_legacy'] == rails
        assert final['assessment']['state'] == 'INCONCLUSIVE'
        assert CapitalBook(ledger).figures() == capital and (controller.directory / 'prediction.json').read_bytes() == original
