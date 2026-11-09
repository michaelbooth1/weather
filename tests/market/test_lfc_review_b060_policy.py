"""Guards: B060 loss basis is explicit, economic, durable and next-claim only."""
from copy import deepcopy
import pytest

from tests.market.test_lfc_review_b060_refill import BASES, guard, opening, settled_pair
from weather.market.lfc_campaign_policy import parse_policy, PolicyRefused
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_f2_policy import support_table
from weather.market.lfc_f2_freeze import economic_digest


def test_shipped_refill_default_and_both_supported_economic_identities():
    row = example_policy()
    assert row['sleeve_loss_basis'] == 'net_of_retained_gains'
    assert support_table()['sleeve_loss_basis'] == sorted(BASES)
    modes = [parse_policy({**row, 'sleeve_loss_basis': value}) for value in BASES]
    assert economic_digest(modes[0]) != economic_digest(modes[1])


@pytest.mark.parametrize('value', [None, False, [], {}, 'NET', 'owner_cash', 'unrealized_gains'])
def test_unsupported_loss_bases_refuse(value):
    with pytest.raises(PolicyRefused, match='sleeve_loss_basis'):
        parse_policy({**example_policy(), 'sleeve_loss_basis': value})


def test_legacy_policy_snapshot_without_the_field_remains_gross():
    row = example_policy(); row.pop('sleeve_loss_basis', None)
    policy = parse_policy(row)
    assert policy.raw.get('sleeve_loss_basis', 'gross') == 'gross'
    assert economic_digest(policy) == economic_digest(parse_policy({**row, 'sleeve_loss_basis': 'gross'}))


def test_sleeve_charge_never_uses_a_label_only_legacy_profit(tmp_path):
    from tests.market.test_lfc_f2_capital import activity, filled, install, ledger_at
    from weather.market.lfc_capital import record_activity
    ledger = ledger_at(tmp_path); filled(ledger, 'legacy', price='.48'); install(ledger, cash='290.4')
    record_activity(ledger, activity(cash='20'))
    row = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    assert row['segregated_profit_native'] > 0
    assert row['proven_campaign_profit_cumulative_native'] == row['retained_gains_offset_native'] == 0


def test_basis_change_requires_a_revision_and_applies_only_at_the_next_claim(tmp_path):
    from weather.market.lfc_campaign_recovery import recover_empty
    from weather.market.lfc_ledger import Ledger
    ledger, state, claim, policy = opening(tmp_path, 'gross')
    before = CapitalBook(ledger).figures()
    assert recover_empty(state, ledger.clock())
    row = deepcopy(policy.raw); row['sleeve_loss_basis'] = 'net_of_retained_gains'
    new = parse_policy(row); entry = next(e for e in new.entries if e.local_date == '2026-11-12')
    ledger.clock = lambda: entry.start
    with pytest.raises(StateRefused, match='economic_policy_change_requires_revision'):
        state.claim(entry, new, ledger.clock())
    assert CapitalBook(ledger).figures()['sleeve_loss_basis'] == 'gross'
    row['policy_revision'] += 1; row['revision'] += 1; new = parse_policy(row)
    state.claim(entry, new, ledger.clock())
    assert CapitalBook(ledger).figures()['sleeve_loss_basis'] == 'net_of_retained_gains'
    reopened = Ledger.open(ledger.path, clock=ledger.clock)
    assert CapitalBook(reopened).figures() == CapitalBook(ledger).figures()
    assert CapitalBook(reopened).figures()['funding_native'] == before['funding_native']


def test_planning_a_new_basis_cannot_change_the_current_durable_intent_gate(tmp_path):
    from weather.market.lfc_ledger import Ledger
    ledger, *_ = settled_pair(tmp_path, 'gross')
    policy = parse_policy({**example_policy(), 'sleeve_loss_basis': 'net_of_retained_gains'})
    policy.cost_gate(ledger, policy.entries[0], '300')
    assert CapitalBook(ledger).figures()['sleeve_loss_basis'] == 'gross'
    ledger.record('session_start', session_id='old-basis', counted=False)
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        ledger.intent(session_id='old-basis', intent_key='old-basis', token_id='101', condition_id='c',
            price='.5', size='600', fee_rate_bps='0')


@pytest.mark.parametrize('value', [[], {}, False, 'unrealized_gains'])
def test_invalid_durable_loss_basis_cannot_be_appended_or_reset_a_claim(tmp_path, value):
    from weather.market.lfc_ledger import LedgerUnavailable
    ledger, *_ = opening(tmp_path, 'gross')
    before = ledger.path.read_bytes()
    with pytest.raises(LedgerUnavailable, match='capital_loss_basis'):
        ledger.record('autostart_claim', attempt_id='bad-basis', file_sha256='a'*64,
                      local_date='2026-11-12', sleeve_loss_basis=value)
    assert ledger.path.read_bytes() == before and ledger.sleeve_loss_basis == 'gross'


def test_omitting_the_field_cannot_hide_a_net_to_gross_change_from_revision_checks(tmp_path):
    from weather.market.lfc_campaign_recovery import recover_empty
    ledger, state, _, policy = opening(tmp_path, 'net_of_retained_gains')
    assert recover_empty(state, ledger.clock())
    row = deepcopy(policy.raw); row.pop('sleeve_loss_basis')
    legacy = parse_policy(row); entry = next(e for e in legacy.entries if e.local_date == '2026-11-12')
    ledger.clock = lambda: entry.start
    with pytest.raises(StateRefused, match='economic_policy_change_requires_revision'):
        state.claim(entry, legacy, ledger.clock())
    assert ledger.sleeve_loss_basis == 'net_of_retained_gains'
