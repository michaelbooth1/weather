"""Synthetic eligibility through pre-go discovery, placement and requote.

Guards: B052 removes hidden 40/75/0.15 defaults only for the F2 policy.
"""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from tests.market import test_lfc_f2_controller as fixtures
from tests.market.test_lfc_f2_selection import universe, NOW
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_f2_policy import example_policy, VARIABLE
from weather.market.lfc_f2_selection import discover, validate_table


def permissive_books():
    rows = universe()
    for row in rows:
        values = row['snapshot']['quote_inputs']
        values.update(reward_rate_per_day='25', reward_max_spread_cents='3', reward_min_size='20',
            yes_bids=[{'price': '.34', 'size': '30'}], yes_asks=[{'price': '.36', 'size': '300'}],
            no_bids=[{'price': '.64', 'size': '300'}], no_asks=[{'price': '.66', 'size': '30'}])
    return rows


@pytest.mark.parametrize('key,good,bad', [('share_many_range', ['0', '1'], ['-.01', '1']),
    ('min_reward_rate', '0', '-.01'), ('min_book_depth', '20', '19.99')])
def test_campaign_eligibility_fields_accept_and_refuse_explicitly(key, good, bad):
    row = example_policy()
    assert key in VARIABLE
    row[key] = good
    assert parse_policy(row).raw[key] == good
    row[key] = bad
    with pytest.raises(ValueError): parse_policy(row)


def test_low_share_rate25_depth30_survives_real_prego_selection_submit_and_requote(tmp_path, monkeypatch):
    from weather.market import lfc_pilot, re1_transport, lfc_campaign_runtime
    from weather.market.re1_attended import SecretGuard
    rows = permissive_books()
    monkeypatch.setattr(fixtures, 'universe', lambda: deepcopy(rows))
    controller, account, status, ledger, clock = fixtures.setup(tmp_path)
    assert all(.025 < row['quote']['share_many'] < .035 for row in controller.table['rows'])
    class Public:
        records = []
        def get(self, url):
            city = 'denver' if 'denver' in url else 'toronto'
            row = next(r for r in rows if r['market_id'] == city)
            return {'slug': url.rsplit('/', 1)[-1], 'markets': [{'conditionId': row['condition_id'],
                'clobTokenIds': row['token_ids'], 'outcomes': ['Yes', 'No']}]}
        def reward(self, cid):
            return {'condition_id': cid, 'rewards_min_size': '20', 'rewards_max_spread': '3', 'total_daily_rate': '25'}
        def snapshot(self, cid, tokens, **kw):
            return deepcopy(next(r['snapshot'] for r in rows if r['condition_id'] == cid))
    public = Public()
    from weather.market.lfc_capital import CapitalBook
    initial = discover(public, controller.policy, now=clock.now(), cash='300',
                       capital=CapitalBook(ledger).figures(), held_conditions=[])
    assert len(validate_table(initial, now=clock.now(), policy=controller.policy)) == 2
    monkeypatch.setattr(lfc_pilot, 'LfcPublicBooks', lambda: public)
    monkeypatch.setattr(re1_transport, 'load_owner_credentials', lambda _: ({'FUNDER_ADDRESS': ledger.rows[0]['maker_address']}, SecretGuard()))
    monkeypatch.setattr(re1_transport, 'build_client', lambda *a, **kw: object())
    monkeypatch.setattr(lfc_campaign_runtime, 'selection_account_screen', lambda *a: None)
    readonly = SimpleNamespace(start=lambda: None, close=lambda: None, events=lambda: [], open_orders=lambda: [],
        positions=lambda: [], balances=lambda: {'available_collateral': '300'}, geography=lambda: {'blocked': False},
        heartbeat=lambda: {'status': 'ok'})
    monkeypatch.setattr(re1_transport, 'OwnerVenue', lambda *a, **kw: readonly)
    runtime = SimpleNamespace(state=SimpleNamespace(root=tmp_path / 'state', ledger=ledger,
        maker=ledger.rows[0]['maker_address']), clock=clock, task_enabled=lambda: True)
    prego = Runtime.readiness(runtime, controller.entry, controller.policy,
                              {'balances': {'available_collateral': '300'}, 'positions': []})
    saved = json.loads((runtime.state.root / prego['readiness_directory'] / 'selection.json').read_text())
    assert len(saved['selected_condition_ids']) == 2
    original = account.advance
    def moved_book():
        if clock.seconds >= 40:
            for raw in account.raws:
                raw.memory.public_input['quote_inputs'].update(
                    yes_bids=[{'price': '.36', 'size': '30'}], yes_asks=[{'price': '.38', 'size': '300'}],
                    no_bids=[{'price': '.62', 'size': '300'}], no_asks=[{'price': '.64', 'size': '30'}])
        original()
    monkeypatch.setattr(account, 'advance', moved_book)
    result = controller.run()
    assert result['cleanup_ok'] and result['post_count'] > 4, result
    assert all(band.requotes > 0 for band in controller.bands)
    assert all(result['reason'] == 'fixed_end' for result in controller.results.values())
    assert not account.open_orders()


@pytest.mark.parametrize('rate', ['0', '-1'])
def test_zero_or_negative_reward_still_refuses_under_filter_off_defaults(rate):
    from tests.market.test_lfc_f2_selection import table
    rows = permissive_books()
    for row in rows: row['snapshot']['quote_inputs']['reward_rate_per_day'] = rate
    assert not table(rows)['selected_condition_ids']
