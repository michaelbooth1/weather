"""Synthetic SDK observation rebinding and known-identity cleanup read outages.

Guards: B036 account cleanup independent of closed band journals; R2 typed GET gaps.
"""
from types import SimpleNamespace

import httpx
import pytest

from tests.market.test_lfc_f2_controller import setup
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.re1_transport import OwnerVenue


def test_sdk_observation_hooks_rebind_after_old_journal_closes_without_duplicating():
    old, new = [], []
    closed = False
    def first(event, **fields):
        if closed:
            raise ValueError('fixture old journal closed')
        old.append(event)
    http = httpx.Client(base_url='https://clob.polymarket.com',
                        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={'id': 'fixture-read'})))
    venue = object.__new__(OwnerVenue)
    venue.client = SimpleNamespace(_ctx=SimpleNamespace(secure_clob=SimpleNamespace(_client=http)))
    venue.journal_failed = False
    try:
        venue.set_journal(SimpleNamespace(record=first))
        assert http.get('/data/order/fixture').status_code == 200
        closed = True
        venue.set_journal(SimpleNamespace(record=lambda event, **fields: new.append(event)))
        assert http.get('/data/order/fixture').status_code == 200
        assert old == new == ['sdk_request', 'sdk_response']
        assert len(http.event_hooks['request']) == len(http.event_hooks['response']) == 1
        assert venue.journal_failed is False
    finally:
        http.close()


def test_final_account_read_outage_stays_pending_with_retained_private_proof(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    def unavailable():
        raise TimeoutError('synthetic final account read outage')
    controller.verify = unavailable
    result = controller.run()
    assert result['unknown_submit'] is False and not result['inventory_proven'] and not result['cleanup_ok']
    assert account.cancel_all_calls and account.open_orders() == []
    outcome = status.finish(success=False)
    proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id=controller.attempt_id, outcome=outcome)
    assert proof['complete'] and not proof['unknown_submit'], proof
    assert 'f2_account_read_unavailable' in proof['money_read_gaps']
    # Missing a core journal remains a physical evidence fault; the typed GET
    # outage cannot excuse it.
    (controller.bands[0].directory / 'journal.jsonl').unlink()
    assert not local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                attempt_id=controller.attempt_id, outcome=outcome)['complete']
