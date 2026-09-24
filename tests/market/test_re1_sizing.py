"""84h wallet sizing and exact confirmation, entirely synthetic and offline."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.market.stage2_fakes import Clock, Venue, CONDITION, TOKENS
from tests.market.test_re1_attended_parity_audit import reference_evaluate
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import digest
from weather.market.mm_stage2_selection import select_table, validate_selection, PublicBooks
from weather.market.re1_attended import Session, SecretGuard, HoldEnd, observe
from weather.market.re1_attended_cli import confirmation, parser
from weather.market.re1_evidence import load_prediction
from weather.market.re1_rehearsal import RehearsalVenue
from weather.market.re1_sizing import sized_quote, session_caps
from weather.market.reward_quote import QuoteRefused, price_reward_quote, price_sized_reward_quote


def band(now=None, *, day='2026-09-22', minimum='20'):
    snapshot = Venue(Clock()).snapshot()
    if now is not None:
        snapshot['observed_at_utc'] = now.isoformat()
    snapshot['quote_inputs'].update(reward_rate_per_day='100', reward_min_size=minimum)
    return dict(market_id='los-angeles', market_timezone=REGISTRY['los-angeles'].timezone,
                target_date=day, condition_id=CONDITION, token_ids=list(TOKENS), snapshot=snapshot)


def table(wallet='97', **kwargs):
    return select_table([band(**kwargs)], now=kwargs.get('now') or Clock().now(), available_collateral=wallet)


@pytest.mark.parametrize('wallet,size', [('200', 75), ('150', 75), ('97', 75), ('60', 50), ('40', 30), ('30', 20),
                                         ('25', None)])
def test_largest_affordable_size(wallet, size):
    result = table(wallet)
    row = result['rows'][0]
    if size is None:
        assert result['selected_condition_id'] is None
        assert row['refusal'] == 'insufficient_size_reserve'
        return
    quote = row['quote']
    assert Decimal(quote['size']) == size
    assert Decimal(quote['reserve_pusd']) == size * (Decimal(quote['yes_buy']) + Decimal(quote['no_buy']))
    assert Decimal(quote['reserve_pusd']) <= min(Decimal(wallet) - 10, 75)
    assert result['selected_condition_id'] == CONDITION
    validate_selection(result, expected_sha256=digest(result), condition_id=CONDITION, token_ids=TOKENS,
                       now=Clock().now(), allow_sized=True)


@pytest.mark.parametrize('wallet', ['200.000001', '201', '-1', 'NaN', 'Infinity', True])
def test_invalid_wallet_refused(wallet):
    with pytest.raises(QuoteRefused):
        table(wallet)


@pytest.mark.parametrize('offset', [-1, 0, 1, 2, 3])
@pytest.mark.parametrize('minimum', ['20', '30', '75', '100'])
def test_local_dates_and_reward_minimum(offset, minimum):
    # 01:00Z on Sep 23 is still Sep 22 at the configured Los Angeles event.
    now = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    day = (datetime(2026, 9, 22) + timedelta(days=offset)).date().isoformat()
    result = table(now=now, day=day, minimum=minimum)
    assert (result['selected_condition_id'] is not None) == (0 <= offset <= 2 and int(minimum) <= 75)


def test_minimum_exceeding_affordable_size_refuses():
    result = table('40', minimum='50')
    assert result['selected_condition_id'] is None
    assert result['rows'][0]['refusal'] == 'reward_minimum_outside_treatment'


@pytest.mark.parametrize('wallet', ['97', '60', '40', '30'])
def test_chosen_size_prediction_and_held_minute_match_canonical_and_reference(wallet):
    row = table(wallet)['rows'][0]
    quote = row['quote']
    values = row['snapshot']['quote_inputs']
    size = Decimal(quote['size'])
    canonical = price_sized_reward_quote(**values, size=size,
        per_order_ceiling=Decimal('.8') * size, per_band_ceiling=size)
    assert row['predicted_360_minutes'] == canonical.predicted_per_minute_many * 360
    own = {'yesBid': float(quote['yes_buy']), 'yesAsk': 1 - float(quote['no_buy']), 'size': int(size)}
    reference = reference_evaluate(row['snapshot'], size=int(size))
    assert canonical.share_many == pytest.approx(reference['share_many'])
    own['resting'] = True
    held = observe(row['snapshot'], [quote['yes_buy'], quote['no_buy']], size)
    reference = reference_evaluate(row['snapshot'], own)
    assert held['share_many'] == pytest.approx(reference['share_many'])


@pytest.mark.parametrize('change', ['size', 'reserve', 'wallet'])
def test_confirmation_digest_binds_size_reserve_wallet(monkeypatch, change):
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    original = table()
    phrase = 'go ' + digest(original)[:6]
    printed = []
    guard = SimpleNamespace(print=printed.append)
    assert confirmation(original, guard, reader=lambda: phrase)['text'] == phrase
    assert confirmation(original, guard, reader=lambda: '  GO   ' + digest(original)[:6].upper() + ' ')['text'] == phrase
    with pytest.raises(RuntimeError, match='confirmation_refused'):
        confirmation(original, guard, reader=lambda: 'go ' + digest(original)[:5])
    assert printed[0]['size'] == '75'
    assert printed[0]['reserve_pusd'] == original['rows'][0]['quote']['reserve_pusd']
    assert printed[0]['available_collateral'] == '97'
    changed = deepcopy(original)
    if change == 'wallet': changed['available_collateral'] = '96'
    else: changed['rows'][0]['quote']['size' if change == 'size' else 'reserve_pusd'] = '50'
    with pytest.raises(RuntimeError, match='confirmation_refused'):
        confirmation(changed, guard, reader=lambda: phrase)
    if change != 'wallet':
        with pytest.raises(ValueError, match='ranking'):
            validate_selection(changed, expected_sha256=digest(changed), condition_id=CONDITION,
                               token_ids=TOKENS, now=Clock().now(), allow_sized=True)


@pytest.mark.parametrize('size', [0, 19, 21, 76, 100, 'NaN'])
def test_no_larger_or_unregistered_size(size):
    with pytest.raises(QuoteRefused): session_caps(size, 97)
    with pytest.raises(QuoteRefused):
        price_sized_reward_quote(**band()['snapshot']['quote_inputs'], size=size)


def test_sealed_proposer_and_cli_cannot_widen_size():
    selection = table()
    with pytest.raises(ValueError, match='attended RE-1 only'):
        validate_selection(selection, expected_sha256=digest(selection), condition_id=CONDITION,
                           token_ids=TOKENS, now=Clock().now())
    with pytest.raises(TypeError):
        price_reward_quote(**band()['snapshot']['quote_inputs'], size=75)
    for flag in ('--size', '--reserve', '--wallet', '--per-band-ceiling'):
        with pytest.raises(SystemExit): parser().parse_args(['live', flag, '100'])
    with pytest.raises(QuoteRefused, match='capital_ceiling'):
        price_sized_reward_quote(**band()['snapshot']['quote_inputs'], size=75, per_band_ceiling=76)


def session_fixture(tmp_path, wallet='97'):
    clock = Clock()
    selection = table(wallet)
    venue = RehearsalVenue(selection['rows'][0]['snapshot'], tmp_path, clock=clock)
    venue.balances = lambda: {'available_collateral': wallet}
    session = Session(venue=venue, public=venue, table=selection, clock=clock, directory=tmp_path)
    return session, venue, clock


@pytest.mark.parametrize('wallet,size', [('97', 75), ('60', 50), ('40', 30), ('30', 20)])
def test_session_orders_and_prediction_replay_keep_size(tmp_path, wallet, size):
    session, venue, clock = session_fixture(tmp_path, wallet)
    result = session.run(rehearsal_seconds=120)
    assert result['submits'] == 2 and result['cleanup_ok']
    assert {Decimal(r['size']) for r in venue.calls} == {size}
    assert result['scope']['size'] == str(size)
    replayed = load_prediction(tmp_path / 'prediction.json', now=clock.now() + timedelta(days=1))
    assert replayed['P_many'] == result['P_many']


def test_wallet_drop_after_confirmation_stops_before_submit(tmp_path):
    session, venue, _ = session_fixture(tmp_path)
    venue.balances = lambda: {'available_collateral': '60'}
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'available_collateral' and not venue.calls


def test_session_size_and_reserve_caps_at_submit(tmp_path):
    session, venue, _ = session_fixture(tmp_path)
    with pytest.raises(HoldEnd): session.submit(0, session.prices[0], size=100)
    session.prices = [Decimal('.79'), Decimal('.22')]
    with pytest.raises(HoldEnd, match='capital_cap'): session.submit(0, session.prices[0])
    assert not venue.calls
    session.journal.close()


def test_live_session_needs_the_sized_table_phrase(tmp_path):
    selection = table()
    clock = Clock()
    venue = RehearsalVenue(selection['rows'][0]['snapshot'], tmp_path, clock=clock)
    with pytest.raises(RuntimeError, match='confirmation'):
        Session(venue=venue, public=venue, table=selection, clock=clock, directory=tmp_path,
                mode='live', confirmation={'text': 'wrong'})


def test_public_selection_enumerates_three_local_dates(monkeypatch):
    from weather.market import mm_stage2_selection as selection
    monkeypatch.setattr(selection, 'REGISTRY', {'los-angeles': REGISTRY['los-angeles']})
    now = datetime(2026, 9, 23, 1, tzinfo=timezone.utc)
    public = PublicBooks(clock=lambda: now)
    requests = []
    def get(url):
        requests.append(url)
        return {'slug': url.rsplit('/', 1)[1], 'markets': []}
    public.get = get
    result = public.selection(available_collateral='97')
    assert len(requests) == 3
    assert all(f'september-{day}-2026' in url for day, url in zip((22, 23, 24), requests))
    assert result['size_treatment'] == 'RE-1-84h'
