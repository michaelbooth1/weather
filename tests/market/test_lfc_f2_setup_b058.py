"""Inert setup latency through the real owner-runtime and freshness guard.

Guards: B058 twelve-band setup does not spend the only date on a stale go read.
"""
import time
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_f2_breadth_runtime import owner_runtime_fixture
from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_f2_breadth import band_day_usage
from weather.market.lfc_ledger import Ledger


@pytest.mark.parametrize('gap', [False, True])
def test_known_auto_redemption_between_t40_and_go_reconciles_without_moving_anchor(tmp_path, monkeypatch, gap):
    from tests.market.test_lfc_f2_capital_reads import native_packet, packet
    from tests.market.test_lfc_f2_capital import MAKER, NOW, filled, ledger_at
    from tests.market.test_lfc_f2_native import TX
    from tests.market.test_lfc_redemption_native import paired
    from tests.market.test_lfc_pilot import Clock
    from weather.market.lfc_capital_reads import read_activity, synchronize
    from weather.market.lfc_capital import CapitalBook, ASSET
    from weather.market.lfc_campaign_policy import parse_policy
    from weather.market.lfc_campaign_runtime import Runtime, ScheduledAuthority
    from weather.market.lfc_f2_breadth import example_policy
    from weather.market.lfc_ledger import take_baseline, write_baseline
    from weather.market.lfc_recording_io import write_new
    from weather.market.mm_stage2_hold import digest
    source, native, tokens = paired(auto=True)
    ledger = ledger_at(tmp_path)
    anchor = take_baseline(label='t40', now=NOW, maker_address=MAKER, positions=[], open_orders=[], available_collateral='300')
    write_baseline(tmp_path, anchor, ledger)
    filled(ledger, 'winner', token=tokens[0], condition=source['condition_id'], price='.35')
    filled(ledger, 'loser', token=tokens[1], condition=source['condition_id'], price='.45')
    read = {'complete': True, 'maker_address': MAKER, 'open_orders': [],
        'positions': [{'asset': token, 'conditionId': source['condition_id'], 'size': '20'} for token in tokens],
        'ended_at_utc': NOW.isoformat(), 'balances': {'available_collateral': '284', 'assets': {ASSET: '284'},
            'collateral_evidence': {'balance': '284000000'}},
        'capital_activity': native_packet(read_activity(MAKER, int(NOW.timestamp()), int(NOW.timestamp()),
            get=lambda *a: packet(), sleep=lambda _: None))}
    synchronize(ledger, anchor, read)
    clock = Clock(NOW); ledger.clock = clock.now; clock.seconds = 1
    t40 = take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=read['positions'], open_orders=[], available_collateral='284')
    write_baseline(tmp_path, t40, ledger)
    clock.seconds = 2
    source['timestamp'] = int(clock.now().timestamp())
    native['rows_sha256'] = digest(native['rows'])
    observed = native_packet(read_activity(MAKER, int(NOW.timestamp()), int(clock.now().timestamp()),
        get=lambda *a: packet([source]), sleep=lambda _: None))
    observed['native_receipts'] = {TX: native}
    when = clock.now().isoformat()
    read.update(schema_version='lfc_campaign_account_read_v0.1', errors=[],
        scope='account_wide_sdk_trades_and_f0_v2_positions', since=str(int(NOW.timestamp())),
        started_at_utc=when, ended_at_utc=when, geography={'blocked': False}, positions=[],
        trades=[{'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'order-' + key, 'matched_amount': '20'}]}
                for key in ('winner', 'loser')],
        component_times={name: {'started_at_utc': when, 'ended_at_utc': when}
                         for name in ('open_orders', 'trades', 'positions', 'balances', 'geography')},
        balances={'available_collateral': '304', 'assets': {ASSET: '304'},
                  'collateral_evidence': {'balance': '304000000'}}, capital_activity=observed)
    state = SimpleNamespace(ledger=ledger, maker=MAKER, root=tmp_path / 'state', incidents=lambda: [],
        require_history=lambda: None, require_retained_evidence=lambda: None,
        save=lambda name, value: write_new(tmp_path / 'state' / name, value))
    runtime = object.__new__(Runtime)
    runtime.state, runtime.clock = state, clock
    runtime.lease = SimpleNamespace(check=lambda: None)
    calls = []
    def account_read():
        calls.append(clock.seconds)
        if gap and len(calls) == 1:
            from weather.market.lfc_campaign import TransientPrecheck
            raise TransientPrecheck('synthetic_redemption_propagation')
        return read
    runtime.read_account = account_read
    runtime.original_baseline = lambda _: anchor
    policy = parse_policy(example_policy())
    authority = object.__new__(ScheduledAuthority)
    authority.runtime, authority.policy, authority.entry = runtime, policy, next(e for e in policy.entries if e.local_date == '2026-11-11')
    authority.claim, authority.prepared, authority.baseline = {'attempt_id': 'a' * 32}, {}, t40
    authority.pilot_root, authority.check = tmp_path, lambda **kw: None
    from weather.market import lfc_cli
    monkeypatch.setattr(lfc_cli, 'session0_passed', lambda *a, **kw: True)
    # Before the native redemption is reconciled, the old start gate refuses.
    assert 'inventory_changed_after_baseline' in authority.start_gates(
        ledger=ledger, now=clock.now(), maker_address=MAKER, open_orders=[], positions=[])
    authority.refresh_go()
    assert authority.start_gates(ledger=ledger, now=clock.now(), maker_address=MAKER,
        open_orders=[], positions=[]) == ['unresolved_campaign_money']  # This isolated lot fixture is not enrolled.
    book = CapitalBook(ledger)
    assert book.anchor == anchor and authority.baseline == t40
    assert book.figures()['funding_native'] == 300_000_000
    assert book.figures()['segregated_profit_native'] == 13_000_000
    assert book.figures()['realized_principal_losses_native'] == 9_000_000
    assert len(calls) == (2 if gap else 1)


def test_twelve_band_setup_refreshes_go_evidence_after_realistic_mocked_latencies(tmp_path, monkeypatch, record_property):
    began = time.perf_counter()
    metrics = owner_runtime_fixture(tmp_path, monkeypatch, setup_latency=12)
    assert metrics['first_post_seconds'] >= 192
    assert 0 <= metrics['go_read_age_seconds'] < 120
    assert metrics['claims'] == 1 and metrics['incidents'] == [] and metrics['posts'] == 24
    for name, value in metrics.items():
        record_property(name, value)
    record_property('wall_seconds', time.perf_counter() - began)


def test_band_day_replay_index_reads_only_the_requested_market_and_day(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, k=12)
    original_rows, original_legs = ledger.rows, ledger.legs
    try:
        for band in controller.bands:
            ledger.intent(session_id=band.session_id, intent_key=band.session_id + ':index',
                condition_id=band.condition, token_id=band.tokens[0], price=str(band.prices[0]), size='20', fee_rate_bps='0')
        market = controller.bands[0].scope['market_id']
        day = clock.now().date().isoformat()
        expected = band_day_usage(ledger, market, day)
        class NoHistoryScan(list):
            def __iter__(self):
                raise AssertionError('whole_history_scan')
        class NoAllLegScan(dict):
            def items(self):
                raise AssertionError('all_legs_scan')
        ledger.rows, ledger.legs = NoHistoryScan(original_rows), NoAllLegScan(original_legs)
        assert band_day_usage(ledger, market, day) == expected
        assert band_day_usage(ledger, market, '2026-11-10')['resting_native'] == 0
        ledger.rows, ledger.legs = original_rows, original_legs
        replay = Ledger.open(ledger.path, clock=clock.now)
        assert band_day_usage(replay, market, day) == expected
    finally:
        ledger.rows, ledger.legs = original_rows, original_legs
        for band in controller.bands:
            band.journal.close()
        controller.journal.close()


def test_fresh_go_read_is_retained_hashed_and_missing_evidence_latches(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_state import StateRefused
    def audit(runtime, status, outcome, claim, proof):
        source = status.evidence_directory / 'go_account.json'
        assert source.is_file() and 'go_account.json' in outcome['evidence_sha256']
        runtime.save_result(claim, {'session_id': status.session_id,
            'private_evidence_directory': status.evidence_directory.name,
            'outcome': outcome, 'local_money_proof': proof})
        runtime.state.retained_result(claim)
        source.unlink()
        with pytest.raises(StateRefused, match='retained_private_evidence_fault'):
            runtime.state.retained_result(claim)
        assert runtime.state.incidents()
    owner_runtime_fixture(tmp_path, monkeypatch, audit=audit)


def test_setup_that_exhausts_start_window_never_posts_or_claims_another_date(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_state import StateRefused
    from tests.market.test_lfc_pilot import Clock
    with pytest.raises(StateRefused, match='start_window_expired'):
        owner_runtime_fixture(tmp_path, monkeypatch, setup_latency=60)
    ledger = Ledger.open(tmp_path / 'ledger.jsonl', clock=Clock().now)
    assert ledger.legs == {} and ledger.open_sessions() == []
    assert len(ledger.autostart_claims) == 1
    assert ledger.autostart_claims[0]['local_date'] == '2026-11-11'
