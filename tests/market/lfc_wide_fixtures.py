"""Guards: T114 deterministic inert controller witnesses without live inputs."""
from decimal import Decimal

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_f2_repost import fixture, wire_trade
from tests.market.test_lfc_pair_integration import journal


def policy_row(mode='continue', **extra):
    return pinb_row() | {'enabled': False, 'policy_revision': 6, 'post_fill_mode': mode} | extra


def controller_fixture(tmp_path, row, *, seconds=600):
    result = fixture(tmp_path, policy_row=row, seconds=seconds)
    controller, account, _, _, clock, _, _ = result
    for raw in account.raws:
        raw.trades = lambda raw=raw: [wire_trade(order, raw.memory.condition) |
            {'matched_at': clock.base.isoformat()} for order in raw.memory.orders.values()
            if Decimal(order['size_matched'])]
    return result


def trace(controller, account):
    result = controller.run()
    return {'reason': result['reason'], 'fills': account.fill_times,
        'bands': [(band.submits, band.requotes, band.TRADE_LEGS,
                   [row['event'] for row in journal(band)]) for band in controller.bands],
        'orders': [[(row['asset_id'], row['price'], row['size_matched'], row['status'])
                    for row in raw.memory.orders.values()] for raw in account.raws]}


def only_first_fill(account):
    ordinary = account.advance
    def advance():
        if account.fill_times:
            account.fills_enabled = False
        ordinary()
    account.advance = advance


def replace_book(snapshot, bid, ask):
    from copy import deepcopy
    result = deepcopy(snapshot)
    for side, price in [('yes_bids', bid), ('yes_asks', ask),
                        ('no_bids', 1-Decimal(ask)), ('no_asks', 1-Decimal(bid))]:
        result['quote_inputs'][side] = [{'price': str(price), 'size': '100'}]
    return result
