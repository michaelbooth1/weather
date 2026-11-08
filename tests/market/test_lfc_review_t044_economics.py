"""Independent T044 desired-behavior witnesses.

Guards: retained campaign evidence.

All inputs are synthetic. No account, venue, credential, reader or Scheduler call.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_capital import ledger_at, install, filled
from tests.market.test_lfc_f2_revision import setup
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_capital import CapitalBook, record_activity
from weather.market.lfc_f2_economics import measured
from weather.market.lfc_f2_final import snapshot
from weather.market.lfc_f2_freeze import capture, verify
from weather.market.lfc_recording_io import file_sha


@pytest.fixture(autouse=True)
def account_guard():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def test_mixed_owner_campaign_redemption_reports_only_campaign_payout(tmp_path):
    from tests.market.test_lfc_redemption_native import paired
    from weather.market.lfc_ledger import take_baseline, write_baseline
    from weather.market.mm_stage2_hold import digest
    row, proof, tokens = paired()
    ledger = ledger_at(tmp_path)
    # Campaign holds 20 winning shares and the owner already holds 20 of the
    # SAME fungible token. Native bundle pays 20 for 40 shares at 50%.
    from tests.market.test_lfc_redemption_native import ctf_calls, word
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    from eth_abi import encode
    row, proof, tokens = paired(ctf=True)
    raw = json.loads(proof['receipt']['raw_response'])['result']
    raw['logs'][0]['data'] = '0x' + encode(['uint256[]', 'uint256[]'], [list(map(int, tokens)), [40_000_000, 0]]).hex()
    calls = ctf_calls(row['condition_id'])
    proof['ctf_views'].update({calls[0]: rpc_packet(word(2)), calls[2]: rpc_packet(word(1))})
    proof['receipt'] = rpc_packet(raw)
    row.update(token_id=tokens[0], size=40.0)
    proof.update(rows=[row], rows_sha256=digest([row]))
    filled(ledger, 'campaign', token=tokens[0], condition=row['condition_id'], price='.4')
    baseline = take_baseline(label='t40', now=ledger.clock(), maker_address=MAKER,
        positions=[{'asset': tokens[0], 'conditionId': row['condition_id'], 'size': '40'}],
        open_orders=[], available_collateral='292')
    write_baseline(tmp_path, baseline, ledger)
    ledger.record('capital_anchor', baseline=baseline, baseline_sha256=digest(baseline))
    install(ledger, cash='292')
    record_activity(ledger, row, native_evidence=proof)
    book = CapitalBook(ledger)
    assert book.external == 10_000_000 and book.profit == 2_000_000
    assert book.returned_principal == 8_000_000  # Money rail segregates correctly.
    report = measured(ledger, ['campaign'])
    assert report['settlement']['redemptions'][0]['session_cash_native'] == 10_000_000, report['settlement']
    assert report['settlement']['redemptions'][0]['exclusive_session_scope'] is False
    assert report['settlement']['redemptions'][0]['session_allocation_intent_keys'] == ['campaign']
