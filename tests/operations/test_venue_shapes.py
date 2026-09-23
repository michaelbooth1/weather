import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'fixtures/venue_shapes'


def credential_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if any(term in key.lower() for term in ('owner', 'key', 'secret', 'credential', 'auth', 'signature', 'passphrase', 'password')):
                yield key
            yield from credential_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from credential_keys(child)


@pytest.mark.parametrize('path', sorted(ROOT.glob('*.json')), ids=lambda path: path.stem)
def test_venue_fixture_contains_no_credential_named_key(path):
    assert not list(credential_keys(json.loads(path.read_text())))


@pytest.mark.parametrize('alias', ['asset_id', 'token_id'])
def test_confirmed_complementary_relationship(alias):
    value = json.loads((ROOT / f'complementary_trade_{alias}.json').read_text())
    assert value['outcome'] == 'Yes'
    assert all(row[alias] != value[alias] and row['outcome'] == 'No' for row in value['maker_orders'])
    assert [row['matched_amount'] for row in value['maker_orders']] == ['20', '5.57']


@pytest.mark.parametrize('alias', ['asset_id', 'token_id'])
def test_confirmed_shape_reaches_frozen_re1_fill_normalizer(alias, tmp_path):
    from weather.market.re1_attended import SecretGuard
    from weather.market.re1_transport import PairStream
    value = json.loads((ROOT / f'complementary_trade_{alias}.json').read_text())
    value['event_type'] = 'trade'
    reader = PairStream(tokens=['1001', '1002'], guard=SecretGuard([]),
                        maker_address='0x' + '2' * 40, condition_id=value['market'],
                        api_key='fixture', secret='fixture', passphrase='fixture',
                        journal_path=tmp_path / 'stream.jsonl', known_order_ids={'redacted-our-order'})
    result = reader._normalize_event(value)
    assert len(result) == 1
    assert result[0]['order_id'] == 'redacted-our-order'
    assert result[0]['clob_token_id'] == '1002'
    assert result[0]['fill_size'] == '5.57'
