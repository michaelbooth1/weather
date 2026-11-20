"""Synthetic settlement/final-look receipts; no live or public read.

Guards: B040 10-12, zero payout loss, cutoff cash and proved enrollment funding.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at
from tests.market.test_lfc_campaign_runtime import runtime_at
from tests.market.test_lfc_f2_capital import activity, filled, install, ledger_at
from tests.market.test_lfc_settlement_record import CONDITION, NOW, resolution, tokens, record_settlement
from weather.market.lfc_accounting import inventory_delta
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import CapitalBook, record_activity
from weather.market.lfc_capital_settlement import record_zero_payouts
from weather.market.lfc_f2_economics import measured
from weather.market.lfc_f2_final import snapshot
from weather.market.lfc_f2_policy import example_policy
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.mm_stage2_hold import digest


@pytest.fixture(autouse=True)
def guarded_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def settled_ledger(tmp_path, *, settlement_time=NOW):
    ledger = ledger_at(tmp_path)
    for key, token in [('loser', '111'), ('winner', '222')]:
        filled(ledger, key, token=token, condition=CONDITION)
    install(ledger, cash='280')
    record_settlement(tmp_path, CONDITION, clock=lambda: settlement_time,
        get=lambda path, params: resolution() if path.endswith('resolutions') else tokens())
    return ledger


def test_unburned_zero_payout_is_realized_loss_and_still_physical_inventory(tmp_path):
    ledger = settled_ledger(tmp_path)
    original_l = ledger.L()
    before = CapitalBook(ledger).figures()
    assert record_zero_payouts(ledger, tmp_path) == 1
    book = CapitalBook(ledger)
    assert book.losses == 10_000_000 and book.figures()['unrecovered_inventory_cost_native'] == 10_000_000
    assert book.figures()['charged_native'] == before['charged_native'] == 20_000_000
    assert book.lots['loser']['remaining_quantity'] == 20
    facts = measured(ledger, ['loser', 'winner'])
    assert [r['token_id'] for r in facts['carried_inventory']] == ['222']
    assert facts['unswept_zero_payout_positions'][0]['token_id'] == '111'
    inventory = inventory_delta(ledger, book.anchor, {'111': '20', '222': '20'})
    assert not inventory['changed']
    assert '111' in inventory_delta(ledger, book.anchor, {'222': '20'})['changed']
    tip = ledger.previous
    assert record_zero_payouts(ledger, tmp_path) == 0 and ledger.previous == tip and ledger.L() == original_l
    assert CapitalBook(Ledger.open(ledger.path, clock=ledger.clock)).figures() == book.figures()
    row = {**activity(cash='0', token='111'), 'condition_id': CONDITION}
    record_activity(ledger, row)
    assert CapitalBook(ledger).losses == 10_000_000  # Later burn cannot charge twice.


@pytest.mark.parametrize('bad', ['hash', 'winner_token', 'price_only'])
def test_zero_loss_requires_original_resolution_payout_evidence(tmp_path, bad):
    ledger = settled_ledger(tmp_path)
    assert record_zero_payouts(ledger, tmp_path) == 1
    row = deepcopy(ledger.capital_rows[-1])
    before = ledger.previous
    fields = {key: value for key, value in row.items() if key not in
              {'schema_version', 'kind', 'sequence', 'previous_sha256', 'recorded_at_utc', 'event'}}
    if bad == 'hash': fields['settlement_sha256'] = '0' * 64
    if bad == 'winner_token': fields['intent_keys'] = ['winner']
    if bad == 'price_only':
        fields['settlement']['resolution'] = None
        fields['settlement_sha256'] = digest(fields['settlement'])
    with pytest.raises(LedgerUnavailable): ledger.record('capital_zero_resolution', **fields)
    assert ledger.previous == before


def test_zero_payout_cannot_later_be_recycled_as_positive_cash(tmp_path):
    ledger = settled_ledger(tmp_path)
    record_zero_payouts(ledger, tmp_path)
    row = {**activity(cash='20', token='111'), 'condition_id': CONDITION}
    with pytest.raises(LedgerUnavailable, match='capital_zero_payout_contradiction'): record_activity(ledger, row)


def test_cutoff_winner_is_not_cash_even_if_redeemed_after_cutoff(tmp_path):
    ledger = settled_ledger(tmp_path)
    record_zero_payouts(ledger, tmp_path)
    policy = parse_policy(example_policy())
    now = datetime(2026, 12, 28, 23, tzinfo=timezone.utc)
    ledger.clock = lambda: now
    late = {**activity(cash='20', token='222'), 'condition_id': CONDITION,
            'timestamp': int(datetime(2026, 12, 28, 18, tzinfo=timezone.utc).timestamp())}
    record_activity(ledger, late)
    row = snapshot(ledger, policy, root=tmp_path, now=now)
    winner = row['unredeemed_winners_at_cutoff'][0]
    assert winner['token_id'] == '222' and winner['counted_as_cash_native'] == 0
    assert winner['unredeemed_payout_native'] == 20_000_000
    assert sum(row['proved_redemption_cash_native'].values()) == 0 and row['late_cash_activity_ids']
    assert row['assessment']['state'] == 'INCONCLUSIVE' and row['planning_booked_as_income'] is False
    assert row['unswept_zero_payout_positions'][0]['token_id'] == '111'


@pytest.mark.parametrize('offset_us', [-1, 0, 1])
def test_final_inventory_uses_only_settlement_observed_by_cutoff(tmp_path, offset_us):
    policy = parse_policy(example_policy())
    cutoff = datetime.fromisoformat(policy.raw['evidence_cutoff_toronto']).astimezone(timezone.utc)
    observed = cutoff + timedelta(microseconds=offset_us)
    ledger = settled_ledger(tmp_path, settlement_time=observed)
    row = snapshot(ledger, policy, root=tmp_path, now=cutoff + timedelta(hours=6))

    assert sum(row['proved_redemption_cash_native'].values()) == 0
    assert row['assessment']['state'] == 'INCONCLUSIVE'
    receipt_key = str((tmp_path / 'settlement' / (CONDITION + '.json')).relative_to(tmp_path))
    assert row['settlement_cutoff_clock'] == 'recorder_observed_at_utc'
    if offset_us > 0:
        assert row['unredeemed_winners_at_cutoff'] == []
        assert row['unswept_zero_payout_positions'] == []
        assert {lot['token_id'] for lot in row['unresolved_at_cutoff']} == {'111', '222'}
        assert receipt_key not in row['evidence_sha256']
        late, = row['late_settlement_receipts']
        assert late['file'] == receipt_key and late['observed_at_utc'] == observed.isoformat()
    else:
        assert [lot['token_id'] for lot in row['unredeemed_winners_at_cutoff']] == ['222']
        assert [lot['token_id'] for lot in row['unswept_zero_payout_positions']] == ['111']
        assert row['unresolved_at_cutoff'] == []
        assert receipt_key in row['evidence_sha256'] and not row['late_settlement_receipts']


def test_after_cutoff_before_final_look_is_an_honest_snapshot(tmp_path):
    ledger = settled_ledger(tmp_path)
    policy = parse_policy(example_policy())
    now = datetime(2026, 12, 28, 17, tzinfo=timezone.utc)
    row = snapshot(ledger, policy, root=tmp_path, now=now)
    assert row['assessment']['reason'] == 'success_look_not_open'
    with pytest.raises(ValueError, match='final_cutoff_not_open'):
        snapshot(ledger, policy, root=tmp_path, now=now.replace(hour=16))


def test_final_look_cli_is_read_only_and_create_only(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_cli as cli, lfc_campaign_runtime as adapter
    runtime = runtime_at(tmp_path)
    runtime.policy_path.write_text(json.dumps(example_policy()))
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'control')
    monkeypatch.setattr(cli, 'load_release', lambda *a: {'maker_address': MAKER, 'campaign_path': str(runtime.policy_path)})
    monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
    monkeypatch.setattr(cli, 'bound_state', lambda *a: (runtime.pilot_root, runtime.state))
    @contextmanager
    def account(*a): yield
    monkeypatch.setattr(cli, 'account_lease', account)
    monkeypatch.setattr(adapter, 'CampaignClock', lambda: SimpleNamespace(now=lambda: datetime(2026, 12, 28, 23, tzinfo=timezone.utc)))
    output = tmp_path / 'final.json'
    args = ['final-look', '--release', 'synthetic', '--release-sha256', 'a' * 64, '--output', str(output)]
    before = runtime.state.ledger.path.read_bytes()
    assert cli.main(args) == 0
    original = output.read_bytes()
    assert json.loads(original)['assessment']['state'] == 'INCONCLUSIVE'
    assert cli.main(args) == 1 and output.read_bytes() == original
    assert runtime.state.ledger.path.read_bytes() == before


@pytest.mark.parametrize('complete', [False, True])
def test_pre_enable_funding_receipt_reports_only_reconciled_actual_funding(tmp_path, monkeypatch, complete):
    runtime = runtime_at(tmp_path)
    @contextmanager
    def admission(): yield
    monkeypatch.setattr(runtime, 'admission', admission)
    monkeypatch.setattr(runtime, 'reload_ledger', lambda: runtime.state.ledger)
    monkeypatch.setattr(runtime, 'read_account', lambda: {})
    monkeypatch.setattr(runtime, 'core_proof', lambda *a, **kw: {'money_accounting_complete': complete,
        'cleanup_proven': True, 'unknown_submit': False, 'capital': {'cash_bridge_complete': True, 'funding_native': 300_000_000}})
    if complete:
        row = runtime.confirm_funding()
        assert row['funding_native'] == 300_000_000 and row['capital_bridge_complete']
        assert len(list((runtime.state.root / 'funding').glob('*.json'))) == 1
    else:
        with pytest.raises(StateRefused, match='enrollment_funding_unreconciled'): runtime.confirm_funding()
        assert not list((runtime.state.root / 'funding').glob('*.json'))
    assert not runtime.state.ledger.autostart_claims


@pytest.mark.parametrize('late_receipt', [False, True])
def test_deposit_after_enrollment_before_first_bridge_never_becomes_funding(tmp_path, late_receipt):
    from tests.market.test_lfc_f2_native import proof, TX
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    clock = Clock()
    state = state_at(tmp_path, clock)
    ledger = state.ledger
    baseline = json.loads((ledger.path.parent / ledger.baselines[0]['file']).read_text())
    ledger.record('capital_anchor', baseline=baseline, baseline_sha256=digest(baseline))
    clock.sleep(2)
    row = {**activity(cash='100', kind='DEPOSIT', size='0', tx=TX), 'timestamp': int(clock.now().timestamp()) - 1}
    evidence = proof([row], incoming=100_000_000)
    if late_receipt:
        record_activity(ledger, row, native_evidence={**evidence, 'receipt': rpc_packet(None)})
        book = CapitalBook(ledger)
        ledger.record('capital_resolution', source=row, source_sha256=digest(row),
            previous_source_sha256=book.sources[book.unknown[0]], native_evidence=evidence)
    else:
        record_activity(ledger, row, native_evidence=evidence)
    install(ledger, cash='200')
    book = CapitalBook(ledger)
    assert book.external == book.figures()['funding_native'] == 100_000_000
    assert book.figures()['headroom_native'] == 100_000_000


@pytest.mark.parametrize('recovery', [False, True])
def test_first_late_receipt_keeps_cutoff_rows_on_report_rerun(tmp_path, monkeypatch, recovery):
    from weather.market import lfc_f2_freeze
    from weather.market.lfc_f2_final import write_final

    policy = parse_policy(example_policy())
    cutoff = datetime.fromisoformat(policy.raw['evidence_cutoff_toronto']).astimezone(timezone.utc)
    observed = cutoff + timedelta(microseconds=1)
    ledger = ledger_at(tmp_path)
    for key, token in [('loser', '111'), ('winner', '222')]:
        filled(ledger, key, token=token, condition=CONDITION)
    install(ledger, cash='280')
    state = SimpleNamespace(root=tmp_path, ledger=ledger, require_retained_evidence=lambda: None)
    monkeypatch.setattr(lfc_f2_freeze, 'verify', lambda *a, **kw: None)
    before_path = tmp_path / 'before.json'
    first = write_final(state, policy, root=tmp_path, output=before_path, now=cutoff)
    original = tmp_path / 'settlement' / (CONDITION + '.json')
    if recovery:
        original.parent.mkdir()
        original.write_bytes(b'invalid fixture\n')
    record_settlement(tmp_path, CONDITION, clock=lambda: observed, recover_corrupt=recovery,
                      get=lambda path, params: resolution() if path.endswith('resolutions') else tokens())
    current = write_final(state, policy, root=tmp_path, output=tmp_path / 'after.json', now=cutoff + timedelta(hours=6))
    for key in ('unresolved_at_cutoff', 'unredeemed_winners_at_cutoff', 'unswept_zero_payout_positions',
                'proved_redemption_cash_native', 'evidence_sha256'):
        assert first[key] == current[key]
    assert not first['late_settlement_receipts']
    receipt, = current['late_settlement_receipts']
    assert receipt['observed_at_utc'] == observed.isoformat()
    assert ('-recovery-' in receipt['file']) is recovery
    from weather.market.lfc_recording_io import file_sha
    assert receipt['sha256'] == file_sha(tmp_path / receipt['file'])
    assert json.loads(before_path.read_bytes())['late_settlement_receipts'] == []


def test_valid_early_original_takes_precedence_over_later_published_recovery(tmp_path):
    from weather.market.lfc_recording_io import prepare_recovery, publish_recovery, write_new

    policy = parse_policy(example_policy())
    cutoff = datetime.fromisoformat(policy.raw['evidence_cutoff_toronto']).astimezone(timezone.utc)
    ledger = settled_ledger(tmp_path, settlement_time=cutoff)
    before = snapshot(ledger, policy, root=tmp_path, now=cutoff)
    original = tmp_path / 'settlement' / (CONDITION + '.json')
    late_time = cutoff + timedelta(seconds=1)
    replacement, manifest = prepare_recovery(original, clock=lambda: late_time, reason='test_fixture')
    new = dict(json.loads(original.read_bytes()), observed_at_utc=late_time.isoformat())
    write_new(replacement, new)
    publish_recovery(replacement, manifest)
    after = snapshot(ledger, policy, root=tmp_path, now=late_time)
    for key in ('unresolved_at_cutoff', 'unredeemed_winners_at_cutoff', 'unswept_zero_payout_positions',
                'evidence_sha256'):
        assert before[key] == after[key]
    assert [row['token_id'] for row in after['unredeemed_winners_at_cutoff']] == ['222']
    late, = after['late_settlement_receipts']
    assert late['file'] == str(replacement.relative_to(tmp_path))


@pytest.mark.parametrize('accepted_recovery', [False, True])
def test_final_report_keeps_disputed_condition_separate_and_is_create_only(tmp_path, monkeypatch, accepted_recovery):
    from tests.market.test_lfc_settlement_token_consensus import CID, ORIGINAL, historical_row, payload
    from weather.market import lfc_f2_freeze
    from weather.market.lfc_f2_final import write_final
    from weather.market.lfc_recording_io import file_sha, prepare_recovery, publish_recovery, retained, write_new

    policy = parse_policy(example_policy())
    cutoff = datetime.fromisoformat(policy.raw['evidence_cutoff_toronto']).astimezone(timezone.utc)
    now = cutoff + timedelta(hours=6)
    ledger = ledger_at(tmp_path)
    filled(ledger, 'disputed', token='101', condition=CID)
    filled(ledger, 'valid_winner', token='222', condition=CONDITION)
    filled(ledger, 'valid_loser', token='111', condition=CONDITION)
    original = tmp_path / 'settlement' / (CID + '.json')
    disputed = historical_row()
    write_new(original, disputed)
    record_settlement(tmp_path, CONDITION, clock=lambda: cutoff,
                      get=lambda path, params: resolution() if path.endswith('resolutions') else tokens())
    valid = tmp_path / 'settlement' / (CONDITION + '.json')
    if accepted_recovery:
        replacement, manifest = prepare_recovery(original, clock=lambda: cutoff, reason='fixture')
        write_new(replacement, dict(disputed, tokens=retained(payload(ORIGINAL))))
        publish_recovery(replacement, manifest)

    evidence_before = (original.read_bytes(), valid.read_bytes(), ledger.path.read_bytes())
    state = SimpleNamespace(root=tmp_path, ledger=ledger, require_retained_evidence=lambda: None)
    monkeypatch.setattr(lfc_f2_freeze, 'verify', lambda *a, **kw: None)
    output = tmp_path / 'report.json'
    report = write_final(state, policy, root=tmp_path, output=output, now=now)
    assert {row['intent_key'] for row in report['unredeemed_winners_at_cutoff']} == (
        {'valid_winner', 'disputed'} if accepted_recovery else {'valid_winner'})
    assert [row['intent_key'] for row in report['unswept_zero_payout_positions']] == ['valid_loser']
    assert sum(report['proved_redemption_cash_native'].values()) == 0
    assert report['assessment']['state'] == 'INCONCLUSIVE'
    assert report['evidence_sha256'][str(valid.relative_to(tmp_path))] == file_sha(valid)
    if accepted_recovery:
        assert report['unresolved_settlement_conditions'] == report['unresolved_at_cutoff'] == []
        assert report['evidence_sha256'][str(replacement.relative_to(tmp_path))] == file_sha(replacement)
    else:
        unresolved, = report['unresolved_at_cutoff']
        assert unresolved['intent_key'] == 'disputed' and unresolved['counted_as_cash_native'] == 0
        assert report['unresolved_settlement_conditions'] == [
            {'condition_id': CID, 'state': 'SETTLEMENT_SCOPE_UNPROVEN',
             'reason': 'ambiguous_matching_token_pair', 'file': str(original.relative_to(tmp_path)),
             'sha256': file_sha(original)}
        ]

    first_bytes = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_final(state, policy, root=tmp_path, output=output, now=now)
    assert output.read_bytes() == first_bytes
    repeated = tmp_path / 'second-report.json'
    assert write_final(state, policy, root=tmp_path, output=repeated, now=now) == report
    assert repeated.read_bytes() == first_bytes
    assert (original.read_bytes(), valid.read_bytes(), ledger.path.read_bytes()) == evidence_before
