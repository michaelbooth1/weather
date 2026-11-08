"""Guards: B063 OwnerVenue cannot sign or POST without its before_post hook.

The SDK surface is inert; no signer, key, network or venue is constructed.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from weather.market.re1_transport import OwnerVenue


def fixture():
    calls=[]
    venue=object.__new__(OwnerVenue)
    venue.readonly=False; venue.maker='0x'+'a'*40
    venue.size=Decimal(20); venue.tokens=('yes','no'); venue.condition='condition'
    venue.fields={'SIGNATURE_TYPE':'3'}
    request={'token_id':'yes','side':'BUY','price':'.33','size':'20','expiration':1800000000,'post_only':True}
    def signed(**fields):
        calls.append('synthetic_signed_shape')
        return SimpleNamespace(maker=venue.maker,signer=venue.maker,signature_type=3,token_id='yes',side='BUY',
            order_type='GTD',post_only=True,expiration=request['expiration'],taker_amount=20000000,maker_amount=6600000)
    def book(**fields):
        calls.append('book');return {'token_id':'yes','market':'condition','asks':[{'price':'.6'}]}
    def post(value):
        calls.append('inert_POST');return {'ok':True,'order_id':'inert-order'}
    venue.client=SimpleNamespace(create_limit_order=signed,get_order_book=book,post_order=post)
    return venue,request,calls


@pytest.mark.parametrize('hook', ['missing',None,'not-callable'])
def test_owner_transport_refuses_absent_or_noncallable_post_hook(hook):
    venue,request,calls=fixture()
    if hook!='missing': venue.before_post=hook
    with pytest.raises(RuntimeError,match='before_post_required'):
        venue.submit(request,checkpoint=lambda:None)
    assert calls==[]


def test_valid_hook_runs_after_fresh_book_and_before_the_only_inert_post():
    venue,request,calls=fixture()
    venue.before_post=lambda value:calls.append('durable_hook')
    row=venue.submit(request,checkpoint=lambda:calls.append('checkpoint'))
    assert row['order_id']=='inert-order'
    assert calls==['synthetic_signed_shape','checkpoint','book','durable_hook','inert_POST']


def test_hook_refusal_never_reaches_the_post():
    venue,request,calls=fixture()
    def refuse(value): raise RuntimeError('fixture_intent_refusal')
    venue.before_post=refuse
    with pytest.raises(RuntimeError,match='fixture_intent_refusal'):
        venue.submit(request,checkpoint=lambda:None)
    assert 'inert_POST' not in calls
