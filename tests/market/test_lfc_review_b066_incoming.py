"""Guards: B066 amount-local quarantine, proven campaign income and the 300 sleeve."""
from copy import deepcopy
from datetime import timedelta
import pytest

from tests.market.test_lfc_review_b060_refill import settled_pair, BASES
from tests.market.test_lfc_f2_capital import NOW, MAKER, filled, activity
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from tests.market.test_lfc_f2_native import log, BLOCK
from tests.market.test_lfc_campaign import Mutexes
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_capital import CapitalBook, CapitalRefused, native, pusd, record_activity
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.mm_stage2_hold import digest


@pytest.fixture(autouse=True)
def guarded():
    with account_lease(MAKER,backend=Mutexes()):yield


def incoming(ledger, *, kind='REWARD', amount='5', campaign=False, nonce=70, missing=True):
    tx='0x'+f'{nonce:064x}'
    source=activity(cash=amount,size='0',kind=kind,tx=tx)
    source['timestamp']+=nonce
    if campaign:source['condition_id']=next(iter(CapitalBook(ledger).lots.values()))['condition_id']
    entry=log(native(amount));entry['transactionHash']=tx
    if kind=='WITHDRAWAL':
        entry=log(native(amount),sender=MAKER,receiver='0x'+'c'*40);entry['transactionHash']=tx
    receipt={'transactionHash':tx,'blockHash':BLOCK,'blockNumber':'0x123','status':'0x1','logs':[entry]}
    proof={'transaction_hash':tx,'rows':[source],'rows_sha256':digest([source]),
           'receipt':rpc_packet(receipt),'failure_type':None}
    ledger.clock=lambda:NOW+timedelta(seconds=nonce)
    record_activity(ledger,source,native_evidence={**proof,'receipt':rpc_packet(None)} if missing else proof)
    return source,proof


def resolve(ledger,source,proof):
    book=CapitalBook(ledger);identity=next(k for k,a in book.activities.items()
        if book.activity_transactions[k]==source['transaction_hash'])
    return ledger.record('capital_resolution',source=source,source_sha256=digest(source),
        previous_source_sha256=book.sources[identity],native_evidence=proof)


@pytest.mark.parametrize('basis',BASES)
@pytest.mark.parametrize('kind',['REWARD','DEPOSIT'])
def test_unknown_incoming_preserves_only_previously_proven_gains(tmp_path,basis,kind):
    ledger,*_=settled_pair(tmp_path,basis)
    incoming(ledger,kind=kind)
    book=CapitalBook(ledger);row=book.figures()
    assert row['retained_gains_available_native']==10_400_000
    assert row['unknown_cash_held_native']==5_000_000
    assert 'unknown_incoming_excluded' in row['retained_gains_reason_codes']
    assert row['headroom_native']==(300_000_000 if basis!='gross' else 290_400_000)


@pytest.mark.parametrize('basis',BASES)
def test_unknown_owner_deposit_never_becomes_gain_after_proof_or_reopen(tmp_path,basis):
    ledger,*_=settled_pair(tmp_path,basis)
    source,proof=incoming(ledger,kind='DEPOSIT',campaign=True)
    before=CapitalBook(ledger).figures()['proven_campaign_profit_cumulative_native']
    resolve(ledger,source,proof)
    for view in (ledger,Ledger.open(ledger.path,clock=ledger.clock)):
        book=CapitalBook(view);row=book.figures()
        assert row['proven_campaign_profit_cumulative_native']==before==10_400_000
        assert row['retained_gains_available_native']==before
        assert not row['unknown_payouts']
        with pytest.raises(CapitalRefused,match='capital_total_ceiling'):book.gate(reserve='300.000001',available_cash='2000')


@pytest.mark.parametrize('basis',BASES)
def test_campaign_reward_requires_native_proof_and_is_credited_once(tmp_path,basis):
    """B068: native cash alone is not complete earning-order attribution."""
    ledger,*_=settled_pair(tmp_path,basis,winner=False)
    source,proof=incoming(ledger,campaign=True)
    assert CapitalBook(ledger).figures()['retained_gains_available_native']==0
    resolve(ledger,source,proof)
    for view in (ledger,Ledger.open(ledger.path,clock=ledger.clock)):
        row=CapitalBook(view).figures()
        assert row['proven_campaign_profit_cumulative_native']==0
        assert row['retained_gains_available_native']==0
        assert row['headroom_native']==290_400_000
        assert 'reward_attribution_unproven' in row['retained_gains_reason_codes']
    with pytest.raises((CapitalRefused,LedgerUnavailable),match='capital_resolution_scope'):resolve(ledger,source,proof)
    assert CapitalBook(ledger).figures()['proven_campaign_profit_cumulative_native']==0


def test_unknown_outgoing_still_zeros_offset_and_refuses_post(tmp_path):
    ledger,*_=settled_pair(tmp_path,'net_of_retained_gains')
    incoming(ledger,kind='WITHDRAWAL')
    book=CapitalBook(ledger);row=book.figures()
    assert row['retained_gains_available_native']==0
    assert 'unknown_outgoing_cash' in row['retained_gains_reason_codes']
    with pytest.raises(CapitalRefused,match='capital_unknown_outgoing_cost'):book.gate(reserve='1')


def test_unknown_campaign_redemption_still_zeros_offset(tmp_path):
    ledger,*_=settled_pair(tmp_path,'net_of_retained_gains')
    filled(ledger,'pending',token='pending',condition='pending')
    source=activity(cash='10',token='pending',tx='0x'+'e'*64);source['condition_id']='pending'
    proof={'transaction_hash':source['transaction_hash'],'rows':[source],'rows_sha256':digest([source]),
           'receipt':rpc_packet(None),'failure_type':None}
    record_activity(ledger,source,native_evidence=proof)
    row=CapitalBook(ledger).figures()
    assert row['retained_gains_available_native']==0
    assert 'unknown_campaign_redemption' in row['retained_gains_reason_codes']


def test_cash_only_redemption_resolution_remains_unknown_until_lot_allocation_is_proved(tmp_path):
    ledger,*_=settled_pair(tmp_path,'net_of_retained_gains')
    filled(ledger,'pending',token='pending',condition='pending')
    ledger.clock=lambda:NOW+timedelta(seconds=71)
    source=activity(cash='5',token='pending',tx='0x'+'f'*64)
    source.update(condition_id='pending',timestamp=int(ledger.clock().timestamp()))
    receipt={'transactionHash':source['transaction_hash'],'blockHash':BLOCK,'blockNumber':'0x123','status':'0x1',
        'logs':[{**log(native('5')),'transactionHash':source['transaction_hash']}]}
    proof={'transaction_hash':source['transaction_hash'],'rows':[source],'rows_sha256':digest([source]),
        'receipt':rpc_packet(receipt),'failure_type':None}
    record_activity(ledger,source,native_evidence={**proof,'receipt':rpc_packet(None)})
    resolve(ledger,source,proof)
    book=CapitalBook(ledger)
    assert any(a['condition_id']=='pending' for k,a in book.activities.items() if k in book.unknown)
    assert book.figures()['retained_gains_available_native']==0


def test_owner_deposit_cannot_be_relabelled_to_campaign_reward(tmp_path):
    ledger,*_=settled_pair(tmp_path,'net_of_retained_gains')
    source,proof=incoming(ledger,kind='DEPOSIT',campaign=True)
    changed={**source,'type':'REWARD'};proof={**proof,'rows':[changed],'rows_sha256':digest([changed])}
    with pytest.raises((CapitalRefused,LedgerUnavailable),match='capital_resolution_scope'):resolve(ledger,changed,proof)
    assert CapitalBook(ledger).figures()['proven_campaign_profit_cumulative_native']==10_400_000


@pytest.mark.parametrize('basis',BASES)
def test_unknown_incoming_cannot_expand_principal_risk_with_parallel_bands(tmp_path,basis):
    ledger,*_=settled_pair(tmp_path,basis)
    for i in range(13):
        filled(ledger,'carried-'+str(i),price='.50',token='carry-'+str(i),condition='old-'+str(i))
    incoming(ledger,kind='DEPOSIT',amount='1000')
    refused=False
    for i in range(12):
        sid='band-'+str(i);ledger.record('session_start',session_id=sid,counted=False)
        try:ledger.intent(session_id=sid,intent_key=sid,token_id=str(i),condition_id=sid,price='.79',size='20',fee_rate_bps='0')
        except CapitalRefused as exc:
            assert str(exc)=='capital_total_ceiling'
            refused=True
            break
        row=CapitalBook(ledger).figures()
        assert row['unrecovered_inventory_cost_native']+row['resting_reserve_native']<=300_000_000
        assert row['charged_native']<=300_000_000
    assert refused, 'Carried inventory plus twelve peer reserves must exhaust the sleeve'


@pytest.mark.parametrize('kind',['REWARD','MAKER_REBATE','YIELD','DEPOSIT'])
@pytest.mark.parametrize('campaign',[False,True])
def test_native_income_still_requires_a_campaign_condition_and_supported_type(tmp_path,kind,campaign):
    ledger,*_=settled_pair(tmp_path,'net_of_retained_gains',winner=False)
    incoming(ledger,kind=kind,campaign=campaign,missing=False)
    row=CapitalBook(ledger).figures()
    expected=0  # No retained complete earning-period order history.
    assert row['proven_campaign_profit_cumulative_native']==expected
    assert row['proven_campaign_paid_incentives_native']==expected


def test_same_second_reward_does_not_prove_it_followed_the_first_quote(tmp_path):
    ledger,*_=settled_pair(tmp_path,'net_of_retained_gains',winner=False)
    incoming(ledger,campaign=True,nonce=0,missing=False)
    assert CapitalBook(ledger).figures()['retained_gains_available_native']==0


def test_unbounded_incoming_remains_unknown_without_erasing_proven_remainder(tmp_path):
    ledger,*_=settled_pair(tmp_path,'net_of_retained_gains')
    source=activity(cash=None,size='0',kind='REWARD',tx='0x'+'d'*64)
    proof={'transaction_hash':source['transaction_hash'],'rows':[source],
        'rows_sha256':digest([source]),'receipt':rpc_packet(None),'failure_type':None}
    record_activity(ledger,source,native_evidence=proof)
    row=CapitalBook(ledger).figures()
    assert row['retained_gains_available_native']==10_400_000
    assert row['unknown_cash_held_native'] is None and row['unknown_cash_unbounded_count']==1
    assert row['unknown_cash_bounded_native']==0 and row['unknown_payouts']


@pytest.mark.parametrize('basis',BASES)
def test_withdrawn_paid_reward_cannot_be_replaced_by_owner_deposit(tmp_path,basis):
    ledger,*_=settled_pair(tmp_path,basis,winner=False)
    incoming(ledger,campaign=True,missing=False)
    incoming(ledger,kind='WITHDRAWAL',missing=False,nonce=72)
    incoming(ledger,kind='DEPOSIT',amount='20',missing=False,nonce=73)
    for view in (ledger,Ledger.open(ledger.path,clock=ledger.clock)):
        book=CapitalBook(view);row=book.figures()
        assert row['proven_campaign_profit_cumulative_native']==0
        assert row['retained_gains_available_native']==0
        assert row['headroom_native']==290_400_000
        assert 'reward_attribution_unproven' in row['retained_gains_reason_codes']
        with pytest.raises(CapitalRefused,match='capital_total_ceiling'):
            book.gate(reserve='290.400001',available_cash='1000')


def test_local_status_reports_amount_local_quarantine_and_reduction_reasons(tmp_path,monkeypatch,capsys):
    import json
    from contextlib import nullcontext
    from weather.market import lfc_campaign_cli as cli
    from weather.market.lfc_campaign_control import control_record
    from weather.market.lfc_f2_breadth import example_policy
    ledger,state,*_=settled_pair(tmp_path,'net_of_retained_gains')
    incoming(ledger)
    path=tmp_path/'campaign.json';path.write_text(json.dumps(example_policy()))
    monkeypatch.setattr(cli,'load_release',lambda *a:{'campaign_path':str(path),'maker_address':MAKER,
        'state_id':ledger.enrollment['state_id'],'ledger_genesis_sha256':ledger.row_sha256(0)})
    monkeypatch.setattr(cli,'validate_release',lambda *a:None)
    monkeypatch.setattr(cli,'bound_state',lambda *a,**kw:(ledger.path.parent,state))
    # The autouse fixture already owns the synthetic account mutex.
    monkeypatch.setattr(cli,'account_lease',lambda maker:nullcontext())
    monkeypatch.setattr(cli,'CONTROL_ROOT',tmp_path/'control')
    monkeypatch.setattr(cli,'pilot_root',lambda:ledger.path.parent)
    monkeypatch.setattr(cli,'DEFAULT_STATE_ROOT',state.root.parent)
    from weather.market import lfc_campaign_guard as guard
    from datetime import datetime,timezone
    monkeypatch.setattr(guard,'account_lease_busy',lambda maker:False)
    control_record(tmp_path/'control','a'*32,phase='COMPLETE',now=datetime.now(timezone.utc))
    result=cli.main(['status','--release','fixture','--release-sha256','a'*64])
    output=capsys.readouterr().out
    assert result==0, output
    capital=json.loads(output.splitlines()[-1])['capital']
    assert capital['retained_gains_available_native']==10_400_000
    assert capital['unknown_cash_held_native']==5_000_000
    assert 'unknown_incoming_excluded' in capital['retained_gains_reason_codes']
