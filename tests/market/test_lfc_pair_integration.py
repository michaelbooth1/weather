"""Guards: T113 canonical inventory and the actual guarded cooperative B path.

Only inert venue/account fixtures run here; no SDK, signer, network or task.
"""
from copy import deepcopy
from decimal import Decimal as D

import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_f2_repost import fixture, wire_trade
from weather.market.lfc_campaign_policy import PolicyRefused, parse_policy
from weather.market.lfc_f2_freeze import economic_digest
from weather.market.lfc_pair_policy import successor_row
from weather.market.lfc_pair_runtime import initialize, refresh_from_read
from weather.market.lfc_recording_io import strict_json


def complete_fixture(tmp_path, *, seconds=300, cheap=False, bounds=None):
    row = successor_row(parse_policy(pinb_row()))
    if cheap:
        row['learning_leg_arms'] = ['cheap']
    if bounds is not None:
        row['leg_price_range'] = bounds
    controller, account, status, ledger, clock, runtime, read = fixture(
        tmp_path, policy_row=row, seconds=seconds)
    # The ordinary fixture omits match clocks. Real SDK records retain matched_at.
    for raw in account.raws:
        def trades(raw=raw):
            return [wire_trade(order, raw.memory.condition) | {'matched_at':
                    (clock.base).isoformat()} for order in raw.memory.orders.values()
                    if D(order['size_matched'])]
        raw.trades = trades
    return controller, account, status, ledger, clock, runtime, read


def journal(band):
    return [strict_json(line) for line in band.journal.path.read_bytes().splitlines()]


def test_parser_and_economic_digest_retain_continue_identity_and_distinguish_b():
    old = parse_policy(pinb_row())
    explicit = parse_policy(old.raw | {'post_fill_mode': 'continue'})
    new = parse_policy(successor_row(old))
    assert old.raw == pinb_row() and 'post_fill_mode' not in old.raw
    assert economic_digest(old) == economic_digest(explicit)
    assert economic_digest(new) != economic_digest(old)
    for invalid in (None, 'COMPLETE_PAIRS', [], False):
        with pytest.raises(PolicyRefused, match='unsupported_post_fill_mode'):
            parse_policy(old.raw | {'post_fill_mode': invalid})
    with pytest.raises(PolicyRefused, match='complete_pairs_requires_policy_revision_6'):
        parse_policy(old.raw | {'post_fill_mode': 'complete_pairs'})


def test_actual_controller_completes_then_returns_flat_with_locked_pair_evidence(tmp_path):
    controller, account, _, ledger, _, _, _ = complete_fixture(tmp_path, seconds=300)
    result = controller.run()
    band = controller.bands[0]
    rows = journal(band)
    assert result['cleanup_ok'], result
    completions = [row for row in rows if row['event'] == 'pair_completion_order']
    assert completions and all(row['completion_leg'] == 1 for row in completions)
    assert any(row['event'] == 'pair_completion_exited' for row in rows)
    allocations = [pair for row in rows if row['event'] == 'pair_completion_inventory'
                   for pair in row['pair_allocations']]
    assert allocations and all(D(pair['margin_per_share']) >= D('.015') for pair in allocations)
    assert not ledger.unresolved_legs()


@pytest.mark.parametrize('stop', ['fixed_end', 'owner_stop', 'submit_budget', 'cap', 'geoblock'])
def test_completion_wait_keeps_cooldown_cleanup_end_and_all_gate_refusals(tmp_path, stop):
    controller, account, _, ledger, clock, _, _ = complete_fixture(tmp_path, seconds=300)
    band, raw = controller.bands[0], account.raws[0]
    # A completion below the existing lower bound must wait, not POST.
    ordinary = band.observe_snapshot
    def observe(snapshot):
        if clock.seconds >= 12 and stop == 'fixed_end':
            band.LEG_PRICE_RANGE = (D('.79'), D('.80'))
        return ordinary(snapshot)
    band.observe_snapshot = observe
    if stop == 'owner_stop':
        account.stop_at = 30
    if stop == 'submit_budget':
        band.MAX_SUBMITS = 2
    if stop == 'cap':
        authorize = band.authorize_post
        def cap(*args):
            if clock.seconds >= 60:
                from weather.market.mm_stage2_hold import HoldEnd
                raise HoldEnd('per_band_daily_filled_cap')
            return authorize(*args)
        band.authorize_post = cap
    if stop == 'geoblock':
        ordinary_geo = raw.geography
        raw.geography = lambda: {'blocked': True} if clock.seconds >= 30 else ordinary_geo()
    result = controller.run()
    expected = 'per_band_daily_filled_cap' if stop == 'cap' else stop
    assert controller.results[band.session_id]['reason'] == expected, controller.results[band.session_id]
    assert band.submits == 2 and not ledger.unresolved_legs(), result
    rows = journal(band)
    if stop == 'fixed_end':
        assert any(row['event'] == 'pair_completion_paused' for row in rows)
        assert any(row['event'] == 'repost_cooldown' for row in rows)
    assert not [row for row in rows if row['event'] == 'pair_completion_order']


def test_cheap_arm_quotes_expensive_complement_and_restores_original_arm_when_flat(tmp_path):
    controller, account, status, ledger, _, _, _ = complete_fixture(tmp_path, seconds=300, cheap=True)
    band = controller.bands[0]
    original = tuple(band.TRADE_LEGS)
    result = controller.run()
    rows = journal(band)
    assert result['cleanup_ok'], result
    orders = [row for row in rows if row['event'] == 'pair_completion_order']
    assert orders and orders[0]['completion_leg'] == 1-original[0]
    assert any(row['event'] == 'pair_completion_inventory' and row['u'] == '0' and
               row['effective_trade_legs'] == list(original) for row in rows)
    assert band.normal_trade_legs == original and band.scope['trade_legs'] == list(original)
    from weather.market.lfc_campaign_proof import local_money_proof
    outcome = status.finish(success=True)
    proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id='a'*32, outcome=outcome)
    assert proof['complete'] and not proof['unknown_submit']


def test_actual_partial_fill_full_completion_flips_and_quotes_only_new_complement(tmp_path):
    controller, account, _, ledger, _, _, _ = complete_fixture(tmp_path, seconds=600)
    advance = account.advance
    def partial_then_full():
        if len(account.fill_times) >= 2:
            account.fills_enabled = False
        changed = None
        if not account.fill_times and account.raws and account.clock.seconds >= account.next_fill:
            orders = [row for row in account.raws[0].memory.orders.values() if row['status'] == 'LIVE']
            if orders:
                changed = orders[0]
                changed['original_size'] = '5.31'
        advance()
        if changed is not None:
            changed['original_size'] = '20'
    account.advance = partial_then_full
    result = controller.run()
    band = controller.bands[0]
    assert result['cleanup_ok'], result
    assert band.pair_state.u == D('-14.69') and len(band.pair_state.flips) == 1
    assert band.TRADE_LEGS == (0,) and not ledger.unresolved_legs()
    assert [row['completion_leg'] for row in journal(band) if row['event'] == 'pair_completion_order'] == [1, 0]


def test_completion_requires_fresh_full_inventory_proof_before_posting(tmp_path):
    controller, account, _, ledger, _, _, _ = complete_fixture(tmp_path)
    controller.repost_proof = lambda band: {'inventory_proven': False, 'unknown_submit': False}
    result = controller.run()
    band = controller.bands[0]
    assert band.submits == 2 and not ledger.unresolved_legs()
    assert controller.results[band.session_id]['reason'] == 'repost_inventory_unproven', result
    assert band.pair_state.u == 20  # Final cleanup evidence may describe U; never grants a post.


def test_price_pause_without_new_fill_rechecks_books_after_60_seconds_without_another_cooldown(tmp_path):
    controller, account, _, _, clock, _, _ = complete_fixture(tmp_path, seconds=600, bounds=['.20', '.75'])
    band, raw = controller.bands[0], account.raws[0]
    advance = account.advance
    def only_first():
        if account.fill_times:
            account.fills_enabled = False
        advance()
    account.advance = only_first
    ordinary = raw.snapshot
    def snapshot(condition, tokens, *, checkpoint=lambda: None):
        result = ordinary(condition, tokens, checkpoint=checkpoint)
        if 90 <= clock.seconds < 180:
            result = deepcopy(result)
            # The ordinary midpoint/depth screens still pass. The normal NO
            # quote falls below this policy's .20 bound, then books recover.
            for side, price in [('yes_bids', '.79'), ('yes_asks', '.80'),
                                ('no_bids', '.20'), ('no_asks', '.21')]:
                result['quote_inputs'][side] = [{'price': price, 'size': '100'}]
        return result
    raw.snapshot = snapshot
    result = controller.run()
    assert result['cleanup_ok'], result
    rows = journal(band)
    paused = next(row for row in rows if row['event'] == 'pair_completion_paused')
    orders = [row for row in rows if row['event'] == 'pair_completion_order']
    assert len(orders) == 2 and all(row['completion_leg'] == 1 for row in orders)
    from datetime import datetime
    delay = (datetime.fromisoformat(orders[1]['recorded_at_utc']) -
             datetime.fromisoformat(paused['recorded_at_utc'])).total_seconds()
    assert 60 <= delay <= 62  # A second fill cooldown would incorrectly make this 120 seconds.


def test_fill_pending_never_moves_inventory_and_k1_still_observes_canonical_completion(tmp_path):
    controller, account, _, _, _, _, _ = complete_fixture(tmp_path)
    band = controller.bands[0]
    captured = []
    controller.post_books = type('Recorder', (), {'watch': lambda self, b, trigger: captured.append(trigger),
                                                 'start': lambda self: None,
                                                 'stop': lambda self: None})()
    band.record_fill(order={'id': 'signal-only', 'size_matched': '20'})
    assert band.pair_state.u == 0 and journal(band)[-1]['event'] == 'fill_pending'
    controller.run()
    assert 'fill' in captured
    assert any(row['event'] == 'pair_completion_fill' for row in journal(band))


def test_recovery_rebuilds_nonzero_u_from_canonical_trades_and_held_lots(tmp_path):
    controller, account, _, ledger, clock, _, read = complete_fixture(tmp_path, seconds=300)
    advance = account.advance
    def only_first():
        if account.fill_times:
            account.fills_enabled = False
        advance()
    account.advance = only_first
    controller.run()
    band = controller.bands[0]
    expected = band.pair_state
    assert expected.completing
    # A new memory projection cannot treat retained campaign lots as flat.
    band.journal = type('Sink', (), {'record': lambda *a, **k: None})()
    band.TRADE_LEGS = band.normal_trade_legs
    initialize(band)
    assert band.pair_state is None
    refresh_from_read(band, read())
    assert band.pair_state == expected and band.TRADE_LEGS == (expected.completion_leg,)


def test_claim_accepts_new_revision_and_refuses_omitted_mode_rollback_at_same_revision(tmp_path):
    from tests.market.test_lfc_pinb_migration import existing_pina, stamp
    from tests.market.test_lfc_campaign import Mutexes, MAKER
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_campaign_recovery import close_empty
    from weather.market.lfc_campaign_state import StateRefused
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, _, _ = existing_pina(tmp_path)
        old = parse_policy(pinb_row())
        clock.value = stamp('2026-11-16T14:00:00Z')
        claim = state.claim(next(e for e in old.entries if e.local_date == '2026-11-16'), old, clock.now())
        close_empty(state, claim, clock.now())
        new = parse_policy(successor_row(old))
        clock.value = stamp('2026-11-17T14:00:00Z')
        claim = state.claim(next(e for e in new.entries if e.local_date == '2026-11-17'), new, clock.now())
        close_empty(state, claim, clock.now())
        rollback = deepcopy(new.raw)
        del rollback['post_fill_mode']
        rollback = parse_policy(rollback)
        clock.value = stamp('2026-11-18T14:00:00Z')
        with pytest.raises(StateRefused, match='economic_policy_change_requires_revision'):
            state.claim(next(e for e in rollback.entries if e.local_date == '2026-11-18'), rollback, clock.now())


def test_freeze_distinguishes_complete_pairs_and_keeps_historical_continue_bytes(tmp_path):
    from tests.market.test_lfc_pinb_migration import existing_pina, stamp
    from tests.market.test_lfc_campaign import Mutexes, MAKER
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_f2_freeze import capture, labels
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, _, _ = existing_pina(tmp_path)
        old = parse_policy(pinb_row())
        clock.value = stamp('2026-11-22T22:55:00Z')
        capture(state, old, clock.now())
        path = state.root/'policies'/'freeze-pinb.json'
        original = path.read_bytes()
        assert labels(state, parse_policy(old.raw | {'post_fill_mode': 'continue'}), '2026-11-23')['evidence_lane'] == 'confirmation'
        assert labels(state, parse_policy(successor_row(old)), '2026-11-23')['evidence_lane'] == 'successor_learning'
        assert path.read_bytes() == original


def test_explicit_and_omitted_continue_keep_the_same_order_and_evidence_trace(tmp_path):
    traces = []
    for name, extra in [('omitted', {}), ('explicit', {'post_fill_mode': 'continue'})]:
        controller, account, _, _, _, _, _ = fixture(tmp_path/name, policy_row=pinb_row() | extra)
        result = controller.run()
        traces.append((result['reason'], account.fill_times,
            [(b.submits, b.requotes, b.TRADE_LEGS, [row['event'] for row in journal(b)]) for b in controller.bands],
            [[(row['asset_id'], row['price'], row['size_matched'], row['status'])
              for row in raw.memory.orders.values()] for raw in account.raws]))
        assert all('post_fill_mode' not in b.scope and not hasattr(b, 'pair_state') for b in controller.bands)
        assert all(not any(row['event'].startswith('pair_completion') for row in journal(b)) for b in controller.bands)
    assert traces[0] == traces[1]
