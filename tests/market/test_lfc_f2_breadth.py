"""Owner-approved breadth on synthetic books; no external account or service.

Guards: B057 registry universe, own-zone T+1, deterministic distance arms and daily/sleeve intent gates.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tests.market.test_lfc_f2_capital import install, ledger_at
from tests.market.test_lfc_f2_selection import universe, capital
from weather.market.lfc_campaign_policy import parse_policy, PolicyRefused
from weather.market.lfc_capital import CapitalBook, CapitalRefused, native
from weather.market.lfc_f2_breadth import (PROTOCOL, CONTINUE, arm, band_day_usage, captured_market_ids,
                                         daily_gate, example_policy)
from weather.market.lfc_f2_selection import build_table, validate_table
from weather.market.market_registry import REGISTRY


NOW = datetime(2026, 11, 11, 14, tzinfo=timezone.utc)


def cities(now=NOW):
    result = []
    for index, city in enumerate(captured_market_ids(), 1):
        row = deepcopy(universe()[0])
        cid = '0x' + format(index, '064x')
        tokens = [str(1000 + index * 2), str(1001 + index * 2)]
        row.update(market_id=city, market_timezone=REGISTRY[city].timezone,
            target_date=(now.astimezone(ZoneInfo(REGISTRY[city].timezone)).date() + timedelta(days=1)).isoformat(),
            condition_id=cid, token_ids=tokens, event_condition_ids=[cid], event_slug=city + '-synthetic')
        snapshot = row['snapshot']
        snapshot.update(condition_id=cid, token_ids=tokens, observed_at_utc=now.isoformat())
        snapshot['rules'] = {token: deepcopy(next(iter(snapshot['rules'].values()))) for token in tokens}
        result.append(row)
    return result


def start(ledger, key, city='toronto', **changes):
    assignment = arm(parse_policy(example_policy()), NOW.astimezone(ZoneInfo('America/Toronto')).date().isoformat(), city)
    return ledger.record('session_start', session_id=key, counted=True, protocol=PROTOCOL,
        market_id=city, quote_day_utc=NOW.date().isoformat(), per_band_daily_filled_cap_pusd='40',
        autostart_attempt_id='a' * 32, **assignment, **changes)


def post(ledger, sid, key, price='.5', size='20'):
    return ledger.intent(session_id=sid, intent_key=key, token_id=key, condition_id='condition-' + sid,
                         price=price, size=size, fee_rate_bps='0')


def test_default_universe_is_all_captured_builtins_and_one_band_each():
    policy = parse_policy(example_policy())
    rows = cities()
    table = build_table(rows + [deepcopy(rows[0]) | {'condition_id': 'extra',
        'event_condition_ids': ['extra'], 'snapshot': deepcopy(rows[0]['snapshot']) | {'condition_id': 'extra'}}],
        now=NOW, policy=policy, cash='300', capital=capital())
    selected = validate_table(table, now=NOW, policy=policy)
    assert len(selected) == len(captured_market_ids()) == 12
    assert {row['market_id'] for row in selected} == set(captured_market_ids())
    assert len({row['market_id'] for row in selected}) == len(selected)
    assert all(row['quote_arm'] in {'learning-0.015', 'learning-0.025'} for row in selected)


@pytest.mark.parametrize('now', [datetime(2026, 11, 11, 5, 30, tzinfo=timezone.utc),
                                  datetime(2026, 11, 11, 7, 30, tzinfo=timezone.utc)])
def test_each_city_uses_own_midnight_and_held_event_is_excluded(now):
    policy = parse_policy(example_policy())
    rows = cities(now)
    targets = {row['market_id']: row['target_date'] for row in rows}
    assert targets['toronto'] == '2026-11-12'
    assert targets['los-angeles'] == '2026-11-11'
    held = rows[0]['condition_id']
    table = build_table(rows, now=now, policy=policy, cash='300', capital=capital(), held_conditions=[held])
    selected = validate_table(table, now=now, policy=policy)
    assert len(selected) == 11 and held not in table['selected_condition_ids']
    wrong = deepcopy(rows)
    next(row for row in wrong if row['market_id'] == 'los-angeles')['target_date'] = '2026-11-12'
    result = build_table(wrong, now=now, policy=policy, cash='300', capital=capital())
    assert next(r for r in result['rows'] if r['market_id'] == 'los-angeles')['refusal'] == 'market_local_horizon'


@pytest.mark.parametrize('day,learning', [('2026-11-10', True), ('2026-11-15', True),
                                        ('2026-11-16', False), ('2026-11-17', False), ('2026-12-22', False)])
def test_arms_are_repeatable_only_in_learning_and_confirmation_uses_field(day, learning):
    policy = parse_policy(example_policy())
    arms = [arm(policy, day, city) for city in captured_market_ids()]
    assert arms == [arm(policy, day, city) for city in captured_market_ids()]
    if learning:
        assert {row['quote_offset_pusd'] for row in arms} == {'0.015', '0.025'}
    else:
        assert {row['quote_arm'] for row in arms} == {'fixed-0.015'}
        row = example_policy(); row.update(quote_offset_pusd='0.025', policy_revision=4)
        assert arm(parse_policy(row), day, 'toronto')['quote_arm'] == 'fixed-0.025'


@pytest.mark.parametrize('key,value', [('market_ids', ['austin']), ('band_limit_session', 1),
    ('per_band_daily_filled_cap_pusd', '20'), ('fill_cooldown_seconds', 60), ('fill_cooldown_seconds', 3600),
    ('learning_quote_offsets_pusd', ['0.025']), ('on_first_band_fill', CONTINUE)])
def test_each_new_field_accepts_supported_values(key, value):
    row = example_policy(); row[key] = value
    if key in {'market_ids', 'band_limit_session'}:
        row['band_limit_session'] = row['band_limit_concurrent'] = 1
    assert parse_policy(row).raw[key] == value


@pytest.mark.parametrize('key,value', [('market_ids', ['london']), ('band_limit_session', 13),
    ('band_limit_concurrent', 0), ('per_band_daily_filled_cap_pusd', '300.000001'),
    ('per_band_daily_filled_cap_pusd', '0'), ('fill_cooldown_seconds', 0), ('fill_cooldown_seconds', True),
    ('fill_cooldown_seconds', 1), ('fill_cooldown_seconds', 59), ('fill_cooldown_seconds', 3601),
    ('learning_quote_offsets_pusd', ['0.02']), ('learning_quote_offsets_pusd', []),
    ('on_first_band_fill', 'unproved_repost')])
def test_each_new_field_refuses_unsupported_values(key, value):
    row = example_policy(); row[key] = value
    with pytest.raises(PolicyRefused):
        parse_policy(row)


def test_daily_filled_cap_reserves_all_legs_and_persists_across_revision_and_reopen(tmp_path):
    from weather.market.lfc_ledger import Ledger
    ledger = ledger_at(tmp_path); install(ledger, cash='300')
    start(ledger, 'first')
    for index in range(3):
        key = str(index); post(ledger, 'first', key); ledger.ack(key, key)
        ledger.terminal(key, {'id': key, 'status': 'MATCHED', 'size_matched': '20'}, source='fixture')
    ledger.record('session_end', session_id='first')
    ledger = Ledger.open(ledger.path, clock=lambda: NOW)
    receipt = start(ledger, 'revision')
    post(ledger, 'revision', 'fourth')
    assert band_day_usage(ledger, 'toronto', '2026-11-11')['filled_native'] == 30_000_000
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match='per_band_daily_filled_cap'):
        post(ledger, 'revision', 'fifth', price='.000001')
    assert ledger.path.read_bytes() == before
    rows = [r for r in ledger.rows if r['event'] == 'leg_intent']
    assert all(r['quote_arm'] == receipt['quote_arm'] and r['market_id'] == 'toronto' for r in rows)


def test_daily_pair_gate_includes_prospective_reserve_and_excludes_other_city(tmp_path):
    ledger = ledger_at(tmp_path); install(ledger, cash='300')
    start(ledger, 'toronto'); start(ledger, 'denver', city='denver')
    post(ledger, 'toronto', 'filled', price='.79'); ledger.ack('filled', 'oid')
    ledger.terminal('oid', {'id': 'oid', 'status': 'MATCHED', 'size_matched': '20'}, source='fixture')
    post(ledger, 'denver', 'other')
    with pytest.raises(CapitalRefused, match='per_band_daily_filled_cap'):
        daily_gate(ledger, ledger.sessions['toronto']['start'], reserve='24.200001')
    assert daily_gate(ledger, ledger.sessions['toronto']['start'], reserve='24.2')['remaining_native'] == 0


def test_breadth_examples_are_disabled_exact_defaults_and_k2_remains_readable():
    import json
    from weather.paths import REPO_ROOT
    for name in ('lfc-campaign.example.json', 'campaign.proposed.json'):
        row = json.loads((REPO_ROOT / 'docs/examples' / name).read_text(encoding='utf-8'))
        # Files ship the owner's refill default even when the regression
        # plugin deliberately runs generated fixtures under the gross basis.
        assert row == {**example_policy(), 'sleeve_loss_basis': 'net_of_retained_gains'} and row['enabled'] is False
        assert parse_policy(row).f2
    old = json.loads((REPO_ROOT / 'docs/examples/lfc-campaign.k2-reference.json').read_text(encoding='utf-8'))
    assert parse_policy(old).raw['band_limit_session'] == 2


def test_large_closed_proof_is_fully_validated_but_only_compact_projection_is_cached(tmp_path):
    import os
    from weather.market.lfc_campaign_state import AccountState, StateRefused
    from weather.market.lfc_recording_io import strict_json
    from weather.market.mm_stage2_hold import digest
    ledger = ledger_at(tmp_path)
    state = AccountState(tmp_path / 'state', ledger)
    state.root.mkdir(parents=True)
    proof = {'ledger_head_sha256': ledger.previous, 'money_accounting_complete': True,
             'unknown_submit': False, 'cleanup_proven': True, 'account_read': {'fixture': 'x' * 3_000_000},
             'capital': {'fixture': 'z' * 1_000_000}}
    from tests.market.test_lfc_campaign import Mutexes
    from weather.market.lfc_campaign_guard import account_lease
    with account_lease(ledger.rows[0]['maker_address'], backend=Mutexes()):
        state.save('closed/fixture.json', {'attempt_id': 'fixture', 'proof': proof, 'proof_sha256': digest(proof)})
    path = state.root / 'closed/fixture.json'
    first = state.closed_binding(path)
    assert 'account_read' not in first['proof'] and len(str(first)) < 2000
    assert state.closed_binding(path) == first
    stamp = path.stat()
    changed = path.read_bytes().replace(b'xxxxxxxx', b'yyyyyyyy', 1)
    path.write_bytes(changed); os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(StateRefused, match='closeout_proof_hash'):
        state.closed_binding(path)


def test_previous_toronto_day_arm_cannot_enter_a_new_band_day():
    before = datetime(2026, 11, 12, 4, 55, tzinfo=timezone.utc)
    after = before + timedelta(minutes=10)
    policy = parse_policy(example_policy())
    # Seattle has not crossed its local event horizon, isolating the arm date.
    rows = [row for row in cities(before) if row['market_id'] == 'seattle']
    table = build_table(rows, now=before, policy=policy, cash='300', capital=capital())
    assert table['selected_condition_ids']
    with pytest.raises(ValueError, match='f2_quote_arm_day_changed'):
        validate_table(table, now=after, policy=policy)
