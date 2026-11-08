"""Guards: RECHECK2 placement certainty through real campaign ticks and closure.

Only in-memory venue/transport and generated native-evidence packets are used.
The actual coordinator, ledger, journals, result, postcheck and close paths run.
"""
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_breadth import cities, NOW
from tests.market.test_lfc_f2_capital import install
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from tests.market.test_lfc_f2_repost import FillingAccount, FundedRaw, fixture
from tests.market.test_lfc_pilot import Clock
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_capital_reads import read_activity
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import strict_json
from weather.market.mm_stage2_hold import HoldEnd


@pytest.mark.parametrize('transport', ['memory', 'owner_method'])
@pytest.mark.parametrize('fault,nth', [('intent_before_append', 1), ('intent_before_append', 2),
    ('checkpoint_fill', 1), ('signing', 2), ('post_response_lost', 1), ('post_response_lost', 2),
    ('intent_after_append', 1)])
def test_actual_tick_preserves_pre_post_vs_post_through_result_and_closure(tmp_path, monkeypatch, fault, nth, transport):
    with account_lease(MAKER, backend=Mutexes()):
        from tests.market import test_lfc_f2_controller as driver_fixture
        clock = Clock(NOW)
        row = example_policy()
        row.update(enabled=True, max_session_seconds=300, band_limit_session=2, band_limit_concurrent=2)
        policy = parse_policy(row)
        ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
        install(ledger, cash='300')
        state = AccountState(tmp_path / 'state', ledger)
        state.enroll(clock.now())
        runtime = object.__new__(Runtime)
        runtime.state, runtime.clock, runtime.pilot_root = state, clock, tmp_path
        runtime.sidecar, runtime.control_root = None, tmp_path / 'control'
        runtime.task_enabled = lambda: True
        runtime.notify_control = lambda row: None
        runtime.pre_go = lambda *args: {}
        @contextmanager
        def admission():
            runtime.lease = SimpleNamespace(check=lambda: None)
            try:
                yield
            finally:
                runtime.lease = None
        runtime.admission, runtime.lease = admission, None
        runs, results, real_posts = [], [], []
        def run_session(claim, entry, actual_policy, prepared):
            # Only the real tick creates the date claim. The fixture constructs
            # inert bands beneath that exact claim, without claiming twice.
            with monkeypatch.context() as patch:
                patch.setattr(state, 'claim', lambda *a, **k: claim)
                patch.setattr(driver_fixture, 'Clock', lambda base: clock)
                controller, account, status, current, _ = driver_fixture.setup(tmp_path,
                    k=2, offset=row['quote_offset_pusd'], policy_row=row, universe_rows=cities(),
                    shared_ledger=state.ledger, shared_state=state, enrolled=True,
                    account_type=FillingAccount, raw_type=FundedRaw)
            assert controller.policy.sha256 == actual_policy.sha256
            account.fills_enabled = False
            first, peer = controller.bands
            raw = account.raws[0]
            if transport == 'owner_method':
                from weather.market.re1_transport import OwnerVenue
                raw.readonly, raw.profile = False, first.profile
                raw.size, raw.tokens, raw.condition = first.size, first.tokens, first.condition
                raw.fields = {'SIGNATURE_TYPE': '3'}
                def synthetic_signed(**request):
                    size, price = Decimal(request['size']), Decimal(request['price'])
                    return SimpleNamespace(maker=MAKER, signer=MAKER, signature_type=3,
                        token_id=request['token_id'], side='BUY', order_type='GTD', post_only=True,
                        expiration=request['expiration'], taker_amount=int(size * 1_000_000),
                        maker_amount=int(size * price * 1_000_000), request=request)
                def actual_post_boundary(signed):
                    request = signed.request
                    oid = 'inert-sdk-order-' + str(len(raw.memory.orders) + 1)
                    raw.memory.orders[oid] = {'id': oid, 'asset_id': request['token_id'],
                        'market': raw.condition, 'maker_address': MAKER, 'side': 'BUY',
                        'price': request['price'], 'original_size': request['size'],
                        'size_matched': '0', 'status': 'LIVE', 'associate_trades': [],
                        'expiration': request['expiration']}
                    raw.calls.append(dict(request))
                    response = {'ok': True, 'order_id': oid, 'status': 'live', 'trade_ids': []}
                    real_posts.append(response)
                    if len(real_posts) == nth and fault == 'post_response_lost':
                        raise ConnectionError('synthetic_response_loss_inside_client_post_order')
                    return response
                raw.client = SimpleNamespace(create_limit_order=synthetic_signed,
                    get_order_book=lambda *, token_id: {'token_id': token_id, 'market': raw.condition,
                                                       'asks': [{'price': '.99'}]},
                    post_order=actual_post_boundary)
                monkeypatch.setattr(raw, 'submit', lambda request, *, checkpoint:
                                    OwnerVenue.submit(raw, request, checkpoint=checkpoint))
            submit, intent = raw.submit, current.intent
            attempts = []
            def submit_with_fault(*args, **kwargs):
                attempts.append(True)
                if len(attempts) == nth and fault in {'signing', 'checkpoint_fill'}:
                    if fault == 'checkpoint_fill':
                        raise HoldEnd('fill')
                    raise RuntimeError('synthetic_signing_refusal_before_callback')
                response = submit(*args, **kwargs)
                if transport == 'memory':
                    real_posts.append(response)
                    if len(attempts) == nth and fault == 'post_response_lost':
                        raise ConnectionError('synthetic_response_lost_after_actual_inert_POST')
                return response
            def intent_with_fault(**fields):
                match = fields['session_id'] == first.session_id and fields['intent_key'].endswith(':' + str(nth))
                if match and fault == 'intent_before_append':
                    raise OSError('synthetic_no_durable_intent')
                result = intent(**fields)
                if match and fault == 'intent_after_append':
                    raise OSError('synthetic_durable_intent_without_known_POST_result')
                return result
            monkeypatch.setattr(raw, 'submit', submit_with_fault)
            monkeypatch.setattr(current, 'intent', intent_with_fault)
            def read():
                when = clock.now().isoformat()
                return {'schema_version': 'lfc_campaign_account_read_v0.1', 'complete': True, 'errors': [],
                    'maker_address': MAKER, 'since': str(int(NOW.timestamp())),
                    'scope': 'account_wide_sdk_trades_and_f0_v2_positions',
                    'started_at_utc': when, 'ended_at_utc': when,
                    'component_times': {key: {'started_at_utc': when, 'ended_at_utc': when}
                        for key in ('open_orders', 'trades', 'positions', 'balances', 'geography')},
                    'open_orders': account.open_orders(), 'positions': [], 'trades': [],
                    'balances': raw.balances(), 'geography': {'blocked': False}, 'terminal_orders': {},
                    'capital_activity': native_packet(read_activity(MAKER, int(NOW.timestamp()),
                        int(clock.now().timestamp()), get=lambda *a: packet(), sleep=lambda _: None))}
            runtime.read_account = read
            controller.verify = lambda: runtime.core_proof(current, read())
            result = controller.run()
            outcome = status.finish(success=not result['unknown_submit'])
            result = runtime.session_result(claim, status, outcome, 0 if result['cleanup_ok'] else 1)
            runs.append((controller, account, first, peer))
            results.append(result)
            return result
        runtime.run_session = run_session
        campaign = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=runtime.control_root)
        assert not state.claims()
        assert campaign.tick(lambda: policy) == 'STARTED'
        assert len(state.claims()) == len(runs) == 1
        controller, account, first, peer = runs[0]
        ambiguous = fault in {'post_response_lost', 'intent_after_append'}
        assert results[0]['unknown_submit'] is ambiguous, results[0]
        if ambiguous:
            assert state.ledger.unacknowledged_intents() and state.incidents()
            assert state.pending() and peer.posts == 0
            assert len(real_posts) == (nth if fault == 'post_response_lost' else 0)
            assert any(row['reason'] == 'ambiguous_placement' for row in state.incidents())
        else:
            assert results[0]['local_money_proof']['complete'], results[0]
            assert not state.ledger.unacknowledged_intents() and not state.incidents() and not state.pending()
            assert first.posts == nth - 1 and peer.posts == 2
            assert len(real_posts) == nth - 1
            assert account.cancel_all_calls == [300]
        # The next scheduled tick must neither relatch a proved abort nor restart
        # an ambiguous POST, even after reopening all retained state.
        runtime.reload_ledger()
        campaign.tick(lambda: policy)
        assert len(runs) == len(state.claims()) == 1
        assert bool(state.incidents()) is ambiguous


@pytest.mark.parametrize('lag', [100, 115])
def test_legitimate_peer_fill_reconciled_before_cash_bound_does_not_retire_waiter(tmp_path, monkeypatch, lag):
    from copy import deepcopy
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=600)
    account.fills_enabled = False
    first, waiting = controller.bands
    peer_raw = account.raws[0]
    authorize = waiting.authorize_post
    order, events = peer_raw.order, peer_raw.events
    triggered = []
    def enter(*args, **kwargs):
        if not triggered:
            row = next(row for row in peer_raw.memory.orders.values() if row['status'] == 'LIVE')
            row.update(size_matched='1', associate_trades=['fill-' + row['id']])
            triggered.append(clock.seconds)
        return authorize(*args, **kwargs)
    def delayed_order(oid):
        row = deepcopy(order(oid))
        if triggered and clock.seconds - triggered[0] < lag:
            row.update(size_matched='0', associate_trades=[])
        return row
    monkeypatch.setattr(waiting, 'authorize_post', enter)
    monkeypatch.setattr(peer_raw, 'order', delayed_order)
    monkeypatch.setattr(peer_raw, 'events', lambda: [] if triggered and clock.seconds - triggered[0] < lag else events())
    result = controller.run()
    assert triggered and waiting.posts == 2, (result, controller.results)
    assert controller.results[waiting.session_id]['reason'] == 'fixed_end'
    assert account.cancel_all_calls == [600] and not result['unknown_submit']
    assert any(Decimal(leg['size_matched']) == 1 for leg in ledger.legs.values())
    rows = [strict_json(line) for line in waiting.journal.path.read_bytes().splitlines()]
    assert any(row['event'] == 'f2_peer_cash_wait' for row in rows)
    assert waiting.submits == 2  # Waiting never burns the ten-submit budget.
