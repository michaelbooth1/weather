"""Guards: T114 actual guarded W/B+W posting, reward boundary, caps and requotes."""
from decimal import Decimal as D

import pytest

from tests.market.lfc_wide_fixtures import controller_fixture, only_first_fill, policy_row, replace_book
from tests.market.test_lfc_pair_integration import journal
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_wide_policy import successor_row


def wide_fixture(tmp_path, mode='continue'):
    row = successor_row(policy_row(mode), post_fill_mode=mode, quote_offset_mode='wide')
    row['learning_leg_arms'] = ['paired']
    return controller_fixture(tmp_path, row)


def test_new_entry_at_four_point_five_waits_then_posts_full_size_after_sixty_seconds(tmp_path):
    controller, account, _, ledger, clock, *_ = wide_fixture(tmp_path)
    account.fills_enabled = False
    raw = account.raws[0]; ordinary = raw.snapshot
    raw.snapshot = lambda *a, **k: replace_book(ordinary(*a, **k), '.35', '.36')
    result = controller.run()
    band = controller.bands[0]; rows = journal(band)
    assert result['cleanup_ok'] and not ledger.unresolved_legs(), result
    assert any(row['event'] == 'wide_quote_paused' for row in rows)
    orders = [row for row in rows if row['event'] == 'quote_scoring_order']
    assert orders and all(D(row['size']) == 20 and D(row['scoring_distance_cents']) < D('4.5') for row in orders)
    from datetime import datetime
    delay = (datetime.fromisoformat(orders[0]['recorded_at_utc'])-band.start).total_seconds()
    assert 60 <= delay <= 62 and band.submits == 2


def test_b_plus_w_posts_the_cost_capped_complement_at_zero_score_and_proves_money(tmp_path):
    controller, account, status, ledger, clock, *_ = wide_fixture(tmp_path, 'complete_pairs')
    only_first_fill(account)
    raw = account.raws[0]; ordinary = raw.snapshot
    def snapshot(*args, **kwargs):
        value = ordinary(*args, **kwargs)
        return replace_book(value, '.19', '.21') if clock.seconds >= 20 else value
    raw.snapshot = snapshot
    result = controller.run()
    band = controller.bands[0]; rows = journal(band)
    assert result['cleanup_ok'] and not ledger.unresolved_legs(), result
    scores = [r for r in rows if r['event'] == 'quote_scoring_order' and r['completion']]
    assert scores and all(r['native_leg_reward_score'] == 0 for r in scores)
    assert all(D(r['price']) == D('.67') and r['leg'] == 1 and r['quote_offset_mode'] == 'wide' for r in scores)
    assert all(D(r['scoring_distance_cents']) == 13 for r in scores)
    assert all(D(r['quote_offset_cents']) == 3 and r['offset_assignment_source'] == 'policy' for r in scores)
    proposals = [r for r in rows if r['event'] == 'pair_completion_quote']
    assert any(D(r['uncapped_completion_price']) == D('.77') and
               D(r['completion_pair_cap']) == D('.675') and D(r['capped_completion_price']) == D('.67')
               for r in proposals)
    assert band.requotes == 0 and band.pair_state.u == 20
    from weather.market.lfc_campaign_proof import local_money_proof
    proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id='a'*32, outcome=status.finish(success=True))
    assert proof['complete'] and not proof['unknown_submit']


def test_b_plus_w_resting_complement_leaves_inside_band_and_reprices_outside(tmp_path):
    controller, account, _, ledger, clock, *_ = wide_fixture(tmp_path, 'complete_pairs')
    only_first_fill(account)
    raw = account.raws[0]; ordinary = raw.snapshot
    def snapshot(*args, **kwargs):
        value = ordinary(*args, **kwargs)
        if clock.seconds >= 200:
            return replace_book(value, '.32', '.34')
        return replace_book(value, '.33', '.35') if clock.seconds >= 100 else value
    raw.snapshot = snapshot
    result = controller.run()
    band = controller.bands[0]
    assert result['cleanup_ok'] and not ledger.unresolved_legs(), result
    prices = [D(r['price']) for r in journal(band) if r['event'] == 'quote_scoring_order' and r['completion']]
    assert prices == [D('.62'), D('.64')] and band.requotes == 1


@pytest.mark.parametrize('mode', ['continue', 'complete_pairs'])
def test_wide_preserves_the_full_size_money_and_attempt_rails(tmp_path, mode):
    controller, account, _, ledger, *_ = wide_fixture(tmp_path, mode)
    result = controller.run()
    assert result['cleanup_ok'] and not ledger.unresolved_legs(), result
    assert CapitalBook(ledger).figures()['charged_native'] <= 300_000_000
    for band in controller.bands:
        assert band.size == 20 and band.MAX_SUBMITS == 40 and band.MAX_REQUOTES == 16
        assert band.order_cap == D('15.80') and band.band_cap <= D('19.60')
        orders = [row for row in ledger.legs.values() if row['session_id'] == band.session_id]
        assert all(D(row['size']) == 20 and D(row['price'])*20 <= D('15.80') for row in orders)
        assert sum(D(row['price'])*D(row['size_matched']) for row in orders) <= 30
        assert band.campaign_policy.raw['fill_cooldown_seconds'] == 60
