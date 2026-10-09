"""Descriptive live-fill analysis on synthetic November 2026 fixtures only.

Guards: c_at/c_thr attribution, queue-ahead buckets, markouts and f_hat arithmetic, and the refusal of any input
dated inside the reserved 2026-09-30..2026-10-15 window unless the explicit override is given.
"""
from decimal import Decimal

import pytest

from weather.market.lfc_analysis import ReservedDateRefused, analyze, check_dates, main


def T(minute, second=0):
    return f'2026-11-03T12:{minute:02d}:{second:02d}+00:00'


LEG = {'order_id': 'o1', 'token_id': '111', 'condition_id': '0xc', 'price': '.40', 'size': '40',
       'placed_at_utc': T(0), 'ended_at_utc': T(59), 'fills': [{'at_utc': T(10, 30), 'size': '10'}],
       'queue_ahead': [{'at_utc': T(0), 'visible_at_price': '140', 'own_size': '40', 'phase': 'placement'},
                       {'at_utc': T(5), 'visible_at_price': '100', 'own_size': '40', 'phase': 'book_update'}]}
PRINTS = [{'token_id': '111', 'price': '.40', 'size': '20', 'at_utc': T(10)},   # at price, we got 10 of 20
          {'token_id': '111', 'price': '.40', 'size': '50', 'at_utc': T(20)},   # at price, nothing for us
          {'token_id': '111', 'price': '.39', 'size': '5', 'at_utc': T(30)},    # strictly through
          {'token_id': '111', 'price': '.41', 'size': '9', 'at_utc': T(31)},    # above our bid: ignored
          {'token_id': '222', 'price': '.40', 'size': '9', 'at_utc': T(32)}]    # other token: ignored
MIDS = [{'token_id': '111', 'at_utc': T(11, 30), 'mid': '.41'}, {'token_id': '111', 'at_utc': T(40, 30), 'mid': '.35'}]


def test_rates_markouts_and_f_hat():
    result = analyze([LEG], PRINTS, MIDS, {'0xc': '222'})
    assert result['N_at'] == 2 and result['N_thr'] == 1
    assert Decimal(result['c_at']) == Decimal(10) / Decimal(50)  # 10 / (min(20,40) + min(50,30))
    assert Decimal(result['c_thr']) == 0
    assert result['c_at_by_queue_ahead']['50.000001-200']['N_at'] == 2
    markout = result['markouts'][0]
    assert Decimal(markout['markout_60s']) == Decimal('.01') and markout['markout_300s'] is None
    assert Decimal(markout['markout_1800s']) == Decimal('-.05') and Decimal(markout['markout_settlement']) == Decimal('-.40')
    assert Decimal(result['f_hat']) == 1 and result['descriptive_only'] is True


def test_reserved_dates_refused_without_override():
    reserved = dict(PRINTS[0], at_utc='2026-10-15T23:59:59+00:00')
    with pytest.raises(ReservedDateRefused):
        analyze([LEG], [reserved], MIDS, {})
    assert analyze([LEG], [reserved], MIDS, {}, allow_reserved=True)['reserved_dates_included'] == ['2026-10-15']
    assert check_dates(['2026-09-29T23:59:59+00:00', '2026-10-16T00:00:00+00:00']) == []
    with pytest.raises(ReservedDateRefused):
        check_dates(['2026-09-30T00:00:00+00:00'])


def test_cli_refuses_reserved_inputs(tmp_path):
    import json
    for name, rows in (('legs', [LEG]), ('prints', [dict(PRINTS[0], at_utc='2026-10-01T00:00:00+00:00')]),
                       ('mids', MIDS)):
        (tmp_path / f'{name}.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (tmp_path / 'settlement.json').write_text('{}')
    args = [f'--{n}={tmp_path / (n + ".jsonl")}' for n in ('legs', 'prints', 'mids')]
    args += [f'--settlement={tmp_path / "settlement.json"}', f'--output={tmp_path / "out.json"}']
    with pytest.raises(ReservedDateRefused):
        main(args)
    assert not (tmp_path / 'out.json').exists()
    assert main(args + ['--allow-reserved-dates']) == 0
