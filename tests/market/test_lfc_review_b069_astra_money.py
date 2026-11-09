"""Guards: B066 uncertainty ordering and campaign-only reward ownership.

Native receipts and balances are generated; no owner records are read.
"""
import pytest
import json
import uuid
from pathlib import Path
from tests.market.test_lfc_review_b060_refill import settled_pair, transfer, BASES
from tests.market.test_lfc_review_b066_incoming import incoming, resolve
from tests.market.test_lfc_campaign import MAKER, Mutexes
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_capital import CapitalBook, CapitalRefused, native, pusd
from weather.market.lfc_ledger import Ledger, LedgerUnavailable


@pytest.fixture(autouse=True)
def isolated():
    with account_lease(MAKER,backend=Mutexes()):yield




@pytest.mark.parametrize('kind',['REWARD','MAKER_REBATE'])
def test_shared_owner_condition_is_not_campaign_only_income_proof(tmp_path,kind):
    # Half of the redeemed winning token was separately recorded as owner
    # inventory in the original baseline. A condition label cannot allocate
    # this wallet-wide payment between the owner's and the campaign's activity.
    ledger,*_=settled_pair(tmp_path,'net_of_retained_gains',winner_size='10',wallet='1000')
    before=CapitalBook(ledger).figures()
    assert before['headroom_native']==native('295.6')
    incoming(ledger,kind=kind,amount='100',campaign=True,nonce=70,missing=False)
    book=CapitalBook(ledger);observed=book.figures()
    output=tmp_path/('r6-income-attribution-'+uuid.uuid4().hex)
    output.mkdir()
    (output/'observed.json').write_text(json.dumps({'kind':kind,'before':before,'after':observed},sort_keys=True))
    (output/'ledger.jsonl').write_bytes(ledger.path.read_bytes())
    # Native proof proves receipt of cash, not exclusive campaign attribution.
    assert observed['proven_campaign_paid_incentives_native']==0, {
        'unallocated_paid_income':observed['proven_campaign_paid_incentives_native'],
        'before_headroom':before['headroom_native'],'after_headroom':observed['headroom_native']}
    with pytest.raises(CapitalRefused,match='capital_total_ceiling'):
        book.gate(reserve='300',available_cash=pusd(book.expected_cash()))
