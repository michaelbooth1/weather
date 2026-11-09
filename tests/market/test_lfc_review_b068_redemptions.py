"""Guards: B068 fixture coverage and boundaries of native redemption allocation."""
from copy import deepcopy
import json
import pytest
from tests.market.test_lfc_redemption_native import paired, word, event
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from weather.market.lfc_capital_native import cash_native
from weather.market.lfc_redemption_native import AUTO, AUTO_BINARY, AUTO_NEG, BATCH, CTF, PM, REDEEM, ZERO, positions


@pytest.mark.parametrize('kind', ['v2_direct', 'v2_auto', 'ctf_direct', 'ctf_auto_binary', 'ctf_auto_neg'])
def test_native_fixture_classes_allocate_each_position_and_exact_cash(kind):
    source, proof, tokens = paired(auto='auto' in kind, ctf=kind.startswith('ctf'))
    if kind == 'ctf_auto_neg':
        receipt = json.loads(proof['receipt']['raw_response'])['result']
        next(row for row in receipt['logs'] if row['topics'][0] == AUTO_BINARY)['topics'][0] = AUTO_NEG
        proof['receipt'] = rpc_packet(receipt)
    bundle = positions(source, proof)
    assert bundle is not None
    parts = {row['token_id']: row for row in bundle['positions']}
    assert set(parts) == set(tokens)
    assert [parts[token]['cash_native'] for token in tokens] == [20_000_000, 0]
    assert all(row['quantity'] == '20' for row in parts.values())
    assert cash_native(source, proof) == 20_000_000


@pytest.mark.parametrize('fault', ['no_receipt', 'no_historical_views', 'unrecognized_position_contract', 'missing_owner_marker'])
def test_unallocatable_redemption_never_gets_a_guessed_native_bundle(fault):
    source, proof, tokens = paired(auto=True, ctf=fault != 'unrecognized_position_contract')
    proof = deepcopy(proof)
    receipt = json.loads(proof['receipt']['raw_response'])['result']
    if fault == 'no_receipt':
        proof['receipt'] = rpc_packet(None)
    elif fault == 'no_historical_views':
        proof['ctf_views'] = {}
    else:
        if fault == 'unrecognized_position_contract':
            for row in receipt['logs']:
                if row['address'] == PM: row['address'] = '0x'+'e'*40
        else:
            receipt['logs'] = [row for row in receipt['logs'] if row['topics'][0] != AUTO_BINARY]
        proof['receipt'] = rpc_packet(receipt)
    assert positions(source, proof) is None
    assert cash_native(source, proof) is None


@pytest.mark.parametrize('auto', [False, True])
def test_ctf_intermediary_requires_the_native_auto_owner_binding(auto):
    from weather.market.lfc_session_driver import SPENDERS
    adapter = SPENDERS['neg_risk_adapter'].lower()
    source, proof, tokens = paired(auto=auto, ctf=True)
    receipt = json.loads(proof['receipt']['raw_response'])['result']
    logs = receipt['logs']
    # Synthetic ERC-1155/CTF intermediary flow, not an observed venue receipt.
    # Existing ABI event shapes only; no new adapter-event ABI is assumed.
    if auto:
        logs.insert(1, event(CTF, BATCH, [AUTO, AUTO, adapter],
            ['uint256[]', 'uint256[]'], [list(map(int, tokens)), [20_000_000]*2], 1))
        logs[2]['topics'][1:3] = [word(adapter), word(adapter)]
        next(row for row in logs if row['topics'][0] == AUTO_BINARY)['topics'][0] = AUTO_NEG
    else:
        logs[0]['topics'][3] = word(adapter)
        logs.insert(1, event(CTF, BATCH, [adapter, adapter, ZERO],
            ['uint256[]', 'uint256[]'], [list(map(int, tokens)), [20_000_000]*2], 1))
    next(row for row in logs if row['topics'][0] == REDEEM)['topics'][1] = word(adapter)
    for index, row in enumerate(logs): row['logIndex'] = hex(index)
    proof['receipt'] = rpc_packet(receipt)
    bundle = positions(source, proof)
    assert (bundle is not None) is auto
    if auto:
        assert {row['token_id']: row['cash_native'] for row in bundle['positions']} == {tokens[0]: 20_000_000, tokens[1]: 0}
    else:
        assert cash_native(source, proof) is None
