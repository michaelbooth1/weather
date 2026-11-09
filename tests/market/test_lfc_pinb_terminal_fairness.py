"""Guards: B074 fair terminal probes and prompt peer cancellation at teardown."""
from decimal import Decimal
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_controller import setup, NOW
from tests.market.test_lfc_pilot import Clock
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_f2_controller import F2Band


def terminal_band(*, old_terminal, live=False):
    band = object.__new__(F2Band)
    band.clock = Clock(NOW); band.size = Decimal(20)
    band.known = {'old': (0, Decimal('.3')), 'new': (1, Decimal('.6'))}
    band.ledger = SimpleNamespace(by_order={'old': 'old', 'new': 'new'}, legs={
        'old': {'status': 'terminal' if old_terminal else 'acknowledged'},
        'new': {'status': 'acknowledged'}})
    band._terminal_order_deadline = None
    band.progress = lambda: None
    band._retain = lambda *a, **k: None
    calls = []
    def read(oid):
        calls.append((oid, band.clock.seconds))
        if oid == 'old' and not live:
            raise TimeoutError('synthetic old order unavailable')
        return {'id': oid, 'status': 'LIVE' if oid == 'old' else 'CANCELED',
                'size_matched': '0', 'original_size': '20'}
    band.venue = SimpleNamespace(order=read)
    return band, calls


@pytest.mark.parametrize('live', [False, True])
def test_already_terminal_leg_gets_one_attempt_without_spending_new_leg_budget(live):
    band, calls = terminal_band(old_terminal=True, live=live)
    with pytest.raises(TimeoutError): band.terminal_order_read('old', None)
    assert band.clock.seconds == 0 and [oid for oid, _ in calls].count('old') == 1
    assert band.terminal_order_read('new', None)['id'] == 'new'
    assert [oid for oid, _ in calls].count('new') == 1


def test_every_known_order_is_probed_even_when_one_new_leg_uses_the_retry_budget():
    band, calls = terminal_band(old_terminal=False)
    with pytest.raises(TimeoutError): band.terminal_order_read('old', None)
    assert band.clock.seconds == 10
    assert band.terminal_order_read('new', None)['id'] == 'new'
    assert ('new', 0) in calls
    assert not any(at >= 10 for _, at in calls)


@pytest.mark.parametrize('band_failure', [False, True])
def test_final_teardown_does_not_spend_repost_retry_time_before_peer_cancel(tmp_path, band_failure):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock = setup(tmp_path)
        if band_failure:
            from types import MethodType
            def failing(self, **kwargs):
                for leg in self.TRADE_LEGS:
                    yield from self.submit_steps(leg, self.prices[leg])
                yield 5
                raise RuntimeError('synthetic band failure')
            controller.bands[0].quote_steps = MethodType(failing, controller.bands[0])
        else:
            account.stop_at = 5
        raw = account.raws[0]; ordinary = raw.order
        def order(oid):
            if clock.seconds >= 5:
                raise TimeoutError('synthetic final read outage')
            return ordinary(oid)
        raw.order = order
        result = controller.run()
        assert not result['unknown_submit'] and not result['cleanup_ok']
        assert raw.cancellations and account.raws[1].cancellations
        assert account.raws[1].cancellations[0][0] == raw.cancellations[0][0] == 5
        assert not account.open_orders() and ledger.unresolved_legs()
