from copy import deepcopy
from datetime import timedelta

import pytest

from tests.market.stage2_fakes import Clock, Venue, CONDITION, TOKENS
from weather.market.mm_stage2_hold import digest
from weather.market.mm_stage2_selection import PublicBooks, select_table, validate_selection
from weather.market.market_registry import REGISTRY


def universe():
    clock = Clock()
    rows = []
    for index, location in enumerate(('denver', 'seattle', 'los-angeles', 'san-francisco')):
        condition = '0x' + str(index + 1) * 64
        snapshot = Venue(clock).snapshot()
        snapshot['condition_id'] = condition
        snapshot['quote_inputs']['reward_rate_per_day'] = '540'
        rows.append({'market_id': location, 'market_timezone': REGISTRY[location].timezone, 'target_date': '2026-09-22',
                     'condition_id': condition, 'token_ids': list(TOKENS), 'snapshot': snapshot})
    return rows


def test_full_ranking_is_reproducible_and_first_only():
    rows = universe()
    table = select_table(rows, now=Clock().now())
    assert table['ranked_conditions'] == [rows[i]['condition_id'] for i in (2, 1, 3, 0)]
    selected = validate_selection(table, expected_sha256=digest(table), condition_id=rows[2]['condition_id'],
                                  token_ids=TOKENS, now=Clock().now())
    assert selected['market_id'] == 'los-angeles'
    with pytest.raises(ValueError, match='another condition'):
        validate_selection(table, expected_sha256=digest(table), condition_id=rows[1]['condition_id'],
                           token_ids=TOKENS, now=Clock().now())


@pytest.mark.parametrize('fault', ['hash', 'ranking', 'future', 'stale', 'partial', 'tokens'])
def test_selection_tampering_and_freshness_fail_closed(fault):
    table = select_table(universe(), now=Clock().now())
    now, tokens, sha = Clock().now(), TOKENS, digest(table)
    if fault == 'hash': sha = 'f' * 64
    if fault == 'ranking': table['ranked_conditions'].reverse(); sha = digest(table)
    if fault == 'future': now -= timedelta(seconds=1)
    if fault == 'stale': now += timedelta(seconds=1801)
    if fault == 'partial': table['universe_complete'] = False; sha = digest(table)
    if fault == 'tokens': tokens = ('111', '333')
    with pytest.raises(ValueError):
        validate_selection(table, expected_sha256=sha, condition_id=table['selected_condition_id'], token_ids=tokens, now=now)


def test_ineligible_rows_remain_in_selection_table():
    rows = universe()
    rows[0]['snapshot']['quote_inputs']['reward_min_size'] = '100'
    rows[1]['snapshot']['quote_inputs']['no_asks'] = []
    table = select_table(rows, now=Clock().now())
    assert len(table['rows']) == 4
    assert sum(r['eligible'] for r in table['rows']) == 2
    assert all(r['refusal'] for r in table['rows'] if not r['eligible'])


def test_stale_row_refuses_entire_universe_instead_of_selecting_another():
    rows = universe()
    rows[0]['snapshot']['observed_at_utc'] = (Clock().now() - timedelta(seconds=1801)).isoformat()
    with pytest.raises(ValueError, match='30-minute'):
        select_table(rows, now=Clock().now())


@pytest.mark.parametrize('fault', [None, 'condition', 'cursor', 'count', 'limit', 'duplicate'])
def test_public_condition_reward_requires_exact_complete_response(fault):
    import json
    condition = universe()[0]['condition_id']
    payload = {'data': [{'condition_id': condition, 'rewards_min_size': 20, 'rewards_max_spread': 3, 'total_daily_rate': 54}],
               'count': 1, 'limit': 100, 'next_cursor': 'LTE='}
    if fault == 'condition': payload['data'][0]['condition_id'] = '0x' + 'f' * 64
    if fault == 'cursor': payload['next_cursor'] = 'MORE'
    if fault == 'count': payload['count'] = 0
    if fault == 'limit': payload['limit'] = 501
    if fault == 'duplicate': payload['data'] *= 2; payload['count'] = 2
    class Response:
        status = 200
        headers = {'Content-Type': 'application/json'}
        def geturl(self): return 'https://clob.polymarket.com/rewards/markets/' + condition
        def read(self, _limit): return json.dumps(payload).encode()
        def close(self): pass
    def opener(request, *, timeout):
        assert request.get_method() == 'GET' and timeout == 2
        assert set(dict(request.header_items())) == {'Accept', 'User-agent'}
        return Response()
    reader = PublicBooks(clock=Clock().now, opener=opener)
    if fault:
        with pytest.raises(ValueError): reader.reward(condition)
    else:
        assert reader.reward(condition)['condition_id'] == condition
        assert len(reader.records) == 1
